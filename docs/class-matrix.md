# Class Matrix — Osceola Microfilm Image Types

**Date:** 2026-04-23
**Purpose:** Enumerate every distinguishable image *subtype* seen in the 218,577-TIF corpus, with the specific visual / textual / layout features that identify each. Drives:
- Tighter LLM prompt text (inject subtype description when relevant)
- Rule-based pre/post-LLM validators
- pHash template library for Tier-0 deterministic skip
- HITL operator training material

Parent classes are the 7 from the taxonomy. Subtypes are concrete layouts observed.

Machine-readable version: **`docs/class-matrix.json`** (same content, structured for code consumption).

---

## Parent class → subtype quick index

| Parent | Subtype ID | One-liner |
|---|---|---|
| `student_cover` | `cover_cum_guidance_1_12` | Florida Cumulative Guidance Record grades 1–12 |
| `student_cover` | `cover_cum_guidance_k_6` | Florida Cumulative Record K–6 (elementary variant) |
| `student_cover` | `cover_osceola_progress` | Osceola Progress Report cover |
| `student_cover` | `cover_high_school_transcript` | HS transcript-style cover w/ credits + GPA |
| `student_test_sheet` | `test_stanford_achievement` | Stanford Achievement Test bubble sheet |
| `student_test_sheet` | `test_hr_first_reader` | H&R First Reader form |
| `student_test_sheet` | `test_sat_profile_graph` | SAT Profile Graph |
| `student_test_sheet` | `test_iowa` | Iowa Tests of Basic Skills |
| `student_test_sheet` | `test_ctbs` | CTBS / California Test of Basic Skills |
| `student_test_sheet` | `test_generic_bubble` | Unknown-brand bubble sheet with name box |
| `student_continuation` | `cont_comments` | Comments / teacher-notes page |
| `student_continuation` | `cont_mch_304_health` | MCH 304 health record |
| `student_continuation` | `cont_family_data` | Elementary Family Data page |
| `student_continuation` | `cont_attendance_history` | Attendance / days-present tabulation |
| `student_continuation` | `cont_test_history_summary` | Aggregated test score history page |
| `student_continuation` | `cont_back_of_cover` | Reverse side of cover with continued demographics |
| `student_records_index` | `index_standard` | Standard `STUDENT RECORDS INDEX` layout (LAST/FIRST/MIDDLE/DOB) |
| `student_records_index` | `index_district_variant` | District-specific column variant (added FILE/FRAME/Roll/SEC/OTHER/TRANS/WITH/GRAD/DATE/BE/CR/ES) |
| `roll_separator` | `separator_style_a_start` | Clapperboard START card (districts 2/4/5/6/7) |
| `roll_separator` | `separator_style_a_end` | Clapperboard END card (districts 2/4/5/6/7) |
| `roll_separator` | `separator_style_b_start` | Certificate of Record START card (districts 1/3) |
| `roll_separator` | `separator_style_b_end` | Certificate of Authenticity END card (districts 1/3) |
| `roll_leader` | `leader_blank` | Blank or near-blank filler frame |
| `roll_leader` | `leader_letterhead_tims` | Total Information Management Systems letterhead |
| `roll_leader` | `leader_letterhead_whites` | White's Microfilm Services letterhead |
| `roll_leader` | `leader_calibration_target` | Microfilm resolution test chart |
| `roll_leader` | `leader_district_title` | Osceola County seal + RECORDS DEPARTMENT title page |
| `roll_leader` | `leader_filmer_cert` | Filmer certification card (NO START/END marker) |
| `roll_leader` | `leader_operator_card` | Small operator roll-identity card |
| `unknown` | `unknown_blank_midroll` | Blank page mid-roll (not start/end region) |
| `unknown` | `unknown_illegible` | Too damaged/faded/skewed to read |
| `unknown` | `unknown_unrecognized` | Legible but doesn't match any other subtype |

**Total subtypes: 32.**

---

## Feature ontology used by every subtype

Each subtype entry below carries these dimensions:

| Dimension | What it captures |
|---|---|
| **title_text** | Exact printed headline phrase, case-insensitive. Strongest single signal. |
| **column_headers** | Pre-printed column/row labels on the form. |
| **key_phrases** | Distinctive mid-page text that disambiguates from siblings. |
| **visual_shapes** | Diagonal hatches, boxes, grids, bubbles, seals, rules. |
| **layout_features** | Orientation, table density, field density, blank-area ratio. |
| **name_location** | Where the student name (if any) appears — top-left, top-center, name-box, grid cell, none. |
| **frame_position_hint** | first-3 / first-7 / last-3 / mid-roll / any. |
| **district_bias** | Which of 1–7 it appears in (or `all`). |
| **vendor_bias** | TIMS (Total Information Management Systems), WMS (White's Microfilm Services), or either. |
| **page_count_per_instance** | How many frames a single real-world item produces. |
| **exclusion_rule** | Fastest rule to REJECT this subtype (used in decision flow). |
| **phash_template** | Whether a reference image is worth hashing (Tier 0). |
| **extraction_target** | What fields the pipeline should pull from this subtype. |

---

## 1. `student_cover` subtypes

### 1.1 `cover_cum_guidance_1_12`

| Dimension | Value |
|---|---|
| title_text | `FLORIDA CUMULATIVE GUIDANCE RECORD` (sometimes with `GRADES 1-12`) |
| column_headers | `LAST NAME`, `FIRST NAME`, `MIDDLE NAME`, `DATE OF BIRTH`, `PLACE OF BIRTH`, `SEX`, `RACE` |
| key_phrases | `GUIDANCE RECORD`, `CUMULATIVE`, parent/guardian block, address block |
| visual_shapes | Dense tabular grid of school-year rows × columns (school, grade, days present/absent) |
| layout_features | Full-page portrait. Header band + demographics band + grades grid |
| name_location | Top-left of demographics band |
| frame_position_hint | mid-roll (anywhere in `[START+1, END-1]`) |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 (single cover page per student) |
| exclusion_rule | No grades grid OR no demographics block → reject |
| phash_template | Yes (for pre-printed form layout) |
| extraction_target | `student.last, first, middle, dob, school` |

### 1.2 `cover_cum_guidance_k_6`

| Dimension | Value |
|---|---|
| title_text | `FLORIDA CUMULATIVE RECORD K-6` or `ELEMENTARY RECORD` |
| column_headers | Similar to 1.1 plus `HEALTH`, `TEACHER`, `KINDERGARTEN READINESS` |
| key_phrases | `ELEMENTARY`, `K-6`, `KINDERGARTEN` |
| visual_shapes | Grid with fewer school-year rows (~7 max) |
| layout_features | Portrait. Often colored background on real print, shows as shaded band on microfilm. |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all; more common for younger student records |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Has `GRADES 1-12` text → it's 1.1 not K-6 |
| phash_template | Yes |
| extraction_target | `student.last, first, middle, dob, school` |

### 1.3 `cover_osceola_progress`

| Dimension | Value |
|---|---|
| title_text | `OSCEOLA PROGRESS REPORT` or `OSCEOLA COUNTY PROGRESS` |
| column_headers | `STUDENT`, `GRADE`, `TEACHER`, `SCHOOL YEAR` |
| key_phrases | `PROGRESS REPORT`, `NINE-WEEKS` grading periods |
| visual_shapes | Smaller grid for nine-weeks marks; less dense than cum record |
| layout_features | Portrait. Less demographic content than 1.1/1.2 |
| name_location | Top-center name-box |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Has `CUMULATIVE` or `GUIDANCE` text → it's 1.1/1.2 |
| phash_template | Yes |
| extraction_target | `student.last, first, middle` |

### 1.4 `cover_high_school_transcript`

| Dimension | Value |
|---|---|
| title_text | `TRANSCRIPT` or `HIGH SCHOOL TRANSCRIPT` |
| column_headers | `COURSE`, `CREDITS`, `GRADE`, `GPA` |
| key_phrases | `GRADUATED`, `DIPLOMA`, course codes like `ENG1001` |
| visual_shapes | Tall course list; GPA summary box |
| layout_features | Portrait |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all (HS records only) |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No course list → not a transcript |
| phash_template | Optional |
| extraction_target | `student.last, first, middle, school` |

---

## 2. `student_test_sheet` subtypes

### 2.1 `test_stanford_achievement`

| Dimension | Value |
|---|---|
| title_text | `STANFORD ACHIEVEMENT TEST` |
| column_headers | Subtest labels (`READING`, `MATH`, `LANGUAGE`, `SPELLING`), `RAW`, `PERCENTILE`, `STANINE` |
| key_phrases | `STANFORD`, `Harcourt`, subtest names |
| visual_shapes | Bubble answer grid (ABCD rows) OR score summary table |
| layout_features | Landscape common. Bubbled name field at top |
| name_location | Bubbled name field top-left; handwritten cursive underneath |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1–2 (bubble sheet + score summary often filmed as 2 pages) |
| exclusion_rule | No bubble grid AND no percentile/stanine table → not this |
| phash_template | Yes (form template) |
| extraction_target | `student.last, first, middle` (often noisy due to bubble letters) |

### 2.2 `test_hr_first_reader`

| Dimension | Value |
|---|---|
| title_text | `H&R FIRST READER` or `HARCOURT FIRST READER` |
| column_headers | Item numbers, subscore labels |
| key_phrases | `FIRST READER`, `Harcourt Brace` |
| visual_shapes | Simpler form, fewer bubbles |
| layout_features | Portrait |
| name_location | Top-center name-box |
| frame_position_hint | mid-roll |
| district_bias | all (elementary) |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Mentions `STANFORD` → 2.1 not 2.2 |
| phash_template | Yes |
| extraction_target | `student.last, first, middle` |

### 2.3 `test_sat_profile_graph`

| Dimension | Value |
|---|---|
| title_text | `SAT PROFILE GRAPH` or `SAT SCORE PROFILE` |
| column_headers | `VERBAL`, `MATH`, percentile scale |
| key_phrases | `SAT`, `College Board`, `PROFILE` |
| visual_shapes | Horizontal bar graph of scores |
| layout_features | Landscape common |
| name_location | Top-left |
| frame_position_hint | mid-roll (HS records) |
| district_bias | all (HS) |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No bar-graph visualization → not 2.3 |
| phash_template | Optional |
| extraction_target | `student.last, first, middle` |

### 2.4 `test_iowa`

| Dimension | Value |
|---|---|
| title_text | `IOWA TESTS OF BASIC SKILLS` |
| column_headers | ITBS subtest labels |
| key_phrases | `IOWA`, `ITBS` |
| visual_shapes | Dense table of subtest scores |
| layout_features | Portrait/landscape mix |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No `IOWA`/`ITBS` text and no standard ITBS subtests → not 2.4 |
| phash_template | Optional |
| extraction_target | `student.last, first, middle` |

### 2.5 `test_ctbs`

| Dimension | Value |
|---|---|
| title_text | `CTBS` or `CALIFORNIA TEST OF BASIC SKILLS` |
| column_headers | CTBS subtests |
| key_phrases | `CTBS`, `McGraw-Hill` |
| visual_shapes | Score summary table; sometimes bubble pages |
| layout_features | Portrait |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Stanford/Iowa/HR markers present → not 2.5 |
| phash_template | Optional |
| extraction_target | `student.last, first, middle` |

### 2.6 `test_generic_bubble`

| Dimension | Value |
|---|---|
| title_text | Any test-sheet heading that doesn't match 2.1–2.5 |
| column_headers | Unknown |
| key_phrases | generic: `TEST`, `SCORE`, `GRADE LEVEL` |
| visual_shapes | Bubble grid |
| layout_features | Various |
| name_location | Top-left or top-center |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No bubble grid AND no score table → not a test sheet |
| phash_template | No |
| extraction_target | `student.last, first, middle` |

---

## 3. `student_continuation` subtypes

### 3.1 `cont_comments`

| Dimension | Value |
|---|---|
| title_text | `COMMENTS` or `TEACHER COMMENTS` |
| column_headers | `DATE`, `TEACHER`, `COMMENT` |
| key_phrases | Narrative sentences about student behavior / progress |
| visual_shapes | Ruled lines for handwritten notes |
| layout_features | Mostly handwritten fill |
| name_location | Top-left header |
| frame_position_hint | mid-roll, follows a cover |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1–3 (many students have multi-year comments) |
| exclusion_rule | Has demographics block → it's cover not comments |
| phash_template | No (content varies) |
| extraction_target | `student.last, first, middle` |

### 3.2 `cont_mch_304_health`

| Dimension | Value |
|---|---|
| title_text | `MCH 304` or `HEALTH RECORD` or `MATERNAL AND CHILD HEALTH 304` |
| column_headers | `IMMUNIZATION`, `DPT`, `OPV`, `MMR`, dates |
| key_phrases | `IMMUNIZATION`, vaccine names |
| visual_shapes | Vaccination table with date columns |
| layout_features | Portrait. Dense small-font table |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No vaccine columns → not 3.2 |
| phash_template | Yes |
| extraction_target | `student.last, first, middle, dob` |

### 3.3 `cont_family_data`

| Dimension | Value |
|---|---|
| title_text | `ELEMENTARY FAMILY DATA` or `FAMILY INFORMATION` |
| column_headers | `FATHER`, `MOTHER`, `GUARDIAN`, `SIBLINGS` |
| key_phrases | `FAMILY`, `GUARDIAN`, `OCCUPATION` |
| visual_shapes | Multiple fill-in-the-blank lines |
| layout_features | Portrait |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No family-relative field labels → not 3.3 |
| phash_template | Yes |
| extraction_target | `student.last, first, middle` |

### 3.4 `cont_attendance_history`

| Dimension | Value |
|---|---|
| title_text | `ATTENDANCE` or `ATTENDANCE HISTORY` |
| column_headers | `YEAR`, `DAYS PRESENT`, `DAYS ABSENT`, `TARDY` |
| key_phrases | `DAYS PRESENT`, `TARDY` |
| visual_shapes | Tabular year-by-year totals |
| layout_features | Portrait |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No attendance-specific columns → not 3.4 |
| phash_template | Optional |
| extraction_target | `student.last, first, middle` |

### 3.5 `cont_test_history_summary`

| Dimension | Value |
|---|---|
| title_text | `TEST HISTORY` or `STANDARDIZED TEST SUMMARY` |
| column_headers | `YEAR`, test name, scores |
| key_phrases | `TEST`, score year labels |
| visual_shapes | Multi-year test score table |
| layout_features | Portrait |
| name_location | Top-left |
| frame_position_hint | mid-roll |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Is a bubble sheet → it's test_sheet not continuation |
| phash_template | No |
| extraction_target | `student.last, first, middle` |

### 3.6 `cont_back_of_cover`

| Dimension | Value |
|---|---|
| title_text | Often none — same header printed as cover |
| column_headers | Reverse side of cover form |
| key_phrases | Blank continuation of cover grid or extra demographics |
| visual_shapes | Similar to cover but fewer filled cells |
| layout_features | Portrait |
| name_location | Sometimes reprinted, sometimes absent |
| frame_position_hint | mid-roll, immediately after cover frame |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Has demographics block with name → it's cover not back |
| phash_template | No (very form-specific) |
| extraction_target | `student.last, first, middle` when present |

---

## 4. `student_records_index` subtypes

### 4.1 `index_standard`

| Dimension | Value |
|---|---|
| title_text | `STUDENT RECORDS INDEX` |
| column_headers | `LAST`, `FIRST`, `MIDDLE`, `DOB` |
| key_phrases | Alphabetical section markers (`A`, `B`, `C`...) |
| visual_shapes | Dense tabular rows, 5–28 per page |
| layout_features | Portrait |
| name_location | Not applicable (many students per page) |
| frame_position_hint | Cluster in frames 7–40 and occasionally near END |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | Multiple index pages per roll (one per alphabetical section) |
| exclusion_rule | Fewer than 5 row candidates → not 4.1 |
| phash_template | Partial (table frame + header stays constant) |
| extraction_target | `index_rows[]` with `{last, first, middle, dob}` per row |

### 4.2 `index_district_variant`

| Dimension | Value |
|---|---|
| title_text | `STUDENT RECORDS INDEX` plus one of `FILE`, `FRAME`, `Roll`, `SEC`, `OTHER`, `TRANS`, `WITH`, `GRAD`, `DATE`, `BE`, `CR`, `ES` in headers |
| column_headers | Standard 4 + district-specific additions |
| key_phrases | Added column labels above |
| visual_shapes | Same as 4.1 but wider/denser table |
| layout_features | Portrait, landscape in a few districts |
| name_location | Not applicable |
| frame_position_hint | Same as 4.1 |
| district_bias | District-specific (exact mapping TBD per sample) |
| vendor_bias | either |
| page_count_per_instance | Multiple |
| exclusion_rule | Lacks extra columns → it's 4.1 |
| phash_template | Low value (too much variation) |
| extraction_target | Same as 4.1 plus optional extra columns |

---

## 5. `roll_separator` subtypes

### 5.1 `separator_style_a_start`

| Dimension | Value |
|---|---|
| title_text | `START` in large block letters |
| column_headers | None |
| key_phrases | Handwritten `ROLL NO. N` in a box |
| visual_shapes | Two diagonal-hatched rectangles (the "clapperboard stripes") |
| layout_features | Portrait. Roughly 50% of page area is hatched-rectangle artwork |
| name_location | None |
| frame_position_hint | frames 3–6 |
| district_bias | 2, 4, 5, 6, 7 |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No `START` text → not 5.1 |
| phash_template | Yes — high-value template |
| extraction_target | `separator.marker = "START"`, `separator.roll_no = N` |

### 5.2 `separator_style_a_end`

| Dimension | Value |
|---|---|
| title_text | `END` in large block letters |
| column_headers | None |
| key_phrases | Handwritten `ROLL NO. N` in a box |
| visual_shapes | Diagonal-hatched rectangles (same as 5.1) |
| layout_features | Same as 5.1 |
| name_location | None |
| frame_position_hint | last-3 to last frame |
| district_bias | 2, 4, 5, 6, 7 |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No `END` text → not 5.2 |
| phash_template | Yes |
| extraction_target | `separator.marker = "END"`, `separator.roll_no = N` |

### 5.3 `separator_style_b_start`

| Dimension | Value |
|---|---|
| title_text | `CERTIFICATE OF RECORD` header + `START` sub-heading |
| column_headers | None (form-style) |
| key_phrases | `I, [filmer name], do hereby certify`, typed school, handwritten date, signature |
| visual_shapes | Printed form with signature line |
| layout_features | Portrait. Text-heavy, no large block artwork |
| name_location | None for student; filmer name present |
| frame_position_hint | frames 3–6 |
| district_bias | 1, 3 |
| vendor_bias | TIMS primarily |
| page_count_per_instance | 1 |
| exclusion_rule | No `CERTIFICATE OF RECORD` text → not 5.3 |
| phash_template | Yes (form layout) |
| extraction_target | `separator.marker = "START"`, `separator.roll_no = N`, `roll_meta.filmer, date, school, reel_no_cert` |

### 5.4 `separator_style_b_end`

| Dimension | Value |
|---|---|
| title_text | `CERTIFICATE OF AUTHENTICITY` header + `END` sub-heading |
| column_headers | None |
| key_phrases | `I, [filmer name], do hereby certify`, signature |
| visual_shapes | Printed form |
| layout_features | Portrait |
| name_location | None |
| frame_position_hint | last-3 to last frame |
| district_bias | 1, 3 |
| vendor_bias | TIMS primarily |
| page_count_per_instance | 1 |
| exclusion_rule | No `CERTIFICATE OF AUTHENTICITY` text → not 5.4 |
| phash_template | Yes |
| extraction_target | `separator.marker = "END"`, `separator.roll_no`, same roll_meta |

---

## 6. `roll_leader` subtypes

### 6.1 `leader_blank`

| Dimension | Value |
|---|---|
| title_text | None |
| column_headers | None |
| key_phrases | None |
| visual_shapes | Near-uniform pixel field |
| layout_features | Pixel std-dev < 8 across full frame |
| name_location | None |
| frame_position_hint | frames 1–2, last-1 |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1–2 |
| exclusion_rule | Any recognizable text or shape → not 6.1 |
| phash_template | No (trivially detectable) |
| extraction_target | None |

### 6.2 `leader_letterhead_tims`

| Dimension | Value |
|---|---|
| title_text | `TOTAL INFORMATION MANAGEMENT SYSTEMS` |
| column_headers | None |
| key_phrases | `TIMS`, address block, logo |
| visual_shapes | Company logo top-left or center |
| layout_features | Portrait, mostly whitespace |
| name_location | None |
| frame_position_hint | frames 1–3 |
| district_bias | all except D1 ROLL 001 (that one is WMS) |
| vendor_bias | TIMS |
| page_count_per_instance | 1 |
| exclusion_rule | Has WMS text → it's 6.3 |
| phash_template | **YES** — strongest pre-LLM filter |
| extraction_target | `roll_meta.filming_vendor = "TIMS"` |

### 6.3 `leader_letterhead_whites`

| Dimension | Value |
|---|---|
| title_text | `WHITE'S MICROFILM SERVICES` |
| column_headers | None |
| key_phrases | `White's`, `Microfilm` |
| visual_shapes | Different company logo |
| layout_features | Similar to 6.2 |
| name_location | None |
| frame_position_hint | frames 1–3 |
| district_bias | D1 ROLL 001 confirmed; TBD elsewhere |
| vendor_bias | WMS |
| page_count_per_instance | 1 |
| exclusion_rule | Has TIMS text → it's 6.2 |
| phash_template | **YES** |
| extraction_target | `roll_meta.filming_vendor = "WMS"` |

### 6.4 `leader_calibration_target`

| Dimension | Value |
|---|---|
| title_text | Usually none or `RESOLUTION TEST` |
| column_headers | None |
| key_phrases | None |
| visual_shapes | Concentric rings / parallel-line groups / NBS resolution chart |
| layout_features | Symmetric pattern |
| name_location | None |
| frame_position_hint | first 1–3 or last 1–2 |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Has readable text → not 6.4 |
| phash_template | **YES** — single canonical chart, identical across rolls |
| extraction_target | None |

### 6.5 `leader_district_title`

| Dimension | Value |
|---|---|
| title_text | `OSCEOLA COUNTY` and `RECORDS DEPARTMENT` or similar |
| column_headers | None |
| key_phrases | County seal, district name |
| visual_shapes | County seal graphic |
| layout_features | Title-page style, mostly centered text |
| name_location | None |
| frame_position_hint | frames 2–5 |
| district_bias | district-labeled per roll |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | No `OSCEOLA` / district-name text → not 6.5 |
| phash_template | Partial (seal is constant) |
| extraction_target | `roll_meta.school = district name` |

### 6.6 `leader_filmer_cert`

| Dimension | Value |
|---|---|
| title_text | `FILMER'S CERTIFICATION` or similar |
| column_headers | Form fields: `FILMER`, `DATE`, `REEL NO.`, `SCHOOL` |
| key_phrases | `I certify that these are true...` but **WITHOUT** `START` / `END` marker |
| visual_shapes | Printed form with signature line |
| layout_features | Portrait |
| name_location | Filmer name, not student |
| frame_position_hint | frames 2–5 |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Has `START` or `END` in heading → it's 5.3/5.4 not 6.6 |
| phash_template | Partial |
| extraction_target | `roll_meta.filmer, date, school, reel_no_cert` |

### 6.7 `leader_operator_card`

| Dimension | Value |
|---|---|
| title_text | Handwritten roll identification |
| column_headers | None |
| key_phrases | Handwritten `ROLL NO.`, `DATE`, operator initials |
| visual_shapes | Small card in center of frame, lots of whitespace around |
| layout_features | Landscape or small vertical card occupying only center of frame |
| name_location | None |
| frame_position_hint | frames 2–5 |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Has `START` / `END` text → it's 5.x |
| phash_template | No (handwriting varies) |
| extraction_target | `roll_meta.date, reel_no_cert` if extractable |

---

## 7. `unknown` subtypes

### 7.1 `unknown_blank_midroll`

| Dimension | Value |
|---|---|
| title_text | None |
| column_headers | None |
| key_phrases | None |
| visual_shapes | Near-uniform pixel field |
| layout_features | Pixel std-dev < 8, frame NOT in first-7 / last-3 |
| name_location | None |
| frame_position_hint | mid-roll only |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Frame is first-7 or last-3 → it's `leader_blank` not `unknown_blank_midroll` |
| phash_template | No |
| extraction_target | None |

### 7.2 `unknown_illegible`

| Dimension | Value |
|---|---|
| title_text | Unreadable |
| column_headers | Unreadable |
| key_phrases | None detectable |
| visual_shapes | Noisy / faded / over-exposed / under-exposed |
| layout_features | High noise, very low contrast, OR extreme skew |
| name_location | Unreadable |
| frame_position_hint | anywhere |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Can read >= 5 contiguous words → not illegible |
| phash_template | No |
| extraction_target | None |

### 7.3 `unknown_unrecognized`

| Dimension | Value |
|---|---|
| title_text | Any text but doesn't match subtype library |
| column_headers | Unknown layout |
| key_phrases | None that map to known classes |
| visual_shapes | Any |
| layout_features | Legible but layout not in any other subtype |
| name_location | Variable |
| frame_position_hint | anywhere |
| district_bias | all |
| vendor_bias | either |
| page_count_per_instance | 1 |
| exclusion_rule | Layout matches any other subtype → use that one |
| phash_template | No |
| extraction_target | None |

---

## Decision rule integration

This matrix feeds three consumers:

1. **Prompt generation:** when classifying, prepend the subtype library description to the system prompt. Haiku gains richer disambiguation context.
2. **Pre-filter (`poc/pre_filter.py` — Phase 2):** pHash checks against `leader_letterhead_tims`, `leader_letterhead_whites`, `leader_calibration_target`, `separator_style_a_start/end` template images. Pixel std-dev gate for `leader_blank` / `unknown_blank_midroll`. Frame-position prior narrows candidate set.
3. **Post-validator (`poc/validators.py` — Phase 2):** each subtype's `exclusion_rule` becomes a negative check. Any validator rejection routes the page to a retry with subtype-specific prompt, OR downgrades it to a neighbor class per the rule.

Machine-readable structure: `docs/class-matrix.json`.

---

## Known limitations / follow-up

- Subtypes 2.4 / 2.5 / 3.4 / 3.5 are inferred from corpus norms; not yet visually confirmed on ROLL 001 sample. May need absorption/split after we build a fixture library with labeled exemplars.
- pHash reference images not yet captured. Next action: script in `scripts/` that pulls N exemplars per subtype from known-good samples, writes `poc/corpora/phash_templates/<subtype>.phash`.
- `district_bias` is partial for D1 only. Broader sampling across D2–D7 will refine.
- `unknown_unrecognized` is a catch-all; anything landing here triggers HITL review.
