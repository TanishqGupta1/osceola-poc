"""Layout-fingerprint classifier.

Maps Textract block-type counts (from a combined-feature AnalyzeDocument response)
to one of the 7 Osceola page classes. Deterministic. No keyword matching against
text; the OCR text is allowed to be noisy.
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


def _counts(resp: dict[str, Any]) -> dict[str, int]:
    blocks = resp.get("Blocks", []) or []
    return dict(Counter(b.get("BlockType", "") for b in blocks))


def classify(resp: dict[str, Any]) -> tuple[str, float, dict[str, int]]:
    """Return (page_class, confidence_0_to_1, fingerprint).

    Decision rules — in priority order:
      1. >=1 TABLE + >=20 CELLs        -> student_records_index
      2. >=1 SIGNATURE + >=3 KV keys + LINE count 20-40  -> roll_separator (Style B cert)
      3. LINE count <25 + 0 TABLE + 0 SIGNATURE         -> roll_separator (Style A clapper)
      4. >=10 KV keys + LINE count >=80                  -> student_cover
      5. LINE count between 25 and 80                    -> roll_leader
      6. otherwise                                       -> unknown
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

    if n_tables >= 1 and n_cells >= 20:
        return "student_records_index", 0.95, fp

    if n_signatures >= 1 and n_kv_keys >= 3 and 20 <= n_lines <= 40:
        return "roll_separator", 0.90, fp

    if n_lines < 25 and n_tables == 0 and n_signatures == 0:
        return "roll_separator", 0.85, fp

    if n_kv_keys >= 10 and n_lines >= 80:
        return "student_cover", 0.85, fp

    if 25 <= n_lines <= 80 and n_kv_keys < 10:
        return "roll_leader", 0.70, fp

    return "unknown", 0.30, fp
