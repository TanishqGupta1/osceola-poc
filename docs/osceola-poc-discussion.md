# Osceola County School District — POC Discussion Notes
Originated: 2026-04-17
Updated: 2026-04-18 (revised roll structure + taxonomy after boundary-sample probe)
Updated: 2026-04-18 later (verification probe — 174 samples across 15 prod rolls + 3 dense mid-roll; two separator-card styles discovered; refined 218K-scale prod architecture)
Updated: 2026-04-20 (full S3 inventory + bucket-config probe + ground-truth quality audit + model bake-off expansion)

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

**Estimated students:** 218,577 TIFs ÷ ~5.1 pages/student avg ≈ **~43,000 students** (revised 2026-04-20 from D1 PDF/TIF size ratio; earlier 48,600 figure was based on 4.5 pages/student).

**Roll size range:** 127 (ROLL 065B) to 2,665 (ROLL 034). Most rolls: 1,900–2,650 TIFs.

**Notable gaps/partials (verified 2026-04-20 full scan):** ROLL 048 missing, ROLL 100 missing, ROLL 059=414, ROLL 065B=127, ROLL 101=320, ROLL 075A=2,557. Split-roll naming convention (`NNNB`, `NNNA`) must be handled by regex — `\d{3}` alone is not sufficient.

**Verified district counts (2026-04-20):** D1=22,179 (11 rolls), D2=39,289 (16), D3=29,700 (13), D4=46,312 (22), D5=28,672 (13), D6=34,476 (15), D7=17,949 (10). Total 218,577 ✓ matches SOW. Earlier CLAUDE.md counts were off by ~20 TIFs per district (stale estimates).

**Total corpus size** ≈ 24 GB (median TIF 104 KB, mean 112 KB). Fits on a single EBS volume; not a big-data problem.

**Test Input is not a held-out test set.** ETag comparison confirms `Test Input/ROLL 001|012|076/` are byte-identical copies of `Input/` equivalents. `Test Output/` is empty. We must curate our own eval holdout.

---

## Tech Stack Decisions

| Decision | Choice |
|---|---|
| Cloud | AWS |
| Vision model | **TBD — bake-off pending** (see "Model bake-off" section). Previously locked to Claude Haiku 4.5; revised 2026-04-20 to include Amazon Nova Lite (~15× cheaper) + Nova Pro candidates. |
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

## Ground Truth Available (audit 2026-04-20)

Output PDFs exist only for District 1, and even there coverage is partial:

| Roll | N PDFs | UPPER clean | TitleCase | Placeholder (`(LAST)/(FIRST)/(MIDDLE)`) | `_N` dup | Other garbage |
|---|---|---|---|---|---|---|
| ROLL 001 | 419 | 118 | 117 | 45 (11%) | 10 | 129 |
| ROLL 002 | 297 | 132 | 92 | 12 (4%) | 6 | 55 |
| ROLL 007 | 488 | 103 | 164 | 76 (16%) | 11 | 134 |
| ROLL 008 | 467 | 69 | 197 | 54 (12%) | 17 | 130 |
| ROLL 009 | 483 | 61 | 193 | **90 (19%)** | 15 | 124 |
| ROLL 010 | 500 | 47 | 238 | 80 (16%) | 16 | 119 |
| ROLL 011 | 474 | 134 | 166 | 56 (12%) | 9 | 109 |
| **real GT total** | **3,128** | | | **~14%** | **~3%** | **~25%** |
| ROLL 003 | 1 (sham — 48 MB batch merge, exclude) | | | | | |
| ROLL 005 | 2 (sham, exclude) | | | | | |
| ROLL 006 | 1 (sham — 543 MB batch merge, exclude) | | | | | |

**Districts 2–7: zero ground truth.** Processing dates 2026-03-05 to 2026-03-11 — operators may still be labeling D1 when POC runs against D2–7.

Filename examples of the garbage/placeholder class (real observations):

- `(LAST) (FIRST) MIDDLE) COUNTY. PLACE OF BIRTHth amb SEX E (CITY) Barton, Virginia Ley (COUNTY).pdf`
- `611 Eblin Carl Byren (FIRST) (MIDDLE).pdf` (`611` is a page number, not a name)
- `AN (LAST) (FIRST) (MIDDLE) Carry Shirley.pdf`
- `Croft, Alice Alice Bett,.pdf`
- `1959.pdf`
- `Birtha.pdf`
- `Clemons, Kathryn, Couretta (FIRST (MIDDLE).pdf`

**Duplicates:** 3,131 unique filenames across 3,132 PDFs → `_N` suffix is a legitimate same-name marker, not a bug.

**Eval implication:** any accuracy measurement against raw GT filenames systematically underestimates AI because ~15% of the GT itself is unreliable. POC **must include a GT-cleaning + filtering pass** before comparing predictions: strip `(LAST)/(FIRST)/(MIDDLE)` tokens, drop rows with embedded OCR artifacts (`BIRTH`, `COUNTY`, `SEX`, `PLACE OF BIRTH`, numeric-only names, lone `AN`/`611`-style prefixes), case-normalize, exclude ROLL 003/005/006.

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

## Model bake-off (new — 2026-04-20)

Primary vision model is no longer locked to Haiku 4.5. Decision rule (accuracy first, cost as tiebreaker):

1. Hard gate: primary must hit **≥90% partial name match** on curated operator-labeled fixtures across all 7 districts.
2. Among passers, pick cheapest.
3. If no model passes, default to Haiku 4.5 + aggressive layering.

Bake-off metric: per-class classification accuracy + per-page name Levenshtein distance vs cleaned ground truth.

### Bedrock access (verified 2026-04-20)

AWS account `690816807846` user `tanishq` has full Bedrock access in `us-west-2`. 125 models available. All vision candidates ACTIVE: `anthropic.claude-haiku-4-5-20251001-v1:0`, `anthropic.claude-sonnet-4-6`, `amazon.nova-lite-v1:0`, `amazon.nova-pro-v1:0`, `mistral.pixtral-large-2502-v1:0`. Amazon Nova Premier and Meta Llama 3.2 90B are LEGACY (still callable but deprecating).

57 cross-region inference profiles available (`us.anthropic.*`, `us.amazon.*`, etc.). Use the `us.*` inference-profile IDs, not raw model IDs — raw model IDs fail `converse` with "on-demand not supported" errors for the newest models.

The new account has **no S3 access** to `servflow-image-one` (403 Forbidden on `HeadBucket`). So the POC must load two env files: `.env` (Servflow-image1, S3) + `.env.bedrock` (tanishq, Bedrock).

### Quick-check bake-off (2026-04-20 — 4 models × 5 samples)

Ran `bedrock-runtime.converse` on 5 diverse fixtures (roll_leader, Style A separator, Style B separator, 2 student pages) with a minimal classify+extract prompt. Directional only — **5 samples is too few to bless a primary** but reveals clear signals.

**Per-sample class accuracy:**

| Sample | Haiku 4.5 | Sonnet 4.6 | Nova Lite | Nova Pro |
|---|---|---|---|---|
| Resolution target → roll_leader | ✓ | ✓ | ✓ | ✓ |
| Style A clapperboard → roll_separator | ✓ | ✓ | ✓ | ✓ |
| Style B certificate → roll_separator | ✗ leader | ✗ leader | ✗ leader | ✗ leader |
| Student 00097 → student_* | ✓ cont | ✓ cont | ✓ cont | ✗ cover |
| Student 00865 → student_* | ✓ cont | ✓ cont | ✓ cont | ✗ cover |

**Name extraction on student 00865** (name visible top-left: Curtis Norman Cecil):
- Haiku 4.5, Sonnet 4.6, Nova Pro: last=Curtis, first=Norman, middle=Cecil ✓
- Nova Lite: last=**Norman**, first=**Curtis**, middle=Cecil — **swaps last/first**

**Cost + latency extrapolated to 218K pages (avg tokens observed):**

| Model | avg_in_tok | avg_out_tok | avg_ms | $/218K on-demand |
|---|---|---|---|---|
| Nova Lite | 2,230 | 50 | 1,681 | **~$32** |
| Nova Pro | 2,230 | 46 | 1,532 | ~$422 |
| Haiku 4.5 | 1,702 | 109 | 2,918 | ~$491 (~$245 batch) |
| Sonnet 4.6 | 1,703 | 67 | 3,851 | ~$1,338 |

Token-economics surprise: Amazon Nova tokenizes images ~30% higher than Claude per page, shrinking Nova Pro's headline price advantage to parity with Haiku 4.5. Earlier naive pricing table over-estimated Nova Pro savings.

**Findings:**

1. **Our `samples/fixtures_public/separator_styleB_certificate_START.png` is mis-labeled.** All 4 models identify it as vendor letterhead / `roll_leader` with notes "Total Information Management Systems Orlando." Real Style B samples in `verify_probe/png/d1r001_01923.png` must be used instead.
2. **Nova Lite swaps last/first on student names.** High SOW-compliance risk since name is the only contractually-required field.
3. **Nova Pro confuses cover vs continuation** and shows no cost advantage over Haiku 4.5 at observed token counts.
4. **Nova Lite mis-calibrated confidence** — reports `0.1` on 3/5 correctly-classified pages. Would trigger unnecessary HITL routing.
5. **Haiku 4.5 output wraps JSON in `\`\`\`json` fences** — needs stripping. Sonnet 4.6 returns clean JSON.

**Provisional recommendation** (subject to ≥50-sample confirmation):
- **Primary:** Claude Haiku 4.5 (us.anthropic.claude-haiku-4-5-20251001-v1:0), Batch Inference for bulk. Use `tool_use` to avoid JSON-fence wrapping.
- **Retry tier:** Claude Sonnet 4.6 on mid-confidence (0.6–0.85) + primary/retry disagreement.
- **Drop** Nova Lite + Nova Pro + Pixtral + Llama 3.2 from consideration.

Before locking, re-run bake-off on ≥50 operator-labeled fixtures with a corrected Style B sample.

## Architecture redesign gaps — observed 2026-04-20

Current design (see `docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md`) has these weaknesses relative to scale + SOW + ground-truth audit:

1. **Single-model pipeline, no retry tier** — current POC spec drops Sonnet fallback for simplicity. At 218K scale that is the wrong call; retry tier costs little and materially lifts accuracy.
2. **Self-reported confidence only** — no cross-validation, no deterministic check, no packet-level name reconciliation. Majority-vote across a packet's ~5 pages is a free accuracy lever.
3. **Ground-truth eval assumes clean filenames** — spec's `parse_pdf_filename` drops placeholders but does not handle embedded OCR garbage. Under-rates AI against noisy GT.
4. **POC evaluates ROLL 001 only** — cannot detect district-specific prompt failures (e.g., Style B certificate separator mis-classification in D1+D3).
5. **Roll-ID regex** (`\d{3}`) will miss `ROLL 065B`, `ROLL 075A`. Minor but real.
6. **No deterministic pre-classifier** — template-hash / pHash against exemplar library of the ~8 known form types could skip LLM on 60–80% of frames. Significant cost + speed lever left on table.
7. **Missing/split rolls not encoded** — no roll manifest that tracks gaps (048, 100) or split rolls (065B, 075A) for downstream accounting.
8. **No idempotency key** — reruns duplicate work in DynamoDB / Bedrock calls.
9. **No DLQ / poison-message handling** — any single-page failure can stall a roll aggregator in the current Phase 2 sketch.
10. **Bedrock throughput quota not measured** — `us-west-2` Haiku 4.5 on-demand quota unknown. Bulk 218K run could hit throttles.
11. **Reel-number cross-reference manifest missing** — S3 roll numbers and physical certification reel numbers diverge (e.g. S3 ROLL 101 = Reel 756). Downstream users need a lookup table.

These drive the v2 architecture redesign underway (spec: `docs/superpowers/specs/2026-04-20-osceola-arch-redesign.md` — in draft).

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
11. **[new 2026-04-20] Model bake-off:** test Amazon Nova Lite + Nova Pro + Claude Haiku 4.5 on operator-labeled fixture set before locking primary. Accept the cheapest model meeting a defined accuracy threshold.
12. **[new 2026-04-20] Eval set curation:** since Districts 2–7 have zero ground truth and Test Input is a byte-identical copy of Input, we need an operator to hand-label ~100–200 pages across all 7 districts to get a real multi-district accuracy signal.
13. **[new 2026-04-20] GT cleaning:** confirm with the client that it is acceptable to drop rows with embedded OCR garbage (`BIRTH`, `COUNTY`, numeric-only names, etc.) from the eval comparison baseline — otherwise AI accuracy will be systematically under-reported against noisy GT.

---

## Infrastructure Notes

- AWS creds in `/Users/tanishq/Documents/project-files/aws-s3/.env`
- n8n API JWT token in `/Users/tanishq/Documents/project-files/aws-s3/.claude/settings.local.json`
- Project S3 helpers: `s3_operations.py` (list_buckets, list_objects, upload_file, download_file, read_object, delete_object)
- Python env: boto3 + python-dotenv (requirements.txt)
- n8n folder placeholder: `/Users/tanishq/Documents/project-files/aws-s3/n8n/`
