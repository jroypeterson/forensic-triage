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
  - `Tech`, `SaaS`, `PA`, `Fintech`, `Other`, `Healthcare Real Estate` → `general`
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
| **Red** | 3+ flag families fired OR any single critical flag (restatement, late filing, auditor resignation, 8-K 4.02) | Deep dive — read latest 10-K notes, MD&A, and any 8-Ks |
| **Yellow** | 2 flag families fired, OR new flag this run that wasn't there last run | Skim filings, set a watch |
| **Green** | 0–1 flag families fired and no governance signals | No action |

**Diff > level.** A company moving Green → Yellow this week is more interesting than one that's been Yellow for six months. `flags_history.csv` exists to make diffs cheap.

## Weekly Triage Workflow

When the user says "run forensic triage" or similar:

### Step 0: Sync watchlist
Run `python sync_watchlist.py` first. Note any adds/removes/subgroup changes — new names get an automatic Yellow tier on their first appearance (no flag history to compare against, so flag them for a baseline read).

### Step 1: Pull data
For each ticker in `watchlist.csv`:
1. Use `mcp__claude_ai_Edgar_Tools__company_brief` for the snapshot
2. Use `financial_statements` and `financial_trends` for the ratio inputs (need 3+ years of trailing data for YoY comps)
3. Use `material_events` for 8-Ks (auditor changes, Item 4.02 non-reliance)
4. Use `insider_activity` for Form 4 clusters
5. Use `edgar_notes(ticker, '<topic>')` on demand when a flag fires — `revenue`, `leases`, `debt`, `goodwill`, `contingencies`

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

## Diffs since last run
- TICKER: Green → Yellow (revenue quality flag fired — DSO +28% YoY while revenue growth decelerated)
- ...

## Cleared this run
- TICKER: Yellow → Green (inventory normalized)
```

For each Red name, also pull and quote the relevant 10-K note via `edgar_notes` so the user can read the source language without leaving the report.

## CSV Formats

### watchlist.csv
```
ticker, company_name, sector_subgroup, subsector, core, added_date, notes
```
`sector_subgroup` values: `hc_services`, `medtech`, `general`. `subsector` and `core` come from Coverage Manager (`Subsector (JP)`, `Core`). `notes` is the only column safe to hand-edit — everything else is overwritten by `sync_watchlist.py`.

### flags_history.csv
```
run_date, ticker, tier, accruals_flag, revenue_flag, capex_flag, balance_sheet_flag,
leverage_flag, governance_flag, market_flag, text_flag, sector_flag, flag_details
```
Boolean columns are 0/1. `flag_details` is a free-text column listing which specific rules fired and the values.

### ratios_latest.csv
```
ticker, fetch_date, dso_days, dso_yoy_change, inventory_days, inv_yoy_change,
cfo_ni_ratio, sloan_accruals, beneish_m, dechow_f, altman_z, capex_da_ratio,
sbc_pct_revenue, goodwill_pct_assets, ... (sector-specific columns appended)
```

## Tools
- **edgartools MCP** — primary data source. Prefer this over web search for any financial ratio or filing question.
- **WebSearch** — only for things EDGAR doesn't have (short interest, borrow cost, recent press)
- **File tools** — read/write CSVs and reports directly
- **Bash** — `python sync_watchlist.py` before every triage run

## Adding Sectors
When the user wants to cover a new sector:
1. Add a new file under `rubrics/`
2. Add a new `sector_subgroup` value to `SUBGROUP_MAP` in `sync_watchlist.py`
3. Add a row to the routing table in Step 3 of the workflow

Don't bloat existing rubrics with sector-specific rules.
