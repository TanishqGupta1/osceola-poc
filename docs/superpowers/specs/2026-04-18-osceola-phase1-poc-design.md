# Osceola Phase 1 POC — Design Spec

**Date:** 2026-04-18
**Revised:** 2026-04-22 (v2 — 7-class taxonomy, dual-env Bedrock, index-parse + index-snap heuristic, GT-cleaning pass, pre/post-snap accuracy reporting, $10 budget ceiling)
**Scope:** Phase 1 only. Phases 2–4 (AWS prod infra + HITL UI + bulk 218K) are out of scope for this spec.

## Revision History

| Date       | Change |
|------------|--------|
| 2026-04-18 | Initial spec. 6-class taxonomy, single-env Bedrock, single-pass classify+extract, eval against raw GT filenames. |
| 2026-04-22 | Revised in place. Adds: (a) `student_records_index` as 7th class, (b) dual-env `.env` + `.env.bedrock` loader, (c) index-parse merged into classify tool schema + H2.7 index-snap in grouping, (d) GT-cleaning pass before eval, (e) pre-snap vs post-snap accuracy reporting, (f) `$10` hard budget ceiling. Not in scope: `bedrock_calls` SQLite tracking, Sonnet retry tier, Tier 0/1/3/4 heuristics. Those defer to Phase 2. |

## Goal

Prove that Claude Haiku 4.5 on AWS Bedrock can classify + extract student records from Osceola microfilm TIF scans on Test Input ROLL 001 (1,924 TIFs) vs the 419 ground-truth Output PDFs.

Primary measurement: two numbers, not one.

- **`accuracy_partial_pre_snap`** — name-match accuracy using raw LLM output (baseline).
- **`accuracy_partial_post_snap`** — name-match accuracy after the H2.7 index-snap pass (treatment).

The delta between the two is the single most important experimental result of the POC: it tells us whether the index-parse stage is worth carrying into Phase 2.

Success gate for Phase 2 go/no-go: **`accuracy_partial_post_snap ≥ 0.85` on ROLL 001.** The pre-snap number is reported alongside but does not gate the decision — it exists to quantify the lift.

## Non-goals

- No AWS infrastructure (Lambda, Step Functions, DynamoDB) — all local Python.
- No PDF generation (Phase 2).
- No HITL UI (Phase 3).
- No multi-roll runs (Phase 4).
- No Bedrock Batch Inference (stick to on-demand Converse API for simplicity).
- No Sonnet fallback tier (single-model pipeline for POC).
- No `bedrock_calls` SQLite cost tracking (Phase 2 addition; POC uses JSONL spend log only).
- No Tier 0 pixel heuristics (blank detector / pHash / Hough), no Tier 1 name-format validators, no Tier 3 structural roll-level rules, no Tier 4 district priors. All listed in `docs/heuristics-brainstorm.md` and land in Phase 2.
- No corpus-snap (Tier 2.1–2.4). The only corpus used in the POC is the per-roll index allowlist (H2.7).

## Architecture

Pure Python, sequential pipeline, filesystem outputs. No infra. No DB. All state in JSON / JSONL files under `poc/output/`.

```
samples/test_input_roll001_full/*.tif   (local, pulled from S3 once)
   │
   ▼  convert.py
PNG bytes (in-memory, Pillow, downscaled to 1500px max side)
   │
   ▼  classify_extract.py  ─── single Bedrock Converse call per frame ───►  Bedrock Haiku 4.5
                                                                             (tool_use schema enforces
                                                                              7-class + student fields +
                                                                              optional index_rows)
   │
   ▼  run_poc.py writes
poc/output/roll_001_pages.jsonl          (one PageResult per line)
   │
   ├──► index.py  extracts index_rows from pages where page_class=student_records_index
   │        │
   │        ▼  writes
   │    poc/output/roll_001_index.json    (deduplicated IndexRow list for the roll)
   │
   ▼  group.py  (consumes pages.jsonl + index.json)
   │      - finds [START+1, END-1] window
   │      - name-change packet grouping
   │      - snap_to_index() applies H2.7 index-snap per packet
   ▼
poc/output/roll_001_students.json        (grouped packets, each with pre-snap + post-snap name)
   │
   ├──► gt_clean.py  (parses + normalizes GT PDF filenames, drops placeholder rows)
   │
   ▼  eval.py
poc/output/roll_001_eval.json            (pre-snap AND post-snap accuracy vs cleaned GT)
```

Two diagnostic artifacts accompany every run: `roll_001_spend.jsonl` (one row per Bedrock call with `tokens_in/tokens_out/usd/latency_ms`) and `roll_001_run.log` (stderr capture). The spend file is the POC substitute for the production `bedrock_calls` SQLite table — same fields, flat file.

## Components

| File | Responsibility |
|---|---|
| `poc/env.py` | Loads `.env` (S3 creds, `Servflow-image1`) AND `.env.bedrock` (Bedrock creds, `tanishq` account). Dual-client setup. |
| `poc/schemas.py` | Pydantic models: `PageResult`, `IndexRow`, `StudentPacket`, `EvalReport` |
| `poc/convert.py` | TIF → PNG bytes via Pillow (in-memory, no disk temp). Downscale to 1500px max side. |
| `poc/prompts.py` | System prompt + `tool_use` schema for 7-class classify+extract with optional `index_rows` payload |
| `poc/bedrock_client.py` | Thin wrapper: Bedrock Converse API, retries on throttle, tool_use schema enforcement, per-call spend logging |
| `poc/classify_extract.py` | Per-page orchestrator: convert → call → parse → return `PageResult` (may include `index_rows`) |
| `poc/index.py` | **New.** Aggregates `index_rows` from all `student_records_index` pages in a roll → writes `roll_<id>_index.json`. Exposes `snap_to_index(packet, index_entries) -> StudentPacket` for H2.7. |
| `poc/group.py` | Name-change packet grouping within `[START+1, END-1]`. Calls `snap_to_index` once per packet if index_entries non-empty. Records pre-snap + post-snap name on each packet. |
| `poc/gt_clean.py` | **New.** Parses raw GT PDF filenames, strips `(LAST)`/`(FIRST)`/`(MIDDLE)` placeholders, strips trailing `_N` dup-suffix, normalizes case. Returns `None` for unusable rows (placeholder-only, OCR garbage, numeric-only, embedded `BIRTH`/`COUNTY`/`SEX` tokens). |
| `poc/eval.py` | Runs gt_clean on all GT filenames, compares twice (pre-snap and post-snap), produces `EvalReport` with both numbers. |
| `poc/run_poc.py` | Top-level orchestrator with `--limit`, `--concurrency`, `--budget-ceiling` flags. Halts workers if cumulative spend exceeds ceiling (default `$10`). |
| `tests/test_*.py` | Unit tests per module. `test_smoke_bedrock.py` is a gated integration test (`BEDROCK_SMOKE_TEST=1`). |

## Data schemas

### `IndexRow` (new)

```python
class IndexRow(BaseModel):
    last: str
    first: str
    middle: str = ""
    dob: str = ""          # empty if column absent in this district's layout
    source_frame: str      # e.g. "00011" - frame the row was extracted from
```

### `PageResult` (revised — 7 classes + optional index_rows)

```python
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
    frame: str                        # "00123"
    roll_id: str                      # "ROLL 001"
    page_class: Literal[
        "student_cover", "student_test_sheet", "student_continuation",
        "student_records_index",      # NEW — 7th class
        "roll_separator", "roll_leader", "unknown",
    ]
    separator: Separator
    student: Student
    roll_meta: RollMeta
    index_rows: list[IndexRow] = []   # NEW — populated only when page_class=student_records_index
    confidence_overall: float         # 0.0-1.0
    confidence_name: float            # 0.0-1.0
    notes: str = ""
    model_version: str
    processed_at: str                 # ISO8601
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    usd_cost: float = 0.0
```

### `StudentPacket` (revised — records snap state)

```python
class StudentPacket(BaseModel):
    packet_id: str                    # "roll001_001"
    # Pre-snap name (raw LLM majority)
    last_raw: str
    first_raw: str
    middle_raw: str
    # Post-snap name (H2.7 applied; falls back to raw when no match within threshold)
    last: str
    first: str
    middle: str
    frames: list[str]
    flagged: bool                     # any page below confidence threshold
    avg_confidence: float
    index_snap_applied: bool          # True if post-snap differs from raw
    index_snap_distance: int | None   # Levenshtein (last+first) at match; None if no snap
```

### `EvalReport` (revised — pre/post snap)

```python
class EvalReport(BaseModel):
    roll_id: str
    pages_total: int
    pages_classified: int
    packets_predicted: int
    packets_ground_truth: int
    # GT quality metrics from gt_clean
    gt_rows_raw: int
    gt_rows_usable: int               # after dropping placeholders/garbage
    gt_rows_dropped_reasons: dict[str, int]   # {"placeholder": 14, "ocr_garbage": 3, ...}
    # Pre-snap numbers
    exact_matches_pre: int
    partial_matches_pre: int
    no_match_pre: int
    accuracy_exact_pre: float
    accuracy_partial_pre: float
    # Post-snap numbers
    exact_matches_post: int
    partial_matches_post: int
    no_match_post: int
    accuracy_exact_post: float
    accuracy_partial_post: float
    # Index stage diagnostics
    index_frames_total: int
    index_rows_total: int
    packets_snapped: int              # how many packets had H2.7 change their name
    # Spend
    usd_total: float
    tokens_in_total: int
    tokens_out_total: int
    # Residuals
    unmatched_predictions: list[str]
    unmatched_ground_truth: list[str]
```

## Dual-env loader

The POC account splits credentials: S3 access sits on the `Servflow-image1` IAM user (`.env`) and Bedrock sits on a separate `tanishq` user in account `690816807846` (`.env.bedrock`). Neither user holds both.

`poc/env.py` is the single source of truth. It exports two factory functions:

```python
def s3_client() -> boto3.client:
    """Returns a boto3 S3 client built from .env creds."""

def bedrock_client() -> boto3.client:
    """Returns a boto3 bedrock-runtime client built from .env.bedrock creds."""
```

Never import `boto3.client` directly in pipeline modules. All consumers go through `poc/env.py`. This prevents cross-contamination (e.g. accidentally calling Bedrock with S3 creds).

Region defaults to `us-west-2` for both clients even though `.env.AWS_REGION` may not be set (the S3 bucket is in us-west-2, not the code's historical us-east-1 default).

## Prompt strategy (single-pass, merged index rows)

One Bedrock Converse call per page. `tool_use` enforces JSON schema. Approach B from brainstorming: the same tool schema contains both student fields AND `index_rows`. The prompt directs the model to populate whichever applies to the current page's class; all other fields stay empty.

System prompt describes:

- **7 classes** (all definitions + 1-2 sentence example each, including `student_records_index` — tabular `STUDENT RECORDS INDEX` with LAST / FIRST / MIDDLE / DOB columns, 5–28 rows per page).
- **Both separator styles** (A clapperboard, B certificate) — explicitly labeled as the same `roll_separator` class.
- **Extraction fields** with "top left of form" hint per SOW.
- **Index rows instruction**: "When `page_class=student_records_index`, return every visible row in the `index_rows` array. Each row is one `(last, first, middle, dob)` tuple. Skip fully blank rows. DOB may be blank in some layouts — leave the field empty in that case. For all other classes, return an empty `index_rows` array."
- **Robustness instructions**: "image may be rotated, blank, or degraded — return `unknown` if unreadable"; "self-report `confidence_overall` + `confidence_name` on 0-1 scale".

Tool schema additions over v1:

```jsonc
{
  "page_class": {
    "enum": ["student_cover", "student_test_sheet", "student_continuation",
             "student_records_index",               // added
             "roll_separator", "roll_leader", "unknown"]
  },
  "index_rows": {                                   // added
    "type": "array",
    "items": {
      "type": "object",
      "required": ["last", "first"],
      "properties": {
        "last":   { "type": "string" },
        "first":  { "type": "string" },
        "middle": { "type": "string" },
        "dob":    { "type": "string" }
      }
    },
    "description": "Rows from a STUDENT RECORDS INDEX page. Empty array when page_class is not student_records_index."
  }
}
```

`inferenceConfig.maxTokens` raised from v1's 1000 → **1500** to accommodate the worst observed index page (28 rows × ~15 tokens/row ≈ 420 output tokens for index alone, plus the base payload).

## Index-parse stage (H2.7 preparation)

Runs after `run_poc.py`'s classify pass completes, before grouping. Pure Python, no Bedrock calls — all data comes from `page_result.index_rows` already populated during classify.

```
# poc/index.py
def build_roll_index(pages: list[PageResult]) -> list[IndexRow]:
    rows = []
    for p in pages:
        if p.page_class != "student_records_index":
            continue
        for r in p.index_rows:
            if not r.last.strip() and not r.first.strip():
                continue
            rows.append(r)
    return _dedupe(rows)

def _dedupe(rows: list[IndexRow]) -> list[IndexRow]:
    """Drop exact (last, first, dob) duplicates; keep first seen."""
```

Deduplication is conservative: only exact triple matches collapse. Fuzzy near-duplicates stay as separate entries (false positives in matching are cheaper than false negatives during snap).

Output: `poc/output/roll_<id>_index.json` — a list of `IndexRow` dicts. Grep-readable for manual inspection.

## Index-snap algorithm (H2.7)

Runs inside `poc/group.py::group_pages`, once per predicted packet, after name-change packet boundaries are fixed.

```
def snap_to_index(packet: StudentPacket, index: list[IndexRow]) -> StudentPacket:
    best_idx = -1
    best_dist = 999
    for i, entry in enumerate(index):
        d_last  = Levenshtein.distance(packet.last_raw.upper(),  entry.last.upper())
        d_first = Levenshtein.distance(packet.first_raw.upper(), entry.first.upper())
        total = d_last + d_first
        # Both components must be within 2; combined ≤ 3 is the accept gate.
        if d_last > 2 or d_first > 2:
            continue
        if total > 3:
            continue
        # DOB cross-check: deferred to Phase 2. POC snaps on (last, first) only.
        # Phase 2 adds: if both packet.dob (majority across frames) and entry.dob are
        # populated and non-matching, reject the candidate.
        if total < best_dist:
            best_dist = total
            best_idx = i
    if best_idx < 0:
        # No match — keep raw. Packet is flagged post-snap-miss for HITL visibility.
        return packet.copy(update={
            "last": packet.last_raw, "first": packet.first_raw, "middle": packet.middle_raw,
            "index_snap_applied": False, "index_snap_distance": None,
        })
    hit = index[best_idx]
    return packet.copy(update={
        "last": hit.last, "first": hit.first, "middle": hit.middle,
        "index_snap_applied": (hit.last.upper() != packet.last_raw.upper()
                               or hit.first.upper() != packet.first_raw.upper()),
        "index_snap_distance": best_dist,
    })
```

Snap is **additive to raw**: `last_raw` / `first_raw` / `middle_raw` are always preserved on the packet. This enables the pre-snap vs post-snap reporting in eval without re-running Bedrock.

Edge cases:

- **Empty index** (no `student_records_index` frames found in the roll) — `snap_to_index` returns the packet unchanged with `index_snap_applied=False`. Eval still reports pre/post columns; post equals pre.
- **Multiple index matches at equal distance** — first match wins (list is sorted alphabetically by surname, so ties break toward earlier letter).
- **Packet name appears to cross two index entries** (e.g. `SMITH/JOHN` near-matches both `SMITH/JOAN` and `SMYTH/JOHN` at distance 1) — both still land within threshold; deterministic tie-break picks the earlier.
- **Index entry with blank first name** — skip as a candidate (can't score distance reliably).

## GT-cleaning pass

`poc/gt_clean.py` encapsulates all GT filename normalization. Pure function. No I/O.

```python
DROP_TOKENS = {"(LAST)", "(FIRST)", "(MIDDLE)",
               "BIRTH", "COUNTY", "SEX", "PLACE", "CITY",
               "NAME", "LAST", "FIRST", "MIDDLE", "RECORD"}
_TRAILING_DUP = re.compile(r"_\d+$")

def clean_gt_filename(fname: str) -> dict[str, str] | None:
    """Returns {last, first, middle} or None if the row is unusable.
    Drop reasons surfaced via return-None + the caller tracks counts for diagnostics."""
```

Drop-reason categories tracked in `EvalReport.gt_rows_dropped_reasons`:

| Reason key       | Triggered when                                                              |
|------------------|-----------------------------------------------------------------------------|
| `placeholder`    | Filename contains any of `(LAST)`, `(FIRST)`, `(MIDDLE)` tokens.            |
| `ocr_garbage`    | Filename contains any blocklist token (`BIRTH`, `COUNTY`, etc.) in a name position. |
| `numeric_only`   | After stripping, last name is fully numeric (e.g. `1959.pdf`).              |
| `too_short`      | <2 tokens after normalization.                                              |
| `sham_merge`     | Filename originates from ROLL 003 / 005 / 006 (hardcoded exclusion list — batch-concatenated PDFs, not per-student). |

Parsed output normalized to uppercase with `_N` trailing-dup suffix stripped. All non-usable rows count toward `gt_rows_dropped_reasons` but do not appear in match denominators — this is the key change from v1, which compared predictions against raw GT including garbage.

`evaluate()` runs twice in one call: once with `packet.last_raw / first_raw / middle_raw`, once with `packet.last / first / middle`. Same matcher, two input streams. Denominator is identical (`gt_rows_usable`) so the two accuracy numbers are directly comparable.

## Grouping algorithm (revised — now drives snap)

```
1. Sort all PageResult by frame number.
2. Find first page with page_class=roll_separator AND separator.marker=START → start_idx.
3. Find last page with page_class=roll_separator AND separator.marker=END → end_idx.
4. If either missing → fall back to start_idx=0, end_idx=last; log warning.
5. window = pages[start_idx+1 : end_idx].
6. Walk window with prev/current:
   - Skip non-student_* classes (index, separator, leader, unknown pass through without contributing to packets).
   - Normalize name: upper(last).strip() + "|" + upper(first).strip()[:3] (coarse match).
   - If normalized_name(current) != normalized_name(prev) AND current has non-empty name:
       → flush current packet, start new one.
   - Else: append to current packet.
7. For each packet: compute avg_confidence, set raw name from frequency-majority across packet frames.
8. For each packet: call snap_to_index(packet, roll_index) to populate post-snap name.
9. Return list of StudentPacket.
```

`roll_index` is built once per run (via `poc/index.py`) and passed in. Step 8 is a no-op if `roll_index == []`.

## Evaluation method (revised)

1. Glob `samples/output_pdfs_district1_roll001/*.pdf` → list of filenames.
2. Run `clean_gt_filename` on each; partition into `gt_usable` (list of parsed dicts) and `gt_dropped` (grouped by reason).
3. For each packet, run the matcher twice:
   - **Pre-snap pass:** compare `packet.last_raw / first_raw / middle_raw` against `gt_usable`.
   - **Post-snap pass:** compare `packet.last / first / middle`.
4. Matching rules (unchanged from v1 except applied twice):
   - Exact = (last, first, middle) all uppercase match; middle counts as match if either side is empty.
   - Partial = (last, first) both within Levenshtein ≤2 but not an exact hit.
   - Each GT row consumed at most once per pass (independent `gt_used` sets for the two passes).
5. `accuracy_partial_{pre,post} = (exact + partial) / packets_predicted`.
6. Write `EvalReport` JSON with both numbers, drop-reason breakdown, and index diagnostics.

## Budget guard

`run_poc.py --budget-ceiling` flag (default `10.0`, unit USD). Cumulative spend is the sum of `usd_cost` across every `PageResult` written so far; tracked in an in-memory float updated under a lock. Each completed Bedrock call checks the running total; if ≥ ceiling, the worker pool stops accepting new futures and the run exits with exit code 2 and a message to stderr. Already-scheduled futures are allowed to finish (to avoid orphaning Bedrock calls).

Haiku 4.5 pricing assumed for cost math: input `$1.00 / MTok`, output `$5.00 / MTok` (matches the broad_index_probe constants).

Cost is logged per call to `poc/output/roll_<id>_spend.jsonl`:

```json
{"page_id":"d1r001_00097","frame":"00097","roll_id":"ROLL 001",
 "purpose":"classify","model_id":"us.anthropic.claude-haiku-4-5-20251001-v1:0",
 "tokens_in":1242,"tokens_out":83,"usd_in":0.001242,"usd_out":0.000415,"usd_total":0.001657,
 "latency_ms":844,"stop_reason":"tool_use","attempt":1,"error":null}
```

This is the flat-file analog of the Phase 2 `bedrock_calls` SQLite table. Same fields, same units. Phase 2 migrates by replaying the JSONL into SQLite; no data shape change.

## Testing strategy

Fixtures (unchanged from v1 + 1 new):

- `samples/boundary_probe/png/t001_00005.png` → roll_separator (Style A).
- `samples/verify_probe/png/d1r001_01923.png` → roll_separator (Style B).
- `samples/test_input_roll001/00097.png` → student_cover (real student).
- `samples/boundary_probe/png/d3r028_00002.png` → roll_leader (letterhead).
- `samples/boundary_probe/png/d5r064_00001.png` → roll_leader (resolution target).
- `samples/index_probe/broad/png/d1r001_00011_INDEX.png` → **student_records_index (new, 25 rows confirmed from broad probe)**.

Unit tests mock Bedrock. Integration smoke test (`tests/test_smoke_bedrock.py`) makes 6 real Bedrock calls (one per fixture); gated on `BEDROCK_SMOKE_TEST=1`. New assertion for the index fixture: `page_class == "student_records_index" AND len(index_rows) >= 10`.

Unit coverage additions over v1:

- `tests/test_index.py` — build_roll_index dedup; snap_to_index threshold cases (exact match, 1 edit, 3 edits, no match, DOB tie-break, blank index first-name skip).
- `tests/test_gt_clean.py` — placeholder drop, OCR-garbage drop, numeric-only drop, `_N` strip, titlecase uppercasing, sham-merge roll exclusion.
- `tests/test_eval.py` — pre/post snap numbers computed from same packet list; `gt_rows_dropped_reasons` populated correctly; index diagnostics surface through.

## Known blockers (updated)

| Blocker | Status |
|---|---|
| IAM Bedrock permissions | **Resolved.** Separate `tanishq` user in account `690816807846` has full Bedrock in us-west-2. Dual-env (`.env` + `.env.bedrock`) loader is the mitigation. |
| `list_objects_v2` pagination | Not a Phase 1 blocker (POC runs against local `samples/`). Remains a Phase 2 blocker for prod `s3_operations.py`. |

## Deliverables

- `poc/` package with 10 modules (`env`, `schemas`, `convert`, `prompts`, `bedrock_client`, `classify_extract`, `index`, `gt_clean`, `group`, `eval`) + `run_poc.py` + tests.
- `poc/output/roll_001_pages.jsonl` — per-page classification results.
- `poc/output/roll_001_index.json` — deduplicated IndexRow list for the roll.
- `poc/output/roll_001_students.json` — grouped packets with pre-snap + post-snap names.
- `poc/output/roll_001_spend.jsonl` — per-Bedrock-call spend log.
- `poc/output/roll_001_eval.json` — EvalReport with both accuracy numbers, drop reasons, index diagnostics.
- `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md` (this file).
- `docs/superpowers/plans/2026-04-18-osceola-phase1-poc.md` — implementation plan (updated to match v2).
- `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-results.md` — results doc with go/no-go recommendation citing `accuracy_partial_post_snap`.
- Final prompt frozen in `poc/prompts.py` as canonical v2.
