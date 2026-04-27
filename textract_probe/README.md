# textract_probe — isolated bake-off harness

One-shot harness for testing AWS Textract + local Tesseract on Osceola TIF
fixtures. **Fully isolated from `poc/`** — own env loader, own TIF helper, own
tests. Drop the entire directory if abandoned.

## Why

`docs/no-llm-90pct-design.md` and `docs/no-llm-pipeline-brainstorm.md` commit
Phase 2 to a Textract + rules pipeline targeting ≥ 90% precision. Cost +
accuracy claims are forecasts, never measured against real Osceola scans.
This module measures them on 8 fixture TIFs spanning all 7 page classes.

## Layout

```
textract_probe/
├── env.py              # Textract boto3 client factory (reads .env.bedrock)
├── convert.py          # TIF -> PNG bytes
├── client.py           # 5 endpoint wrappers (Detect / Forms / Tables / Layout / Queries)
├── bake_off.py         # CLI: fixtures × features sweep
├── tesseract_run.py    # CLI: Tesseract raw + preprocessed
├── fixtures.json       # 8 TIFs spanning 7 page classes
├── queries.json        # 6 Textract Queries (LAST/FIRST/MIDDLE/DOB/SCHOOL/ROLL_NO)
├── tests/
│   ├── test_client.py  # mocked unit tests
│   └── test_smoke.py   # gated live test (TEXTRACT_SMOKE_TEST=1)
└── output/             # gitignored, raw JSON + Tesseract TXT/TSV land here
```

## Run

```bash
# Install (separate from project requirements.txt — keeps poc/ deps lean)
pip install -r textract_probe/requirements.txt
brew install tesseract  # one-time, for tesseract_run.py

# Unit tests (mocked, no $$)
pytest textract_probe/tests/test_client.py -v

# Live smoke (~$0.0015)
TEXTRACT_SMOKE_TEST=1 pytest textract_probe/tests/test_smoke.py -v -s

# Full Textract sweep (~$0.70)
python3 -m textract_probe.bake_off \
    --fixtures-file textract_probe/fixtures.json \
    --out-dir textract_probe/output/textract \
    --features detect,forms,tables,layout,queries \
    --queries-file textract_probe/queries.json \
    --budget-ceiling 1.50

# Cross-district covers, queries-only (6 fixtures, ~$0.09)
python3 -m textract_probe.bake_off \
    --fixtures-file textract_probe/fixtures_cross_district.json \
    --out-dir textract_probe/output/textract \
    --features queries \
    --queries-file textract_probe/queries.json \
    --budget-ceiling 0.20

# Tesseract sweep ($0)
python3 -m textract_probe.tesseract_run \
    --fixtures-file textract_probe/fixtures.json \
    --out-dir textract_probe/output/tesseract \
    --preprocess

# Decode raw JSON dumps into per-fixture markdown digests
python3 -m textract_probe.decode \
    --in-dir textract_probe/output/textract \
    --out-dir textract_probe/output/digests
```

## Credentials

Reuses repo-root `.env.bedrock` (tanishq AWS account, us-west-2). The IAM user
must have `textract:DetectDocumentText` + `textract:AnalyzeDocument`
permissions. If smoke test fails with `AccessDeniedException`, attach
`AmazonTextractFullAccess` to that user.

## Output

Results doc: `docs/2026-04-27-textract-bake-off-results.md`.
