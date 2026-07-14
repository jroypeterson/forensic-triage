# Forensic Accounting Triage System

Claude-driven forensic accounting screen. Surfaces companies in the coverage list with accounting irregularities or quality-of-earnings concerns worth a deep dive. Same philosophy as `biotech_triage/`: Claude is the runtime, data lives in CSVs, rubrics live in markdown.

**The output is not a score. The output is a list of flagged companies plus the specific concerns to investigate.** A single composite score (Beneish, F-score, etc.) hides the *why*, and the *why* is what tells you where to dig.

## Project Structure

```
forensic_triage/
  CLAUDE.md                       # This file — workflow instructions
  sync_watchlist.py               # Sync watchlist from CM master + S&P 500 expansion ring
  coverage_cohorts.py             # Cohort partition (Portfolio>Researching>Core>S&P 500)
  next_batch.py                   # Next-batch picker (cohort-priority order)
  dashboard.py                    # Coverage dashboard: Slack digest + HTML + day-over-day
  data/
    watchlist.csv                 # Companies tracked (CM + S&P 500; cohort baked in)
    cohort_totals.json            # Disjoint roster sizes (CI-safe; for the excluded count)
    flags_history.csv             # Per-company flag state per run (for diffs)
    ratios_latest.csv             # Latest computed ratios snapshot
  reports/
    coverage_dashboard.html       # Rendered coverage dashboard (HTML)
  .health/
    dashboard_history.json        # Day-over-day snapshots for the digest delta
  rubrics/
    general.md                    # Universal forensic checks (any sector)
    healthcare_services.md        # Hospitals, providers, payers, PBMs, distributors
    medtech.md                    # Devices, diagnostics, capital equipment
  reports/                        # Generated triage reports
```

## Watchlist Source of Truth

The watchlist is **derived from** `../Coverage Manager/data/coverage_universe_tickers.csv`. Do not edit `data/watchlist.csv` by hand for ticker adds/removes — edit the Coverage Manager master and re-sync. Manual edits to the `notes` column are preserved across syncs.

### Sync rules (`sync_watchlist.py`)
- Only US-listed names (must have a CIK — EDGAR is the data source)
- **Biopharma: large-cap only** (2026-07-13, JP). Biopharma is screened only when it's in the
  S&P 500 (a large-cap proxy) — big pharma (LLY/PFE/MRK…) has normal financials the rubric
  handles; small/pre-revenue biotech accruals/revenue rules are noise, so non-S&P-500 biopharma
  stays excluded. `LARGE_CAP_ONLY_SECTORS={"Biopharma"}` gates it; included ones route to the
  `general` rubric (no biopharma-specific rubric yet). The dashboard's "Not screenable" line
  shows the remaining small-cap-biopharma gap.
- Maps Coverage Manager `Sector (JP)` → forensic `sector_subgroup`:
  - `Healthcare Services` → `hc_services`
  - `MedTech`, `Life Science Tools` → `medtech`
  - `Tech`, `SaaS`, `Fintech`, `Other` → `general`
  - (Coverage Manager retired `PA` → `Other` and `Healthcare Real Estate` → `Healthcare Services` on 2026-04-17. Former HC Real Estate rows now roll up under `hc_services` via the `Healthcare Services` sector.)
- Preserves `notes` and original `added_date` for tickers that survive
- Propagates `Core` flag and `Subsector (JP)` from coverage master
- Reports adds / removes / subgroup changes to stdout

### Sync command
```
python sync_watchlist.py            # write (CM universe + S&P 500 expansion ring)
python sync_watchlist.py --dry-run  # report only
python sync_watchlist.py --no-sp500 # CM universe only (skip the S&P 500 ring)
```

Run this **before** every triage. It is Step 0 of the weekly workflow below.

### S&P 500 expansion ring (2026-07-13)

The watchlist is the CM universe **plus the S&P 500** as a 4th, lowest-priority coverage
ring (JP's request: "portfolio, researching, core coverage, and then broader S&P 500").
`sync_watchlist.py` unions in the S&P 500 names CM doesn't already carry (`sp500 − cm_master`,
from `../sigma-alert/sources/sp500.txt`), resolving each CIK from SEC's free
`company_tickers.json` (cached at `data/.sec_company_tickers.json`, gitignored). These rows
get `source=sp500`, `sector_subgroup=general`, `filer_type=domestic`. Names with no SEC CIK
are skipped loudly (can't EDGAR-screen). Result: ~700 names (~303 CM + ~394 S&P 500).

**Cohort is baked into `watchlist.csv`.** Each row carries a `cohort` column
(`portfolio|researching|core|sp500|other`, disjoint by priority via `coverage_cohorts.py`),
and `sync` also writes `data/cohort_totals.json` (disjoint roster sizes). Both are committed
so CI — which has **no CM/sigma sibling repos** — reads cohorts from the watchlist, not live.
`next_batch.py` and `dashboard.py` read the baked `cohort` with a live-roster fallback.

## Coverage Dashboard (`dashboard.py`)

Forensic triage is a **standing process**, not a one-shot task — names are screened a few per
day and this dashboard shows coverage + freshness across the four rings so progress (and gaps)
stay visible. Modeled on the transcripts daily digest.

```
python dashboard.py                 # plaintext to stdout (dry-run; no post, no snapshot)
python dashboard.py --html          # + write reports/coverage_dashboard.html
python dashboard.py --post          # post Slack digest (#forensic-flags) + save day-over-day snapshot
python dashboard.py --post --html   # both (what the daily workflow runs)
python dashboard.py --per-day 6 --cycle-start 2026-06-20
```

- **Rings** (disjoint, priority order): Portfolio → Researching → Core coverage → S&P 500
  (+ `other` residual). A name counts under its highest ring only.
- **"Screened"** = a `flags_history.csv` row dated ≥ cycle-start with `status=complete` (the
  exact done-definition `next_batch.py` uses). Per ring: screened/total, 🔴/🟡 tallies, pending,
  and the foreign (Data-Gap) count that can't be EDGAR-screened.
- **Honest denominator:** the dashboard surfaces `Not screenable (N biopharma-excluded …)` per
  ring — forensic skips biopharma at sync, so e.g. ~10 Portfolio names aren't screened and that
  gap is shown, never hidden.
- **Day-over-day** delta persisted to `.health/dashboard_history.json` (saved on `--post`).
- **Per-ring ETA** — `DAYS` + `DONE BY` columns. Screening runs top-down by priority, so a ring's
  completion is **cumulative**: it finishes only after everything above it plus its own pending
  is screened (Portfolio in days; S&P 500 last). A ring with 0 pending shows `done`. The forensic
  cadence is **a few names every day** — the dashboard tracks that steady progress; there is no
  "run the whole universe at once" step.

**Cadence:** the daily Path-A workflow (`forensic_triage.yml`, 18:30 UTC) runs
`dashboard.py --post --html` after the screen step (`continue-on-error` — a digest failure can
never fail the screen). **Activation gap:** the Slack post needs a **new `#forensic-flags`
webhook** in `SLACK_WEBHOOK_FORENSIC` (same secret Path A already expects). Until it's created,
the digest writes the HTML + prints, but the Slack post no-ops. The HTML is committed each run.

## Core Principle: Flag Families, Not Scores

Route every company through these families. Each family has its own diagnostic ratios and flag rules. A company is flagged when *combinations* fire — single-ratio flags are noisy.

| Family | What it catches |
|---|---|
| **Accruals quality** | Earnings ≠ cash (Sloan accruals, CFO–NI gap) |
| **Revenue quality** | Channel stuffing, pull-ins, gross-vs-net, premature recognition |
| **Expense capitalization** | Hiding opex in capex / intangibles / capitalized software |
| **Balance sheet bloat** | Inventory & AR growing faster than sales |
| **Leverage hiding** | Off-BS debt, factoring, supplier finance, VIEs |
| **Governance / disclosure** | Restatements, auditor changes, late filings, 8-K Item 4.02 |
| **Market signals** | Insider selling clusters, short interest, borrow cost |
| **Text signals** | MD&A length / hedging / boilerplate Δ YoY |
| **Sector-specific** | See sector rubrics in `rubrics/` |

Composite scores (Beneish M, Dechow F, Altman Z, Sloan accruals) are computed as **inputs to the flag rules**, not as headline outputs.

## Tier System

| Tier | Meaning | Action |
|---|---|---|
| **Red** | 3+ flag families fired, OR any single **critical governance** flag (8-K 4.02 / restatement / auditor resignation-with-disagreement / late filing — `general.md` §6a) | Deep dive — read latest 10-K notes, MD&A, and any 8-Ks |
| **Yellow** | 2 flag families fired, OR a **new** flag this run that wasn't there last run, OR a single **high-severity** accounting family (e.g. a revenue/inventory collapse, a fresh FCA/qui-tam matter) even when only one family fired | Skim filings, set a watch |
| **Green** | 0–1 flag families fired, no critical-governance signal, **and the rubric was actually evaluable** | No action |
| **Data Gap** | The rubric **could not be evaluated** — a foreign 20-F/IFRS filer (`filer_type=foreign`), a filing staler than ~400 days with no current-year 10-K, or required financial statements/notes unavailable | Manual review — never treat as Green |
| **Corporate Action** | A non-accounting structural event (completed merger / take-private / delisting — 8-K 5.01/2.01/3.01) with no accounting concern | Flag for **watchlist removal**, not Red |

**"Unable to evaluate" is NOT Green** (calibration 2026-06-20). A name whose data the rubric can't
read goes to **Data Gap**, never Green — a data gap silently passing as a clean bill is the most
dangerous failure mode (PHG/INMD were wrongly Green in the June run). `sync_watchlist.py` tags
`filer_type=foreign` for ADR/20-F filers; those are Data Gap by default unless a domestic 10-K is found.

**Critical vs soft governance.** Only **critical** governance (§6a) auto-Reds or blocks a Green. **Soft**
governance (§6b: routine CFO/audit-chair turnover, clean auditor re-tender) counts as one ordinary
family toward the combination — it does not, by itself, escalate to Red (calibration 2026-06-20:
MASI's take-private and routine C-suite churn were over-firing Red).

**Corporate actions are not accounting flags.** A completed merger / take-private / delisting is a
structural event — tier it **Corporate Action** and flag the name for removal at the next sync, do
NOT score it Red (MASI, June run).

**Diff > level.** A company moving Green → Yellow this week is more interesting than one that's been Yellow for six months. `flags_history.csv` exists to make diffs cheap.

## Weekly Triage Workflow

When the user says "run forensic triage" or similar:

### "A few each day" cadence (Path B, interactive)
The full universe (~274 domestic names) is screened a **few at a time** across interactive
sessions, not one big run. `python next_batch.py [-n 6]` is the daily driver: it prints the next
batch of un-screened names (core-first → hc_services → medtech → general), the progress
(`X/274 this cycle`), and the foreign Data-Gap count. A name is "done this cycle" once it has a
`flags_history.csv` row dated ≥ the cycle-start (default `2026-06-20`, the recalibration baseline);
bump `--cycle-start` to begin a fresh re-screen. Each session: run `next_batch.py`, screen that
batch (Steps 1–5 below), append rows to `flags_history.csv`, write/append the day's report. Foreign
filers never appear in the batch (they're Data Gap, not EDGAR-screened).

### Step 0: Sync watchlist
Run `python sync_watchlist.py` first. Note any adds/removes/subgroup changes — new names get an automatic Yellow tier on their first appearance (no flag history to compare against, so flag them for a baseline read).

### Step 1: Pull data
**First, route `filer_type=foreign` names straight to Data Gap** — do NOT spend EDGAR calls on them; the 10-K-based rubric can't evaluate a 20-F/IFRS filer. List them under the Data Gap section of the report for manual review.

For each **domestic** ticker in `watchlist.csv`:
1. Use `mcp__claude_ai_Edgar_Tools__company_brief` for the snapshot
2. Use `financial_statements` and `financial_trends` for the ratio inputs (need 3+ years of trailing data for YoY comps)
3. Use `material_events` for 8-Ks (auditor changes, Item 4.02 non-reliance)
4. Use `insider_activity` for Form 4 clusters
5. Use `edgar_notes(ticker, '<topic>')` on demand when a flag fires — `revenue`, `leases`, `debt`, `goodwill`, `contingencies`

#### What the 3-call baseline catches vs. needs escalation

Calibrated 2026-04-17 on an 8-ticker smoke test (AAPL, CVNA, AHCO, CVS, HIMS, JNJ, DXCM, TMDX). The cheap baseline = `company_brief` + `financial_snapshot` + `financial_trends`.

| Family | Baseline catches it? | Escalation needed |
|---|---|---|
| Accruals (CFO/NI) | ✅ — `company_brief` returns NI + CFO directly | none for the < 0.5 rule; `financial_statements` for Sloan accruals |
| Revenue quality (DSO, gross margin trend) | ❌ | `financial_statements` for AR; `financial_trends` for gross_profit (sometimes missing — see below) |
| Expense capitalization | ❌ | `financial_statements` (capex, D&A) + `edgar_notes("Policies")` |
| Balance sheet bloat (inventory, AR, goodwill %) | ❌ | `financial_statements` for line items |
| Leverage hiding | ⚠️ partial — `recent_events` catches new 2.03 / 8-K debt items; ratio leverage visible | `edgar_notes("Debt")` for off-BS, factoring, supplier finance |
| Governance | ✅ — `recent_events` shows 4.01/4.02/5.02/NT items by date | none unless a 4.02/restatement requires note-text quoting for the report |
| Market signals | ⚠️ — `insider_activity` shows top 3 transactions (date + dollar) but not pct-of-holdings | `insider_activity(detailed=True)` if available, or skip the 25%-of-holdings clause |
| Text signals | ❌ | `edgar_notes` for risk-factor/MD&A diffs (rarely worth the call) |
| Sector-specific (every rule) | ❌ | `edgar_notes` for the topics in each sector rubric |

**Auto-escalation triggers** (apply during Step 1 to keep the per-ticker call count down):

1. `subgroup ∈ {hc_services, medtech}` AND (`health_hint != "strong"` OR `CFO/NI < 0.7`) → pull one targeted `edgar_notes` for the top sector concern (hc: `"Policies"` for revenue/bad-debt; medtech: `"Inventory"` or `"Commitments"`).
2. Any `recent_event` item ∈ {4.01, 4.02, NT, 2.03} in last 90 days → pull `edgar_notes` for the obvious topic (4.02 → `"Restatement"` if present; 2.03 → `"Debt"`).
3. CFO/NI < 0.5 with positive NI → pull `financial_statements` for balance-sheet deltas to identify the source of the gap.
4. Any historically-flagged name (per `notes` column or prior-run history) → escalate even if baseline is clean. Baseline alone is too forgiving on these — CVNA was the smoke-test example.

**Quirk:** `financial_trends` sometimes omits the `revenue` and `gross_profit` arrays even when explicitly requested (saw on CVS, TMDX in the smoke test). Compute YoY revenue from `company_brief` + a one-off `financial_statements` call when the trend array is missing.

**Budget:** the real Edgar-Tools **Pro cap is 10,000 calls/day** (the old "500/day" was stale — corrected 2026-06-20; the June run confirmed 10k). At ~3.5–3.7 calls/ticker incl. escalations, the **full ~301-name watchlist ≈ 1,100 calls — comfortably a single day's run.** The June 50-name pilot used ~185 calls. So batching across days is **not** required; run the whole universe in one interactive session. `core=true` (~30–60 names) is still useful for a fast first pass, not a budget necessity. Foreign filers (`filer_type=foreign`) are skipped from EDGAR pulls — they go straight to Data Gap.

### Step 2: Run general flags
Apply `rubrics/general.md` to every company. Compute the ratios, evaluate flag rules, record which families fired in `flags_history.csv`.

### Step 3: Run sector-specific flags
Based on the watchlist `sector_subgroup` column, apply the matching rubric:
- `hc_services` → `rubrics/healthcare_services.md`
- `medtech` → `rubrics/medtech.md`
- (other sectors → general rubric only for now)

### Step 4: Tier and diff
- Assign Red / Yellow / Green per the tier system
- Diff against last run — surface every Green→Yellow, Yellow→Red, and any new flags on Red names
- Write to `data/flags_history.csv` with the run date

### Step 5: Report
Write a markdown report to `reports/forensic_YYYY-MM-DD.md`:

```
# Forensic Triage — {date}

## Red (deep dive)
| Ticker | Subgroup | Flags fired | New this run? | One-liner concern |

## Yellow (watch)
| Ticker | Subgroup | Flags fired | New this run? | One-liner concern |

## Data Gap (manual review — NOT screened)
| Ticker | Subgroup | Why | (e.g. foreign 20-F filer / FY24 10-K 473d stale / financial statements unavailable) |

## Corporate Action (flag for watchlist removal)
| Ticker | Event | (e.g. take-private merger closed 2026-06-10) |

## Diffs since last run
- TICKER: Green → Yellow (revenue quality flag fired — DSO +28% YoY while revenue growth decelerated)
- ...

## Cleared this run
- TICKER: Yellow → Green (inventory normalized)
```

Tier precedence when assigning: **Corporate Action** (structural exit) → **Data Gap** (unevaluable) → **Red** (critical-gov or 3+ families) → **Yellow** (2 families / new flag / single high-severity) → **Green** (evaluated clean). A name is never Green unless it was actually evaluated.

For each Red name, also pull and quote the relevant 10-K note via `edgar_notes` so the user can read the source language without leaving the report.

## CSV Formats

### watchlist.csv
```
ticker, company_name, sector_subgroup, subsector, core, filer_type, added_date, notes
```
`sector_subgroup` values: `hc_services`, `medtech`, `general`. `subsector` and `core` come from Coverage Manager (`Subsector (JP)`, `Core`). `filer_type` is `domestic` (10-K filer) or `foreign` (ADR/20-F/IFRS — derived from CM `Country (ISO)` + `Listing Type`); **`foreign` names route to the Data Gap tier** (the 10-K-based rubric can't evaluate a 20-F), so they're tagged not screened. `notes` is the only column safe to hand-edit — everything else is overwritten by `sync_watchlist.py`.

### flags_history.csv
```
run_date, ticker, tier, accruals_flag, revenue_flag, capex_flag, balance_sheet_flag,
leverage_flag, governance_flag, market_flag, text_flag, sector_flag, flag_details
```
Boolean columns are 0/1. `tier` ∈ {`Red`, `Yellow`, `Green`, `DataGap`, `CorporateAction`}. `flag_details` is a free-text column listing which specific rules fired and the values — for `governance_flag`, mark each as `critical` (§6a) or `soft` (§6b) so the diff can tell an 8-K 4.02 from routine CFO churn. **Do not write `DataGap`/`CorporateAction` rows from the degraded Saturday trigger** — only persist interactive-run results.

### ratios_latest.csv
```
ticker, fetch_date, dso_days, dso_yoy_change, inventory_days, inv_yoy_change,
cfo_ni_ratio, sloan_accruals, beneish_m, dechow_f, altman_z, capex_da_ratio,
sbc_pct_revenue, goodwill_pct_assets, ... (sector-specific columns appended)
```

## Tools
- **edgartools MCP** — primary data source. Prefer this over web search for any financial ratio or filing question. **Requires Pro tier** ($24.99/mo at https://app.edgar.tools/pricing) — see "Edgar-Tools tier requirements" below.
- **WebSearch** — only for things EDGAR doesn't have (short interest, borrow cost, recent press)
- **File tools** — read/write CSVs and reports directly
- **Bash** — `python sync_watchlist.py` before every triage run

## Edgar-Tools tier requirements

The forensic rubric needs ~80% of fields that are **gated behind Edgar-Tools Pro**. Free tier returns the literal string `"upgrade_required"` for most ratios and TOC-only for note bodies. Specifically:

| Call | Free tier delivers | Pro unlocks (rubric needs these) |
|---|---|---|
| `financial_snapshot` | 5 profitability margins | ROE, ROA, current/quick ratio, D/E, debt/assets, net debt/EBITDA |
| `financial_trends` | 3yr × 2 concepts | 10yr × all 8 concepts + trend classification + anomaly flags |
| `edgar_notes` | TOC + note titles only | **Full note body text** — required for quoting 10-K language in Red-tier reports |
| `company_brief` | Profile + counts | Insider sentiment, event summaries, fund detail, financial health assessment |
| `material_events` | Truncated (≤1–2 events on free) | Full 8-K history |

**Pro daily limit: 10,000 API calls** (corrected 2026-06-20 — the prior "500/day" here was stale and drove unnecessary multi-day batching). A full ~301-name run at a realistic 2–4 calls/ticker is ~700–1,100 calls — **well under the cap, one day.** Still keep the call count lean for speed/cost:
1. Lean on `company_brief` (bundles many signals) — only escalate to other calls when a flag fires
2. `core=true` first pass (~30–60 tickers) is a fast smoke-check, not a budget requirement
3. Foreign 20-F/ADR filers (`filer_type=foreign`) are not pulled — they route to Data Gap (manual review)

### `edgar_notes` topic search is literal, not semantic

The `topic` parameter does **substring matching against note titles**, not concept search. Calling `edgar_notes(ticker, "revenue")` returns "no notes matched" even when revenue policy lives inside Note 2 ("Summary of Significant Accounting Policies"). Use note-title keywords instead:

| What you want | What to pass as `topic` |
|---|---|
| Revenue recognition policy | `"Policies"` or `"Significant Accounting"` |
| Debt covenants, maturities, off-BS | `"Debt"` |
| Goodwill impairment | `"Goodwill"` |
| Lease obligations | `"Leases"` |
| Legal proceedings, contingencies | `"Commitments"` or `"Contingencies"` |
| Segment data | `"Segment"` |

When in doubt, call `edgar_notes` once with a broad topic, read the `notes_toc` it returns, then call again with an exact title-substring from the TOC.

## Adding Sectors
When the user wants to cover a new sector:
1. Add a new file under `rubrics/`
2. Add a new `sector_subgroup` value to `SUBGROUP_MAP` in `sync_watchlist.py`
3. Add a row to the routing table in Step 3 of the workflow

Don't bloat existing rubrics with sector-specific rules.

## Run modes: interactive vs scheduled trigger

There are two ways this workflow runs, and they have **different tool surfaces**.

### Interactive (local Claude Code session)
You say "run forensic triage" in a local session and Claude executes the workflow on your machine. **This is the working mode today.** Your `claude.ai` MCP connectors (Edgar-Tools, Slack, Notion, Gmail, etc.) are all available — so the rubric works as written, including `edgar_notes` quoting and Slack posting.

### Scheduled remote trigger (cloud CCR session)
A weekly trigger runs Claude in Anthropic's cloud on a cron schedule (`trig_01TgUC5JJ2Wzz7fF7skw9Cd6`, Saturday 09:00 ET / 13:00 UTC). The trigger config is at https://claude.ai/code/scheduled/trig_01TgUC5JJ2Wzz7fF7skw9Cd6.

**KNOWN GOTCHA:** Scheduled triggers do **not** receive user-configured `claude.ai` connector MCPs, even when listed in the trigger's `mcp_connections`. The platform appears to auto-attach only the GitHub MCP for repo access. Calibration runs on 2026-04-08 confirmed that **both** `Edgar-Tools` and `Slack` were absent from the trigger session despite being attached in config.

What this means for the trigger:
- It cannot call `edgar_notes`, `company_brief`, etc. — falls back to raw `https://data.sec.gov` XBRL `companyconcept` API + WebFetch on 10-K HTML, which **truncates on large filings** and cannot extract financial statement notes
- It cannot post to Slack via the connector — would need an incoming webhook for `#forensic-flags`
- The trigger's first calibration run still produced an excellent AHCO Red-tier analysis using the fallback path, but missed the four most important notes (revenue recognition, debt covenants, goodwill detail, current legal proceedings)

### ⚠ UPDATE 2026-07-08: Edgar-Tools REST moved under /v1 (fixed) + per-statement coverage
The paid REST API versioned its paths (~2026-07-01): unversioned `/companies/{cik}/...` now 404s; use `https://api.edgar.tools/v1/...` (`REST_BASE` in `edgar_fetch.py`). The 07-01..07-07 CI failures were this + SEC throttling the edgartools fallback tripping the circuit breaker; `RestClient._get` now retries transient 429/5xx. The /v1 statement payloads are rows×periods XBRL (`_absorb_v1` normalizer). **False-Green hardening (codex 2x):** each financial family's coverage now requires its OWN source statement to have contributed mapped line items (`_stmt_ok_from` — an income-only or empty-`{}` fetch can no longer mark accruals/capex/balance_sheet/leverage complete). If all endpoints 404 again, probe `/v1` vs `/v2` before debugging code.

### ⚠ UPDATE 2026-06-24: Path A (unattended) is BUILT — pending Codex review + secrets, then enable
JP greenlit and built **Path A** (unattended automation) after the recalibration was validated. See
**`PATH_A_PLAN.md`** (codex-reviewed 2×) for the authoritative spec. Architecture: **GitHub Actions cron
+ Anthropic-API tiering** (NOT the claude.ai trigger), hybrid data layer (paid Edgar REST key for
statements/ratios/8-K item codes + free `edgartools` PyPI lib for 10-K note bodies, with REST-down →
edgartools fallback so an outage can't hide a 4.02).

**Components (all committed-locally, 48 tests passing):**
- `forensic_schema.py` + `forensic_tier.py` — deterministic false-Green guard + finalizer (pre-existing).
- `edgar_fetch.py` — per-ticker hybrid fetch → `data/fetched/<TICKER>.json` (hard schema, NEVER raises;
  `not_disclosed` vs `fetch_failed`; date-based staleness; `family_coverage` enum + `required_families_complete`).
- `tier_batch.py` — Anthropic **Fable-5** structured-output per-family judge (Claude judges families,
  NOT the final tier) → validate/retry fail-closed → `forensic_tier.finalize_tier()` deterministic
  precedence + Green-gate. Run-level circuit breaker on broad outages. History migration (13→16 cols).
- `notify.py` — #forensic-flags Block Kit + #status-reports heartbeat (context blocks use `elements[]`).
- `run_unattended.py` — per-run orchestrator (next_batch → fetch → tier → history → report → notify).
- `.github/workflows/forensic_triage.yml` — cron `30 18 * * *` (daily since 2026-07-13; was weekdays), `concurrency: forensic-triage`,
  `contents: write`, rebase-before-push, `if: failure()` alarm.
- `next_batch.py` — idempotency: done only when a `status=complete` flags_history row exists since
  cycle-start; transient `fetch_failed` retries next run; structural Data Gap (foreign/stale/not-disclosed) is done.
- `sync_watchlist.py` — now emits a `cik` column; `data/watchlist.csv` regenerated (301 rows, CIKs zero-padded).

**Before enabling the cron:** (1) Codex review (per JP's forensic convention — `git push` was deliberately
NOT done); (2) provision the 5 GH Actions secrets (`ANTHROPIC_API_KEY`, `EDGARTOOLS_API_KEY`, `EDGAR_IDENTITY`,
`SLACK_WEBHOOK_STATUS_REPORTS`, and a NEW `SLACK_WEBHOOK_FORENSIC` for a #forensic-flags webhook that must be
created); (3) one LIVE smoke (`python run_unattended.py --batch-size 2` with secrets set) to confirm a real
EDGAR fetch + a real Fable-5 tiering call before flipping the cron on. The old claude.ai trigger `trig_…9Cd6`
should be **disabled** once Path A is enabled.

### Decision (2026-06-20): Path B — interactive-only is the source of truth; disable the degraded trigger

Reviewed (Codex + PROJECT_BRIEF §5): **Path B for v1.** Interactive runs are the ONLY authoritative
source. The Saturday remote trigger (`trig_01TgUC5JJ2Wzz7fF7skw9Cd6`) runs **degraded** (no Edgar-Tools,
no Slack — see gotcha above) and produces a **partial report that misses the most important notes**
(revenue recognition, debt covenants, goodwill detail, current legal proceedings). A partial report that
*looks* complete is worse than no report — so the trigger should be **disabled in the claude.ai UI**
(`https://claude.ai/code/scheduled/trig_01TgUC5JJ2Wzz7fF7skw9Cd6` → disable/delete) and its output must
**never** be treated as a real triage. Do not append trigger-run output to `flags_history.csv`.

**Path A (full unattended automation) is deferred, not chosen.** The main open uncertainty is still rubric
calibration on the full universe, so building an `edgartools` helper now is premature. Build Path A only
if, after a few interactive full/core cycles, missed runs become a real problem. The migration would then be:
1. Add the `edgartools` Python package + a helper that pulls all required per-ticker data as JSON (replaces the MCP data layer)
2. Add a Slack webhook + `curl` post (replaces the Slack MCP)
3. Update the trigger prompt to call the helper instead of MCP tools
