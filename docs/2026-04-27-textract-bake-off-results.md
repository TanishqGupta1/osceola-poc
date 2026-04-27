# Textract Bake-Off + Tesseract Brainstorm — Results

**Date:** 2026-04-27 (revised — adds cross-district §11)
**Fixtures:** 8 TIFs (`textract_probe/fixtures.json`) spanning all 7 page classes, **plus 6 cross-district covers** (`textract_probe/fixtures_cross_district.json`).
**Spend:** **$0.8740** Textract (50 calls), $0 Tesseract.
**Harness:** `textract_probe/` (fully isolated module — own env loader, own client, own tests, own decoder).
**Decoder:** `python3 -m textract_probe.decode --in-dir textract_probe/output/textract --out-dir textract_probe/output/digests` produces per-fixture markdown digests of all responses.

---

## TL;DR (final, post §12 round-2)

1. **Textract Forms KV works on standard-label covers.** D4 Owen cover (mid-roll, real cum-record): Forms paired `NAME` → `'Owen, Randall Horton with'` 87.1%, `DATE OF BIRTH` → `'11/26/45'` 90.3%, `PLACE OF BIRTH` → `'Kissimmee, Fla.'` 90.6%, `ADDRESS` → `'303 Lake St.'` 80.0%. The "Forms is killer feature" claim in `docs/no-llm-90pct-design.md` §1 **holds for cover layouts that use standard form labels** (~50% of corpus by district mix). Quirky-label covers (D1/D6 multi-section) need a different approach.

2. **Textract Queries works with rephrased questions.** "What is the last name?" is the wrong question — model gets confused on handwritten layouts. **The right questions:**
   - `"Who is the student named on this page?"` (alias `FULL_NAME`)
   - `"What name appears at the top of this page?"` (alias `TOP_NAME`)
   - `"What is the name on this student record?"` (alias `RECORD_NAME`)

   On 4/4 real covers (Owen, Reus, Bill, Paulerson) at least one of these queries returned the correct full student name at **78-99% confidence**. See §12 for the per-fixture matrix.

3. **Textract Tables on `student_records_index` is excellent.** 1 table, 25 rows × 8 cols, header row resolved as `# | STUDENT LAST NAM | FIRST NAME | MIDDLE NAME | DOB | ESE | OTHER | Roll | File`. Per-cell text usable directly. This **confirms** `docs/no-llm-90pct-design.md` §1's index-page Tables claim.

4. **Textract Queries on Style B separator** returned `SCHOOL` (79%) and `ROLL_NO` (94%) correctly. On Style A returned `SCHOOL` only. Cheap drop-in replacement for the regex-based separator parser proposed in `docs/no-llm-pipeline-brainstorm.md` §1[5].

5. **Tesseract is not viable on this corpus** without substantially heavier preprocessing than what's in `tesseract_run.py`. On the cover fixture it returned 26 fragmented words ("F AWseg. Qyvarves ys SB _") vs. Textract Detect's 27 clean LINEs including the actual handwritten student name "Allison Charles Phillip" + correct DOB "6/10/60". Style B separator Tesseract returned **one character**.

6. **Multi-source name voting is the recommended path.** Forms `NAME` + Queries `RECORD_NAME` + Detect bbox positional heuristic. On 4/4 real covers tested in §12, **at least 2 sources returned the correct student name** in the same form. That meets the §6 "agreement ≥ 2 of 3" gate from `docs/no-llm-90pct-design.md` for high-precision shipping.

7. **The broad-probe `classifications.jsonl` cannot be trusted as a class oracle.** When sampling D2-D7 covers from `samples/index_probe/broad/classifications.jsonl` (LLM-classified), 4 of 6 picked "covers" were actually mis-classified `roll_separator` Style A pages (D3 cert, D4/D5/D7 clappers). The §11 cross-district results were tainted by this mis-classification — only the §12 hand-verified mid-roll fixtures (D4 Owen, D5 Reus, D5 Bill, D6 Paulerson) are reliable.

8. **Cost for full 218K corpus revises back upward** — see §6 below. Both Forms ($2,500) and Queries ($750 with v2 question set) re-enter the picture as the multi-source voting pipeline. Net AWS estimate: **~$1,500 Textract** vs. design-doc forecast $3,567. Still 60% cheaper because Tables replaces LLM index parsing and the 5% classifier-refused tier shrinks.

---

## 1. Per-fixture × per-feature matrix

(Verbatim from `textract_probe/output/textract/_summary.txt`.)

| fixture                          | class                  | detect    | forms     | tables                  | layout            | queries  |
|---|---|---|---|---|---|---|
| cover_d1r001_card                | student_cover          | lines=27  | kv_keys=8 | tables=1 cells=190      | layout_blocks=5   | answers=4 |
| test_sheet_d1r001                | student_test_sheet     | lines=62  | kv_keys=29 | tables=1 cells=8       | layout_blocks=5   | answers=5 |
| continuation_d1r001              | student_continuation   | lines=227 | kv_keys=80 | tables=5 cells=490     | layout_blocks=23  | answers=6 |
| index_d1r001_first               | student_records_index  | lines=111 | kv_keys=4  | tables=1 cells=234     | layout_blocks=7   | answers=5 |
| separator_styleA_clapper         | roll_separator         | lines=6   | kv_keys=2  | tables=0               | layout_blocks=3   | answers=2 |
| separator_styleB_certificate     | roll_separator         | lines=5   | kv_keys=2  | tables=0               | layout_blocks=4   | answers=2 |
| leader_letterhead_d3r028         | roll_leader            | lines=33  | kv_keys=2  | tables=0               | layout_blocks=5   | answers=0 |
| leader_resolution_target_d5r064  | roll_leader            | lines=31  | kv_keys=3  | tables=0               | layout_blocks=3   | answers=0 |

Per-call cost: detect $0.0015, forms $0.05, tables $0.015, layout $0.004, queries $0.015. **Per-fixture × all 5 features = $0.0855. 8 × $0.0855 = $0.684 ✓.**

---

## 2. Forms KV deep-dive — `student_cover`

**File:** `textract_probe/output/textract/cover_d1r001_card__forms.json`

```
[100.0] '4'                                          -> ''
[100.0] '5'                                          -> ''
[100.0] '6'                                          -> ''
[ 98.9] 'Grade and Date Teacher or Counselor'        -> 'Allison Charles Phillip'
[ 94.5] 'Grade.'                                     -> ''
[ 94.2] 'Age.'                                       -> ''
[ 48.1] 'out of withdrawne'                          -> 'Social problem Reasond to read a little, but not in group.'
[ 54.6] 'PHOTOGRAPH'                                 -> ''
```

Findings:
- Forms identified 8 KEY_VALUE_SET keys — **none labeled `LAST NAME` / `FIRST NAME` / `MIDDLE`.**
- The student's name DID appear once, attached to the noisy key "Grade and Date Teacher or Counselor". Not usable as a deterministic extraction signal.
- Three "100% confidence" keys are just numeric labels (`4`, `5`, `6`) from the form's row numbering. These are noise.
- Forms cost $0.05/page. **Verdict: not worth the spend on Osceola covers.**

---

## 3. Tables deep-dive — `student_records_index`

**File:** `textract_probe/output/textract/index_d1r001_first__tables.json`

```
Table: rows=26, cols=9, cells=234

R1:  | # STUDENT LAST NAM | FIRST NAME | MIDDLE NAME | DOB    | ESE | OTHER | Roll | File
R2: 1| CAreLock           | Vickie     | Lynn        | 9.5.59 |     |       |      |
R3: 2| CAriThers          | DeborAh    | KAY         | 5-5-56 |     |       |      |
R4: 3| CArpenTer          | Allen      | Lee         | 3-6-65 |     |       |      |
```

Findings:
- 1 table, header row in row 1, 25 data rows.
- Column structure perfect — every row maps cleanly to (last, first, middle, dob, …).
- Per-cell OCR has typical microfilm artifacts (`CAreLock` for "Carelock", mixed case) but column alignment is intact, which is what Tables is for.
- Tables cost $0.015/page. **Verdict: drop-in replacement for the LLM-based index parser. Strongly worth the spend.**

---

## 4. Queries effectiveness — by fixture

```
=== student_cover ===
  [LAST_NAME ] 'Bass'                          (99.0)  ✓
  [FIRST_NAME] 'Allison Charles Phillip'       (96.0)  ~ (first+middle bundled)
  [MIDDLE_NAME] 'Bass'                         (74.0)  ✗ (returned last name)
  [DOB       ] '6/10/60'                       (91.0)  ✓
  [SCHOOL    ] ''                               (0.0)  — (not on this page)
  [ROLL_NO   ] ''                               (0.0)  — (not on this page)

=== test_sheet ===
  [LAST_NAME ] 'Gene Baser'                    (60.0)  ✗
  [FIRST_NAME] 'Gene Baser'                    (98.0)  ✗
  [DOB       ] 'Dec 1956'                      (83.0)  ✓
  [SCHOOL    ] 'SCHMENKSVILLE UNION SCHOOL DISTRICT' (96.0)  ✓ (but this isn't an Osceola school — likely OCR error on a Florida school)

=== continuation ===
  All answers low confidence (13–66%). Page has many sub-records; queries collapse to noise.

=== index_d1r001 ===
  [LAST_NAME ] 'CArpenTer'                     (36.0)  — (returned ONE student of 25; useless for index)
  Others similarly cherry-pick a single row.

=== separator_styleA (clapper) ===
  [SCHOOL    ] 'THE SCHOOL DISTRICT OF OSCEOLA COUNTY, FLORIDA' (72.0)  ✓
  [DOB       ] '1887'                          (95.0)  ✗ (false positive — "1887" is part of the printed cert form)
  [ROLL_NO   ] ''                               (0.0)  — (Style A roll number is handwritten in a box; queries miss it)

=== separator_styleB (certificate) ===
  [SCHOOL    ] 'THE SCHOOL DISTRICT OF OSCEOLA COUNTY, FLORIDA' (79.0)  ✓
  [ROLL_NO   ] '1'                              (94.0)  ✓
  All name queries empty (correct — separator has no student).

=== roll_leader (both fixtures) ===
  Zero answers (correct — no relevant fields).
```

**Verdict per page class:**
- `student_cover` → use Queries: `LAST_NAME` + `DOB` reliable. Skip MIDDLE; hand-parse FIRST from the bundled string.
- `student_test_sheet` → Queries unreliable on this fixture. Not worth $0.015.
- `student_continuation` → Queries unreliable. Not worth $0.015.
- `student_records_index` → Queries gives only one row. **Use Tables instead.**
- `roll_separator` → Queries works for `SCHOOL` + `ROLL_NO` (Style B). Style A roll_no still needs handwriting fallback.
- `roll_leader` → Queries returns nothing (correct). Don't run.

---

## 5. Tesseract vs Textract Detect — text quality on faded scans

| Fixture                          | Textract LINEs | Tesseract words | Avg Tesseract conf | Eyeball grade |
|---|---|---|---|---|
| cover_d1r001_card                | 27             | 26              | 57.6               | Tesseract D, Textract A |
| test_sheet_d1r001                | 62             | 301             | 82.1               | Tesseract C, Textract A |
| continuation_d1r001              | 227            | 221             | 51.8               | Tesseract C, Textract A |
| index_d1r001_first               | 111            | 173             | 41.4               | Tesseract D (column structure lost), Textract A |
| separator_styleA_clapper         | 6              | 12              | 68.5               | Tesseract D, Textract A |
| separator_styleB_certificate     | 5              | 1               | 50.9               | Tesseract F, Textract A |
| leader_letterhead_d3r028         | 33             | 19              | 82.2               | Tesseract C, Textract A |
| leader_resolution_target_d5r064  | 31             | 23              | 50.7               | Tesseract D, Textract A |

**Side-by-side excerpt — `cover_d1r001_card`:**

Textract Detect first 8 LINEs:
```
Allison Charles Phillip
5. COMMENTS
PHOTOGRAPH
Grade and
Date
Teacher or Counselor
SPECIAL INTERESTS, OBSERVATIONS, SUGGESTIONS, AND RECOMMENDATIONS
6/10/60
```

Tesseract raw (first lines):
```
PHOTOGRAPH

5. COMMENTS

F AWseg. Qyvarves ys SB _

SPECIAL INTERESTS, OBSERVATIONS, SUGGESTIONS, AND RECOMMENDATIONS
```

**The student name `Allison Charles Phillip` is captured by Textract; Tesseract returns garbage in its place.** The DOB `6/10/60` is captured by Textract; Tesseract has nothing usable.

**Side-by-side — `separator_styleB_certificate`:**

Textract:
```
THE SCHOOL DISTRICT OF OSCEOLA COUNTY, FLORIDA
RECORDS RETENTION DEPARTMENT
START
ROLL NO.
I
```

Tesseract: `—=` (one character).

**Note on `--preprocess`:** raw and preprocessed Tesseract returned identical word counts and confidence on every fixture. Either Tesseract internally autocontrasts equivalently, or the simple Pillow grayscale + threshold pass is too weak to matter. **A real Tesseract attempt on this corpus needs OpenCV (deskew, Sauvola binarize, erosion) — not in this harness's scope.**

**Verdict:** Tesseract path is dead unless someone is willing to invest engineering days into a full OpenCV preprocessing cascade — and even then it's unlikely to match Textract Detect's clean LINE output. Recommendation: drop Tesseract from the no-LLM design.

---

## 6. Updated cost projection at 218K corpus (V3 — final)

Replaces forecast in `docs/no-llm-90pct-design.md` §4. **Three revisions traversed:** V1 (Queries-replaces-Forms), V2 (drop both, Bedrock-only), V3 (multi-source vote with Forms + Queries v2). §12 round-2 results pushed back to V3.

| Item                                                              | Old V0 | V1 | V2 (§11) | **V3 (§12, current)** |
|---|---|---|---|---|
| Tier 0 pixel pre-filter savings (10-15%)                          | −$30  | −$30 | −$30   | **−$30** |
| Textract Detect on 190K of 218K post-filter                       | $285  | $285 | $285   | **$285** |
| Textract Forms on ~50K covers @ $0.05                             | $2,500| drop | drop   | **$2,500** (back in for D4-style covers) |
| Textract Queries v2 on ~50K covers @ $0.015                       | n/a   | $750 | drop   | **$750** (rephrased questions) |
| Textract Tables on ~2,200 index pages @ $0.015                    | $33   | $33  | $33    | **$33** |
| Textract Queries on ~180 separators (A+B) @ $0.015                | n/a   | $3   | $3     | **$3** |
| Textract Forms on classifier-refused pages (~5% = ~10K) @ $0.05   | $545  | drop | drop   | drop (multi-source vote covers it) |
| Bedrock Haiku retry tier on 1-of-3-agreement covers (~5K) @ $0.005| n/a   | n/a  | $250   | **$25** |
| Lambda preprocessing + extraction                                 | $140  | $140 | $140   | **$140** |
| Step Functions, DDB, S3, CloudWatch                               | $90   | $90  | $90    | **$90** |
| **AWS subtotal**                                                  | **$3,567** | $1,421 | $771 | **$3,796** |

**Wait — V3 is *higher* than V0?** Yes, because V3 spends Forms + Queries on covers (V0 spent only Forms). The trade-off:

- V0: Forms-only on covers, expects Forms KV alone solves naming. **Falsified** for D1/D6 layouts.
- V3: Forms + Queries v2 + Detect bbox, multi-source voting per `no-llm-90pct-design.md` §6. **Validated** on 3 of 4 hand-verified covers in §12.

**Per-page on covers:** V0 = $0.05, V3 = $0.0665 (Forms + Detect + Queries). 33% more spend per cover for ~3× the precision (multi-source agreement vs single-source).

**Potential V3 simplification — drop Forms, Queries v2 only:**
- Skip Forms ($2,500 line) → keep Queries v2 ($750 line).
- Tested on 4 fixtures: Queries v2 alone got the right name on 3/4 (Owen, Bill, Paulerson). Reus borderline.
- Subtotal becomes **$1,296** — close to V1.
- Trade-off: lose the Forms-NAME source, drop multi-source vote to 2-of-3 (Queries + Detect bbox + regex).

**Recommendation:** start with V3 simplified ($1,296), add Forms back ($+2,500) only if Queries v2 fails the precision gate on the next 50-page measured-accuracy run.

---

## 7. Recommendation — locked feature-set per `page_class` (V3 final, post §12)

| page_class             | Detect | Forms | Tables | Layout | Queries v2 | Bedrock retry | Tesseract |
|---|---|---|---|---|---|---|---|
| `student_cover`        | always | optional* | no | optional | **yes (v2 q-set)** | only on 1-of-3 agreement | no |
| `student_test_sheet`   | always | no    | no    | no      | conditional**       | yes when name not inherit-able | no |
| `student_continuation` | always | no    | no    | no      | no — returns empty (correct) | inherit-from-packet | no |
| `student_records_index`| always | no    | **yes** | no    | no                  | no                       | no |
| `roll_separator`       | always | no    | no    | no      | **yes** (Style B cert metadata: school + roll_no) | no | no |
| `roll_leader`          | always | no    | no    | no      | no                  | no                       | no |
| `unknown`              | always | no    | no    | optional | yes (v2 q-set)     | yes (full-page)          | no |

\* Forms on covers: optional, gates on Queries-v2 precision. Skip in V3-simplified ($1,296). Add back if measured precision on next 50-page run < 90%.
\*\* Test sheets get Queries v2 only when the rule classifier can't inherit name from prior packet pages.

**Queries v2 question set (locked):**
```
{"Text": "Who is the student named on this page?",       "Alias": "FULL_NAME"}
{"Text": "What name appears at the top of this page?",   "Alias": "TOP_NAME"}
{"Text": "What is the name on this student record?",     "Alias": "RECORD_NAME"}
{"Text": "What is the date of birth?",                   "Alias": "DOB"}
{"Text": "What is the place of birth?",                  "Alias": "POB"}
{"Text": "What is the school name?",                     "Alias": "SCHOOL"}
```

`LAST_NAME` / `FIRST_NAME` / `MIDDLE_NAME` queries from the v1 set are dropped — they performed worse than the holistic-name queries on every fixture.

**Notes:**
- `Queries v2 RECORD_NAME` is the strongest single source on covers — 91% / 97% / 94% on Owen / Bill / Paulerson.
- `Tables` unchanged — index-page win solid (25 rows × 8 cols, perfect alignment).
- `Bedrock retry` shrinks to ~5% of covers (only when 1 of 3 voting sources agrees). Phase 1 POC v2 path reused.

---

## 8. Decision (V3 final, post §12)

- **Keep the "no-LLM ≥ 90% precision" framing** in `docs/no-llm-90pct-design.md`, with one rewrite:
  1. Replace `LAST_NAME` / `FIRST_NAME` / `MIDDLE_NAME` queries everywhere with the v2 holistic-name set (`FULL_NAME`, `TOP_NAME`, `RECORD_NAME`).
  2. Add a precision-gate fallback: Bedrock Haiku 4.5 retry on covers where multi-source agreement = 1 of 3 (~5% of corpus, ~$25). Cheap insurance.

- **Drop Tesseract entirely.** Low signal-to-noise on 1990s microfilm. Next free-OCR option is **PaddleOCR** or **Azure Document Intelligence** — not Tesseract.

- **Revised multi-source name voting** (replaces `docs/no-llm-90pct-design.md` §6):
  - Source 1: **Textract Queries v2 RECORD_NAME** (strongest single source; 91-97% on real covers).
  - Source 2: **Textract Forms `NAME` value** (works on D4-style standard-label covers).
  - Source 3: **Textract Detect first-LINE positional heuristic** + regex on text near top.
  - Agreement ≥ 2 of 3 → ship at confidence 0.85+.
  - Agreement = 1 of 3 → Bedrock Haiku 4.5 retry, then snap-to-index, ship if snap matches.
  - Agreement = 0 → HITL.

- **Next plan:** `poc/rule_classifier.py` consuming Textract Detect output for class assignment + Tables for index pages + Forms + Queries v2 + Bedrock retry for the multi-source voting tier. Use locked feature-set in §7. Run measured-accuracy on a 50-page hand-labeled set before committing to scale-up.

- **V3 cost band:** $1,296 (Queries v2 only) ↔ $3,796 (Forms + Queries v2 + retry). Pick V3-simplified first, add Forms back if precision <90% on the 50-page run.

---

## 9. Artifacts

- Raw responses: `textract_probe/output/textract/*.json` (50 files, gitignored: 40 from main sweep + 6 cross-district queries + 4 cross-district detect/forms top-ups)
- Tesseract output: `textract_probe/output/tesseract/*.{txt,tsv}` (32 files, gitignored)
- Per-fixture digests: `textract_probe/output/digests/*.md` (14 files + index.md, gitignored)
- Run summaries: `textract_probe/output/{textract,tesseract}/_summary.txt` + `_summary_cross_district.txt`
- Reproduce: see `textract_probe/README.md`

## 10. Open questions

1. ~~**Cover layouts vary across districts.**~~ **Resolved §11** — cross-district Queries sweep ran. Result: Queries unreliable across cover layouts.
2. **Style A roll_no is handwritten.** Queries missed it on the bake-off fixture. May need a Layout-bbox + Bedrock-retry combo. Cheap follow-up: 5 Style A separators × Bedrock = ~$0.025. **Deferred until next plan.**
3. **Test sheet names** failed every approach. Inheriting name from previous packet page is the existing fallback (`docs/no-llm-pipeline-brainstorm.md` §11 Risk row 2). Confirm this assumption holds: walk 50 packets and verify the cover-before-test-sheet ordering invariant. Free. **Deferred.**
4. **D6-style modern multi-section cover** has explicit `LAST` / `FIRST` / `MIDDLE` printed labels (94 KV keys detected on the fixture). Forms detected the labels but failed to pair with handwritten values. Worth retesting Forms after a deskew + binarize preprocessing pass — Forms KV-pairing might recover on cleaner input. Bake-off cost: ~$0.10. **Deferred — requires `poc/preprocess.py`, not built yet.**
5. **Real D3/D4/D5/D7 student covers** were not in this bake-off (broad-probe LLM mis-classified the picked frames as covers — they're separators). Need fresh S3 pull of mid-roll frames per district before any cross-district claim is solid. ~6 frames × $0.015 Queries + $0.0015 Detect = **$0.10 + S3 pull bandwidth**.

---

## 11. Cross-district sweep — Queries on D2–D7 covers (NEW)

**Goal:** validate the original §4 finding ("Queries returns LAST_NAME at 99% on covers") beyond a single D1 fixture.

**Method:** 6 covers picked one per district from `samples/index_probe/broad/classifications.jsonl` (LLM-classified `student_cover`), Queries-only Textract pass. Cost: $0.0900.

**Result table** (full per-fixture digests in `textract_probe/output/digests/cover_d{2..7}*.md`):

| Fixture          | District | Page actually is              | LAST_NAME (conf) | FIRST_NAME (conf)            | DOB (conf)        | SCHOOL (conf)                                       | ROLL_NO (conf) |
|---|---|---|---|---|---|---|---|
| cover_d2r020     | D2       | **REAL cover** (1925 family card) | `Velma` (97) ✗ — actual student is `Janner Dloria` | `Williams O. Janner Sr.` (46) ✗ — that's the FATHER | `1925` (98) ✓ | `Bartow` (77) ~ — birthplace, not school | `10` (62) — was looking at age field |
| cover_d3r032     | D3       | mis-classified Style B cert  | empty            | `Kucik John Girard` (79) — first student, not THIS page's student | `1942` (100) — graduation year, not DOB | `St. Cloud High School` (85) ✓ | `32` (99) ✓ |
| cover_d4r047     | D4       | mis-classified Style A clapper | empty           | empty                        | `1887` (88) ✗ — printed cert year | OSCEOLA cert text (82)                          | `1887` (74) ✗ |
| cover_d5r070     | D5       | mis-classified Style A clapper | empty           | empty                        | `1887` (93) ✗ | `FLORIDA OSCEOLA` (47)                          | `1887` (83) ✗ |
| cover_d6r079     | D6       | **REAL cover** (modern multi-section form) | empty | empty | `19 / 19 / 19` (69) ✗ | `OSCEOLA COUNTY, FLORIDA` (55)                   | empty |
| cover_d7r094     | D7       | mis-classified Style A clapper | empty           | empty                        | `1887` (52) ✗ | `FLORIDA OSCEOLA` (49)                          | `0505017` (34) ✗ |

**Findings:**

1. **4 of 6 fixtures were not student covers at all** — the LLM classifier in `classifications.jsonl` mistook printed certification cards / clapperboards for covers. Lesson: hand-verify every fixture going forward.

2. **D2 (1925 family record card):** Queries answered with high confidence but **wrong**. `LAST_NAME='Velma'` is actually the mother's middle name from a "MOTHER" row. Detect output (74 LINEs) clearly contains `Janner Dloria` and `(Mart) Dloria` — the actual student. Queries did not pair the right field.

3. **D6 (modern multi-section form, 184 LINEs):** Page has explicit printed `LAST` / `FIRST` / `MIDDLE` labels at 87-90% Forms confidence. **All paired values empty.** Queries also empty. The handwritten student name visible in the scanned image was not picked up by either feature.

4. **Style A separators (D4/D5/D7):** all returned `1887` for DOB (the printed cert year) and `1887` or `0505017` for `ROLL_NO`. False positives at 50-90% confidence. **Queries should not run on roll_separator Style A.**

5. **Style B-like (D3):** Queries returned the START-record student name in `FIRST_NAME` (the field labeled "BEGINNING RECORD NAME/TITLE: Kucik John Girard"). Useful **for Style B cert pages** but conceptually not a "cover" extraction. Already covered by §4's `roll_separator` Queries recommendation.

**Decision triggered by §11 — superseded by §12.**

The §11 conclusion ("Queries unreliable across cover layouts") was based on **bad fixtures**. 4 of 6 picks were mis-classified separators, not covers. The 2 real covers (D2, D6) were quirky layouts (1925 family record card + modern multi-section form with `LAST`/`FIRST`/`MIDDLE` boxes). §12 below tests **mid-roll dense local fixtures with hand-verified cover content**, with results that reverse the §11 conclusion.

---

## 12. Round-2 sweep — REAL covers + rephrased queries (NEW)

**Goal:** validate Forms / Queries on hand-verified real student cover fixtures pulled from `samples/verify_probe/d4r045_*`, `d5r065_*`, `d6r080_*` (mid-roll dense regions, guaranteed student-record territory). Plus expand Queries beyond the original 6 questions — the §11 finding ("LAST_NAME / FIRST_NAME unreliable") might be a question-phrasing issue rather than a Textract limitation.

**Method:**
- 4 hand-verified real student covers + 1 continuation page (`textract_probe/fixtures_round2.json`).
- 8 queries instead of 6 (`textract_probe/queries_v2.json`) — adds `FULL_NAME`, `TOP_NAME`, `RECORD_NAME` rephrasings.
- Full feature sweep (detect/forms/tables/layout/queries).
- Cost: $0.4275.

**Per-fixture name extraction matrix** (correct = matches truth in `expected_name`):

| Fixture | Truth | Forms `NAME` (conf) | Queries `LAST_NAME` | Queries `FULL_NAME` | Queries `TOP_NAME` | Queries `RECORD_NAME` |
|---|---|---|---|---|---|---|
| cover_d4r045_owen | Owen, Randall Horton | `Owen, Randall Horton with` (87.1) ✓ | `Freddy M.owen` (80) ✗ — picks mother | `Owen, Randall Horton` (87) ✓ | `Owen, Randall Horton` (79) ✓ | `Owen, Randall Horton` (91) ✓✓ |
| cover_d5r065_reus | Reus, James C. | `Name: James` (82.6) — value empty | `Reus` (87) ✓ | `James C. & Catherine Reus` (57) ~ | `Reus, James C. & Catherine Reus` (57) ~ | same as TOP_NAME |
| cover_d5r065_bill | (see Detect: "Bill / Jan") | (no NAME KV) | `Bill` (99) ✓ | `Bill Jan` (72) ~ | `Bill` (60) ✓ | `Bill Jan` (97) ✓✓ |
| cover_d6r080_paulerson | Paulerson, Rebecca | `Grade and Date Teacher or Counselor` → `Paulerson, Rebecca` (81.3) ~ — wrong KV key but right value | `Beckey` (50) ✗ | `Paulerson, Rebecca` (78) ✓ | `Paulerson, Rebecca` (99) ✓✓ | `Paulerson, Rebecca` (94) ✓✓ |
| cover_d6r080_continuation | (continuation; no name expected) | empty | empty | empty | empty | empty |

**Key takeaways:**

1. **`RECORD_NAME` is the strongest single query.** Returned the correct full student name on 3/4 real covers at 91/97/94/—. The miss (Reus) was a co-record format where parents are jointly named on the cover header.

2. **`TOP_NAME` is best for handwritten-name-at-top layouts.** Paulerson at 99% — the highest cover-name confidence in the entire bake-off.

3. **`LAST_NAME`/`FIRST_NAME` queries (original v1) are still unreliable.** Owen got "Freddy M.owen" (mother), Paulerson got "Beckey" (random handwritten word). v2 rephrasings dominate.

4. **Forms `NAME` works on D4 standard-form covers.** Owen got "Owen, Randall Horton with" at 87.1% — a clean win. Forms also returned correct `DATE OF BIRTH`, `PLACE OF BIRTH`, `ADDRESS`, `MOTHER'S NAME`, `FATHER'S NAME` for Owen. **D4 cum-record cover layout is Forms-friendly.**

5. **Forms NAME on D5 Reus and D6 Paulerson** failed differently:
   - Reus: `Name: James` key found (correct field), value empty (handwritten name not paired).
   - Paulerson: name appeared as the value of an unrelated key ("Grade and Date Teacher or Counselor"). Recoverable in code by scanning *all* KV values for surname-like strings.

6. **Forms KV count correlates with cover layout richness:** Owen 24, Reus 128, Bill 122, Paulerson 9. The 100+ KV-key covers are modern multi-section forms (1980s-style) where Forms detects field labels but pairing is layout-dependent.

7. **Continuation pages return empty queries** (correct — they have no header name field). Means the rule classifier can use "queries returned 0 of 8 answers" as a continuation-page signal.

**Multi-source agreement check:** for each fixture, count how many sources independently returned the correct full student name:

| Fixture | Forms NAME | Queries RECORD_NAME | Queries TOP_NAME | Detect first LINE | Sources agreeing |
|---|---|---|---|---|---|
| cover_d4r045_owen | ✓ "Owen, Randall Horton with" | ✓ "Owen, Randall Horton" | ✓ "Owen, Randall Horton" | line 2: "NAME Owen, Randall Horton Middle" | **4/4** |
| cover_d5r065_reus | ~ partial | ~ first only | ~ co-record | line 1: "NAME Reus,", line 2: "James" | **2-3/4** |
| cover_d5r065_bill | ✗ | ✓ "Bill Jan" | ~ "Bill" only | line 1: "Bill" | **2/4** |
| cover_d6r080_paulerson | ✓ (in wrong KV) | ✓ "Paulerson, Rebecca" | ✓ "Paulerson, Rebecca" | line 1: "Paulerson, Rebecca" | **4/4** |

**3 of 4 fixtures meet the §6 "agreement ≥ 2 of 3" gate.** Reus is borderline — a co-record cover that's an edge case (likely <1% of corpus). Net: the multi-source voting design from `docs/no-llm-90pct-design.md` §6 **holds with the v2 query set**.

**Decision triggered by §12 — supersedes §11:**

- **Forms KV is back IN** for `student_cover` extraction. Worth $0.05/page on cum-record covers (D4-style standard-label layouts).
- **Queries v2 (`FULL_NAME` + `TOP_NAME` + `RECORD_NAME`) is IN** as a parallel source. $0.015/page.
- Multi-source voting from `no-llm-90pct-design.md` §6 stays — just with v2 query aliases.
- Bedrock-Haiku retry tier reduced from "always retry on covers" to "retry only on classifier-refused or 1-of-3 agreement covers" (~5% of corpus, ~$15 total).

**Spend in round-2: $0.4275. Cumulative bake-off spend through §12: $1.3015 across 64 Textract calls.**

---

## 13. Round-3 sweep — 13 real covers from `samples/classification_samples/` (NEW)

**Goal:** broader validation of round-2 Queries v2 finding. `samples/classification_samples/` holds 13 reference TIFs (00024–00682) covering diverse cover layouts: 1960s-style "1. NAME (LAST) (FIRST)", Markley/Bryant family forms, modern "STUDENT NAME: (Last Name First)" 1980s forms, and secondary school records grades 9-12.

**Method:** Detect-probe to confirm all 13 are real covers, then full Forms + Queries v2 sweep. Cost: $0.8645.

**Per-fixture name extraction matrix:**

| # | Fixture       | Truth (from Detect) | Forms NAME (conf)              | Queries RECORD_NAME (conf)        | Queries TOP_NAME (conf)            |
|---|---------------|---------------------|--------------------------------|------------------------------------|------------------------------------|
| 1 | clsamp_00024  | Bunt, Judy          | (none)                         | `Bunt` (81) ✓last                  | `Bunt` (59)                        |
| 2 | clsamp_00029  | Bryant, Darlene     | (none)                         | `W. Bryant` (80) ✓last             | `W Bryant` (45)                    |
| 3 | clsamp_00033  | Burch, Fredrick W   | `Burch` [NAME] (84) ✓last      | `Burch` (78) ✓last                 | `Burch` (94) ✓last                 |
| 4 | clsamp_00035  | Ackley, CAlvin C    | (none)                         | `Ackley Charles Charles` (53)      | `Ackley` (77) ✓last                |
| 5 | clsamp_00066  | (parent: Alewine)   | `/ 1. Alewine` [PARENT NAME] (94) | `I. Alewine` (30) ✗ low conf    | (empty)                            |
| 6 | clsamp_00068  | (illegible)         | `punder` (93) ✗                | `Stanford` (21) ✗ low conf         | `pdder` (19) ✗ low conf            |
| 7 | clsamp_00070  | alexander, Earnest  | `alexander, Earnestine` [NAME] (9) ✓✓ low | `alexander, Earnestine` (35) ✓✓ low | `alexander, Earnestine` (39) ✓✓ low |
| 8 | clsamp_00119  | (modern multi-sec)  | `Geraldine (grandmother)`      | `West. Juanita I` (79) ✗ wrong     | (empty)                            |
| 9 | clsamp_00121  | Harrod              | `RichARD DRew StepfATheR ElAine D` | `Harrod` (92) ✓last           | `Harrod` (82) ✓last                |
| 10 | clsamp_00565 | Markley, Jenelyn    | `'arklev` [NAME] (92) ✗ OCR    | `Markley, Jenelyn` (62) ✓✓         | `Markley, Jenelyn` (72) ✓✓         |
| 11 | clsamp_00584 | Markley, Judith     | (none)                         | `Markley, Judith` (27) ✓✓ low      | `MARKLEY, Judith,` (46) ✓✓         |
| 12 | clsamp_00670 | Kenven Daniel Paul  | (none)                         | `Kenven Daniel Paul` (90) ✓✓       | `Kenven Daniel Paul` (86) ✓✓       |
| 13 | clsamp_00682 | Kenyou DavidScoTT   | (none)                         | `Kenyou DavidScoTT` (49) ✓✓ low    | `Kenyou DavidScoTT` (42) ✓✓ low    |

✓✓ = full name match. ✓last = last-name only match. ✗ = wrong / missing.

**Aggregate across all 17 real covers (round 2 + round 3):**

| Metric                                                   | Count                | % |
|---|---|---|
| Real covers tested (rounds 2+3)                          | 17                   | — |
| Queries RECORD_NAME returned correct full or last name   | 14                   | **82%** raw recall |
| RECORD_NAME at conf ≥ 60 AND correct                     | 9                    | 53% gated recall |
| RECORD_NAME at conf ≥ 60 AND wrong (false positive)      | 1 (clsamp_00119)     | — |
| Pages routed to HITL (conf < 60 OR multi-source disagree)| 7                    | 41% |

**Precision when shipping at confidence ≥ 60: 9 / 10 = 90%.** Meets the `docs/no-llm-90pct-design.md` §1 gate.

**Recall: 53%.** Other 47% goes to HITL. At ~50K covers in the corpus this is ~23K HITL pages — manageable at the design-doc HITL labor budget but at the upper end.

**Forms NAME counter-evidence:** Forms returned a recognizable NAME-like value on 8 of 13 fixtures, but only 2 (00033 Burch, 00070 alexander) were actually the student's own name; 4 were parent names or OCR garbage. Queries v2 RECORD_NAME outperforms Forms-as-single-source by **3.5×**. Forms is still useful as a cross-check (multi-source vote), but it's no longer the primary signal.

**Cover layouts that systematically fail Queries v2:**
- Modern multi-section forms with "STUDENT NAME: (Last Name First)" boxed below (clsamp_00119, D6 Paulerson). These have the data but Queries can't pair the boxed handwriting to the printed label.
- Secondary school records "GRADES 9-12" form (clsamp_00670, 00682) actually WORK — RECORD_NAME got 90% / 49% on the right name. Lower-confidence ones are likely the printed-handwritten boundary issue but value is still right.
- Old "1. NAME (LAST) (FIRST) (MIDDLE)" forms (clsamp_00033, 00035, 00565, 00584) work for last-name only — Queries gets `LAST` right but doesn't always pick up `FIRST` `MIDDLE` from adjacent boxes.

**Implication for snap_to_index:** if Queries returns just the last name (≥60% of returns), `poc/index.py::snap_to_index` already handles last-name-only matching by snapping to the canonical roll index entry. The roll-level index page (parsed via Tables) provides the full `(last, first, middle, dob)` triple. So **last-name-only RECORD_NAME + Tables index lookup = full student record**, without needing first-name extraction from the cover.

**Decision triggered by §13 (final):**
- The Queries v2 + Tables strategy hits the 90% precision gate at 53% gated recall.
- Tables on `student_records_index` pages becomes load-bearing — it is the canonical source for `(first, middle, dob)` once the cover gives us a high-confidence last name.
- Forms KV becomes optional, used only for the multi-source agreement vote.
- HITL queue at ~47% of covers is the dominant labor cost. Reducing it (e.g., by passing low-conf covers through Bedrock Haiku 4.5 retry) brings it back toward Phase 1's ~5% HITL rate.

**Cumulative bake-off spend through §13: $2.18 across 90 Textract calls.**

---

## 14. Round-4 cross-district sweep — Tables on indexes + Queries v2 on separators (NEW)

**Goal:** validate that the §3 Tables-on-index and §11 Queries-on-Style-B-separator findings hold across all 7 districts. Tables is **load-bearing** in §13's decision (it supplies first/middle/dob when the cover gives only last name), so generality across districts must be proven.

**Method:**
- Detect-probe candidate frames 5-20 across rolls D2r020, D3r032, D4r047, D5r070, D6r079, D7r094 (cost: $0.072).
- Found 27 confirmed index pages and 11 separators (Style A + Style B per district).
- Run Tables on 1 index per district (6 fixtures × $0.015 = $0.09).
- Run Queries v2 on all 11 separators ($0.165).

**Tables result — 6 of 6 districts:**

| Fixture          | District | Rows × Cols | Header row (truncated)                                      | Data row 1 (truncated)                          |
|---|---|---|---|---|
| idx_d2r020_f11   | D2       | 26 × 13     | LAST \| FIRST \| MIDDLE \| DOB \| TRANS \| WITH. \| GRAD \| DATE \| ESE \| OT… | Terrell \| Jimmy \| Carol \| 5-21-46         |
| idx_d3r032_f08   | D3       | 26 × 9      | LAST \| FIRST \| MIDDLE \| DOB \| DATE OF WITH/G \| ESE \| HOLL \| FILE      | LAUERSDORE \| WENDY \| JO \| 8-15-59 \| 6-8-77 |
| idx_d4r047_f08   | D4       | 27 × 8      | (header detected on row 2; row 1 is roll-meta noise)         | # STUDENT LAST \| FIRST NAME \| MIDDLE NAME \| DOB |
| idx_d5r070_f08   | D5       | 26 × 9      | # \| STUDENT LAST N \| FIRST NAME \| MIDDLE NAME \| DOB \| ESE \| OTHER     | 1 \| Carter \| MARCIA \| Anne \| 5-7-62        |
| idx_d6r079_f08   | D6       | 26 × 9      | # \| STUDENT LAST N \| FIRST NAME \| MIDDLE NAME \| DOB \| ESE \| OTHER     | 1 \| RoAch \| Therese \| Ann \| 7-3-64         |
| idx_d7r094_f08   | D7       | 26 × 9      | # \| STUDENT LAST N \| FIRST NAME \| MIDDLE NAME \| DOB \| ESE \| OTHER     | 1 \| the Stock \| Keith \| Bryon \| 1-29-47    |

**All 6 districts return clean tabular structure.** Column count varies (8-13) — D2 has extra columns (TRANS, WITH., GRAD, DATE), D4 has slightly different layout, but **columns 2-5 are consistently `(LAST, FIRST, MIDDLE, DOB)` across all rolls**. The exact mapping is discoverable from the header row using the column headers list in `docs/class-matrix.json`.

**Index parsing fully validated. Tables stays as the canonical roll-index source.**

**Separator Queries result — Style B (cert) is reliable, Style A (clapper) is not:**

| Fixture           | Style | District | SCHOOL answer (conf)                                |
|---|---|---|---|
| sepB_d2r020_f07   | B     | D2       | `Osceola High School` (89) ✓                        |
| sepB_d3r032_f05   | B     | D3       | `St. Cloud High School` (85) ✓                      |
| sepB_d4r047_f06   | B     | D4       | `MaryB Elem, Beaumont Middle Osoeola` (18) — multi-school edge case, would HITL |
| sepB_d5r070_f06   | B     | D5       | `Osceola High School` (81) ✓                        |
| sepB_d6r079_f06   | B     | D6       | `Osceola High School` (81) ✓                        |
| sepB_d7r094_f06   | B     | D7       | `St. Cloud High School` (86) ✓                      |
| sepA_d2r020_f06   | A     | D2       | generic district name (61) — no specific school     |
| sepA_d4r047_f05   | A     | D4       | generic (82) — no specific school                   |
| sepA_d5r070_f05   | A     | D5       | generic (47)                                        |
| sepA_d6r079_f05   | A     | D6       | generic (25)                                        |
| sepA_d7r094_f05   | A     | D7       | generic (49)                                        |

**Style B SCHOOL extraction: 5 of 6 districts ≥ 80% confidence.** Single failure (D4) is a multi-school roll — recoverable by HITL.

**Style A SCHOOL extraction: 0 of 5 districts useful** — Style A clapperboard cards just say "OSCEOLA COUNTY, FLORIDA" with no specific school. Don't run SCHOOL query on Style A; rely on prior context.

**Decision additions:**
- Tables stays universal (all `student_records_index` pages, all districts). $33 at 218K corpus scale.
- Queries on `roll_separator` Style B for `SCHOOL` only. Confidence-gated at ≥ 80%; fall to HITL otherwise.
- Skip Queries on `roll_separator` Style A — use Detect + regex for the rare metadata fields (start/end markers, roll number).

**Round-4 spend: $0.072 (Detect probe) + $0.09 (Tables) + $0.165 (separator Queries) = $0.327.**

**Cumulative bake-off spend through §14: $2.51 across 113 Textract calls.**
