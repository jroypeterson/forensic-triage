"""Pick the next batch of names to screen — the daily "a few each day" driver.

Path B (interactive) chips through the domestic watchlist names a few at a
time. This deterministic helper picks the next batch so each session knows exactly
what to screen, prioritised by JP's coverage rings:

  1. by cohort: portfolio -> researching -> core -> sp500 -> other
  2. then by subgroup within a cohort: hc_services -> medtech -> general (HC focus)
  3. then alphabetical

A name is "done this cycle" once it has a flags_history row dated >= CYCLE_START
(the recalibration baseline) WITH status=complete (codex R2 idempotency). A row
written by a transient fetch failure (status=fetch_failed) does NOT mark the name
done — it retries next run. A structural Data Gap (foreign/stale/not-disclosed) is
written status=complete and IS done. Older rows without a status column are treated
as complete (back-compat). Foreign filers (filer_type=foreign) are never screened by
EDGAR — they belong to the Data Gap tier — so they're excluded here and reported separately.

Usage:
  python next_batch.py            # show the next batch (default 8) + progress
  python next_batch.py -n 5       # batch of 5
  python next_batch.py --cycle-start 2026-06-20
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import coverage_cohorts as cc

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
    """Tickers DONE this cycle: a flags_history row dated >= cycle_start with status=complete.

    A `status=fetch_failed` row does NOT count as done (transient failure retries next run).
    Rows without a `status` column (legacy interactive runs) are treated as complete."""
    if not FLAGS_HISTORY_CSV.exists():
        return set()
    done: set[str] = set()
    with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        has_status = "status" in (reader.fieldnames or [])
        for row in reader:
            if (row.get("run_date") or "") < cycle_start or not row.get("ticker"):
                continue
            status = (row.get("status") or "").strip() if has_status else "complete"
            if status in ("", "complete"):
                done.add(row["ticker"].strip())
    return done


def row_cohort(row: dict, rosters: dict[str, set[str]] | None = None) -> str:
    """Baked `cohort` column (CI-safe) if present, else compute live from rosters.
    `rosters=None` → `cohort_for` loads them live (defensive; avoids a hard dep on
    the caller pre-loading rosters)."""
    c = (row.get("cohort") or "").strip()
    return c if c else cc.cohort_for(row.get("ticker", ""), rosters)


def sort_key(row: dict, rosters: dict[str, set[str]] | None = None):
    cohort_rank = cc.COHORT_RANK.get(row_cohort(row, rosters), 99)
    sg_rank = SUBGROUP_ORDER.get(row.get("sector_subgroup", ""), 9)
    return (cohort_rank, sg_rank, row.get("ticker", ""))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-n", "--batch-size", type=int, default=8, help="How many names this batch")
    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START,
                   help=f"Names screened on/after this date count as done (default {DEFAULT_CYCLE_START})")
    args = p.parse_args()

    watchlist = load_watchlist()
    rosters = cc.load_rosters()
    domestic = [r for r in watchlist if r.get("filer_type", "domestic") != "foreign"]
    foreign = [r for r in watchlist if r.get("filer_type") == "foreign"]
    done = screened_since(args.cycle_start)

    pending = [r for r in domestic if r["ticker"].strip() not in done]
    pending.sort(key=lambda r: sort_key(r, rosters))

    n_dom = len(domestic)
    n_done = sum(1 for r in domestic if r["ticker"].strip() in done)
    print(f"Cycle start: {args.cycle_start}")
    print(f"Domestic screened this cycle: {n_done}/{n_dom}  ({n_dom - n_done} pending)")
    print(f"Foreign (Data Gap, not EDGAR-screened): {len(foreign)}")
    print()
    if not pending:
        print("Cycle complete - every domestic name screened since cycle start. Bump --cycle-start to re-screen.")
        return 0

    batch = pending[:args.batch_size]
    print(f"Next batch ({len(batch)}):")
    for r in batch:
        cohort = row_cohort(r, rosters)
        print(f"  {r['ticker']:<6} [{cohort:<11}] {r['sector_subgroup']:<12} {r.get('company_name','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
