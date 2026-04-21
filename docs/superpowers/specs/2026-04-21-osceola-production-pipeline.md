# Osceola Production Pipeline — Design Spec

**Date:** 2026-04-21
**Scope:** Phase 1 production pipeline that processes the full 218,577 TIFs end-to-end with a client-facing HITL UI.
**Supersedes:** `2026-04-18-osceola-phase1-poc-design.md` (kept as Phase-0 POC reference for schemas + prompts).
**Companions:** `../../heuristics-brainstorm.md` (heuristic catalog), `../../osceola-poc-discussion.md` (source of truth for data/domain facts).

## Goal

Deliver a single, deployable, reproducible pipeline that ingests 218,577 microfilm TIFs from `s3://servflow-image-one/Osceola Co School District/Input/`, produces per-student PDFs (`Last, First MI.pdf`) in `.../Output/` that mirror the input folder structure, surfaces low-confidence frames to a human operator via a web UI, and finishes the bulk run for **≤ $400 AWS spend + 1 human-hour of review**.

Accuracy target: **≥ 97% partial name match at packet level, ≥ 99% after HITL review**, measured against a cleaned D1 ground-truth baseline (target revised upward 2026-04-21 after universal `student_records_index` pattern was confirmed).

## Non-goals

- Amazon Nova / Mistral / Llama models — dropped after the 2026-04-20 bake-off (name-order risk + no cost advantage).
- Multi-tier model chains (Opus tiebreaker, 3-model ensemble, cover-page double-vote) — YAGNI; reinstate only if accuracy gates fail.
- Step Functions / Distributed Map / Lambda orchestration — deferred to Phase 2; not needed at 218K scale on a single host.
- Client-hosted HITL UI — we ship a containerized UI; client consumes via URL.
- Phase 3 HITL SPA / Cognito — not in this spec.
- Live Bedrock quota elasticity testing — the pipeline throttles itself; no dynamic autoscaling.

## Deliverables

1. One Docker image (`osceola-pipeline`) containing the Python daemon, workers, heuristics, Streamlit HITL UI, and SQLite schema.
2. A `docker-compose.yml` that runs two services (`pipeline` + `hitl`) behind a shared volume and reverse proxy.
3. A populated `s3://.../Output/` matching SOW folder layout.
4. A `manifest_<roll>.csv` per roll summarising every TIF → predicted class + name + confidence + heuristics fired + HITL status.
5. A final `report.md` auto-generated at run end with measured accuracy (vs cleaned D1 GT), cost, token counts, HITL volume, failure patterns.
6. The SQLite state file `/data/osceola.db` shipped to the client with every decision captured — single portable audit artifact.

---

## Architecture

Single Docker host. Two containers sharing one volume. n8n at `dev-n8n.visualgraphx.com` drives orchestration from outside.

```
┌─ Docker host (EC2 us-west-2 or on-prem — env-agnostic) ─────────────┐
│                                                                      │
│  docker compose up                                                   │
│                                                                      │
│  ┌─ pipeline container ──────────────────────────────┐              │
│  │ FastAPI :8000  (control plane)                    │              │
│  │   POST /rolls/{id}/start    → enqueue a roll      │              │
│  │   GET  /rolls/{id}/progress → { pct, ETA, cost }  │              │
│  │   GET  /rolls/{id}/summary  → per-roll stats      │              │
│  │   POST /hitl/{hitl_id}/resolve                    │              │
│  │   POST /rolls/{id}/cancel                         │              │
│  │                                                    │              │
│  │ Background workers (asyncio + threadpool)         │              │
│  │   - fetch_worker   S3 TIF → in-mem PNG            │              │
│  │   - classify_worker  Haiku 4.5 via tool_use       │              │
│  │   - retry_worker     Sonnet 4.6 on low-conf       │              │
│  │   - heuristics       Tier 0-4 modules             │              │
│  │   - aggregator       grouping + pypdf PDF gen     │              │
│  │                                                    │              │
│  │ SQLite /data/osceola.db  (WAL mode, single writer)│              │
│  └────────────────────────────────────────────────────┘              │
│                                                                      │
│  ┌─ hitl container ─────────────────────────────────┐               │
│  │ Streamlit :8501                                   │               │
│  │   - streamlit-authenticator (yaml user store)     │               │
│  │   - Queue list (flagged pages + packets)          │               │
│  │   - Image preview via S3 presigned URL (15 min)   │               │
│  │   - Approve / Edit name / Reject / Reassign packet│               │
│  │   - Submits via FastAPI /hitl/resolve             │               │
│  └────────────────────────────────────────────────────┘              │
│                                                                      │
│  Caddy :443 (automatic LE cert) → /api/* → pipeline, / → hitl        │
│                                                                      │
│  Volumes: /data (SQLite, PNG cache, logs), /creds (env files)        │
└──────────────────────────────────────────────────────────────────────┘
           ▲                      ▲                     ▲
           │ POST /rolls/start    │ operator browser    │ Slack webhook
           │ GET /progress        │ → HITL UI           │ (HITL backlog)
           │                      │                     │
┌──────────┴──────────┐           │                     │
│ n8n                 │           │              ┌──────┴─────┐
│ dev-n8n.vgx.com     │           │              │ Slack      │
│                     │           │              │ (optional) │
│ 4 workflows:        │           │              └────────────┘
│  1 bulk-start       │           │
│  2 progress-poll    │           │
│  3 hitl-notifier    │           │
│  4 completion-mail  │           │
└─────────────────────┘           │
                                  │
                         ┌────────┴──────────┐
                         │ S3 bucket          │
                         │ servflow-image-one │
                         │ (us-west-2)        │
                         └───────────────────┘
```

### Why single-host

- 218K frames × ~3 s/frame ÷ 30 concurrent threads ≈ **6 hours** end-to-end. Overnight run, one machine.
- Bedrock on-demand throughput quota in us-west-2 for Haiku 4.5 caps effective concurrency around 50–80 requests/sec anyway; multi-node wouldn't go faster without quota increase.
- SQLite with WAL mode supports the concurrent read + serialized write pattern we need. No need for Postgres.
- One log stream, one state file, one container to debug.

### Dual AWS credentials

Two principals, mutually exclusive access:

| Principal | Account | Works |
|---|---|---|
| `Servflow-image1` | `523109542532` | S3 read/write on `servflow-image-one` |
| `tanishq` | `690816807846` | Bedrock us-west-2 (invoke + list models) |

Container loads `.env.s3` + `.env.bedrock` at startup and routes each boto3 client to the right creds. Never mix.

---

## Pipeline flow — per roll

```
1. n8n POST /rolls/{id}/start
2. FastAPI enqueues roll in SQLite.rolls (status=queued)
3. fetch_worker  lists S3 prefix → for each TIF, check SQLite.pages
                 (idempotent skip if status=done)
4. fetch_worker  streams TIF bytes → in-mem PNG via Pillow (max-side 1500px)
5. heuristics T0 run on PNG bytes:
     - blank → label roll_leader, skip LLM
     - pHash hit → label directly
     - else pass through
6. heuristics T4.1–T4.3 inject district/vendor/position prior into prompt
7. classify_worker calls Haiku 4.5 Bedrock Converse with tool_use schema
     model = us.anthropic.claude-haiku-4-5-20251001-v1:0
     temperature = 0.0
     maxTokens = 400
     page_class enum includes student_records_index (added 2026-04-21)
8. heuristics T1 validates response:
     - name regex
     - OCR-garbage blocklist
     - numeric-prefix strip
     - DOB regex
   Fail → mark for retry
9. if (conf < 0.7) OR (T1 format reject):
     retry_worker calls Sonnet 4.6 with same payload
     model = us.anthropic.claude-sonnet-4-6
10. heuristics T2.1–T2.4 corpus-snap on name fields
11. record final PageResult in SQLite.pages

--- NEW STAGE (added 2026-04-21): per-roll index parse ---

12. Once every frame in the roll has status=done or status=flagged, trigger
    index_worker for the roll:
       SELECT * FROM pages
       WHERE roll_id=? AND page_class='student_records_index'
       ORDER BY frame
    For each index frame:
       - load cached PNG bytes
       - call Haiku with INDEX_PARSE_PROMPT (tool_use schema that returns
         rows = list of {last, first, middle, dob, enroll_date})
       - on Haiku confidence < 0.8: retry with Sonnet 4.6
       - INSERT rows into SQLite.roll_index_entries
13. After index-parse: compute canonical name set per roll. If roll has
    zero index frames → log warning, set roll.index_coverage='none',
    fall back to pure name-change grouping.

--- continuing ---

14. heuristics T3 (START/END bracket, packet-size sanity, transition rules,
    frame contiguity, H3.7 alpha-monotonic against sorted index entries)
15. Name-change grouping with:
      - H2.4 within-packet Levenshtein reconcile
      - H2.7 INDEX-SNAP: every extracted cover name → nearest
        roll_index_entries row, Levenshtein ≤ 2 on (last, first).
        DOB cross-check when both sides populated.
        No match → flag HITL reason=no_index_match.
      - H4.5 INDEX PRIOR: for conf < 0.85 cover frames, a second Bedrock
        call is made with top-5 candidate names from the index injected
        as hints. Not per-frame — only for residual ambiguous ones.
16. HITL routing (existing):
     - conf < 0.6                      → HITL reason=low_confidence
     - T1 format reject after retry    → HITL reason=format_reject
     - no_index_match (new)            → HITL reason=no_index_match
     - alpha-monotonic break (new)     → HITL reason=alpha_break
     - disagreement between Haiku+Sonnet → HITL reason=model_disagree
17. aggregator pypdf-merges the roll's TIFs per packet
    writes Last, First MI.pdf to s3://.../Output/<district>/<roll>/
18. aggregator writes manifest_<roll>.csv to /data and uploads to S3
19. SQLite.rolls status=done, completion timestamp recorded
20. n8n hitl-notifier fires if pending_hitl > 50 → Slack ping
21. Operator reviews in Streamlit → submits → re-trigger aggregator for
    the affected packets only (incremental PDF regen)
```

Every step is idempotent. Any crash → restart FastAPI, workers pick up from SQLite row states.

---

## File structure

```
osceola-pipeline/
├── Dockerfile                        # python:3.11-slim base
├── docker-compose.yml                # pipeline + hitl + caddy
├── Caddyfile                         # HTTPS + reverse proxy
├── pyproject.toml                    # deps, build config
├── requirements.txt                  # pinned versions
├── .env.s3.example                   # Servflow-image1 creds
├── .env.bedrock.example              # tanishq creds
├── auth_users.yaml.example           # streamlit-authenticator config
│
├── poc/
│   ├── __init__.py
│   ├── config.py                     # env loading, model IDs, budget cap
│   ├── schemas.py                    # pydantic models (copy from 04-18 spec)
│   ├── db.py                         # SQLite schema + typed queries
│   ├── s3_client.py                  # Servflow-image1 client (streaming reads, signed URLs)
│   ├── bedrock.py                    # Converse wrapper (tool_use, retry, throttle)
│   ├── convert.py                    # TIF → PNG bytes (Pillow)
│   ├── prompts.py                    # system prompt + tool schema
│   │
│   ├── heuristics/
│   │   ├── __init__.py
│   │   ├── tier0_pixel.py            # H0.1 blank, H0.2/0.3 pHash, H0.5 rotate
│   │   ├── tier1_format.py           # H1.1–H1.5 name regex, garbage, DOB
│   │   ├── tier2_corpus.py           # H2.1–H2.4 surname/first/confusion/reconcile + H2.7 index-snap
│   │   ├── tier3_structural.py       # H3.1–H3.5 bracket, size, transitions + H3.7 alpha-monotonic
│   │   └── tier4_priors.py           # H4.1–H4.3 district/vendor/position + H4.5 index prior
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── fetch.py                  # S3 list + stream
│   │   ├── classify.py               # Haiku primary
│   │   ├── retry.py                  # Sonnet retry-tier
│   │   ├── index_parse.py            # NEW 2026-04-21: per-roll index → roll_index_entries
│   │   └── aggregate.py              # group + pdf + manifest (uses index allowlist)
│   │
│   ├── grouping.py                   # name-change packet builder + Levenshtein
│   ├── pdfgen.py                     # pypdf TIF→PDF writer
│   ├── eval.py                       # GT-cleaner + scoring
│   ├── manifest.py                   # roll manifest JSON/CSV writer
│   ├── report.py                     # auto-generated run report
│   │
│   ├── api.py                        # FastAPI control plane
│   ├── streamlit_app.py              # HITL UI (single file)
│   ├── logging_config.py             # structured JSON logs
│   └── __main__.py                   # CLI entrypoint: migrate | serve | worker | dryrun
│
├── corpora/
│   ├── surnames_us_census.txt        # US Census top-10,000 (public domain)
│   ├── first_names_us_census.txt     # top-5,000
│   └── surnames_d1_cleaned.txt       # built from D1 GT after cleaning (FERPA)
│
├── alembic/                          # SQLite schema migrations
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
│
├── tests/
│   ├── unit/                         # per-module mocked tests
│   ├── integration/                  # real SQLite, no Bedrock
│   └── smoke/                        # real Bedrock, BEDROCK_SMOKE=1
│
├── scripts/
│   ├── bake_off.py                   # model/fixture eval tool
│   ├── build_corpus.py               # D1 GT → surname corpus
│   ├── dry_run.sh                    # single-roll validation
│   ├── run_full.sh                   # 218K run
│   └── export_audit.sh               # ship SQLite + manifests to client
│
└── docs/
    ├── README.md                     # ops runbook
    ├── ARCH.md                       # this spec (copy)
    └── HITL.md                       # operator guide
```

Boundary rules:

- **`workers/` never imports `api.py` or `streamlit_app.py`** — workers are pure library code, runnable standalone.
- **`heuristics/` has no S3/Bedrock imports** — pure pixel + text functions, unit-testable without AWS.
- **`db.py` is the only module that writes to SQLite** — every worker calls through typed accessors.
- **`config.py` is the only place env vars are read** — every module imports constants from it.
- **`api.py` is thin** — delegates all logic to `workers/` and `db.py`. Target < 300 lines.

---

## SQLite schema

WAL mode on. Single writer (FastAPI process), multiple readers (workers, Streamlit, observers).

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE rolls (
  roll_id              TEXT PRIMARY KEY,                     -- "OSCEOLA SCHOOL DISTRICT-4/ROLL 045"
  district             INTEGER NOT NULL,                     -- 1..7
  roll_num             TEXT NOT NULL,                        -- "045", "065B"
  n_frames             INTEGER NOT NULL,
  status               TEXT NOT NULL CHECK(status IN (
                         'queued','fetching','classifying',
                         'aggregating','done','failed','cancelled')),
  started_at           DATETIME,
  completed_at         DATETIME,
  pages_done           INTEGER NOT NULL DEFAULT 0,
  pages_flagged        INTEGER NOT NULL DEFAULT 0,
  pages_hitl           INTEGER NOT NULL DEFAULT 0,
  packets_created      INTEGER NOT NULL DEFAULT 0,
  cost_usd             REAL NOT NULL DEFAULT 0.0,
  tokens_in            INTEGER NOT NULL DEFAULT 0,
  tokens_out           INTEGER NOT NULL DEFAULT 0,
  reel_no_cert         TEXT,                                 -- from certification card
  filmer_name          TEXT,
  filming_date         TEXT,
  filming_vendor       TEXT,
  index_coverage       TEXT CHECK(index_coverage IN (        -- added 2026-04-21
                         'pending','none','partial','full')),
  index_pages_parsed   INTEGER NOT NULL DEFAULT 0,
  index_entries_total  INTEGER NOT NULL DEFAULT 0,
  notes                TEXT
);

CREATE TABLE pages (
  page_id              TEXT PRIMARY KEY,                     -- "d4r045_00097"
  roll_id              TEXT NOT NULL REFERENCES rolls(roll_id),
  frame                INTEGER NOT NULL,                     -- 97
  s3_key               TEXT NOT NULL,
  page_class           TEXT CHECK(page_class IN (
                         'student_cover','student_test_sheet',
                         'student_continuation','student_records_index',
                         'roll_separator','roll_leader','unknown')),
  separator_marker     TEXT CHECK(separator_marker IN ('START','END',NULL)),
  separator_roll_no    TEXT,
  student_last         TEXT,
  student_first        TEXT,
  student_middle       TEXT,
  student_dob          TEXT,
  student_school       TEXT,
  confidence_overall   REAL,
  confidence_name      REAL,
  primary_model        TEXT,                                 -- model used
  retry_model          TEXT,                                 -- NULL unless retried
  heuristics_fired     TEXT,                                 -- JSON array ["H0.1","H2.1"]
  latency_ms           INTEGER,
  tokens_in            INTEGER,
  tokens_out           INTEGER,
  notes                TEXT,
  status               TEXT NOT NULL CHECK(status IN (
                         'pending','done','retry','flagged',
                         'hitl_open','hitl_resolved','failed')),
  processed_at         DATETIME,
  UNIQUE(roll_id, frame)
);
CREATE INDEX idx_pages_roll ON pages(roll_id, frame);
CREATE INDEX idx_pages_status ON pages(status);

CREATE TABLE packets (
  packet_id            TEXT PRIMARY KEY,                     -- "d4r045_001"
  roll_id              TEXT NOT NULL REFERENCES rolls(roll_id),
  student_last         TEXT NOT NULL,
  student_first        TEXT NOT NULL,
  student_middle       TEXT,
  frame_start          INTEGER NOT NULL,
  frame_end            INTEGER NOT NULL,
  frames_json          TEXT NOT NULL,                        -- JSON [97,98,99]
  avg_confidence       REAL,
  flagged              INTEGER NOT NULL DEFAULT 0,           -- 0/1
  hitl_reviewed        INTEGER NOT NULL DEFAULT 0,
  pdf_s3_key           TEXT,                                 -- null until generated
  pdf_generated_at     DATETIME,
  status               TEXT NOT NULL CHECK(status IN (
                         'pending','ready','pdf_generated',
                         'flagged','hitl_open','hitl_resolved'))
);
CREATE INDEX idx_packets_roll ON packets(roll_id);

CREATE TABLE hitl_queue (
  hitl_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type          TEXT NOT NULL CHECK(entity_type IN ('page','packet')),
  entity_id            TEXT NOT NULL,
  reason               TEXT NOT NULL,                        -- "low_confidence","format_reject","bracket_missing",...
  created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  assigned_to          TEXT,
  reviewed_at          DATETIME,
  resolution           TEXT,                                 -- JSON of operator's edits
  resolved_by          TEXT
);
CREATE INDEX idx_hitl_open ON hitl_queue(reviewed_at) WHERE reviewed_at IS NULL;

CREATE TABLE roll_index_entries (
  entry_id             INTEGER PRIMARY KEY AUTOINCREMENT,
  roll_id              TEXT NOT NULL REFERENCES rolls(roll_id),
  source_page_id       TEXT NOT NULL REFERENCES pages(page_id),
  row_order            INTEGER NOT NULL,            -- alpha position within source index page
  last_name            TEXT NOT NULL,
  first_name           TEXT NOT NULL,
  middle_name          TEXT,
  dob                  TEXT,                         -- "M/D/YYYY" or ""
  enroll_date          TEXT,                         -- "1965-1966" or ""
  parsed_model         TEXT NOT NULL,                -- which model parsed this row
  parse_confidence     REAL,
  notes                TEXT
);
CREATE INDEX idx_rie_roll_name ON roll_index_entries(roll_id, last_name, first_name);
CREATE INDEX idx_rie_roll      ON roll_index_entries(roll_id);

CREATE TABLE run_log (
  log_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  level                TEXT NOT NULL,                        -- INFO|WARN|ERROR
  component            TEXT NOT NULL,                        -- fetch|classify|retry|aggregate|hitl
  roll_id              TEXT,
  page_id              TEXT,
  message              TEXT NOT NULL
);

CREATE TABLE budget (
  key                  TEXT PRIMARY KEY,                     -- 'bedrock_usd_total'
  value                REAL NOT NULL
);
INSERT INTO budget (key, value) VALUES
  ('bedrock_usd_total', 0.0),
  ('bedrock_usd_ceiling', 500.0),   -- hard cap (configurable)
  ('haiku_in_per_mtok', 1.00),
  ('haiku_out_per_mtok', 5.00),
  ('haiku_batch_in_per_mtok', 0.50),
  ('haiku_batch_out_per_mtok', 2.50),
  ('sonnet_in_per_mtok', 3.00),
  ('sonnet_out_per_mtok', 15.00);
```

---

## Bedrock call strategy

**Primary** — Claude Haiku 4.5 via cross-region inference profile.

```python
modelId = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
temperature = 0.0
maxTokens = 400
tool_use: classify_page (schema in poc/prompts.py)
```

- On-demand Converse for first pass (simpler, observable, no batch-job complexity).
- Throttle self-limited at `MAX_CONCURRENT_BEDROCK = 30` (env var, tunable without code change).
- Exponential backoff on `ThrottlingException`, `ServiceUnavailableException`, `InternalServerException` with max 4 retries.
- Budget guard: after every call, increment `budget.bedrock_usd_total`. If > ceiling → `cancel_all_workers()` and log `BUDGET_EXCEEDED`.

**Retry tier** — Claude Sonnet 4.6 via cross-region profile.

```python
modelId = "us.anthropic.claude-sonnet-4-6"
```

Triggered when any of:
- `confidence_overall < 0.7`
- Tier-1 format validation rejected Haiku's output (name regex fail, OCR garbage, etc.)
- Haiku `page_class` conflicts with a tier-0 heuristic prediction (bug indicator)

If Sonnet also returns `confidence < 0.6` → push to HITL.

**Batch Inference** — Phase 1.5 optimization, not in the initial build. Once the pipeline is validated on a dry-run, the exact same tool_use prompt can be submitted via `CreateModelInvocationJob` for 50% off. Adding this later requires zero architecture change — only a second classify worker mode.

**Index parse tier (added 2026-04-21)** — `poc/workers/index_parse.py`. Runs once per roll after classify finishes. Input: all frames where `pages.page_class = 'student_records_index'`. One Haiku call per index frame with a specialized prompt:

```
You are parsing a STUDENT RECORDS INDEX page from Osceola microfilm.
Extract every row into structured JSON using the parse_index tool.

Handle both layout families:
- D1 HIGHLANDS-style: columns # | LAST | FIRST | MIDDLE | DOB | SEC | OTHER | Roll | File
- D2 OHS OSCEOLA-style: columns LAST | FIRST | MIDDLE | DOB | TRANS | WITH | GRAD | DATE | BE | CR | ES | FILE | FRAME

Rows are handwritten. For blank or unreadable cells use "". Do not
hallucinate names. Preserve exact alphabetical order.
```

Tool schema returns `rows = [{last, first, middle, dob, enroll_date}, ...]`. Parse confidence comes from `usage.stopReason = "tool_use"` + row-count sanity check. Rows flowed into `roll_index_entries`. Expected ~15 index frames per roll × 100 rolls × ~$0.008 each = **~$12 total**.

---

## Heuristics scope (locked from brainstorm)

**In (POC v1):**

Tier 0: H0.1 blank, H0.2 resolution-target pHash, H0.3 vendor-letterhead pHash, H0.5 orientation normalization.
Tier 1: H1.1 name regex, H1.2 OCR-garbage blocklist, H1.3 numeric-prefix strip, H1.4 DOB format, H1.5 roll-number sanity.
Tier 2: H2.1 surname snap, H2.2 first-name snap, H2.3 OCR-confusion pairs, H2.4 within-packet Levenshtein reconcile.
Tier 3: H3.1 START/END bracket, H3.2 roll-size sanity, H3.3 transition rules, H3.4 packet-size distribution, H3.5 frame contiguity.
Tier 4: H4.1 district-style, H4.2 vendor, H4.3 frame-position priors.
Tier 5: H5.2 Sonnet retry on mid-band (already in Bedrock call strategy).

**Out (deferred to Phase 2 or beyond):** H0.4 Hough-line clapperboard, H2.5 cross-packet merge, H4.4 previous-page name prior, H5.1 two-pass split, H5.3 self-consistency probe, H5.4 packet-level re-extraction.

Every tier-0 / tier-1 / tier-2 heuristic is a pure function in its own module. Unit tests cover happy path + 2–3 adversarial inputs per rule. No network, no SQLite dependency in heuristic modules — they operate on PNG bytes and structured dicts only.

---

## HITL UI (Streamlit)

Single `poc/streamlit_app.py` file. Three sections:

### 1. Login
- `streamlit-authenticator` yaml-based users.
- bcrypt-hashed passwords.
- Session cookie valid 8 hours.
- Failed-login counter + lockout after 5 attempts.

### 2. Queue dashboard
- Top bar: pending HITL count, today's resolved count, oldest pending age.
- Filters: district, roll, reason (low_conf / format_reject / bracket_missing), age.
- Sort: oldest first (default).
- Click row → detail view.

### 3. Detail view
- Left column: image preview at 600px wide via S3 presigned URL (15-min TTL).
- Right column:
  - Predicted class + name + confidence.
  - Heuristics fired (for context).
  - Text input for corrected `last` / `first` / `middle`.
  - Class radio buttons.
  - Three buttons: **Approve** (accept prediction), **Save edits**, **Reject / Not a student page**.
- Submit → `POST /hitl/{hitl_id}/resolve` → SQLite update → auto re-trigger aggregator for affected packet only.
- Next unreviewed item auto-loaded on submit.

Image preview logic uses `s3_client.generate_presigned_url()` with the Servflow-image1 key. Never embed raw image bytes in the Streamlit session state — too heavy.

---

## FastAPI endpoints

```
POST /rolls/{roll_id}/start         → enqueue roll. Idempotent. 202 Accepted.
POST /rolls/{roll_id}/cancel        → mark status=cancelled, workers drain. 200.
GET  /rolls                         → list all rolls + status.
GET  /rolls/{roll_id}               → detailed status.
GET  /rolls/{roll_id}/progress      → { pct, pages_done, pages_total, eta_iso, cost_usd }
GET  /rolls/{roll_id}/summary       → aggregated results, packet count, accuracy (if GT present).
GET  /rolls/{roll_id}/manifest.csv  → stream manifest CSV.

POST /hitl/{hitl_id}/resolve        → { action, corrections }. Body validated against pydantic schema.
GET  /hitl/pending                  → list of pending items with S3 signed URLs.
GET  /hitl/stats                    → aggregate counts.

GET  /budget                        → current spend vs ceiling.
GET  /health                        → healthcheck for compose + LB.
GET  /metrics                       → Prometheus-format counters.
```

All mutating endpoints require Bearer token (`HITL_API_TOKEN` env var). Streamlit UI uses the same token internally.

---

## Deployment

### Dockerfile (sketch)

```dockerfile
FROM python:3.11-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
      libjpeg-dev zlib1g-dev libtiff-dev libopenjp2-7-dev \
      libwebp-dev tcl8.6-dev tk8.6-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
VOLUME /data
EXPOSE 8000 8501
```

### docker-compose.yml (sketch)

```yaml
services:
  pipeline:
    build: .
    command: uvicorn poc.api:app --host 0.0.0.0 --port 8000
    env_file: [.env.s3, .env.bedrock]
    volumes:
      - ./data:/data
    restart: unless-stopped

  hitl:
    build: .
    command: streamlit run poc/streamlit_app.py --server.port 8501 --server.address 0.0.0.0
    env_file: [.env.s3, .env.bedrock]
    environment:
      - FASTAPI_URL=http://pipeline:8000
    volumes:
      - ./data:/data
      - ./auth_users.yaml:/app/auth_users.yaml:ro
    depends_on: [pipeline]
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on: [pipeline, hitl]
    restart: unless-stopped

volumes:
  caddy_data:
```

### Caddyfile (sketch)

```
osceola.example.com {
  handle_path /api/* {
    reverse_proxy pipeline:8000
  }
  reverse_proxy hitl:8501
  encode gzip
  header X-Frame-Options DENY
  header Strict-Transport-Security "max-age=31536000"
}
```

Host environment is **deferred** (user decision pending). Spec is env-agnostic: any Docker-compatible host works. EC2 us-west-2 m6i.xlarge is the recommended baseline but not locked.

---

## n8n workflows (external, at `dev-n8n.visualgraphx.com`)

1. **Bulk-start** — manual webhook trigger. Loops 100 rolls (from a CSV node). Calls `POST /api/rolls/{id}/start` with parallel 3 at a time. On 202 responses, records in a tracking table node.
2. **Progress-watcher** — cron every 15 min. Queries `GET /api/rolls/{id}/progress` for all `status=classifying` rolls. If `pct` unchanged after 1 hour → Slack alert.
3. **HITL-notifier** — webhook `POST /n8n/hitl-backlog` from pipeline when `hitl_open > 50`. Posts to Slack with Streamlit link.
4. **Completion-mail** — webhook fires when all rolls done. Pulls `/rolls/*/summary` + `report.md`, renders email, sends via SMTP node.

n8n config stays in the n8n instance. The pipeline never depends on n8n running — it's an outer observer/trigger.

---

## Cost & runtime

| Line | Pages / calls | Tokens | Cost |
|---|---|---|---|
| Pre-LLM skipped by Tier 0 heuristics | ~15K | — | $0 |
| Haiku 4.5 classify on-demand | 203K | 1,700 in / 110 out avg | ~$210 |
| Sonnet 4.6 retry (10–15% band) | ~22K | 1,700 in / 67 out avg | ~$145 |
| **Index parse (new 2026-04-21)** | ~1,500 index frames × Haiku | ~2,900 in / 900 out avg | **~$12** |
| Index prior re-call (H4.5, ~5% of student_cover) | ~2,000 | 2,500 in / 120 out avg | ~$6 |
| Docker host (EC2 m6i.xlarge, 10 hr) | — | — | ~$2 |
| S3 egress (same-region) | — | — | $0 |
| Storage (EBS 50 GB × 10 hr) | — | — | $0.10 |
| **AWS total** | | | **~$375** |
| HITL human time (expected rate 1%, was 2%) | ~2,200 pages × 15 s | | ~9 hrs |

Runtime ~6–10 hours for bulk. Dry-run on D1 ROLL 001 (1,924 frames) ~15 minutes at ~$3.

Switching Haiku from on-demand to Batch Inference cuts $210 → $105 (~$255 total) at the cost of 2–24 hours async turnaround. Baseline uses on-demand for observability; Batch is Phase 1.5 flip.

---

## Accuracy stack

Base Haiku 4.5 ~85% page-level → heuristic stack (including new index-snap H2.7 + alpha-monotonic H3.7 + index prior H4.5) + packet vote + Sonnet retry → target **≥ 97% page / ≥ 99% packet** before HITL. HITL closes the remaining gap.

The lift from 92% (pre-2026-04-21) to 97% comes from the index-snap heuristic alone: once we have the canonical per-roll name allowlist, any extracted name that fails Levenshtein ≤ 2 against the allowlist is caught — eliminating most OCR-garbage class of errors.

Numbers are estimates; confirm with the **D1 dry-run gate** (see below) before authorizing bulk.

---

## D1 dry-run gate (go/no-go)

Before bulk:

1. Run full pipeline on ROLL 001 (1,924 frames, including the ~8 index frames confirmed at frames 00008, 00011, 00012, 00014, 00018, 00019, 00022 per `samples/index_probe/broad/SUMMARY.md`).
2. Run `eval.py` against cleaned D1 GT (419 PDFs, after filtering ~14% placeholders / garbage).
3. Accept criteria (tightened 2026-04-21 after index pattern confirmed):
   - `accuracy_partial ≥ 0.92` (packet-level name match with Levenshtein ≤ 2)
   - `accuracy_exact ≥ 0.80`
   - HITL rate ≤ 5%
   - Index coverage = `full` (all index frames parsed into `roll_index_entries`)
   - Total cost for 1,924 frames ≤ $5
4. If pass → authorize bulk. If fail → iterate on prompt + heuristics, rerun dry, do not burn bulk budget.

---

## Eval with cleaned ground truth

`eval.py` must first clean D1 GT:

- Strip `(LAST)`, `(FIRST)`, `(MIDDLE)`, `MIDDL)`, `BIRTH`, `COUNTY`, `SEX`, `PLACE`, `CITY`, `NAME` tokens from filename.
- Drop filenames with only digits, or single-word non-name garbage (`1959.pdf`, `Birtha.pdf`, `AN …pdf`).
- Exclude ROLL 003/005/006 (sham batch merges).
- Case-normalize to UPPER for comparison.
- Preserve `_N` dup-suffixed filenames as legitimate same-name students.

Scoring:
- `exact` = `(UPPER_last, UPPER_first, UPPER_middle)` all match
- `partial` = `(UPPER_last, UPPER_first)` match with Levenshtein ≤ 2 on each

Report: precision, recall, F1 at exact + partial levels, plus per-district breakdown once GT exists for D2–7.

---

## Security + data handling

- TIFs + PDFs are FERPA-protected. Docker host must run in a private network or with network ACL restricting inbound to Caddy HTTPS only.
- PNG cache at `/data/cache/` is ephemeral and purged on roll completion (retention 7 days for HITL re-preview, then auto-evicted).
- SQLite backup via `VACUUM INTO /data/backup/osceola_YYYYMMDD.db` at end of each roll.
- No student PII in logs (log lines redact `student_last`/`student_first` in INFO level; ERROR level preserves for debugging).
- Credentials via `.env.s3` + `.env.bedrock`, mounted read-only into container. Host file permissions `0600`.
- HITL bearer token rotated per deployment (`HITL_API_TOKEN`).
- TLS via Caddy automatic Let's Encrypt.

---

## Observability

- **Logs**: structured JSON, one line per event, correlated by `roll_id` + `page_id`. Written to `/data/logs/pipeline.log` with daily rotation.
- **Metrics**: Prometheus at `/metrics`. Key gauges:
  - `osceola_pages_total{status="..."}`
  - `osceola_bedrock_cost_usd`
  - `osceola_hitl_open`
  - `osceola_roll_in_progress`
  - `osceola_throttle_events_total`
- **SQLite `run_log`** table captures major events for in-DB audit without external tooling.
- **Progress API** gives the operator live visibility without log tailing.

---

## Testing strategy

- **Unit** — every heuristic module, schema validator, grouping algo, eval scorer. Target > 90% branch coverage on `heuristics/`, `grouping.py`, `eval.py`. Mock boto3 everywhere.
- **Integration** — real SQLite, fake S3 (via `moto`), mocked Bedrock. Run the pipeline end-to-end on 5 fixture TIFs.
- **Smoke** — gated by `BEDROCK_SMOKE=1`. Hits real Bedrock on 5 fixtures, confirms round-trip. Runs in CI nightly, not per-PR.
- **Dry-run** — operator script to run ROLL 001 end-to-end (real Bedrock, real S3) before bulk.

Pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.smoke`.

---

## Open questions (client sign-off needed)

1. **Runtime host** — EC2 us-west-2 (recommended) vs client on-prem vs Fargate? Decision deferred.
2. **GT-cleaning policy** — client must confirm acceptable to drop ~14% garbage filenames from eval baseline.
3. **Eval set curation** — operator hand-labels 100–200 pages across D2–D7 so we can measure accuracy outside D1. Who does the labeling work, and on what timeline?
4. **Operator auth** — streamlit-authenticator yaml is fine for 1–5 ops. For 10+ operators, switch to OAuth (Google / Okta) later.
5. **HITL backlog SLA** — how fast must the queue drain? 24 hr? 7 days? Decides whether we need multi-operator shift model.
6. **Reel-number cross-reference** — do we ship the reel→folder mapping back to client in `manifest.csv`? (Recommend yes.)
7. **Data retention** — how long does `/data/` stay on the host after bulk completes? SQLite audit file ship-to-client + then wipe container?
8. **≥50-sample bake-off** — still worth running before bulk to confirm Haiku choice with corrected Style B fixture. Blocks dry-run? Or run in parallel?
9. **Budget ceiling** — default $500 hard cap. Client preference?
10. **Docker registry** — private ECR vs Docker Hub private vs simple build-on-host?

---

## Out-of-scope (explicit)

- Building the Phase 2 Step Functions stack.
- Replacing n8n as the HITL UI (Streamlit owns HITL here).
- Real-time Bedrock quota auto-tuning.
- Multi-region failover.
- Client-side re-training / fine-tuning.
- Email integrations beyond n8n-driven notifications.

---

## Change log

- 2026-04-21 (initial): simple pipeline (Haiku + Sonnet only). Heuristics locked from `docs/heuristics-brainstorm.md`. EC2 env deferred. Streamlit HITL locked; HTMX fallback noted. Supersedes `2026-04-18-osceola-phase1-poc-design.md`.
- 2026-04-21 (revision — later same day): reinstated `student_records_index` as 7th page class after 100-roll broad probe (see `samples/index_probe/broad/SUMMARY.md`) confirmed the pattern is universal (93/100 rolls carry ≥ 1 index frame). Added per-roll index-parse stage to the pipeline flow between classify and aggregate. Added `roll_index_entries` SQLite table. Added heuristics H2.7 (index-snap), H3.7 (alphabetical-monotonic), H4.5 (index prior on ambiguous frames). Revised accuracy target from 92% / 98% to **97% page / 99% packet**. Added ~$12 index-parse cost. Updated total budget to ~$400 and dry-run gate to ≥ 92% partial (up from 90%).
