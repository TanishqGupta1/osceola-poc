# Per-Class Classification Heuristics

**Date:** 2026-04-23
**Scope:** Defines, per 7-class taxonomy, the decision rules the pipeline should apply. Each class entry covers: definition → positive signals → disambiguation vs neighbors → pre-LLM rule (if any) → post-LLM validator → failure modes observed in ROLL 001 run.

Purpose: replace implicit "let LLM figure it out" with explicit rules that (a) feed stricter prompt text, (b) run as deterministic pre/post filters, (c) resolve overlap between look-alike classes.

---

## Taxonomy reference

7 classes:
1. `student_cover`
2. `student_test_sheet`
3. `student_continuation`
4. `student_records_index`
5. `roll_separator`
6. `roll_leader`
7. `unknown`

Classes 1–4 are per-student content. Class 4 is tabular index of many students. Classes 5–6 are structural / non-student. Class 7 is fallback.

---

## 1. `student_cover`

**Definition.** Primary cumulative guidance record. One per student. Contains student's identifying info + school history summary.

**Positive signals (any):**
- Form header contains one of: `FLORIDA CUMULATIVE GUIDANCE RECORD`, `FLORIDA CUMULATIVE RECORD 1–12`, `OSCEOLA PROGRESS REPORT`, `ELEMENTARY RECORD`.
- Printed/typed student name at top-left AND demographics block (DOB, sex, race, place of birth, parent/guardian, address).
- Grid of school years + grade levels + schools attended.
- Pre-printed column headers: `LAST NAME`, `FIRST NAME`, `MIDDLE`, `DATE OF BIRTH`, `PLACE OF BIRTH`, `SEX`.

**Disambiguation:**
- vs `student_continuation`: cover has **demographics block AND school-history grid**. Continuation has name at top but no demographics.
- vs `student_test_sheet`: cover has school-history grid, not bubble-sheet / score grid.
- vs `student_records_index`: cover is one student. Index is ≥5 rows of students in a table.

**Pre-LLM rule.** None (layout too varied).

**Post-LLM validators:**
- If `page_class == student_cover` AND `student.last == "" AND student.first == ""` → downgrade to `unknown` (legit cover always has name extractable).
- If `student.dob` and `student.school` both empty → downgrade to `student_continuation` (cover should carry demographics).
- Name-format regex: `last` and `first` match `^[A-Za-z][A-Za-z'\-\. ]{0,38}[A-Za-z]$`. Fail → retry with stricter prompt.

**Failure modes observed (ROLL 001):**
- Over-classified: 586 covers vs ~347 real students. Haiku labels back/continuation pages as covers when any header text visible.
- Field inversion: Haiku sometimes puts first name in `last` and vice-versa (e.g. frame 39 `Calvin/Ackley` where true is `Ackley/Calvin`).

---

## 2. `student_test_sheet`

**Definition.** Standardized test form with student's name printed on it. Bubble-sheet style, score tables, grade-level rubric.

**Positive signals (any):**
- Form header: `STANFORD ACHIEVEMENT TEST`, `H&R FIRST READER`, `SAT PROFILE GRAPH`, `IOWA TESTS`, `CTBS`.
- Bubble grid for ABCD answers.
- Percentile / stanine / grade-equivalent score columns.
- Student name in a top name-box (often handwritten in bubbled letters).

**Disambiguation:**
- vs `student_cover`: test sheet lacks demographics block. Has bubble/score visuals instead of school-history grid.
- vs `student_continuation`: test sheet has scoring grid/bubbles. Continuation has comments, health records, family data.
- vs `student_records_index`: test sheet is one student's scores. Index is tabular list of many students.

**Pre-LLM rule.** None (would need OCR of form title; deferred).

**Post-LLM validators:**
- If `page_class == student_test_sheet` AND `student.last == ""` AND previous page in frame sequence had a student name, **inherit previous name** (test sheets frequently fail name OCR because bubbled letters are hard).
  - *This is a helpful policy for Phase 2; current Phase 1 just drops the page.*
- Same name-format regex as cover.

**Failure modes observed:**
- 42% of student pages extract empty names. Many are test sheets (bubble-letter names are hard for vision).
- 384 labeled `student_test_sheet`. Probably undercount — some bubble sheets get labeled `student_cover` when a form-title phrase is visible.

---

## 3. `student_continuation`

**Definition.** Back page, comments, family data, health records, or any additional student page that carries the student's name in the header but no primary demographics.

**Positive signals (any):**
- Form header: `COMMENTS`, `MCH 304 HEALTH RECORD`, `ELEMENTARY FAMILY DATA`, `ATTENDANCE HISTORY`, `STANDARDIZED TEST HISTORY`.
- Name at top as `Last, First` or `Last Name: X First Name: Y`.
- Absence of demographics block.
- Absence of bubble-sheet / score grid.

**Disambiguation:**
- vs `student_cover`: continuation has name only, no demographics.
- vs `student_test_sheet`: continuation has no bubble/score grid.
- vs `roll_leader`: continuation has a student name. Leader has no student-specific content.
- vs `unknown`: continuation has a legible header with text. Unknown is blank/illegible.

**Pre-LLM rule.** None.

**Post-LLM validators:**
- If `page_class == student_continuation` AND name empty → treat as name-carrying-forward-from-neighbor (Phase 2 policy), not garbage drop.
- If `student_cover` was seen in the same frame-neighborhood and this page lacks demographics → confirm `student_continuation`.

**Failure modes observed:**
- 843 pages classified — highest count. Likely correct: most pages after a cover ARE continuations.
- Many extract empty name → lost to name-change grouping.

---

## 4. `student_records_index`

**Definition.** Tabular page titled `STUDENT RECORDS INDEX` (or variant) listing 5–28 students per page in alphabetical blocks.

**Positive signals (all required for confidence):**
- Title text: `STUDENT RECORDS INDEX` or `STUDENT RECORDS LIST` or variant at top.
- Column headers: `LAST`, `FIRST`, `MIDDLE`, `DOB`, plus district variants (`FILE`, `FRAME`, `Roll`, `SEC`, `OTHER`, `TRANS`, `WITH`, `GRAD`, `DATE`, `BE`, `CR`, `ES`).
- ≥5 rows of data (not just header).
- Rows are alphabetically ordered by surname in a section.

**Disambiguation:**
- vs `student_cover`: index has many students per page; cover has one.
- vs `roll_leader`: index is tabular content. Leader is blank/letterhead/title/card.
- vs `unknown`: index has clear table structure. Unknown has no discernible structure.

**Pre-LLM rule (potential).** If pixel-heuristic detects repeating horizontal row grid AND ≥5 rows AND text at top matches `STUDENT RECORDS INDEX` → skip LLM classify, confirm class, run `tool_use` on `index_rows` only. Deferred to Phase 2.

**Post-LLM validators:**
- If `page_class == student_records_index` AND `len(index_rows) < 5` → downgrade to `student_cover` or `unknown` (too few rows to be a legit index page).
- For each row: both `last` and `first` must match name-format regex. Drop malformed rows.
- If two adjacent index frames contain identical rows → keep one, mark other as duplicate (happens on double-scan).

**Failure modes observed:**
- 20 frames detected on ROLL 001. Extrapolated truth: ~25 (from broad probe pattern).
- Miss mode: index page labeled as `student_cover` when row count is low or the title header is clipped.
- Extraction mode: 445 rows dedup'd across 20 frames = ~22 rows/frame. Matches expected 5–28 range.

---

## 5. `roll_separator`

**Definition.** START or END card that bookends each roll. Handwritten or printed ROLL NO. on card.

**Positive signals (all required — very restrictive):**
- One of two layouts:
  - **Style A (clapperboard):** two diagonal-hatched rectangles + large block "START" or "END" text + boxed handwritten `ROLL NO. N`. Districts 2, 4, 5, 6, 7.
  - **Style B (certificate):** printed `CERTIFICATE OF RECORD` / `CERTIFICATE OF AUTHENTICITY` form + START or END heading + typed school + handwritten date + filmer signature + reel number. Districts 1, 3.
- Card appears ONLY at frame positions 3–6 (START) or last-3 to last frame (END).

**Disambiguation:**
- vs `roll_leader`: leader is non-bookend filler (letterhead / blank / title card). Separator explicitly has START/END text.
- vs `student_*`: separator has no student-identifying info.

**Pre-LLM rule.** Frame-position prior: only check this class on frames in first 10 or last 5 of the roll. For mid-roll frames, reject separator class with high confidence.

**Post-LLM validators:**
- Per-roll sanity: exactly 1 `START` marker + 1 `END` marker expected per roll. More than 1 of either → keep the highest-confidence instance, downgrade rest to `roll_leader`.
- `separator.marker` must be exactly `"START"` or `"END"`. Other values → invalid.
- `separator.roll_no` should match the S3 folder's roll number (with caveat: folder number may differ from reel number on Style B cards — compare folder, log mismatch).

**Failure modes observed:**
- Over-classified: 13 in ROLL 001 vs expected 2. 11 mid-roll false positives.
- Main cause: LLM confuses mid-roll stamp-like or bold-header pages for separator cards.
- Fix: aggressive frame-position filter plus "duplicate START/END" downgrade.

---

## 6. `roll_leader`

**Definition.** Any non-student, non-separator filler: blank page, vendor letterhead, microfilm resolution test target, district title page, filmer certification card, operator roll-identity card.

**Positive signals (any):**
- Blank / near-blank page (pixel std-dev < 8).
- Vendor letterhead: `TOTAL INFORMATION MANAGEMENT SYSTEMS` or `WHITE'S MICROFILM SERVICES`.
- Microfilm resolution calibration chart (parallel line groups at decreasing pitches).
- District title page: Osceola County seal + `RECORDS DEPARTMENT`.
- Filmer certification card: fields like `Filmer`, `Date`, `Reel No.`, `School` but NO `START`/`END` header.
- Operator roll-identity card: small card with handwritten roll details.

**Disambiguation:**
- vs `roll_separator`: leader lacks `START`/`END` word. Certification card without START/END = leader.
- vs `student_*`: no student-identifying info.
- vs `unknown`: leader has recognizable filler content. Unknown is truly unreadable.

**Pre-LLM rules (Tier 0):**
- **H0.1 blank detector:** Pillow pixel std-dev < 8 → `roll_leader` (confidence high in first 7 / last 3 frames).
- **H0.2 resolution-target pHash:** perceptual hash against canonical calibration chart. Hamming ≤5 → `roll_leader`.
- **H0.3 vendor letterhead pHash:** hash against 2 known letterheads. Hamming ≤5 → `roll_leader`.

**Post-LLM validators:**
- If `roll_leader` AND frame is mid-roll AND page has extractable text → flag for HITL (most leaders are first/last frames only).
- `roll_meta` fields (filmer, date, school, reel_no_cert) populated ONLY from certification/operator cards — for blank/letterhead/target frames, leave empty.

**Failure modes observed:**
- 21 in ROLL 001. Reasonable (6 at START, 3 at END, handful mid-roll false positives).

---

## 7. `unknown`

**Definition.** Blank mid-roll, illegible, rotated beyond recovery, or unrecognized layout. Use when in doubt rather than guess wrong.

**Positive signals:**
- Illegible / badly scanned / over-exposed / under-exposed.
- Blank mid-roll (NOT first/last frames — those are `roll_leader`).
- Heavy skew or rotation model couldn't correct.
- Layout doesn't match any of 1–6 classes.

**Disambiguation:**
- vs `roll_leader`: leader is blank-at-start/end. Unknown is blank-mid-roll or illegible.
- vs any other class: if ≥70% confident it matches a specific class, use that. Only fall to unknown when confidence < 0.5.

**Pre-LLM rule.**
- Blank detector mid-roll (std-dev < 8 AND frame not in first 7 / last 3) → `unknown`.

**Post-LLM validators:**
- `student.*` and `roll_meta.*` must be empty for `unknown`. If any populated → re-classify.
- Three consecutive `unknown` frames mid-roll → flag roll for HITL review (structural anomaly).

**Failure modes observed:**
- 57 in ROLL 001. Some legit; some are real student pages with bad scans where LLM gave up.

---

## Decision flow (per frame)

```
                    ┌─────────────────┐
                    │  incoming frame │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ pixel std-dev<8 │
                    └────────┬────────┘
                   yes───────┤───────no
                    │                │
            ┌───────▼────┐           ▼
            │ is frame in│    ┌───────────────┐
            │  first 7 / │    │ pHash leader  │
            │ last 3     │    │  chart / vend │
            └───────┬────┘    └───────┬───────┘
           yes──────┤──────no         │
            │            │            │
    ┌───────▼──┐  ┌──────▼────┐  ┌────▼─────┐
    │roll_     │  │unknown    │  │hash match│
    │leader    │  │(blank     │  │        ? │
    │          │  │ mid-roll) │  └─┬────────┘
    └──────────┘  └───────────┘   yes     no
                                   │      │
                                   ▼      ▼
                         ┌─────────┐  ┌─────────────┐
                         │roll_    │  │  LLM classify│
                         │leader   │  │  (remaining  │
                         │         │  │   classes)   │
                         └─────────┘  └──────┬──────┘
                                             │
                                             ▼
                                ┌─────────────────────────┐
                                │  apply post-LLM         │
                                │  validators per class:  │
                                │  • name regex           │
                                │  • OCR garbage blocklist│
                                │  • empty-field downgrade│
                                │  • duplicate separator  │
                                │    downgrade            │
                                │  • row-count floor for  │
                                │    index pages          │
                                └──────────┬──────────────┘
                                           │
                                           ▼
                               ┌───────────────────────┐
                               │ frame-position prior  │
                               │ (separator only on    │
                               │  first 10 / last 5)   │
                               └──────────┬────────────┘
                                          │
                                          ▼
                                    ┌─────────┐
                                    │  final  │
                                    │  class  │
                                    └─────────┘
```

---

## Implementation priority

| Heuristic | Class | Phase 1 status | Phase 2 ROI |
|---|---|---|---|
| Pixel std-dev blank detector | leader / unknown | not shipped | 2-5% frames, $50 save |
| Resolution-target pHash | leader | not shipped | ~1/roll, tiny save |
| Vendor letterhead pHash | leader | not shipped | ~1-2/roll, tiny save |
| Frame-position prior for separators | separator | not shipped | **high** — drops mid-roll false positives |
| Name-format regex (H1.1) | student_* | not shipped | **high** — drops garbage extractions |
| OCR garbage token blocklist | student_* | not shipped | **high** — catches `BIRTH`/`COUNTY`/`SEX` tokens |
| Empty-field downgrade | cover → continuation | not shipped | medium — fixes over-classification |
| Duplicate START/END collapse | separator | not shipped | medium |
| Row-count floor for index | index | not shipped | low — model already accurate at class but not at row count |
| Three-consecutive-unknown flag | unknown | not shipped | low — HITL signal only |
| Index-snap (H2.7) | student_* | **SHIPPED** | primary lever, 3.2× lift already measured |
| Index-entry clustering | all student classes | **SHIPPED** | primary grouping mode |
| GT-cleaner drop reasons | eval-only | **SHIPPED** | already in pipeline |

---

## Next steps for building these

1. **Pre-LLM tier** — add `poc/pre_filter.py` with blank detector + pHash stubs. Each takes `PIL.Image` → `Optional[PageClass]` (None = pass through to LLM).
2. **Post-LLM validator tier** — add `poc/validators.py` with per-class check functions. Run after `classify_extract.py` before `build_roll_index`. Each returns possibly-updated `PageResult`.
3. **Frame-position prior** — inject into `poc/prompts.py` dynamically: when caller knows the frame number, add "This is frame N of M total in this roll" to user text. Stronger than any post-filter.
4. **Duplicate separator collapse** — run after full classify pass, before grouping. Per roll: keep top-1 START and top-1 END by confidence, downgrade rest.

All four land as Phase 1.5 / Phase 2 work. Not in this session's branch.
