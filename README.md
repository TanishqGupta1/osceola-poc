# Osceola POC — Student Records AI Pipeline

AI pipeline to classify and extract data from **~218,677 TIF scans** of student records on S3, producing named PDFs per student (`Last, First Name MI.pdf`) grouped into their original microfilm roll folders.

Client: Osceola County School District.
Source: `s3://servflow-image-one/Osceola Co School District/` (us-west-2).
Model: Claude Haiku 4.5 on AWS Bedrock. Vision only — no Textract.

---

## Problem

~218K TIF images, one per scanned microfilm frame, across 7 districts × 101 rolls (≈2,000 frames per roll). Each roll is a linear scan of a physical 1991–92 microfilm reel. Student packets are back-to-back with no per-student separator pages — boundaries must be inferred from name changes. Two different filming vendors used different leader + separator-card layouts.

Output target: ~48,600 student PDFs, named `Last, First MI.pdf`, one per student, with 90–95% name-extraction accuracy and a human-in-the-loop queue for low-confidence cases.

---

## Canonical roll structure

```
Frame 00001 … 0000N     roll_leader — variable length (3–7 frames)
  00001                 blank / vendor letterhead / microfilm resolution target
  00002…0000(N-1)       operator card, certification card, district title page
  0000N                 roll_separator (START clapperboard OR certificate card)

Frame 0000N+1 … M-1     student packets, back-to-back
                         grouped by name-change detection

Frame M                 roll_separator (END clapperboard OR certificate card)
Frame M+1 … last        roll_leader — trailing blank / letterhead
```

Two visually distinct separator-card styles — both classify as `roll_separator`:

| Style | Look | Districts |
|---|---|---|
| A — clapperboard | diagonal-hatched rectangles + "START/END" + boxed handwritten `ROLL NO. N` | 2, 4, 5, 6, 7 |
| B — certificate | printed "CERTIFICATE OF RECORD" form + START/END heading + filmer signature | 1, 3 |

## Page taxonomy (6 classes)

- `student_cover` — primary cumulative/guidance record (name + demographics)
- `student_test_sheet` — standardized test form with student name
- `student_continuation` — back page, comments, family data with name at top
- `roll_separator` — START or END card (either style)
- `roll_leader` — blank, vendor letterhead, calibration target, district title, certification card, operator card
- `unknown` — blank mid-roll, illegible

---

## Production architecture (Phase 2+)

```mermaid
flowchart LR
    S3IN["`**S3 Input**
    servflow-image-one/.../Input/
    new roll uploaded`"]

    EB["`**EventBridge**
    roll-ready rule`"]

    SFN["`**Step Functions**
    1 execution per roll`"]

    DMAP["`**Distributed Map**
    parallel over pages
    (up to 1000 concurrent)`"]

    LC["`**Lambda: classify_page**
    Pillow TIF→PNG
    Bedrock Haiku 4.5 Converse
    tool_use schema`"]

    LS["`**Lambda: sonnet_retry**
    (conf 0.70–0.85)
    Bedrock Sonnet 4.6`"]

    DDB[("`**DynamoDB: pages**
    pk=roll_id
    sk=frame`")]

    AGG["`**Lambda: aggregate_roll**
    find START/END
    name-change grouping
    generate PDFs (pypdf)`"]

    S3OUT["`**S3 Output**
    Output/DISTRICT-X/ROLL-Y/
    Last, First M.pdf`"]

    SQS["`**SQS: hitl-queue**
    low confidence frames`"]

    HITL["`**HITL web app**
    React + Cognito
    API Gateway + Lambda
    writes corrections → DDB`"]

    S3IN --> EB --> SFN --> DMAP --> LC
    LC -->|"conf ≥ 0.85"| DDB
    LC -->|"conf 0.70–0.85"| LS --> DDB
    LC -->|"conf < 0.70"| SQS
    DMAP --> AGG
    AGG --> DDB
    AGG --> S3OUT
    AGG --> SQS
    SQS --> HITL
    HITL --> DDB
    HITL -->|"retrigger roll"| AGG
```

### Accuracy strategy (target 90–95%)

Five stacked layers — compound effect:

1. **Self-reported confidence** per page + per field from Haiku 4.5
2. **Cross-page validation** — majority-vote name across consecutive pages in same packet
3. **Format validation** — DOB regex, name alpha-only, `ROLL NO.` matches folder context
4. **Sonnet 4.6 fallback tier** — mid-confidence retries only (~10–15% of pages)
5. **HITL review** — residual <5% sent to human operators

### Cost estimate (one-time 218K run)

| Line item | Cost |
|---|---|
| Bedrock Haiku (Batch Inference) | ~$225 |
| Bedrock Sonnet (retry tier) | ~$150 |
| Lambda invocations | ~$50 |
| Step Functions | ~$20 |
| DynamoDB on-demand | ~$10 |
| S3 + transfer | ~$30 |
| **AWS total** | **~$490** |

Plus operator HITL time (~90 hrs estimated at 5% review rate × 30s per page).

---

## Phase 1 POC architecture (current scope)

Local Python, no AWS infra. Prove accuracy before building production stack.

```mermaid
flowchart LR
    S3["`**S3**
    Test Input/ROLL 001/
    1924 TIFs`"]

    L["`samples/ (local)`"]

    CONV["`**poc/convert.py**
    Pillow TIF → PNG bytes
    (in-memory)`"]

    BR["`**Bedrock Converse**
    Claude Haiku 4.5
    tool_use schema`"]

    CE["`**poc/classify_extract.py**
    per-page orchestrator`"]

    PAGES["`**poc/output/
    roll_001_pages.jsonl**
    per-page JSON`"]

    GROUP["`**poc/group.py**
    name-change grouping
    [START+1 … END-1]`"]

    STUDENTS["`**poc/output/
    roll_001_students.json**`"]

    EVAL["`**poc/eval.py**
    vs ground-truth
    Output PDF filenames`"]

    REPORT["`**poc/output/
    roll_001_eval.json**
    accuracy report`"]

    S3 --> L --> CONV --> CE --> BR
    BR --> CE --> PAGES --> GROUP --> STUDENTS --> EVAL --> REPORT
```

Success criterion: `accuracy_partial ≥ 0.85` on ROLL 001.

---

## Repo layout

```
├── main.py                     # interactive S3 helper CLI (current)
├── s3_operations.py            # boto3 wrappers for S3 list/upload/download/read/delete
├── requirements.txt            # boto3, pillow, pydantic, pytest, Levenshtein
├── CLAUDE.md                   # guidance for AI coding assistants
├── README.md                   # you are here
├── .env.example                # AWS creds template
├── docs/
│   ├── osceola-poc-discussion.md         # project discovery notes (source of truth)
│   └── superpowers/
│       ├── specs/2026-04-18-osceola-phase1-poc-design.md   # Phase 1 design spec
│       └── plans/2026-04-18-osceola-phase1-poc.md          # 12-task TDD plan
├── samples/
│   └── fixtures_public/        # 3 non-PII fixtures (separator cards + calibration target)
│                               # Full sample set stays in S3 (FERPA-protected).
└── poc/                        # (to be created per plan) — classify + extract + group + eval
```

---

## Quick start

```bash
# install deps
pip install -r requirements.txt

# configure AWS
cp .env.example .env
# edit .env with AWS creds + set S3_BUCKET_NAME=servflow-image-one, AWS_REGION=us-west-2

# run the S3 helper CLI
python main.py
```

POC pipeline scripts not yet written — see [`docs/superpowers/plans/2026-04-18-osceola-phase1-poc.md`](docs/superpowers/plans/2026-04-18-osceola-phase1-poc.md) for the 12-task TDD build order.

---

## Roadmap

| Phase | Scope | Duration |
|---|---|---|
| **1 — POC** (current) | Python pipeline on ROLL 001, measure accuracy | 2 weeks |
| **2 — Single-roll prod** | Step Functions + Lambda + DynamoDB for one roll end-to-end + PDF output | 2 weeks |
| **3 — HITL UI** | React SPA + Cognito + API Gateway for operator review | 2 weeks |
| **4 — Bulk 218K** | Bedrock Batch Inference, monitoring, security hardening, full dataset run | 2 weeks |

---

## Data source

FERPA-protected student records. Real TIFs are NOT in this repo — they live in S3 (`servflow-image-one`, us-west-2) with IAM-gated access. The three images in `samples/fixtures_public/` are separator cards and a calibration target that contain no student PII.

Known data caveat: the S3 folder number (e.g. `ROLL 101`) does not always match the original microfilm reel number on the certification card (`Reel 756` in one observed case). Use the certification card's reel number when referencing the original archive.

---

## Known blockers

1. **IAM Bedrock permissions missing** — the current `Servflow-image1` IAM user cannot call `bedrock:*` APIs. Must be resolved before Phase 1 Task 5. Grant policy or issue a new role.

---

## License

Private internal project. No license granted.
