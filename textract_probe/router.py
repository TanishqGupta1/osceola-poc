"""Two-pass cost-aware router.

Pass 1 (cheap): Detect on every page, classify via layout-fingerprint rules.
Pass 2 (selective): per-class feature call.

| page_class            | Pass 2 features  | Pass 2 cost |
|-----------------------|------------------|-------------|
| student_cover         | analyze_all      | $0.0885     |
| student_records_index | analyze_tables   | $0.0150     |
| roll_separator        | (Pass 1 only)    | $0          |
| roll_leader           | (Pass 1 only)    | $0          |
| student_test_sheet    | (Pass 1 only)    | $0          |
| student_continuation  | (Pass 1 only)    | $0          |
| unknown               | analyze_all      | $0.0885     |
"""
from __future__ import annotations

from typing import Any

from textract_probe import client as tc
from textract_probe import layout_classifier as lc


def process_page(
    png_bytes: bytes,
    *,
    queries: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run two-pass extraction. Returns dict with class + spend + raw responses."""
    detect_resp, detect_cost = tc.detect_document_text(png_bytes)
    page_class, conf, fp = lc.classify(detect_resp)

    spend = detect_cost
    pass2_resp: dict[str, Any] | None = None

    if page_class == "student_cover" or page_class == "unknown":
        pass2_resp, c = tc.analyze_all(
            png_bytes,
            queries=queries,
            include_signatures=True,
        )
        spend += c
    elif page_class == "student_records_index":
        pass2_resp, c = tc.analyze_tables(png_bytes)
        spend += c

    return {
        "page_class": page_class,
        "classifier_confidence": conf,
        "fingerprint": fp,
        "detect_response": detect_resp,
        "pass2_response": pass2_resp,
        "spend_usd": round(spend, 6),
    }
