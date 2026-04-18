# Osceola Phase 1 POC — Design Spec

**Date:** 2026-04-18
**Scope:** Phase 1 only. Phases 2–4 (AWS prod infra + HITL UI + bulk 218K) are out of scope for this spec.

## Goal

Prove that Claude Haiku 4.5 on AWS Bedrock can classify + extract student records from Osceola microfilm TIF scans at **≥85% name-match accuracy** on Test Input ROLL 001 (1,924 TIFs) vs the 419 ground-truth Output PDFs.

Success = documented prompt + measured accuracy score. Go/no-go gate for Phase 2 production build.

## Non-goals

- No AWS infrastructure (Lambda, Step Functions, DynamoDB) — all local Python
- No PDF generation (Phase 2)
- No HITL UI (Phase 3)
- No multi-roll runs (Phase 4)
- No Bedrock Batch Inference (stick to on-demand Converse API for simplicity)
- No Sonnet fallback tier (single-model pipeline for POC)

## Architecture

Pure Python, sequential pipeline, filesystem outputs. No infra. No DB. All state in JSON files under `poc/output/`.

```
samples/test_input_roll001/*.tif   (local, already downloaded)
   │
   ▼  convert.py
PNG bytes (in-memory, Pillow)
   │
   ▼  classify_extract.py
Bedrock Haiku 4.5 Converse API  →  per-page JSON result
   │
   ▼  run_poc.py writes
poc/output/roll001_pages.jsonl   (one JSON per line)
   │
   ▼  group.py
poc/output/roll001_students.json (grouped packets)
   │
   ▼  eval.py
poc/output/roll001_eval.json     (accuracy vs ground truth)
```

## Components

| File | Responsibility |
|---|---|
| `poc/schemas.py` | Pydantic models: `PageResult`, `StudentPacket`, `EvalReport` |
| `poc/convert.py` | TIF → PNG bytes via Pillow (in-memory, no disk temp) |
| `poc/prompts.py` | Prompt template + schema for single-pass classify+extract |
| `poc/bedrock_client.py` | Thin wrapper: Bedrock Converse API, retries, tool_use schema enforcement |
| `poc/classify_extract.py` | Per-page orchestrator: convert → call → parse → return `PageResult` |
| `poc/group.py` | Name-change packet grouping within `[START+1, END-1]` window |
| `poc/eval.py` | Compare extracted student names vs ground-truth Output PDF filenames; compute precision/recall/exact-match |
| `poc/run_poc.py` | Top-level orchestrator with `--limit`/`--sample` flags |
| `tests/test_*.py` | Unit tests per module |

## Data schemas

### `PageResult` (per page)

```python
class Separator(BaseModel):
    marker: Literal["START", "END"] | None
    roll_no: str | None

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
    frame: str                    # "00123"
    roll_id: str                  # "ROLL 001"
    page_class: Literal[
        "student_cover","student_test_sheet","student_continuation",
        "roll_separator","roll_leader","unknown"
    ]
    separator: Separator
    student: Student
    roll_meta: RollMeta
    confidence_overall: float     # 0.0-1.0
    confidence_name: float        # 0.0-1.0
    notes: str = ""
    model_version: str
    processed_at: str             # ISO8601
    latency_ms: int
```

### `StudentPacket`

```python
class StudentPacket(BaseModel):
    packet_id: str                # "roll001_001"
    last: str
    first: str
    middle: str
    frames: list[str]             # ["00006","00007","00008"]
    flagged: bool                 # any page below threshold
    avg_confidence: float
```

### `EvalReport`

```python
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
    accuracy_partial: float       # fuzzy match
    unmatched_predictions: list[str]
    unmatched_ground_truth: list[str]
```

## Prompt strategy (single-pass)

One Bedrock Converse call per page. Use `tool_use` to enforce JSON schema. Prompt describes:
- 6 classes (all definitions + 1-2 sentence example)
- Both separator styles (A clapperboard, B certificate) — explicitly listed as same class
- Extraction fields with "top left of form" hint per SOW
- Instruction: "image may be rotated, blank, or degraded — return `unknown` if unreadable"
- Instruction: "self-report `confidence_overall` + `confidence_name` on 0-1 scale"

## Grouping algorithm

```
1. Sort all PageResult by frame number
2. Find first page with page_class=roll_separator AND separator.marker=START → start_idx
3. Find last page with page_class=roll_separator AND separator.marker=END → end_idx
4. If either missing → fall back to start_idx=0, end_idx=last; log warning
5. window = pages[start_idx+1 : end_idx]
6. Walk window with sliding prev/current:
   - Normalize name: upper(last).strip() + "|" + upper(first).strip()[:3]  (coarse match)
   - If normalized_name(current) != normalized_name(prev) AND current has non-empty name:
       → start new packet
   - Else: append to current packet
7. Return list of StudentPacket
```

## Evaluation method

Ground truth = filenames in `samples/output_pdfs_district1_roll001/*.pdf`. Parse each filename:
- Regex: `^\(?(?P<last>[A-Z]+)\)?,?\s+\(?(?P<first>[A-Z]+)\)?(?:\s+(?P<middle>\w+))?\.pdf$`
- Drop `(LAST)`, `(FIRST)`, `(MIDDLE)` tokens (human-op placeholders for AI-failure cases — not comparable)

Match algorithm:
- For each predicted packet: find best GT match via `(upper(last), upper(first))` Levenshtein ≤2
- Exact = (last, first, middle) all match
- Partial = (last, first) match but middle mismatch or missing
- Compute precision, recall, F1

## Testing strategy

Fixtures = 5 hand-picked TIFs covering each class:
- `samples/boundary_probe/png/t001_00005.png` → roll_separator (Style A)
- `samples/verify_probe/png/d1r001_01923.png` → roll_separator (Style B)
- `samples/test_input_roll001/00097.png` → student_cover (real student)
- `samples/boundary_probe/png/d3r028_00002.png` → roll_leader (letterhead)
- `samples/boundary_probe/png/d5r064_00001.png` → roll_leader (resolution target)

Unit tests avoid hitting Bedrock (mock the client). Integration smoke test (`test_smoke.py`) makes 1 real Bedrock call; skip if `BEDROCK_SMOKE_TEST!=1` env var.

## Blockers

1. **IAM Bedrock permissions** — current `Servflow-image1` user lacks `bedrock:*`. Must resolve before task 5.

## Deliverables

- `poc/` package with 8 modules + tests
- `poc/output/roll001_eval.json` with measured accuracy
- `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md` (this file)
- `docs/superpowers/plans/2026-04-18-osceola-phase1-poc.md` (implementation plan)
- Final prompt saved to `poc/prompts.py` as canonical v1
