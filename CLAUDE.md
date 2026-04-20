# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

This repo is the working directory for the **Osceola County School District POC** — an AI pipeline to classify and extract data from **218,577 TIF scans** (verified 2026-04-20 via S3 listing — matches SOW exactly) of student records on S3, producing named PDFs per student (`Last, First Name MI.pdf`). See `docs/osceola-poc-discussion.md` for the full brief; it is the source of truth for scope, taxonomy, S3 layout, and approach decisions — read it before making non-trivial changes.

Today the repo contains only a small boto3-based S3 helper CLI (`main.py` + `s3_operations.py`). The POC pipeline scripts (`convert.py`, `classify.py`, `extract.py`, `group.py`, `eval.py`, `run_poc.py`) described in the discussion doc do **not** exist yet — they are the planned Phase 1 work. Phase 2 moves to n8n + Lambda (see the empty `n8n/` placeholder).

## Common Commands

```bash
# Install deps
pip install -r requirements.txt

# Run the interactive S3 menu (requires .env with AWS creds)
python main.py
```

There is no test suite, linter, or build step configured.

## Architecture

**`s3_operations.py`** — thin boto3 wrappers (`list_buckets`, `list_objects`, `upload_file`, `download_file`, `read_object`, `delete_object`). Each call constructs a new S3 client via `get_s3_client()` using env vars `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (defaults to `us-east-1`). Errors are caught as `ClientError`, printed, and functions return `None` / `[]` / `False`.

**`main.py`** — `load_dotenv()` → env-var check → menu loop dispatching to `s3_operations` functions. Bucket name comes from `S3_BUCKET_NAME` env or an interactive prompt via `get_bucket_name()`.

**Known limitation:** `list_objects` calls `list_objects_v2` without pagination — silently caps at 1,000 keys. Real roll folders in the target bucket have up to ~2,665 objects, so pagination must be added before running against production data.

## Target S3 Layout

Bucket: `servflow-image-one` in **us-west-2** (note: different from the code's default region). Root prefix: `Osceola Co School District/`. Key subfolders: `Input/OSCEOLA SCHOOL DISTRICT-{1..7}/ROLL XXX/`, `Test Input/ROLL 001|012|076/`, `Output/` (partial ground truth — human-produced PDFs whose filenames encode student names), `Test Output/` (empty), `Classification Samples/`.

**Verified roll map (2026-04-20 full S3 scan):** 218,577 TIFs across 100 rolls in 7 districts. D1=22,179 (11 rolls), D2=39,289 (16), D3=29,700 (13), D4=46,312 (22 — largest), D5=28,672 (13), D6=34,476 (15), D7=17,949 (10). Gaps: `ROLL 048`, `ROLL 100` missing entirely. Split rolls: `ROLL 065B` (127 TIFs), `ROLL 075A` (2,557). Partial: `ROLL 059` (414), `ROLL 101` (320). Total corpus ≈ 24 GB (median TIF 104 KB, mean 112 KB). No manifest / README / JSON files in the bucket — just TIFs.

**Test Input ≠ held-out test set.** ETag comparison (2026-04-20) shows `Test Input/ROLL 001|012|076/` are byte-identical copies of their `Input/` equivalents. Client provided no hand-curated holdout, and `Test Output/` is empty. Any real test/eval set must be curated by us.

TIFs are named `00001.tif` → `0NNNN.tif`, resetting per roll. Each roll is a linear sequential microfilm scan.

**Roll structure (verified 2026-04-18 across 15 prod rolls + 3 dense mid-roll samples in `samples/verify_probe/`):** The first ~3–7 frames and the last ~1–3 frames of every roll are `roll_leader` material (blank, vendor letterhead, microfilm resolution target, district title page, filmer certification card, operator roll-identity card). The real student records are bracketed by two `roll_separator` cards — one START, one END — with the roll number written on each. Within the `[START+1, END-1]` window, student packets are back-to-back with **no per-student separators** (verified across 39 mid-roll samples); grouping must use name-change detection.

**Separator cards come in TWO styles; both classify as `roll_separator`:**
- **Style A (clapperboard)** — diagonal-hatched rectangles + "START"/"END" block text + boxed handwritten ROLL NO. Districts 2, 4, 5, 6, 7.
- **Style B (certificate)** — printed "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" form with "START"/"END" header, typed school, handwritten date, filmer signature. Districts 1, 3 primarily.
- START position varies: frame 3–6. END position varies: last to last-3. At least one rotated-90° card observed. Any pre-filter heuristic (e.g. hatched-rectangle detection) would miss Style B — use Bedrock for every frame.

**Reel-number caveat:** The S3 folder number is a project-local index and does **not** always match the original microfilm reel number on the certification card (example observed: S3 `OSCEOLA SCHOOL DISTRICT-7/ROLL 101/` has certification `Reel No. 756`). If tracing back to physical archives, use the certification card's reel number, not the folder name.

**Two filming vendors** appear across the dataset with different leader layouts: `Total Information Management Systems` (most production rolls, 1991–92) and `White's Microfilm Services` (observed in test ROLL 001).

## Local Data Layout

- `samples/classification_samples/` — 13 TIFs covering the document templates (NB: SOW called these "separators", but they are mostly content templates, not separator cards)
- `samples/test_input_roll001/` — 20 evenly-spaced TIFs + PNGs from Test Input ROLL 001
- `samples/output_pdfs_district1_roll001/` — 15 human-produced output PDFs (ground truth for extraction eval)
- `samples/boundary_probe/` (+ `png/`) — 51 TIFs from first/last frames of 3 test rolls and first frames of rolls across all 7 districts; evidence for the roll-leader + Style A clapperboard structure
- `samples/verify_probe/` (+ `png/` + `grid_*.png` classification grids + `../roll_sizes.json`) — 174 TIFs pulled later on 2026-04-18 across 15 prod rolls (first 6 + last 3 frames each) plus mid-roll dense samples (every ~200 frames) in d4r045/d5r065/d6r080. Confirms two separator styles, variable START/END positions, no mid-roll separators.
- `downloads/` — ad-hoc pulls, not canonical

When iterating on prompts, work against `samples/` locally first — do not re-download from S3.

## Ground-truth quality (verified 2026-04-20)

Output PDFs exist only for 7 D1 rolls (001, 002, 007–011 = 3,128 real) + ROLL 003/005/006 sham merges (1–2 each, 48–543 MB — batch-concatenated, not per-student; exclude from eval). **Districts 2–7: zero ground truth.** Processing dates 2026-03-05 to 2026-03-11 — recent, likely ongoing.

Filename quality is mixed. Across 3,128 real PDFs: ~25% clean UPPER (`SMITH, JOHN.pdf`), ~27% TitleCase, **~14% placeholder/garbage** (`(LAST) (FIRST) (MIDDLE) Burris, Tammy L.pdf`, `1959.pdf`, `611 Eblin Carl Byren (FIRST) (MIDDLE).pdf`, `(LAST) (FIRST) MIDDLE) COUNTY. PLACE OF BIRTHth amb SEX E (CITY) Barton, Virginia Ley (COUNTY).pdf`), ~3% `_N` duplicate-suffix (legit same-name students — 3,131 unique names in 3,132 files), ~25% "other" inconsistent format (extra commas, multi-word middles like `Carter, Della, Priscilla,.pdf`). Placeholder rate varies by roll: ROLL 009 = 18.6%, ROLL 001 = 11%.

**Implication:** eval must run a GT-cleaning pass first (strip `(LAST)/(FIRST)/(MIDDLE)` tokens, normalize case, drop rows with embedded OCR garbage like `BIRTH`/`COUNTY`/`SEX`/numeric-only names, exclude ROLL 003/005/006) before comparing AI predictions — else AI accuracy is under-reported against noisy GT.

Estimated students: 218,577 TIFs ÷ ~5.1 pages/student ≈ **~43,000 students** (was 48,600 in earlier docs; new estimate uses D1 median PDF 400 KB ÷ median TIF 104 KB).

## Page Taxonomy (6 classes — revised 2026-04-18)

Classification labels to use in prompts and data:

- `student_cover` — primary cumulative/guidance record with name + demographics
- `student_test_sheet` — standardized test form with student name
- `student_continuation` — back pages, comments, family data with name at top
- `roll_separator` — the START/END clapperboard card bracketing each roll (contains handwritten `ROLL NO. N`)
- `roll_leader` — any non-student filler: blank, vendor letterhead, resolution test target, district title page, filmer certification card, operator roll-identity card
- `unknown` — blank mid-roll, illegible, or unrecognized

`separator_index` (the previously hypothesized multi-student index page) was **dropped** — no such page has been observed in any sample. Full definitions in `docs/osceola-poc-discussion.md`.

## Extraction Fields

Per `student_*` page, where present: `last_name`, `first_name`, `middle_name`, `date_of_birth`, `school`, `page_class`, `confidence`.

The **SOW only contractually requires student name**. `date_of_birth` and `school` are our choice to aid packet grouping / deduplication; confirm with the client before treating them as required.

Per roll (extracted once from `roll_leader` frames): `reel_number_certification`, `filmer_name`, `filming_date`, `filming_vendor`, `school_name_begin`.

## Model / Infra Choices (already decided)

- Vision model: **Claude Haiku 4.5 on AWS Bedrock** (`anthropic.claude-haiku-4-5`)
- TIF→PNG: Pillow locally for POC; Lambda in production. (The doc also mentions `sips` inside an n8n Code Node for the n8n path.)
- Textract is **not** used — Bedrock vision only.
- n8n host: `dev-n8n.visualgraphx.com`, using the `makafeli/n8n-workflow-builder` MCP server.

Do not reopen these decisions without the user's sign-off.

## Production scale architecture (revised 2026-04-18 after 174-sample verification)

For Phase 2 at 218K-TIF scale, the recommended stack is **Step Functions Distributed Map + Lambda + Bedrock Batch Inference + DynamoDB + S3**, not pure n8n. n8n remains appropriate for the HITL operator UI and manual reruns but becomes a bottleneck as the bulk-processing orchestrator on a single self-hosted host. Full architecture diagram and cost estimate (~$335 total for the 218K bulk run; ~1 hr end-to-end with on-demand Bedrock or hours with Batch Inference) are in `docs/osceola-poc-discussion.md`.

## Known blocker

The current IAM user `Servflow-image1` **lacks Bedrock permissions** (`bedrock:ListFoundationModels` returns AccessDenied). A Bedrock-enabled role or new key is required before any POC LLM work.

**IAM capability probe (2026-04-20) on `Servflow-image1`:**
- Works: `s3:ListObjectsV2`, `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:GetBucketVersioning`, `s3:GetBucketTagging` (tag `servflow-image-one=true`, versioning disabled).
- Denied: `s3:ListAllMyBuckets`, `s3:GetBucketLocation`, `s3:GetBucketEncryption`, `s3:GetBucketLifecycleConfiguration`, `s3:GetBucketPolicyStatus`, `s3:GetBucketCors`, **all Bedrock**.

## Model / infra candidates + quick-check bake-off (2026-04-20)

Bedrock access verified: account `690816807846` user `tanishq` (stored in `.env.bedrock`) has full Bedrock perms in `us-west-2`. Use the `us.*` cross-region inference-profile IDs, not raw model IDs (raw IDs error with "on-demand not supported" for newest models). The same account has **no S3 access** → POC must load both `.env` (S3) and `.env.bedrock` (Bedrock).

**Quick bake-off on 4 models × 5 fixture pages (directional only; not a locked choice):**

| Model | Class accuracy | Name extraction | 218K cost | Verdict |
|---|---|---|---|---|
| Claude Haiku 4.5 | 4/5 | correct on both student samples | ~$491 / $245 batch | **Provisional primary** |
| Claude Sonnet 4.6 | 4/5 | correct on both | ~$1,338 | **Retry tier** |
| Amazon Nova Lite | 4/5 | swaps last/first on 1 sample | ~$32 | Drop — SOW name risk |
| Amazon Nova Pro | 2/5 | correct on student pages | ~$422 | Drop — no cost advantage |

All 4 failed on our local `separator_styleB_certificate_START.png` fixture — turned out that fixture is **mis-labeled** (actually vendor letterhead). Re-run with real Style B sample from `samples/verify_probe/png/d1r001_01923.png` when building the >50-page labeled fixture set.

**Other observed quirks:**
- Haiku 4.5 wraps output in ` ```json ` fences — use `tool_use` schema instead of plain text.
- Nova Lite's self-reported confidence is mis-calibrated (0.1 on correct answers).
- Amazon Nova tokenizes images ~30% higher than Claude → Nova Pro cost is near parity with Haiku, not cheaper.

**Provisional Phase 1 pipeline**: Haiku 4.5 primary (via `tool_use`) + Sonnet 4.6 retry on mid-confidence (0.6–0.85) + packet-level majority-vote grouping + HITL below 0.6. Lock only after full bake-off on ≥50 fixtures.
