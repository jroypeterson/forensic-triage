# Forensic Accounting Triage System

Claude-driven forensic accounting screen. Surfaces companies in the coverage list with accounting irregularities or quality-of-earnings concerns worth a deep dive. Same philosophy as `biotech_triage/`: Claude is the runtime, data lives in CSVs, rubrics live in markdown.

**The output is not a score. The output is a list of flagged companies plus the specific concerns to investigate.** A single composite score (Beneish, F-score, etc.) hides the *why*, and the *why* is what tells you where to dig.

## Project Structure

```
forensic_triage/
  CLAUDE.md                       # This file — workflow instructions
  sync_watchlist.py               # Sync watchlist from Coverage Manager master list
  data/
    watchlist.csv                 # Companies tracked (synced from Coverage Manager)
    flags_history.csv             # Per-company flag state per run (for diffs)
    ratios_latest.csv             # Latest computed ratios snapshot
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
- Excludes Biopharma (forensic triage de-prioritizes biotech accounting)
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
python sync_watchlist.py            # write
python sync_watchlist.py --dry-run  # report only
```

Run this **before** every triage. It is Step 0 of the weekly workflow below.

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
