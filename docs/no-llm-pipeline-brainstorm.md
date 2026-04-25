# No-LLM Pipeline — Deep Brainstorm

**Date:** 2026-04-23
**Premise:** rebuild the entire 218K-TIF pipeline using OCR + deterministic rules + JSON validation only. Zero Bedrock / LLM / vision-AI calls. All classification, name extraction, and grouping done with explicit code and lookup tables.
**Status:** brainstorm only — not a commitment to swap. Compares against current LLM-based pipeline.

---

## 0. Why consider this

Reasons to drop the LLM:

- **Determinism:** same input → same output forever, regardless of model version.
- **Cost predictability:** $/page locked at OCR provider's rate; no token math.
- **No vendor lock-in to one model.** Class rules live in `docs/class-matrix.json`; OCR provider is swappable.
- **No prompt brittleness.** No prompt iteration loops, no field-inversion failures.
- **Audit clarity:** every classification + extraction has a visible rule trace, easier for HITL operator + FERPA review.

Reasons against (must be balanced):

- 1991–92 microfilm scans are the worst-case for OCR. Old toner bleed, skew, varying contrast.
- Rule libraries grow over time as new edge cases appear. Maintenance cost shifts from prompt-tuning to rule authoring.
- Hand-written name fields (test sheets) are still hard for OCR alone — possibly worse than vision LLM.

---

## 1. Pipeline shape (no-LLM)

```
TIF (microfilm scan, 1990s)
    │
    ▼
[1] Image preprocessing
    │   deskew / binarize / denoise / upscale-to-300dpi / deinterlace
    │
    ▼
[2] Pre-filter (Tier 0, deterministic)
    │   - pixel std-dev < 8 → roll_leader / unknown_blank_midroll
    │   - pHash vs known templates (TIMS letterhead, WMS letterhead, calibration target,
    │     Style A clapperboard, Style B certificate)
    │   - frame-position prior (separators only valid in first 10 / last 5)
    │   if matched → emit class directly, skip OCR
    │
    ▼
[3] OCR (Amazon Textract DetectDocumentText + AnalyzeDocument {FORMS, TABLES, LAYOUT})
    │   raw text + bounding boxes + key-value pairs + table cells
    │
    ▼
[4] Text-based classifier
    │   - token-set extraction from full-page text
    │   - keyword scoring against class-matrix.json title_text + key_phrases + column_headers
    │   - layout features: dense table rows? bubble grid? handwritten ratio?
    │   - position weighting: top-of-page text scores higher
    │   - winner = subtype with max score above threshold
    │   → page_class assigned (one of 7) + subtype label
    │
    ▼
[5] Field extractor (per page_class)
    │
    │   student_cover / student_test_sheet / student_continuation:
    │     - locate `LAST NAME`/`FIRST NAME`/`MIDDLE` key-value pairs from Textract FORMS
    │     - fallback: regex on text near top-left of page
    │     - DOB regex: \d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}
    │     - school: nearest text below "School:" key
    │
    │   student_records_index:
    │     - Textract TABLES output → list of rows, columns
    │     - column-header detection: find row containing "LAST" + "FIRST" + "MIDDLE"
    │     - per data row: extract last/first/middle/dob from matched columns
    │
    │   roll_separator:
    │     - regex for `START` / `END` in large text region
    │     - regex for `ROLL NO\.\s*\d+` / `Reel\s+No\.\s*\d+`
    │     - filmer / date / school from key-value pairs (Style B only)
    │
    │   roll_leader:
    │     - if vendor letterhead text → roll_meta.filming_vendor
    │     - if certification card text → filmer/date/school/reel from key-value pairs
    │
    ▼
[6] Validators (Tier 1, deterministic)
    │   - name regex: ^[A-Za-z][A-Za-z'\-\. ]{0,38}[A-Za-z]$
    │   - OCR garbage blocklist: BIRTH, COUNTY, SEX, PLACE, CITY, NAME, LAST, FIRST, MIDDLE, RECORD
    │   - numeric-prefix strip
    │   - DOB plausibility window (e.g. 1900–2010)
    │   - per-class consistency: separator marker ∈ {START, END}; index row count ≥ 5
    │   any failure → flag for HITL or downgrade class
    │
    ▼
[7] Index aggregator + snap
    │   - dedupe rows on (last, first, dob)
    │   - per packet: snap raw extracted name to nearest index entry, Lev ≤ 2/2/3
    │   - swap-tolerant scoring (last/first columns sometimes inverted)
    │
    ▼
[8] Grouping (index-entry mode, same as current pipeline)
    │
    ▼
[9] PDF aggregator → S3 output
```

Phase 4 infra wrapping (Step Functions + Lambda + DDB + S3) stays identical to the LLM design — only the per-page worker changes.

---

## 2. OCR provider trade-off

Three serious candidates plus a self-hosted option.

| Provider | Per-page cost | TIFF native? | Forms KV | Tables | Strength on old/skewed scans |
|---|---|---|---|---|---|
| **Amazon Textract** | $0.0015 (text) / $0.05 (forms) / $0.015 (tables) / $0.065 combined | **Yes**, multipage TIFF supported since Oct 2021 | Yes (`AnalyzeDocument FORMS`) | Yes | Mid — better on modern scans, weaker on 1990s |
| **Azure Document Intelligence** | $1.50 per 1K basic / $10 per 1K layout | Yes | Yes (custom models trainable in 30 min) | Yes | **Best** of cloud OCRs on irregular / older docs |
| **Google Document AI** | similar to Azure (~$10 per 1K) | Yes | Yes | Yes | Strong, slight edge over Azure on multilingual |
| **Tesseract 5 (OSS)** | $0 software cost — pay only Lambda compute | Yes | No native KV (use layout heuristics) | No native (use cell-detection lib) | Acceptable after heavy preprocessing; needs 300+ DPI, deskew, binarization, erosion for ink bleed |

**Pricing math at 218K scale:**

- Textract `DetectDocumentText` only: 218K × $0.0015 = **$327**
- Textract `AnalyzeDocument FORMS+TABLES`: 218K × $0.065 = **$14,170** ← prohibitive
- Textract `AnalyzeDocument FORMS` only: 218K × $0.05 = **$10,900** ← still high
- Azure Document Intelligence layout: 218K × $0.01 = **$2,180**
- Tesseract on Lambda: ~218K × $0.0001 (Lambda time) = **~$22** + dev/maintenance time

**Decision driver:** Forms + Tables endpoint costs ~$14K — kills the Textract option for full Forms extraction.

**Realistic stack:**

- **Textract `DetectDocumentText`** ($327) for raw text on every page.
- Use the bounding-box geometry from text response to do our own form-field localization in code.
- Reserve Textract `AnalyzeDocument` (Forms+Tables) for the ~5% of pages that the rule-based classifier flags as ambiguous, costing 218K × 0.05 × 0.065 ≈ **$700** added.
- Azure Document Intelligence kept as a fallback option for re-running known-bad rolls.

**Total OCR budget for full corpus:** ~$1K — comparable to current LLM bulk projection ($770).

---

## 3. Image preprocessing pipeline

1990s microfilm is the worst case. OCR engines need 300+ DPI clean grayscale to perform. Recommended cascade:

| Step | Library | Purpose |
|---|---|---|
| **DPI normalization** | Pillow `resize` + `dpi` flag | Ensure ≥300 DPI; many TIFs report 200 or unset DPI |
| **Grayscale convert** | Pillow `convert("L")` | Drop color noise |
| **Deskew** | OpenCV Hough + `getRotationMatrix2D` | Rotate pages back to horizontal text. Even small skew kills line-segmentation |
| **Binarize** | OpenCV Otsu's threshold OR Sauvola adaptive | Black/white separation. Adaptive is better for bleed-through |
| **Despeckle / denoise** | OpenCV `fastNlMeansDenoising` | Remove film-scratch noise |
| **Erosion** | OpenCV morphology `erode` 1px | Compensate for ink bleed (common on 1990s xerography) |
| **Cropping / margin trim** | Pillow `getbbox` + buffer | Strip black borders left by microfilm scanner |
| **Optional rotation correction** | Tesseract `--psm 0` orientation detection | Auto-rotate 90/180/270° if needed |

All preprocessing runs as a Lambda step before OCR. Preserves source TIF; outputs a normalized PNG/TIF for OCR. Adds ~50ms/page on Lambda.

**Library shortlist:** Pillow (already in pipeline), OpenCV-Python (cv2), `scikit-image` for Sauvola binarization. None require GPU.

---

## 4. Rule-based classifier — using `docs/class-matrix.json`

Already-built artifact: `docs/class-matrix.json` contains 32 subtypes × 13 feature dimensions. Each has `title_text`, `column_headers`, `key_phrases`, `exclusion_rule`. Treat this file as a programmable rule library.

Algorithm:

```python
def classify(text: str, layout: TextractLayout, frame_pos: int,
             roll_total: int, district: int) -> tuple[str, float, str]:
    """
    Returns (parent_class, confidence, subtype_id).
    """
    upper = text.upper()
    scores: dict[str, float] = {}  # subtype_id -> score

    for subtype in load("docs/class-matrix.json")["subtypes"]:
        score = 0.0

        # 1. Title-text bonus
        for tt in subtype["title_text"]:
            if tt.upper() in upper:
                score += 5.0

        # 2. Column-header bonus
        for ch in subtype.get("column_headers", []):
            if isinstance(ch, str) and ch.upper() in upper:
                score += 1.5

        # 3. Key-phrase bonus
        for kp in subtype.get("key_phrases", []):
            if isinstance(kp, str) and kp.upper() in upper:
                score += 0.8

        # 4. Frame-position prior
        if "first_3_to_6" in subtype.get("frame_position_hint", "") and 3 <= frame_pos <= 6:
            score += 1.0
        if "last_3_to_last" in subtype.get("frame_position_hint", "") and frame_pos >= roll_total - 3:
            score += 1.0
        if subtype.get("frame_position_hint") == "mid_roll" and 7 <= frame_pos <= roll_total - 4:
            score += 0.3

        # 5. District prior
        bias = subtype.get("district_bias", "all")
        if isinstance(bias, list) and district in bias:
            score += 0.8

        # 6. Exclusion rule (negative)
        if exclusion_fires(subtype["exclusion_rule"], text, layout):
            score = 0  # disqualify

        scores[subtype["id"]] = score

    if not scores or max(scores.values()) < 3.0:
        return ("unknown", 0.0, "unknown_unrecognized")

    winner = max(scores, key=scores.get)
    raw = scores[winner]
    runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    confidence = (raw - runner_up) / raw if raw else 0
    parent = next(s["parent"] for s in matrix if s["id"] == winner)
    return (parent, confidence, winner)
```

**Properties:**

- Deterministic. Same text → same class.
- Auditable. Every score has a rule trace.
- Confidence = (winner_score − runner_up_score) / winner_score. Ambiguous pages flagged for HITL.
- Tunable: weights live in code, not in a model.

**Expected accuracy (rule-of-thumb):**

- High-text-content pages (cover, continuation, index, certificate separator): 85–95% — title text alone is decisive.
- Low-text pages (clapperboard separator, calibration target, blank): 90–99% via pHash before OCR even runs.
- Bubble-sheet test pages: 60–80% — depends on whether form title prints at top.

---

## 5. Name extraction — three layered strategies

### 5a. Textract Forms key-value (when affordable)

If we accept paying $0.05/page Forms cost on student_* pages only (estimated 70% of corpus = 153K pages × $0.05 = **$7,650**), Textract returns `{LAST NAME: "...", FIRST NAME: "..."}` directly. Cleanest extraction.

### 5b. Geometric heuristics on DetectDocumentText output

Cheaper. Use the bounding boxes from cheap text-detect to find the name field manually:

1. Find LINE blocks containing exactly "LAST NAME", "LAST", "Last:" (case-insensitive).
2. Find adjacent LINE block to the right (same `top` ± 10px, `left` > anchor's `left+width`).
3. That neighbor's text = `last`. Repeat for `FIRST` and `MIDDLE`.
4. If layout differs (e.g. names stacked vertically): fall back to "first non-anchor text in top-left quadrant".

Works because every form in `class-matrix.json` puts the name field consistently relative to its label.

### 5c. Regex on full text

Last resort. Patterns per subtype, e.g. for cum_guidance_1_12:

```python
# matches "ACKLEY, CALVIN CHARLES" or "Ackley, Calvin Charles" near top
r"^([A-Z][A-Z'\- ]+),\s+([A-Z][a-zA-Z'\- ]+)(?:\s+([A-Z][a-zA-Z'\-]+))?"
```

Per-subtype regex bank lives next to class-matrix.json.

**Recommended: tier all three.** Try 5b first. If extracted name fails name-regex validator, escalate to 5a. If still bad, escalate to 5c. If still bad, route to HITL.

---

## 6. Index-page parsing — Textract Tables

`AnalyzeDocument` with `TABLES` feature is the obvious tool for `student_records_index` pages. Cost: $0.015 × ~25 index pages/roll × 100 rolls = **$37.50 for full corpus**.

Output structure:

```
TABLE block
├── ROW 0
│   ├── CELL "LAST"
│   ├── CELL "FIRST"
│   ├── CELL "MIDDLE"
│   └── CELL "DOB"
├── ROW 1
│   ├── CELL "ACKLEY"
│   ├── CELL "CALVIN"
│   ├── CELL "CHARLES"
│   └── CELL "5/12/74"
└── ...
```

Algorithm:

1. Identify header row (first row containing 2+ of {LAST, FIRST, MIDDLE, DOB}).
2. Map column index → field name.
3. Iterate data rows, extract `(last, first, middle, dob, source_frame)`.
4. Apply same drop-reasons as `gt_clean.py`: placeholder, ocr_garbage, numeric_only, too_short.
5. Dedupe on (last, first, dob).

This is simpler than the LLM index extraction and likely **more accurate** because Textract's table model is purpose-built for this layout.

---

## 7. Snap + grouping — unchanged

The current `poc/index.py` `snap_to_index()` and `poc/group.py` `group_by_index_entry()` work on plain Python data structures. They are agnostic to whether the per-page extraction came from an LLM or OCR. **Drop-in replaceable**, no changes needed.

---

## 8. Validation layer — already designed

`docs/class-heuristics.md` lists Tier 1 validators. None require an LLM. Existing implementation plan (Phase 2 spec) covers:

- Name regex
- OCR garbage blocklist
- Numeric-prefix strip
- DOB regex + plausibility window
- Per-class field consistency
- Empty-field downgrade
- Duplicate START/END collapse

All apply to OCR output identically to LLM output.

---

## 9. Cost comparison (full 218K)

| Line item | Current LLM pipeline | No-LLM pipeline (Textract Detect + selective Forms/Tables) | No-LLM (Tesseract on Lambda) |
|---|---|---|---|
| OCR / extraction | Bedrock Haiku Batch ~$560 | Textract DetectDocumentText: $327 + selective Forms ~$700 + Tables $38 = **$1,065** | Tesseract: ~$22 |
| Sonnet retry | $150 | n/a (rule-based, but ambiguous-page Forms call substitutes) | n/a |
| Tier 0 pre-filter savings | −$75 | −$75 | −$75 |
| Lambda + Step Functions | $70 | $70 (heavier preprocessing on Lambda) → $100 | $200 (Tesseract is CPU-heavy) |
| DDB + S3 + CloudWatch | $55 | $55 | $55 |
| **AWS total** | **~$770** | **~$1,165** | **~$200** |
| HITL labor | ~90 hrs | 90 hrs (similar review rate expected) | likely **higher** review rate (worse OCR accuracy on hard pages) |
| Maintenance cost | Prompt iteration when model behavior shifts | Rule-library upkeep + per-district class quirks | Rule-library + heavy preprocessing tuning |

**Surprise:** Tesseract is ~4× cheaper but the HITL labor delta probably eats the savings. Textract path costs ~50% more than LLM path on AWS but eliminates LLM lock-in.

---

## 10. Accuracy comparison (estimate)

We have measured numbers for current LLM. No-LLM numbers are inferred from public benchmarks on similar materials.

| Pipeline | Precision | Recall | Notes |
|---|---|---|---|
| LLM (current, min_bucket=1) | 75.9% | 70.6% | Measured on ROLL 001 |
| LLM (current, min_bucket=3) | 87.1% | 23.3% | Gate met at high precision |
| Textract Detect-only + rules | ~70% est | ~70% est | OCR text quality + rule classifier — cover/index pages do well, test sheets weak |
| Textract Forms+Tables (full) | ~85% est | ~80% est | Forms KV directly returns structured fields; tables for index near-perfect |
| Tesseract + heavy preprocessing | ~55–65% est | ~60% est | OCR quality drops on faded scans, hand-written, low contrast |

Caveat: Azure Document Intelligence likely beats Textract on this corpus (per benchmark on irregular/older invoices). Worth a 50-page pilot if seriously considering this path.

---

## 11. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OCR fails on faded 1990s scans | High | High | Heavy preprocessing pipeline; fall back to Forms API on flagged pages |
| Hand-written name fields (test sheets) unreadable | Very high | Medium | Inherit name from previous page in packet (already in plan); HITL for residual |
| Rule library bloats as district variants surface | Medium | Medium | Treat `class-matrix.json` as living spec; version it |
| Field-positional heuristics fail when form layout shifts | Medium | High | Keep Forms API as escape hatch on positional-heuristic failure |
| Text-detect bounding boxes off by 5–10px | Low | Low | Tolerance windows in name-extraction code |
| Old scans need 300+ DPI but source is 200 DPI | High | Medium | Upscale + sharpen in preprocessing — partial recovery |

---

## 12. Hybrid recommendation

Pure no-LLM is feasible but probably ~5–10 pp lower precision than current best. **Hybrid wins both ways:**

1. **Tier 0 pixel** (already designed) — pHash + blank detector. Skips OCR entirely on ~10% of frames.
2. **Textract DetectDocumentText** — cheap text + bounding boxes on every other frame.
3. **Rule-based classifier** — `class-matrix.json` scoring decides class.
4. **Field extraction:**
   - Textract bbox-positional heuristic for name fields.
   - On positional fail or low classifier confidence: Textract Forms+Tables on that single page.
5. **Validators** — Tier 1 (Tier 1 already designed).
6. **Snap + group** — index-entry mode (no change).
7. **HITL** — for residual.

Estimated cost on full 218K: **~$900–$1,000 AWS** (Textract Detect $327 + selective Forms $400–500 + Tables $38 + Lambda $100 + DDB/S3 $55).

Estimated precision: **80–88%** balanced; **>90%** in high-precision filtered mode.

**Most valuable property of this approach:** every classification has an audit trail. Operators can see exactly why a page got a class, which makes FERPA review and stakeholder buy-in far easier than "the AI thought so".

---

## 13. Action items if pursuing

1. **50-page bake-off** on a labeled mix from ROLL 001:
   - Run Textract DetectDocumentText
   - Run Tesseract 5 with full preprocessing
   - Run Azure Document Intelligence layout endpoint
   - Compare extracted-text accuracy + class-rule confidence
   - Estimated cost: ~$5
2. **Build rule-engine prototype** (`poc/rule_classifier.py`) consuming `class-matrix.json` and a Textract response JSON. ~2 days.
3. **Compare prototype output** against current LLM output on the same 1924-frame ROLL 001 pages.jsonl. Use `poc/regroup.py` to evaluate downstream impact.
4. **Decide on hybrid vs replace** based on bake-off + prototype numbers.

Net engineering cost to evaluate: **~3 days + $5 OCR**. Outcome unblocks a $200–$300 AWS-cost-delta decision and a determinism / audit-trail vs accuracy tradeoff.

---

## 14. References

OCR providers + capabilities:
- [AWS Textract — TIFF support announcement](https://aws.amazon.com/about-aws/whats-new/2021/10/amazon-textract-tiff-asynchronous-receipts-invoices/)
- [AWS Textract pricing](https://aws.amazon.com/textract/pricing/)
- [AWS Textract — Form Data (Key-Value Pairs) docs](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-kvp.html)
- [AWS Textract — Layout feature blog](https://aws.amazon.com/blogs/machine-learning/amazon-textracts-new-layout-feature-introduces-efficiencies-in-general-purpose-and-generative-ai-document-processing-tasks/)
- [Azure Document Intelligence vs AWS Textract vs Google Document AI 2026](https://aiproductivity.ai/blog/best-ocr-tools-2026/)
- [Comparison of AI OCR Tools 2026](https://persumi.com/c/product-builders/u/fredwu/p/comparison-of-ai-ocr-tools-microsoft-azure-ai-document-intelligence-google-cloud-document-ai-aws-textract-and-others)

OCR preprocessing:
- [Tesseract Improving Quality of Output (official)](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)
- [7 steps of image preprocessing for OCR (Python)](https://nextgeninvent.com/blogs/7-steps-of-image-pre-processing-to-improve-ocr-using-python-2/)
- [Survey on Image Preprocessing Techniques to Improve OCR Accuracy](https://medium.com/technovators/survey-on-image-preprocessing-techniques-to-improve-ocr-accuracy-616ddb931b76)

Rule-based document classification:
- [Document Classification Without AI — deterministic pipeline (2026)](https://www.textcontrol.com/blog/2026/04/23/document-classification-without-ai-deterministic-explainable-built-for-production-in-csharp-dot-net/)
- [AltexSoft — Document Classification With Machine Learning vs rules](https://www.altexsoft.com/blog/document-classification/)
- [Docsumo — Understanding Document Classification](https://www.docsumo.com/blogs/ocr/document-classification)

Fuzzy matching:
- [DataCamp — Fuzzy String Matching in Python Tutorial](https://www.datacamp.com/tutorial/fuzzy-string-python)
- [TheFuzz (formerly FuzzyWuzzy) — GitHub](https://github.com/seatgeek/thefuzz)

Sources:
- [Best Practices — Amazon Textract](https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html)
- [AnalyzeDocument — Amazon Textract](https://docs.aws.amazon.com/textract/latest/dg/API_AnalyzeDocument.html)
- [Textract Document Layout response objects](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-document-layout.html)
- [Boost Tesseract OCR Accuracy](https://sparkco.ai/blog/boost-tesseract-ocr-accuracy-advanced-tips-techniques)
- [AWS Textract vs Google, Azure, GPT-4o invoice benchmark](https://www.businesswaretech.com/blog/research-best-ai-services-for-automatic-invoice-processing)
- [Top 6 OCR Models 2025/2026 comparison](https://www.marktechpost.com/2025/11/02/comparing-the-top-6-ocr-optical-character-recognition-models-systems-in-2025/)
