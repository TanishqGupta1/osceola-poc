# Osceola Student Records — How the AI Pipeline Works

**Prepared for:** Osceola County School District
**Date:** 2026-04-23

This document explains, in plain language, how the AI system reads your 218,577 scanned microfilm pages and produces one named PDF per student. Technical details live in separate engineering docs; this is the stakeholder view.

---

## 1. What you're getting

**Input:** 218,577 microfilm scans on Amazon S3, one image per frame, across 100 rolls and 7 districts.

**Output:** Approximately **43,000 student PDFs**, each named `Last, First Middle.pdf`, organized by district and roll. Each PDF contains every scanned page that belongs to one specific student, stitched together in the right order.

**Accuracy target:** 90–95% of student names correct on the first automated pass. The remaining 5–10% flow to a human reviewer before any file is shipped.

---

## 2. The six steps

Think of the pipeline as a factory line. Each scan moves through six stations:

### Step 1 — Intake
The AWS Step Functions service picks up every TIF file from your S3 bucket and fans it out to thousands of parallel workers. There is no queue to manage manually; it just streams through.

### Step 2 — Cheap pre-check
Before we ask the AI anything, a fast rule-based filter catches the easy cases:
- Blank pages
- Vendor cover sheets (e.g. "Total Information Management Systems" letterhead)
- Microfilm calibration targets

About 10% of all frames are filtered here for free. The AI never has to look at them.

### Step 3 — AI reads the page
For every remaining page, Claude Haiku 4.5 (a vision AI from Anthropic, running on AWS Bedrock) looks at the image and returns:
- **What kind of page is it?** One of 7 categories — cover, test sheet, continuation, index page, roll separator, roll leader, or unknown.
- **Student name** if present (last, first, middle).
- **Date of birth, school, etc.** if visible on the page.
- **If it's a `STUDENT RECORDS INDEX` table**, it extracts every row — which is a directory of all students on that roll. This is the single biggest accuracy lever.

### Step 4 — Smart second opinion
When the AI is only moderately confident (60–85%), the system re-asks a smarter model (Claude Sonnet 4.6) to verify. This catches mistakes before they reach you, and only costs extra on the hard ~12% of pages.

### Step 5 — Validation
Every extracted name runs through sanity checks:
- Must look like a real name (no numbers, no garbage OCR tokens like "BIRTH" or "COUNTY")
- Snap to the closest name on the roll's index page (our canonical list of students for that roll)
- Must match a known record

Pages that fail validation are flagged for the human reviewer.

### Step 6 — Bundle into PDFs
Once every page in a roll has been processed, the system:
1. Reads the index-page directory for that roll (the list of ~347 students).
2. Groups all pages that refer to each student.
3. Merges those TIF frames into a single PDF.
4. Saves it as `Last, First Middle.pdf` in the output S3 bucket.

---

## 3. The human-in-the-loop (HITL) review layer

AI is not 100% accurate. We plan for that.

Any page the AI is **less than 60% confident** about, or any extraction that fails validation, goes into a review queue. Your designated operator (or our team) opens a simple web app, sees the scanned image on the left and the extracted fields on the right, and either:
- **Approves** the AI's guess as-is, or
- **Edits** the name / DOB and approves the correction, or
- **Rejects** the page (e.g. "this is illegible").

Once a correction is submitted, the pipeline automatically re-bundles that student's PDF with the fixed name. No manual file shuffling.

Expected review volume: ~5% of pages = ~11,000 pages = ~90 hours of operator time across the full run.

---

## 4. How we know it works

We have already completed a **Phase 1 proof-of-concept** on Test Input ROLL 001 (1,924 TIFs, one of your existing rolls). The pipeline ran end-to-end on real scans and measured:

| Metric | Result |
|---|---|
| Pages correctly classified | 1,924 / 1,924 |
| Student names correctly extracted (high-confidence mode) | **87.1%** — meets the 85% target |
| Student names correctly extracted (balanced mode) | 75.9% |
| Cost to process 1,924 pages | $9.89 |
| Processing time | ~20 minutes |

At full scale (218K pages), this extrapolates to roughly **$770 in AWS costs** for one full run, plus the ~90 hours of operator HITL review.

A detailed results report is available on request.

---

## 5. Rollout plan

| Phase | What happens | Duration |
|---|---|---|
| **Phase 1 — POC** | Proof on ROLL 001, accuracy measured | **Complete** |
| **Phase 2 — Single-roll production** | Move to AWS infra, add Tier 0/1 filters, add Sonnet retry, PDF output on one roll end-to-end | 3 weeks |
| **Phase 3 — Operator UI** | Build the review web app, train operators, pilot on 1 roll with humans in the loop | 3 weeks |
| **Phase 4 — Full 218K run** | Process the entire corpus, monitor, deliver final PDFs | 2–3 weeks |
| **Total** | | ~8–10 weeks |

---

## 6. Security and compliance

- Files never leave AWS. All processing happens inside the Osceola-controlled S3 bucket and our Bedrock account, both hosted in the AWS us-west-2 region.
- Student records are FERPA-protected. The pipeline runs with IAM-gated access; no public endpoints.
- The AI model does not retain the scans or the extracted names. Each call is stateless.
- Operator access is gated by AWS Cognito; every edit is logged to an immutable audit trail.
- Raw extracted data is stored in DynamoDB for 90 days, then archived. Output PDFs stay in S3 under your account.

---

## 7. Known limitations (being addressed in Phase 2)

- **Older / degraded scans** — some 1991–92 microfilm pages are faint or skewed; the AI flags these as low-confidence automatically.
- **Hand-written name fields** — bubble-sheet tests where names are filled in with pencil are harder than typed forms.
- **Districts 2–7** — we currently have ground-truth PDFs only for District 1 (seven rolls). Before running those six districts at scale we will label a small sample per district to confirm accuracy holds.

---

## 8. What we need from you

| Item | Why it matters |
|---|---|
| **Confirmation on accuracy target** — is ≥85% first-pass + 5% HITL review acceptable? | Defines our go/no-go gate |
| **Operator staffing decision** — your team or ours for HITL reviews? | Drives Phase 3 timeline + cost |
| **District 2–7 ground-truth sample** — ~50 labeled PDFs per district | Lets us verify accuracy outside D1 |
| **Security review sign-off** — IAM policies, data-retention terms | Before Phase 4 bulk run |

---

## 9. One-page visual

Full architecture diagram (four views — bulk pipeline, single-TIF journey, operator UI, classification rules) is on our shared Figma board: see the link the team has shared.

The four views cover:
1. **Bulk pipeline** — how all 218K files move through the system.
2. **Single-TIF journey** — what happens to one page, end-to-end.
3. **Operator UI** — what the human reviewer sees on screen.
4. **Classification rules** — how the AI decides what kind of page it is looking at.

---

## 10. Questions?

Technical: please reach out to the engineering team.
Contractual: please raise via the existing client-engagement channel.
