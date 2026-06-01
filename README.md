# Forensic Triage
> Claude-driven forensic-accounting screen over the coverage universe — flags US-listed names with accounting irregularities / quality-of-earnings concerns (Red/Yellow/Green); output is flagged companies + specific concerns, not a composite score.

- **Status:** live (interactive is the source-of-truth mode; the Saturday remote trigger runs degraded without MCPs)
- **Runtime/trigger:** Claude-driven on-demand (interactive) · scheduled remote CCR trigger (Sat 09:00 ET)
- **Reads:** Coverage Manager `coverage_universe_tickers.csv` (synced) · edgartools MCP (snapshots / statements / trends / events / notes) · WebSearch (insider / short interest)
- **Writes:** `data/{watchlist,flags_history,ratios_latest}.csv` · `reports/forensic_<date>.md` · Slack `#forensic-flags` (heartbeat)
- **Run:** `python sync_watchlist.py`, then Claude runs the 5-step workflow  ·  **Entry points:** `sync_watchlist.py`, `CLAUDE.md`, `rubrics/`

Claude-driven forensic accounting screen for a coverage universe of US-listed companies. Surfaces names with accounting irregularities or quality-of-earnings concerns worth a deep dive — output is **flagged companies + the specific concerns**, not a single composite score.

See [`CLAUDE.md`](./CLAUDE.md) for the full workflow, tier system, and CSV formats.

## Project layout

```
forensic_triage/
  CLAUDE.md                 # Workflow instructions for Claude
  sync_watchlist.py         # Sync watchlist from Coverage Manager master list
  data/
    watchlist.csv           # Tracked tickers (synced — do not hand-edit rows)
    flags_history.csv       # Per-run flag state for diffing
    ratios_latest.csv       # Latest ratio snapshot
  rubrics/
    general.md              # 8 universal flag families
    healthcare_services.md  # 9 HC services-specific flag families
    medtech.md              # 9 medtech-specific flag families
  reports/                  # Generated weekly triage reports
```

## Watchlist sync

The watchlist is derived from the [Coverage-Manager](https://github.com/jroypeterson/Coverage-Manager) repo. Re-sync before every triage:

```bash
python sync_watchlist.py            # write
python sync_watchlist.py --dry-run  # report only
```

By default the script looks for the coverage CSV at `../Coverage Manager/data/coverage_universe_tickers.csv` (sibling-folder layout). For the remote weekly trigger, set `FORENSIC_COVERAGE_CSV` to point at the cloned coverage CSV.

## Weekly schedule

A scheduled remote Claude trigger runs the full triage every Saturday morning. It syncs the watchlist, applies the rubrics via the EDGAR Tools MCP, writes a dated markdown report under `reports/`, posts a one-line summary to Slack `#forensic-flag`, and commits the updated `flags_history.csv` and report back to this repo.
