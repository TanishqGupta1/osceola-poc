# Osceola Phase 1 POC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Claude Haiku 4.5 on Bedrock hits ≥85% name-match accuracy on Test Input ROLL 001 (1924 TIFs) vs 419 ground-truth Output PDFs.

**Architecture:** Sequential Python pipeline. TIF → Pillow PNG → Bedrock Converse (single-pass classify+extract, `tool_use` enforced schema) → JSONL results → name-change grouping → eval vs ground-truth filenames. No AWS infra. All local.

**Tech Stack:** Python 3.11+, boto3, Pillow, Pydantic v2, pytest, python-Levenshtein, python-dotenv.

**Spec:** `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md`.

---

## Pre-flight

**Blocker:** IAM user `Servflow-image1` lacks `bedrock:*`. Must be resolved (add policy or provide new key) before Task 5 (first Bedrock call). Earlier tasks can proceed without it.

Working directory: `/Users/tanishq/Documents/project-files/aws-s3`

---

## Task 1: Bootstrap repo + deps

**Files:**
- Create: `.gitignore` (augment existing)
- Modify: `requirements.txt`
- Create: `pyproject.toml`
- Create: `poc/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Init git if not already**

```bash
cd /Users/tanishq/Documents/project-files/aws-s3
git init 2>/dev/null || true
git config user.name "$(git config --global user.name || echo 'dev')"
git config user.email "$(git config --global user.email || echo 'dev@local')"
```

Expected: git repo exists (new or pre-existing).

- [ ] **Step 2: Add new deps to requirements.txt**

Replace `requirements.txt` content with:

```
boto3>=1.35.0
python-dotenv>=1.0.0
Pillow>=10.0.0
pydantic>=2.5.0
python-Levenshtein>=0.23.0
pytest>=8.0.0
```

- [ ] **Step 3: Install deps**

```bash
pip install -r requirements.txt
```

Expected: all packages install successfully.

- [ ] **Step 4: Create package skeletons**

```bash
mkdir -p poc tests poc/output
touch poc/__init__.py tests/__init__.py
```

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
```

- [ ] **Step 5: Add POC outputs to .gitignore**

Append to `.gitignore`:

```
poc/output/
samples/*/png/
samples/verify_probe/*.tif
samples/boundary_probe/*.tif
```

- [ ] **Step 6: Verify pytest discovers no tests (sanity)**

```bash
pytest
```

Expected: `no tests ran`. Exit code 5 (no tests) is OK.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pyproject.toml poc/__init__.py tests/__init__.py .gitignore
git commit -m "chore: bootstrap POC package structure and deps"
```

---

## Task 2: Pydantic schemas

**Files:**
- Create: `poc/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_schemas.py`:

```python
from poc.schemas import PageResult, StudentPacket, EvalReport, Separator, Student, RollMeta


def test_page_result_minimal():
    r = PageResult(
        frame="00001",
        roll_id="ROLL 001",
        page_class="unknown",
        separator=Separator(marker=None, roll_no=None),
        student=Student(),
        roll_meta=RollMeta(),
        confidence_overall=0.0,
        confidence_name=0.0,
        model_version="test",
        processed_at="2026-04-18T00:00:00Z",
        latency_ms=0,
    )
    assert r.page_class == "unknown"
    assert r.student.last == ""


def test_page_class_enum_validation():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PageResult(
            frame="00001",
            roll_id="ROLL 001",
            page_class="bogus",
            separator=Separator(marker=None, roll_no=None),
            student=Student(),
            roll_meta=RollMeta(),
            confidence_overall=0.0,
            confidence_name=0.0,
            model_version="test",
            processed_at="2026-04-18T00:00:00Z",
            latency_ms=0,
        )


def test_student_packet():
    p = StudentPacket(
        packet_id="roll001_001",
        last="SMITH", first="JOHN", middle="A",
        frames=["00006","00007"],
        flagged=False,
        avg_confidence=0.92,
    )
    assert p.frames == ["00006","00007"]


def test_eval_report_defaults():
    e = EvalReport(
        roll_id="ROLL 001",
        pages_total=1924,
        pages_classified=1900,
        packets_predicted=419,
        packets_ground_truth=419,
        exact_name_matches=380,
        partial_name_matches=30,
        no_match=9,
        accuracy_exact=0.906,
        accuracy_partial=0.978,
        unmatched_predictions=[],
        unmatched_ground_truth=[],
    )
    assert e.accuracy_exact == 0.906
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/test_schemas.py -v
```

Expected: ImportError / ModuleNotFoundError for `poc.schemas`.

- [ ] **Step 3: Implement schemas**

Create `poc/schemas.py`:

```python
from typing import Literal
from pydantic import BaseModel, Field

PageClass = Literal[
    "student_cover",
    "student_test_sheet",
    "student_continuation",
    "roll_separator",
    "roll_leader",
    "unknown",
]


class Separator(BaseModel):
    marker: Literal["START", "END"] | None = None
    roll_no: str | None = None


class Student(BaseModel):
    last: str = ""
    first: str = ""
    middle: str = ""
    dob: str = ""
    school: str = ""


class RollMeta(BaseModel):
    filmer: str = ""
    date: str = ""
    school: str = ""
    reel_no_cert: str = ""


class PageResult(BaseModel):
    frame: str
    roll_id: str
    page_class: PageClass
    separator: Separator
    student: Student
    roll_meta: RollMeta
    confidence_overall: float = Field(ge=0.0, le=1.0)
    confidence_name: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    model_version: str
    processed_at: str
    latency_ms: int


class StudentPacket(BaseModel):
    packet_id: str
    last: str
    first: str
    middle: str
    frames: list[str]
    flagged: bool
    avg_confidence: float


class EvalReport(BaseModel):
    roll_id: str
    pages_total: int
    pages_classified: int
    packets_predicted: int
    packets_ground_truth: int
    exact_name_matches: int
    partial_name_matches: int
    no_match: int
    accuracy_exact: float
    accuracy_partial: float
    unmatched_predictions: list[str]
    unmatched_ground_truth: list[str]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_schemas.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/schemas.py tests/test_schemas.py
git commit -m "feat: add Pydantic schemas for page result, student packet, eval report"
```

---

## Task 3: TIF → PNG conversion

**Files:**
- Create: `poc/convert.py`
- Create: `tests/test_convert.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_convert.py`:

```python
import io
from pathlib import Path
from PIL import Image

from poc.convert import tif_to_png_bytes


def _write_sample_tif(path: Path) -> None:
    img = Image.new("L", (200, 300), color=255)
    img.save(path, format="TIFF")


def test_tif_to_png_bytes_returns_png(tmp_path: Path):
    tif = tmp_path / "sample.tif"
    _write_sample_tif(tif)
    data = tif_to_png_bytes(tif)
    assert isinstance(data, bytes)
    # PNG magic bytes
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_tif_to_png_bytes_downscale(tmp_path: Path):
    tif = tmp_path / "big.tif"
    Image.new("L", (4000, 5000), color=255).save(tif, format="TIFF")
    data = tif_to_png_bytes(tif, max_side=1500)
    im = Image.open(io.BytesIO(data))
    assert max(im.size) <= 1500


def test_tif_to_png_bytes_mode_conversion(tmp_path: Path):
    tif = tmp_path / "cmyk.tif"
    Image.new("CMYK", (100, 100)).save(tif, format="TIFF")
    data = tif_to_png_bytes(tif)
    im = Image.open(io.BytesIO(data))
    assert im.mode in ("RGB", "L")
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/test_convert.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement convert**

Create `poc/convert.py`:

```python
import io
from pathlib import Path
from PIL import Image


def tif_to_png_bytes(path: str | Path, max_side: int = 1500) -> bytes:
    """Load TIF, downscale to max_side px, normalize mode to RGB, return PNG bytes."""
    img = Image.open(path)
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_convert.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/convert.py tests/test_convert.py
git commit -m "feat: add TIF to PNG bytes conversion with downscale"
```

---

## Task 4: Prompt template

**Files:**
- Create: `poc/prompts.py`
- Create: `tests/test_prompts.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_prompts.py`:

```python
from poc.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT


def test_system_prompt_mentions_six_classes():
    for cls in [
        "student_cover", "student_test_sheet", "student_continuation",
        "roll_separator", "roll_leader", "unknown",
    ]:
        assert cls in SYSTEM_PROMPT


def test_system_prompt_mentions_both_separator_styles():
    assert "clapperboard" in SYSTEM_PROMPT.lower()
    assert "certificate" in SYSTEM_PROMPT.lower()


def test_system_prompt_handles_rotation():
    assert "rotat" in SYSTEM_PROMPT.lower()


def test_tool_schema_has_required_fields():
    props = TOOL_SCHEMA["input_schema"]["properties"]
    for f in ["page_class", "separator", "student", "roll_meta",
              "confidence_overall", "confidence_name"]:
        assert f in props


def test_user_turn_text_non_empty():
    assert len(USER_TURN_TEXT.strip()) > 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_prompts.py -v
```

- [ ] **Step 3: Implement prompts**

Create `poc/prompts.py`:

```python
SYSTEM_PROMPT = """You classify and extract data from scanned microfilm pages of Osceola County School District student records (circa 1991-92). Each page belongs to one of six classes:

1. `student_cover` — primary cumulative/guidance record, typically has student name top-left, demographics, school, DOB. Florida Cumulative Guidance Record 1-12, Osceola Progress Report, Elementary Record.
2. `student_test_sheet` — standardized test form with student name printed or typed. Stanford Achievement Test, H&R First Reader, SAT Profile Graph.
3. `student_continuation` — back pages, comments, family data, health records — student name at top. Comments page, MCH 304 health record, Elementary family data page.
4. `roll_separator` — START or END card that bookends each roll. TWO visually distinct styles both count as `roll_separator`:
     - Style A (clapperboard): diagonal-hatched rectangles + "START" or "END" in large block text + boxed handwritten "ROLL NO. N"
     - Style B (certificate): printed "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" form with START or END heading, typed school name, handwritten date, filmer signature, reel number
5. `roll_leader` — non-student filler frames: blank page, vendor letterhead ("Total Information Management Systems" or "White's Microfilm Services"), microfilm resolution test target, district title page (Osceola County seal + "RECORDS DEPARTMENT"), filmer certification card without START/END marker, operator roll-identity card.
6. `unknown` — blank mid-roll, illegible, or unrecognized.

Images may be rotated 90°, 180°, or 270°; read orientation regardless. Images may be noisy, low-contrast, or partially missing — when in doubt use `unknown` with low confidence rather than guessing.

Extract student name from the TOP-LEFT of the form (per SOW). Only extract student fields when `page_class` is `student_*`. Leave them blank otherwise.

Extract separator fields (`marker`, `roll_no`) only when `page_class` is `roll_separator`.

Extract roll metadata (`filmer`, `date`, `school`, `reel_no_cert`) only from certification or operator leader cards — these appear once per roll near the start.

Self-report `confidence_overall` and `confidence_name` on a 0.0-1.0 scale based on legibility and certainty. Be honest — low confidence flags work for human review."""

USER_TURN_TEXT = "Classify this page and extract the fields. Respond only via the `classify_page` tool."

TOOL_SCHEMA = {
    "name": "classify_page",
    "description": "Return structured classification and extraction for one page.",
    "input_schema": {
        "type": "object",
        "required": [
            "page_class", "separator", "student", "roll_meta",
            "confidence_overall", "confidence_name",
        ],
        "properties": {
            "page_class": {
                "type": "string",
                "enum": [
                    "student_cover", "student_test_sheet", "student_continuation",
                    "roll_separator", "roll_leader", "unknown",
                ],
            },
            "separator": {
                "type": "object",
                "properties": {
                    "marker": {"type": ["string", "null"], "enum": ["START", "END", None]},
                    "roll_no": {"type": ["string", "null"]},
                },
            },
            "student": {
                "type": "object",
                "properties": {
                    "last": {"type": "string"},
                    "first": {"type": "string"},
                    "middle": {"type": "string"},
                    "dob": {"type": "string"},
                    "school": {"type": "string"},
                },
            },
            "roll_meta": {
                "type": "object",
                "properties": {
                    "filmer": {"type": "string"},
                    "date": {"type": "string"},
                    "school": {"type": "string"},
                    "reel_no_cert": {"type": "string"},
                },
            },
            "confidence_overall": {"type": "number", "minimum": 0, "maximum": 1},
            "confidence_name": {"type": "number", "minimum": 0, "maximum": 1},
            "notes": {"type": "string"},
        },
    },
}
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_prompts.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/prompts.py tests/test_prompts.py
git commit -m "feat: add Bedrock prompt + tool schema for classify+extract"
```

---

## Task 5: Bedrock client wrapper

**Blocker:** requires Bedrock IAM access. Confirm before starting:

```bash
python3 -c "
import os, boto3
from dotenv import dotenv_values
for k,v in dotenv_values('.env').items(): os.environ[k]=v
try:
    br = boto3.client('bedrock', region_name='us-west-2')
    r = br.list_foundation_models(byProvider='anthropic')
    print('OK:', len(r.get('modelSummaries',[])), 'models')
except Exception as e:
    print('BLOCKED:', str(e)[:200])
"
```

If `BLOCKED`: stop, resolve IAM, then proceed.

**Files:**
- Create: `poc/bedrock_client.py`
- Create: `tests/test_bedrock_client.py`

- [ ] **Step 1: Write failing unit tests (mocked boto3)**

Create `tests/test_bedrock_client.py`:

```python
from unittest.mock import MagicMock, patch

from poc.bedrock_client import classify_via_bedrock


def _mock_converse_response(tool_input: dict) -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {
                        "toolUseId": "tu_1",
                        "name": "classify_page",
                        "input": tool_input,
                    }}
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 1000, "outputTokens": 100, "totalTokens": 1100},
    }


@patch("poc.bedrock_client.boto3.client")
def test_classify_via_bedrock_parses_tool_use(mock_boto):
    fake_tool_input = {
        "page_class": "student_cover",
        "separator": {"marker": None, "roll_no": None},
        "student": {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "", "school": ""},
        "roll_meta": {"filmer": "", "date": "", "school": "", "reel_no_cert": ""},
        "confidence_overall": 0.9,
        "confidence_name": 0.88,
        "notes": "",
    }
    client = MagicMock()
    client.converse.return_value = _mock_converse_response(fake_tool_input)
    mock_boto.return_value = client

    result, usage = classify_via_bedrock(b"fake_png_bytes")
    assert result["page_class"] == "student_cover"
    assert result["student"]["last"] == "SMITH"
    assert usage["inputTokens"] == 1000


@patch("poc.bedrock_client.boto3.client")
def test_classify_via_bedrock_retries_on_throttling(mock_boto):
    from botocore.exceptions import ClientError
    client = MagicMock()
    # first call throttles, second succeeds
    throttle_err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}},
        "Converse",
    )
    client.converse.side_effect = [
        throttle_err,
        _mock_converse_response({
            "page_class": "unknown",
            "separator": {"marker": None, "roll_no": None},
            "student": {"last":"","first":"","middle":"","dob":"","school":""},
            "roll_meta": {"filmer":"","date":"","school":"","reel_no_cert":""},
            "confidence_overall": 0.1,
            "confidence_name": 0.0,
            "notes": "",
        }),
    ]
    mock_boto.return_value = client
    result, _ = classify_via_bedrock(b"x", max_retries=2, retry_base_delay=0.01)
    assert result["page_class"] == "unknown"
    assert client.converse.call_count == 2
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_bedrock_client.py -v
```

- [ ] **Step 3: Implement Bedrock wrapper**

Create `poc/bedrock_client.py`:

```python
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from poc.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT

DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-west-2")


def classify_via_bedrock(
    png_bytes: bytes,
    model_id: str = DEFAULT_MODEL_ID,
    region: str = DEFAULT_REGION,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Call Bedrock Converse with image + enforced tool schema. Returns (tool_input, usage)."""
    client = boto3.client("bedrock-runtime", region_name=region)

    messages = [
        {
            "role": "user",
            "content": [
                {"image": {"format": "png", "source": {"bytes": png_bytes}}},
                {"text": USER_TURN_TEXT},
            ],
        }
    ]
    tool_config = {
        "tools": [{"toolSpec": {
            "name": TOOL_SCHEMA["name"],
            "description": TOOL_SCHEMA["description"],
            "inputSchema": {"json": TOOL_SCHEMA["input_schema"]},
        }}],
        "toolChoice": {"tool": {"name": TOOL_SCHEMA["name"]}},
    }

    delay = retry_base_delay
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 1000, "temperature": 0.0},
            )
            content = resp["output"]["message"]["content"]
            for block in content:
                if "toolUse" in block:
                    return block["toolUse"]["input"], resp.get("usage", {})
            raise RuntimeError(f"no toolUse block: {content!r}")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in {"ThrottlingException", "ServiceUnavailableException", "InternalServerException"}:
                last_err = e
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError(f"exhausted retries: {last_err!r}")
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_bedrock_client.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/bedrock_client.py tests/test_bedrock_client.py
git commit -m "feat: add Bedrock Converse wrapper with tool_use + retry"
```

---

## Task 6: Per-page orchestrator

**Files:**
- Create: `poc/classify_extract.py`
- Create: `tests/test_classify_extract.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_classify_extract.py`:

```python
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from poc.classify_extract import classify_page


def _sample_tif(path: Path):
    Image.new("L", (200, 300), color=255).save(path, format="TIFF")


@patch("poc.classify_extract.classify_via_bedrock")
def test_classify_page_builds_page_result(mock_call, tmp_path: Path):
    mock_call.return_value = (
        {
            "page_class": "student_cover",
            "separator": {"marker": None, "roll_no": None},
            "student": {"last":"SMITH","first":"JOHN","middle":"A","dob":"","school":""},
            "roll_meta": {"filmer":"","date":"","school":"","reel_no_cert":""},
            "confidence_overall": 0.9,
            "confidence_name": 0.88,
            "notes": "",
        },
        {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
    )
    tif = tmp_path / "00123.tif"
    _sample_tif(tif)
    r = classify_page(tif, roll_id="ROLL 001")
    assert r.frame == "00123"
    assert r.roll_id == "ROLL 001"
    assert r.page_class == "student_cover"
    assert r.student.last == "SMITH"
    assert r.latency_ms >= 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_classify_extract.py -v
```

- [ ] **Step 3: Implement**

Create `poc/classify_extract.py`:

```python
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from poc.bedrock_client import DEFAULT_MODEL_ID, classify_via_bedrock
from poc.convert import tif_to_png_bytes
from poc.schemas import PageResult, RollMeta, Separator, Student

_FRAME_RE = re.compile(r"(\d{5})")


def _extract_frame(path: Path) -> str:
    m = _FRAME_RE.search(path.stem)
    return m.group(1) if m else path.stem


def classify_page(tif_path: str | Path, roll_id: str) -> PageResult:
    tif_path = Path(tif_path)
    png = tif_to_png_bytes(tif_path)
    t0 = time.monotonic()
    tool_input, _usage = classify_via_bedrock(png)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return PageResult(
        frame=_extract_frame(tif_path),
        roll_id=roll_id,
        page_class=tool_input["page_class"],
        separator=Separator(**tool_input.get("separator", {})),
        student=Student(**tool_input.get("student", {})),
        roll_meta=RollMeta(**tool_input.get("roll_meta", {})),
        confidence_overall=float(tool_input.get("confidence_overall", 0.0)),
        confidence_name=float(tool_input.get("confidence_name", 0.0)),
        notes=tool_input.get("notes", "") or "",
        model_version=DEFAULT_MODEL_ID,
        processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        latency_ms=latency_ms,
    )
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_classify_extract.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/classify_extract.py tests/test_classify_extract.py
git commit -m "feat: add per-page classify_page orchestrator"
```

---

## Task 7: Real Bedrock smoke test on 5 fixture TIFs

Skipped by default; runs only with env var set. Proves end-to-end round-trip before batch.

**Files:**
- Create: `tests/test_smoke_bedrock.py`

- [ ] **Step 1: Write smoke test**

Create `tests/test_smoke_bedrock.py`:

```python
import os
from pathlib import Path

import pytest

from poc.classify_extract import classify_page

SMOKE = os.environ.get("BEDROCK_SMOKE_TEST") == "1"
SAMPLES = Path("samples")

FIXTURES = [
    ("boundary_probe/t001_00005.tif", "roll_separator"),     # Style A START
    ("verify_probe/d1r001_01923.tif", "roll_separator"),     # Style B END
    ("test_input_roll001/00097.tif", "student_cover"),        # student
    ("boundary_probe/d3r028_00002.tif", "roll_leader"),       # letterhead
    ("boundary_probe/d5r064_00001.tif", "roll_leader"),       # resolution target
]


@pytest.mark.skipif(not SMOKE, reason="BEDROCK_SMOKE_TEST not set")
@pytest.mark.parametrize("rel_path,expected_class", FIXTURES)
def test_classify_fixture(rel_path, expected_class):
    tif = SAMPLES / rel_path
    assert tif.exists(), f"missing fixture: {tif}"
    r = classify_page(tif, roll_id="SMOKE")
    print(f"{rel_path}: predicted={r.page_class} conf={r.confidence_overall}")
    assert r.page_class == expected_class, (
        f"{rel_path}: expected {expected_class}, got {r.page_class}. "
        f"student={r.student} separator={r.separator}"
    )
```

- [ ] **Step 2: Run smoke test**

```bash
BEDROCK_SMOKE_TEST=1 pytest tests/test_smoke_bedrock.py -v -s
```

Expected: 5 passed. If any fail, iterate on prompt in `poc/prompts.py` before proceeding. Don't skip failures.

- [ ] **Step 3: Commit**

```bash
git add tests/test_smoke_bedrock.py
git commit -m "test: add Bedrock smoke test on 5 fixture TIFs"
```

---

## Task 8: Name-change grouping

**Files:**
- Create: `poc/group.py`
- Create: `tests/test_group.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_group.py`:

```python
from poc.group import group_pages
from poc.schemas import PageResult, Separator, Student, RollMeta


def _pg(frame, cls, last="", first="", conf=0.9, marker=None, roll_no=None):
    return PageResult(
        frame=frame, roll_id="ROLL 001", page_class=cls,
        separator=Separator(marker=marker, roll_no=roll_no),
        student=Student(last=last, first=first),
        roll_meta=RollMeta(),
        confidence_overall=conf, confidence_name=conf,
        model_version="t", processed_at="2026-04-18T00:00:00Z", latency_ms=0,
    )


def test_groups_consecutive_same_name():
    pages = [
        _pg("00001", "roll_leader"),
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SMITH", "JOHN"),
        _pg("00007", "student_continuation", "SMITH", "JOHN"),
        _pg("00008", "student_test_sheet", "JONES", "MARY"),
        _pg("00009", "student_cover", "JONES", "MARY"),
        _pg("01924", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages)
    assert len(packets) == 2
    assert packets[0].last == "SMITH"
    assert packets[0].frames == ["00006", "00007"]
    assert packets[1].last == "JONES"
    assert packets[1].frames == ["00008", "00009"]


def test_fallback_when_no_start_end():
    pages = [
        _pg("00001", "student_cover", "SMITH", "JOHN"),
        _pg("00002", "student_continuation", "SMITH", "JOHN"),
    ]
    packets = group_pages(pages)
    assert len(packets) == 1


def test_low_confidence_flags_packet():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SMITH", "JOHN", conf=0.5),
        _pg("00007", "student_continuation", "SMITH", "JOHN", conf=0.95),
        _pg("00008", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, confidence_threshold=0.7)
    assert packets[0].flagged is True
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_group.py -v
```

- [ ] **Step 3: Implement grouping**

Create `poc/group.py`:

```python
from poc.schemas import PageResult, StudentPacket


def _normalize(p: PageResult) -> str:
    return f"{p.student.last.upper().strip()}|{p.student.first.upper().strip()[:3]}"


def _has_name(p: PageResult) -> bool:
    return bool(p.student.last.strip() or p.student.first.strip())


def group_pages(
    pages: list[PageResult],
    confidence_threshold: float = 0.7,
) -> list[StudentPacket]:
    pages = sorted(pages, key=lambda p: p.frame)

    start_idx = 0
    end_idx = len(pages)
    for i, p in enumerate(pages):
        if p.page_class == "roll_separator" and p.separator.marker == "START":
            start_idx = i + 1
            break
    for i in range(len(pages) - 1, -1, -1):
        if pages[i].page_class == "roll_separator" and pages[i].separator.marker == "END":
            end_idx = i
            break
    window = pages[start_idx:end_idx]

    packets: list[StudentPacket] = []
    cur_frames: list[str] = []
    cur_confs: list[float] = []
    cur_last = cur_first = cur_middle = ""
    cur_key: str | None = None

    def flush():
        nonlocal cur_frames, cur_confs, cur_last, cur_first, cur_middle, cur_key
        if not cur_frames:
            return
        avg = sum(cur_confs) / len(cur_confs)
        pid = f"{pages[0].roll_id.lower().replace(' ', '')}_{len(packets)+1:03d}"
        packets.append(StudentPacket(
            packet_id=pid,
            last=cur_last, first=cur_first, middle=cur_middle,
            frames=list(cur_frames),
            flagged=any(c < confidence_threshold for c in cur_confs),
            avg_confidence=avg,
        ))
        cur_frames = []; cur_confs = []
        cur_last = cur_first = cur_middle = ""
        cur_key = None

    for p in window:
        if p.page_class not in {"student_cover", "student_test_sheet", "student_continuation"}:
            continue
        if not _has_name(p):
            if cur_frames:
                cur_frames.append(p.frame)
                cur_confs.append(p.confidence_name)
            continue
        k = _normalize(p)
        if k != cur_key:
            flush()
            cur_key = k
            cur_last = p.student.last.upper().strip()
            cur_first = p.student.first.upper().strip()
            cur_middle = p.student.middle.upper().strip()
        cur_frames.append(p.frame)
        cur_confs.append(p.confidence_name)
    flush()
    return packets
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_group.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/group.py tests/test_group.py
git commit -m "feat: add name-change grouping with START/END window"
```

---

## Task 9: Eval vs ground-truth PDFs

**Files:**
- Create: `poc/eval.py`
- Create: `tests/test_eval.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_eval.py`:

```python
from poc.eval import parse_pdf_filename, evaluate
from poc.schemas import StudentPacket


def test_parse_clean_filename():
    got = parse_pdf_filename("ACKLEY, CALVIN CHARLES.pdf")
    assert got == {"last": "ACKLEY", "first": "CALVIN", "middle": "CHARLES"}


def test_parse_partial_filename_drops_placeholders():
    got = parse_pdf_filename("(LAST) Buston Jerry.pdf")
    assert got is None


def test_parse_with_underscore_dup():
    got = parse_pdf_filename("ALLEN, TAMMY_1.pdf")
    assert got == {"last": "ALLEN", "first": "TAMMY", "middle": ""}


def test_evaluate_exact_match():
    packets = [
        StudentPacket(packet_id="r001_001", last="SMITH", first="JOHN",
                      middle="A", frames=["00006"], flagged=False, avg_confidence=0.9),
        StudentPacket(packet_id="r001_002", last="JONES", first="MARY",
                      middle="", frames=["00010"], flagged=False, avg_confidence=0.9),
    ]
    gt = ["SMITH, JOHN A.pdf", "JONES, MARY.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.exact_name_matches == 2
    assert report.accuracy_exact == 1.0


def test_evaluate_partial_match_levenshtein():
    packets = [
        StudentPacket(packet_id="r001_001", last="SNITH", first="JOHN",
                      middle="A", frames=["00006"], flagged=False, avg_confidence=0.9),
    ]
    gt = ["SMITH, JOHN A.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001", max_levenshtein=2)
    assert report.partial_name_matches >= 1
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_eval.py -v
```

- [ ] **Step 3: Implement eval**

Create `poc/eval.py`:

```python
import re
from pathlib import Path
from typing import Iterable

import Levenshtein

from poc.schemas import EvalReport, StudentPacket

_PLACEHOLDER_RE = re.compile(r"\(LAST\)|\(FIRST\)|\(MIDDLE\)", re.I)
_TRAILING_DUP = re.compile(r"_\d+$")


def parse_pdf_filename(fname: str) -> dict[str, str] | None:
    """Parse ground-truth PDF filename. Return None if placeholder (AI-failure case)."""
    stem = Path(fname).stem
    if _PLACEHOLDER_RE.search(stem):
        return None
    stem = _TRAILING_DUP.sub("", stem)
    if "," in stem:
        last, rest = stem.split(",", 1)
        rest = rest.strip()
        tokens = rest.split()
        first = tokens[0] if tokens else ""
        middle = " ".join(tokens[1:]) if len(tokens) > 1 else ""
    else:
        tokens = stem.split()
        if len(tokens) >= 2:
            last, first, *mid = tokens
            middle = " ".join(mid)
        elif tokens:
            last = tokens[0]; first = ""; middle = ""
        else:
            return None
    return {"last": last.upper().strip(), "first": first.upper().strip(), "middle": middle.upper().strip()}


def _key(last: str, first: str) -> str:
    return f"{last}|{first}"


def evaluate(
    packets: list[StudentPacket],
    ground_truth_filenames: Iterable[str],
    roll_id: str,
    max_levenshtein: int = 2,
) -> EvalReport:
    gt_parsed: list[dict[str, str]] = []
    for fn in ground_truth_filenames:
        p = parse_pdf_filename(fn)
        if p is not None:
            gt_parsed.append(p)

    gt_used: set[int] = set()
    exact = 0; partial = 0; nomatch = 0
    unmatched_pred: list[str] = []

    for pkt in packets:
        pkt_last = pkt.last.upper().strip()
        pkt_first = pkt.first.upper().strip()
        pkt_middle = pkt.middle.upper().strip()

        # exact match first
        best_idx = -1; best_level = "none"
        for i, gt in enumerate(gt_parsed):
            if i in gt_used:
                continue
            if gt["last"] == pkt_last and gt["first"] == pkt_first:
                if gt["middle"] == pkt_middle or not pkt_middle or not gt["middle"]:
                    best_idx = i; best_level = "exact"; break
                else:
                    best_idx = i; best_level = "partial"
        if best_level == "none":
            for i, gt in enumerate(gt_parsed):
                if i in gt_used:
                    continue
                if (Levenshtein.distance(gt["last"], pkt_last) <= max_levenshtein
                    and Levenshtein.distance(gt["first"], pkt_first) <= max_levenshtein):
                    best_idx = i; best_level = "partial"; break

        if best_level == "exact":
            exact += 1; gt_used.add(best_idx)
        elif best_level == "partial":
            partial += 1; gt_used.add(best_idx)
        else:
            nomatch += 1
            unmatched_pred.append(_key(pkt_last, pkt_first))

    unmatched_gt = [_key(gt_parsed[i]["last"], gt_parsed[i]["first"])
                    for i in range(len(gt_parsed)) if i not in gt_used]

    total_predicted = len(packets)
    return EvalReport(
        roll_id=roll_id,
        pages_total=0,
        pages_classified=0,
        packets_predicted=total_predicted,
        packets_ground_truth=len(gt_parsed),
        exact_name_matches=exact,
        partial_name_matches=partial,
        no_match=nomatch,
        accuracy_exact=(exact / total_predicted) if total_predicted else 0.0,
        accuracy_partial=((exact + partial) / total_predicted) if total_predicted else 0.0,
        unmatched_predictions=unmatched_pred,
        unmatched_ground_truth=unmatched_gt,
    )
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_eval.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/eval.py tests/test_eval.py
git commit -m "feat: add eval against ground-truth PDF filenames"
```

---

## Task 10: `run_poc.py` orchestrator

**Files:**
- Create: `poc/run_poc.py`

- [ ] **Step 1: Implement runner**

Create `poc/run_poc.py`:

```python
"""
Usage:
  # Process first 20 TIFs for prompt iteration:
  python -m poc.run_poc --roll-id "ROLL 001" \
      --input samples/test_input_roll001 \
      --ground-truth samples/output_pdfs_district1_roll001 \
      --limit 20

  # Full run:
  python -m poc.run_poc --roll-id "ROLL 001" \
      --input samples/test_input_roll001 \
      --ground-truth samples/output_pdfs_district1_roll001

Outputs to poc/output/<roll_slug>_{pages.jsonl,students.json,eval.json}.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import dotenv_values

from poc.classify_extract import classify_page
from poc.eval import evaluate
from poc.group import group_pages
from poc.schemas import PageResult


def _load_env():
    for k, v in dotenv_values(".env").items():
        os.environ.setdefault(k, v)


def _slug(roll_id: str) -> str:
    return roll_id.lower().replace(" ", "_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roll-id", required=True)
    ap.add_argument("--input", required=True, help="dir of TIFs")
    ap.add_argument("--ground-truth", required=True, help="dir of PDFs")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--confidence-threshold", type=float, default=0.7)
    ap.add_argument("--output-dir", default="poc/output")
    args = ap.parse_args()

    _load_env()

    in_dir = Path(args.input)
    tifs = sorted(in_dir.glob("*.tif"))
    if args.limit:
        tifs = tifs[: args.limit]
    if not tifs:
        print(f"no .tif in {in_dir}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(args.roll_id)
    pages_path = out_dir / f"{slug}_pages.jsonl"
    students_path = out_dir / f"{slug}_students.json"
    eval_path = out_dir / f"{slug}_eval.json"

    results: list[PageResult] = []
    print(f"classifying {len(tifs)} tifs @ concurrency {args.concurrency}")
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex, pages_path.open("w") as pf:
        futs = {ex.submit(classify_page, t, args.roll_id): t for t in tifs}
        for i, fut in enumerate(as_completed(futs), 1):
            tif = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                print(f"  [{i}/{len(tifs)}] {tif.name}: ERROR {e!r}", file=sys.stderr)
                continue
            results.append(r)
            pf.write(r.model_dump_json() + "\n")
            if i % 25 == 0 or i == len(tifs):
                print(f"  [{i}/{len(tifs)}] last={r.frame} class={r.page_class} conf={r.confidence_overall:.2f}")

    packets = group_pages(results, confidence_threshold=args.confidence_threshold)
    students_path.write_text(json.dumps([p.model_dump() for p in packets], indent=2))
    print(f"wrote {len(packets)} packets → {students_path}")

    gt_files = [p.name for p in Path(args.ground_truth).glob("*.pdf")]
    report = evaluate(packets, gt_files, roll_id=args.roll_id)
    report.pages_total = len(tifs)
    report.pages_classified = len(results)
    eval_path.write_text(report.model_dump_json(indent=2))
    print(f"eval: exact={report.accuracy_exact:.1%} partial={report.accuracy_partial:.1%} "
          f"({report.exact_name_matches}/{report.packets_predicted} exact) → {eval_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke run on 20-page subset**

```bash
python -m poc.run_poc \
  --roll-id "ROLL 001" \
  --input samples/test_input_roll001 \
  --ground-truth samples/output_pdfs_district1_roll001 \
  --limit 20
```

Expected: 3 output files in `poc/output/`. Inspect `roll_001_pages.jsonl` manually — confirm class distribution matches expectations (most will be `student_*`, maybe 1-2 `roll_leader`).

- [ ] **Step 3: Commit**

```bash
git add poc/run_poc.py
git commit -m "feat: add run_poc.py orchestrator"
```

---

## Task 11: Download full ROLL 001 + run

**Files:** no code changes; data pull.

- [ ] **Step 1: Pull full ROLL 001 from S3**

```bash
python3 << 'EOF'
import boto3, os
from dotenv import dotenv_values
for k,v in dotenv_values('.env').items(): os.environ[k]=v
s3 = boto3.client('s3', region_name='us-west-2')
BUCKET='servflow-image-one'
PREFIX='Osceola Co School District/Test Input/ROLL 001/'
os.makedirs('samples/test_input_roll001_full', exist_ok=True)
paginator = s3.get_paginator('list_objects_v2')
count = 0
for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
    for obj in page.get('Contents', []):
        k = obj['Key']
        if not k.endswith('.tif'):
            continue
        out = f"samples/test_input_roll001_full/{k.split('/')[-1]}"
        if os.path.exists(out): continue
        s3.download_file(BUCKET, k, out)
        count += 1
        if count % 100 == 0:
            print(f'  pulled {count}')
print(f'done: {count} new files')
EOF
ls samples/test_input_roll001_full/*.tif | wc -l
```

Expected: 1924 TIFs.

- [ ] **Step 2: Full POC run**

```bash
python -m poc.run_poc \
  --roll-id "ROLL 001" \
  --input samples/test_input_roll001_full \
  --ground-truth samples/output_pdfs_district1_roll001 \
  --concurrency 10 \
  > poc/output/run_full.log 2>&1
```

Expected: runs to completion, eval.json written. Runtime 10-60 min depending on Bedrock quota.

- [ ] **Step 3: Review eval**

```bash
cat poc/output/roll_001_eval.json
```

Pass criteria: `accuracy_partial >= 0.85`. If lower, iterate on prompt in `poc/prompts.py`, rerun on a 100-page subset, commit improvement, then re-run full.

- [ ] **Step 4: Commit results + notes**

```bash
git add poc/output/*.json poc/output/*.log docs/superpowers/specs/ docs/superpowers/plans/
git commit -m "feat: complete Phase 1 POC on ROLL 001 with measured accuracy"
```

---

## Task 12: Write accuracy report

**Files:**
- Create: `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-results.md`

- [ ] **Step 1: Write results doc**

Template to fill in:

```markdown
# Osceola Phase 1 POC — Results

**Date:** YYYY-MM-DD
**Model:** claude-haiku-4-5 (Bedrock us-west-2)
**Dataset:** Test Input ROLL 001 (1924 TIFs) vs Output/ROLL 001 PDFs (419 ground-truth)

## Measured accuracy

| Metric | Value |
|---|---|
| Pages total | 1924 |
| Pages classified | N |
| Packets predicted | N |
| Packets ground-truth | 419 |
| Exact name matches | N |
| Partial name matches | N |
| No match | N |
| **accuracy_exact** | N% |
| **accuracy_partial** | N% |

## Class distribution

(from pages.jsonl aggregation)

| Class | Count |
|---|---|
| student_cover | N |
| student_test_sheet | N |
| student_continuation | N |
| roll_separator | N |
| roll_leader | N |
| unknown | N |

## Confidence distribution

- Mean overall confidence: X
- Pages below 0.7 threshold: N
- Pages flagged for HITL: N

## Failure modes observed

- (list top 5-10 failure patterns from unmatched_predictions + unmatched_ground_truth)

## Prompt iterations tried

1. v1 (initial): X% partial
2. v2 (<change>): Y% partial
3. ...

## Go/no-go recommendation

- If partial ≥ 85%: GO for Phase 2 (single-roll prod)
- Else: iterate further before proceeding

## Next steps

- Phase 2 spec: <link>
- Remaining risks: <list>
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-04-18-osceola-phase1-poc-results.md
git commit -m "docs: record Phase 1 POC accuracy + go/no-go recommendation"
```

---

## Done criteria

- [ ] All unit tests pass: `pytest` green
- [ ] Bedrock smoke test passes on 5 fixtures
- [ ] Full ROLL 001 run produces `poc/output/roll_001_eval.json`
- [ ] Measured `accuracy_partial >= 0.85` on ROLL 001
- [ ] Results doc written with go/no-go
- [ ] Every task committed

## Self-review

- Spec coverage: every section of the spec has a task (schemas→2, convert→3, prompts→4, bedrock→5, orchestrator→6, smoke→7, group→8, eval→9, runner→10, full run→11, report→12). ✓
- Placeholder scan: no TBDs, no "similar to above", all code literal. ✓
- Type consistency: `PageResult.page_class` enum matches tool_schema enum matches `group_pages` string checks. ✓
