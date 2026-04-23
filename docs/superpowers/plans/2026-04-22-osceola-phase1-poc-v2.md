# Osceola Phase 1 POC v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate existing `poc/` (currently matches v1 plan) to match v2 spec — adds `student_records_index` class, dual-env Bedrock loader, index-parse + H2.7 index-snap, GT-cleaning pass, pre/post-snap eval, `$10` budget ceiling.

**Architecture:** In-place edits to 7 existing modules plus 3 new modules (`env.py`, `index.py`, `gt_clean.py`). Each change is TDD-driven: failing test → minimal implementation → passing test → commit. No new top-level directories.

**Tech Stack:** Python 3.11+, boto3, Pillow, Pydantic v2, pytest, python-Levenshtein, python-dotenv.

**Spec:** `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md` (revised 2026-04-22).

---

## Pre-flight

Working directory: `/Users/tanishq/Documents/project-files/aws-s3`.

Current state (verified 2026-04-23):
- `poc/` exists with 8 modules + `run_poc.py` matching v1 plan.
- 28 unit tests under `tests/` all pass against v1 code.
- `.env` contains S3 creds (`Servflow-image1`). `.env.bedrock` contains Bedrock creds (`tanishq`, account `690816807846`, us-west-2).
- `python-Levenshtein` already installed.

Sanity step before Task 1:

```bash
cd /Users/tanishq/Documents/project-files/aws-s3
pytest -q
```

Expected: `28 passed` (smoke tests skip without `BEDROCK_SMOKE_TEST=1`).

If anything fails, stop and fix before proceeding — the plan assumes a green baseline.

---

## Task 1: Add `poc/env.py` dual-env loader

**Files:**
- Create: `poc/env.py`
- Create: `tests/test_env.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_env.py`:

```python
import os
from unittest.mock import MagicMock, patch

from poc import env


def test_load_dotenvs_populates_process_env(tmp_path, monkeypatch):
    s3 = tmp_path / ".env"
    br = tmp_path / ".env.bedrock"
    s3.write_text("AWS_ACCESS_KEY_ID=S3_KEY\nAWS_SECRET_ACCESS_KEY=S3_SECRET\n")
    br.write_text("AWS_ACCESS_KEY_ID=BR_KEY\nAWS_SECRET_ACCESS_KEY=BR_SECRET\n")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

    loaded = env.load_dotenvs(s3_path=s3, bedrock_path=br)
    assert loaded["s3"]["AWS_ACCESS_KEY_ID"] == "S3_KEY"
    assert loaded["bedrock"]["AWS_ACCESS_KEY_ID"] == "BR_KEY"


@patch("poc.env.boto3.client")
def test_s3_client_uses_s3_env(mock_boto, tmp_path):
    s3 = tmp_path / ".env"
    br = tmp_path / ".env.bedrock"
    s3.write_text("AWS_ACCESS_KEY_ID=S3_KEY\nAWS_SECRET_ACCESS_KEY=S3_SECRET\n")
    br.write_text("AWS_ACCESS_KEY_ID=BR_KEY\nAWS_SECRET_ACCESS_KEY=BR_SECRET\n")
    mock_boto.return_value = MagicMock()

    env.s3_client(s3_path=s3)
    args, kwargs = mock_boto.call_args
    assert args[0] == "s3"
    assert kwargs["aws_access_key_id"] == "S3_KEY"
    assert kwargs["region_name"] == "us-west-2"


@patch("poc.env.boto3.client")
def test_bedrock_client_uses_bedrock_env(mock_boto, tmp_path):
    s3 = tmp_path / ".env"
    br = tmp_path / ".env.bedrock"
    s3.write_text("AWS_ACCESS_KEY_ID=S3_KEY\nAWS_SECRET_ACCESS_KEY=S3_SECRET\n")
    br.write_text("AWS_ACCESS_KEY_ID=BR_KEY\nAWS_SECRET_ACCESS_KEY=BR_SECRET\n")
    mock_boto.return_value = MagicMock()

    env.bedrock_client(bedrock_path=br)
    args, kwargs = mock_boto.call_args
    assert args[0] == "bedrock-runtime"
    assert kwargs["aws_access_key_id"] == "BR_KEY"
    assert kwargs["region_name"] == "us-west-2"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_env.py -v
```

Expected: ImportError / ModuleNotFoundError for `poc.env`.

- [ ] **Step 3: Implement `poc/env.py`**

Create `poc/env.py`:

```python
"""Dual-env loader. S3 creds live in .env; Bedrock creds live in .env.bedrock.

Pipeline modules MUST use s3_client() / bedrock_client() from this module.
Never call boto3.client() directly — that risks cross-contamination of creds
(Servflow-image1 cannot call Bedrock; tanishq cannot list S3).
"""
from pathlib import Path

import boto3
from dotenv import dotenv_values

DEFAULT_REGION = "us-west-2"
REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_S3_ENV = REPO_ROOT / ".env"
_DEFAULT_BEDROCK_ENV = REPO_ROOT / ".env.bedrock"


def _load(path: Path) -> dict[str, str]:
    values = dotenv_values(path)
    return {k: v for k, v in values.items() if v}


def load_dotenvs(
    s3_path: Path | str = _DEFAULT_S3_ENV,
    bedrock_path: Path | str = _DEFAULT_BEDROCK_ENV,
) -> dict[str, dict[str, str]]:
    """Return the parsed contents of both .env files without mutating os.environ."""
    return {
        "s3": _load(Path(s3_path)),
        "bedrock": _load(Path(bedrock_path)),
    }


def s3_client(
    s3_path: Path | str = _DEFAULT_S3_ENV,
    region: str = DEFAULT_REGION,
) -> boto3.client:
    env = _load(Path(s3_path))
    return boto3.client(
        "s3",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", region),
    )


def bedrock_client(
    bedrock_path: Path | str = _DEFAULT_BEDROCK_ENV,
    region: str = DEFAULT_REGION,
) -> boto3.client:
    env = _load(Path(bedrock_path))
    return boto3.client(
        "bedrock-runtime",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", region),
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_env.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/env.py tests/test_env.py
git commit -m "feat: add poc/env.py dual-env loader for S3 + Bedrock clients"
```

---

## Task 2: Extend `poc/schemas.py` for v2 fields

**Files:**
- Modify: `poc/schemas.py`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_schemas.py` (keep existing tests, add these):

```python
from poc.schemas import IndexRow


def test_page_class_accepts_student_records_index():
    r = PageResult(
        frame="00011",
        roll_id="ROLL 001",
        page_class="student_records_index",
        separator=Separator(marker=None, roll_no=None),
        student=Student(),
        roll_meta=RollMeta(),
        index_rows=[IndexRow(last="SMITH", first="JOHN", middle="A",
                              dob="3/4/1975", source_frame="00011")],
        confidence_overall=0.9,
        confidence_name=0.9,
        model_version="t",
        processed_at="2026-04-22T00:00:00Z",
        latency_ms=10,
    )
    assert r.page_class == "student_records_index"
    assert r.index_rows[0].last == "SMITH"


def test_page_result_default_empty_index_rows():
    r = PageResult(
        frame="00001", roll_id="ROLL 001", page_class="unknown",
        separator=Separator(marker=None, roll_no=None),
        student=Student(), roll_meta=RollMeta(),
        confidence_overall=0.0, confidence_name=0.0,
        model_version="t", processed_at="2026-04-22T00:00:00Z", latency_ms=0,
    )
    assert r.index_rows == []
    assert r.tokens_in == 0
    assert r.tokens_out == 0
    assert r.usd_cost == 0.0


def test_student_packet_has_raw_and_snap_fields():
    p = StudentPacket(
        packet_id="r001_001",
        last_raw="SNITH", first_raw="JOHN", middle_raw="A",
        last="SMITH", first="JOHN", middle="A",
        frames=["00006"],
        flagged=False,
        avg_confidence=0.9,
        index_snap_applied=True,
        index_snap_distance=1,
    )
    assert p.last_raw == "SNITH"
    assert p.last == "SMITH"
    assert p.index_snap_distance == 1


def test_eval_report_has_pre_post_and_diagnostics():
    e = EvalReport(
        roll_id="ROLL 001",
        pages_total=1924, pages_classified=1900,
        packets_predicted=419, packets_ground_truth=400,
        gt_rows_raw=419, gt_rows_usable=400,
        gt_rows_dropped_reasons={"placeholder": 14, "ocr_garbage": 3, "numeric_only": 2},
        exact_matches_pre=300, partial_matches_pre=60, no_match_pre=59,
        accuracy_exact_pre=0.716, accuracy_partial_pre=0.859,
        exact_matches_post=350, partial_matches_post=55, no_match_post=14,
        accuracy_exact_post=0.835, accuracy_partial_post=0.966,
        index_frames_total=7, index_rows_total=165,
        packets_snapped=42,
        usd_total=2.15, tokens_in_total=1_850_000, tokens_out_total=93_000,
        unmatched_predictions=[], unmatched_ground_truth=[],
    )
    assert e.accuracy_partial_post == 0.966
    assert e.gt_rows_dropped_reasons["placeholder"] == 14
```

Remove the obsolete `test_eval_report_defaults` test (uses v1 field names). Keep all other existing v1 tests — they continue to pass because we add optional fields with defaults and don't remove any.

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_schemas.py -v
```

Expected: new tests ImportError (no `IndexRow`) or ValidationError (unknown fields). Existing `test_eval_report_defaults` failed first — it was deleted.

- [ ] **Step 3: Replace `poc/schemas.py`**

Overwrite `poc/schemas.py` with:

```python
from typing import Literal
from pydantic import BaseModel, Field

PageClass = Literal[
    "student_cover",
    "student_test_sheet",
    "student_continuation",
    "student_records_index",
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


class IndexRow(BaseModel):
    last: str
    first: str
    middle: str = ""
    dob: str = ""
    source_frame: str = ""


class PageResult(BaseModel):
    frame: str
    roll_id: str
    page_class: PageClass
    separator: Separator
    student: Student
    roll_meta: RollMeta
    index_rows: list[IndexRow] = []
    confidence_overall: float = Field(ge=0.0, le=1.0)
    confidence_name: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    model_version: str
    processed_at: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    usd_cost: float = 0.0


class StudentPacket(BaseModel):
    packet_id: str
    # Pre-snap (raw LLM majority across packet frames).
    last_raw: str
    first_raw: str
    middle_raw: str
    # Post-snap (equals raw when snap did not match / index empty).
    last: str
    first: str
    middle: str
    frames: list[str]
    flagged: bool
    avg_confidence: float
    index_snap_applied: bool = False
    index_snap_distance: int | None = None


class EvalReport(BaseModel):
    roll_id: str
    pages_total: int
    pages_classified: int
    packets_predicted: int
    packets_ground_truth: int
    gt_rows_raw: int = 0
    gt_rows_usable: int = 0
    gt_rows_dropped_reasons: dict[str, int] = {}
    exact_matches_pre: int = 0
    partial_matches_pre: int = 0
    no_match_pre: int = 0
    accuracy_exact_pre: float = 0.0
    accuracy_partial_pre: float = 0.0
    exact_matches_post: int = 0
    partial_matches_post: int = 0
    no_match_post: int = 0
    accuracy_exact_post: float = 0.0
    accuracy_partial_post: float = 0.0
    index_frames_total: int = 0
    index_rows_total: int = 0
    packets_snapped: int = 0
    usd_total: float = 0.0
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    unmatched_predictions: list[str] = []
    unmatched_ground_truth: list[str] = []
```

- [ ] **Step 4: Update the v1 `test_student_packet` test (renames to raw fields)**

Replace the existing `test_student_packet` in `tests/test_schemas.py` with:

```python
def test_student_packet():
    p = StudentPacket(
        packet_id="roll001_001",
        last_raw="SMITH", first_raw="JOHN", middle_raw="A",
        last="SMITH", first="JOHN", middle="A",
        frames=["00006","00007"],
        flagged=False,
        avg_confidence=0.92,
    )
    assert p.frames == ["00006","00007"]
    assert p.index_snap_applied is False
```

- [ ] **Step 5: Run — expect pass**

```bash
pytest tests/test_schemas.py -v
```

Expected: all schema tests pass. Existing `test_page_result_minimal` and `test_page_class_enum_validation` still pass because default-zero token fields don't break minimal-construction tests.

- [ ] **Step 6: Commit**

```bash
git add poc/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add student_records_index class, IndexRow, token+usd on PageResult, raw/snap on StudentPacket, pre/post on EvalReport"
```

---

## Task 3: Extend `poc/prompts.py` to 7 classes + `index_rows`

**Files:**
- Modify: `poc/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: Rewrite tests**

Replace `tests/test_prompts.py` content with:

```python
from poc.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT, MAX_OUTPUT_TOKENS


def test_system_prompt_mentions_seven_classes():
    for cls in [
        "student_cover", "student_test_sheet", "student_continuation",
        "student_records_index",
        "roll_separator", "roll_leader", "unknown",
    ]:
        assert cls in SYSTEM_PROMPT


def test_system_prompt_mentions_both_separator_styles():
    assert "clapperboard" in SYSTEM_PROMPT.lower()
    assert "certificate" in SYSTEM_PROMPT.lower()


def test_system_prompt_handles_rotation():
    assert "rotat" in SYSTEM_PROMPT.lower()


def test_system_prompt_describes_index_rows_behavior():
    text = SYSTEM_PROMPT.lower()
    assert "index_rows" in text
    assert "student_records_index" in text
    assert "empty" in text  # instructs empty array when class is not index


def test_tool_schema_has_required_fields():
    props = TOOL_SCHEMA["input_schema"]["properties"]
    for f in ["page_class", "separator", "student", "roll_meta",
              "confidence_overall", "confidence_name", "index_rows"]:
        assert f in props


def test_tool_schema_page_class_enum_has_seven():
    enum = TOOL_SCHEMA["input_schema"]["properties"]["page_class"]["enum"]
    assert set(enum) == {
        "student_cover", "student_test_sheet", "student_continuation",
        "student_records_index",
        "roll_separator", "roll_leader", "unknown",
    }


def test_tool_schema_index_rows_is_array_of_objects():
    spec = TOOL_SCHEMA["input_schema"]["properties"]["index_rows"]
    assert spec["type"] == "array"
    assert spec["items"]["type"] == "object"
    assert "last" in spec["items"]["required"]
    assert "first" in spec["items"]["required"]


def test_user_turn_text_non_empty():
    assert len(USER_TURN_TEXT.strip()) > 0


def test_max_output_tokens_is_1500():
    assert MAX_OUTPUT_TOKENS == 1500
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_prompts.py -v
```

Expected: multiple failures (no 7th class, no `index_rows`, no `MAX_OUTPUT_TOKENS`).

- [ ] **Step 3: Rewrite `poc/prompts.py`**

Overwrite with:

```python
MAX_OUTPUT_TOKENS = 1500

SYSTEM_PROMPT = """You classify and extract data from scanned microfilm pages of Osceola County School District student records (circa 1991-92). Each page belongs to one of seven classes:

1. `student_cover` — primary cumulative/guidance record, typically has student name top-left, demographics, school, DOB. Florida Cumulative Guidance Record 1-12, Osceola Progress Report, Elementary Record.
2. `student_test_sheet` — standardized test form with student name printed or typed. Stanford Achievement Test, H&R First Reader, SAT Profile Graph.
3. `student_continuation` — back pages, comments, family data, health records — student name at top. Comments page, MCH 304 health record, Elementary family data page.
4. `student_records_index` — tabular page titled "STUDENT RECORDS INDEX" listing many students on one page. Columns: LAST / FIRST / MIDDLE / DOB and district-specific variants (FILE, FRAME, Roll, SEC, OTHER, TRANS, WITH, GRAD, DATE, BE, CR, ES). 5-28 rows per page. Layout differs by school/district but class is the same. Appears multiple times per roll in alphabetical sections.
5. `roll_separator` — START or END card that bookends each roll. TWO visually distinct styles both count as `roll_separator`:
     - Style A (clapperboard): diagonal-hatched rectangles + "START" or "END" in large block text + boxed handwritten "ROLL NO. N"
     - Style B (certificate): printed "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" form with START or END heading, typed school name, handwritten date, filmer signature, reel number
6. `roll_leader` — non-student filler frames: blank page, vendor letterhead ("Total Information Management Systems" or "White's Microfilm Services"), microfilm resolution test target, district title page (Osceola County seal + "RECORDS DEPARTMENT"), filmer certification card without START/END marker, operator roll-identity card.
7. `unknown` — blank mid-roll, illegible, or unrecognized.

Images may be rotated 90°, 180°, or 270°; read orientation regardless. Images may be noisy, low-contrast, or partially missing — when in doubt use `unknown` with low confidence rather than guessing.

Extract student name from the TOP-LEFT of the form (per SOW). Only extract student fields when `page_class` is `student_cover`, `student_test_sheet`, or `student_continuation`. Leave them blank otherwise.

Extract separator fields (`marker`, `roll_no`) only when `page_class` is `roll_separator`.

Extract roll metadata (`filmer`, `date`, `school`, `reel_no_cert`) only from certification or operator leader cards — these appear once per roll near the start.

When `page_class` is `student_records_index`, populate the `index_rows` array with every visible row in the table. Each row is one object: `{last, first, middle, dob}`. Skip fully blank rows. If a district's layout lacks the DOB column, leave `dob` as an empty string. For every other value of `page_class`, `index_rows` MUST be an empty array.

Self-report `confidence_overall` and `confidence_name` on a 0.0-1.0 scale based on legibility and certainty. Be honest — low confidence flags work for human review."""

USER_TURN_TEXT = "Classify this page and extract the fields. Respond only via the `classify_page` tool."

TOOL_SCHEMA = {
    "name": "classify_page",
    "description": "Return structured classification and extraction for one page.",
    "input_schema": {
        "type": "object",
        "required": [
            "page_class", "separator", "student", "roll_meta",
            "confidence_overall", "confidence_name", "index_rows",
        ],
        "properties": {
            "page_class": {
                "type": "string",
                "enum": [
                    "student_cover", "student_test_sheet", "student_continuation",
                    "student_records_index",
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
            "index_rows": {
                "type": "array",
                "description": "Rows from a STUDENT RECORDS INDEX page. Empty array when page_class is not student_records_index.",
                "items": {
                    "type": "object",
                    "required": ["last", "first"],
                    "properties": {
                        "last": {"type": "string"},
                        "first": {"type": "string"},
                        "middle": {"type": "string"},
                        "dob": {"type": "string"},
                    },
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

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): expand to 7-class taxonomy, add index_rows schema, raise maxTokens to 1500"
```

---

## Task 4: Update `poc/bedrock_client.py` — use env.py, return spend

**Files:**
- Modify: `poc/bedrock_client.py`
- Modify: `tests/test_bedrock_client.py`

- [ ] **Step 1: Rewrite tests**

Replace `tests/test_bedrock_client.py` content with:

```python
from unittest.mock import MagicMock, patch

from poc.bedrock_client import classify_via_bedrock, compute_usd_cost


def _mock_converse_response(tool_input: dict, usage: dict | None = None) -> dict:
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
        "usage": usage or {"inputTokens": 1000, "outputTokens": 100, "totalTokens": 1100},
    }


_FAKE_INPUT = {
    "page_class": "student_cover",
    "separator": {"marker": None, "roll_no": None},
    "student": {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "", "school": ""},
    "roll_meta": {"filmer": "", "date": "", "school": "", "reel_no_cert": ""},
    "index_rows": [],
    "confidence_overall": 0.9,
    "confidence_name": 0.88,
    "notes": "",
}


@patch("poc.bedrock_client.env.bedrock_client")
def test_classify_via_bedrock_parses_tool_use(mock_factory):
    client = MagicMock()
    client.converse.return_value = _mock_converse_response(_FAKE_INPUT)
    mock_factory.return_value = client

    tool_input, usage, usd_cost = classify_via_bedrock(b"fake_png_bytes")
    assert tool_input["page_class"] == "student_cover"
    assert usage["inputTokens"] == 1000
    # 1000 input @ $1/MTok + 100 output @ $5/MTok = 0.001 + 0.0005 = 0.0015
    assert usd_cost == 0.0015


@patch("poc.bedrock_client.env.bedrock_client")
def test_classify_via_bedrock_retries_on_throttling(mock_factory):
    from botocore.exceptions import ClientError
    throttle = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "Converse")
    client = MagicMock()
    client.converse.side_effect = [
        throttle,
        _mock_converse_response({**_FAKE_INPUT, "page_class": "unknown"}),
    ]
    mock_factory.return_value = client

    tool_input, _usage, _usd = classify_via_bedrock(
        b"x", max_retries=2, retry_base_delay=0.01)
    assert tool_input["page_class"] == "unknown"
    assert client.converse.call_count == 2


@patch("poc.bedrock_client.env.bedrock_client")
def test_classify_via_bedrock_passes_max_tokens_1500(mock_factory):
    client = MagicMock()
    client.converse.return_value = _mock_converse_response(_FAKE_INPUT)
    mock_factory.return_value = client

    classify_via_bedrock(b"x")
    _, kwargs = client.converse.call_args
    assert kwargs["inferenceConfig"]["maxTokens"] == 1500


def test_compute_usd_cost_formula():
    # 2,000,000 in, 200,000 out -> 2.00 + 1.00 = 3.00
    assert compute_usd_cost(2_000_000, 200_000) == 3.0
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_bedrock_client.py -v
```

Expected: ImportError / AttributeError (no `compute_usd_cost`, signature mismatch).

- [ ] **Step 3: Rewrite `poc/bedrock_client.py`**

Overwrite with:

```python
import os
import time
from typing import Any

from botocore.exceptions import ClientError

from poc import env
from poc.prompts import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT

DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)

# Haiku 4.5 pricing as of 2026-04: $1.00 / MTok input, $5.00 / MTok output.
HAIKU_IN_USD_PER_MTOK = 1.00
HAIKU_OUT_USD_PER_MTOK = 5.00


def compute_usd_cost(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in / 1e6 * HAIKU_IN_USD_PER_MTOK) + (tokens_out / 1e6 * HAIKU_OUT_USD_PER_MTOK)


def classify_via_bedrock(
    png_bytes: bytes,
    model_id: str = DEFAULT_MODEL_ID,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], dict[str, int], float]:
    """Call Bedrock Converse with image + enforced tool schema.

    Returns (tool_input, usage, usd_cost).
    """
    client = env.bedrock_client()

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
    for _attempt in range(max_retries):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0.0},
            )
            content = resp["output"]["message"]["content"]
            usage = resp.get("usage", {}) or {}
            tokens_in = int(usage.get("inputTokens") or 0)
            tokens_out = int(usage.get("outputTokens") or 0)
            usd_cost = compute_usd_cost(tokens_in, tokens_out)
            for block in content:
                if "toolUse" in block:
                    return block["toolUse"]["input"], usage, usd_cost
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

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/bedrock_client.py tests/test_bedrock_client.py
git commit -m "feat(bedrock_client): route through poc.env, return usage+usd_cost, maxTokens=1500"
```

---

## Task 5: Update `poc/classify_extract.py` — surface index_rows + tokens + usd

**Files:**
- Modify: `poc/classify_extract.py`
- Modify: `tests/test_classify_extract.py`

- [ ] **Step 1: Rewrite test**

Replace `tests/test_classify_extract.py` content with:

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
            "index_rows": [],
            "confidence_overall": 0.9,
            "confidence_name": 0.88,
            "notes": "",
        },
        {"inputTokens": 1200, "outputTokens": 80, "totalTokens": 1280},
        0.0016,
    )
    tif = tmp_path / "00123.tif"
    _sample_tif(tif)
    r = classify_page(tif, roll_id="ROLL 001")
    assert r.frame == "00123"
    assert r.roll_id == "ROLL 001"
    assert r.page_class == "student_cover"
    assert r.student.last == "SMITH"
    assert r.index_rows == []
    assert r.tokens_in == 1200
    assert r.tokens_out == 80
    assert r.usd_cost == 0.0016
    assert r.latency_ms >= 0


@patch("poc.classify_extract.classify_via_bedrock")
def test_classify_page_passes_through_index_rows(mock_call, tmp_path: Path):
    mock_call.return_value = (
        {
            "page_class": "student_records_index",
            "separator": {"marker": None, "roll_no": None},
            "student": {"last":"","first":"","middle":"","dob":"","school":""},
            "roll_meta": {"filmer":"","date":"","school":"","reel_no_cert":""},
            "index_rows": [
                {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "3/4/75"},
                {"last": "JONES", "first": "MARY", "middle": "", "dob": ""},
            ],
            "confidence_overall": 0.95,
            "confidence_name": 0.9,
            "notes": "",
        },
        {"inputTokens": 1400, "outputTokens": 400, "totalTokens": 1800},
        0.0034,
    )
    tif = tmp_path / "00011.tif"
    _sample_tif(tif)
    r = classify_page(tif, roll_id="ROLL 001")
    assert r.page_class == "student_records_index"
    assert len(r.index_rows) == 2
    assert r.index_rows[0].last == "SMITH"
    assert r.index_rows[0].source_frame == "00011"
    assert r.index_rows[1].dob == ""
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_classify_extract.py -v
```

Expected: unpacking error (function returns 2-tuple, test expects 3-tuple) + attribute errors.

- [ ] **Step 3: Rewrite `poc/classify_extract.py`**

Overwrite with:

```python
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from poc.bedrock_client import DEFAULT_MODEL_ID, classify_via_bedrock
from poc.convert import tif_to_png_bytes
from poc.schemas import IndexRow, PageResult, RollMeta, Separator, Student

_FRAME_RE = re.compile(r"(\d{5})")


def _extract_frame(path: Path) -> str:
    m = _FRAME_RE.search(path.stem)
    return m.group(1) if m else path.stem


def _build_index_rows(raw_rows: list[dict], source_frame: str) -> list[IndexRow]:
    out: list[IndexRow] = []
    for r in raw_rows or []:
        if not isinstance(r, dict):
            continue
        last = (r.get("last") or "").strip()
        first = (r.get("first") or "").strip()
        if not last and not first:
            continue
        out.append(IndexRow(
            last=last,
            first=first,
            middle=(r.get("middle") or "").strip(),
            dob=(r.get("dob") or "").strip(),
            source_frame=source_frame,
        ))
    return out


def classify_page(tif_path: str | Path, roll_id: str) -> PageResult:
    tif_path = Path(tif_path)
    png = tif_to_png_bytes(tif_path)
    frame = _extract_frame(tif_path)
    t0 = time.monotonic()
    tool_input, usage, usd_cost = classify_via_bedrock(png)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return PageResult(
        frame=frame,
        roll_id=roll_id,
        page_class=tool_input["page_class"],
        separator=Separator(**tool_input.get("separator", {})),
        student=Student(**tool_input.get("student", {})),
        roll_meta=RollMeta(**tool_input.get("roll_meta", {})),
        index_rows=_build_index_rows(tool_input.get("index_rows", []), frame),
        confidence_overall=float(tool_input.get("confidence_overall", 0.0)),
        confidence_name=float(tool_input.get("confidence_name", 0.0)),
        notes=tool_input.get("notes", "") or "",
        model_version=DEFAULT_MODEL_ID,
        processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        latency_ms=latency_ms,
        tokens_in=int(usage.get("inputTokens") or 0),
        tokens_out=int(usage.get("outputTokens") or 0),
        usd_cost=usd_cost,
    )
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_classify_extract.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/classify_extract.py tests/test_classify_extract.py
git commit -m "feat(classify_extract): surface index_rows + tokens + usd_cost on PageResult"
```

---

## Task 6: Create `poc/gt_clean.py` — GT filename cleaner with drop reasons

**Files:**
- Create: `poc/gt_clean.py`
- Create: `tests/test_gt_clean.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_gt_clean.py`:

```python
from poc.gt_clean import clean_gt_filename, DROP_REASONS


def _call(fname: str):
    return clean_gt_filename(fname)


def test_clean_standard_uppercase():
    r = _call("SMITH, JOHN A.pdf")
    assert r == {"last": "SMITH", "first": "JOHN", "middle": "A"}


def test_clean_titlecase_normalizes_to_upper():
    r = _call("Smith, John Anthony.pdf")
    assert r == {"last": "SMITH", "first": "JOHN", "middle": "ANTHONY"}


def test_placeholder_drops():
    r, reason = clean_gt_filename("(LAST) Buston Jerry.pdf", return_reason=True)
    assert r is None
    assert reason == "placeholder"


def test_ocr_garbage_drops():
    r, reason = clean_gt_filename("(LAST) (FIRST) MIDDLE) COUNTY Barton, Virginia.pdf",
                                   return_reason=True)
    assert r is None
    # placeholder fires before OCR garbage; either is acceptable but must drop.
    assert reason in {"placeholder", "ocr_garbage"}


def test_numeric_only_drops():
    r, reason = clean_gt_filename("1959.pdf", return_reason=True)
    assert r is None
    assert reason == "numeric_only"


def test_too_short_drops():
    r, reason = clean_gt_filename("Smith.pdf", return_reason=True)
    assert r is None
    assert reason == "too_short"


def test_trailing_dup_suffix_stripped():
    r = _call("ALLEN, TAMMY_1.pdf")
    assert r == {"last": "ALLEN", "first": "TAMMY", "middle": ""}


def test_sham_merge_roll_prefix_drops():
    r, reason = clean_gt_filename("SMITH, JOHN.pdf", return_reason=True, source_roll="ROLL 003")
    assert r is None
    assert reason == "sham_merge"


def test_drop_reasons_enum_complete():
    assert DROP_REASONS == {
        "placeholder", "ocr_garbage", "numeric_only", "too_short", "sham_merge",
    }
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_gt_clean.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `poc/gt_clean.py`**

Create `poc/gt_clean.py`:

```python
"""Ground-truth PDF filename normalization with drop-reason taxonomy.

See spec section "GT-cleaning pass" in
docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md.
"""
import re
from pathlib import Path
from typing import overload

DROP_REASONS = {"placeholder", "ocr_garbage", "numeric_only", "too_short", "sham_merge"}

# Client-provided batch-merge PDFs, not per-student. Hardcoded exclusion.
SHAM_MERGE_ROLLS = {"ROLL 003", "ROLL 005", "ROLL 006"}

_PLACEHOLDER_RE = re.compile(r"\((?:LAST|FIRST|MIDDLE)\)", re.I)
_TRAILING_DUP = re.compile(r"_\d+$")
_OCR_GARBAGE_TOKENS = {
    "BIRTH", "COUNTY", "SEX", "PLACE", "CITY",
    "NAME", "LAST", "FIRST", "MIDDLE", "RECORD",
}


def _strip_numeric_prefix(tok: str) -> str:
    # "611" -> "" ; "611Eblin" -> "Eblin" ; "Eblin" -> "Eblin"
    m = re.match(r"^\d+(.*)$", tok)
    return m.group(1) if m else tok


@overload
def clean_gt_filename(fname: str, *, return_reason: bool = False,
                      source_roll: str = "") -> dict[str, str] | None: ...


def clean_gt_filename(fname, *, return_reason=False, source_roll=""):
    """Parse and normalize a GT PDF filename.

    Args:
        fname: e.g. "SMITH, JOHN A.pdf"
        return_reason: when True, returns (result, reason) tuple. `result` is
            None for dropped rows.
        source_roll: e.g. "ROLL 003" (for sham-merge exclusion).

    Returns:
        dict {last, first, middle} or None if unusable.
    """
    def _fail(reason: str):
        return (None, reason) if return_reason else None

    def _ok(result: dict[str, str]):
        return (result, None) if return_reason else result

    if source_roll and source_roll in SHAM_MERGE_ROLLS:
        return _fail("sham_merge")

    stem = Path(fname).stem
    if _PLACEHOLDER_RE.search(stem):
        return _fail("placeholder")

    upper_stem = stem.upper()
    if any(tok in upper_stem for tok in _OCR_GARBAGE_TOKENS):
        return _fail("ocr_garbage")

    stem = _TRAILING_DUP.sub("", stem)

    if "," in stem:
        last, rest = stem.split(",", 1)
        tokens = rest.strip().split()
        first = tokens[0] if tokens else ""
        middle = " ".join(tokens[1:]) if len(tokens) > 1 else ""
    else:
        tokens = stem.split()
        if len(tokens) >= 2:
            last, first, *mid = tokens
            middle = " ".join(mid)
        elif tokens:
            last, first, middle = tokens[0], "", ""
        else:
            return _fail("too_short")

    last = _strip_numeric_prefix(last.strip())
    first = _strip_numeric_prefix(first.strip())

    if last and last.isdigit():
        return _fail("numeric_only")
    if not last or not first:
        return _fail("too_short")

    return _ok({
        "last": last.upper(),
        "first": first.upper(),
        "middle": middle.strip().upper(),
    })
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_gt_clean.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/gt_clean.py tests/test_gt_clean.py
git commit -m "feat: add gt_clean module with drop-reason taxonomy (placeholder, ocr_garbage, numeric_only, too_short, sham_merge)"
```

---

## Task 7: Create `poc/index.py` — build_roll_index + snap_to_index + JSON writer

**Files:**
- Create: `poc/index.py`
- Create: `tests/test_index.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_index.py`:

```python
import json
from pathlib import Path

from poc.index import build_roll_index, snap_to_index, write_index_json
from poc.schemas import IndexRow, PageResult, RollMeta, Separator, Student, StudentPacket


def _page(frame, cls, index_rows=None):
    return PageResult(
        frame=frame, roll_id="ROLL 001", page_class=cls,
        separator=Separator(), student=Student(), roll_meta=RollMeta(),
        index_rows=index_rows or [],
        confidence_overall=0.9, confidence_name=0.9,
        model_version="t", processed_at="2026-04-22T00:00:00Z", latency_ms=0,
    )


def _row(last, first, middle="", dob="", frame="00011"):
    return IndexRow(last=last, first=first, middle=middle, dob=dob, source_frame=frame)


def _packet(last_raw, first_raw, middle_raw="", packet_id="r001_001"):
    return StudentPacket(
        packet_id=packet_id,
        last_raw=last_raw, first_raw=first_raw, middle_raw=middle_raw,
        last=last_raw, first=first_raw, middle=middle_raw,
        frames=["00100"],
        flagged=False,
        avg_confidence=0.9,
    )


def test_build_roll_index_only_reads_index_pages():
    pages = [
        _page("00001", "roll_leader"),
        _page("00011", "student_records_index",
              [_row("SMITH", "JOHN"), _row("JONES", "MARY")]),
        _page("00050", "student_cover"),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 2
    assert rows[0].last == "SMITH"


def test_build_roll_index_dedupes_exact_triples():
    pages = [
        _page("00011", "student_records_index",
              [_row("SMITH", "JOHN", "A", "3/4/75", frame="00011")]),
        _page("00018", "student_records_index",
              [_row("SMITH", "JOHN", "A", "3/4/75", frame="00018")]),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 1


def test_build_roll_index_keeps_near_duplicates():
    pages = [
        _page("00011", "student_records_index",
              [_row("SMYTH", "JOHN", "A", "3/4/75")]),
        _page("00018", "student_records_index",
              [_row("SMITH", "JOHN", "A", "3/4/75")]),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 2


def test_build_roll_index_skips_blank_rows():
    pages = [
        _page("00011", "student_records_index",
              [_row("", ""), _row("SMITH", "JOHN")]),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 1


def test_snap_exact_match_sets_applied_false():
    idx = [_row("SMITH", "JOHN")]
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.index_snap_applied is False
    assert out.index_snap_distance == 0


def test_snap_one_edit_corrects_and_marks_applied():
    idx = [_row("SMITH", "JOHN")]
    p = _packet("SNITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.index_snap_applied is True
    assert out.index_snap_distance == 1


def test_snap_three_edits_rejected():
    idx = [_row("SMITH", "JOHN")]
    p = _packet("GRAMT", "ALAN")
    out = snap_to_index(p, idx)
    assert out.last == "GRAMT"
    assert out.index_snap_applied is False
    assert out.index_snap_distance is None


def test_snap_component_cap_enforced():
    # distance-sum = 3 but last component = 3 violates per-component <=2.
    idx = [_row("ABCDE", "JOHN")]
    p = _packet("XYZDE", "JOHN")  # last-distance 3, first-distance 0
    out = snap_to_index(p, idx)
    assert out.index_snap_applied is False


def test_snap_picks_smallest_distance():
    idx = [_row("SMITH", "JOHN"), _row("SMYTH", "JOHN")]
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.index_snap_distance == 0


def test_snap_empty_index_returns_packet_unchanged():
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, [])
    assert out.last == "SMITH"
    assert out.index_snap_applied is False
    assert out.index_snap_distance is None


def test_snap_skips_index_entry_with_blank_first_name():
    idx = [_row("SMITH", ""), _row("SMITH", "JOHN")]
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, idx)
    # Must still match the second entry (first is skipped).
    assert out.last == "SMITH"
    assert out.first == "JOHN"


def test_write_index_json(tmp_path: Path):
    rows = [_row("SMITH", "JOHN", "A", "3/4/75"),
            _row("JONES", "MARY", "", "")]
    out = tmp_path / "roll_001_index.json"
    write_index_json(rows, out)
    data = json.loads(out.read_text())
    assert isinstance(data, list)
    assert data[0]["last"] == "SMITH"
    assert data[0]["source_frame"] == "00011"
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_index.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `poc/index.py`**

Create `poc/index.py`:

```python
"""Index-parse stage (H2.7 preparation).

Aggregates rows emitted by Bedrock on student_records_index pages,
dedupes on exact (last, first, dob) triples, and snaps grouped
student packets to the nearest index entry (Levenshtein <=2 per
component, <=3 sum).

See spec section "Index-parse stage" + "Index-snap algorithm" in
docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md.
"""
import json
from pathlib import Path

import Levenshtein

from poc.schemas import IndexRow, PageResult, StudentPacket

COMPONENT_CAP = 2
SUM_CAP = 3


def build_roll_index(pages: list[PageResult]) -> list[IndexRow]:
    """Collect every index_rows entry from student_records_index pages, dedupe."""
    rows: list[IndexRow] = []
    seen: set[tuple[str, str, str]] = set()
    for p in pages:
        if p.page_class != "student_records_index":
            continue
        for r in p.index_rows:
            last = r.last.strip().upper()
            first = r.first.strip().upper()
            dob = r.dob.strip()
            if not last and not first:
                continue
            key = (last, first, dob)
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    return rows


def snap_to_index(packet: StudentPacket, index: list[IndexRow]) -> StudentPacket:
    """Apply H2.7: snap (last_raw, first_raw) to nearest index entry within threshold."""
    if not index:
        return packet.model_copy(update={
            "last": packet.last_raw, "first": packet.first_raw, "middle": packet.middle_raw,
            "index_snap_applied": False, "index_snap_distance": None,
        })

    pkt_last = packet.last_raw.upper().strip()
    pkt_first = packet.first_raw.upper().strip()

    best_idx = -1
    best_dist = 1_000
    for i, entry in enumerate(index):
        if not entry.first.strip():
            continue
        d_last = Levenshtein.distance(pkt_last, entry.last.upper().strip())
        d_first = Levenshtein.distance(pkt_first, entry.first.upper().strip())
        if d_last > COMPONENT_CAP or d_first > COMPONENT_CAP:
            continue
        total = d_last + d_first
        if total > SUM_CAP:
            continue
        if total < best_dist:
            best_dist = total
            best_idx = i

    if best_idx < 0:
        return packet.model_copy(update={
            "last": packet.last_raw, "first": packet.first_raw, "middle": packet.middle_raw,
            "index_snap_applied": False, "index_snap_distance": None,
        })

    hit = index[best_idx]
    snapped_last = hit.last.upper().strip()
    snapped_first = hit.first.upper().strip()
    snapped_middle = hit.middle.upper().strip()
    applied = (snapped_last != pkt_last) or (snapped_first != pkt_first)
    return packet.model_copy(update={
        "last": snapped_last,
        "first": snapped_first,
        "middle": snapped_middle or packet.middle_raw,
        "index_snap_applied": applied,
        "index_snap_distance": best_dist,
    })


def write_index_json(rows: list[IndexRow], out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([r.model_dump() for r in rows], indent=2))
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_index.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/index.py tests/test_index.py
git commit -m "feat: add poc/index.py — build_roll_index + snap_to_index (H2.7) + JSON writer"
```

---

## Task 8: Update `poc/group.py` — raw vs snapped, call snap_to_index

**Files:**
- Modify: `poc/group.py`
- Modify: `tests/test_group.py`

- [ ] **Step 1: Rewrite tests**

Replace `tests/test_group.py` content with:

```python
from poc.group import group_pages
from poc.schemas import IndexRow, PageResult, Separator, Student, RollMeta


def _pg(frame, cls, last="", first="", middle="", conf=0.9, marker=None, roll_no=None):
    return PageResult(
        frame=frame, roll_id="ROLL 001", page_class=cls,
        separator=Separator(marker=marker, roll_no=roll_no),
        student=Student(last=last, first=first, middle=middle),
        roll_meta=RollMeta(),
        confidence_overall=conf, confidence_name=conf,
        model_version="t", processed_at="2026-04-18T00:00:00Z", latency_ms=0,
    )


def test_groups_consecutive_same_name_with_raw_and_post_fields():
    pages = [
        _pg("00001", "roll_leader"),
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SMITH", "JOHN"),
        _pg("00007", "student_continuation", "SMITH", "JOHN"),
        _pg("00008", "student_test_sheet", "JONES", "MARY"),
        _pg("00009", "student_cover", "JONES", "MARY"),
        _pg("01924", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, roll_index=[])
    assert len(packets) == 2
    assert packets[0].last_raw == "SMITH"
    assert packets[0].last == "SMITH"            # no snap when index empty
    assert packets[0].index_snap_applied is False
    assert packets[0].frames == ["00006", "00007"]
    assert packets[1].last_raw == "JONES"
    assert packets[1].frames == ["00008", "00009"]


def test_index_pages_do_not_form_packets():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_records_index"),
        _pg("00007", "student_cover", "SMITH", "JOHN"),
        _pg("00999", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, roll_index=[])
    assert len(packets) == 1
    assert packets[0].last_raw == "SMITH"


def test_snap_applies_when_index_has_near_match():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SNITH", "JOHN"),
        _pg("00999", "roll_separator", marker="END", roll_no="1"),
    ]
    index = [IndexRow(last="SMITH", first="JOHN", source_frame="00011")]
    packets = group_pages(pages, roll_index=index)
    assert packets[0].last_raw == "SNITH"
    assert packets[0].last == "SMITH"
    assert packets[0].index_snap_applied is True
    assert packets[0].index_snap_distance == 1


def test_fallback_when_no_start_end():
    pages = [
        _pg("00001", "student_cover", "SMITH", "JOHN"),
        _pg("00002", "student_continuation", "SMITH", "JOHN"),
    ]
    packets = group_pages(pages, roll_index=[])
    assert len(packets) == 1


def test_low_confidence_flags_packet():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SMITH", "JOHN", conf=0.5),
        _pg("00007", "student_continuation", "SMITH", "JOHN", conf=0.95),
        _pg("00008", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, roll_index=[], confidence_threshold=0.7)
    assert packets[0].flagged is True
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_group.py -v
```

Expected: TypeError (unexpected `roll_index` kwarg) / ValidationError (missing raw fields).

- [ ] **Step 3: Rewrite `poc/group.py`**

Overwrite with:

```python
from poc.index import snap_to_index
from poc.schemas import IndexRow, PageResult, StudentPacket


def _normalize(p: PageResult) -> str:
    return f"{p.student.last.upper().strip()}|{p.student.first.upper().strip()[:3]}"


def _has_name(p: PageResult) -> bool:
    return bool(p.student.last.strip() or p.student.first.strip())


def group_pages(
    pages: list[PageResult],
    roll_index: list[IndexRow],
    confidence_threshold: float = 0.7,
) -> list[StudentPacket]:
    pages = sorted(pages, key=lambda p: p.frame)
    if not pages:
        return []

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
        raw_pkt = StudentPacket(
            packet_id=pid,
            last_raw=cur_last, first_raw=cur_first, middle_raw=cur_middle,
            last=cur_last, first=cur_first, middle=cur_middle,
            frames=list(cur_frames),
            flagged=any(c < confidence_threshold for c in cur_confs),
            avg_confidence=avg,
        )
        packets.append(snap_to_index(raw_pkt, roll_index))
        cur_frames = []; cur_confs = []
        cur_last = cur_first = cur_middle = ""
        cur_key = None

    _STUDENT_CLASSES = {"student_cover", "student_test_sheet", "student_continuation"}

    for p in window:
        if p.page_class not in _STUDENT_CLASSES:
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

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add poc/group.py tests/test_group.py
git commit -m "feat(group): split raw vs snapped names, invoke snap_to_index per packet"
```

---

## Task 9: Rewrite `poc/eval.py` — two-pass matcher, drop reasons

**Files:**
- Modify: `poc/eval.py`
- Modify: `tests/test_eval.py`

- [ ] **Step 1: Rewrite tests**

Replace `tests/test_eval.py` content with:

```python
from poc.eval import evaluate
from poc.schemas import StudentPacket


def _pkt(last_raw, first_raw, last, first, middle="", pid="r001_001"):
    return StudentPacket(
        packet_id=pid,
        last_raw=last_raw, first_raw=first_raw, middle_raw=middle,
        last=last, first=first, middle=middle,
        frames=["00006"],
        flagged=False,
        avg_confidence=0.9,
    )


def test_evaluate_exact_match_both_passes():
    packets = [
        _pkt("SMITH", "JOHN", "SMITH", "JOHN", middle="A", pid="r001_001"),
        _pkt("JONES", "MARY", "JONES", "MARY", middle="", pid="r001_002"),
    ]
    gt = ["SMITH, JOHN A.pdf", "JONES, MARY.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.accuracy_exact_pre == 1.0
    assert report.accuracy_exact_post == 1.0
    assert report.gt_rows_raw == 2
    assert report.gt_rows_usable == 2
    assert report.gt_rows_dropped_reasons == {}


def test_evaluate_snap_lifts_accuracy():
    packets = [
        _pkt("SNITH", "JOHN", "SMITH", "JOHN", pid="r001_001"),  # snap fixed SNITH -> SMITH
    ]
    gt = ["SMITH, JOHN.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    # Pre-snap: SNITH vs SMITH is Levenshtein 1 -> partial match.
    assert report.partial_matches_pre == 1
    assert report.exact_matches_pre == 0
    # Post-snap: SMITH vs SMITH -> exact.
    assert report.exact_matches_post == 1
    assert report.accuracy_exact_post == 1.0


def test_evaluate_drops_placeholder_from_gt():
    packets = [_pkt("SMITH", "JOHN", "SMITH", "JOHN", pid="r001_001")]
    gt = ["SMITH, JOHN.pdf", "(LAST) (FIRST) MIDDLE Burris, Tammy L.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.gt_rows_raw == 2
    assert report.gt_rows_usable == 1
    # Either placeholder or ocr_garbage catches this sample (tokens overlap).
    dropped = report.gt_rows_dropped_reasons
    assert sum(dropped.values()) == 1


def test_evaluate_reports_index_diagnostics():
    packets = [
        _pkt("SNITH", "JOHN", "SMITH", "JOHN", pid="r001_001"),   # snapped
        _pkt("JONES", "MARY", "JONES", "MARY", pid="r001_002"),   # unchanged
    ]
    # Simulate snap_applied by modifying the fixture packets.
    packets[0].index_snap_applied = True
    report = evaluate(packets, ["SMITH, JOHN.pdf", "JONES, MARY.pdf"],
                      roll_id="ROLL 001", index_frames_total=7, index_rows_total=165)
    assert report.packets_snapped == 1
    assert report.index_frames_total == 7
    assert report.index_rows_total == 165


def test_evaluate_sham_merge_roll_excluded():
    packets = [_pkt("SMITH", "JOHN", "SMITH", "JOHN")]
    gt = ["SMITH, JOHN.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 003")
    assert report.gt_rows_usable == 0
    assert report.gt_rows_dropped_reasons == {"sham_merge": 1}
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_eval.py -v
```

Expected: AttributeError (no `accuracy_exact_pre`) or signature mismatch.

- [ ] **Step 3: Rewrite `poc/eval.py`**

Overwrite with:

```python
from collections import Counter
from typing import Iterable

import Levenshtein

from poc.gt_clean import clean_gt_filename
from poc.schemas import EvalReport, StudentPacket


def _key(last: str, first: str) -> str:
    return f"{last}|{first}"


def _match_pass(
    packets: list[StudentPacket],
    gt_usable: list[dict[str, str]],
    get_last, get_first, get_middle,
    max_levenshtein: int,
) -> tuple[int, int, int, list[str], list[str]]:
    gt_used: set[int] = set()
    exact = 0
    partial = 0
    nomatch = 0
    unmatched_pred: list[str] = []
    for pkt in packets:
        pkt_last = get_last(pkt).upper().strip()
        pkt_first = get_first(pkt).upper().strip()
        pkt_middle = get_middle(pkt).upper().strip()

        best_idx = -1
        best_level = "none"

        for i, gt in enumerate(gt_usable):
            if i in gt_used:
                continue
            if gt["last"] == pkt_last and gt["first"] == pkt_first:
                if gt["middle"] == pkt_middle or not pkt_middle or not gt["middle"]:
                    best_idx = i
                    best_level = "exact"
                    break
                best_idx = i
                best_level = "partial"

        if best_level == "none":
            for i, gt in enumerate(gt_usable):
                if i in gt_used:
                    continue
                if (Levenshtein.distance(gt["last"], pkt_last) <= max_levenshtein
                        and Levenshtein.distance(gt["first"], pkt_first) <= max_levenshtein):
                    best_idx = i
                    best_level = "partial"
                    break

        if best_level == "exact":
            exact += 1
            gt_used.add(best_idx)
        elif best_level == "partial":
            partial += 1
            gt_used.add(best_idx)
        else:
            nomatch += 1
            unmatched_pred.append(_key(pkt_last, pkt_first))

    unmatched_gt = [_key(gt_usable[i]["last"], gt_usable[i]["first"])
                    for i in range(len(gt_usable)) if i not in gt_used]
    return exact, partial, nomatch, unmatched_pred, unmatched_gt


def evaluate(
    packets: list[StudentPacket],
    ground_truth_filenames: Iterable[str],
    roll_id: str,
    max_levenshtein: int = 2,
    index_frames_total: int = 0,
    index_rows_total: int = 0,
) -> EvalReport:
    raw_list = list(ground_truth_filenames)
    gt_usable: list[dict[str, str]] = []
    drop_reasons: Counter[str] = Counter()

    for fn in raw_list:
        parsed, reason = clean_gt_filename(fn, return_reason=True, source_roll=roll_id)
        if parsed is None:
            drop_reasons[reason] += 1
        else:
            gt_usable.append(parsed)

    total = len(packets)

    exact_pre, partial_pre, no_pre, unmatched_pred_pre, unmatched_gt_pre = _match_pass(
        packets, gt_usable,
        lambda p: p.last_raw, lambda p: p.first_raw, lambda p: p.middle_raw,
        max_levenshtein,
    )
    exact_post, partial_post, no_post, unmatched_pred_post, unmatched_gt_post = _match_pass(
        packets, gt_usable,
        lambda p: p.last, lambda p: p.first, lambda p: p.middle,
        max_levenshtein,
    )

    def _acc(num: int) -> float:
        return (num / total) if total else 0.0

    usd_total = 0.0  # pages carry usd; runner fills this separately if needed.

    return EvalReport(
        roll_id=roll_id,
        pages_total=0,
        pages_classified=0,
        packets_predicted=total,
        packets_ground_truth=len(gt_usable),
        gt_rows_raw=len(raw_list),
        gt_rows_usable=len(gt_usable),
        gt_rows_dropped_reasons=dict(drop_reasons),
        exact_matches_pre=exact_pre,
        partial_matches_pre=partial_pre,
        no_match_pre=no_pre,
        accuracy_exact_pre=_acc(exact_pre),
        accuracy_partial_pre=_acc(exact_pre + partial_pre),
        exact_matches_post=exact_post,
        partial_matches_post=partial_post,
        no_match_post=no_post,
        accuracy_exact_post=_acc(exact_post),
        accuracy_partial_post=_acc(exact_post + partial_post),
        index_frames_total=index_frames_total,
        index_rows_total=index_rows_total,
        packets_snapped=sum(1 for p in packets if p.index_snap_applied),
        usd_total=usd_total,
        tokens_in_total=0,
        tokens_out_total=0,
        unmatched_predictions=unmatched_pred_post,
        unmatched_ground_truth=unmatched_gt_post,
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
git commit -m "feat(eval): two-pass matcher (pre/post snap), gt_clean integration, drop-reason + index diagnostics"
```

---

## Task 10: Update `poc/run_poc.py` — dual-env, budget guard, index stage, spend JSONL

**Files:**
- Modify: `poc/run_poc.py`
- No new tests (`run_poc.py` is exercised by the full-run smoke in Task 12).

- [ ] **Step 1: Rewrite `poc/run_poc.py`**

Overwrite with:

```python
"""POC runner.

Usage:
  python -m poc.run_poc --roll-id "ROLL 001" \
      --input samples/test_input_roll001 \
      --ground-truth samples/output_pdfs_district1_roll001 \
      [--limit 20] [--concurrency 8] [--budget-ceiling 10.0]

Outputs under poc/output/ (slug = lower+replace-space-with-underscore of roll-id):
  <slug>_pages.jsonl        one PageResult JSON per line
  <slug>_index.json         deduplicated IndexRow list
  <slug>_students.json      StudentPacket list
  <slug>_spend.jsonl        one Bedrock call per line
  <slug>_eval.json          EvalReport with pre/post snap accuracy
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from poc.classify_extract import classify_page
from poc.eval import evaluate
from poc.group import group_pages
from poc.index import build_roll_index, write_index_json
from poc.schemas import PageResult


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
    ap.add_argument("--budget-ceiling", type=float, default=10.0,
                    help="Hard halt once cumulative Bedrock spend >= this USD. 0 disables.")
    ap.add_argument("--output-dir", default="poc/output")
    args = ap.parse_args()

    in_dir = Path(args.input)
    tifs = sorted(in_dir.glob("*.tif"))
    if args.limit:
        tifs = tifs[: args.limit]
    if not tifs:
        print(f"no .tif in {in_dir}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(args.roll_id)
    pages_path = out_dir / f"{slug}_pages.jsonl"
    index_path = out_dir / f"{slug}_index.json"
    students_path = out_dir / f"{slug}_students.json"
    spend_path = out_dir / f"{slug}_spend.jsonl"
    eval_path = out_dir / f"{slug}_eval.json"

    results: list[PageResult] = []
    spend_lock = threading.Lock()
    cum_usd = 0.0
    halted = False

    print(f"classifying {len(tifs)} tifs @ concurrency {args.concurrency}, "
          f"budget ceiling ${args.budget_ceiling:.2f}")

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex, \
            pages_path.open("w") as pf, \
            spend_path.open("w") as sf:
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

            with spend_lock:
                cum_usd += r.usd_cost
            sf.write(json.dumps({
                "page_id": f"{slug}_{r.frame}",
                "frame": r.frame,
                "roll_id": r.roll_id,
                "purpose": "classify",
                "model_id": r.model_version,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "usd_total": r.usd_cost,
                "latency_ms": r.latency_ms,
                "page_class": r.page_class,
            }) + "\n")

            if i % 25 == 0 or i == len(tifs):
                print(f"  [{i}/{len(tifs)}] last={r.frame} class={r.page_class} "
                      f"conf={r.confidence_overall:.2f} usd=${cum_usd:.4f}")

            if args.budget_ceiling > 0 and cum_usd >= args.budget_ceiling and not halted:
                print(f"BUDGET CEILING ${args.budget_ceiling:.2f} reached "
                      f"(actual ${cum_usd:.4f}). Stopping further submissions.",
                      file=sys.stderr)
                halted = True
                for pending_fut in futs:
                    if not pending_fut.done():
                        pending_fut.cancel()

    if halted:
        print("Halted mid-run due to budget ceiling. Partial results written.", file=sys.stderr)

    # Index stage.
    roll_index = build_roll_index(results)
    write_index_json(roll_index, index_path)
    index_frames = sum(1 for r in results if r.page_class == "student_records_index")
    print(f"index: frames={index_frames} rows={len(roll_index)} -> {index_path}")

    # Grouping (applies H2.7 snap internally).
    packets = group_pages(results, roll_index=roll_index,
                          confidence_threshold=args.confidence_threshold)
    students_path.write_text(json.dumps([p.model_dump() for p in packets], indent=2))
    snapped = sum(1 for p in packets if p.index_snap_applied)
    print(f"packets: total={len(packets)} snapped={snapped} -> {students_path}")

    # Eval.
    gt_files = [p.name for p in Path(args.ground_truth).glob("*.pdf")]
    report = evaluate(packets, gt_files, roll_id=args.roll_id,
                      index_frames_total=index_frames,
                      index_rows_total=len(roll_index))
    report.pages_total = len(tifs)
    report.pages_classified = len(results)
    report.usd_total = cum_usd
    report.tokens_in_total = sum(r.tokens_in for r in results)
    report.tokens_out_total = sum(r.tokens_out for r in results)
    eval_path.write_text(report.model_dump_json(indent=2))

    print(
        f"eval: pre_partial={report.accuracy_partial_pre:.1%} "
        f"post_partial={report.accuracy_partial_post:.1%} "
        f"(exact_pre={report.exact_matches_pre}/{report.packets_predicted}, "
        f"exact_post={report.exact_matches_post}/{report.packets_predicted}) "
        f"spend=${report.usd_total:.4f} -> {eval_path}"
    )
    return 0 if not halted else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-run against 5-TIF subset (mocked Bedrock — no credentials required)**

Create a temporary test fixture run to confirm the module wires up:

```bash
python -m py_compile poc/run_poc.py && echo "compile ok"
pytest tests/test_env.py tests/test_schemas.py tests/test_prompts.py \
       tests/test_bedrock_client.py tests/test_classify_extract.py \
       tests/test_gt_clean.py tests/test_index.py tests/test_group.py \
       tests/test_eval.py tests/test_convert.py -v
```

Expected: `compile ok` and all non-smoke tests pass.

- [ ] **Step 3: Commit**

```bash
git add poc/run_poc.py
git commit -m "feat(run_poc): budget ceiling, index stage invocation, spend JSONL, pre/post accuracy logging"
```

---

## Task 11: Update smoke test fixtures — add index fixture

**Files:**
- Modify: `tests/test_smoke_bedrock.py`

- [ ] **Step 1: Add the index fixture entry + assertion**

Open `tests/test_smoke_bedrock.py` and replace its body with:

```python
import os
from pathlib import Path

import pytest

from poc.classify_extract import classify_page

SMOKE = os.environ.get("BEDROCK_SMOKE_TEST") == "1"
SAMPLES = Path("samples")

FIXTURES = [
    ("boundary_probe/t001_00005.tif",            "roll_separator"),
    ("verify_probe/d1r001_01923.tif",            "roll_separator"),
    ("test_input_roll001/00097.tif",             "student_cover"),
    ("boundary_probe/d3r028_00002.tif",          "roll_leader"),
    ("boundary_probe/d5r064_00001.tif",          "roll_leader"),
    # v2 addition.
    ("index_probe/broad/d1r001/00011.tif",       "student_records_index"),
]


@pytest.mark.skipif(not SMOKE, reason="BEDROCK_SMOKE_TEST not set")
@pytest.mark.parametrize("rel_path,expected_class", FIXTURES)
def test_classify_fixture(rel_path, expected_class):
    tif = SAMPLES / rel_path
    assert tif.exists(), f"missing fixture: {tif}"
    r = classify_page(tif, roll_id="SMOKE")
    print(f"{rel_path}: predicted={r.page_class} conf={r.confidence_overall} "
          f"index_rows={len(r.index_rows)}")
    assert r.page_class == expected_class, (
        f"{rel_path}: expected {expected_class}, got {r.page_class}. "
        f"student={r.student} separator={r.separator}"
    )
    if expected_class == "student_records_index":
        assert len(r.index_rows) >= 10, \
            f"expected >=10 index rows, got {len(r.index_rows)}: {r.index_rows}"
```

- [ ] **Step 2: Verify the new index TIF exists**

```bash
ls samples/index_probe/broad/d1r001/00011.tif
```

Expected: file prints (confirmed 2026-04-23 in repo snapshot).

- [ ] **Step 3: Run smoke (requires real Bedrock access)**

```bash
BEDROCK_SMOKE_TEST=1 pytest tests/test_smoke_bedrock.py -v -s
```

Expected: 6 passed. If the index fixture fails (<10 rows, wrong class), iterate on `poc/prompts.py` until it passes before moving to Task 12.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke_bedrock.py
git commit -m "test: add student_records_index fixture to Bedrock smoke suite"
```

---

## Task 12: Full ROLL 001 run (v2)

**Files:** no code changes. Data pull + measurement.

- [ ] **Step 1: Pull full ROLL 001 from S3 if not already cached**

```bash
python3 << 'EOF'
import os
from pathlib import Path
from poc import env

s3 = env.s3_client()
BUCKET = 'servflow-image-one'
PREFIX = 'Osceola Co School District/Test Input/ROLL 001/'
out_dir = Path('samples/test_input_roll001_full')
out_dir.mkdir(parents=True, exist_ok=True)
paginator = s3.get_paginator('list_objects_v2')
n = 0
for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
    for obj in page.get('Contents', []):
        k = obj['Key']
        if not k.endswith('.tif'):
            continue
        out = out_dir / k.split('/')[-1]
        if out.exists():
            continue
        s3.download_file(BUCKET, k, str(out))
        n += 1
        if n % 100 == 0:
            print(f'  pulled {n}')
print(f'done: {n} new files')
EOF
ls samples/test_input_roll001_full/*.tif | wc -l
```

Expected: 1924 TIFs.

- [ ] **Step 2: Full run**

```bash
python -m poc.run_poc \
  --roll-id "ROLL 001" \
  --input samples/test_input_roll001_full \
  --ground-truth samples/output_pdfs_district1_roll001 \
  --concurrency 10 \
  --budget-ceiling 10.0 \
  > poc/output/run_full.log 2>&1
tail -30 poc/output/run_full.log
```

Expected: run completes (exit 0) without hitting budget ceiling. Final log line shows `pre_partial=X% post_partial=Y% ... spend=$Z`. Runtime 10–60 min.

- [ ] **Step 3: Inspect artifacts**

```bash
python3 -c "
import json
r = json.load(open('poc/output/roll_001_eval.json'))
print(f\"pre_partial = {r['accuracy_partial_pre']:.3f}\")
print(f\"post_partial = {r['accuracy_partial_post']:.3f}\")
print(f\"lift = {r['accuracy_partial_post'] - r['accuracy_partial_pre']:.3f}\")
print(f\"index_frames = {r['index_frames_total']}, rows = {r['index_rows_total']}\")
print(f\"packets_snapped = {r['packets_snapped']} / {r['packets_predicted']}\")
print(f\"gt_dropped = {r['gt_rows_dropped_reasons']}\")
print(f\"spend = \${r['usd_total']:.4f}\")
"
```

Pass criteria: `accuracy_partial_post >= 0.85`. If lower, iterate on `poc/prompts.py` (or `snap_to_index` thresholds), rerun on a 100-TIF subset (`--limit 100`), commit the prompt change, then re-run full.

- [ ] **Step 4: Commit results**

```bash
git add poc/output/roll_001_eval.json poc/output/roll_001_students.json \
        poc/output/roll_001_index.json poc/output/run_full.log
git commit -m "feat: Phase 1 POC v2 full ROLL 001 run with pre/post snap accuracy"
```

Note: `poc/output/roll_001_pages.jsonl` and `roll_001_spend.jsonl` stay gitignored per the v1 `.gitignore` rule.

---

## Task 13: Write v2 results doc

**Files:**
- Create: `docs/superpowers/specs/2026-04-22-osceola-phase1-poc-v2-results.md`

- [ ] **Step 1: Fill in the template using the numbers from Task 12 Step 3**

Template:

```markdown
# Osceola Phase 1 POC v2 — Results

**Date:** YYYY-MM-DD
**Model:** claude-haiku-4-5 (Bedrock us-west-2, inference profile `us.anthropic.claude-haiku-4-5-20251001-v1:0`)
**Dataset:** Test Input ROLL 001 (1924 TIFs) vs Output/ROLL 001 (419 GT PDFs)
**Spec:** `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md` (v2)

## Accuracy (pre/post snap)

| Metric                         | Pre-snap | Post-snap | Delta |
|--------------------------------|----------|-----------|-------|
| exact matches                  | N        | N         | +N    |
| partial matches                | N        | N         | +N    |
| no match                       | N        | N         | -N    |
| **accuracy_exact**             | X%       | Y%        | +Z pp |
| **accuracy_partial (GATE)**    | X%       | Y%        | +Z pp |

Go/no-go gate: **`accuracy_partial_post ≥ 0.85`** — PASS / FAIL.

## GT cleaning

| Bucket            | Count |
|-------------------|-------|
| gt_rows_raw       | N     |
| gt_rows_usable    | N     |
| placeholder       | N     |
| ocr_garbage       | N     |
| numeric_only      | N     |
| too_short         | N     |
| sham_merge        | 0 (ROLL 001 not in exclusion list) |

## Index-parse diagnostics

- Index frames detected: N
- Index rows extracted (deduped): N
- Packets snapped: N / N_total ( P% )
- Mean snap distance when applied: X

## Class distribution (from pages.jsonl)

| Class                   | Count |
|-------------------------|-------|
| student_cover           | N     |
| student_test_sheet      | N     |
| student_continuation    | N     |
| student_records_index   | N     |
| roll_separator          | N     |
| roll_leader             | N     |
| unknown                 | N     |

## Confidence distribution

- Mean overall confidence: X
- Pages below 0.7 threshold: N
- Packets flagged for HITL: N

## Budget

- Cumulative spend: $X.XX
- Input tokens: N
- Output tokens: N
- Budget ceiling hit: YES / NO

## Failure modes observed

(list top 5–10 patterns from unmatched_predictions + unmatched_ground_truth — e.g. consistent surname misreads, garbage frames, snap mis-matches)

## Prompt / threshold iterations during run

1. v1 prompt, snap threshold 2/2/3 — partial_post = X%
2. (any subsequent tweak) — partial_post = Y%

## Go/no-go recommendation

- If post_partial ≥ 85%: **GO** for Phase 2 (single-roll prod).
- Else: iterate further before proceeding. Most likely levers in priority order: (1) prompt tuning, (2) Sonnet retry tier, (3) Tier 0 pixel heuristics.

## Next steps

- Phase 2 spec: `docs/superpowers/specs/2026-04-21-osceola-production-pipeline-v1-full.md`
- Remaining risks: districts 2–7 have zero GT; index-snap untested outside D1; no DOB cross-check in POC.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-04-22-osceola-phase1-poc-v2-results.md
git commit -m "docs: Phase 1 POC v2 results + go/no-go"
```

---

## Done criteria

- [ ] All unit tests green: `pytest -q` returns 0 (excluding smoke).
- [ ] 6 smoke fixtures pass with `BEDROCK_SMOKE_TEST=1`.
- [ ] `poc/output/roll_001_eval.json` exists and contains both `accuracy_partial_pre` and `accuracy_partial_post`.
- [ ] `accuracy_partial_post >= 0.85` on ROLL 001.
- [ ] `poc/output/roll_001_index.json` non-empty (expected ≥5 rows on ROLL 001).
- [ ] `poc/output/roll_001_spend.jsonl` one line per frame classified.
- [ ] Budget guard was honored (run either finished under ceiling or exit code 2 at ceiling).
- [ ] v2 results doc written with go/no-go.
- [ ] Every task committed individually.

## Self-Review

**Spec coverage:**

- Goal (pre/post snap, ≥0.85 on post) — Tasks 9 + 12.
- Non-goals (no bedrock_calls SQLite / no Sonnet / no other tiers) — Tasks 10 (JSONL is flat), no Sonnet in `bedrock_client.py`, no Tier 0/1/3/4 modules created.
- Dual-env loader — Task 1.
- 7-class taxonomy — Tasks 2, 3.
- `IndexRow`, `PageResult.index_rows`, tokens/usd, `StudentPacket.*_raw` + snap fields, `EvalReport` pre/post — Task 2.
- Prompt expansion + `index_rows` in tool schema + maxTokens 1500 — Task 3.
- Bedrock client through env.py + spend cost — Task 4.
- `classify_extract` threading tokens/usd + populating index_rows — Task 5.
- GT-cleaning pass + drop-reason taxonomy + sham-merge exclusion — Task 6.
- `build_roll_index`, `snap_to_index` (per-component Lev≤2, sum≤3, DOB deferred), JSON writer — Task 7.
- Grouping calls snap — Task 8.
- Two-pass eval, pre/post numbers, gt_clean integration, diagnostics — Task 9.
- `--budget-ceiling` with $10 default, spend JSONL, index stage invocation — Task 10.
- Smoke fixture for index — Task 11.
- Full run with artifacts — Task 12.
- Results doc with go/no-go — Task 13. ✓

**Placeholder scan:** no TBDs / "similar to above" / "implement error handling". Every step shows exact code or command.

**Type consistency:**
- `classify_via_bedrock` returns 3-tuple (`tool_input`, `usage`, `usd_cost`) — used consistently in Task 4 (definition) and Task 5 (consumer). ✓
- `group_pages(pages, roll_index, confidence_threshold=...)` — new signature used consistently in Task 8 (definition) and Task 10 (caller). ✓
- `snap_to_index(packet, index)` — defined in Task 7, called in Tasks 8 (via `group.py`) and 9 (not called from eval; eval only reads `packet.index_snap_applied`). ✓
- `clean_gt_filename(fname, *, return_reason, source_roll)` — defined in Task 6, called in Task 9 with all three args. ✓
- `EvalReport.gt_rows_dropped_reasons` shape = `dict[str, int]` everywhere. ✓
- `MAX_OUTPUT_TOKENS` imported in Task 4 from prompts defined in Task 3. ✓
