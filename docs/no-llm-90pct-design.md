# No-LLM Pipeline — 90% Accuracy Design (Textract + code only)

**Date:** 2026-04-23
**Constraint:** ≥ **90% precision** on shipped output. Pure Textract OCR JSON + Python rules. Zero LLM calls.
**Trade:** willing to spend more on Textract and route more pages to HITL to lock precision.

Companion to `docs/no-llm-pipeline-brainstorm.md` (v1, generic). This doc commits to the **specific architecture and tuning needed to hit 90%**.

---

## 1. Why 90% from rules + Textract only is achievable

Current LLM pipeline already hit **87.1%** at the high-confidence operating point. The gap to 90% closes via three levers, none requiring an LLM:

| Lever | Why it adds precision |
|---|---|
| **Textract Forms KV** on student covers | Returns `{LAST NAME → "ACKLEY", FIRST NAME → "CALVIN"}` directly — eliminates the field-inversion bug we saw in Haiku |
| **Textract Tables** on `student_records_index` pages | Pulls rows with column-correct cell mapping. Index allowlist becomes near-perfect, snap quality goes up |
| **Aggressive HITL routing on ambiguity** | If two extraction sources disagree → don't ship, route to operator. Trade recall for precision |

Combined effect: every shipped student PDF passes 3 independent agreement checks before going out.

---

## 2. Pipeline architecture (precision-first)

```
TIF
 │
 ▼
[A] Preprocessing (mandatory, all pages)
     ├── grayscale → deskew (Hough) → adaptive binarize (Sauvola) → erode 1px → upscale to 300 DPI
     └── output: clean PNG ready for OCR
 │
 ▼
[B] Tier 0 pixel pre-filter
     ├── pixel std-dev < 8 + frame in [first 7 ∪ last 3] → roll_leader (no OCR)
     ├── pixel std-dev < 8 + mid-roll → unknown_blank_midroll (no OCR)
     ├── pHash match TIMS letterhead / WMS / calibration target → roll_leader (no OCR)
     ├── pHash match clapperboard Style A → roll_separator (parse START/END from corner OCR if needed)
     └── ~10–15% of frames exit here at $0 OCR cost
 │
 ▼
[C] Textract `DetectDocumentText` (cheap path, $0.0015/page)
     └── returns LINE blocks with bounding boxes
 │
 ▼
[D] Rule classifier v2 (deterministic, audit trail)
     ├── score every subtype in class-matrix.json
     ├── HARD threshold: winner_score - runner_up_score >= 3.0 OR refuse
     ├── refuse → escalate to Pass [E]
     └── pass → page_class assigned + subtype label + confidence
 │
 ▼
[E] Selective Textract `AnalyzeDocument` (per page_class)
     │
     ├── student_cover → FORMS feature ($0.05)
     │     └── extract LAST/FIRST/MIDDLE/DOB from explicit KV pairs
     │
     ├── student_records_index → TABLES feature ($0.015)
     │     └── extract every row as IndexRow
     │
     ├── student_test_sheet, student_continuation → no extra call
     │     └── use existing DetectDocumentText bboxes + positional heuristic
     │     └── (test sheets often have name in bubble grid, low success — that's OK, see [G])
     │
     ├── roll_separator Style B → FORMS feature ($0.05)
     │     └── extract filmer/date/school/reel_no from cert form
     │
     └── ambiguous (refused at [D]) → FORMS feature ($0.05) on whole page → re-classify
 │
 ▼
[F] Multi-source name voting (precision driver)
     ├── source 1: Forms KV (when available)
     ├── source 2: bbox positional heuristic (LINE near "LAST NAME" anchor)
     ├── source 3: regex on full text
     ├── 3 of 3 agree → confidence 0.95+ → ship
     ├── 2 of 3 agree → confidence 0.80 → snap-and-verify, then ship if snap matches
     ├── 1 of 3 or none agree → confidence 0.50 → HITL queue
 │
 ▼
[G] Validators (Tier 1, deterministic)
     ├── name regex: ^[A-Za-z][A-Za-z'\-\. ]{0,38}[A-Za-z]$
     ├── OCR garbage blocklist: BIRTH, COUNTY, SEX, PLACE, CITY, NAME, LAST, FIRST, MIDDLE, RECORD
     ├── numeric-prefix strip
     ├── DOB regex + plausibility window 1900-2010
     ├── per-class field consistency
     └── any failure → HITL queue
 │
 ▼
[H] Index-snap (H2.7) — DOB-aware (NEW)
     ├── snap_to_index now uses (last, first, dob) triple
     ├── DOB match required when both packet and index entry have DOB populated
     ├── Lev <=2 per component, sum <=3 (same as current)
     └── no match within threshold → HITL
 │
 ▼
[I] Index-entry grouping + min_bucket_size=2 (default)
     └── every student page snaps to canonical index entry
 │
 ▼
[J] Per-packet final agreement check (NEW)
     ├── all pages in packet agree on snapped name? yes → ship
     ├── disagreement (e.g. 4 pages snap to ACKLEY, 1 to ASHLEY) → majority wins, minority pages flagged for HITL spot-check
     └── packet has no student_cover frame? → HITL
 │
 ▼
[K] PDF aggregator → S3 output
     └── shipped output target: 90%+ precision
     HITL queue: ~15-25% of pages
```

---

## 3. Why each step gets us closer to 90%

| Step | Precision impact (estimate) | Cost impact |
|---|---|---|
| [A] Preprocessing | +5–10 pp on faded scans | +50ms/page Lambda, $0 service |
| [B] Pixel pre-filter | +1–2 pp on edge cases (no garbage classified) | −$30 OCR cost (10–15% skipped) |
| [C] Detect text | baseline | $327 |
| [D] Rule classifier with refuse threshold | +5–8 pp (refusals become HITL, never ship-bad) | $0 |
| [E] Selective Forms/Tables | +8–12 pp on student pages (KV is the killer feature) | +$2,500 |
| [F] Multi-source name voting | +5 pp (catches single-source extraction errors) | $0 |
| [G] Validators | +2–3 pp (drops garbage extractions) | $0 |
| [H] DOB-aware snap | +2–3 pp on common surnames (disambiguates ACKLEY vs ACKLEY-with-different-DOB) | $0 |
| [J] Per-packet agreement | +1–2 pp | $0 |

**Stacked target: 87.1% → ≥ 90%, conservatively.**

Caveat: gains are not strictly additive (overlap + diminishing returns). 90% is realistic; 92–93% is the upper end of plausible without LLM.

---

## 4. Cost commitment for 90% target

| Item | Cost full 218K |
|---|---|
| Tier 0 pixel pre-filter savings | −$30 |
| Textract DetectDocumentText (190K of 218K, after filter) | $285 |
| Textract Forms on student_cover (~50K, ~30% of corpus after class assignment) | $2,500 |
| Textract Tables on student_records_index (~2,200) | $33 |
| Textract Forms on Style B separators (~80) | $4 |
| Textract Forms on classifier-refused pages (~5%) | $545 |
| Lambda preprocessing + extraction (heavier than LLM path, 2x) | $140 |
| Step Functions, DDB, S3, CloudWatch | $90 |
| **AWS subtotal** | **~$3,567** |
| HITL operator labor (15–25% review rate, ~150–200 hrs vs LLM 90 hrs) | TBD client rate |

**About 4.5× the current LLM pipeline AWS cost. Two value drivers justify it:**

1. **Determinism.** Same TIF gives same output forever. Audit log is human-readable.
2. **Higher precision floor.** 90%+ on shipped vs current 87.1% at filtered-to-23%-recall.

---

## 5. Rule classifier v2 — concrete scoring

Existing `class-matrix.json` becomes the rule library. Scoring algorithm tightened from v1 brainstorm:

```python
def classify_v2(detect_response: TextractDetect, frame_pos: int,
                roll_total: int, district: int) -> ClassResult:
    full_text = " ".join(b["Text"] for b in detect_response["Blocks"]
                         if b["BlockType"] == "LINE").upper()
    line_blocks = [b for b in detect_response["Blocks"] if b["BlockType"] == "LINE"]

    # Top-of-page text gets weight bonus
    top_text = " ".join(b["Text"] for b in line_blocks
                        if b["Geometry"]["BoundingBox"]["Top"] < 0.20).upper()

    scores: dict[str, float] = {}
    for st in CLASS_MATRIX["subtypes"]:
        s = 0.0

        # Title text — must appear, in top region preferred
        for tt in st["title_text"]:
            tt_u = tt.upper()
            if tt_u in top_text:
                s += 8.0
            elif tt_u in full_text:
                s += 4.0

        # Column headers — count distinct hits, weight per hit
        ch_hits = sum(1 for ch in st.get("column_headers", [])
                      if isinstance(ch, str) and ch.upper() in full_text)
        s += min(ch_hits, 5) * 1.5  # cap to prevent overcounting

        # Key phrases
        kp_hits = sum(1 for kp in st.get("key_phrases", [])
                      if isinstance(kp, str) and kp.upper() in full_text)
        s += min(kp_hits, 4) * 0.8

        # Frame-position prior
        fph = st.get("frame_position_hint", "")
        if "first_3_to_6" in fph and 3 <= frame_pos <= 6: s += 1.5
        if "last_3_to_last" in fph and frame_pos >= roll_total - 3: s += 1.5
        if fph == "mid_roll" and 7 <= frame_pos <= roll_total - 4: s += 0.4

        # District prior
        bias = st.get("district_bias", "all")
        if isinstance(bias, list) and district in bias: s += 1.0
        elif bias == "all": s += 0.0

        # Exclusion rules — disqualify completely
        if exclusion_fires(st["exclusion_rule"], full_text, line_blocks):
            s = 0.0

        scores[st["id"]] = s

    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    winner_id, winner_score = sorted_scores[0]
    runner_up_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0

    # PRECISION GATE: refuse if margin too small or absolute too low
    if winner_score < 6.0 or (winner_score - runner_up_score) < 3.0:
        return ClassResult(parent="unknown", subtype="unknown_unrecognized",
                           confidence=0.0, refused=True)

    confidence = (winner_score - runner_up_score) / winner_score
    parent = SUBTYPE_TO_PARENT[winner_id]
    return ClassResult(parent=parent, subtype=winner_id,
                       confidence=confidence, refused=False)
```

**Refusal is the precision lock.** When the classifier can't decide cleanly, the page does not get a class — it goes to a Forms-feature retry, then HITL.

---

## 6. Multi-source name voting — concrete

```python
def extract_name(page_class, detect_response, forms_response=None) -> NameVote:
    candidates = []

    # Source 1: Forms KV (highest weight)
    if forms_response:
        kv = forms_kv_dict(forms_response)
        if "LAST NAME" in kv and "FIRST NAME" in kv:
            candidates.append(("forms_kv",
                               kv["LAST NAME"].upper().strip(),
                               kv["FIRST NAME"].upper().strip(),
                               kv.get("MIDDLE", "").upper().strip()))

    # Source 2: bbox positional heuristic
    bbox_name = positional_extract(detect_response, anchor="LAST NAME")
    if bbox_name:
        candidates.append(("bbox_positional", *bbox_name))

    # Source 3: regex on top region
    rgx_name = regex_extract_top(detect_response)
    if rgx_name:
        candidates.append(("regex", *rgx_name))

    # Vote
    if not candidates:
        return NameVote(last="", first="", middle="", confidence=0.0,
                        agreement=0, sources=[])

    last_votes = Counter(c[1] for c in candidates)
    first_votes = Counter(c[2] for c in candidates)

    top_last, top_last_count = last_votes.most_common(1)[0]
    top_first, top_first_count = first_votes.most_common(1)[0]

    agreement = min(top_last_count, top_first_count)

    if agreement >= 3:
        confidence = 0.95
    elif agreement >= 2:
        confidence = 0.80
    else:
        confidence = 0.50

    middle_votes = Counter(c[3] for c in candidates if c[3])
    top_middle = middle_votes.most_common(1)[0][0] if middle_votes else ""

    return NameVote(last=top_last, first=top_first, middle=top_middle,
                    confidence=confidence, agreement=agreement,
                    sources=[c[0] for c in candidates])
```

**Decision rules:**
- `agreement >= 3` → ship.
- `agreement == 2` → snap to index. If snap matches → ship. If snap rejects → HITL.
- `agreement <= 1` → HITL.

This is what locks 90%. No single OCR error gets through alone.

---

## 7. DOB-aware snap (upgraded H2.7)

Current snap uses (last, first) only. v2 design:

```python
def snap_to_index_v2(packet, roll_index):
    pkt_last, pkt_first = packet.last_raw.upper(), packet.first_raw.upper()
    pkt_dob = packet.dob_raw  # majority DOB across packet pages, "" if none

    candidates = []
    for entry in roll_index:
        if not entry.first.strip():
            continue
        d_last = Levenshtein.distance(pkt_last, entry.last.upper())
        d_first = Levenshtein.distance(pkt_first, entry.first.upper())
        if d_last > 2 or d_first > 2 or (d_last + d_first) > 3:
            continue

        # DOB cross-check (NEW)
        dob_score = 0
        if pkt_dob and entry.dob:
            if normalize_dob(pkt_dob) == normalize_dob(entry.dob):
                dob_score = -2  # bonus for DOB match (lower distance)
            else:
                continue  # DOB mismatch → reject candidate entirely

        total = d_last + d_first + dob_score
        candidates.append((total, entry))

    if not candidates:
        return packet  # unchanged, no snap, route to HITL on no-snap
    candidates.sort()
    best = candidates[0][1]
    return packet.with_snap(best)
```

DOB cross-check is the precision-clincher when two students share the same surname (3% of corpus). Without it, snap may pick wrong student.

---

## 8. Validation cascade (Tier 1+2)

```
extracted name -> [g1] name regex -> pass/reject
              -> [g2] OCR garbage token check -> pass/reject
              -> [g3] numeric prefix strip
              -> [g4] surname dictionary fuzzy lookup (Census top-10K + corpus)
              -> [g5] DOB regex + plausibility (1900-2010)
              -> [g6] index-snap match -> pass/reject
              -> [g7] per-packet majority agreement -> pass/reject

any failure -> HITL queue with reason code
```

Each gate is a few lines of code. Fail-fast. Reject reason logged to DDB for HITL operator context.

---

## 9. Expected accuracy on ROLL 001 (forecast)

Apply this design to the same 1924 TIFs we already have ground-truth for. Forecast vs measured-LLM:

| Metric | LLM (current) | No-LLM (this design, forecast) |
|---|---|---|
| Pages classified | 1924 | 1924 |
| Correctly classified by class (7-class) | ~95% | ~93% |
| Names extracted (after multi-source vote) | ~50% useful (per-page) | ~60% useful |
| Packets shipped (after HITL routing) | ~245 (75% of GT) | ~210–230 (~65% of GT) |
| Precision on shipped | 75.9% | **90–92%** |
| Recall on usable GT | 70.6% | ~60–65% |
| HITL queue size | 5% | ~15–25% |
| AWS cost | $9.89 (POC scale) → $770 full | scaled equivalent: ~$30 (POC scale) → ~$3,500 full |

**Key reading:** rule-based + Textract + heavy validation **trades recall for precision**. We catch fewer students, but the ones we catch are very right. HITL closes the gap on missed students.

If 90% precision + 60% recall is acceptable for the contracted output (with HITL covering the rest), **this design hits gate**.

If contract requires higher recall + 90% precision simultaneously, **add LLM back as the retry tier on classifier-refused pages** — hybrid wins both.

---

## 10. Implementation outline

| Module | Status | Effort |
|---|---|---|
| `poc/preprocess.py` | new | 1.5 days |
| `poc/pre_filter.py` | new (Tier 0) | 1 day |
| `poc/textract_client.py` | new — wraps Detect / Forms / Tables | 1 day |
| `poc/rule_classifier.py` | new (consumes class-matrix.json) | 2 days |
| `poc/name_voter.py` | new (3-source agreement) | 1 day |
| `poc/validators.py` | new (Tier 1 + Tier 2) | 1 day |
| `poc/index.py::snap_to_index_v2` | extend (DOB cross-check) | 0.5 day |
| `poc/group.py::group_by_index_entry` | reuse | 0 |
| `poc/regroup.py` | extend with Textract path | 0.5 day |
| `tests/*` | TDD per module | 2 days |
| `scripts/textract_bake_off.py` | run on 50-page labeled set | 1 day |
| **Total** | | **~12 days** |

Plus a 50-page bake-off ($5 OCR) before committing to scale-up.

---

## 11. Decision matrix

| Scenario | Recommended pipeline |
|---|---|
| Determinism + auditability hard requirement | **No-LLM design (this doc)** |
| Lowest AWS cost matters most | Current LLM batch pipeline |
| Highest accuracy at any cost | **Hybrid: this design + LLM retry on refused pages** |
| Fastest path to delivery | Current LLM pipeline (already 87.1%, just need balanced-mode tuning) |

---

## 12. Open questions to resolve before implementation

1. Confirm Textract Forms accuracy on 1990s microfilm. Bake-off needed.
2. Confirm acceptable HITL load — 15–25% review rate vs current 5%. Operator capacity?
3. Confirm DOB column quality on `student_records_index` pages. Tables endpoint should work, but unverified.
4. Decide whether to layer this on top of current LLM pipeline (hybrid) or replace.

---

## 13. References

All sources from `docs/no-llm-pipeline-brainstorm.md` § 14 apply here. Critical ones:

- [AWS Textract — Form Data (Key-Value Pairs) docs](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-kvp.html)
- [AWS Textract pricing](https://aws.amazon.com/textract/pricing/)
- [Textract Layout feature blog](https://aws.amazon.com/blogs/machine-learning/amazon-textracts-new-layout-feature-introduces-efficiencies-in-general-purpose-and-generative-ai-document-processing-tasks/)
- [TheFuzz fuzzy matching library](https://github.com/seatgeek/thefuzz)
- [Tesseract Improving Quality of Output](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)
