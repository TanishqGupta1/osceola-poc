# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

This repo is the working directory for the **Osceola County School District POC** — an AI pipeline to classify and extract data from ~218,677 TIF scans of student records on S3, producing named PDFs per student (`Last, First Name MI.pdf`). See `docs/osceola-poc-discussion.md` for the full brief; it is the source of truth for scope, taxonomy, S3 layout, and approach decisions — read it before making non-trivial changes.

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

Bucket: `servflow-image-one` in **us-west-2** (note: different from the code's default region). Root prefix: `Osceola Co School District/`. Key subfolders: `Input/OSCEOLA SCHOOL DISTRICT-{1..7}/ROLL XXX/`, `Test Input/ROLL 001|012|076/`, `Output/` (partial ground truth — human-produced PDFs whose filenames encode student names), `Classification Samples/`.

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
