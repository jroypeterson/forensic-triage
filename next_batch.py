"""Pick the next batch of names to screen — the daily "a few each day" driver.

Path B (interactive) chips through the ~274 domestic watchlist names a few at a
time. This deterministic helper picks the next batch so each session knows exactly
what to screen, prioritised toward JP's coverage:

  1. core=Y first (names JP analytically covers)
  2. then by subgroup: hc_services -> medtech -> general (HC focus)
  3. then alphabetical

A name is "done this cycle" once it has a flags_history row dated >= CYCLE_START
(the recalibration baseline). Foreign filers (filer_type=foreign) are never
screened by EDGAR — they belong to the Data Gap tier — so they're excluded here
and reported separately.

Usage:
  python next_batch.py            # show the next batch (default 8) + progress
  python next_batch.py -n 5       # batch of 5
  python next_batch.py --cycle-start 2026-06-20
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).parent
WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"
FLAGS_HISTORY_CSV = ROOT / "data" / "flags_history.csv"

# Names screened on/after this date count as done for the current cycle. Bump it
# when a fresh full re-screen cycle starts. Default = the 2026-06-20 recalibration.
DEFAULT_CYCLE_START = "2026-06-20"

SUBGROUP_ORDER = {"hc_services": 0, "medtech": 1, "general": 2}


def load_watchlist() -> list[dict]:
    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def screened_since(cycle_start: str) -> set[str]:
    if not FLAGS_HISTORY_CSV.exists():
        return set()
    done: set[str] = set()
    with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("run_date") or "") >= cycle_start and row.get("ticker"):
                done.add(row["ticker"].strip())
    return done


def sort_key(row: dict):
    core_rank = 0 if (row.get("core", "").strip().upper() == "Y") else 1
    sg_rank = SUBGROUP_ORDER.get(row.get("sector_subgroup", ""), 9)
    return (core_rank, sg_rank, row.get("ticker", ""))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-n", "--batch-size", type=int, default=8, help="How many names this batch")
    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START,
                   help=f"Names screened on/after this date count as done (default {DEFAULT_CYCLE_START})")
    args = p.parse_args()

    watchlist = load_watchlist()
    domestic = [r for r in watchlist if r.get("filer_type", "domestic") != "foreign"]
    foreign = [r for r in watchlist if r.get("filer_type") == "foreign"]
    done = screened_since(args.cycle_start)

    pending = [r for r in domestic if r["ticker"].strip() not in done]
    pending.sort(key=sort_key)

    n_dom = len(domestic)
    n_done = sum(1 for r in domestic if r["ticker"].strip() in done)
    print(f"Cycle start: {args.cycle_start}")
    print(f"Domestic screened this cycle: {n_done}/{n_dom}  ({n_dom - n_done} pending)")
    print(f"Foreign (Data Gap, not EDGAR-screened): {len(foreign)}")
    print()
    if not pending:
        print("Cycle complete — every domestic name screened since cycle start. Bump --cycle-start to re-screen.")
        return 0

    batch = pending[:args.batch_size]
    print(f"Next batch ({len(batch)}):")
    for r in batch:
        core = "core" if r.get("core", "").strip().upper() == "Y" else "    "
        print(f"  {r['ticker']:<6} [{core}] {r['sector_subgroup']:<12} {r.get('company_name','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
