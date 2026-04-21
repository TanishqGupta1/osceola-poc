# Heuristic Patterns — Osceola Pipeline Quality Boosters

**Date:** 2026-04-20
**Status:** brainstorm — feeds into `docs/superpowers/specs/2026-04-20-osceola-arch-redesign.md` (pending)
**Purpose:** enumerate deterministic heuristics and cross-signal validators that raise accuracy, cut LLM cost, and enforce structural invariants across the 218,577-TIF pipeline.

The goal is to build defense in depth. The LLM is one signal; structural rules, pixel heuristics, corpus lookups, and prompt priors are additional signals. Any single signal failing should not cause a wrong student PDF to ship.

---

## Tier 0 — Pre-LLM pixel heuristics

Deterministic checks that run before any Bedrock call. Match → skip LLM entirely, label the frame directly. Pure pixel/hash math, cost ~$0.

| ID | Heuristic | Rule | Expected coverage | Notes |
|---|---|---|---|---|
| H0.1 | **Blank-frame detector** | Pillow pixel std-dev < 8 → `roll_leader` (or `unknown` mid-roll) | 2–5% of frames | Zero false positives on ink-heavy student pages. |
| H0.2 | **Resolution-target pHash** | Perceptual hash against canonical microfilm calibration chart. Hamming ≤5 → `roll_leader` | ~1 frame / roll (~100 total) | Chart is identical byte-for-byte in most rolls. |
| H0.3 | **Vendor letterhead pHash** | pHash against 2 known letterheads (Total Information Management Systems + White's Microfilm Services) | ~1–2 / roll (~200 total) | Build exemplar library from `samples/boundary_probe/`. |
| H0.4 | **Style A clapperboard pixel detector** | Hough-line detection for two diagonal-hatched rectangles. Match → `roll_separator` + parse `START`/`END` from text block | ~100 frames (2 per Style-A roll) | Districts 2/4/5/6/7. Style B falls through to LLM. |
| H0.5 | **Orientation normalization** | H/W aspect ratio + quick OCR-confidence probe on 4 rotations. Rotate before passing to LLM | All frames; lifts LLM accuracy on the ~0.5% rotated | Observed at least one 90°-rotated END card (d7r099). |

**Coverage total:** ~5–10% of 218K = 10K–22K frames pre-classified for free.
**Cost savings:** ~$50–100 on the primary model, plus lower tail latency.
**Main win:** deterministic correctness on the trivially-solvable cases — LLM never sees them, so LLM can't be wrong about them.

---

## Tier 1 — Post-LLM format validation

Run immediately after LLM response on every student_* page. Rejects garbage before it reaches grouping or eval.

| ID | Heuristic | Rule | Action |
|---|---|---|---|
| H1.1 | **Name regex** | `last` / `first` must match `^[A-Z][a-zA-Z'\-\. ]{1,38}[a-z]$` (allow apostrophes, hyphens, periods) | Fail → flag → retry tier or HITL |
| H1.2 | **OCR garbage token blocklist** | Reject if name contains any of: `BIRTH`, `COUNTY`, `SEX`, `PLACE`, `CITY`, `NAME`, `LAST`, `FIRST`, `MIDDLE`, `RECORD`, `BEGIN`, `END` | Rewrite prompt with stricter instruction + retry |
| H1.3 | **Numeric-prefix strip** | Strip leading digits from any name field (`611 Eblin` → `Eblin`) | Transform, not reject |
| H1.4 | **DOB format** | `^\d{1,2}/\d{1,2}/\d{2,4}$` or empty string | Fail → null the field, do not reject page |
| H1.5 | **Roll-number sanity** | Separator's extracted `roll_no` should equal the S3 folder's roll number, allowing for the known reel-vs-folder mismatch (e.g. S3 ROLL 101 = Reel 756) | Disagreement → log; do not reject |

**Expected accuracy lift:** +2% — catches the ~14% GT-shaped garbage class that contaminates raw LLM output.
**Cost:** $0.

---

## Tier 2 — Corpus-aware correction

Build reference corpora; use edit-distance snap to fix systematic OCR errors without any extra LLM call.

| ID | Heuristic | Rule | Notes |
|---|---|---|---|
| H2.1 | **Surname frequency dictionary** | Snap LLM surname to nearest corpus entry if Levenshtein ≤1 | Corpus = cleaned D1 GT (3,131 names) ∪ US Census top-10,000 surnames. Catches `SNITH → SMITH`, `R0GERS → ROGERS`. |
| H2.2 | **First-name dictionary** | Snap given name to nearest corpus entry, Levenshtein ≤1 | US Census top-5,000 given names. |
| H2.3 | **Microfilm OCR confusion pairs** | Try character swaps (`0↔O`, `1↔l↔I`, `5↔S`, `8↔B`, `6↔G`, `rn↔m`) and re-check corpus | Pick highest-frequency match; no change if no improvement. |
| H2.4 | **Within-packet Levenshtein reconciliation** | If 4/5 packet pages agree on name and 1 differs by Levenshtein ≤2 → override minority. Majority-vote logic already in the spec; extend with edit-distance tolerance | Catches same-name single-page misreads. |
| H2.5 | **Cross-packet near-dup merge** | Adjacent packets whose canonical names differ by Levenshtein ≤2 and have contiguous frame ranges → merge candidates. Require operator sign-off on merges (never auto) | Catches split-packet errors at boundaries. |
| H2.7 | **Index-snap (added 2026-04-21)** | Every extracted `student_*` name snaps to nearest entry in the SAME roll's `roll_index_entries` allowlist, Levenshtein ≤ 2 on `(last, first)`. Cross-check DOB when both sides populated. No match within threshold → flag HITL with `reason=no_index_match`. | **Largest accuracy lever in the pipeline.** Requires the new index-parse stage. 100-roll probe on 2026-04-21 confirmed 93/100 rolls carry at least one index page. |

**Expected accuracy lift:** +3% corpus snap **+5% index-snap (H2.7)** — the reinstated index-snap is now the highest-ROI non-LLM intervention by a wide margin.
**Cost:** $0 at runtime; upfront corpus build once.

---

## Tier 3 — Structural / roll-level rules

Catch systemic failures that a per-page model cannot see.

| ID | Heuristic | Rule | Action |
|---|---|---|---|
| H3.1 | **START/END bracket enforcement** | Each roll must have exactly one `roll_separator` with `marker=START` in the first 10 frames and one `END` in the last 5. Missing or duplicated → scan top candidates by confidence; if still missing, fall back to frame 0 / last | 0 START → flag whole roll for HITL |
| H3.2 | **Roll size sanity** | Expected 1,500–2,800 TIFs per full roll; known partials (059=414, 065B=127, 075A=2,557, 101=320) whitelisted. Anything outside ranges → anomaly log | Do not block; annotate manifest |
| H3.3 | **Page-class transition rules** | Impossible sequences:<br>• `roll_separator(END) → student_*`<br>• `student_*` before any `roll_separator(START)`<br>• 3+ consecutive `unknown` mid-roll | Retry affected frames with stricter prompt; if still bad → HITL |
| H3.4 | **Packet size distribution** | Mean 5, stdev ~3 (from D1 PDF-vs-TIF size ratio). Packet size 1 or ≥15 → suspect | Size-1 adjacent to size-15 with similar names → merge candidate |
| H3.5 | **Frame-number contiguity** | S3 frame numbers must form `00001..0NNNN` contiguous sequence. Gap = missing scan | Annotate manifest; never silently skip |
| H3.7 | **Alphabetical monotonic (added 2026-04-21)** | Index pages prove student records are filmed in alphabetical order by surname. Student-cover names in a roll must progress monotonically (ignoring `_N` dup-suffix ties). Out-of-order transition → flag packet boundary error. | Paired with H2.7 — if the extracted name both fails index-snap AND breaks alphabetical order, HITL is almost certainly right. |

**Expected accuracy lift:** +1% for H3.1–H3.5 + **+2% for H3.7 alpha-monotonic** (catches most of the residual boundary errors) — ~3% total.
**Cost:** $0.

---

## Tier 4 — Vendor / district priors injected into prompt

Shape LLM output by giving it frame-specific context before it answers.

| ID | Heuristic | Rule | Mechanism |
|---|---|---|---|
| H4.1 | **District-style prior** | D1 + D3 → expect Style B certificate separator. D2/D4/D5/D6/D7 → expect Style A clapperboard | Extra system-prompt line per frame |
| H4.2 | **Vendor prior** | D1 test ROLL 001 → White's Microfilm Services. Everything else → Total Information Management Systems | Injected into `roll_leader` frames so extractions use correct vendor |
| H4.3 | **Frame-position prior** | Frames 1–7 = "likely roll_leader or START separator". Last 1–5 = "likely END separator or trailing leader". Middle = "likely student_*" | Reduces class confusion on ambiguous frames |
| H4.4 | **Previous-page name prior** (optional) | For `student_continuation` / `student_test_sheet` frames, include the previous frame's extracted name in the prompt as a hint: "If this is the same student, confirm" | Improves packet boundary detection; small prompt-cost increase. Skip for POC. |
| H4.5 | **Index prior (added 2026-04-21)** | For ambiguous `student_cover` frames (confidence < 0.85), inject the top 5 nearest candidates from `roll_index_entries` into the system prompt: "Likely candidates for this page's student: [A], [B], [C], [D], [E]. Confirm exact match or 'none'." | Turns name extraction from open-ended vision OCR into constrained multiple-choice. Huge accuracy lift on degraded frames. Requires index-parse pre-stage. |

**Expected accuracy lift:** +2% — priors are cheap and high-signal.
**Cost:** ~5% more input tokens on affected frames. Marginal.

---

## Tier 5 — Cross-signal accuracy boosters

Higher-complexity. Only pull in if Tiers 0-4 don't close the gap to target.

| ID | Heuristic | Rule | Tradeoff |
|---|---|---|---|
| H5.1 | **Two-pass classify then extract** | Pass 1: classify only (few output tokens). Pass 2: extract only if `page_class` starts with `student_` | Cheaper output tokens; more total calls. Could save ~10% output cost. |
| H5.2 | **Ensemble voting on mid-band** | Confidence 0.5–0.75 → re-run with Sonnet 4.6. Agree → accept. Disagree → HITL | Already in the plan as "retry tier"; formalize as vote with disagreement → HITL |
| H5.3 | **Self-consistency probe** (skip for POC) | Re-ask LLM: "given this image and your prior answer, is the name correct?" | Doubles calls on probed frames; YAGNI for POC |
| H5.4 | **Packet-level re-extraction** (skip for POC) | If within-packet names disagree, submit 2 best cover pages in a single combined LLM call asking for the canonical name | One extra call per suspicious packet; YAGNI |

---

## Stacking — expected impact

Assumes Haiku 4.5 baseline at ~85% page-level partial name match (SOW gate is ≥90%; current spec 85%).

| Layer added | Page-level acc | Packet-level acc | Incremental cost (218K) |
|---|---|---|---|
| Baseline Haiku 4.5 batch | 85% | ~91% (majority vote lift) | $245 |
| + Tier 0 (pre-filter) | 85% | 91% | −$20 |
| + Tier 1 (reject garbage) | 87% | 93% | $0 |
| + Tier 2.1–2.4 (corpus snap) | 90% | 95% | $0 |
| + Tier 2.7 **index-snap** | 95% | 98% | +$12 (index parse) |
| + Tier 3 (structural + alpha-monotonic) | 96% | 98% | $0 |
| + Tier 4.1–4.3 (static priors) | 96% | 98% | marginal |
| + Tier 4.5 (index prior on ambiguous frames) | 97% | 99% | marginal |
| + Tier 5.2 (Sonnet retry on mid-band) | 98% | 99% | +$150 |
| **Total target** | **~98% page / ~99% packet** | | **~$400** |

These numbers are estimates, not measurements. Confirm with a ≥50-page labeled bake-off after the curated fixture set exists.

---

## POC scope recommendation

- **In:** Tier 0 (H0.1, H0.2, H0.3, H0.5), Tier 1 (all), Tier 2 (H2.1, H2.2, H2.3, H2.4, **H2.7 index-snap**), Tier 3 (all + **H3.7 alpha-monotonic**), Tier 4 (H4.1, H4.2, H4.3, **H4.5 index prior on ambiguous frames**), Tier 5 (H5.2 only).
- **Out (Phase 2 or later):** H0.4 (clapperboard Hough — nice-to-have), H2.5 (cross-packet merge — needs HITL UI), H4.4 (previous-page prior — POC complexity), H5.1, H5.3, H5.4.

**New dependency (added 2026-04-21):** Production pipeline must now have a per-roll **index-parse stage** that runs after classify, before grouping. Input: all frames labeled `student_records_index` for a roll. Output: populated `roll_index_entries` SQLite table with canonical `(last, first, middle, dob, enroll_date)` rows. Cost ~$12 added for the full 218K corpus. Without this stage, H2.7 / H4.5 can't run.

This keeps the POC focused on deterministic heuristics that cost $0 at inference time, plus the one LLM-layer boost (Sonnet retry) already in the plan.

---

## Dependencies this brainstorm surfaces

To implement these, the POC codebase needs:

1. **Image-hash library** (e.g. `imagehash`) for H0.2, H0.3.
2. **OpenCV or scikit-image** for H0.4 Hough-line detection (deferred to Phase 2).
3. **Name corpus files** — cleaned D1 GT + US Census dumps — committed to `poc/corpora/` (small, ~200KB total).
4. **Manifest schema** — JSON per roll recording: district, roll_num, n_frames, partial flag, gap frames, physical reel_no (when known), processing status. Lives at `poc/output/manifest_<roll>.json`.
5. **Orientation module** — PIL-based 4-rotation scorer using a cheap OCR (e.g. `pytesseract` at low resolution) or image statistics. Alternative: trust Bedrock's rotation handling and only normalize via aspect ratio.

Most of these are additive to the existing spec — they don't invalidate any Phase 1 module.

---

## Open questions about heuristics

1. **Orientation detection cost:** is it cheaper to rotate-then-LLM (extra Python work) or just trust LLM rotation handling + accept slightly worse accuracy? Needs a measurement.
2. **Corpus licensing:** US Census name data is public domain. D1 GT names are FERPA — corpus must stay internal / not committed to the public repo.
3. **Hough-line detector reliability on faded scans:** the Style A diagonal hatches are visible in our fixtures but unknown on degraded frames. Decide after a dedicated test.
4. **Reel-number cross-reference manifest:** do we build the reel→folder lookup table by extracting from `roll_leader` frames in every roll, or does the client have this mapping?
5. **Retry tier triggering:** retry on confidence band alone, or also on name-format rejection (H1.1 / H1.2)? Recommend: both.
