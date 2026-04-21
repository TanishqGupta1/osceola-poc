# Osceola Production Pipeline — Simplified Design Spec (v2)

**Date:** 2026-04-21
**Scope:** Phase 1 production pipeline that processes the full 218,577 TIFs end-to-end with a client-facing HITL UI.
**Supersedes:** `2026-04-21-osceola-production-pipeline-v1-full.md` (kept as archive). This v2 simplifies: no n8n orchestration, no FastAPI, no Caddy, no Prometheus, no Alembic, no Docker-compose. Single Python process + Streamlit + SQLite.
**Companions:** `../../heuristics-brainstorm.md`, `../../osceola-poc-discussion.md`.

## Goal

One Python project that:

1. Reads 218,577 TIFs from `s3://servflow-image-one/Osceola Co School District/Input/`.
2. Classifies each frame (7 classes including `student_records_index`).
3. Parses every index page into a canonical per-roll student allowlist.
4. Extracts student names from cover pages and cross-checks against the allowlist.
5. Groups frames into per-student packets, generates one PDF per student, uploads to `.../Output/` mirroring input folder structure.
6. Queues low-confidence frames for human review via a Streamlit UI.
7. Ships a single SQLite audit file to the client with every decision recorded.

Target: **≥ 97% packet-level partial name match before HITL, ≥ 99% after review**, total cost **≤ $700 on-demand / ~$475 with Haiku Batch**, runtime ~6–10 hours.

## Non-goals

- FastAPI control plane. No external callers. CLI triggers runs.
- Caddy / HTTPS / Let's Encrypt. Operator accesses Streamlit via SSH tunnel or localhost.
- n8n orchestration. A shell command starts the run; a shell command serves HITL. Slack is optional.
- Multi-container docker-compose. One Python process. Optional Dockerfile for reproducibility.
- Prometheus / Alembic / multi-operator locking / bearer-token rotation — YAGNI for a one-shot job.
- Amazon Nova / Mistral / Llama / Opus / Textract — dropped after bake-offs.
- Step Functions / Lambda / DynamoDB — deferred to Phase 2.

## Deliverables

1. Python package + pinned `requirements.txt` + `Dockerfile` (optional).
2. Populated `s3://.../Output/<district>/<roll>/Last, First MI.pdf` matching SOW layout.
3. `osceola.db` SQLite file — ship to client, one-file audit trail.
4. `manifest_<roll>.csv` per roll (every frame's class, name, confidence, heuristics fired, HITL status).
5. `report.md` auto-generated at end (accuracy vs cleaned D1 GT, cost, token counts, HITL volume).

---

## Architecture

One Python process, one SQLite file, one Streamlit UI. Runs on any host with Python 3.11 + 50 GB disk.

```
┌─ Host (EC2 m6i.xlarge, laptop, or on-prem) ──────────────┐
│                                                          │
│  python -m osceola pipeline run-all                      │
│    • fetch (S3 stream, in-mem)                           │
│    • classify (Haiku 4.5)                                │
│    • retry (Sonnet 4.6 on low-conf)                      │
│    • heuristics T0-T4                                    │
│    • index parse → roll_index_entries                    │
│    • group + index-snap + PDF gen                        │
│    • upload to S3                                        │
│                                                          │
│  streamlit run hitl.py                                   │
│    • login (basic password from env)                     │
│    • queue dashboard                                     │
│    • image + edit form                                   │
│                                                          │
│  osceola.db   (SQLite WAL mode)                          │
│  .env         (Servflow-image1 — S3 only)                │
│  .env.bedrock (tanishq — Bedrock only)                   │
│  corpora/     (surnames, first names)                    │
└──────────────────────────────────────────────────────────┘
                   ▲
                   │ boto3 (two separate clients, two creds)
                   ▼
          ┌────────────────────┐
          │ s3://servflow-...  │
          │    (us-west-2)     │
          │  Input/ → Output/  │
          └────────────────────┘
```

Dual AWS creds kept strictly separate:

| Principal | Account | Used for |
|---|---|---|
| `Servflow-image1` | `523109542532` | S3 read + write |
| `tanishq` | `690816807846` | Bedrock invoke |

Two boto3 clients constructed at startup, never mixed.

## Why so simple

- 218K frames × ~3 s/frame ÷ 30 concurrent threads ≈ **6 hours**. Overnight.
- SQLite WAL mode supports 1 writer + many readers, which is exactly our pattern.
- Streamlit reads SQLite directly. No API layer needed for single-operator HITL.
- Crash → rerun the CLI, workers skip rows already marked `status=done` in SQLite.
- One audit file the client can open in DB Browser to inspect every decision.

---

## Pipeline flow — per roll

Two stages: **classify-all-frames** then **aggregate**.

### Stage 1 — classify all frames

For every TIF in the roll's S3 prefix (skipped if SQLite already has `status=done`):

1. Fetch bytes from S3 (streaming, in-memory).
2. Pillow: TIF → PNG, max side 1500 px, mode RGB.
3. **Tier 0 heuristics** (pre-LLM):
   - Blank detector: pixel std-dev < 8 → label `roll_leader`, skip LLM.
   - pHash vs resolution-target exemplar → label `roll_leader`.
   - pHash vs vendor-letterhead exemplars (TIMS, White's) → label `roll_leader`.
   - Rotation: aspect-ratio heuristic; rotate 90° if tall-and-narrow.
4. **Tier 4 priors** injected into the system prompt:
   - District-style hint (D1/D3 → Style B separator; others → Style A).
   - Frame-position hint (first 7 → "likely leader/separator", middle → "likely student", last 5 → "likely END separator/trailing leader").
5. **Classify** via Bedrock Converse + `tool_use`:
   - Model: `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
   - `temperature=0.0`, `maxTokens=400`.
   - Returns: `{page_class, separator, student, roll_meta, confidence_overall, confidence_name, notes}`.
6. **Tier 1 format validation**:
   - Name regex, OCR-garbage blocklist, numeric-prefix strip, DOB regex.
   - Fail → `retry_needed=true`.
7. **Retry** (if `confidence_overall < 0.7` OR Tier-1 failed):
   - Model: `us.anthropic.claude-sonnet-4-6`.
   - Same image + prompt. Overwrites Haiku output if Sonnet confidence is higher.
8. **Tier 2 corpus-snap** on name fields (surname/first-name dictionaries, Levenshtein ≤ 1 snap, OCR-confusion pairs).
9. Persist to SQLite `pages` with full audit trail (`heuristics_fired`, `primary_model`, `retry_model`, tokens, latency).

### Stage 2 — aggregate (runs per roll after all frames classified)

10. **Index parse**: `SELECT page_id FROM pages WHERE roll_id=? AND page_class='student_records_index' ORDER BY frame`. For each index frame, call Haiku with the `INDEX_PARSE_PROMPT` + `parse_index` tool schema. Rows inserted into `roll_index_entries`.
11. **Compute canonical allowlist** for the roll = distinct `(last, first, middle, dob)` tuples from `roll_index_entries`.
12. **Group covers into packets** via name-change detection on `student_*` frames between START and END separators, with within-packet Levenshtein reconcile (H2.4).
13. **Index-snap (H2.7)**: each packet's extracted name → nearest allowlist entry, Levenshtein ≤ 2 on `(last, first)`. DOB cross-check when populated. No match → flag HITL `reason=no_index_match`.
14. **Index prior (H4.5)** for still-ambiguous covers (primary confidence < 0.85 AND no confident index match): one extra Haiku call passing the top-5 nearest allowlist candidates as hints. This replaces the earlier generic Sonnet retry for these frames — it's strictly cheaper and more accurate (constrained multiple-choice).
15. **Tier 3 structural checks**: START/END bracket sanity, packet size distribution, alphabetical-monotonic (H3.7) against roll's sorted index.
16. **HITL routing**: all of `confidence<0.6`, Tier-1 format-reject after retry, `no_index_match`, `alpha_break`, model-disagreement → push to `hitl_queue`.
17. **PDF generation**: for each packet, load the TIFs in frame order, `Pillow.save(out_pdf, save_all=True, append_images=[...])` → upload to `s3://.../Output/<district>/<roll>/Last, First MI.pdf` (atomic write via `.tmp` key + rename).
18. **Manifest**: write `manifest_<roll>.csv` locally and upload to S3 next to the PDFs.
19. Mark `rolls.status=done`.

### HITL resolution (Streamlit)

- Operator picks item from queue.
- Approves / Edits / Rejects via form.
- Submission updates SQLite `pages` + `packets` + `hitl_queue`.
- If packet name changed → regenerate the affected PDF, replace in S3.

Every step is idempotent against SQLite row state. Any crash → rerun the CLI, workers resume.

---

## File structure

```
osceola-pipeline/
├── Dockerfile                    # optional, python:3.11-slim
├── requirements.txt              # pinned
├── pyproject.toml
├── .env.example                  # Servflow-image1 creds template
├── .env.bedrock.example          # tanishq creds template
├── README.md                     # ops runbook
│
├── osceola/
│   ├── __init__.py
│   ├── __main__.py               # CLI dispatcher: dry-run | run-all | run-roll | serve-hitl
│   ├── config.py                 # env loading, model IDs, budget ceiling
│   ├── schemas.py                # pydantic models
│   ├── db.py                     # SQLite schema + typed queries (single writer)
│   ├── s3io.py                   # Servflow-image1 client (streaming + signed URLs)
│   ├── bedrock.py                # Converse wrapper — ALL calls go through converse_tracked() which logs every invocation to SQLite.bedrock_calls with tokens + cost + latency + stop_reason + error
│   ├── convert.py                # TIF → PNG bytes (Pillow)
│   ├── prompts.py                # CLASSIFY_PROMPT, INDEX_PARSE_PROMPT, tool schemas
│   │
│   ├── heuristics/
│   │   ├── __init__.py
│   │   ├── tier0.py              # blank, pHash, rotation
│   │   ├── tier1.py              # name regex, garbage blocklist, DOB format
│   │   ├── tier2.py              # corpus snap + index-snap (H2.7)
│   │   ├── tier3.py              # bracket, size, transitions, alpha-monotonic
│   │   └── tier4.py              # district/vendor/position priors + index prior (H4.5)
│   │
│   ├── pipeline.py               # orchestrator: classify loop + aggregator
│   ├── index_parse.py            # per-roll index deep-parse
│   ├── group.py                  # name-change packet builder + Levenshtein
│   ├── pdfgen.py                 # Pillow-based TIF→multipage-PDF
│   ├── eval.py                   # GT-cleaner + scoring
│   ├── manifest.py               # roll manifest CSV writer
│   ├── report.py                 # final report.md
│   │
│   └── hitl.py                   # Streamlit single-file UI
│
├── corpora/
│   ├── surnames_us_census.txt    # public domain
│   ├── first_names_us_census.txt
│   └── surnames_d1_cleaned.txt   # built from D1 GT (FERPA, gitignored)
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── smoke/                    # opt-in real Bedrock
│
└── scripts/
    ├── build_surname_corpus.py
    ├── dry_run.sh
    └── export_audit.sh
```

**Boundary rules:**

- `heuristics/` modules import nothing from AWS or SQLite — pure functions on PNG bytes and dicts.
- `db.py` is the only module that writes to SQLite. Everything else calls typed accessors.
- `config.py` is the only module that reads env vars.
- `hitl.py` talks to SQLite via `db.py` (read-only except via `db.resolve_hitl()`).
- `pipeline.py` glues it all together. Target < 500 lines.

---

## SQLite schema

WAL mode on. Single-writer (pipeline process or hitl.py, never both at once in this simplified design — HITL runs after bulk classify finishes, or CLI pauses for HITL drain).

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE rolls (
  roll_id              TEXT PRIMARY KEY,              -- "OSCEOLA SCHOOL DISTRICT-4/ROLL 045"
  district             INTEGER NOT NULL,
  roll_num             TEXT NOT NULL,
  n_frames             INTEGER NOT NULL,
  status               TEXT NOT NULL CHECK(status IN (
                         'queued','classifying','aggregating','done','failed')),
  started_at           DATETIME,
  completed_at         DATETIME,
  pages_done           INTEGER NOT NULL DEFAULT 0,
  pages_flagged        INTEGER NOT NULL DEFAULT 0,
  packets_created      INTEGER NOT NULL DEFAULT 0,
  cost_usd             REAL NOT NULL DEFAULT 0.0,
  tokens_in            INTEGER NOT NULL DEFAULT 0,
  tokens_out           INTEGER NOT NULL DEFAULT 0,
  index_coverage       TEXT CHECK(index_coverage IN (
                         'pending','none','partial','full')),
  index_pages_parsed   INTEGER NOT NULL DEFAULT 0,
  index_entries_total  INTEGER NOT NULL DEFAULT 0,
  notes                TEXT
);

CREATE TABLE pages (
  page_id              TEXT PRIMARY KEY,              -- "d4r045_00097"
  roll_id              TEXT NOT NULL REFERENCES rolls(roll_id),
  frame                INTEGER NOT NULL,
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
  confidence_overall   REAL,
  confidence_name      REAL,
  primary_model        TEXT,
  retry_model          TEXT,
  heuristics_fired     TEXT,                          -- JSON array
  latency_ms           INTEGER,
  tokens_in            INTEGER,
  tokens_out           INTEGER,
  notes                TEXT,
  status               TEXT NOT NULL CHECK(status IN (
                         'pending','done','flagged',
                         'hitl_open','hitl_resolved','failed')),
  processed_at         DATETIME,
  UNIQUE(roll_id, frame)
);
CREATE INDEX idx_pages_roll ON pages(roll_id, frame);
CREATE INDEX idx_pages_status ON pages(status);

CREATE TABLE packets (
  packet_id            TEXT PRIMARY KEY,              -- "d4r045_001"
  roll_id              TEXT NOT NULL REFERENCES rolls(roll_id),
  student_last         TEXT NOT NULL,
  student_first        TEXT NOT NULL,
  student_middle       TEXT,
  frames_json          TEXT NOT NULL,                 -- JSON [97,98,99]
  avg_confidence       REAL,
  flagged              INTEGER NOT NULL DEFAULT 0,
  hitl_reviewed        INTEGER NOT NULL DEFAULT 0,
  pdf_s3_key           TEXT,
  pdf_generated_at     DATETIME,
  status               TEXT NOT NULL CHECK(status IN (
                         'pending','pdf_generated','flagged',
                         'hitl_open','hitl_resolved'))
);
CREATE INDEX idx_packets_roll ON packets(roll_id);

CREATE TABLE hitl_queue (
  hitl_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type          TEXT NOT NULL CHECK(entity_type IN ('page','packet')),
  entity_id            TEXT NOT NULL,
  reason               TEXT NOT NULL,                 -- low_confidence | format_reject | no_index_match | alpha_break | model_disagree
  created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at          DATETIME,
  resolution           TEXT                            -- JSON of operator's edits
);
CREATE INDEX idx_hitl_open ON hitl_queue(reviewed_at) WHERE reviewed_at IS NULL;

CREATE TABLE roll_index_entries (
  entry_id             INTEGER PRIMARY KEY AUTOINCREMENT,
  roll_id              TEXT NOT NULL REFERENCES rolls(roll_id),
  source_page_id       TEXT NOT NULL REFERENCES pages(page_id),
  row_order            INTEGER NOT NULL,
  last_name            TEXT NOT NULL,
  first_name           TEXT NOT NULL,
  middle_name          TEXT,
  dob                  TEXT,
  enroll_date          TEXT,
  parsed_model         TEXT NOT NULL,
  parse_confidence     REAL
);
CREATE INDEX idx_rie_roll_name ON roll_index_entries(roll_id, last_name, first_name);

CREATE TABLE run_log (
  log_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  level                TEXT NOT NULL,                 -- INFO|WARN|ERROR
  component            TEXT NOT NULL,
  roll_id              TEXT,
  page_id              TEXT,
  message              TEXT NOT NULL
);

CREATE TABLE bedrock_calls (
  call_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  purpose              TEXT NOT NULL,                 -- classify | retry | index_parse | index_prior
  model_id             TEXT NOT NULL,                 -- full inference-profile ID (e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0)
  mode                 TEXT NOT NULL CHECK(mode IN ('on_demand','batch')) DEFAULT 'on_demand',
  roll_id              TEXT,
  page_id              TEXT,
  retry_attempt        INTEGER NOT NULL DEFAULT 0,    -- 0 = primary, 1+ = retries after throttle
  tokens_in            INTEGER NOT NULL DEFAULT 0,
  tokens_out           INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens    INTEGER NOT NULL DEFAULT 0,    -- prompt-cache reads if used (future)
  cache_write_tokens   INTEGER NOT NULL DEFAULT 0,
  usd_in               REAL NOT NULL DEFAULT 0.0,     -- computed at insert time
  usd_out              REAL NOT NULL DEFAULT 0.0,
  usd_total            REAL NOT NULL DEFAULT 0.0,
  latency_ms           INTEGER NOT NULL DEFAULT 0,
  stop_reason          TEXT,                          -- tool_use | end_turn | max_tokens | throttling | error
  error                TEXT                           -- NULL unless call failed
);
CREATE INDEX idx_bc_ts       ON bedrock_calls(ts);
CREATE INDEX idx_bc_roll     ON bedrock_calls(roll_id, ts);
CREATE INDEX idx_bc_page     ON bedrock_calls(page_id);
CREATE INDEX idx_bc_model    ON bedrock_calls(model_id);
CREATE INDEX idx_bc_purpose  ON bedrock_calls(purpose);
```

`bedrock_calls` is the source of truth for every Bedrock invocation. Every Converse call — classify, retry, index parse, index prior — inserts one row before returning to the caller. Throttled retries each get their own row with `retry_attempt` incremented. Failed calls still insert a row with `error` populated and `tokens_in=tokens_out=0` so cost math is honest.

The `tokens_in`/`tokens_out`/`cost_usd` columns on `rolls` and `pages` are denormalized caches for fast dashboard queries — computed by a trigger or an explicit `db.refresh_roll_totals(roll_id)` call after each roll finishes. Ground truth always lives in `bedrock_calls`.

No budget table, no migrations, no packet status beyond what's used. Keep it lean.

---

## Bedrock call tracking (every invocation logged)

Every Bedrock Converse call flows through `osceola/bedrock.py::converse_tracked()`. Wrapper is the ONLY legal way to hit Bedrock — naked `client.converse()` is banned by code review.

Pricing table in `osceola/config.py`:

```python
BEDROCK_PRICING = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    # On-demand rates us-west-2 (2026-04):
    "us.anthropic.claude-haiku-4-5-20251001-v1:0":            (1.00,  5.00),
    "us.anthropic.claude-sonnet-4-6":                         (3.00, 15.00),
    # Batch Inference 50% discount (use when mode='batch'):
    "us.anthropic.claude-haiku-4-5-20251001-v1:0::batch":     (0.50,  2.50),
    "us.anthropic.claude-sonnet-4-6::batch":                  (1.50,  7.50),
}
```

Wrapper contract (pseudocode):

```python
def converse_tracked(
    *,
    purpose: Literal["classify","retry","index_parse","index_prior"],
    model_id: str,
    mode: Literal["on_demand","batch"] = "on_demand",
    roll_id: str | None = None,
    page_id: str | None = None,
    retry_attempt: int = 0,
    **converse_kwargs,
) -> dict:
    t0 = time.monotonic()
    tokens_in = tokens_out = 0
    stop_reason = error = None
    try:
        resp = bedrock_client.converse(modelId=model_id, **converse_kwargs)
        usage = resp.get("usage", {})
        tokens_in  = usage.get("inputTokens", 0)
        tokens_out = usage.get("outputTokens", 0)
        stop_reason = resp.get("stopReason")
        return resp
    except ClientError as e:
        error = f"{e.response['Error']['Code']}: {str(e)[:200]}"
        stop_reason = "error"
        raise
    finally:
        key = f"{model_id}::{mode}" if mode != "on_demand" else model_id
        in_rate, out_rate = BEDROCK_PRICING[key]
        usd_in  = tokens_in  / 1e6 * in_rate
        usd_out = tokens_out / 1e6 * out_rate
        db.insert_bedrock_call({
            "purpose": purpose, "model_id": model_id, "mode": mode,
            "roll_id": roll_id, "page_id": page_id,
            "retry_attempt": retry_attempt,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "usd_in": usd_in, "usd_out": usd_out, "usd_total": usd_in + usd_out,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "stop_reason": stop_reason, "error": error,
        })
```

Key properties:
- **Every call is logged**, including throttled retries (distinct rows with incrementing `retry_attempt`).
- **Failed calls logged** too (tokens=0, `error` populated) — so retry-rate is observable.
- **Cost computed at insert** — no deferred math, no rate-change drift in history.
- **Unit-testable**: pass a mocked `bedrock_client`, inspect `db.insert_bedrock_call` fixtures.
- **Live budget guard**: a ~50-line async task runs `SELECT SUM(usd_total) FROM bedrock_calls` every 60 s and halts workers if over ceiling.

### Useful cost queries

Available as `osceola/report.py::cost_queries`:

```sql
-- Total spend
SELECT SUM(usd_total) FROM bedrock_calls;

-- By model
SELECT model_id, COUNT(*) AS calls, SUM(tokens_in), SUM(tokens_out), SUM(usd_total)
FROM bedrock_calls GROUP BY model_id ORDER BY SUM(usd_total) DESC;

-- By purpose (classify vs retry vs index_parse vs index_prior)
SELECT purpose, COUNT(*), SUM(usd_total), AVG(latency_ms)
FROM bedrock_calls GROUP BY purpose;

-- By roll (find expensive rolls)
SELECT roll_id, COUNT(*) AS calls, SUM(usd_total) AS spend
FROM bedrock_calls GROUP BY roll_id ORDER BY spend DESC LIMIT 20;

-- Error rate
SELECT model_id, stop_reason,
       COUNT(*) AS n,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER(PARTITION BY model_id), 2) AS pct
FROM bedrock_calls GROUP BY model_id, stop_reason;

-- Hour-by-hour burn rate
SELECT strftime('%Y-%m-%d %H:00', ts) AS hour,
       COUNT(*), SUM(usd_total), SUM(tokens_in), SUM(tokens_out)
FROM bedrock_calls GROUP BY hour ORDER BY hour;

-- Retry amplification (how many calls per unique page?)
SELECT page_id, COUNT(*) AS calls, SUM(usd_total)
FROM bedrock_calls WHERE page_id IS NOT NULL
GROUP BY page_id HAVING COUNT(*) > 1
ORDER BY calls DESC LIMIT 30;

-- Throttle/error history
SELECT ts, model_id, purpose, error
FROM bedrock_calls WHERE error IS NOT NULL ORDER BY ts DESC LIMIT 100;
```

### Final report

`osceola/report.py` consumes `bedrock_calls` to auto-generate `report.md` at end of bulk:
- Total spend vs budgeted.
- Per-model breakdown (Haiku vs Sonnet, call counts + tokens + $).
- Per-purpose breakdown (classify vs retry vs index_parse vs index_prior).
- Throttle / error counts.
- Top 10 most-expensive rolls.
- Cost per page (for future capacity planning).

Ship this `report.md` + `osceola.db` to client at end of run for full cost transparency.

## Bedrock prompts

### Classify prompt (used for all 218K frames)

`poc/prompts.py::CLASSIFY_PROMPT` describes the 7 classes with short examples, explicitly lists both separator styles, notes the 2 index-page layouts, instructs on rotation handling, requires self-reported confidence. Tool `classify_page` returns structured JSON.

### Index parse prompt (used only on index frames, ~5K total)

`poc/prompts.py::INDEX_PARSE_PROMPT` instructs the model to read every row of a tabular STUDENT RECORDS INDEX page, handling both known layouts (D1 HIGHLANDS-style and D2 OHS OSCEOLA-style). Tool `parse_index_page` returns `rows = list of {last, first, middle, dob, enroll_date}`.

### Index prior retry (H4.5, used on ~5% of covers)

For covers with low confidence and no confident index match, the retry uses the regular classify prompt plus one extra line: `Likely candidates for this page based on the roll's index: [A, B, C, D, E]. Confirm exact match, pick another, or say "none".` Replaces the generic Sonnet retry for covers in this band — both cheaper and more accurate.

---

## Heuristics scope

**In (all tiers):**

- T0: blank detector, resolution-target pHash, vendor-letterhead pHash, rotation.
- T1: name regex, OCR-garbage blocklist, numeric-prefix strip, DOB format, roll-number sanity.
- T2: surname dict snap, first-name dict snap, OCR-confusion pairs, within-packet Levenshtein reconcile, **index-snap (H2.7)**.
- T3: START/END bracket, roll-size sanity, transition rules, packet-size distribution, frame contiguity, **alphabetical-monotonic (H3.7)**.
- T4: district-style, vendor, frame-position, **index prior on ambiguous covers (H4.5)**.
- T5: Sonnet retry on low-confidence band (H5.2).

**Out (Phase 2 or later):** Hough-line clapperboard, cross-packet merge, previous-page prior, two-pass split, self-consistency probe, packet-level re-extraction.

---

## CLI

```
python -m osceola init                        # create osceola.db, run schema
python -m osceola dry-run ROLL_001            # ROLL 001 end-to-end, single-roll validate
python -m osceola run-roll "OSCEOLA SCHOOL DISTRICT-4/ROLL 045"
python -m osceola run-all [--districts 1,2,3] [--concurrency 30]
python -m osceola aggregate ROLL_ID           # aggregate-only (re-run after HITL resolution)
python -m osceola report                      # generate global report.md (consumes bedrock_calls for cost breakdown)
python -m osceola cost                         # quick CLI cost summary (totals, by model, by purpose, by roll)
streamlit run osceola/hitl.py                 # HITL UI
```

All CLIs read both `.env` and `.env.bedrock` automatically.

---

## HITL UI (Streamlit)

Single `osceola/hitl.py` file. Three sections:

1. **Login**: single password from `HITL_PASSWORD` env var. Session 2 hours with idle timeout.
2. **Queue**: table of pending items (filter by district, roll, reason, age). Oldest first.
3. **Detail**: image preview (S3 presigned URL 15 min TTL) + editable fields + approve/edit/reject buttons. Submit → `db.resolve_hitl()` → SQLite → auto-regenerate affected PDF.

No multi-operator locking. One operator. If two log in simultaneously, assume they can sort it out via voice — this is a one-off job.

---

## Cost

| Line | Pages / calls | Cost |
|---|---|---|
| Tier 0 skipped | ~15K | $0 |
| Haiku classify on-demand (1,700 in / 110 out avg) | 203K | ~$450 |
| Sonnet retry (~10% mid-band, 1,700 in / 67 out avg) | ~20K | ~$200 |
| Index parse Haiku (~5K index frames, 2,900 in / 900 out) | ~5K | ~$50 |
| Index prior retry (folded into Sonnet retry for ~5% of covers) | — | $0 extra |
| EC2 m6i.xlarge × 10 hr | — | ~$2 |
| S3 egress (same region) | — | $0 |
| **Total on-demand** | | **~$700** |
| Haiku Batch flip (after dry-run) | | **~$475** |
| HITL operator time (~1% residual × 15 s) | ~2,200 pages | ~9 hrs |

Runtime ~6–10 hours overnight. Dry-run on ROLL 001 (1,924 frames) ~15 minutes at ~$3.

---

## Accuracy

Target **≥ 97% packet partial before HITL, ≥ 99% after HITL**. Stack:

- Haiku baseline ~85% page → heuristic stack (T1 reject garbage, T2 corpus snap, T3 structural, **T2.7 index-snap**, **T4.5 index prior**) → ~97% page, ~99% packet.
- The lift from 92% (pre-2026-04-21) to 97% comes from the index-snap heuristic once per-roll allowlist exists.
- HITL closes the last 1–3%.

Numbers are estimates — confirm via the **D1 dry-run gate**.

---

## D1 dry-run gate

Before bulk, run the pipeline on D1 ROLL 001 (1,924 frames including ~8 confirmed index frames). Run `eval.py` against cleaned D1 GT (419 PDFs after filtering ~14% placeholders / OCR garbage). Accept criteria:

- `accuracy_partial ≥ 0.92` (packet-level, Levenshtein ≤ 2)
- `accuracy_exact ≥ 0.80`
- HITL rate ≤ 5%
- `index_coverage = 'full'` (all index frames parsed into `roll_index_entries`)
- Spend for 1,924 frames ≤ $5

Pass → authorize bulk. Fail → iterate prompts + heuristics, rerun dry, do not burn bulk budget.

---

## Eval with cleaned ground truth

`eval.py` cleans D1 GT filenames before scoring:

- Strip `(LAST)`, `(FIRST)`, `(MIDDLE)`, `MIDDL)`, `BIRTH`, `COUNTY`, `SEX`, `PLACE`, `CITY`, `NAME` tokens.
- Drop digits-only and single-word garbage filenames (`1959.pdf`, `Birtha.pdf`, `AN ...pdf`).
- Exclude ROLL 003/005/006 (sham batch merges).
- Case-normalize to UPPER for comparison.
- Preserve `_N` dup-suffixed filenames as legitimate same-name students.

Scoring:
- `exact` = `(UPPER_last, UPPER_first, UPPER_middle)` all match.
- `partial` = `(UPPER_last, UPPER_first)` match with Levenshtein ≤ 2.

Output: precision, recall, F1 + per-district breakdown if GT exists.

---

## Security + data handling

- TIFs and PDFs are FERPA-protected. Host runs in private network. Streamlit port never exposed publicly — operator uses SSH tunnel (`ssh -L 8501:localhost:8501 host`).
- PNG cache at `/data/cache/` purged after aggregator commits packets to PDF.
- SQLite backup via `VACUUM INTO /data/backup/osceola_YYYYMMDD.db` at end of each roll.
- Student PII redacted in INFO logs; kept in ERROR logs for debug.
- Creds via `.env` + `.env.bedrock`, file perms 0600, never logged.
- HITL password rotated per run (`HITL_PASSWORD` env var).

---

## Testing strategy

- **Unit**: heuristics modules, schemas, grouping, eval scorer. Mock boto3 everywhere. Target > 90% branch coverage on `heuristics/`, `group.py`, `eval.py`.
- **Integration**: real SQLite, mocked S3 (`moto`), mocked Bedrock. End-to-end on 5 fixture TIFs.
- **Smoke**: opt-in `BEDROCK_SMOKE=1`, hits real Bedrock on 5 fixtures.
- **Dry-run**: operator runs ROLL 001 end-to-end pre-bulk.

Pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.smoke`.

---

## Open questions (client sign-off)

1. **Runtime host** — EC2 us-west-2 recommended. Client preference?
2. **GT-cleaning policy** — OK to drop ~14% garbage filenames from eval baseline?
3. **Eval set curation** — hand-label 100–200 pages across D2–D7? Who, when?
4. **HITL backlog SLA** — 24 hr? 7 days?
5. **Data retention** — how long keep `/data/` after shipping SQLite audit file?
6. **Budget ceiling** — default $750 hard cap. Client OK?
7. **Batch Inference flip** — after dry-run, switch Haiku to Batch for ~40% savings?

---

## Out-of-scope (explicit)

- Phase 2 Step Functions stack.
- Replacing Streamlit with a React SPA.
- Multi-region / multi-tenant.
- Client-side re-training.
- Auto-renewal / scheduled runs — this is a one-off job.

---

## Change log

- 2026-04-21 v1: full spec with FastAPI + Caddy + n8n + Docker-compose + Prometheus.
- 2026-04-21 v2 (this doc, simplified): single Python process, CLI-driven, SQLite-only state, Streamlit HITL via SSH tunnel. Drop FastAPI / Caddy / n8n / Prometheus / Alembic / multi-container. Same accuracy stack, same deliverables, fewer moving parts. ~2,000 LOC weekend build.
- 2026-04-21 v2.1: added `bedrock_calls` SQLite table + mandatory `converse_tracked()` wrapper. Every Bedrock invocation (classify, retry, index_parse, index_prior, even failed/throttled) logs one row with tokens, cost computed at insert time, latency, stop_reason. Enables live budget guard, per-roll/per-purpose/per-model cost breakdowns, retry amplification queries, and client-facing cost transparency in `report.md`. `python -m osceola cost` CLI exposes quick summaries.
