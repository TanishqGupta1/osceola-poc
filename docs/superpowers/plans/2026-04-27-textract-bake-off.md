# Textract Bake-Off + Tesseract Brainstorm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot bake-off harness that hits AWS Textract with all five features (DetectDocumentText, Forms, Tables, Layout, Queries) plus local Tesseract on a curated 8-fixture TIF set spanning the 7 Osceola page classes, then write a results doc that confirms or revises the cost/precision forecasts in `docs/no-llm-90pct-design.md`.

**Architecture:** **Fully isolated module `textract_probe/` — no edits to `poc/`, existing `tests/`, `scripts/`, `requirements.txt`, or `README.md`.** Self-contained: own env loader (reads same `.env.bedrock`), own TIF→PNG helper, own boto3 wrapper, own tests, own requirements file. Two driver scripts (`textract_probe/bake_off.py`, `textract_probe/tesseract_run.py`) iterate fixtures × features and dump raw JSON / TSV to `textract_probe/output/`. Smoke test gated on `TEXTRACT_SMOKE_TEST=1`. Only deliverable outside the module: `docs/2026-04-27-textract-bake-off-results.md`.

**Tech Stack:** Python 3.11+, boto3 (Textract via `.env.bedrock` tanishq AWS account, us-west-2), Pillow (already installed), pytesseract (new dep), pytest, `python-dotenv`. No new infra.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `poc/env.py` | modify | Add `textract_client()` factory using `.env.bedrock` |
| `poc/textract_client.py` | create | Five Textract endpoint wrappers + pricing + retry |
| `tests/test_textract_client.py` | create | Unit tests for cost, retry, endpoint dispatch (mocked boto3) |
| `tests/test_smoke_textract.py` | create | Live one-call smoke gated on `TEXTRACT_SMOKE_TEST=1` |
| `tests/fixtures_textract_baseline.json` | create | Manifest: 8 fixture TIFs spanning 7 page classes |
| `scripts/textract_queries.json` | create | 6 hand-crafted Textract Queries for student/separator pages |
| `scripts/textract_bake_off.py` | create | CLI: loops fixtures × features, dumps raw JSON, prints summary |
| `scripts/tesseract_run.py` | create | CLI: runs Tesseract raw + preprocessed on same fixtures |
| `requirements.txt` | modify | Append `pytesseract>=0.3.10` |
| `docs/2026-04-27-textract-bake-off-results.md` | create | Authored after bake-off runs; numbers + recommendation |
| `README.md`, `CLAUDE.md` | modify | One-line usage entries |

`samples/textract_responses/` and `samples/tesseract_responses/` will be populated by the bake-off; both are already covered by existing `samples/**` gitignore rule.

---

## Task 1: Add `textract_client()` factory to `poc/env.py`

**Files:**
- Modify: `poc/env.py`
- Test: `tests/test_textract_client.py` (created here, expanded later)

- [ ] **Step 1: Write failing test**

Create `tests/test_textract_client.py`:

```python
from poc import env


def test_textract_client_uses_bedrock_env(tmp_path):
    fake_env = tmp_path / ".env.bedrock"
    fake_env.write_text(
        "AWS_ACCESS_KEY_ID=AKIATEST\n"
        "AWS_SECRET_ACCESS_KEY=secrettest\n"
        "AWS_REGION=us-west-2\n"
    )
    client = env.textract_client(bedrock_path=fake_env)
    assert client.meta.service_model.service_name == "textract"
    assert client.meta.region_name == "us-west-2"
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_textract_client.py::test_textract_client_uses_bedrock_env -v
```

Expected: `AttributeError: module 'poc.env' has no attribute 'textract_client'`.

- [ ] **Step 3: Implement `textract_client()`**

Append to `poc/env.py` after the existing `bedrock_client()` definition:

```python
def textract_client(
    bedrock_path: Path | str = _DEFAULT_BEDROCK_ENV,
    region: str = DEFAULT_REGION,
) -> boto3.client:
    """Textract reuses the .env.bedrock IAM user (tanishq AWS acct)."""
    env = _load(Path(bedrock_path))
    return boto3.client(
        "textract",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", region),
    )
```

- [ ] **Step 4: Run test, verify pass**

```
pytest tests/test_textract_client.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/env.py tests/test_textract_client.py
git commit -m "feat(env): add textract_client factory reusing .env.bedrock"
```

---

## Task 2: Pricing constants + `compute_textract_cost`

**Files:**
- Create: `poc/textract_client.py`
- Test: `tests/test_textract_client.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_textract_client.py`:

```python
import pytest

from poc import textract_client as tc


@pytest.mark.parametrize("feature,pages,expected", [
    ("detect", 1, 0.0015),
    ("forms",  1, 0.05),
    ("tables", 1, 0.015),
    ("layout", 1, 0.004),
    ("queries", 1, 0.015),
    ("detect", 10, 0.015),
    ("forms",  3, 0.15),
])
def test_compute_textract_cost(feature, pages, expected):
    assert tc.compute_textract_cost(feature, pages) == pytest.approx(expected, rel=1e-9)


def test_compute_textract_cost_unknown_feature():
    with pytest.raises(KeyError):
        tc.compute_textract_cost("magic", 1)
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest tests/test_textract_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'poc.textract_client'`.

- [ ] **Step 3: Create `poc/textract_client.py` with constants + cost fn**

```python
"""Thin wrappers around boto3 Textract for the bake-off harness.

Each endpoint returns (raw_response_dict, usd_cost). Routes through
poc.env.textract_client() so the .env.bedrock IAM user is enforced.
"""
from __future__ import annotations

import time
from typing import Any

from botocore.exceptions import ClientError

from poc import env

# AWS Textract pricing in us-west-2 as of 2026-04, per-page USD.
# Source: https://aws.amazon.com/textract/pricing/
TEXTRACT_PRICING_USD: dict[str, float] = {
    "detect": 0.0015,   # DetectDocumentText
    "forms":  0.05,     # AnalyzeDocument FORMS
    "tables": 0.015,    # AnalyzeDocument TABLES
    "layout": 0.004,    # AnalyzeDocument LAYOUT
    "queries": 0.015,   # AnalyzeDocument QUERIES
}

RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ProvisionedThroughputExceededException",
    "InternalServerError",
    "ServiceUnavailable",
}


def compute_textract_cost(feature: str, pages: int = 1) -> float:
    return TEXTRACT_PRICING_USD[feature] * pages
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest tests/test_textract_client.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/textract_client.py tests/test_textract_client.py
git commit -m "feat(textract_client): pricing constants + per-feature cost helper"
```

---

## Task 3: `detect_document_text` wrapper with retry

**Files:**
- Modify: `poc/textract_client.py`
- Test: `tests/test_textract_client.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_textract_client.py`:

```python
from unittest.mock import MagicMock, patch


@patch("poc.textract_client.env.textract_client")
def test_detect_document_text_happy_path(mock_factory):
    fake_resp = {"Blocks": [{"BlockType": "LINE", "Text": "ACKLEY, CALVIN"}]}
    fake_client = MagicMock()
    fake_client.detect_document_text.return_value = fake_resp
    mock_factory.return_value = fake_client

    resp, cost = tc.detect_document_text(b"PNGBYTES")

    assert resp == fake_resp
    assert cost == pytest.approx(0.0015)
    fake_client.detect_document_text.assert_called_once_with(
        Document={"Bytes": b"PNGBYTES"}
    )


@patch("poc.textract_client.time.sleep", return_value=None)
@patch("poc.textract_client.env.textract_client")
def test_detect_document_text_retries_on_throttle(mock_factory, _sleep):
    err = ClientError({"Error": {"Code": "ThrottlingException"}}, "DetectDocumentText")
    fake_client = MagicMock()
    fake_client.detect_document_text.side_effect = [err, err, {"Blocks": []}]
    mock_factory.return_value = fake_client

    resp, cost = tc.detect_document_text(b"x", max_retries=3, retry_base_delay=0.0)

    assert resp == {"Blocks": []}
    assert fake_client.detect_document_text.call_count == 3


@patch("poc.textract_client.env.textract_client")
def test_detect_document_text_raises_non_retryable(mock_factory):
    err = ClientError({"Error": {"Code": "AccessDeniedException"}}, "DetectDocumentText")
    fake_client = MagicMock()
    fake_client.detect_document_text.side_effect = err
    mock_factory.return_value = fake_client

    with pytest.raises(ClientError):
        tc.detect_document_text(b"x")
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest tests/test_textract_client.py -v
```

Expected: `AttributeError: module 'poc.textract_client' has no attribute 'detect_document_text'`.

- [ ] **Step 3: Implement helper + first endpoint**

Append to `poc/textract_client.py`:

```python
def _call_with_retry(
    fn,
    *,
    max_retries: int,
    retry_base_delay: float,
    op_name: str,
):
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
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest tests/test_textract_client.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/textract_client.py tests/test_textract_client.py
git commit -m "feat(textract_client): detect_document_text wrapper with retry"
```

---

## Task 4: `analyze_forms`, `analyze_tables`, `analyze_layout` wrappers

**Files:**
- Modify: `poc/textract_client.py`
- Test: `tests/test_textract_client.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_textract_client.py`:

```python
@pytest.mark.parametrize("fn_name,feature,api_features", [
    ("analyze_forms",  "forms",  ["FORMS"]),
    ("analyze_tables", "tables", ["TABLES"]),
    ("analyze_layout", "layout", ["LAYOUT"]),
])
@patch("poc.textract_client.env.textract_client")
def test_analyze_simple_features(mock_factory, fn_name, feature, api_features):
    fake_resp = {"Blocks": [{"BlockType": "PAGE"}]}
    fake_client = MagicMock()
    fake_client.analyze_document.return_value = fake_resp
    mock_factory.return_value = fake_client

    fn = getattr(tc, fn_name)
    resp, cost = fn(b"PNG")

    assert resp == fake_resp
    assert cost == pytest.approx(tc.TEXTRACT_PRICING_USD[feature])
    fake_client.analyze_document.assert_called_once_with(
        Document={"Bytes": b"PNG"},
        FeatureTypes=api_features,
    )
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest tests/test_textract_client.py -v
```

Expected: `AttributeError: module 'poc.textract_client' has no attribute 'analyze_forms'`.

- [ ] **Step 3: Implement three wrappers**

Append to `poc/textract_client.py`:

```python
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
    kwargs = {"Document": {"Bytes": png_bytes}, "FeatureTypes": feature_types}
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
    return _analyze(png_bytes, feature_types=["FORMS"],
                    feature_pricing_key="forms", op_name="analyze_forms", **kwargs)


def analyze_tables(png_bytes: bytes, **kwargs) -> tuple[dict[str, Any], float]:
    return _analyze(png_bytes, feature_types=["TABLES"],
                    feature_pricing_key="tables", op_name="analyze_tables", **kwargs)


def analyze_layout(png_bytes: bytes, **kwargs) -> tuple[dict[str, Any], float]:
    return _analyze(png_bytes, feature_types=["LAYOUT"],
                    feature_pricing_key="layout", op_name="analyze_layout", **kwargs)
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest tests/test_textract_client.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/textract_client.py tests/test_textract_client.py
git commit -m "feat(textract_client): analyze_forms/tables/layout wrappers"
```

---

## Task 5: `analyze_queries` wrapper with QueriesConfig

**Files:**
- Modify: `poc/textract_client.py`
- Test: `tests/test_textract_client.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_textract_client.py`:

```python
@patch("poc.textract_client.env.textract_client")
def test_analyze_queries_passes_queries_config(mock_factory):
    fake_resp = {"Blocks": [{"BlockType": "QUERY_RESULT", "Text": "ACKLEY"}]}
    fake_client = MagicMock()
    fake_client.analyze_document.return_value = fake_resp
    mock_factory.return_value = fake_client

    queries = [
        {"Text": "What is the last name?", "Alias": "LAST"},
        {"Text": "What is the first name?", "Alias": "FIRST"},
    ]
    resp, cost = tc.analyze_queries(b"PNG", queries=queries)

    assert resp == fake_resp
    assert cost == pytest.approx(0.015)
    fake_client.analyze_document.assert_called_once_with(
        Document={"Bytes": b"PNG"},
        FeatureTypes=["QUERIES"],
        QueriesConfig={"Queries": queries},
    )


def test_analyze_queries_rejects_empty_queries():
    with pytest.raises(ValueError):
        tc.analyze_queries(b"PNG", queries=[])
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest tests/test_textract_client.py -v
```

Expected: `AttributeError: ... has no attribute 'analyze_queries'`.

- [ ] **Step 3: Implement `analyze_queries`**

Append to `poc/textract_client.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest tests/test_textract_client.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/textract_client.py tests/test_textract_client.py
git commit -m "feat(textract_client): analyze_queries wrapper with QueriesConfig"
```

---

## Task 6: Fixture manifest covering 7 page classes

**Files:**
- Create: `tests/fixtures_textract_baseline.json`

- [ ] **Step 1: Write the fixture manifest**

Create `tests/fixtures_textract_baseline.json`:

```json
[
  {
    "label": "cover_d1r001_card",
    "rel_path": "test_input_roll001/00097.tif",
    "expected_class": "student_cover",
    "expected_fields": ["last", "first", "dob"]
  },
  {
    "label": "test_sheet_d1r001",
    "rel_path": "test_input_roll001/00193.tif",
    "expected_class": "student_test_sheet",
    "expected_fields": ["last", "first"]
  },
  {
    "label": "continuation_d1r001",
    "rel_path": "test_input_roll001/00289.tif",
    "expected_class": "student_continuation",
    "expected_fields": ["last", "first"]
  },
  {
    "label": "index_d1r001_first",
    "rel_path": "index_probe/broad/d1r001/00011.tif",
    "expected_class": "student_records_index",
    "expected_fields": ["index_rows"]
  },
  {
    "label": "separator_styleA_clapper",
    "rel_path": "boundary_probe/d2r012_00005.tif",
    "expected_class": "roll_separator",
    "expected_fields": ["start_or_end", "roll_no"]
  },
  {
    "label": "separator_styleB_certificate",
    "rel_path": "boundary_probe/t001_00005.tif",
    "expected_class": "roll_separator",
    "expected_fields": ["start_or_end", "roll_no", "filmer", "date"]
  },
  {
    "label": "leader_letterhead_d3r028",
    "rel_path": "boundary_probe/d3r028_00002.tif",
    "expected_class": "roll_leader",
    "expected_fields": []
  },
  {
    "label": "leader_resolution_target_d5r064",
    "rel_path": "boundary_probe/d5r064_00001.tif",
    "expected_class": "roll_leader",
    "expected_fields": []
  }
]
```

- [ ] **Step 2: Verify all eight TIFs exist on disk**

```bash
python3 - <<'PY'
import json, pathlib
fixtures = json.loads(pathlib.Path("tests/fixtures_textract_baseline.json").read_text())
samples = pathlib.Path("samples")
for f in fixtures:
    p = samples / f["rel_path"]
    assert p.exists(), f"missing: {p}"
    print(f"OK {p}")
PY
```

Expected: 8 lines starting with `OK `, no errors.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures_textract_baseline.json
git commit -m "test: add textract bake-off fixture manifest (8 fixtures, 7 classes)"
```

---

## Task 7: Textract Queries config file

**Files:**
- Create: `scripts/textract_queries.json`

- [ ] **Step 1: Write the queries file**

Create `scripts/textract_queries.json`:

```json
[
  {"Text": "What is the student's last name?",  "Alias": "LAST_NAME"},
  {"Text": "What is the student's first name?", "Alias": "FIRST_NAME"},
  {"Text": "What is the student's middle name?", "Alias": "MIDDLE_NAME"},
  {"Text": "What is the student's date of birth?", "Alias": "DOB"},
  {"Text": "What is the school name?", "Alias": "SCHOOL"},
  {"Text": "What is the roll number?", "Alias": "ROLL_NO"}
]
```

- [ ] **Step 2: Validate JSON parses + length**

```bash
python3 -c "import json; q=json.load(open('scripts/textract_queries.json')); assert len(q)==6; print('OK', len(q))"
```

Expected: `OK 6`.

- [ ] **Step 3: Commit**

```bash
git add scripts/textract_queries.json
git commit -m "feat(scripts): add textract queries config (6 student/separator queries)"
```

---

## Task 8: Live smoke test (gated)

**Files:**
- Create: `tests/test_smoke_textract.py`

- [ ] **Step 1: Write the smoke test**

Create `tests/test_smoke_textract.py`:

```python
import os
from pathlib import Path

import pytest

from poc import textract_client as tc
from poc.convert import tif_to_png_bytes

SMOKE = os.environ.get("TEXTRACT_SMOKE_TEST") == "1"
SAMPLES = Path("samples")


@pytest.mark.skipif(not SMOKE, reason="TEXTRACT_SMOKE_TEST not set")
def test_detect_document_text_smoke():
    fixture = SAMPLES / "test_input_roll001/00097.tif"
    assert fixture.exists(), f"missing fixture: {fixture}"

    png = tif_to_png_bytes(fixture)
    resp, cost = tc.detect_document_text(png)

    blocks = resp.get("Blocks", [])
    line_blocks = [b for b in blocks if b.get("BlockType") == "LINE"]

    print(f"smoke: {len(blocks)} blocks, {len(line_blocks)} LINE, cost ${cost:.4f}")
    assert blocks, "Textract returned zero blocks"
    assert line_blocks, "Textract returned no LINE blocks"
    assert cost == pytest.approx(0.0015)
```

- [ ] **Step 2: Verify it skips without env var**

```bash
pytest tests/test_smoke_textract.py -v
```

Expected: 1 skipped.

- [ ] **Step 3: Run live (costs $0.0015)**

```bash
TEXTRACT_SMOKE_TEST=1 pytest tests/test_smoke_textract.py -v -s
```

Expected: 1 passed, prints block + LINE counts. **If this fails with `AccessDeniedException`, halt and add `textract:*` to the tanishq IAM user (or provide `.env.textract`); do not proceed to Task 9.**

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke_textract.py
git commit -m "test: live Textract smoke gated on TEXTRACT_SMOKE_TEST=1"
```

---

## Task 9: Bake-off CLI

**Files:**
- Create: `scripts/textract_bake_off.py`
- Create: `scripts/__init__.py` (if missing — required for `python3 -m scripts.*`)

- [ ] **Step 1: Ensure `scripts/` is an importable package**

```bash
test -f scripts/__init__.py || touch scripts/__init__.py
```

- [ ] **Step 2: Write the bake-off CLI**

Create `scripts/textract_bake_off.py`:

```python
"""Textract bake-off harness.

Iterates fixtures × features, dumps raw JSON to samples/textract_responses/,
prints a summary table to stdout, halts on budget breach.

Usage:
  python3 -m scripts.textract_bake_off \\
      --fixtures-file tests/fixtures_textract_baseline.json \\
      --out-dir samples/textract_responses \\
      --features detect,forms,tables,layout,queries \\
      --queries-file scripts/textract_queries.json \\
      --budget-ceiling 1.50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from poc import textract_client as tc
from poc.convert import tif_to_png_bytes

SAMPLES = Path("samples")
ALL_FEATURES = ["detect", "forms", "tables", "layout", "queries"]


def _summarize(feature: str, resp: dict[str, Any]) -> str:
    blocks = resp.get("Blocks", []) or []
    if feature == "detect":
        return f"lines={sum(1 for b in blocks if b.get('BlockType') == 'LINE')}"
    if feature == "forms":
        return f"kv={sum(1 for b in blocks if b.get('BlockType') == 'KEY_VALUE_SET')}"
    if feature == "tables":
        n_tables = sum(1 for b in blocks if b.get("BlockType") == "TABLE")
        n_cells = sum(1 for b in blocks if b.get("BlockType") == "CELL")
        return f"tables={n_tables} cells={n_cells}"
    if feature == "layout":
        layout_types = [b.get("BlockType", "") for b in blocks if b.get("BlockType", "").startswith("LAYOUT_")]
        return f"layout_blocks={len(layout_types)}"
    if feature == "queries":
        results = [b for b in blocks if b.get("BlockType") == "QUERY_RESULT"]
        return f"answers={len(results)}"
    return "?"


def _run_feature(feature: str, png: bytes, queries: list[dict] | None):
    if feature == "detect":
        return tc.detect_document_text(png)
    if feature == "forms":
        return tc.analyze_forms(png)
    if feature == "tables":
        return tc.analyze_tables(png)
    if feature == "layout":
        return tc.analyze_layout(png)
    if feature == "queries":
        if not queries:
            raise SystemExit("queries feature requested but --queries-file empty")
        return tc.analyze_queries(png, queries=queries)
    raise SystemExit(f"unknown feature: {feature}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures-file", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--features", default=",".join(ALL_FEATURES))
    p.add_argument("--queries-file", type=Path, default=None)
    p.add_argument("--budget-ceiling", type=float, default=1.50)
    args = p.parse_args(argv)

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    bad = [f for f in features if f not in ALL_FEATURES]
    if bad:
        raise SystemExit(f"unknown features: {bad}")

    fixtures = json.loads(args.fixtures_file.read_text())
    queries = json.loads(args.queries_file.read_text()) if args.queries_file else None

    args.out_dir.mkdir(parents=True, exist_ok=True)
    spend = 0.0
    rows: list[dict[str, Any]] = []

    for fx in fixtures:
        tif = SAMPLES / fx["rel_path"]
        if not tif.exists():
            print(f"SKIP missing: {tif}", file=sys.stderr)
            continue
        png = tif_to_png_bytes(tif)
        row = {"label": fx["label"], "expected_class": fx["expected_class"]}
        for feature in features:
            if spend >= args.budget_ceiling:
                print(f"HALT: budget ceiling ${args.budget_ceiling} reached "
                      f"(spent ${spend:.4f})", file=sys.stderr)
                _print_summary(rows, features, spend)
                return 2
            try:
                resp, cost = _run_feature(feature, png, queries)
            except Exception as e:
                row[feature] = f"ERR:{type(e).__name__}"
                print(f"ERR {fx['label']} {feature}: {e}", file=sys.stderr)
                continue
            spend += cost
            out_file = args.out_dir / f"{fx['label']}__{feature}.json"
            out_file.write_text(json.dumps(resp, default=str, indent=2))
            row[feature] = _summarize(feature, resp)
            print(f"OK {fx['label']:<35} {feature:<8} {row[feature]:<25} "
                  f"${cost:.4f}  total=${spend:.4f}")
        rows.append(row)

    _print_summary(rows, features, spend)
    return 0


def _print_summary(rows, features, spend):
    print()
    print("=" * 100)
    print(f"{'fixture':<35}{'class':<22}" + "".join(f"{f:<22}" for f in features))
    print("-" * 100)
    for r in rows:
        cells = "".join(f"{str(r.get(f, '-')):<22}" for f in features)
        print(f"{r['label']:<35}{r['expected_class']:<22}{cells}")
    print("-" * 100)
    print(f"TOTAL SPEND: ${spend:.4f}")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Dry-run the CLI with one feature only (detect) before the full sweep**

Costs ~$0.012. Sanity-checks the wiring on every fixture without touching the expensive features.

```bash
python3 -m scripts.textract_bake_off \
    --fixtures-file tests/fixtures_textract_baseline.json \
    --out-dir samples/textract_responses \
    --features detect \
    --budget-ceiling 0.05
```

Expected: 8 `OK` lines (all fixtures × detect), `TOTAL SPEND: ~$0.0120`, files like `samples/textract_responses/cover_d1r001_card__detect.json` exist.

- [ ] **Step 4: Commit**

```bash
git add scripts/__init__.py scripts/textract_bake_off.py
git commit -m "feat(scripts): textract bake-off CLI w/ budget ceiling + summary table"
```

---

## Task 10: Tesseract runner

**Files:**
- Modify: `requirements.txt`
- Create: `scripts/tesseract_run.py`

- [ ] **Step 1: Append `pytesseract` to requirements**

Append a single line to `requirements.txt`:

```
pytesseract>=0.3.10
```

- [ ] **Step 2: Install (system + Python)**

```bash
brew list tesseract >/dev/null 2>&1 || brew install tesseract
pip install -r requirements.txt
tesseract --version
```

Expected: `tesseract 5.x.x` and binary on PATH.

- [ ] **Step 3: Write the runner**

Create `scripts/tesseract_run.py`:

```python
"""Tesseract bake-off runner.

For each fixture: convert TIF→PNG (poc.convert), run Tesseract twice (raw and
preprocessed), save extracted text + per-word TSV with bboxes + confidences.

Usage:
  python3 -m scripts.tesseract_run \\
      --fixtures-file tests/fixtures_textract_baseline.json \\
      --out-dir samples/tesseract_responses \\
      --preprocess
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

import pytesseract
from poc.convert import tif_to_png_bytes

SAMPLES = Path("samples")


def _preprocess(png_bytes: bytes) -> bytes:
    img = Image.open(__import__("io").BytesIO(png_bytes)).convert("L")
    img = ImageOps.autocontrast(img)
    threshold = 160
    bw = img.point(lambda p: 0 if p < threshold else 255, mode="1")
    out = __import__("io").BytesIO()
    bw.save(out, format="PNG")
    return out.getvalue()


def _run_one(label: str, png: bytes, suffix: str, out_dir: Path) -> tuple[int, float]:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
        f.flush()
        path = f.name
    try:
        text = pytesseract.image_to_string(path)
        tsv = pytesseract.image_to_data(path, output_type=pytesseract.Output.STRING)
    finally:
        Path(path).unlink(missing_ok=True)

    (out_dir / f"{label}__tesseract_{suffix}.txt").write_text(text)
    (out_dir / f"{label}__tesseract_{suffix}.tsv").write_text(tsv)

    word_count = sum(1 for ln in tsv.splitlines()[1:] if ln.split("\t")[-1].strip())
    confs = [int(c) for c in (ln.split("\t")[-2] for ln in tsv.splitlines()[1:])
             if c.strip().lstrip("-").isdigit() and int(c) >= 0]
    avg_conf = (sum(confs) / len(confs)) if confs else 0.0
    return word_count, avg_conf


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures-file", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--preprocess", action="store_true",
                   help="also run a preprocessed pass (grayscale + Otsu-ish threshold)")
    args = p.parse_args(argv)

    fixtures = json.loads(args.fixtures_file.read_text())
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'fixture':<35}{'pass':<10}{'words':<8}{'avg_conf':<10}")
    print("-" * 70)
    for fx in fixtures:
        tif = SAMPLES / fx["rel_path"]
        if not tif.exists():
            print(f"SKIP missing: {tif}", file=sys.stderr)
            continue
        png = tif_to_png_bytes(tif)

        wc, conf = _run_one(fx["label"], png, "raw", args.out_dir)
        print(f"{fx['label']:<35}{'raw':<10}{wc:<8}{conf:<10.2f}")

        if args.preprocess:
            pre = _preprocess(png)
            wc2, conf2 = _run_one(fx["label"], pre, "pre", args.out_dir)
            print(f"{fx['label']:<35}{'pre':<10}{wc2:<8}{conf2:<10.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run on one fixture as a smoke check**

```bash
python3 -m scripts.tesseract_run \
    --fixtures-file tests/fixtures_textract_baseline.json \
    --out-dir samples/tesseract_responses \
    --preprocess
```

Expected: 8 fixtures × 2 passes = 16 rows printed, files in `samples/tesseract_responses/`. No errors.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt scripts/tesseract_run.py
git commit -m "feat(scripts): tesseract runner w/ raw + preprocessed passes"
```

---

## Task 11: Run the full Textract sweep

**Files:** none modified — produces JSON dumps under `samples/textract_responses/`.

- [ ] **Step 1: Run all features × all fixtures, piping summary to a transcript file**

```bash
python3 -m scripts.textract_bake_off \
    --fixtures-file tests/fixtures_textract_baseline.json \
    --out-dir samples/textract_responses \
    --features detect,forms,tables,layout,queries \
    --queries-file scripts/textract_queries.json \
    --budget-ceiling 1.50 \
    2>&1 | tee samples/textract_responses/_summary.txt
```

Expected: ≤ ~$0.70 spent. 40 JSON files (8 fixtures × 5 features). Final summary table both on screen and in `_summary.txt`.

- [ ] **Step 2: Confirm 40 JSON files landed**

```bash
ls samples/textract_responses/*.json | wc -l
```

Expected: `40`.

- [ ] **Step 3: Spot-check the cover Forms response**



```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("samples/textract_responses/cover_d1r001_card__forms.json")
data = json.loads(p.read_text())
kv = [b for b in data["Blocks"] if b["BlockType"] == "KEY_VALUE_SET"
      and "KEY" in (b.get("EntityTypes") or [])]
print(f"KV pairs: {len(kv)}")
for b in kv[:10]:
    print(" ", b.get("Id"), b.get("EntityTypes"))
PY
```

Expected: at least one KV pair printed; one of them resolves to `LAST NAME` or `LAST` text. **This is the load-bearing claim from `docs/no-llm-90pct-design.md` §1 — record the actual answer (Y/N) for the results doc.**

- [ ] **Step 4: No commit yet — JSONs are gitignored by `samples/**` rule.**

Continue to Task 12.

---

## Task 12: Run the Tesseract sweep

**Files:** none modified — produces TXT/TSV files.

- [ ] **Step 1: Run raw + preprocessed**

```bash
python3 -m scripts.tesseract_run \
    --fixtures-file tests/fixtures_textract_baseline.json \
    --out-dir samples/tesseract_responses \
    --preprocess \
    | tee samples/tesseract_responses/_summary.txt
```

Expected: 16 rows; 32 output files (8 × 2 passes × 2 file types).

- [ ] **Step 2: Eyeball one student_cover output**

```bash
cat samples/tesseract_responses/cover_d1r001_card__tesseract_raw.txt
echo "---"
cat samples/tesseract_responses/cover_d1r001_card__tesseract_pre.txt
```

Record qualitative judgment (A/B/C/D grade) for the results doc. Compare against the Textract Detect text in `samples/textract_responses/cover_d1r001_card__detect.json`.

- [ ] **Step 3: No commit — outputs gitignored.**

---

## Task 13: Author the results doc

**Files:**
- Create: `docs/2026-04-27-textract-bake-off-results.md`

- [ ] **Step 1: Write the results doc**

Create `docs/2026-04-27-textract-bake-off-results.md` with these sections, populated from the captured outputs:

```markdown
# Textract Bake-Off + Tesseract Brainstorm — Results

**Date:** 2026-04-27
**Fixtures:** 8 TIFs (`tests/fixtures_textract_baseline.json`) spanning 7 page classes.
**Spend:** $X.XX Textract, $0 Tesseract.

## TL;DR

- Forms KV on `student_cover`: <returned LAST/FIRST/MIDDLE Y/N, with example>
- Tables on `student_records_index`: <rows/cols extracted, header-row detected Y/N>
- Queries: <answers resolved out of 6 per fixture>
- Tesseract raw vs preprocessed: <CER estimate>
- Bottom line: <docs/no-llm-90pct-design.md confirmed | needs revision>

## 1. Per-fixture × per-feature matrix

(Paste from `samples/textract_responses/_summary.txt` + manual annotations.)

## 2. Forms KV deep-dive on student_cover

- Total KV pairs: N
- KV pairs with confidence ≥ 90%: N
- Did `LAST NAME` / `FIRST NAME` resolve? Y/N — show the actual JSON snippet.

## 3. Tables deep-dive on student_records_index

- Tables detected: N (expected 1)
- Header row detected: Y/N
- Cells per data row: N (expected 4–6)
- Sample row extracted as `(last, first, middle, dob)`.

## 4. Queries effectiveness

For each fixture × each of the 6 queries, what was returned + confidence. Highlight failures.

## 5. Tesseract vs Textract Detect — text quality on faded scans

| Fixture | Textract Detect (lines) | Tesseract raw (words / avg_conf) | Tesseract preprocessed (words / avg_conf) | Eyeball grade (A–D) |
|---|---|---|---|---|

Two fixtures get a 30-line hand transcription + character-error-rate estimate.

## 6. Updated cost projection at 218K corpus

(Replace forecasts in `docs/no-llm-90pct-design.md` §4 with measured per-feature cost × projected page-class distribution.)

## 7. Recommendation — locked feature-set per page_class

| page_class | Detect | Forms | Tables | Layout | Queries | Tesseract |
|---|---|---|---|---|---|---|
| student_cover | always | <Y/N> | no | <Y/N> | <Y/N> | <Y/N> |
| student_records_index | always | no | always | optional | no | no |
| roll_separator (Style B) | always | <Y/N> | no | no | <Y/N> | no |
| ... | | | | | | |

## 8. Decision

- Stay on `docs/no-llm-90pct-design.md` plan as-written: <Y/N>
- Revisions needed: <list>
- Next plan: implementation of `poc/rule_classifier.py` consuming the locked feature-set above.
```

- [ ] **Step 2: Fill in every `<...>` placeholder with real numbers from the captured output. Read the JSON dumps under `samples/textract_responses/` directly to populate sections 2–4.**

- [ ] **Step 3: Commit**

```bash
git add docs/2026-04-27-textract-bake-off-results.md
git commit -m "docs: textract bake-off + tesseract results, 218K cost re-forecast"
```

---

## Task 14: Update `README.md` and `CLAUDE.md`

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a Common Commands entry to `README.md`**

Find the "Common Commands" section (already present per `CLAUDE.md`). Add this block:

```bash
# Textract bake-off (8 fixtures × 5 features, ~$0.70)
TEXTRACT_SMOKE_TEST=1 python3 -m scripts.textract_bake_off \
    --fixtures-file tests/fixtures_textract_baseline.json \
    --out-dir samples/textract_responses \
    --features detect,forms,tables,layout,queries \
    --queries-file scripts/textract_queries.json \
    --budget-ceiling 1.50

# Tesseract bake-off (raw + preprocessed, $0)
python3 -m scripts.tesseract_run \
    --fixtures-file tests/fixtures_textract_baseline.json \
    --out-dir samples/tesseract_responses \
    --preprocess
```

- [ ] **Step 2: Add a one-liner under `CLAUDE.md` "Common Commands"**

Find the last command in the "Common Commands" code block in `CLAUDE.md` (the `regroup` command). Append:

```bash
# Textract + Tesseract bake-off (see scripts/textract_bake_off.py, scripts/tesseract_run.py)
python3 -m scripts.textract_bake_off --fixtures-file tests/fixtures_textract_baseline.json --out-dir samples/textract_responses --features detect,forms,tables,layout,queries --queries-file scripts/textract_queries.json --budget-ceiling 1.50
python3 -m scripts.tesseract_run --fixtures-file tests/fixtures_textract_baseline.json --out-dir samples/tesseract_responses --preprocess
```

- [ ] **Step 3: Add a line under `CLAUDE.md` "Resolved blockers"** (only if Task 8 Step 3 surfaced a missing IAM perm and you added `textract:*` to the tanishq user):

```markdown
- ~~Textract not authorized on `tanishq` IAM user~~ — resolved 2026-04-27 by attaching `AmazonTextractFullAccess` (or scoped `textract:DetectDocumentText, textract:AnalyzeDocument`).
```

- [ ] **Step 4: Run full unit-test suite to confirm nothing broke**

```bash
pytest -q
```

Expected: 59 prior tests + 16 new textract_client tests = 75 passed; smoke tests (Bedrock + Textract) skipped.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: README + CLAUDE.md entries for textract / tesseract bake-off"
```

---

## Verification (end-to-end)

After all 14 tasks:

1. **Unit tests pass:**
   ```bash
   pytest -q
   ```
   75 passed (59 prior + 16 new), all smoke tests skipped.

2. **Live smoke test passes:**
   ```bash
   TEXTRACT_SMOKE_TEST=1 pytest tests/test_smoke_textract.py -v -s
   ```
   1 passed, prints block + LINE counts. Costs $0.0015.

3. **Bake-off artifacts exist:**
   ```bash
   ls samples/textract_responses/*.json | wc -l   # → 40
   ls samples/tesseract_responses/*.txt | wc -l   # → 16 (8 raw + 8 pre)
   ```

4. **Results doc exists with no `<...>` placeholders:**
   ```bash
   grep -c '<' docs/2026-04-27-textract-bake-off-results.md   # → 0 (after Task 13 Step 2)
   ```

5. **Spot-check the load-bearing claim:** open `samples/textract_responses/cover_d1r001_card__forms.json`, find a `KEY_VALUE_SET` block whose `KEY` text matches `LAST NAME` (case-insensitive) and whose linked `VALUE` block looks like a real surname. Record the answer in §2 of the results doc.

6. **Total spend:** $0.0015 (smoke) + ~$0.68 (full sweep) + ≤ $0.0120 (bake-off detect-only smoke in Task 9) = under the $1.50 ceiling.

7. **No production pipeline disturbed:** `poc/run_poc.py`, `poc/regroup.py`, etc. untouched. `pytest -q` baseline still 59 passing.

---

## Out of scope (deferred to next plan)

- `poc/rule_classifier.py` consuming the locked feature-set from §7 of the results doc.
- `poc/preprocess.py` (deskew, Sauvola, erosion) — only justified if Tesseract path is pursued.
- `poc/name_voter.py` (3-source agreement) and `poc/validators.py` (Tier 1 gates).
- DOB-aware `snap_to_index_v2`.
- PaddleOCR / EasyOCR / docTR / Surya / Azure DocAI bake-offs — triggered only if Tesseract is too weak per §5.
- Step Functions / Lambda wrapping for Phase 2 production.
