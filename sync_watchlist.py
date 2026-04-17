"""Sync forensic_triage/data/watchlist.csv from Coverage Manager master list.

Reads:  ../Coverage Manager/data/coverage_universe_tickers.csv
Writes: data/watchlist.csv

Rules:
  - Only US-listed names (must have a CIK — EDGAR is the data source)
  - Exclude Biopharma (forensic triage de-prioritizes biotech accounting)
  - Map Sector (JP) -> forensic subgroup (see SUBGROUP_MAP)
  - Preserve manual `notes` and original `added_date` for tickers that survive
  - Report adds / removes / subgroup changes to stdout

Run:  python sync_watchlist.py
      python sync_watchlist.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"

# Coverage CSV path resolution:
#   1. FORENSIC_COVERAGE_CSV env var (used by remote scheduled trigger)
#   2. Local sibling layout: ../Coverage Manager/data/coverage_universe_tickers.csv
def resolve_coverage_csv() -> Path:
    env_path = os.environ.get("FORENSIC_COVERAGE_CSV")
    if env_path:
        return Path(env_path)
    return ROOT.parent / "Coverage Manager" / "data" / "coverage_universe_tickers.csv"

# Map Coverage Manager Sector (JP) -> forensic_triage sector_subgroup.
# Kept in sync with Coverage Manager's ALLOWED_SECTORS_JP (config.py).
# Coverage Manager retired "PA" and "Healthcare Real Estate" on 2026-04-17
# (collapsed into "Other" and "Healthcare Services" respectively). The new
# "Healthcare Real Estate" subsector rolls up under hc_services here.
SUBGROUP_MAP = {
    "Healthcare Services": "hc_services",
    "MedTech": "medtech",
    "Life Science Tools": "medtech",
    # Everything else that survives the filter falls through to "general"
    "Tech": "general",
    "SaaS": "general",
    "Fintech": "general",
    "Other": "general",
}

EXCLUDED_SECTORS = {"Biopharma"}

WATCHLIST_FIELDS = [
    "ticker",
    "company_name",
    "sector_subgroup",
    "subsector",
    "core",
    "added_date",
    "notes",
]


def load_existing_watchlist() -> dict[str, dict]:
    if not WATCHLIST_CSV.exists():
        return {}
    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["ticker"]: row for row in reader if row.get("ticker")}


def load_coverage(coverage_csv: Path) -> list[dict]:
    rows = []
    with coverage_csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("CIK"):
                continue
            sector = row.get("Sector (JP)", "").strip()
            if sector in EXCLUDED_SECTORS:
                continue
            if sector not in SUBGROUP_MAP:
                continue
            rows.append(row)
    return rows


def build_new_watchlist(
    coverage_rows: list[dict],
    existing: dict[str, dict],
    today: str,
) -> tuple[list[dict], list[str], list[str], list[tuple[str, str, str]]]:
    """Returns (new_rows, added_tickers, removed_tickers, subgroup_changes)."""
    new_rows: list[dict] = []
    seen: set[str] = set()
    added: list[str] = []
    subgroup_changes: list[tuple[str, str, str]] = []

    for row in coverage_rows:
        ticker = row["Ticker"].strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        sector = row["Sector (JP)"].strip()
        subgroup = SUBGROUP_MAP[sector]
        prev = existing.get(ticker)

        new_row = {
            "ticker": ticker,
            "company_name": row.get("Company Name", "").strip(),
            "sector_subgroup": subgroup,
            "subsector": row.get("Subsector (JP)", "").strip(),
            "core": row.get("Core", "").strip(),
            "added_date": prev["added_date"] if prev and prev.get("added_date") else today,
            "notes": prev.get("notes", "") if prev else "",
        }
        new_rows.append(new_row)

        if not prev:
            added.append(ticker)
        elif prev.get("sector_subgroup") and prev["sector_subgroup"] != subgroup:
            subgroup_changes.append((ticker, prev["sector_subgroup"], subgroup))

    removed = sorted(set(existing) - seen)
    new_rows.sort(key=lambda r: (r["sector_subgroup"], r["ticker"]))
    return new_rows, sorted(added), removed, subgroup_changes


def write_watchlist(rows: list[dict]) -> None:
    WATCHLIST_CSV.parent.mkdir(parents=True, exist_ok=True)
    with WATCHLIST_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WATCHLIST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    coverage_csv = resolve_coverage_csv()
    if not coverage_csv.exists():
        print(f"ERROR: coverage CSV not found at {coverage_csv}", file=sys.stderr)
        print("Set FORENSIC_COVERAGE_CSV env var or check sibling-folder layout.", file=sys.stderr)
        return 1

    existing = load_existing_watchlist()
    coverage_rows = load_coverage(coverage_csv)
    today = date.today().isoformat()
    new_rows, added, removed, subgroup_changes = build_new_watchlist(
        coverage_rows, existing, today
    )

    by_subgroup: dict[str, int] = {}
    for r in new_rows:
        by_subgroup[r["sector_subgroup"]] = by_subgroup.get(r["sector_subgroup"], 0) + 1

    print(f"Coverage source: {coverage_csv}")
    print(f"Watchlist target: {WATCHLIST_CSV}")
    print(f"Total in new watchlist: {len(new_rows)}")
    for sg in sorted(by_subgroup):
        print(f"  {sg}: {by_subgroup[sg]}")
    print(f"Added: {len(added)}")
    print(f"Removed: {len(removed)}")
    print(f"Subgroup changes: {len(subgroup_changes)}")

    if added:
        print("\n+ Added:")
        for t in added[:50]:
            print(f"  + {t}")
        if len(added) > 50:
            print(f"  ... and {len(added) - 50} more")
    if removed:
        print("\n- Removed:")
        for t in removed[:50]:
            print(f"  - {t}")
        if len(removed) > 50:
            print(f"  ... and {len(removed) - 50} more")
    if subgroup_changes:
        print("\n~ Subgroup changes:")
        for t, old, new in subgroup_changes[:50]:
            print(f"  ~ {t}: {old} -> {new}")

    if args.dry_run:
        print("\n[dry-run] no file written")
        return 0

    write_watchlist(new_rows)
    print(f"\nWrote {len(new_rows)} rows to {WATCHLIST_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
