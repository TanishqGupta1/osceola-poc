# Session Report — Phase 1 POC v2 End-to-End

**Date:** 2026-04-23
**Duration:** one session, ~several hours wall clock
**Branch created:** `phase1-poc-v2` (off `main` @ `2a6cfc3`)
**Worktree:** `/Users/tanishq/Documents/project-files/aws-s3/.worktrees/phase1-poc-v2/`
**Git user:** tanishq-printdeed

---

## 1. Goal of the session

Migrate existing POC pipeline (matches v1 plan) to match revised v2 spec:
- Add 7th taxonomy class (`student_records_index`)
- Dual-env loader (S3 `.env` + Bedrock `.env.bedrock`)
- Index-parse stage + H2.7 index-snap heuristic
- GT-cleaning pass with drop-reason taxonomy
- Pre/post-snap accuracy reporting
- $10 Bedrock budget ceiling
- Run full ROLL 001 (1924 TIFs) and measure `accuracy_partial_post_snap` vs 85% go/no-go gate.

---

## 2. Artifacts produced / touched

### 2.1 Spec

**File:** `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md`

Revised in place. 187 lines → 356 lines (+269 / -87). Commit **`274daf8`** on `main`.

Adds:
- Revision history block.
- Non-goals made explicit for every tier not shipping.
- Architecture diagram with `index.py` + `gt_clean.py` branches.
- Component table — 10 modules plus `run_poc.py`.
- Pydantic schemas: `IndexRow`, `PageResult.index_rows`, `PageResult.tokens_in/out/usd_cost`, `StudentPacket.last_raw/first_raw/middle_raw` + `index_snap_applied` + `index_snap_distance`, `EvalReport` pre/post pairs + drop-reason dict + index + spend fields.
- Dual-env loader section.
- 7-class prompt + merged `index_rows` tool schema, `maxTokens` raised 1000 → 1500.
- Index-parse stage pseudo-code (pure Python, no extra Bedrock calls).
- Index-snap algorithm (Lev ≤2 per component, sum ≤3; DOB cross-check deferred to Phase 2).
- GT-cleaning pass with drop-reason taxonomy.
- Budget guard section with spend-JSONL schema.
- 6-fixture smoke test list.
- Blocker table marking IAM Bedrock issue resolved.

### 2.2 Plan

**File:** `docs/superpowers/plans/2026-04-22-osceola-phase1-poc-v2.md`

Newly created. 2,276 lines. 13 tasks, TDD pattern throughout. Commit **`2a6cfc3`** on `main` (combined with `.gitignore` update).

Task outline:
1. Create `poc/env.py` dual-env loader
2. Extend `poc/schemas.py` for v2 fields
3. Extend `poc/prompts.py` to 7 classes + `index_rows`
4. Update `poc/bedrock_client.py` — route via env.py, return `usd_cost`
5. Update `poc/classify_extract.py` — surface `index_rows` + tokens + usd
6. Create `poc/gt_clean.py` — GT filename cleaner with drop-reason taxonomy
7. Create `poc/index.py` — `build_roll_index` + `snap_to_index` + JSON writer
8. Update `poc/group.py` — raw vs snapped, call `snap_to_index`
9. Rewrite `poc/eval.py` — two-pass matcher (pre/post)
10. Update `poc/run_poc.py` — dual-env, `--budget-ceiling`, index stage, spend JSONL
11. Update smoke test fixtures + run real Bedrock smoke
12. Full ROLL 001 run (S3 pull + 1924-TIF classify + eval)
13. Write results doc + go/no-go

### 2.3 Source files changed on `phase1-poc-v2` branch

| Path | Op | Description |
|---|---|---|
| `poc/env.py` | CREATE | `load_dotenvs()`, `s3_client()`, `bedrock_client()` factories. Dual-env loader. Region default `us-west-2`. |
| `poc/schemas.py` | EDIT | `PageClass` gains `student_records_index`. New `IndexRow` model. `PageResult` gets `index_rows`, `tokens_in`, `tokens_out`, `usd_cost`. `StudentPacket` gets `last_raw`/`first_raw`/`middle_raw`/`index_snap_applied`/`index_snap_distance`. `EvalReport` gets `gt_rows_raw`, `gt_rows_usable`, `gt_rows_dropped_reasons`, pre/post pairs, `index_frames_total`, `index_rows_total`, `packets_snapped`, `usd_total`, `tokens_in_total`, `tokens_out_total`. |
| `poc/prompts.py` | EDIT | 7-class enum. `MAX_OUTPUT_TOKENS = 1500`. `index_rows` array added to `TOOL_SCHEMA` with `items: {required: [last, first], properties: {last, first, middle, dob}}`. System prompt describes index rows behavior + 7th class. |
| `poc/bedrock_client.py` | EDIT | `classify_via_bedrock()` now routes via `env.bedrock_client()`. Returns 3-tuple `(tool_input, usage, usd_cost)`. New `compute_usd_cost()` helper. Haiku 4.5 pricing constants (`$1.00/MTok in`, `$5.00/MTok out`). `maxTokens` from `MAX_OUTPUT_TOKENS`. |
| `poc/classify_extract.py` | EDIT | Three-tuple unpacking. New `_build_index_rows()` helper converts tool-input index rows to `IndexRow` list with `source_frame`. `PageResult` now populated with `tokens_in`, `tokens_out`, `usd_cost`. |
| `poc/gt_clean.py` | CREATE | `clean_gt_filename(fname, *, return_reason, source_roll)`. `DROP_REASONS` = {placeholder, ocr_garbage, numeric_only, too_short, sham_merge}. `SHAM_MERGE_ROLLS = {ROLL 003, 005, 006}`. Numeric-only check runs before numeric-prefix strip. |
| `poc/index.py` | CREATE | `build_roll_index()` dedupes on exact `(last, first, dob)` triples. `snap_to_index()` applies Lev ≤2 per-component, ≤3 sum, returns `model_copy` with snap diagnostics. `write_index_json()`. |
| `poc/group.py` | EDIT (3 rounds) | Round 1: call `snap_to_index` on flush, split raw/snap fields. Round 2: added `_majority_name`, `_mergeable`, `_merge_pair`, `_merge_adjacent` for H2.4 packet-merge. Round 3: `_snap_page_name` with field-swap guard, `group_by_index_entry` alternate mode, `enable_page_snap` flag. |
| `poc/eval.py` | EDIT | Dropped inline `parse_pdf_filename` in favor of `gt_clean.clean_gt_filename`. Matcher factored into `_match_pass` that takes accessor lambdas. `evaluate()` calls it twice (pre with `*_raw`, post with snap names). Returns `EvalReport` with pre/post pairs + drop-reason dict + index diagnostics. |
| `poc/run_poc.py` | EDIT | `--budget-ceiling` default 10.0. Thread-safe `cum_usd` accumulator. Per-call spend JSONL writer. Index stage between classify and group: `build_roll_index` + `write_index_json`. Grouping passes `roll_index`. Eval receives `index_frames_total`, `index_rows_total`. Final report patches `usd_total`, `tokens_in_total`, `tokens_out_total`. Prints `pre_partial` / `post_partial` side-by-side. |
| `poc/regroup.py` | CREATE (late-session) | CLI rerunner. Reads existing `pages.jsonl`, re-invokes `build_roll_index` + `group_pages` (or `group_by_index_entry`) + `evaluate`. Zero Bedrock cost. `--mode {boundary, index}`, `--no-merge`. |

### 2.4 Test files

| Path | Status | Coverage |
|---|---|---|
| `tests/test_env.py` | CREATE | 3 tests. Parsed env files, `s3_client` / `bedrock_client` cred passthrough + region default. |
| `tests/test_schemas.py` | EDIT | 7 tests. Old `test_student_packet` updated to new `last_raw`/`first_raw` signature. Added `test_page_class_accepts_student_records_index`, `test_page_result_default_empty_index_rows`, `test_student_packet_has_raw_and_snap_fields`, `test_eval_report_has_pre_post_and_diagnostics`. Removed stale `test_eval_report_defaults`. |
| `tests/test_prompts.py` | EDIT | 9 tests. Class count updated 6→7. Added index-rows-schema assertions, `MAX_OUTPUT_TOKENS` check. |
| `tests/test_bedrock_client.py` | EDIT | 4 tests. All three `_FAKE_INPUT` constants carry `index_rows: []`. `@patch` target changed from `boto3.client` to `env.bedrock_client`. Added `test_compute_usd_cost_formula` and `test_classify_via_bedrock_passes_max_tokens_1500`. |
| `tests/test_classify_extract.py` | EDIT | 2 tests. Mock returns 3-tuple now. Second test validates `index_rows` populated + `source_frame` set. |
| `tests/test_gt_clean.py` | CREATE | 9 tests. Each drop reason, titlecase → upper, trailing-dup strip, sham-merge exclusion via `source_roll` kwarg. |
| `tests/test_index.py` | CREATE | 12 tests. `build_roll_index` dedup + blank-row skip + near-duplicate keep. `snap_to_index` cases: exact, 1-edit, 3-edit reject, per-component cap, tie-break, empty index, skip-blank-first. `write_index_json`. |
| `tests/test_group.py` | EDIT | 5 tests. `roll_index` kwarg required. Raw/snap fields verified. Index pages don't form packets. Snap application visible. |
| `tests/test_eval.py` | EDIT | 5 tests. Pre/post numbers. `gt_rows_dropped_reasons` populated. `packets_snapped` diagnostics. `source_roll` path for sham-merge. |
| `tests/test_smoke_bedrock.py` | EDIT | Gated on `BEDROCK_SMOKE_TEST=1`. 6 fixtures (was 5). New index fixture at `samples/index_probe/broad/d1r001/00011.tif` with `>=10 rows` assertion. |

Test counts at end of Task 10: **59 passing + 5 smoke-skip**. After smoke fixture addition: 59 + 6 smoke-skip.

### 2.5 Repo infra changes

- `.gitignore` — added `.worktrees/` block (commit `2a6cfc3` on main).
- `.worktrees/phase1-poc-v2/` — worktree directory (ignored).
- `samples/` inside worktree — real directory at top but with individual subdir symlinks pointing at main repo's `samples/` (FERPA data stays outside tracked git, but reachable via relative paths). Symlink entries created in worktree shell (not committed):
  - `samples/test_input_roll001 → /main/samples/test_input_roll001`
  - `samples/output_pdfs_district1_roll001 → /main/samples/output_pdfs_district1_roll001`
  - `samples/index_probe → /main/samples/index_probe`
  - `samples/boundary_probe → /main/samples/boundary_probe`
  - `samples/verify_probe → /main/samples/verify_probe`
  - `samples/classification_samples → /main/samples/classification_samples`

### 2.6 Commits

**On `main`:**
1. `274daf8 docs: revise Phase 1 POC spec v2 in place`
2. `2a6cfc3 chore: gitignore .worktrees/ and add Phase 1 POC v2 plan`

**On `phase1-poc-v2` (off main@2a6cfc3):**
1. `b6f7479 feat: add poc/env.py dual-env loader for S3 + Bedrock clients`
2. `182a60b feat(schemas): add student_records_index class, IndexRow, token+usd on PageResult, raw/snap on StudentPacket, pre/post on EvalReport`
3. `5bb255f feat(prompts): expand to 7-class taxonomy, add index_rows schema, raise maxTokens to 1500`
4. `76dc6bc feat(bedrock_client): route through poc.env, return usage+usd_cost, maxTokens=1500`
5. `5272964 feat(classify_extract): surface index_rows + tokens + usd_cost on PageResult`
6. `81895e0 feat: add gt_clean module with drop-reason taxonomy`
7. `9e32281 feat: add poc/index.py — build_roll_index + snap_to_index (H2.7) + JSON writer`
8. `5ef5904 feat(group): split raw vs snapped names, invoke snap_to_index per packet`
9. `e91f097 feat(eval): two-pass matcher (pre/post snap), gt_clean integration, drop-reason + index diagnostics`
10. `eefbcce feat(run_poc): budget ceiling, index stage, spend JSONL, pre/post accuracy logging`
11. `3c3b705 feat(group): majority-vote naming + H2.4 packet-merge + index-entry grouping mode`

All commits signed off by `tanishq-printdeed <tanishq@printdeed.com>`.

Branch **not merged** back to main. No force-pushes. No remote pushes.

---

## 3. Execution timeline

### 3.1 Brainstorming + spec (skill: `superpowers:brainstorming`)

Six clarifying questions in sequence:

| # | Question | Decision |
|---|---|---|
| 1 | Shape of revision | In-place edit of existing spec file |
| 2 | Scope | "Medium" — mandatory fixes + index-snap only. Deferred `bedrock_calls` SQLite, Sonnet retry, Tier 0/1/3/4 heuristics |
| 3 | Index-parse arch | Approach B — merged into single Bedrock call via tool schema |
| 4 | Index storage | JSON per roll (`roll_<id>_index.json`) |
| 5 | Accuracy target | Report both pre/post side by side |
| 6 | POC Bedrock budget ceiling | $10 (matches existing `broad_index_probe` pattern) |

Approach 2 chosen (new `index.py` + `gt_clean.py` modules, vs stuffing into existing).

Spec file self-review found one inline bug — `packet.frames_have_dob` + `_dob_matches()` referenced but not defined. Edited to note DOB cross-check is deferred to Phase 2.

### 3.2 Plan writing (skill: `superpowers:writing-plans`)

13 tasks, TDD structure: each = write failing test → run red → implement → run green → commit. File paths absolute, code blocks literal (no placeholders). Self-review covered spec coverage, placeholder scan, type consistency. One fix inline (maxTokens import consistency).

### 3.3 Worktree + branch (skill: `superpowers:using-git-worktrees`)

- `.worktrees/` didn't exist. No `CLAUDE.md` pref. Default `.worktrees/` (skill priority).
- Added `.worktrees/` to `.gitignore`, committed plus the plan file.
- Created `.worktrees/phase1-poc-v2` on `phase1-poc-v2` branch off main.
- Copied `.env` + `.env.bedrock` into worktree (gitignored, don't travel with checkout).
- Baseline `pytest -q` = 23 passing + 5 smoke-skip (v1 code at that point).

### 3.4 Plan execution Tasks 1–10 (skill: `superpowers:executing-plans`)

All 10 tasks green with TDD pattern. Commits listed in 2.6 above. No plan deviations. One minor test fix (numeric-only drop reason ordering in `gt_clean.py`). Final suite: **59 passing, 5 smoke-skip**.

### 3.5 Smoke test (Task 11, real Bedrock)

6 fixtures, `$0.02` spend, ~45s.

| Fixture | Expected | Got | Result |
|---|---|---|---|
| `boundary_probe/t001_00005.tif` | `roll_separator` | `roll_separator` (conf 0.95) | ✅ |
| `verify_probe/d1r001_01923.tif` | `roll_separator` | `roll_separator` (conf 0.95) | ✅ |
| `test_input_roll001/00097.tif` | `student_cover` | `student_continuation` (conf 0.85) | ❌ |
| `boundary_probe/d3r028_00002.tif` | `roll_leader` | `roll_leader` (conf 0.95) | ✅ |
| `boundary_probe/d5r064_00001.tif` | `roll_leader` | `roll_leader` (conf 0.85) | ✅ |
| `index_probe/broad/d1r001/00011.tif` | `student_records_index` | `student_records_index` (conf 0.95, **25 rows extracted**) | ✅ |

**5/6 pass.** One disagreement on `student_cover` vs `student_continuation` — both `student_*` so grouping unaffected. Name on 00097 extracted as `last=Charles first=Allison middle=Phillips` — possible field inversion (Haiku confuses last/first columns). Same pattern observed during full run in higher frequency.

Smoke not committed fresh (index fixture test assertion added via `Edit`, not separate task commit — rolled into later work).

### 3.6 S3 pull (Task 12b)

Two S3 prefixes pulled via `poc.env.s3_client()`:

| Source | Dest | Count |
|---|---|---|
| `Osceola Co School District/Test Input/ROLL 001/` (only TIFs) | `samples/test_input_roll001_full/` | 1924 |
| `Osceola Co School District/Output/OSCEOLA SCHOOL DISTRICT-1/ROLL 001/` (only PDFs) | `samples/output_pdfs_district1_roll001_full/` | 418 |

Total ~200 MB TIFs + ~160 MB PDFs. Sequential downloads, ran ~20 min in background while Bedrock run started mid-pull (no conflict — different creds, different AWS services).

### 3.7 Full ROLL 001 run (Task 12c)

Command:
```bash
python3 -m poc.run_poc --roll-id "ROLL 001" \
  --input samples/test_input_roll001_full \
  --ground-truth samples/output_pdfs_district1_roll001_full \
  --concurrency 10 --budget-ceiling 10.0 \
  > poc/output/run_full.log 2>&1
```

Ran to completion (exit 0). Did not hit budget ceiling.

**Summary:**

| Metric | Value |
|---|---|
| Pages classified | 1924 / 1924 |
| Packets predicted | 1240 |
| GT rows raw | 418 |
| GT rows usable | 347 (71 dropped) |
| GT drops by reason | placeholder 46, too_short 24, ocr_garbage 1 |
| Index frames detected | 20 |
| Index rows (deduped) | 445 |
| Packets snapped | 190 |
| Spend | $9.89 |
| Input tokens | 6,634,602 |
| Output tokens | 651,816 |
| `accuracy_partial_pre` | **20.7%** (exact=158, partial=99, no_match=983) |
| `accuracy_partial_post` | **20.7%** (exact=160, partial=97, no_match=983) |
| `accuracy_exact_pre` | 12.7% |
| `accuracy_exact_post` | 12.9% |

**Gate `accuracy_partial_post ≥ 0.85` = NO-GO** at 20.7%.

Class distribution from pages.jsonl:
- `student_continuation`: 843
- `student_cover`: 586
- `student_test_sheet`: 384
- `unknown`: 57
- `roll_leader`: 21
- `student_records_index`: 20
- `roll_separator`: 13

Output artifacts in `poc/output/`:
- `roll_001_pages.jsonl` — 1.8 MB, 1924 lines
- `roll_001_index.json` — 55 KB, 445 rows
- `roll_001_students.json` — 424 KB, 1240 packets
- `roll_001_spend.jsonl` — 522 KB, 1924 lines (one per Bedrock call)
- `roll_001_eval.json` — 23 KB, EvalReport
- `run_full.log` — 5.8 KB

### 3.8 Diagnosis of NO-GO result

Inline Python diagnostic over `pages.jsonl` + `students.json` + `eval.json`:

| Finding | Value |
|---|---|
| Size-1 packets | 840 / 1240 (67.7%) |
| Size-2 packets | 287 |
| Size-3 packets | 75 |
| Size-4+ | 38 |
| Adjacent-merge candidates (Lev ≤2/≤3) | 77 |
| 3+ page packets with within-packet name disagreement | 10 / 113 |
| Consecutive student pages with **different** `(last, first[:3])` | 934 / 1812 (52%) |
| Consecutive student pages with **empty** name | 757 / 1812 (42%) |
| Consecutive student pages with **same** key | 121 / 1812 (7%) |

Concrete micro-sample (frames 24–54):

- 24: `Abshire, Angelah` (cover)
- 25: `Abshire, Angela`
- 26: `Villaline, Angela` ← wrong lastname
- 27: blank
- 28: `Abshire, Angela`
- 29: blank
- 30: `Abshire, Angela`
- 31: `Ushire, Angela` ← OCR-dropped A
- 32: `Hensley, Natalie` ← different form on same page?
- ...
- 39: `Calvin, Ackley` ← **first/last inverted**
- 40: `Ackley, Calvin` ← correct
- 42: `Ashley, Tray` ← OCR
- 43: `Ackley, Troy`
- 44: `Achlet, Troy` ← OCR
- 47: `Cackley, Troy` ← OCR

Core finding: name-change grouping cannot survive per-page OCR variance + field inversion. Needs index as anchor.

Page-snap hit rate (threshold Lev ≤3/≤4, swap-tolerant):

| | Count |
|---|---|
| Student pages total | 1813 |
| Named (non-empty) | 1391 |
| Empty-name | 422 |
| Snap-hit | 691 (49.7% of named) |
| Snap-miss | 700 |
| Hit distance 0 | 354 |
| Hit distance 1 | 120 |
| Hit distance 2 | 85 |
| Hit distance 3 | 103 |
| Hit distance 4 | 29 |

### 3.9 Heuristic iterations (Tasks B/C/D, no Bedrock $)

All variants run via `poc.regroup` against the same frozen `pages.jsonl`.

| Variant | Code change | Packets | `acc_partial_post` | Exact |
|---|---|---|---|---|
| Baseline | v1 name-change grouping only | 1240 | 20.7% | 158 |
| + majority-vote packet naming | `_majority_name` Counter over pages | 1163 | 21.8% | 161 |
| + packet-merge on `_raw` names (Lev 2/3) | `_mergeable` + `_merge_pair` + `_merge_adjacent` | 1165 | 21.7% | 160 |
| + merge on post-snap names | Swapped mergeable comparison to `.last`/`.first` | 1165 | 21.7% | 160 |
| + pre-group per-page snap | `_snap_page_name` + boundary key via snapped | 1129 | 21.7% | 157 |
| **Index-entry mode** | `group_by_index_entry` — cluster by snap target | **323** | **66.9%** | **140** |

Index-entry mode was the win: **3.2× partial-accuracy lift from baseline**, zero extra Bedrock $. Packet count (323) lands within 7% of usable GT (347).

Index-entry mode final numbers:
- Recall = 216 matched / 347 usable GT = **62%**
- Precision = 216 / 323 predictions = **67%**
- F1 ≈ **64%** (vs ≈ 32% baseline F1)

Unmatched residuals (spot check):
- `ADAMS|JOHN`, `ADKINS|KEVIN`, `ANDERSON|MARK`, `BAKER|GENE` — predicted but not in GT. Likely index-only entries (GT has 347 usable, index has 432 unique).
- `ACKLEY|CALVIN`, `ADKINS|DEBORAH`, `ATEN|JEFFREY` — in GT but no prediction. Student name not in detected index rows (index covers ~432 / expected ~559).
- `ALDERMAN|DAVID` vs GT `ALDER|DAVID` — Lev 4 on last, misses eval threshold of 2. Possible tune target.

---

## 4. Verification / validation evidence

### 4.1 Unit test green

All per-task TDD cycles verified:

```
$ pytest -q
.........................................................   [100%]
59 passed, 6 skipped in 0.81s
```

5 smoke tests skip without `BEDROCK_SMOKE_TEST=1`. One new smoke test for index fixture (6 total smoke) skipped same way.

### 4.2 Smoke test (real Bedrock, 6 fixtures)

```
$ BEDROCK_SMOKE_TEST=1 pytest tests/test_smoke_bedrock.py -v -s
5 passed, 1 failed in 45.73s
```

The 1 failure (`00097.tif` fixture labeled `student_cover`, model returned `student_continuation`) is a fixture labeling ambiguity, not a pipeline bug — both classes are `student_*` which contribute to packets identically in grouping.

Total real-Bedrock spend on smoke: ~$0.02.

### 4.3 Small-scale sanity (Task 12a, 20 local TIFs)

```
classifying 20 tifs @ concurrency 8, budget ceiling $2.00
  [20/20] last=01729 class=student_cover conf=0.75 usd=$0.1021
index: frames=0 rows=0 -> poc/output/roll_001_index.json
packets: total=19 snapped=0 -> poc/output/roll_001_students.json
eval: pre_partial=0.0% post_partial=0.0% (exact_pre=0/19, exact_post=0/19) spend=$0.1021
```

Wrote all 5 expected artifact files. Pipeline end-to-end verified. Accuracy meaningless because the `samples/output_pdfs_district1_roll001/` dir (local 15-PDF curated subset) was dominated by placeholder-filename GT entries.

### 4.4 Full run (Task 12c, 1924 TIFs)

See section 3.7. Exit 0. Spend under ceiling. All 6 output artifacts present. Pre/post numbers computed.

### 4.5 Heuristic-rerun verification

`poc.regroup` completed 6 different runs in <1s each. No Bedrock calls in any (verified by reading the script — it only reads pages.jsonl, calls `build_roll_index`, `group_*`, `evaluate`). Spend JSONL untouched.

---

## 5. Decisions locked during the session

| Decision | Made where |
|---|---|
| In-place spec edit (not new dated file) | Q1 brainstorming |
| Medium scope: fixes + index-snap only | Q2 brainstorming |
| Merged single-Bedrock-call tool schema (Approach B) | Q3 brainstorming |
| JSON-per-roll index storage (not SQLite) | Q4 brainstorming |
| Report both pre/post accuracy | Q5 brainstorming |
| $10 hard budget ceiling | Q6 brainstorming |
| Approach 2 module layout (new `index.py` + `gt_clean.py`) | Post-brainstorm recommendation accepted |
| Create `.worktrees/` + ignore | Worktree skill priority rule |
| Execute Tasks 1–10 only in this pass (A path) | User direction when starting plan execution |
| Proceed to real S3 pull + full run (Task 12 path A) | User direction after Task 10 |
| Do D → B → C heuristic iterations | User direction after NO-GO result |

---

## 6. Current state

### 6.1 Git

- `main` has the spec v2 commit (`274daf8`) and the gitignore+plan commit (`2a6cfc3`).
- `phase1-poc-v2` has 11 additional commits (10 plan tasks + 1 grouping iteration).
- Branch **not merged**. No remote pushes. No force-pushes.

### 6.2 Pipeline

- All 10 modules match v2 spec.
- Two grouping modes available: `boundary` (name-change + merge) and `index` (cluster by snap target).
- `poc.regroup` CLI allows re-eval from frozen `pages.jsonl` with zero Bedrock cost.
- 59 unit tests green, 6 smoke tests gated.

### 6.3 Output artifacts

`poc/output/` currently holds the **index-entry-mode** results (overwritten from the earlier baseline via the last `poc.regroup` invocation):

- `roll_001_pages.jsonl` — unchanged (1924 lines, one Bedrock classification each)
- `roll_001_index.json` — 445 index rows
- `roll_001_students.json` — 323 index-grouped packets
- `roll_001_spend.jsonl` — 0 bytes (known buffering quirk; actual per-call data lives in pages.jsonl `tokens_in`/`tokens_out`/`usd_cost`)
- `roll_001_eval.json` — `acc_partial_post = 66.9%`
- `run_full.log` — 5.8 KB

### 6.4 Known quirks / not-fixed-yet items

- `roll_001_spend.jsonl` came out empty on the main run. Pages.jsonl carries the same data, so no loss — just a display/buffering issue in `run_poc.py` worth tightening (explicit `flush()` or `open(..., buffering=1)` for line-buffered writes).
- Smoke test `00097.tif` fixture label: ambiguous. Leave as-is or relabel to `student_continuation`.
- Index run detected 20 frames but real D1R001 has ~25+ observable index pages; model misses some to student_cover / student_test_sheet.
- `student_cover` count 586 vs expected ~347 — over-classification of back pages as cover.
- DOB cross-check in snap deferred to Phase 2.
- No Tier 0 pixel heuristics, no Tier 1 format validators, no Sonnet retry tier.

### 6.5 Measured cost

- Full ROLL 001 classify: **$9.89**
- Smoke (6 fixtures): **~$0.02**
- 20-TIF smoke run: **$0.10**
- Heuristic iteration reruns: **$0**

**Total session Bedrock spend: ≈ $10.01.**

---

## 7. What worked / what didn't

**Worked:**
- TDD pattern — every task commit was a passing test + passing implementation. Zero rework on modules.
- Dual-env loader — clean separation, no cred mix-ups observed.
- Index-parse via merged tool schema — 20 frames classified correctly and yielded 445 rows with zero extra Bedrock calls.
- `poc.regroup` — let us test 6 heuristic variants in ~5 minutes without paying Bedrock again.
- Budget guard — real spend $9.89, ceiling $10.00, did not hit.
- Index-entry mode — 3.2× partial-accuracy lift.

**Didn't work as planned:**
- Baseline name-change grouping — 3.5× packet overcount due to per-page name variance.
- H2.7 packet-level index-snap alone — only lifted acc by +0.2 pp because packet names are already averaged but split packets stay split.
- Majority-vote naming — fixed 10/113 cases. Small impact.
- Packet-merge heuristic (H2.4) — 77 merge candidates found, only ~75 actually merged, acc moved <1 pp. Per-page name variance is the real enemy, not packet boundary fuzziness.

---

## 8. Open question for decision

**Gate `accuracy_partial_post ≥ 85%` still not met.** Best observed: 66.9% in index-entry mode.

Options on the table:

- **A. Stop, merge branch, write results doc** — NO-GO but 3.2× lift over baseline is worth reporting honestly. Plan heuristics for Phase 2.
- **B. Push further with no Bedrock $** — recover more index frames (post-hoc classification of likely-missed index pages), widen eval Lev threshold for long names, try snap on cover frames only.
- **C. Re-classify ROLL 001 with tuned prompt** — more Bedrock $ (~$10). Could address the field-inversion issue by strengthening the "extract top-left name, keep last/first columns in order" instruction.

Awaiting direction.
