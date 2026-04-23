# Cost Analysis — Osceola POC to Production

**Date:** 2026-04-23
**Purpose:** single consolidated view of all cost numbers: Phase 1 measured, model bake-off projections, Phase 2 added levers, Phase 4 bulk run. Supersedes the scattered cost tables in other docs for the comparison view.

---

## 1. Phase 1 POC — measured (ROLL 001, 1924 TIFs)

| Line item | Value | Source |
|---|---|---|
| Pages classified | 1,924 | `roll_001_pages.jsonl` |
| Input tokens | 6,634,602 | `EvalReport.tokens_in_total` |
| Output tokens | 651,816 | `EvalReport.tokens_out_total` |
| Haiku 4.5 input price | $1.00 / MTok | `poc/bedrock_client.py` constants |
| Haiku 4.5 output price | $5.00 / MTok | same |
| **Input cost** | **$6.63** | 6.63M × $1/MTok |
| **Output cost** | **$3.26** | 652K × $5/MTok |
| **Total Phase 1 spend** | **$9.89** | budget ceiling $10 — not hit |
| Cost per page | $0.00514 | |
| Smoke test (6 fixtures) | ~$0.02 | one-off |
| 20-TIF sanity run | $0.10 | one-off |
| Heuristic iteration reruns (6 variants) | $0 | `poc.regroup` = no Bedrock |
| **Session total** | **$10.01** | |

---

## 2. Model bake-off (directional, 5 fixture pages)

From the 2026-04-20 bake-off:

| Model | 5-page class accuracy | Projected 218K on-demand | Projected 218K batch | Verdict |
|---|---|---|---|---|
| **Claude Haiku 4.5** | 4/5 | **~$1,123** | **~$560** | **Primary — shipped in Phase 1** |
| Claude Sonnet 4.6 | 4/5 | ~$1,338 | ~$669 | Retry tier only |
| Amazon Nova Lite | 4/5 (name swap risk) | ~$32 | ~$16 | Rejected — SOW name accuracy risk |
| Amazon Nova Pro | 2/5 | ~$422 | ~$211 | Rejected — worse class accuracy, cost near parity with Haiku |

Haiku 4.5 on-demand projection derived from measured $9.89 per 1,924 TIFs × (218,577 / 1,924) = **$1,123**. Batch at ~50% Bedrock discount = **$560**.

---

## 3. Phase 1 measured vs estimated (what we got right / wrong)

| Metric | Pre-run estimate | Measured | Delta |
|---|---|---|---|
| Full-run spend | ~$5 (early guess) | $9.89 | 2× under-estimate |
| Per-page cost | $0.003 | $0.00514 | 71% high |
| Input tokens / page | ~2,000 | ~3,450 | image token cost was higher |
| Output tokens / page | ~200 | ~340 | index_rows arrays add ~100 tokens on index frames |
| Index frames detected | ~7 | 20 | 3× better than broad-probe estimate |
| Packets produced | ~400 (≈ real count) | 1,240 (name-change) or 323 (index-entry) | name-change over-splits 3.5× |

---

## 4. Per-heuristic cost impact (Phase 2 proposals)

| Lever | Added bulk cost (218K) | Expected accuracy gain | ROI rank |
|---|---|---|---|
| Prompt v2 (tighter prompts, field order fix) | $0 — same call count | +5–10 pp partial acc | ★★★★★ |
| Index-parse stage (already shipped in Phase 1) | +$12 per 100 rolls = $12 total | +46 pp (measured) | ★★★★★ |
| Tier 0 H0.1 blank detector | −$50 to −$100 (skipped LLM calls on 2–5% frames) | neutral; precision on trivial cases | ★★★★ |
| Tier 0 H0.2/H0.3 pHash leaders/chart | −$5 to −$10 | neutral | ★★ |
| Tier 1 format validators (name regex, garbage blocklist) | $0 | +2 pp | ★★★★ |
| Tier 2 corpus snap (surname/given dict) | $0 | +3 pp | ★★★ |
| Tier 3 structural rules (alpha-monotonic, START/END enforce) | $0 | +1–3 pp | ★★★ |
| Tier 4 district-prior prompt injection | +5% input tokens on affected frames (~+$25) | +2 pp | ★★ |
| Tier 5 Sonnet 4.6 retry on 0.60–0.85 confidence | **+$150** | +1–2 pp | ★★ |

**Realistic Phase 2 heuristic stack (ROLL 001 scale → 218K proj):**

Heuristics running at 218K corpus:
- Tier 0 pixel filter saves ~$75
- Prompt v2 + Tier 1/2/3 validators add nothing
- Sonnet retry adds ~$150
- Net Bedrock cost ~$560 (batch) + $75 (savings cancel some additions) ≈ **$635** for Bedrock alone

---

## 5. Phase 4 bulk — full 218K run projection

| Component | On-demand cost | Batch cost | Notes |
|---|---|---|---|
| Bedrock Haiku (classify) | $1,123 | **$560** | primary pass |
| Bedrock Sonnet (retry tier, ~12% of pages) | — | **$150** | mid-confidence |
| Bedrock index-parse (per roll) | — | **$12** | merged into classify, minimal delta |
| Tier-0 savings | — | **−$75** | blank + pHash pre-filter |
| **Bedrock subtotal** | — | **~$647** | |
| Lambda invocations (classify + aggregate) | — | ~$50 | |
| Step Functions (Distributed Map) | — | ~$20 | |
| DynamoDB on-demand | — | ~$10 | `bedrock_calls`, `pages`, `rolls` tables |
| S3 storage + transfer | — | ~$30 | output PDFs + audit logs |
| CloudWatch / Athena | — | ~$15 | dashboards + query |
| **AWS infra total** | — | **~$772** | |
| HITL operator time | — | ~90 hrs @ TBD rate | 5% of pages × 30s each |

Result: **~$770 AWS** + **HITL labor**. Matches the $820 estimate in README with ~$50 slack.

---

## 6. Cost per student (reality check)

Target: ~43,000 student PDFs from 218K TIFs.

| Scenario | Cost / student |
|---|---|
| Phase 1 on-demand scale-up | $1,123 / 43K = $0.026 / student |
| Phase 4 batch + heuristics | $770 / 43K = $0.018 / student |
| Includes HITL at $30/hr × 90 hr = $2,700 | $3,470 / 43K = $0.081 / student |

---

## 7. Cost risks / variance

| Risk | Direction | Magnitude |
|---|---|---|
| Sonnet retry tier hits >15% of pages (currently modeled at 12%) | Up | +$50–$100 |
| Batch Inference price changes | Either | ±20% |
| Haiku tokenization changes with model updates | Either | ±10% |
| HITL review rate >5% of pages | Up | HITL labor scales linearly |
| GT curation labor for D2–D7 | New cost | ~40 hrs per district × 7 = 280 hrs |
| FERPA external audit (if required) | New cost | $5–15K one-off |
| Re-runs due to prompt iteration | Up | +$10 per full-roll iteration |

---

## 8. Decisions locked by cost data

1. **Haiku 4.5 primary** — cheapest vision-capable model that hits 4/5 on small bake-off, ships in Phase 1.
2. **Sonnet 4.6 retry tier only** — 2.4× Haiku cost, use only on mid-confidence.
3. **Nova models dropped** — name-extraction accuracy risk not justified by cost delta.
4. **Bedrock Batch Inference in Phase 4** — 50% discount, only used for bulk since POC needed realtime iteration.
5. **Index-parse merged into classify call** — 0 added Bedrock calls; would have been $12 extra if separate pass.
6. **Budget ceiling `$10` on `run_poc`** — prevents silent overspend on iteration runs.
7. **pHash Tier 0 deferred** — savings (−$75) not worth Phase 1 implementation time; comes in Phase 2.

---

## 9. Source-of-truth data

Raw numbers live in:
- `poc/output/roll_001_eval.json` — current ROLL 001 measured totals
- `poc/output/roll_001_pages.jsonl` — per-page token/usd breakdown
- `docs/2026-04-23-session-report.md` — session cost summary section
- `docs/heuristics-brainstorm.md` — per-tier cost impact estimates
- `docs/superpowers/specs/2026-04-22-osceola-phase1-poc-v2-results.md` — cost summary section (lines 203–216)
- `docs/osceola-poc-discussion.md` — early cost hypothesis from project brief
