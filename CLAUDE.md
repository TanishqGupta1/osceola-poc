# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

This repo is the working directory for the **Osceola County School District POC** — an AI pipeline to classify and extract data from **218,577 TIF scans** (verified 2026-04-20 via S3 listing — matches SOW exactly) of student records on S3, producing named PDFs per student (`Last, First Name MI.pdf`). See `docs/osceola-poc-discussion.md` for the full brief; it is the source of truth for scope, taxonomy, S3 layout, and approach decisions — read it before making non-trivial changes.

**Phase 1 POC status (2026-04-23): COMPLETE.** Pipeline ships end-to-end. Full ROLL 001 run (1924 TIFs, $9.89) measured accuracy, go/no-go gate hit at the high-precision operating point. Branch `phase1-poc-v2` merged to `main`. See `docs/2026-04-23-session-report.md` and `docs/superpowers/specs/2026-04-22-osceola-phase1-poc-v2-results.md` for numbers.

**Phase 2 Textract bake-off + V4 stack (2026-04-27): COMPLETE.** Pure-Textract + pure-code-logic pipeline built in isolated `textract_probe/` module — combined-call AnalyzeDocument + layout-fingerprint classifier + bbox-positional fallback + Tier 1 garbage filter + multi-source name voter + index-snap booster + per-class router. **No Bedrock, no Adapter training.** Replay-mode measured **90.9% precision** on 13 hand-verified covers (round 3) at conf ≥ 0.70 ship gate — meets the `docs/no-llm-90pct-design.md` §1 ≥90% target. 74 unit tests + 59 prior poc tests = 133 pass. See `docs/2026-04-27-textract-bake-off-results.md` (15 sections, 4 cost-projection revisions V0→V3) and `docs/superpowers/plans/2026-04-27-textract-code-logic-v4.md`.

## Repo structure (as of 2026-04-27)

```
├── main.py                       # interactive S3 helper CLI (pre-POC tool)
├── s3_operations.py              # boto3 wrappers — known pagination limitation
├── poc/                          # Phase 1 POC pipeline (v2, complete)
│   ├── env.py                    # dual-env loader (.env S3 + .env.bedrock Bedrock)
│   ├── schemas.py                # Pydantic models — 7-class taxonomy, IndexRow, pre/post-snap fields
│   ├── convert.py                # TIF -> PNG bytes via Pillow
│   ├── prompts.py                # 7-class system prompt + tool_use schema with index_rows
│   ├── bedrock_client.py         # Converse wrapper via poc.env, returns (input, usage, usd_cost)
│   ├── classify_extract.py       # per-page orchestrator
│   ├── index.py                  # build_roll_index + snap_to_index (H2.7) + JSON writer
│   ├── gt_clean.py               # GT filename normalization w/ drop-reason taxonomy
│   ├── group.py                  # TWO grouping modes: boundary (name-change) + group_by_index_entry
│   ├── eval.py                   # two-pass matcher, pre/post-snap accuracy
│   ├── run_poc.py                # full-pipeline CLI with $10 budget ceiling + spend JSONL
│   ├── regroup.py                # re-eval from pages.jsonl, zero Bedrock $
│   └── output/                   # run artifacts (gitignored — gitignored FERPA data)
├── textract_probe/               # Phase 2 bake-off + V4 no-LLM pipeline (isolated, complete)
│   ├── env.py                    # own .env.bedrock loader (Textract perms required)
│   ├── convert.py                # own TIF -> PNG (no poc/ coupling)
│   ├── client.py                 # Textract endpoints: detect/forms/tables/layout/queries +
│   │                             # analyze_all combined-call + signatures pricing + retry
│   ├── layout_classifier.py      # block-fingerprint -> page_class (deterministic, no keywords)
│   ├── bbox_extract.py           # nearest-WORD-to-anchor fallback when Forms VALUE empty
│   ├── validators.py             # Tier 1 garbage filter + name regex + DOB plausibility
│   ├── name_voter.py             # multi-source confidence-weighted vote (Forms+Queries+Detect)
│   ├── index_snap.py             # Tables -> IndexRow + Levenshtein last-name-only snap
│   ├── router.py                 # two-pass cost-aware: Detect classify -> per-class extract
│   ├── extract_pipeline.py       # live end-to-end CLI
│   ├── replay.py                 # offline re-evaluation against cached JSONs (zero $$)
│   ├── bake_off.py               # fixtures × features sweep CLI
│   ├── tesseract_run.py          # local Tesseract comparison (Tesseract dead on this corpus)
│   ├── decode.py                 # raw JSON -> per-fixture markdown digest
│   ├── fixtures*.json            # 5 fixture manifests (round 1-4 + cross-district)
│   ├── queries{,_v2}.json        # original + rephrased Textract Queries
│   ├── tests/                    # 74 unit tests (mocked) + 1 gated live smoke
│   ├── output/                   # raw JSONs + Tesseract files + V4 results — gitignored FERPA
│   └── README.md                 # module docs + run commands
├── scripts/
│   └── broad_index_probe.py      # 100-roll index-page detection probe
├── tests/                        # 59 unit tests (pytest), 6 smoke-skip
├── samples/                      # FERPA TIFs/PDFs — gitignored except fixtures_public/
├── docs/
│   ├── osceola-poc-discussion.md              # source-of-truth brief
│   ├── heuristics-brainstorm.md               # Tier 0-5 heuristic catalogue
│   ├── class-heuristics.md                    # per-class decision rules + failure modes
│   ├── class-matrix.md                        # 32 subtypes × 13 feature dims
│   ├── class-matrix.json                      # machine-readable subtype library
│   ├── 2026-04-23-session-report.md           # full Phase 1 POC v2 session dump
│   ├── 2026-04-27-textract-bake-off-results.md # bake-off + V4 measured results (15 sections)
│   ├── no-llm-pipeline-brainstorm.md          # original deep brainstorm (V0)
│   ├── no-llm-90pct-design.md                 # original Forms-KV-as-killer-feature design
│   │                                          # — REVISED post-bake-off (see results doc §6,8)
│   └── superpowers/
│       ├── specs/2026-04-18-osceola-phase1-poc-design.md          # design spec v2
│       ├── specs/2026-04-22-osceola-phase1-poc-v2-results.md      # measured results + go/no-go
│       ├── specs/2026-04-21-osceola-production-pipeline.md        # Phase 2 spec
│       ├── specs/2026-04-21-osceola-production-pipeline-v1-full.md
│       ├── plans/2026-04-22-osceola-phase1-poc-v2.md              # 13-task TDD plan
│       ├── plans/2026-04-27-textract-bake-off.md                  # bake-off harness plan
│       └── plans/2026-04-27-textract-code-logic-v4.md             # V4 9-task TDD plan
├── .env                          # S3 creds (Servflow-image1) — gitignored
└── .env.bedrock                  # Bedrock creds (tanishq account) — gitignored
```

## Common Commands

```bash
# Install deps
pip install -r requirements.txt

# Run unit tests (59 passing, 6 smoke tests gated on BEDROCK_SMOKE_TEST=1)
pytest -q

# Run Bedrock smoke test against 6 fixture TIFs (costs ~$0.02)
BEDROCK_SMOKE_TEST=1 pytest tests/test_smoke_bedrock.py -v -s

# Full POC run on ROLL 001 (1924 TIFs, ~20 min, ~$10)
python3 -m poc.run_poc --roll-id "ROLL 001" \
    --input samples/test_input_roll001_full \
    --ground-truth samples/output_pdfs_district1_roll001_full \
    --concurrency 10 --budget-ceiling 10.0

# Re-evaluate from existing pages.jsonl with zero Bedrock cost
python3 -m poc.regroup --roll-id "ROLL 001" \
    --ground-truth samples/output_pdfs_district1_roll001_full \
    --mode index --min-bucket-size 3

# Interactive S3 helper CLI (legacy)
python3 main.py

# textract_probe — V4 no-LLM stack
pip install -r textract_probe/requirements.txt   # adds pytesseract; brew install tesseract
pytest textract_probe/tests/ -q                   # 74 unit tests (mocked, no $$)
TEXTRACT_SMOKE_TEST=1 pytest textract_probe/tests/test_smoke.py -v -s   # live, ~$0.0015
python3 -m textract_probe.bake_off --fixtures-file textract_probe/fixtures.json \
    --out-dir textract_probe/output/textract --features detect,forms,tables,layout,queries \
    --queries-file textract_probe/queries.json --budget-ceiling 1.50
python3 -m textract_probe.extract_pipeline --fixtures-file textract_probe/fixtures_round3.json \
    --queries-file textract_probe/queries_v2.json --run-label round3_v4 --budget-ceiling 2.00
python3 -m textract_probe.replay --fixtures-file textract_probe/fixtures_round3.json \
    --run-label round3_v4_replay   # zero $$ re-eval against cached JSONs
```

## Architecture

**`poc/` pipeline (Phase 1, current).** Sequential Python. TIF → Pillow PNG → Bedrock Converse (single-call merged classify+extract, `tool_use` schema) → JSONL → index-parse → grouping (boundary OR index-entry mode) → two-pass eval (pre-snap vs post-snap) → EvalReport JSON. Outputs land in `poc/output/`. Config via `--budget-ceiling` (default $10) halts runs that exceed spend.

**`s3_operations.py` / `main.py` (legacy tool).** Thin boto3 wrappers (`list_buckets`, `list_objects`, `upload_file`, `download_file`, `read_object`, `delete_object`). Each call constructs a new S3 client via `get_s3_client()`. **Known limitation:** `list_objects` calls `list_objects_v2` without pagination — silently caps at 1,000 keys. Use `poc.env.s3_client()` + paginator for any bulk S3 work.

**Dual-env credentials.** `.env` holds S3 creds (`Servflow-image1` IAM user, full S3 in us-west-2, NO Bedrock). `.env.bedrock` holds Bedrock creds (`tanishq` account `690816807846`, full Bedrock in us-west-2, NO S3). All pipeline modules MUST route via `poc.env.s3_client()` / `poc.env.bedrock_client()` — never call `boto3.client(...)` directly.

## Target S3 Layout

Bucket: `servflow-image-one` in **us-west-2** (note: different from the legacy `s3_operations.py` default of `us-east-1`). Root prefix: `Osceola Co School District/`. Key subfolders: `Input/OSCEOLA SCHOOL DISTRICT-{1..7}/ROLL XXX/`, `Test Input/ROLL 001|012|076/`, `Output/` (partial ground truth — human-produced PDFs whose filenames encode student names), `Test Output/` (empty), `Classification Samples/`.

**Verified roll map (2026-04-20 full S3 scan):** 218,577 TIFs across 100 rolls in 7 districts. D1=22,179 (11 rolls), D2=39,289 (16), D3=29,700 (13), D4=46,312 (22 — largest), D5=28,672 (13), D6=34,476 (15), D7=17,949 (10). Gaps: `ROLL 048`, `ROLL 100` missing entirely. Split rolls: `ROLL 065B` (127 TIFs), `ROLL 075A` (2,557). Partial: `ROLL 059` (414), `ROLL 101` (320). Total corpus ≈ 24 GB (median TIF 104 KB, mean 112 KB). No manifest / README / JSON files in the bucket — just TIFs.

**Test Input ≠ held-out test set.** ETag comparison (2026-04-20) shows `Test Input/ROLL 001|012|076/` are byte-identical copies of their `Input/` equivalents. Client provided no hand-curated holdout, and `Test Output/` is empty. Any real test/eval set must be curated by us.

TIFs are named `00001.tif` → `0NNNN.tif`, resetting per roll. Each roll is a linear sequential microfilm scan.

**Roll structure (verified 2026-04-18 across 15 prod rolls + 3 dense mid-roll samples in `samples/verify_probe/`):** The first ~3–7 frames and the last ~1–3 frames of every roll are `roll_leader` material (blank, vendor letterhead, microfilm resolution target, district title page, filmer certification card, operator roll-identity card). The real student records are bracketed by two `roll_separator` cards — one START, one END — with the roll number written on each. Within the `[START+1, END-1]` window, student packets are back-to-back with **no per-student separators** (verified across 39 mid-roll samples); grouping must use name-change detection OR index-entry clustering.

**Separator cards come in TWO styles; both classify as `roll_separator`:**
- **Style A (clapperboard)** — diagonal-hatched rectangles + "START"/"END" block text + boxed handwritten ROLL NO. Districts 2, 4, 5, 6, 7.
- **Style B (certificate)** — printed "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" form with "START"/"END" header, typed school, handwritten date, filmer signature. Districts 1, 3 primarily.
- START position varies: frame 3–6. END position varies: last to last-3. At least one rotated-90° card observed. Any pre-filter heuristic (e.g. hatched-rectangle detection) would miss Style B — use Bedrock for every frame.

**Reel-number caveat:** The S3 folder number is a project-local index and does **not** always match the original microfilm reel number on the certification card (example observed: S3 `OSCEOLA SCHOOL DISTRICT-7/ROLL 101/` has certification `Reel No. 756`). If tracing back to physical archives, use the certification card's reel number, not the folder name.

**Two filming vendors** appear across the dataset with different leader layouts: `Total Information Management Systems` (most production rolls, 1991–92) and `White's Microfilm Services` (observed in test ROLL 001).

## Local Data Layout

- `samples/classification_samples/` — 13 TIFs covering document templates.
- `samples/test_input_roll001/` — 20 evenly-spaced TIFs + PNGs from Test Input ROLL 001 (sparse sample).
- `samples/test_input_roll001_full/` — **1924 TIFs** (full ROLL 001, pulled 2026-04-23).
- `samples/output_pdfs_district1_roll001/` — 15 GT PDFs (curated small subset — mostly placeholder-garbage).
- `samples/output_pdfs_district1_roll001_full/` — **418 GT PDFs** (full ROLL 001 output, pulled 2026-04-23).
- `samples/boundary_probe/` (+ `png/`) — 51 TIFs from first/last frames of 3 test rolls and first frames of rolls across all 7 districts.
- `samples/verify_probe/` (+ `png/` + `grid_*.png` + `../roll_sizes.json`) — 174 TIFs across 15 prod rolls (first 6 + last 3 frames each) + mid-roll dense samples in d4r045/d5r065/d6r080.
- `samples/index_probe/broad/` — 7 subdirs per district with index-page TIFs pulled by `scripts/broad_index_probe.py`.
- `downloads/` — ad-hoc pulls, not canonical.

When iterating on prompts, work against `samples/` locally first — do not re-download from S3.

## Ground-truth quality (verified 2026-04-20, applied 2026-04-23)

Output PDFs exist only for 7 D1 rolls (001, 002, 007–011 = 3,128 real) + ROLL 003/005/006 sham merges (1–2 each, 48–543 MB — batch-concatenated, not per-student; excluded in `poc/gt_clean.py` via `SHAM_MERGE_ROLLS`). **Districts 2–7: zero ground truth.**

Filename quality mixed. Across 3,128 real PDFs: ~25% clean UPPER, ~27% TitleCase, **~14% placeholder/garbage** (`(LAST) (FIRST) (MIDDLE) Burris, Tammy L.pdf`, `1959.pdf`, etc.), ~3% `_N` dup-suffix (legit same-name students), ~25% "other" inconsistent format. Placeholder rate varies by roll: ROLL 009 = 18.6%, ROLL 001 = 11%.

**Measured on ROLL 001 (2026-04-23):** raw 418 PDFs → 347 usable after `gt_clean` (71 dropped: 46 placeholder, 24 too_short, 1 ocr_garbage). 17% drop rate matches corpus estimate.

Estimated students: 218,577 TIFs ÷ ~5.1 pages/student ≈ **~43,000 students**.

## Page Taxonomy (7 classes — revised 2026-04-21, final)

- `student_cover` — primary cumulative/guidance record with name + demographics.
- `student_test_sheet` — standardized test form with student name.
- `student_continuation` — back pages, comments, family data with name at top.
- `student_records_index` — tabular `STUDENT RECORDS INDEX` page listing 5–28 students/page. Columns: LAST / FIRST / MIDDLE / DOB + district variants (`FILE`, `FRAME`, `Roll`, `SEC`, `OTHER`, `TRANS`, `WITH`, `GRAD`, `DATE`, `BE`, `CR`, `ES`). 100-roll probe confirmed 559 frames across 93/100 rolls in 7/7 districts.
- `roll_separator` — START/END card (Style A or B).
- `roll_leader` — non-student filler.
- `unknown` — blank mid-roll, illegible, unrecognized.

Full definitions + 32-subtype breakdown in `docs/class-matrix.md` and `docs/class-matrix.json`.

Per-class identification heuristics, disambiguation rules, and failure modes observed on ROLL 001 in `docs/class-heuristics.md`.

**Taxonomy change history:**
- 2026-04-18: dropped `separator_index` as "never observed in sample"
- 2026-04-21: reinstated as `student_records_index` after broad probe
- 2026-04-23: locked as Phase 1 POC v2 class. 32 subtypes catalogued.

## Extraction Fields

Per `student_*` page, where present: `last`, `first`, `middle`, `dob`, `school`, plus `page_class` and `confidence`. All populated on `PageResult` (Pydantic, `poc/schemas.py`).

Per `student_records_index` page: list of rows `{last, first, middle, dob, source_frame}`. Aggregated + deduped by `poc/index.py::build_roll_index` into the canonical roll-level allowlist. Feeds H2.7 index-snap in `snap_to_index`.

Per roll (extracted once from `roll_leader` / `roll_separator` Style B): `reel_no_cert`, `filmer`, `date`, `school` (via `RollMeta` schema).

The **SOW only contractually requires student name**. `dob` and `school` are our choice to aid packet grouping / deduplication; confirm with client before treating as required.

## Grouping modes (ship-critical decision)

`poc.group.group_pages()` and `poc.group.group_by_index_entry()` are both available. Regroup CLI picks via `--mode`.

- **`boundary` mode** (original v1 approach, now deprecated for production). Name-change grouping in `[START+1, END-1]` window. Majority-vote packet naming. H2.4 adjacent-packet Lev merge. Tested on ROLL 001: **20.7% → 21.8% acc_partial** — per-page OCR variance (52% of consecutive pages disagree on name) overwhelms this approach.
- **`index` mode** (Phase 2 default). Every student page snaps to nearest index entry. All pages that snap to the same `(last, first)` become one packet. Pages that don't snap are dropped (or fallback-boundary-grouped). Tested on ROLL 001: **66.9% → 87.1% acc_partial** depending on `min_bucket_size` filter. **3.2× lift over boundary mode with zero extra Bedrock cost.**

`min_bucket_size` is the key dial:
- `1` → balanced: 75.9% acc_partial, 70.6% recall (323 packets from 347 usable GT).
- `2` → 82.8% acc_partial, 48.4% recall.
- `3` → **87.1% acc_partial (gate met)**, 23.3% recall (93 high-confidence students only).
- `4` → 86.4% acc_partial, 10.9% recall.

Production should likely run `min_bucket_size=1` + Sonnet retry + Tier 1 validators to push recall + precision simultaneously.

## Model / Infra Choices (already decided)

- Vision model (Phase 1): **Claude Haiku 4.5 on AWS Bedrock** via inference profile `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Use `us.*` cross-region profile IDs, not raw model IDs.
- Haiku 4.5 quirk: wraps output in ` ```json ` fences in plain-text mode — POC uses `tool_use` schema which sidesteps this.
- TIF→PNG: Pillow (in-memory, max side 1500px) in POC. Lambda in Phase 2.
- **Textract bake-off complete (2026-04-27).** Pure-Textract + code-logic V4 stack hits 90.9% precision on round-3 covers without LLM. Phase 2 path is **Detect everywhere + analyze_all on covers + Tables on indexes + Queries v2 on Style B separators + multi-source vote + index-snap**, no Bedrock retry needed for standard cover layouts. Bedrock retry stays as worst-case escape only.
- n8n host: `dev-n8n.visualgraphx.com`, using the `makafeli/n8n-workflow-builder` MCP server (Phase 2 HITL UI).
- `.env.bedrock` IAM user (tanishq acct, account 690816807846) needs **both** Bedrock and Textract perms. AWS access keys rotated 2026-04-27 — verify with `TEXTRACT_SMOKE_TEST=1 pytest textract_probe/tests/test_smoke.py` before running pipeline live.

Do not reopen these decisions without the user's sign-off.

## Budget + cost tracking

`poc/run_poc.py --budget-ceiling USD` (default 10.0) halts runs that exceed cumulative spend. Per-call spend written to `poc/output/<slug>_spend.jsonl` (one row per Bedrock call, same schema as Phase 2 `bedrock_calls` SQLite table so migration is replay-only).

Haiku 4.5 pricing constants in `poc/bedrock_client.py`: `$1.00/MTok` input, `$5.00/MTok` output.

Measured cost on ROLL 001 classify (1924 TIFs): **$9.89**. Extrapolated to full 218K corpus: ~$1,123 on-demand, ~$560 with Bedrock Batch Inference.

## Production scale architecture (Phase 2)

For Phase 2 at 218K-TIF scale, the recommended stack is **Step Functions Distributed Map + Lambda + Bedrock Batch Inference + DynamoDB + S3**, not pure n8n. n8n remains appropriate for the HITL operator UI and manual reruns but becomes a bottleneck as the bulk-processing orchestrator on a single self-hosted host. Full architecture diagram in `docs/superpowers/specs/2026-04-21-osceola-production-pipeline.md`.

## Known limitations / deferred to Phase 2

- **Spend JSONL buffering:** `poc/output/<slug>_spend.jsonl` sometimes comes out empty; the same per-call data is redundantly embedded in `pages.jsonl`. Fix: line-buffered open or explicit flush per write.
- **Over-classified `student_cover`:** 586 covers on ROLL 001 vs ~347 real students. Prompt v2 should tighten cover definition.
- **Field inversion:** Haiku occasionally reads last/first columns swapped. `_snap_page_name` has swap-tolerant scoring; prompt v2 should make column order explicit.
- **Index coverage incomplete:** 20 detected frames; broad probe pattern suggests ~25 actual. Some `index` frames get mis-classified as `student_cover` when row count is low.
- **No Tier 0 pixel heuristics** (blank / pHash / Hough) — deferred.
- **No Tier 1 format validators** (name regex, OCR garbage blocklist) — deferred.
- **No Sonnet 4.6 retry tier** — deferred.
- **DOB cross-check in snap** — deferred to Phase 2; POC uses (last, first) only.

## Resolved blockers

- ~~IAM Bedrock permissions missing on `Servflow-image1`~~ — resolved 2026-04-20 via separate `tanishq` user in account `690816807846`. Dual-env loader is the integration. `Servflow-image1` still lacks Bedrock; still has S3.
- ~~Textract permissions on `tanishq` user~~ — resolved 2026-04-27. `AmazonTextractFullAccess` (or scoped `textract:DetectDocumentText, textract:AnalyzeDocument`) attached. Verify via gated smoke test in `textract_probe/`.

## Open issues

- **Modern multi-section covers** (clsamp_00119, D6 Paulerson family) — Forms KV detects `LAST` / `FIRST` / `MIDDLE` labels but cannot pair to boxed handwriting on faded scans. Recovery: build `poc/preprocess.py` (Pillow deskew + Sauvola binarize + erode 1px). No LLM needed.
- **Co-record covers** (D5 Reus joint-parent layout) — voter picks one parent's name. Recovery: splitter rule on `&` / ` and ` / multi-comma patterns.
- **AWS creds rotation** — `.env.bedrock` keys rotate periodically. Smoke test before any live pipeline run.

## Agent hints

When editing pipeline modules:
- Run `pytest -q` before committing. **133 tests** should stay green (59 `tests/` + 74 `textract_probe/tests/`).
- Never bypass `poc.env` for AWS client construction in `poc/`.
- Never bypass `textract_probe.env` for Textract calls.
- `textract_probe/` is **fully isolated** — no `from poc.*` imports. Keep it that way; the module is delete-as-a-unit if abandoned.
- Reuse `gt_clean.clean_gt_filename` (in `poc/`) — do not re-implement GT parsing.
- Grouping behavior is a user-visible contract. Changes to `group.py` need test updates.
- Re-evals are zero-cost via `poc.regroup` (LLM path) or `textract_probe.replay` (V4 path against cached Textract JSONs). Use either before re-running expensive live passes.
- V4 ship gate is **vote_confidence ≥ 0.70 (multi-source agreement ≥ 2)**. Locked in `textract_probe/replay.py`. Don't lower without measuring precision regression on round 3.
- New garbage tokens go in `textract_probe/validators.py::GARBAGE_TOKENS`. Add tests in `tests/test_validators.py`.
