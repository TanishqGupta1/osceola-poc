# Osceola County School District — POC Discussion Notes
Originated: 2026-04-17
Updated: 2026-04-18 (revised roll structure + taxonomy after boundary-sample probe)
Updated: 2026-04-18 later (verification probe — 174 samples across 15 prod rolls + 3 dense mid-roll; two separator-card styles discovered; refined 218K-scale prod architecture)

---

## Project Overview (from SOW)

- **Client:** Osceola County School District
- **Scope:** 218,577 TIF files of student records
- **Goal:** AI classification + extraction with Human-in-the-Loop (HITL)
- **Output:** Named PDFs — `Last, First Name MI.pdf` — grouped per student, matching input folder structure

---

## S3 Bucket Structure

**Bucket:** `servflow-image-one` (us-west-2)

```
Osceola Co School District/
├── Osceola Co film SOW.docx
├── Classification Samples/         ← 14 TIF sample images
├── Input/                          ← 218,677 TIFs total across 7 districts
│   ├── OSCEOLA SCHOOL DISTRICT-1/  ←  22,190 TIFs, ROLL 001-011
│   ├── OSCEOLA SCHOOL DISTRICT-2/  ←  39,305 TIFs, ROLL 012-027
│   ├── OSCEOLA SCHOOL DISTRICT-3/  ←  29,713 TIFs, ROLL 028-040
│   ├── OSCEOLA SCHOOL DISTRICT-4/  ←  46,334 TIFs, ROLL 041-063 (largest)
│   ├── OSCEOLA SCHOOL DISTRICT-5/  ←  28,685 TIFs, ROLL 064-075A
│   ├── OSCEOLA SCHOOL DISTRICT-6/  ←  34,491 TIFs, ROLL 076-090
│   └── OSCEOLA SCHOOL DISTRICT-7/  ←  17,959 TIFs, ROLL 091-101 (smallest)
├── Test Input/
│   ├── ROLL 001  = 1,924 TIFs
│   ├── ROLL 012  = 2,165 TIFs
│   └── ROLL 076  = 2,613 TIFs
├── Output/                         ← Only DISTRICT-1 partially processed
│   ├── ROLL 001 = 419 PDFs  (of 1,925 TIFs — 4.6 pages/student)
│   ├── ROLL 002 = 297 PDFs
│   ├── ROLL 007 = 488 PDFs
│   ├── ROLL 008 = 467 PDFs
│   ├── ROLL 009 = 483 PDFs
│   ├── ROLL 010 = 500 PDFs
│   ├── ROLL 011 = 474 PDFs
│   └── ROLLs 003-006 = 4 PDFs total (not processed)
└── Test Output/                    ← Empty
```

**File naming:** Every roll resets to `00001.tif` and counts up sequentially (e.g. `00001.tif` → `01924.tif`). All files are `.tif` only.

**Estimated students:** ~218,677 TIFs ÷ 4.5 pages/student avg ≈ **~48,600 students** total.

**Roll size range:** 321 (ROLL 101, partial) to 2,665 (ROLL 034). Most rolls: 1,900–2,650 TIFs.

**Notable gaps/partials:** ROLL 048 missing, ROLL 100 missing, ROLL 059=415, ROLL 039=1,235, ROLL 053=1,071, ROLL 065B=128, ROLL 075A=2,557.

---

## Tech Stack Decisions

| Decision | Choice |
|---|---|
| Cloud | AWS |
| Vision model | Claude Haiku 4.5 on AWS Bedrock (`anthropic.claude-haiku-4-5`) |
| TIF→PNG conversion | `sips -s format png` (macOS built-in, in n8n Code Node) |
| Textract | ❌ Skipped — Bedrock vision only |
| Execution | **Pure n8n** workflow (self-hosted at `dev-n8n.visualgraphx.com`) |
| n8n MCP server | `github.com/makafeli/n8n-workflow-builder` |
| Input source | S3 Classification Samples path |
| Output | Single JSON/CSV results file per run |
| Scope | POC = classification + extraction per-page only (no grouping yet) |

---

## Page Taxonomy (6 classes — revised 2026-04-18)

Derived from viewing 20 evenly-spaced TIFs in Test Input ROLL 001 (April 17 probe), the Classification Samples folder, and 51 additional boundary-probe TIFs pulled on April 18 from first/last frames of Test Input ROLLS 001/012/076 plus production rolls across all 7 districts.

| Class | Description | Example Templates |
|---|---|---|
| `student_cover` | Primary cumulative/guidance record with name + demographics | Florida Cumulative Guidance Record 1-12, Osceola Progress Report |
| `student_test_sheet` | Standardized test forms — has student name | Stanford Achievement Test, H&R First Reader Test, SAT Profile Graph |
| `student_continuation` | Back pages, comments, family data — name at top | Comments page, MCH 304 health record, Elementary family data |
| `roll_separator` | START or END card — **two visually distinct styles both count as `roll_separator`**: **Style A (clapperboard)** = diagonal-hatched rectangles + "START"/"END" text + boxed handwritten ROLL NO. (districts 2, 4, 5, 6, 7); **Style B (certificate)** = printed "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" form with "START" or "END" header, typed school, handwritten date, filmer signature (districts 1, 3 primarily). Exactly 2 per roll (one START, one END). Can appear rotated 90° (observed in d7r099). | Style A: `samples/boundary_probe/png/t001_00005.png`, `t012_02163.png`. Style B: `samples/verify_probe/png/d1r001_01923.png`, `d3r030_00005.png` |
| `roll_leader` | Any non-student filler in the first or last ~2–10 frames of a roll — blank frames, vendor letterhead ("Total Information Management Systems" or "White's Microfilm Services"), microfilm resolution test target, district title page (Osceola County seal + "RECORDS DEPARTMENT"), microfilm-records certification card (filmer signature + reel number + date), operator-written roll-identity cards (e.g. "ROLL 1 / BEGIN Highlands Ave. Elem. / JANET") | see the `samples/boundary_probe/png/*_00001.png` set |
| `unknown` | Blank mid-roll page, illegible, or unrecognized | — |

**Dropped class:** `separator_index` — we hypothesized a multi-student index page listing ~420 students per roll, but none has been observed in any sample. The SOW's "Classification Samples = sample set of all possible separators" wording turned out to be inaccurate: those 13 TIFs are mostly content templates, not separator cards.

**Key finding (revised):** True per-student separator pages do not appear to exist. Boundaries between student packets must be inferred from name-change detection.

**Key finding:** Roll-level separators **do** exist and are deterministic — a "START — ROLL NO. N" clapperboard card at the top of each roll and a matching "END — ROLL NO. N" card at the bottom. Exactly 2 per roll. Visually unmistakable (two diagonal-hatched rectangles + large block text). Trivial to detect with the vision model and useful for auto-trimming the leader.

**Key finding:** Almost every real student page has a legible student name field at top. Combined with name-change detection, this is the primary grouping signal.

---

## Document Templates Observed (8 types)

1. Florida Cumulative Guidance Record — Grades 1-12 (most common)
2. School Record MCH 304 (health/immunization, state dept. of education)
3. Stanford Achievement Test — Form W Primary I Battery
4. Stanford Achievement Test — Individual Profile Graph (Grades 1-8)
5. H & R First Reader Achievement Test
6. Osceola County School District Progress Report — Grades 1-5
7. Elementary Record with Photograph + Family Data sections
8. Comments/Teacher Notes page (part of cumulative record)

---

## Ground Truth Available

- **Output PDFs** in `s3://servflow-image-one/.../Output/` — human-produced filenames encode student names:
  - `ACKLEY, CALVIN CHARLES.pdf`
  - `(LAST) (FIRST) Burris, Tammy L.pdf`
  - `) Boydston, Royer W.pdf` (malformed — also valid ground truth for edge cases)
- Can match TIF sequence numbers back to output PDF names for extraction eval

---

## Local Sample Files

```
/Users/tanishq/Documents/project-files/aws-s3/samples/
├── classification_samples/     ← 13 TIFs from S3 Classification Samples folder
├── test_input_roll001/         ← 20 evenly-spaced TIFs + PNGs from Test Input ROLL 001
│                                  (00001, 00097, 00193 ... 01825 — every ~96th file)
├── output_pdfs_district1_roll001/ ← 15 human-produced output PDFs (ground truth)
├── boundary_probe/             ← 51 TIFs (+ PNG thumbnails in png/) pulled 2026-04-18 morning
│                                  Covers first/last 3-5 frames of Test Input rolls 001/012/076
│                                  and first 3-5 frames of production rolls across all 7 districts.
│                                  Used to confirm roll-leader + START/END clapperboard structure.
└── verify_probe/               ← 174 TIFs (+ PNG thumbnails in png/ + pre-built classification
                                   grids grid_*.png) pulled 2026-04-18 afternoon. Covers first 6
                                   + last 3 frames of 15 production rolls (d1r001/005/010,
                                   d2r015/022, d3r030/038, d4r045/055, d5r065/070, d6r080/088,
                                   d7r095/099) + mid-roll dense samples (every ~200 frames) from
                                   d4r045, d5r065, d6r080. Evidence for: two separator-card
                                   styles, variable START/END positions, no mid-roll separators.
                                   `roll_sizes.json` maps each probe roll to its true frame count.
```

---

## Full Pipeline — How It Works End-to-End

```
S3 Input/DISTRICT-X/ROLL-XXX/
  00001.tif  ← Roll index page (lists all ~420 students for this roll)
  00002.tif  ┐
  00003.tif  ├── Student A packet (~4-6 pages)
  00006.tif  ┘
  00007.tif  ┐
  00010.tif  ├── Student B packet (~4-6 pages)
  ...        ┘

       ▼  Stage 1: Convert
    PNG bytes  (Pillow locally / Lambda in production)

       ▼  Stage 2: Classify  (Bedrock Claude Haiku 4.5)
    student_cover | student_test_sheet | student_continuation
    separator_index | unknown

       ▼  Stage 3: Extract  (Bedrock Claude Haiku 4.5)
    { last, first, middle, dob, school, confidence }

       ▼  Stage 4: Group
    name-change between consecutive pages → packet boundaries
    { "ACKLEY CALVIN CHARLES": ["00002", "00003", "00004"] }

       ▼  Stage 5: HITL  (n8n)
    confidence < threshold → human reviews flagged pages
    human corrects name / confirms grouping

       ▼  Stage 6: Output
    S3 Output/DISTRICT-X/ROLL-XXX/ACKLEY, CALVIN CHARLES.pdf
```

---

## Development Workflow — How We'll Build It

### Phase 1 — Python POC (prove AI accuracy first)

```
poc/
├── convert.py     ← TIF→PNG via Pillow
├── classify.py    ← Bedrock classify (5 classes)
├── extract.py     ← Bedrock extract (name/DOB/school)
├── group.py       ← name-change grouping logic
├── eval.py        ← compare results vs. ground truth PDFs
└── run_poc.py     ← orchestrates all stages on Test Input ROLL 001
```

**Iteration loop:**
1. Run on 20 sample pages → inspect wrong outputs → refine prompt → repeat
2. Once >85% accurate → run full ROLL 001 (1,924 pages) → eval against 419 ground truth PDFs
3. Document final prompts → hand off to Phase 2

**POC success criteria:** `results.json` with per-page classification + extraction + student groupings for Test Input ROLL 001. Name extraction accuracy >85% vs. Output ROLL 001 ground truth.

### Phase 2 — Production architecture for 218K TIFs (revised 2026-04-18)

**Recommended stack: Step Functions Distributed Map + Lambda + Bedrock Batch Inference + DynamoDB + S3.**

n8n remains useful for the HITL review UI and manual reruns, but is not the bulk-processing orchestrator at 218K scale — it becomes a bottleneck on a single self-hosted host. AWS-native orchestration scales to 1000+ concurrent executions natively.

```
S3 Input event (new roll uploaded)
  → EventBridge rule
  → Step Functions Distributed Map (1 execution per roll)
      → Inner Lambda per page:
          - Pillow TIF → PNG (in-memory)
          - Bedrock Converse API (or Bedrock Batch — see below)
          - Write result JSON to DynamoDB (pk=roll_id, sk=frame_number)
      → Aggregator Lambda (after all pages done):
          - Query DynamoDB for this roll
          - Find START/END indices from page_class=roll_separator marker=START|END
          - Walk [start+1, end-1], group consecutive pages by name-change
          - Flag any page with confidence < threshold → push to SQS HITL queue
          - Generate per-student PDF via pypdf from the roll's S3 TIFs
          - Upload to s3://.../Output/DISTRICT-X/ROLL-Y/Last, First M.pdf
  → HITL review app (separate; n8n or small web UI):
      - Consume SQS queue
      - Show operator the flagged frames + current extractions
      - Operator corrects name / confirms grouping → write to DynamoDB
      - Re-trigger aggregator for affected roll(s)
```

**Bedrock call strategy: Batch Inference for bulk pass, on-demand for HITL reruns.**
- Bedrock Batch = 50% discount vs on-demand, async (finishes in hours), fits an overnight bulk job
- On-demand Converse API for HITL-corrected single-page retries (low-volume, needs real-time)

**Cost estimate, 218K pages:**
- Bedrock Haiku 4.5 via Batch Inference: ~$225 (vs ~$450 on-demand)
- Lambda (218K invocations × ~2s avg): ~$50
- Step Functions: ~$20
- DynamoDB: ~$10
- S3 + data transfer: ~$30
- **Total: ~$335 + HITL operator time**

**Runtime estimate:**
- Bulk bedrock batch: hours (async)
- If on-demand instead: 500 concurrent Lambdas × ~2s per page × 218K = ~15 min compute; aggregation + PDF gen ~30 min; **~1 hr end-to-end**

**Why not only n8n + Lambda for bulk:**
- Self-hosted n8n host becomes bottleneck; no native distributed-map pattern
- Harder to recover partial runs; Step Functions gives idempotency + retry per map item
- n8n still valuable for the HITL operator UI — small workflow, easy to maintain there

**Pre-filter heuristics considered and rejected for POC:**
- Blank-frame skip via Pillow pixel std-dev would save ~2–5% of calls — not worth adding complexity since Bedrock Batch cost is already low
- Clapperboard shape detector would miss the Style B (certificate) separators entirely — cannot be used without a fallback LLM call anyway

**Fields written per page in DynamoDB:**
```json
{
  "roll_id": "DISTRICT-2/ROLL 015",
  "frame": "00004",
  "page_class": "roll_separator|roll_leader|student_cover|student_test_sheet|student_continuation|unknown",
  "separator": {"marker": "START|END|null", "roll_no": "15|null"},
  "student": {"last":"", "first":"", "middle":"", "dob":"", "school":""},
  "roll_meta": {"filmer":"", "date":"", "school":"", "reel_no_cert":""},
  "confidence": 0.0,
  "model_version": "claude-haiku-4-5",
  "processed_at": "2026-04-18T...Z"
}
```

---

## 3 Approach Options (Updated)

### Approach A — Python POC → n8n Production ⭐ Recommended

**Phase 1:** Local Python script — Pillow converts TIF→PNG, boto3 calls Bedrock, outputs `results.json/csv`. Run against Test Input ROLL 001.
**Phase 2:** n8n workflow + AWS Lambda for production-scale processing of all 218K TIFs with HITL.

- **Pros:** Fastest to prove AI accuracy (no infra setup), prompt iteration is cheap, clean handoff to n8n
- **Cons:** n8n not involved until Phase 2

### Approach B — n8n + Lambda from Day 1

Single n8n workflow: S3 → HTTP call to Lambda (TIF→PNG) → Bedrock classify node → Bedrock extract node → write CSV to S3.

- **Pros:** Full production architecture from day 1, HITL built in early
- **Cons:** Must deploy Lambda before running a single test; slows prompt iteration

### Approach C — Full End-to-End POC (Stages 1–4)

Python handles all 4 stages including grouping + PDF generation via `pypdf`. Output: named PDFs matching SOW format directly from Test Input.

- **Pros:** Delivers something tangible matching the SOW output; shows client a working PDF
- **Cons:** Broader scope; Test Output is empty so no automated eval — requires manual inspection

---

## Fields to Extract (per page, where present)

Per-page (on `student_*` classes):

- `last_name`
- `first_name`
- `middle_name`
- `date_of_birth`
- `school`
- `page_class` (taxonomy label above)
- `confidence` (model self-reported)

**SOW alignment note (2026-04-18):** The SOW only explicitly requires extraction of **"the student's name"** ("located on the top left of the form"). The additional fields (`date_of_birth`, `school`) are our choice to aid packet grouping and deduplication (e.g., distinguishing two "SMITH, JOHN" students); they are not contractually required. Worth confirming with the client before production.

Per-roll (from `roll_leader` frames, extracted once per roll):

- `reel_number_certification` (from the certification card — the archive's real reel ID)
- `filmer_name`
- `filming_date`
- `filming_vendor`
- `school_name_begin` (where an operator card is present)

---

## TIF Arrangement Within a Roll (revised 2026-04-18)

Each roll is a **linear sequential scan** of a physical microfilm reel. Corrected structure:

```
Frame 00001 ... 0000N     roll_leader — variable length (3–7 frames observed)
  00001                   blank / vendor letterhead / microfilm resolution target
  00002-0000(N-1)         operator roll-identity card, certification card, district title page
  0000N                   roll_separator (START clapperboard — "START — ROLL NO. <N>")

Frame 0000N+1 ... M-1     student packets, back-to-back, no per-student separators
  (cover + continuation + test_sheet, etc.; grouped by name-change detection)

Frame M                   roll_separator (END clapperboard — "END — ROLL NO. <N>")
Frame M+1 ... last        roll_leader — trailing blank / letterhead frames (1–3 observed)
```

**Empirical confirmation** (from `samples/boundary_probe/` + `samples/verify_probe/`, 174 additional TIFs across 15 prod rolls pulled 2026-04-18):
- Test ROLL 001 → START clapperboard at frame `00005`, END clapperboard at frame `01924`
- Test ROLL 012 → START clapperboard at frame `00004`, END clapperboard at frame `02163`
- Every one of 15 sampled prod rolls (across all 7 districts) has some form of START separator in frames 3–6
- END separator observed at `last`, `last-1`, `last-2`, or `last-3` depending on roll — not always final file
- Districts 1 + 3 use Style B (certificate), districts 2, 4, 5, 6, 7 use Style A (clapperboard) — mixed within dataset
- No mid-roll separator cards observed in 39 mid-roll samples (every ~200 frames across d4r045, d5r065, d6r080) — students remain back-to-back with no per-student marker
- At least one rotated separator card observed (d7r099 end-of-roll); pipeline must handle rotation

**What the discovery doc got wrong earlier** (corrected here):
- "00001.tif is a STUDENT RECORDS INDEX" — **wrong**. `00001` is blank / vendor letterhead / resolution calibration target. Student records start only after the START clapperboard.
- "20 evenly-spaced samples, zero separators" — frame `00001` of the sample set was actually a microfilm resolution test chart, not a student page; so the "zero separators" claim conflated absence of student-level separators with the presence of roll-level leader material.
- "Each roll resets to 00001.tif and counts up sequentially with student records" — half-right: frame numbering resets per roll, but the first several frames are leader material, not students.

**Grouping strategy:** Within the `[START+1, END-1]` window, detect name changes between consecutive pages. When page N has a different student name than page N-1, a new packet has started. Almost every real student page has a legible name field at top.

**Output PDF naming quality (from ground truth):**
- Clean: `ACKLEY, CALVIN CHARLES.pdf`
- Partial extractions: `(LAST) Buston Jerry.pdf`, `(FIRST) Combs, Gene.pdf`
- Total failures: `(LAST) (FIRST) (MIDDLE) Burris, Tammy L.pdf`
- Duplicates: `ALLEN, TAMMY.pdf` + `ALLEN, TAMMY_1.pdf`
- The `(LAST)`, `(FIRST)`, `(MIDDLE)` tokens are human-operator placeholders when OCR/AI failed

## Separator Card Styles (new — 2026-04-18 verification)

Two visually distinct separator-card designs appear across the dataset. Both must be recognized as `roll_separator`:

**Style A — Clapperboard card**
- Header: "THE SCHOOL DISTRICT OF OSCEOLA COUNTY, FLORIDA — RECORDS RETENTION DEPARTMENT"
- Body: two large diagonal-hatched rectangles (like a film-slate clapperboard), the word "START" or "END" in large block type, and a separate boxed section reading "ROLL NO." with the roll number handwritten
- Districts observed: 2, 4, 5, 6, 7
- Example: `samples/boundary_probe/png/t012_00004.png` (START), `t012_02163.png` (END)

**Style B — Certificate card**
- Header: "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" with large "START" or "END" heading
- Body: printed paragraph ("This is to certify... records of Osceola County School Board... filmed by..."), typed school name, handwritten date blank, filmer signature, reel number
- Districts observed: 1, 3 (primarily)
- Example: `samples/verify_probe/png/d1r001_01923.png` (END), `d3r030_00005.png` (START)

**Rotation caveat:** at least one separator card was scanned 90° rotated (`d7r099_02088`). Bedrock vision handles rotation natively; pipeline must not assume fixed orientation.

**Position variability:**
- START: frames 3, 4, 5, or 6 (per roll)
- END: `last`, `last-1`, `last-2`, or `last-3`
- Trailing leader (blank / letterhead) always present between END card and last file

**Implication:** cannot use a pure-pixel heuristic ("find hatched rectangle") as a pre-filter — would miss Style B. Use Bedrock vision for every frame, or run a two-model detector (heuristic + LLM fallback). For POC simplicity: Bedrock for every frame.

## Roll Provenance Metadata (new — 2026-04-18)

The `roll_leader` frames carry rich per-roll metadata worth extracting once per roll:

- **Filming vendor** — two observed: `Total Information Management Systems` (2090 Forsyth Rd, Orlando — most production rolls, filmed 1991–92) and `White's Microfilm Services` (1616 N. Orange Ave., Orlando — at least test ROLL 001). Leader layout varies by vendor.
- **Reel No.** (handwritten on clapperboard + typed on certification card) — **does NOT always equal the S3 folder number**. Example: S3 folder `OSCEOLA SCHOOL DISTRICT-7/ROLL 101/` has a certification card reading "Reel No. 756". Treat S3 folder number as a project-local index; the certification reel number is the original archive ID.
- **Filmer name** — e.g. "Linda Connors", handwritten "JANET"
- **Filming date** — e.g. 11/11/91, 1/29/92
- **Customer** — "School District of Osceola County, Florida"
- **School name** (test ROLL 001 only, from handwritten operator card) — e.g. "Highlands Ave. Elem." as the `BEGIN` marker. Not observed on production rolls so far.

---

## Open Questions

1. **Approach:** Which of A/B/C above? (Recommendation: A — Python POC first)
2. **Bedrock call strategy:** Single-pass (classify + extract in one prompt) vs. two-pass (classify first, then extract)
3. **POC target scope:** Test Input ROLL 001 only (1,924 TIFs) vs. all 3 test rolls (6,706 TIFs)
4. **TIF conversion in production n8n:** Lambda (recommended) vs. ImageMagick on n8n host vs. custom Docker image
5. **Separator prompt handling:** Include example image in prompt or describe in text only?
6. **[new 2026-04-18] SOW reconciliation with the client:**
   - Do they want DOB + school extracted, or only student name (strict SOW)?
   - Is our START/END separator card (Style A clapperboard OR Style B certificate) the "separator" they meant in the SOW? (The SOW's "Classification Samples = sample set of all possible separators" was inaccurate — those are content templates, not separators.)
   - Should the per-roll provenance metadata (filmer, date, certification reel number) be returned in the output?
7. **[new 2026-04-18] Should the pipeline record the reel-number mismatch** (S3 folder "ROLL 101" vs. certification "Reel 756") in a cross-reference manifest so downstream users can find files by either ID?
8. **[new 2026-04-18 verification] Production orchestration:** Step Functions Distributed Map (recommended) vs Batch on Fargate vs n8n. Current decision: SFN for bulk, n8n for HITL. Needs sign-off before Phase 2 build.
9. **[new 2026-04-18 verification] Bedrock access:** the current IAM user (`Servflow-image1`) lacks `bedrock:*` permissions — attempted `ListFoundationModels` returned AccessDenied. Need a Bedrock-enabled IAM role (or a new key) before any POC LLM work can start.
10. **[new 2026-04-18 verification] Bulk inference path:** Bedrock Batch Inference (~$225, async, 50% discount) vs on-demand (~$450, faster). Recommend Batch for bulk 218K run; on-demand for HITL retries.

---

## Infrastructure Notes

- AWS creds in `/Users/tanishq/Documents/project-files/aws-s3/.env`
- n8n API JWT token in `/Users/tanishq/Documents/project-files/aws-s3/.claude/settings.local.json`
- Project S3 helpers: `s3_operations.py` (list_buckets, list_objects, upload_file, download_file, read_object, delete_object)
- Python env: boto3 + python-dotenv (requirements.txt)
- n8n folder placeholder: `/Users/tanishq/Documents/project-files/aws-s3/n8n/`
