"""Layout-fingerprint classifier.

Maps Textract block-type counts (from a combined-feature AnalyzeDocument
response) OR a Detect-only response to one of the 7 Osceola page classes.
Deterministic. Uses block counts when available (combined call), falls back
to text-keyword patterns when only Detect LINEs exist (Pass 1 of router).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

PAGE_CLASSES = (
    "student_cover",
    "student_test_sheet",
    "student_continuation",
    "student_records_index",
    "roll_separator",
    "roll_leader",
    "unknown",
)

# Text patterns scanned in Detect-only mode (UPPERCASED full-page text).
INDEX_PATTERNS = ("STUDENT RECORDS INDEX",)
CERT_PATTERNS = ("CERTIFICATE OF AUTHENTICITY", "CERTIFICATE OF RECORD")
CLAPPER_PATTERNS = ("OSCEOLA COUNTY", "RECORDS DEPARTMENT", "1887")
COVER_LABEL_PATTERNS = (
    "1. NAME",
    "STUDENT NAME",
    "DATE OF BIRTH",
    "PLACE OF BIRTH",
    "BIRTHDATE",
    "BIRTHPLACE",
    "SCHOOL DISTRICT OF",
    "PUPIL LIVES",
    "MOTHER",
    "FATHER",
    "GUARDIAN",
)
TEST_SHEET_PATTERNS = (
    "STATEWIDE",
    "ASSESSMENT PROGRAM",
    "STUDENT REPORT",
    "SSAT",
    "STANFORD",
    "ACHIEVEMENT TEST",
)


def _counts(resp: dict[str, Any]) -> dict[str, int]:
    blocks = resp.get("Blocks", []) or []
    return dict(Counter(b.get("BlockType", "") for b in blocks))


def _full_text_upper(resp: dict[str, Any]) -> str:
    return " ".join(
        (b.get("Text") or "")
        for b in resp.get("Blocks", []) or []
        if b.get("BlockType") == "LINE"
    ).upper()


def classify(resp: dict[str, Any]) -> tuple[str, float, dict[str, int]]:
    """Return (page_class, confidence_0_to_1, fingerprint).

    Block-rich rules fire first (combined-call response); text-pattern fallback
    fires for Detect-only responses.
    """
    fp = _counts(resp)
    n_lines      = fp.get("LINE", 0)
    n_tables     = fp.get("TABLE", 0)
    n_cells      = fp.get("CELL", 0)
    n_kv_keys    = sum(
        1 for b in resp.get("Blocks", [])
        if b.get("BlockType") == "KEY_VALUE_SET"
        and "KEY" in (b.get("EntityTypes") or [])
    )
    n_signatures = fp.get("SIGNATURE", 0)

    if n_lines == 0:
        return "unknown", 0.0, fp

    # Block-rich rules (combined-call AnalyzeDocument response)
    if n_tables >= 1 and n_cells >= 20:
        return "student_records_index", 0.95, fp

    if n_signatures >= 1 and n_kv_keys >= 3 and 20 <= n_lines <= 40:
        return "roll_separator", 0.90, fp

    if n_kv_keys >= 10 and n_lines >= 80:
        return "student_cover", 0.85, fp

    # Detect-only fallback — uses LINE text patterns instead of KV/Tables.
    text_u = _full_text_upper(resp)

    if any(p in text_u for p in INDEX_PATTERNS):
        return "student_records_index", 0.85, fp

    if any(p in text_u for p in CERT_PATTERNS):
        return "roll_separator", 0.85, fp

    if n_lines < 25 and n_tables == 0 and n_signatures == 0:
        return "roll_separator", 0.80, fp

    if any(p in text_u for p in TEST_SHEET_PATTERNS):
        return "student_test_sheet", 0.75, fp

    cover_hits = sum(1 for p in COVER_LABEL_PATTERNS if p in text_u)
    # Tightened: require >=3 cover-label hits OR >=2 hits with >=80 LINEs.
    # Earlier 2/40 threshold over-routed continuation pages -> needless analyze_all.
    if cover_hits >= 3 or (cover_hits >= 2 and n_lines >= 80):
        return "student_cover", 0.80, fp

    if 25 <= n_lines <= 80 and cover_hits < 2:
        return "roll_leader", 0.65, fp

    if n_lines >= 80 and cover_hits < 2:
        return "student_continuation", 0.60, fp

    return "unknown", 0.30, fp
