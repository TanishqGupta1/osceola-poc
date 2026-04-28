"""boto3 Textract endpoint wrappers.

Each function returns (raw_response, usd_cost). Retries on Throttling /
ServiceUnavailable / InternalServerError. All other ClientErrors raised.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from botocore.exceptions import ClientError

from textract_probe import env

# AWS Textract pricing in us-west-2 as of 2026-04, per-page USD.
# Source: https://aws.amazon.com/textract/pricing/
TEXTRACT_PRICING_USD: dict[str, float] = {
    "detect":     0.0015,
    "forms":      0.05,
    "tables":     0.015,
    "layout":     0.004,
    "queries":    0.015,
    "signatures": 0.004,
}

RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ProvisionedThroughputExceededException",
    "InternalServerError",
    "ServiceUnavailable",
}


def compute_textract_cost(feature: str, pages: int = 1) -> float:
    return TEXTRACT_PRICING_USD[feature] * pages


def _call_with_retry(
    fn: Callable[[], Any],
    *,
    max_retries: int,
    retry_base_delay: float,
    op_name: str,
) -> Any:
    delay = retry_base_delay
    last_err: Exception | None = None
    for _attempt in range(max_retries):
        try:
            return fn()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in RETRYABLE_ERROR_CODES:
                last_err = e
                if delay > 0:
                    time.sleep(delay)
                delay = max(delay * 2, retry_base_delay)
                continue
            raise
    raise RuntimeError(f"{op_name}: exhausted retries: {last_err!r}")


def detect_document_text(
    png_bytes: bytes,
    *,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], float]:
    client = env.textract_client()
    resp = _call_with_retry(
        lambda: client.detect_document_text(Document={"Bytes": png_bytes}),
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        op_name="detect_document_text",
    )
    return resp, compute_textract_cost("detect", 1)


def _analyze(
    png_bytes: bytes,
    *,
    feature_types: list[str],
    feature_pricing_key: str,
    extra_kwargs: dict[str, Any] | None = None,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
    op_name: str = "analyze_document",
) -> tuple[dict[str, Any], float]:
    client = env.textract_client()
    kwargs: dict[str, Any] = {
        "Document": {"Bytes": png_bytes},
        "FeatureTypes": feature_types,
    }
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    resp = _call_with_retry(
        lambda: client.analyze_document(**kwargs),
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        op_name=op_name,
    )
    return resp, compute_textract_cost(feature_pricing_key, 1)


def analyze_forms(png_bytes: bytes, **kwargs) -> tuple[dict[str, Any], float]:
    return _analyze(
        png_bytes,
        feature_types=["FORMS"],
        feature_pricing_key="forms",
        op_name="analyze_forms",
        **kwargs,
    )


def analyze_tables(png_bytes: bytes, **kwargs) -> tuple[dict[str, Any], float]:
    return _analyze(
        png_bytes,
        feature_types=["TABLES"],
        feature_pricing_key="tables",
        op_name="analyze_tables",
        **kwargs,
    )


def analyze_layout(png_bytes: bytes, **kwargs) -> tuple[dict[str, Any], float]:
    return _analyze(
        png_bytes,
        feature_types=["LAYOUT"],
        feature_pricing_key="layout",
        op_name="analyze_layout",
        **kwargs,
    )


def analyze_queries(
    png_bytes: bytes,
    *,
    queries: list[dict[str, str]],
    **kwargs,
) -> tuple[dict[str, Any], float]:
    if not queries:
        raise ValueError("analyze_queries requires at least one query")
    return _analyze(
        png_bytes,
        feature_types=["QUERIES"],
        feature_pricing_key="queries",
        extra_kwargs={"QueriesConfig": {"Queries": queries}},
        op_name="analyze_queries",
        **kwargs,
    )


def analyze_all(
    png_bytes: bytes,
    *,
    queries: list[dict[str, str]] | None = None,
    include_signatures: bool = True,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], float]:
    """One-shot AnalyzeDocument call combining FORMS+TABLES+LAYOUT (+QUERIES, +SIGNATURES).

    Same per-feature pricing as separate calls, single API roundtrip. Returns
    (raw_response, total_usd_cost).
    """
    feature_types: list[str] = ["FORMS", "TABLES", "LAYOUT"]
    cost_keys: list[str] = ["forms", "tables", "layout"]
    extra_kwargs: dict[str, Any] = {}

    if queries:
        feature_types.append("QUERIES")
        cost_keys.append("queries")
        extra_kwargs["QueriesConfig"] = {"Queries": queries}
    if include_signatures:
        feature_types.append("SIGNATURES")
        cost_keys.append("signatures")

    client = env.textract_client()
    kwargs: dict[str, Any] = {
        "Document": {"Bytes": png_bytes},
        "FeatureTypes": feature_types,
    }
    kwargs.update(extra_kwargs)
    resp = _call_with_retry(
        lambda: client.analyze_document(**kwargs),
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        op_name="analyze_all",
    )
    total_cost = sum(compute_textract_cost(k, 1) for k in cost_keys)
    return resp, total_cost
