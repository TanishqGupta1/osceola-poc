# Pure-Textract + Code-Logic V4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-Textract pure-code-logic extraction stack — combined-call AnalyzeDocument + layout-fingerprint classifier + bbox-positional fallback + multi-source name voter + index-snap recall booster + per-class cost routing — and measure precision/recall on existing 113 raw response JSONs (Stages 1-6) plus a fresh end-to-end run on 50 ROLL 001 pages (Stage 8). **No Bedrock. No custom Adapter training.** Worst-case escape only.

**Architecture:** All new code lands inside the existing isolated `textract_probe/` module (per user directive — separate from `poc/`). Builds on the unit-tested `client.py`, the 113 already-collected raw response JSONs in `textract_probe/output/textract/`, and the `decode.py` digest tool. Each new module is small, single-responsibility, unit-tested with mocked Textract responses. End-to-end driver script wires them all together via the per-class router.

**Tech Stack:** Python 3.11+, boto3 Textract, Pillow, pytest. Reuses `poc/index.py::snap_to_index` (no rewrite). Same `.env.bedrock` IAM credentials.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `textract_probe/client.py` | modify | Add `analyze_all(png, queries, include_signatures)` combined-feature wrapper |
| `textract_probe/layout_classifier.py` | create | Map Layout block-type counts → page_class fingerprint |
| `textract_probe/bbox_extract.py` | create | Find handwritten value adjacent to a labeled anchor in Detect/Forms output |
| `textract_probe/validators.py` | create | Tier 1 garbage filter, name regex, parent-prefix rejection |
| `textract_probe/name_voter.py` | create | Multi-source confidence-weighted vote across Forms/Queries/bbox/regex |
| `textract_probe/index_snap.py` | create | Thin wrapper that builds roll-index from Tables responses + reuses `poc/index.py::snap_to_index` |
| `textract_probe/router.py` | create | Per-class feature selection — two-pass cheap-classify → expensive-extract |
| `textract_probe/extract_pipeline.py` | create | End-to-end CLI driving the full V4 stack on a fixture set |
| `textract_probe/tests/test_layout_classifier.py` | create | Unit tests on existing JSON fixtures |
| `textract_probe/tests/test_bbox_extract.py` | create | Unit tests with synthetic Block layouts |
| `textract_probe/tests/test_validators.py` | create | Tier 1 filter coverage |
| `textract_probe/tests/test_name_voter.py` | create | Voting logic + agreement counting |
| `textract_probe/tests/test_index_snap.py` | create | Tables → roll-index → snap integration |
| `textract_probe/tests/test_router.py` | create | Per-class routing with mocked client |

`textract_probe/output/v4/` holds end-to-end run artifacts (gitignored).

---

## Task 1: Combined-call wrapper `analyze_all`

**Files:**
- Modify: `textract_probe/client.py`
- Test: `textract_probe/tests/test_client.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `textract_probe/tests/test_client.py`:

```python
@patch("textract_probe.client.env.textract_client")
def test_analyze_all_combined_call(mock_factory):
    fake_resp = {"Blocks": [{"BlockType": "PAGE"}]}
    fake_client = MagicMock()
    fake_client.analyze_document.return_value = fake_resp
    mock_factory.return_value = fake_client

    queries = [{"Text": "Q1?", "Alias": "Q1"}]
    resp, cost = tc.analyze_all(b"PNG", queries=queries, include_signatures=True)

    assert resp == fake_resp
    expected_cost = (
        tc.TEXTRACT_PRICING_USD["forms"]
        + tc.TEXTRACT_PRICING_USD["tables"]
        + tc.TEXTRACT_PRICING_USD["layout"]
        + tc.TEXTRACT_PRICING_USD["queries"]
        + tc.TEXTRACT_PRICING_USD["signatures"]
    )
    assert cost == pytest.approx(expected_cost)
    fake_client.analyze_document.assert_called_once_with(
        Document={"Bytes": b"PNG"},
        FeatureTypes=["FORMS", "TABLES", "LAYOUT", "QUERIES", "SIGNATURES"],
        QueriesConfig={"Queries": queries},
    )


@patch("textract_probe.client.env.textract_client")
def test_analyze_all_no_signatures_no_queries(mock_factory):
    fake_client = MagicMock()
    fake_client.analyze_document.return_value = {"Blocks": []}
    mock_factory.return_value = fake_client

    _, cost = tc.analyze_all(b"PNG", queries=None, include_signatures=False)

    expected_cost = (
        tc.TEXTRACT_PRICING_USD["forms"]
        + tc.TEXTRACT_PRICING_USD["tables"]
        + tc.TEXTRACT_PRICING_USD["layout"]
    )
    assert cost == pytest.approx(expected_cost)
    fake_client.analyze_document.assert_called_once_with(
        Document={"Bytes": b"PNG"},
        FeatureTypes=["FORMS", "TABLES", "LAYOUT"],
    )
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_client.py -v
```

Expected: `AttributeError: module 'textract_probe.client' has no attribute 'analyze_all'` and `KeyError: 'signatures'` on pricing.

- [ ] **Step 3: Implement `analyze_all` + pricing constant**

In `textract_probe/client.py`, add `signatures` to pricing dict:

```python
TEXTRACT_PRICING_USD: dict[str, float] = {
    "detect":     0.0015,
    "forms":      0.05,
    "tables":     0.015,
    "layout":     0.004,
    "queries":    0.015,
    "signatures": 0.004,
}
```

Append at end of `textract_probe/client.py`:

```python
def analyze_all(
    png_bytes: bytes,
    *,
    queries: list[dict[str, str]] | None = None,
    include_signatures: bool = True,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], float]:
    """One-shot call with FORMS+TABLES+LAYOUT (+QUERIES if given) (+SIGNATURES if requested).

    Returns (raw_response, total_usd_cost). Same per-feature pricing — no discount
    for combining, but single API roundtrip.
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
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_client.py -v
```

Expected: 19 passed (17 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add textract_probe/client.py textract_probe/tests/test_client.py
git commit -m "feat(textract_probe): analyze_all combined-feature call w/ signatures"
```

---

## Task 2: Layout-fingerprint classifier

**Files:**
- Create: `textract_probe/layout_classifier.py`
- Create: `textract_probe/tests/test_layout_classifier.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_layout_classifier.py`:

```python
import pytest

from textract_probe import layout_classifier as lc


def _resp(blocks):
    return {"Blocks": blocks}


def _block(t, conf=99.0, text=""):
    return {"BlockType": t, "Confidence": conf, "Text": text}


def test_classify_index_page():
    blocks = (
        [_block("LINE")] * 100
        + [_block("LAYOUT_TITLE")]
        + [_block("TABLE")]
        + [_block("CELL")] * 200
    )
    cls, conf, fp = lc.classify(_resp(blocks))
    assert cls == "student_records_index"
    assert conf >= 0.8
    assert fp["TABLE"] == 1


def test_classify_separator_styleA():
    blocks = (
        [_block("LINE")] * 6
        + [_block("LAYOUT_TITLE")] * 2
    )
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "roll_separator"


def test_classify_separator_styleB():
    blocks = (
        [_block("LINE")] * 26
        + [_block("LAYOUT_TITLE")]
        + [_block("KEY_VALUE_SET", conf=88.0)] * 5
        + [_block("SIGNATURE")]
    )
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "roll_separator"


def test_classify_student_cover():
    blocks = (
        [_block("LINE")] * 200
        + [_block("KEY_VALUE_SET", conf=85.0)] * 80
        + [_block("LAYOUT_FIGURE")]
        + [_block("SIGNATURE")] * 2
    )
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "student_cover"


def test_classify_roll_leader():
    blocks = [_block("LINE")] * 30
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "roll_leader"


def test_classify_unknown():
    blocks = []
    cls, conf, _ = lc.classify(_resp(blocks))
    assert cls == "unknown"
    assert conf == 0.0
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_layout_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.layout_classifier'`.

- [ ] **Step 3: Implement classifier**

Create `textract_probe/layout_classifier.py`:

```python
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
    n_figures    = fp.get("LAYOUT_FIGURE", 0)

    if n_lines == 0:
        return "unknown", 0.0, fp

    # 1. Index page
    if n_tables >= 1 and n_cells >= 20:
        return "student_records_index", 0.95, fp

    # 2. Separator Style B (certificate)
    if n_signatures >= 1 and n_kv_keys >= 3 and 20 <= n_lines <= 40:
        return "roll_separator", 0.90, fp

    # 3. Separator Style A (clapperboard)
    if n_lines < 25 and n_tables == 0 and n_signatures == 0:
        return "roll_separator", 0.85, fp

    # 4. Student cover (forms-rich)
    if n_kv_keys >= 10 and n_lines >= 80:
        return "student_cover", 0.85, fp

    # 5. Leader (medium lines, no structure)
    if 25 <= n_lines <= 80 and n_kv_keys < 10:
        return "roll_leader", 0.70, fp

    return "unknown", 0.30, fp
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_layout_classifier.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run classifier on existing 113 JSONs as sanity-check**

Add a one-off check to verify accuracy against the fixture manifests:

```bash
python3 - <<'PY'
import json, pathlib
from textract_probe import layout_classifier as lc

TEXTRACT = pathlib.Path("textract_probe/output/textract")
for fixtures_file in [
    "textract_probe/fixtures.json",
    "textract_probe/fixtures_round2.json",
    "textract_probe/fixtures_round3.json",
    "textract_probe/fixtures_round4_indexes.json",
    "textract_probe/fixtures_round4_separators.json",
]:
    fixtures = json.loads(pathlib.Path(fixtures_file).read_text())
    for fx in fixtures:
        # Need a combined-call response; round 1 fixtures only have separate per-feature
        # responses. Approximate by union of all available block types.
        label = fx["label"]
        merged = {"Blocks": []}
        for feat in ["detect", "forms", "tables", "layout", "queries"]:
            p = TEXTRACT / f"{label}__{feat}.json"
            if p.exists():
                merged["Blocks"].extend(json.loads(p.read_text())["Blocks"])
        if not merged["Blocks"]:
            continue
        cls, conf, _ = lc.classify(merged)
        ok = "OK " if cls == fx["expected_class"] else "MISS"
        print(f"{ok} {label:<35} expected={fx['expected_class']:<22} got={cls:<22} conf={conf:.2f}")
PY
```

Expected: ≥80% accuracy on deterministic classes (index, separator, leader). Misses are fine for `student_cover` because no fixture has had a true combined-call response yet.

- [ ] **Step 6: Commit**

```bash
git add textract_probe/layout_classifier.py textract_probe/tests/test_layout_classifier.py
git commit -m "feat(textract_probe): layout-fingerprint classifier (deterministic, no keywords)"
```

---

## Task 3: Bbox-positional pairing fallback

**Files:**
- Create: `textract_probe/bbox_extract.py`
- Create: `textract_probe/tests/test_bbox_extract.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_bbox_extract.py`:

```python
import pytest

from textract_probe import bbox_extract as bx


def _word(text, top, left, width=0.05, height=0.02, conf=95.0):
    return {
        "BlockType": "WORD",
        "Text": text,
        "Confidence": conf,
        "Geometry": {"BoundingBox": {"Top": top, "Left": left,
                                     "Width": width, "Height": height}},
    }


def test_extract_value_to_right_of_anchor():
    blocks = [
        _word("LAST", top=0.10, left=0.10, width=0.05),
        _word("Owen", top=0.10, left=0.18, width=0.06),  # right of anchor
        _word("Title", top=0.05, left=0.10),  # above, irrelevant
    ]
    val = bx.extract_value_near_anchor(
        blocks, anchor_text="LAST", direction="right"
    )
    assert val == "Owen"


def test_extract_value_below_anchor():
    blocks = [
        _word("NAME", top=0.10, left=0.10, width=0.05, height=0.02),
        _word("Janner", top=0.13, left=0.10),  # directly below, slight gap
        _word("Other", top=0.50, left=0.50),  # far away
    ]
    val = bx.extract_value_near_anchor(blocks, anchor_text="NAME", direction="below")
    assert val == "Janner"


def test_skip_label_words():
    blocks = [
        _word("LAST", top=0.10, left=0.10, width=0.05),
        _word("FIRST", top=0.10, left=0.18, width=0.06),  # another label
        _word("Owen", top=0.10, left=0.26, width=0.06),
    ]
    val = bx.extract_value_near_anchor(
        blocks, anchor_text="LAST", direction="right",
        skip_words={"FIRST", "MIDDLE", "DOB"},
    )
    assert val == "Owen"


def test_no_anchor_returns_empty():
    blocks = [_word("hello", top=0.1, left=0.1)]
    assert bx.extract_value_near_anchor(blocks, "MISSING", "right") == ""


def test_no_value_in_direction_returns_empty():
    blocks = [_word("LAST", top=0.5, left=0.5, width=0.05)]
    assert bx.extract_value_near_anchor(blocks, "LAST", "right") == ""
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_bbox_extract.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.bbox_extract'`.

- [ ] **Step 3: Implement bbox extractor**

Create `textract_probe/bbox_extract.py`:

```python
"""Bbox-positional value extractor.

When Textract Forms detects a label (e.g. `LAST`) but returns an empty VALUE,
fall back to scanning Detect WORD blocks for the nearest non-label word in
the expected direction (right of the label or directly below it). Used to
rescue handwritten name fields that Forms cannot pair on faded microfilm.
"""
from __future__ import annotations

from typing import Any, Iterable

# Default Osceola-corpus form labels — words to skip when scanning.
DEFAULT_LABEL_WORDS: frozenset[str] = frozenset({
    "LAST", "FIRST", "MIDDLE", "NAME", "DOB", "BIRTH", "DATE",
    "PLACE", "BIRTHPLACE", "BIRTHDATE", "SCHOOL", "SEX", "RACE",
    "AGE", "GRADE", "ADDRESS", "PHONE", "PARENT", "MOTHER", "FATHER",
    "GUARDIAN", "PUPIL", "STUDENT", "RECORD", "OF", "OSCEOLA",
    "FLORIDA", "COUNTY", "ROLL", "NUMBER",
})


def _bbox(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    g = block.get("Geometry", {}).get("BoundingBox")
    if not g:
        return None
    return g["Top"], g["Left"], g["Width"], g["Height"]


def extract_value_near_anchor(
    blocks: Iterable[dict[str, Any]],
    anchor_text: str,
    direction: str = "right",
    skip_words: Iterable[str] | None = None,
    max_horizontal_gap: float = 0.30,
    max_vertical_gap: float = 0.05,
) -> str:
    """Find a WORD block adjacent to an anchor LINE/WORD, in the given direction.

    direction = "right": same row (top within ±height), left > anchor_left+anchor_width.
    direction = "below": same column (left within ±width), top > anchor_top+anchor_height.

    Returns the candidate WORD's Text, or "" if none found.
    """
    skip = {w.upper() for w in (skip_words or DEFAULT_LABEL_WORDS)}
    anchor_text_u = anchor_text.upper()

    word_blocks = [b for b in blocks if b.get("BlockType") == "WORD"]

    # Find anchor block (case-insensitive substring match on the WORD text)
    anchor = None
    for b in word_blocks:
        if anchor_text_u == (b.get("Text") or "").upper():
            anchor = b
            break
    if anchor is None:
        return ""

    a_box = _bbox(anchor)
    if a_box is None:
        return ""
    a_top, a_left, a_width, a_height = a_box

    candidates: list[tuple[float, dict[str, Any]]] = []
    for b in word_blocks:
        if b is anchor:
            continue
        text = (b.get("Text") or "").strip()
        if not text or text.upper() in skip:
            continue
        bx_box = _bbox(b)
        if bx_box is None:
            continue
        b_top, b_left, b_width, b_height = bx_box

        if direction == "right":
            if abs(b_top - a_top) > a_height:
                continue
            gap = b_left - (a_left + a_width)
            if gap < -0.005 or gap > max_horizontal_gap:
                continue
            candidates.append((gap, b))
        elif direction == "below":
            if abs(b_left - a_left) > a_width:
                continue
            gap = b_top - (a_top + a_height)
            if gap < -0.005 or gap > max_vertical_gap:
                continue
            candidates.append((gap, b))
        else:
            raise ValueError(f"unknown direction: {direction!r}")

    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0])
    return (candidates[0][1].get("Text") or "").strip()
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_bbox_extract.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/bbox_extract.py textract_probe/tests/test_bbox_extract.py
git commit -m "feat(textract_probe): bbox-positional value extractor (Forms KV fallback)"
```

---

## Task 4: Tier 1 garbage filter / name validator

**Files:**
- Create: `textract_probe/validators.py`
- Create: `textract_probe/tests/test_validators.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_validators.py`:

```python
import pytest

from textract_probe import validators as v


@pytest.mark.parametrize("name,ok", [
    # Valid
    ("Owen", True),
    ("Owen, Randall Horton", True),
    ("alexander, Earnestine", True),
    ("O'Brien", True),
    ("Markley-Smith", True),
    # Garbage
    ("",                      False),
    ("BIRTH",                 False),
    ("PHOTOGRAPH",            False),
    ("STUDENT",               False),
    ("OSCEOLA",               False),
    ("1887",                  False),
    ("1925 Sept 11",          False),
    ("X",                     False),  # too short
    ("12345",                 False),  # all numeric
    ("Mrs. W. O. Janner",     False),  # parent prefix
    ("FATHER's name",         False),
    ("MOTHER",                False),
    ("(LAST)",                False),  # form label
])
def test_is_valid_student_name(name, ok):
    assert v.is_valid_student_name(name) is ok


@pytest.mark.parametrize("text,expected", [
    ("Owen, Randall Horton with",     "Owen, Randall Horton"),
    ("MARKLEY, Judith,",              "MARKLEY, Judith"),
    ("  Bunt   ",                     "Bunt"),
    ("'arklev",                       "arklev"),
])
def test_clean_extracted_name(text, expected):
    assert v.clean_extracted_name(text) == expected


@pytest.mark.parametrize("dob,ok", [
    ("11/26/45",  True),
    ("6/10/60",   True),
    ("5-21-46",   True),
    ("1925",      False),  # year-only
    ("1887",      False),  # printed cert year
    ("",          False),
    ("19 / 19 / 19", False),  # placeholder pattern
    ("9.5.59",    True),
])
def test_is_valid_dob(dob, ok):
    assert v.is_valid_dob(dob) is ok
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_validators.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.validators'`.

- [ ] **Step 3: Implement validators**

Create `textract_probe/validators.py`:

```python
"""Tier 1 deterministic validators — garbage filter, name regex, DOB checker.

Run on every extracted name/DOB candidate before it can vote in the
multi-source name voter. Fail-fast.
"""
from __future__ import annotations

import re

# Words that look like names but are actually form labels or noise.
GARBAGE_TOKENS: frozenset[str] = frozenset({
    "BIRTH", "BIRTHDATE", "BIRTHPLACE", "PLACE", "DATE", "AGE",
    "COUNTY", "STATE", "CITY", "SEX", "RACE", "GRADE",
    "NAME", "LAST", "FIRST", "MIDDLE", "RECORD", "RECORDS",
    "STUDENT", "PUPIL", "TEACHER", "COUNSELOR", "PARENT", "GUARDIAN",
    "ADDRESS", "PHONE", "OCCUPATION", "SCHOOL", "DISTRICT",
    "OSCEOLA", "FLORIDA", "ROLL", "NUMBER", "REEL", "REDUCTION",
    "CERTIFICATE", "AUTHENTICITY", "DEPARTMENT",
    "PHOTOGRAPH", "COMMENTS", "OBSERVATIONS", "SUGGESTIONS",
    "SECONDARY", "ELEMENTARY",
})

# Title prefixes -> reject as student name (these are parent/guardian forms).
PARENT_PREFIXES: tuple[str, ...] = (
    "MR.", "MRS.", "MS.", "DR.",
    "MOTHER", "FATHER", "GUARDIAN", "PARENT", "STEPFATHER", "STEPMOTHER",
)

# Valid name pattern: starts/ends with a letter, allows space, hyphen, apostrophe, period.
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-\. ,]{1,60}[A-Za-z\.]$")

# DOB pattern: m/d/y or m-d-y or m.d.y, day in [1-31], year 2 or 4 digits.
DOB_RE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\s*$")


def clean_extracted_name(s: str) -> str:
    """Strip trailing form noise like 'with', 'COUNTY', trailing punctuation."""
    if not s:
        return ""
    s = s.strip()
    s = re.sub(r"^['`\"]+", "", s)
    s = re.sub(r"[,\s]+$", "", s)
    # Common Osceola-form trailing-noise suffixes
    for noise in (" with", " COUNTY", " (LAST)", " (FIRST)", " (MIDDLE)"):
        if s.endswith(noise):
            s = s[: -len(noise)].strip()
    return s.strip()


def is_valid_student_name(s: str) -> bool:
    if not s:
        return False
    cleaned = clean_extracted_name(s)
    if not cleaned or len(cleaned) < 3:
        return False
    if not NAME_RE.match(cleaned):
        return False
    upper = cleaned.upper()
    if upper.replace(" ", "").replace(",", "").isdigit():
        return False
    # Reject if any whole-word token is a garbage token.
    tokens = re.findall(r"[A-Za-z]+", upper)
    if any(t in GARBAGE_TOKENS for t in tokens):
        return False
    if any(upper.startswith(p) for p in PARENT_PREFIXES):
        return False
    return True


def is_valid_dob(s: str) -> bool:
    if not s:
        return False
    m = DOB_RE.match(s)
    if not m:
        return False
    mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mm <= 12) or not (1 <= dd <= 31):
        return False
    # Year window: 1900-2010
    yyyy = yy if yy >= 100 else (1900 + yy if yy >= 30 else 2000 + yy)
    if not (1900 <= yyyy <= 2010):
        return False
    # Reject obvious placeholder patterns where mm == dd == yy.
    if mm == dd == yy:
        return False
    return True
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_validators.py -v
```

Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/validators.py textract_probe/tests/test_validators.py
git commit -m "feat(textract_probe): Tier 1 garbage filter + name regex + DOB validator"
```

---

## Task 5: Multi-source name voter

**Files:**
- Create: `textract_probe/name_voter.py`
- Create: `textract_probe/tests/test_name_voter.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_name_voter.py`:

```python
import pytest

from textract_probe.name_voter import NameVote, vote_on_name


def test_three_sources_agree_high_confidence():
    sources = [
        ("forms_name",      "Owen, Randall Horton", 87.0),
        ("queries_record",  "Owen, Randall Horton", 91.0),
        ("queries_top",     "Owen, Randall Horton", 79.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Owen, Randall Horton"
    assert r.agreement == 3
    assert r.confidence >= 0.85
    assert set(r.sources) == {"forms_name", "queries_record", "queries_top"}


def test_two_sources_agree_one_disagrees():
    sources = [
        ("forms_name",     "Bunt",  81.0),
        ("queries_record", "Bunt",  78.0),
        ("detect_first",   "Judy",  60.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Bunt"
    assert r.agreement == 2


def test_garbage_inputs_filtered_out():
    sources = [
        ("forms_name",      "BIRTH",                  95.0),  # garbage
        ("queries_record",  "Markley, Jenelyn",       62.0),
        ("queries_top",     "Markley, Jenelyn",       72.0),
        ("detect_first",    "(LAST)",                  99.0),  # garbage
    ]
    r = vote_on_name(sources)
    assert r.name == "Markley, Jenelyn"
    assert r.agreement == 2


def test_no_valid_sources_returns_empty():
    sources = [
        ("forms_name",      "BIRTH", 95.0),
        ("queries_record",  "1887", 92.0),
    ]
    r = vote_on_name(sources)
    assert r.name == ""
    assert r.agreement == 0
    assert r.confidence == 0.0


def test_single_high_confidence_source_keeps_low_confidence():
    """One valid source at 92% conf, no agreement — confidence reflects it."""
    sources = [
        ("queries_record", "Paulerson, Rebecca", 99.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Paulerson, Rebecca"
    assert r.agreement == 1
    # Confidence is dampened because no agreement.
    assert 0.40 <= r.confidence <= 0.65


def test_name_normalization_for_agreement():
    """'Markley, Judith' and 'MARKLEY, Judith,' should count as agreement."""
    sources = [
        ("queries_record", "Markley, Judith", 27.0),
        ("queries_top",    "MARKLEY, Judith,", 46.0),
    ]
    r = vote_on_name(sources)
    assert r.name in {"Markley, Judith", "MARKLEY, Judith"}
    assert r.agreement == 2
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_name_voter.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.name_voter'`.

- [ ] **Step 3: Implement voter**

Create `textract_probe/name_voter.py`:

```python
"""Multi-source name voter — combines Forms, Queries, and Detect/regex sources.

Each candidate (source_name, raw_text, raw_textract_confidence_0_to_100) is run
through Tier 1 validators. Survivors are normalized and vote-clustered.

The winning cluster is the one with the largest agreement count; ties broken by
sum-of-confidences. Returned `confidence` is a 0..1 score:

  - 3+ agreement      -> 0.85 + min(0.10, top_conf * 0.001)
  - 2  agreement      -> 0.75 + min(0.10, top_conf * 0.001)
  - 1  source         -> 0.40 + min(0.20, raw_conf * 0.002)
  - 0                 -> 0.0
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from textract_probe.validators import clean_extracted_name, is_valid_student_name


@dataclass
class NameVote:
    name: str
    confidence: float
    agreement: int
    sources: list[str] = field(default_factory=list)


def _normalize_for_match(s: str) -> str:
    """Lower-case, strip diacritics, collapse whitespace, drop trailing comma."""
    s = clean_extracted_name(s).lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip(" ,")
    return s


def vote_on_name(
    sources: list[tuple[str, str, float]],
) -> NameVote:
    """sources = list of (source_name, raw_text, raw_textract_confidence)."""
    valid: list[tuple[str, str, str, float]] = []
    for src, raw, conf in sources:
        cleaned = clean_extracted_name(raw)
        if not is_valid_student_name(cleaned):
            continue
        norm = _normalize_for_match(cleaned)
        valid.append((src, cleaned, norm, conf))

    if not valid:
        return NameVote(name="", confidence=0.0, agreement=0, sources=[])

    # Cluster by normalized form
    clusters: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for src, cleaned, norm, conf in valid:
        clusters[norm].append((src, cleaned, conf))

    def cluster_key(item: tuple[str, list[tuple[str, str, float]]]):
        norm, members = item
        return (len(members), sum(m[2] for m in members))

    winner_norm, winner_members = max(clusters.items(), key=cluster_key)
    agreement = len(winner_members)
    top_conf = max(m[2] for m in winner_members)
    # Pick the most-confident raw form as canonical.
    canonical = max(winner_members, key=lambda m: m[2])[1]
    sources_used = [m[0] for m in winner_members]

    if agreement >= 3:
        score = 0.85 + min(0.10, top_conf * 0.001)
    elif agreement == 2:
        score = 0.75 + min(0.10, top_conf * 0.001)
    elif agreement == 1:
        score = 0.40 + min(0.20, top_conf * 0.002)
    else:
        score = 0.0

    return NameVote(
        name=canonical,
        confidence=round(score, 3),
        agreement=agreement,
        sources=sources_used,
    )
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_name_voter.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/name_voter.py textract_probe/tests/test_name_voter.py
git commit -m "feat(textract_probe): multi-source name voter (Forms+Queries+Detect)"
```

---

## Task 6: Index-snap recall booster

**Files:**
- Create: `textract_probe/index_snap.py`
- Create: `textract_probe/tests/test_index_snap.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_index_snap.py`:

```python
import pytest

from textract_probe.index_snap import (
    parse_tables_into_index_rows,
    snap_packet_name_to_index,
    IndexRow,
)


def _table_resp(rows: list[list[str]]) -> dict:
    """Build a minimal Tables response for testing.

    rows[0] is the header row, rows[1:] are data rows.
    """
    blocks: list[dict] = []
    word_id = 0
    table_id = "table-1"
    cell_relationships = []
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, cell_text in enumerate(row, start=1):
            cell_id = f"cell-{r_idx}-{c_idx}"
            children: list[str] = []
            for token in cell_text.split():
                word_id += 1
                wid = f"word-{word_id}"
                blocks.append({"BlockType": "WORD", "Id": wid, "Text": token})
                children.append(wid)
            blocks.append({
                "BlockType": "CELL",
                "Id": cell_id,
                "RowIndex": r_idx,
                "ColumnIndex": c_idx,
                "Relationships": [{"Type": "CHILD", "Ids": children}] if children else [],
            })
            cell_relationships.append(cell_id)
    blocks.append({
        "BlockType": "TABLE",
        "Id": table_id,
        "Relationships": [{"Type": "CHILD", "Ids": cell_relationships}],
    })
    return {"Blocks": blocks}


def test_parse_index_table_extracts_rows():
    resp = _table_resp([
        ["#", "STUDENT LAST NAME", "FIRST NAME", "MIDDLE NAME", "DOB"],
        ["1", "Carter",            "Marcia",     "Anne",        "5-7-62"],
        ["2", "Bunt",              "Judy",       "",            "9-3-65"],
    ])
    rows = parse_tables_into_index_rows(resp)
    assert len(rows) == 2
    assert rows[0].last == "Carter"
    assert rows[0].first == "Marcia"
    assert rows[0].middle == "Anne"
    assert rows[0].dob == "5-7-62"
    assert rows[1].last == "Bunt"
    assert rows[1].first == "Judy"


def test_snap_last_name_only_to_full_record():
    index = [
        IndexRow(last="Carter", first="Marcia", middle="Anne",  dob="5-7-62"),
        IndexRow(last="Bunt",   first="Judy",   middle="",      dob="9-3-65"),
        IndexRow(last="Owen",   first="Randall", middle="Horton", dob="11-26-45"),
    ]
    snapped = snap_packet_name_to_index(
        last_raw="Bunt", first_raw="", middle_raw="", index=index
    )
    assert snapped.last == "Bunt"
    assert snapped.first == "Judy"
    assert snapped.dob == "9-3-65"


def test_snap_with_levenshtein_tolerance():
    index = [
        IndexRow(last="Owen",   first="Randall", middle="Horton", dob="11-26-45"),
    ]
    # OCR returned "Owen," with trailing comma — should still snap
    snapped = snap_packet_name_to_index(
        last_raw="Owen,", first_raw="", middle_raw="", index=index
    )
    assert snapped is not None
    assert snapped.first == "Randall"


def test_snap_no_match_returns_none():
    index = [IndexRow(last="Carter", first="Marcia", middle="", dob="5-7-62")]
    snapped = snap_packet_name_to_index(
        last_raw="Zzzzz", first_raw="", middle_raw="", index=index
    )
    assert snapped is None
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_index_snap.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.index_snap'`.

- [ ] **Step 3: Implement index-snap**

Create `textract_probe/index_snap.py`:

```python
"""Build roll-level index from Textract Tables responses + snap raw cover names.

Reuses the field structure (`last`, `first`, `middle`, `dob`) used elsewhere
in the codebase but does NOT import from poc/ — keeps textract_probe/ isolated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import Levenshtein


@dataclass(frozen=True)
class IndexRow:
    last: str
    first: str
    middle: str
    dob: str


# Header tokens we expect for the LAST/FIRST/MIDDLE/DOB columns.
HEADER_HINTS = {
    "last":   ("LAST",),
    "first":  ("FIRST",),
    "middle": ("MIDDLE",),
    "dob":    ("DOB", "BIRTH"),
}


def _by_id(blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {b["Id"]: b for b in blocks}


def _cell_text(cell: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    out: list[str] = []
    for rel in cell.get("Relationships", []) or []:
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []):
                child = by_id.get(cid)
                if child and child.get("BlockType") == "WORD":
                    out.append((child.get("Text") or "").strip())
    return " ".join(out).strip()


def _resolve_header_columns(
    grid: dict[tuple[int, int], str], rows: int, cols: int
) -> dict[str, int]:
    """Find which column index maps to last/first/middle/dob from the header row."""
    header_row_idx = 1
    # If row 1 is empty/noisy, scan rows 1..3
    for r in range(1, min(4, rows + 1)):
        non_empty = sum(1 for c in range(1, cols + 1) if grid.get((r, c), "").strip())
        if non_empty >= 3:
            header_row_idx = r
            break

    mapping: dict[str, int] = {}
    for c in range(1, cols + 1):
        text = grid.get((header_row_idx, c), "").upper()
        for field, hints in HEADER_HINTS.items():
            if field in mapping:
                continue
            if any(h in text for h in hints):
                mapping[field] = c
                break
    mapping["__header_row__"] = header_row_idx
    return mapping


def parse_tables_into_index_rows(resp: dict[str, Any]) -> list[IndexRow]:
    """Parse all TABLE blocks in `resp` into IndexRow tuples."""
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    out: list[IndexRow] = []
    for t in blocks:
        if t.get("BlockType") != "TABLE":
            continue
        cells = []
        for rel in t.get("Relationships", []) or []:
            if rel.get("Type") == "CHILD":
                for cid in rel.get("Ids", []):
                    c = by_id.get(cid)
                    if c and c.get("BlockType") == "CELL":
                        cells.append(c)
        if not cells:
            continue
        rows = max(c["RowIndex"] for c in cells)
        cols = max(c["ColumnIndex"] for c in cells)
        grid: dict[tuple[int, int], str] = {}
        for c in cells:
            grid[(c["RowIndex"], c["ColumnIndex"])] = _cell_text(c, by_id)
        col_map = _resolve_header_columns(grid, rows, cols)
        if "last" not in col_map or "first" not in col_map:
            continue
        header_row = col_map["__header_row__"]
        for r in range(header_row + 1, rows + 1):
            last  = grid.get((r, col_map["last"]),   "").strip()
            first = grid.get((r, col_map["first"]),  "").strip()
            middle = grid.get((r, col_map.get("middle", -1)), "").strip()
            dob   = grid.get((r, col_map.get("dob", -1)),    "").strip()
            if not last and not first:
                continue
            out.append(IndexRow(last=last, first=first, middle=middle, dob=dob))
    return out


def snap_packet_name_to_index(
    last_raw: str,
    first_raw: str,
    middle_raw: str,
    index: list[IndexRow],
    *,
    max_last_distance: int = 2,
    max_first_distance: int = 2,
    max_total_distance: int = 3,
) -> IndexRow | None:
    """Match (last_raw, first_raw, middle_raw) to nearest IndexRow by Levenshtein.

    `first_raw` may be empty — in that case match by last only.
    Returns the matched IndexRow, or None if no candidate within threshold.
    """
    if not index:
        return None
    last_q = (last_raw or "").strip().rstrip(",").upper()
    first_q = (first_raw or "").strip().upper()
    if not last_q:
        return None

    best: tuple[int, IndexRow] | None = None
    for row in index:
        d_last = Levenshtein.distance(last_q, row.last.upper())
        if d_last > max_last_distance:
            continue
        if first_q:
            d_first = Levenshtein.distance(first_q, row.first.upper())
            if d_first > max_first_distance:
                continue
            total = d_last + d_first
        else:
            d_first = 0
            total = d_last
        if total > max_total_distance:
            continue
        if best is None or total < best[0]:
            best = (total, row)
    return best[1] if best else None
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_index_snap.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/index_snap.py textract_probe/tests/test_index_snap.py
git commit -m "feat(textract_probe): roll-index parse + last-name-only snap booster"
```

---

## Task 7: Per-class router (cost-aware feature selection)

**Files:**
- Create: `textract_probe/router.py`
- Create: `textract_probe/tests/test_router.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_router.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from textract_probe.router import process_page


@patch("textract_probe.router.tc")
def test_router_index_page_runs_detect_plus_tables(mock_tc):
    """An index page should run Detect (cheap) then Tables (analyze)."""
    detect_resp = {
        "Blocks": (
            [{"BlockType": "LINE"}] * 100
            + [{"BlockType": "LAYOUT_TITLE"}]
            + [{"BlockType": "TABLE"}]
            + [{"BlockType": "CELL"}] * 200
        )
    }
    tables_resp = {"Blocks": [{"BlockType": "TABLE"}]}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)
    mock_tc.analyze_tables.return_value = (tables_resp, 0.015)

    res = process_page(b"PNG", queries=None)

    assert res["page_class"] == "student_records_index"
    assert res["spend_usd"] == pytest.approx(0.0015 + 0.015)
    mock_tc.detect_document_text.assert_called_once()
    mock_tc.analyze_tables.assert_called_once()
    mock_tc.analyze_all.assert_not_called()


@patch("textract_probe.router.tc")
def test_router_cover_runs_detect_plus_combined(mock_tc):
    """A student_cover triggers the expensive combined call."""
    detect_resp = {
        "Blocks": (
            [{"BlockType": "LINE"}] * 200
            + [{"BlockType": "LAYOUT_FIGURE"}]
            + [{"BlockType": "KEY_VALUE_SET", "EntityTypes": ["KEY"]}] * 50
            + [{"BlockType": "SIGNATURE"}] * 2
        )
    }
    combined_resp = {"Blocks": [{"BlockType": "PAGE"}]}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)
    mock_tc.analyze_all.return_value = (combined_resp, 0.0885)

    queries = [{"Text": "Q?", "Alias": "A"}]
    res = process_page(b"PNG", queries=queries)

    assert res["page_class"] == "student_cover"
    assert res["spend_usd"] == pytest.approx(0.0015 + 0.0885)
    mock_tc.analyze_all.assert_called_once()


@patch("textract_probe.router.tc")
def test_router_separator_styleA_only_detect(mock_tc):
    detect_resp = {"Blocks": [{"BlockType": "LINE"}] * 8}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)

    res = process_page(b"PNG", queries=None)

    assert res["page_class"] == "roll_separator"
    assert res["spend_usd"] == pytest.approx(0.0015)
    mock_tc.analyze_all.assert_not_called()
    mock_tc.analyze_tables.assert_not_called()


@patch("textract_probe.router.tc")
def test_router_leader_only_detect(mock_tc):
    detect_resp = {"Blocks": [{"BlockType": "LINE"}] * 30}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)

    res = process_page(b"PNG", queries=None)

    assert res["page_class"] == "roll_leader"
    assert res["spend_usd"] == pytest.approx(0.0015)
    mock_tc.analyze_all.assert_not_called()
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.router'`.

- [ ] **Step 3: Implement router**

Create `textract_probe/router.py`:

```python
"""Two-pass cost-aware router.

Pass 1 (cheap): Detect on every page, classify via layout-fingerprint rules.
Pass 2 (selective): per-class feature call.

| page_class            | Pass 2 features      | Pass 2 cost   |
|-----------------------|----------------------|---------------|
| student_cover         | analyze_all          | $0.0885       |
| student_records_index | analyze_tables       | $0.0150       |
| roll_separator        | (handled in Pass 1 by Detect — Style A & B both classifiable from Detect+Layout output via the analyze_all-on-cover mechanism is overkill) — for now, no Pass 2 |
| roll_leader           | none                 | $0            |
| student_test_sheet    | none                 | $0            |
| student_continuation  | none                 | $0            |
| unknown               | analyze_all          | $0.0885       |
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
    # roll_separator / roll_leader / test_sheet / continuation: no Pass 2.

    return {
        "page_class": page_class,
        "classifier_confidence": conf,
        "fingerprint": fp,
        "detect_response": detect_resp,
        "pass2_response": pass2_resp,
        "spend_usd": round(spend, 6),
    }
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_router.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/router.py textract_probe/tests/test_router.py
git commit -m "feat(textract_probe): two-pass cost-aware router"
```

---

## Task 8: End-to-end pipeline driver `extract_pipeline.py`

**Files:**
- Create: `textract_probe/extract_pipeline.py`

- [ ] **Step 1: Write the driver**

Create `textract_probe/extract_pipeline.py`:

```python
"""End-to-end V4 extractor — drives the full pure-code-logic pipeline.

For each fixture:
  1. Router decides page_class + which Textract calls to make.
  2. If `student_records_index`: parse Tables -> add IndexRows to the roll's index list.
  3. If `student_cover`: extract candidate names from Forms NAME, Forms-empty-VALUE
     bbox fallback, Queries v2 RECORD_NAME, Queries TOP_NAME, Detect first
     non-label LINE; vote; if vote returned only `last` (single token), snap
     to roll index.
  4. Emit a result row per page with class, name, dob, confidence, agreement,
     and per-page spend.

Writes:
  textract_probe/output/v4/<run_label>_results.jsonl
  textract_probe/output/v4/<run_label>_summary.txt

Usage:
  python3 -m textract_probe.extract_pipeline \
      --fixtures-file textract_probe/fixtures_round3.json \
      --queries-file textract_probe/queries_v2.json \
      --run-label round3_v4 \
      --budget-ceiling 2.00
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from textract_probe import bbox_extract, name_voter, validators
from textract_probe.convert import tif_to_png_bytes
from textract_probe.index_snap import (
    IndexRow,
    parse_tables_into_index_rows,
    snap_packet_name_to_index,
)
from textract_probe.router import process_page

SAMPLES = Path("samples")
OUT = Path("textract_probe/output/v4")


def _by_id(blocks):
    return {b["Id"]: b for b in blocks}


def _text_of(block, by_id):
    out = []
    for rel in block.get("Relationships", []) or []:
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []):
                c = by_id.get(cid)
                if c and c.get("BlockType") == "WORD":
                    out.append((c.get("Text") or "").strip())
    return " ".join(out).strip()


def _query_answer(resp, alias):
    if not resp:
        return ("", 0.0)
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    for q in [b for b in blocks if b.get("BlockType") == "QUERY"]:
        if (q.get("Query") or {}).get("Alias") != alias:
            continue
        for rel in q.get("Relationships", []) or []:
            if rel.get("Type") == "ANSWER":
                for rid in rel.get("Ids", []):
                    a = by_id.get(rid)
                    if a:
                        return (a.get("Text") or "", a.get("Confidence", 0.0))
    return ("", 0.0)


def _forms_name_value(resp):
    if not resp:
        return ("", 0.0)
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    keys = [
        b for b in blocks
        if b.get("BlockType") == "KEY_VALUE_SET"
        and "KEY" in (b.get("EntityTypes") or [])
    ]
    best = ("", 0.0)
    for k in keys:
        ktext = _text_of(k, by_id).upper()
        if "NAME" in ktext and "MOTHER" not in ktext and "FATHER" not in ktext \
                and "PARENT" not in ktext:
            val = ""
            for rel in k.get("Relationships", []) or []:
                if rel.get("Type") == "VALUE":
                    for vid in rel.get("Ids", []):
                        v = by_id.get(vid)
                        if v:
                            val = _text_of(v, by_id)
            conf = k.get("Confidence", 0.0)
            if val and conf > best[1]:
                best = (val, conf)
    return best


def _forms_empty_label_bbox_fallback(resp, label="LAST"):
    if not resp:
        return ("", 0.0)
    blocks = resp.get("Blocks", []) or []
    val = bbox_extract.extract_value_near_anchor(
        blocks, anchor_text=label, direction="right"
    )
    return (val, 50.0 if val else 0.0)


def _detect_first_non_label_line(detect_resp):
    blocks = detect_resp.get("Blocks", []) or []
    for b in blocks:
        if b.get("BlockType") != "LINE":
            continue
        text = (b.get("Text") or "").strip()
        if not text:
            continue
        # Skip obvious form labels.
        if validators.is_valid_student_name(text):
            return (text, b.get("Confidence", 0.0))
    return ("", 0.0)


def _process_one(
    fixture: dict,
    queries: list[dict] | None,
    roll_index_acc: list[IndexRow],
) -> dict[str, Any]:
    rel = fixture["rel_path"]
    label = fixture["label"]
    tif = SAMPLES / rel
    if not tif.exists():
        return {"label": label, "error": f"missing fixture: {tif}"}
    png = tif_to_png_bytes(tif)
    routed = process_page(png, queries=queries)

    pass2 = routed.get("pass2_response")
    detect = routed["detect_response"]
    page_class = routed["page_class"]
    spend = routed["spend_usd"]

    out: dict[str, Any] = {
        "label": label,
        "rel_path": rel,
        "expected_class": fixture.get("expected_class"),
        "expected_name": fixture.get("expected_name"),
        "page_class": page_class,
        "classifier_confidence": routed["classifier_confidence"],
        "spend_usd": spend,
    }

    if page_class == "student_records_index":
        rows = parse_tables_into_index_rows(pass2 or detect)
        roll_index_acc.extend(rows)
        out["index_rows_added"] = len(rows)
        return out

    if page_class != "student_cover":
        return out

    forms_name, forms_conf       = _forms_name_value(pass2)
    forms_bbox, forms_bbox_conf  = _forms_empty_label_bbox_fallback(pass2, "LAST")
    q_record, q_record_conf      = _query_answer(pass2, "RECORD_NAME")
    q_top,    q_top_conf         = _query_answer(pass2, "TOP_NAME")
    q_full,   q_full_conf        = _query_answer(pass2, "FULL_NAME")
    detect_first, detect_conf    = _detect_first_non_label_line(detect)

    sources = [
        ("forms_name",     forms_name,    forms_conf),
        ("forms_bbox",     forms_bbox,    forms_bbox_conf),
        ("queries_record", q_record,      q_record_conf),
        ("queries_top",    q_top,         q_top_conf),
        ("queries_full",   q_full,        q_full_conf),
        ("detect_first",   detect_first,  detect_conf),
    ]

    vote = name_voter.vote_on_name(sources)

    snapped = None
    if vote.name and " " not in vote.name and roll_index_acc:
        # Last-name-only winner — try snap.
        snapped = snap_packet_name_to_index(
            last_raw=vote.name, first_raw="", middle_raw="", index=roll_index_acc,
        )

    out["candidate_sources"] = [
        {"source": s, "raw": r, "conf": c} for (s, r, c) in sources
    ]
    out["vote_name"] = vote.name
    out["vote_confidence"] = vote.confidence
    out["vote_agreement"] = vote.agreement
    out["vote_sources"] = vote.sources
    out["snapped"] = (
        {"last": snapped.last, "first": snapped.first, "middle": snapped.middle, "dob": snapped.dob}
        if snapped else None
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures-file", required=True, type=Path)
    p.add_argument("--queries-file", type=Path, default=Path("textract_probe/queries_v2.json"))
    p.add_argument("--run-label", required=True, type=str)
    p.add_argument("--budget-ceiling", type=float, default=2.00)
    args = p.parse_args(argv)

    fixtures = json.loads(args.fixtures_file.read_text())
    queries  = json.loads(args.queries_file.read_text()) if args.queries_file.exists() else None

    OUT.mkdir(parents=True, exist_ok=True)
    results_jsonl = OUT / f"{args.run_label}_results.jsonl"
    summary_txt   = OUT / f"{args.run_label}_summary.txt"

    spend = 0.0
    rows = []
    roll_index_acc: list[IndexRow] = []

    with results_jsonl.open("w") as f:
        for fx in fixtures:
            if spend >= args.budget_ceiling:
                print(
                    f"HALT: budget ${args.budget_ceiling} reached (${spend:.4f})",
                    file=sys.stderr,
                )
                break
            r = _process_one(fx, queries, roll_index_acc)
            spend += r.get("spend_usd", 0.0)
            f.write(json.dumps(r, default=str) + "\n")
            rows.append(r)
            print(
                f"OK {r['label']:<35} class={r.get('page_class','?'):<22} "
                f"name={r.get('vote_name','-')[:30]:<30} agree={r.get('vote_agreement','-')} "
                f"conf={r.get('vote_confidence','-')} ${r['spend_usd']:.4f} "
                f"total=${spend:.4f}"
            )

    # Summary
    n_total = len(rows)
    n_correct = 0
    n_shipped = 0
    for r in rows:
        if r.get("expected_name") and r.get("vote_name"):
            exp = r["expected_name"].lower().strip()
            got = r["vote_name"].lower().strip()
            if got and (got in exp or exp in got):
                n_correct += 1
            if r.get("vote_confidence", 0) >= 0.60:
                n_shipped += 1

    summary = (
        f"V4 run: {args.run_label}\n"
        f"Fixtures processed: {n_total}\n"
        f"Total spend: ${spend:.4f}\n"
        f"Vote names matching expected (substring): {n_correct}\n"
        f"Pages eligible to ship (vote_confidence >= 0.60): {n_shipped}\n"
        f"Roll index accumulated rows: {len(roll_index_acc)}\n"
    )
    summary_txt.write_text(summary)
    print()
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Re-run V4 on round-3 fixtures (uses existing JSONs OK to re-spend ~$1)**

```bash
python3 -m textract_probe.extract_pipeline \
    --fixtures-file textract_probe/fixtures_round3.json \
    --queries-file textract_probe/queries_v2.json \
    --run-label round3_v4 \
    --budget-ceiling 2.00
```

Expected: ≤ ~$1.20 spent (Detect probe + analyze_all on covers); 13 result rows. The `_summary.txt` should report N_correct + N_shipped.

- [ ] **Step 3: Run V4 on the round-2 real-cover fixtures**

```bash
python3 -m textract_probe.extract_pipeline \
    --fixtures-file textract_probe/fixtures_round2.json \
    --queries-file textract_probe/queries_v2.json \
    --run-label round2_v4 \
    --budget-ceiling 1.00
```

Expected: ≤ ~$0.50 spent.

- [ ] **Step 4: Run V4 on the original 8-fixture mix to verify class routing**

```bash
python3 -m textract_probe.extract_pipeline \
    --fixtures-file textract_probe/fixtures.json \
    --queries-file textract_probe/queries_v2.json \
    --run-label round1_v4 \
    --budget-ceiling 1.00
```

Expected: ≤ ~$0.40. Index page should add IndexRows; covers should benefit from snap.

- [ ] **Step 5: Aggregate results into a §15 of the results doc**

Read the three `_summary.txt` files and the `_results.jsonl` files; compute aggregate precision (correct_at_conf>=0.60 / shipped_at_conf>=0.60) and aggregate recall (correct_at_any_conf / total_real_covers). Append a new `## 15. V4 pipeline measured results` section to `docs/2026-04-27-textract-bake-off-results.md`.

- [ ] **Step 6: Commit pipeline + results**

```bash
git add textract_probe/extract_pipeline.py docs/2026-04-27-textract-bake-off-results.md
git commit -m "feat(textract_probe): V4 end-to-end pipeline + measured results"
```

---

## Task 9: Final pytest sweep + plan reference update

**Files:**
- Modify: `textract_probe/README.md`

- [ ] **Step 1: Run full unit test suite**

```bash
pytest textract_probe/tests/ -v
```

Expected: ≥ 17 prior + 6 (layout) + 5 (bbox) + 25 (validators) + 6 (voter) + 4 (snap) + 4 (router) + 2 (analyze_all) = **69 passed**, 1 skipped (live smoke).

- [ ] **Step 2: Check existing `pytest -q` baseline still green**

```bash
pytest -q
```

Expected: prior 59 `tests/` + 69 `textract_probe/tests/` = **128 passed**, 7 skipped.

- [ ] **Step 3: Append V4 entry to `textract_probe/README.md`**

Add inside the existing `## Run` code block, just after the bake-off commands:

```bash
# V4 end-to-end pipeline (router + classifier + voter + snap)
python3 -m textract_probe.extract_pipeline \
    --fixtures-file textract_probe/fixtures_round3.json \
    --queries-file textract_probe/queries_v2.json \
    --run-label round3_v4 \
    --budget-ceiling 2.00
```

- [ ] **Step 4: Commit README**

```bash
git add textract_probe/README.md
git commit -m "docs(textract_probe): document V4 pipeline run command"
```

---

## Verification (end-to-end)

After all 9 tasks:

1. **Unit tests:**
   ```bash
   pytest -q
   ```
   128 passed, 7 skipped.

2. **V4 results doc has measured numbers:**
   ```bash
   grep -A 30 "## 15. V4 pipeline measured results" docs/2026-04-27-textract-bake-off-results.md
   ```
   Section exists, contains real precision/recall.

3. **Spot-check JSONL output:**
   ```bash
   head -3 textract_probe/output/v4/round3_v4_results.jsonl | python3 -m json.tool
   ```
   Each row has `vote_name`, `vote_confidence`, `vote_agreement`, `vote_sources`, optional `snapped`.

4. **Cumulative spend across V4 runs:** ≤ $3.00.

5. **`poc/` untouched:**
   ```bash
   git diff main -- poc/
   ```
   Empty diff.

---

## Out of scope (deferred)

- Bedrock retry tier. Only revisit if V4 measured precision < 90%.
- Custom Forms Adapter training. Same gate.
- Async API + S3-direct path. Phase 2 production work.
- Multipage TIF batching.
- D6-style modern multi-section form preprocessing (deskew/binarize). Add only if V4 router-empty-Forms-LAST fallback fails on those layouts.
- Co-record (Reus) splitter. Add only if measured pipeline mis-snaps co-records.
- Step Functions / Lambda packaging.
