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
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"

# SEC ticker->CIK map, used to resolve CIKs for the S&P 500 names that expand the
# universe beyond CM coverage (the 4th coverage ring). Free, cached locally.
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_TICKERS_CACHE = ROOT / "data" / ".sec_company_tickers.json"

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
    "cik",
    "sector_subgroup",
    "subsector",
    "core",
    "filer_type",
    "added_date",
    "notes",
    "source",  # "cm" (Coverage Manager universe) or "sp500" (S&P 500 expansion ring)
    "cohort",  # portfolio|researching|core|sp500|other — baked so CI (no sibling repos) reads it
]

COHORT_TOTALS_JSON = ROOT / "data" / "cohort_totals.json"


def normalize_cik(raw: str) -> str:
    """Normalize a Coverage Manager CIK to a zero-padded 10-digit string.

    EDGAR APIs want a 10-digit zero-padded CIK. CM stores it variously
    (with/without leading zeros, sometimes a 'CIK' prefix). Empty -> ''.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    s = s.upper().removeprefix("CIK").lstrip("0") or "0"
    if not s.isdigit():
        return ""
    return s.zfill(10)


def derive_filer_type(row: dict) -> str:
    """domestic (10-K filer) vs foreign (20-F/IFRS filer).

    The forensic rubric is built on 10-K disclosures (financial-statement notes,
    MD&A). ADR / cross-listed foreign private issuers file a 20-F with different
    structure and often IFRS, which the 10-K-based rubric cannot evaluate
    cleanly — so they must be routed to manual review (Data Gap tier), NOT
    silently screened as Green. We TAG rather than drop so coverage stays visible.
    """
    iso = (row.get("Country (ISO)", "") or "").strip().upper()
    listing = (row.get("Listing Type", "") or "").strip().lower()
    if (iso and iso != "USA") or "adr" in listing or "cross-listed" in listing:
        return "foreign"
    return "domestic"


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
            "cik": normalize_cik(row.get("CIK", "")),
            "sector_subgroup": subgroup,
            "subsector": row.get("Subsector (JP)", "").strip(),
            "core": row.get("Core", "").strip(),
            "filer_type": derive_filer_type(row),
            "added_date": prev["added_date"] if prev and prev.get("added_date") else today,
            "notes": prev.get("notes", "") if prev else "",
            "source": "cm",
        }
        new_rows.append(new_row)

        if not prev:
            added.append(ticker)
        elif prev.get("sector_subgroup") and prev["sector_subgroup"] != subgroup:
            subgroup_changes.append((ticker, prev["sector_subgroup"], subgroup))

    removed = sorted(set(existing) - seen)
    new_rows.sort(key=lambda r: (r["sector_subgroup"], r["ticker"]))
    return new_rows, sorted(added), removed, subgroup_changes


def load_sec_ticker_ciks() -> dict[str, str]:
    """Return {TICKER: zero-padded-10-digit CIK} from SEC's ticker map.

    Cached at SEC_TICKERS_CACHE; fetched once (free, no key — just a descriptive
    User-Agent per SEC policy). On any fetch failure with no cache, returns {} and
    the extras step degrades loudly (names without a CIK can't be EDGAR-screened).
    """
    data = None
    if SEC_TICKERS_CACHE.exists():
        try:
            data = json.loads(SEC_TICKERS_CACHE.read_text(encoding="utf-8"))
        except Exception:
            data = None
    if data is None:
        ua = os.environ.get("EDGAR_IDENTITY") or "Jason Peterson jroypeterson@gmail.com"
        req = urllib.request.Request(SEC_TICKERS_URL, headers={"User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            SEC_TICKERS_CACHE.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            print(f"WARNING: could not fetch SEC ticker map ({e}); "
                  f"S&P 500 extras without a cached CIK will be skipped.", file=sys.stderr)
            return {}
    out: dict[str, str] = {}
    for rec in data.values():
        t = str(rec.get("ticker", "")).strip().upper()
        cik = rec.get("cik_str")
        if t and cik is not None:
            out[t] = str(cik).zfill(10)
    return out


def load_cm_master_tickers(coverage_csv: Path) -> set[str]:
    """Every ticker in the CM master (pre-filter), so the S&P 500 expansion only
    ADDS names CM doesn't already carry — it never re-introduces a name CM
    deliberately filtered out (e.g. a Biopharma name)."""
    out: set[str] = set()
    with coverage_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            t = (row.get("Ticker", "") or "").strip().upper()
            if t:
                out.add(t)
    return out


def build_sp500_extras(
    existing: dict[str, dict],
    cm_master: set[str],
    already_added: set[str],
    today: str,
) -> tuple[list[dict], list[str], list[str]]:
    """Rows for the S&P 500 expansion ring: roster-priority names NOT in the CM
    master. Returns (rows, added_tickers, unresolved_no_cik)."""
    try:
        import coverage_cohorts as cc
    except Exception as e:
        print(f"WARNING: coverage_cohorts unavailable ({e}); skipping S&P 500 expansion.",
              file=sys.stderr)
        return [], [], []

    rosters = cc.load_rosters()
    # The expansion ring is the S&P 500 specifically. Portfolio/Researching/Core are
    # already CM data (in cm_master); only the S&P 500 adds names CM doesn't carry.
    # (Using just the sp500 roster avoids pulling in foreign CM-position tickers whose
    # export format differs from the CM master, which have no SEC CIK anyway.)
    core_set = rosters["core"]
    extras = sorted(t for t in rosters["sp500"]
                    if t not in cm_master and t not in already_added)

    sec_ciks = load_sec_ticker_ciks() if extras else {}
    rows: list[dict] = []
    added: list[str] = []
    unresolved: list[str] = []
    for ticker in extras:
        cik = sec_ciks.get(ticker) or sec_ciks.get(ticker.replace(".", "-"))
        if not cik:
            unresolved.append(ticker)
            continue  # no CIK -> can't EDGAR-screen; skip loudly (reported below)
        prev = existing.get(ticker)
        rows.append({
            "ticker": ticker,
            "company_name": prev.get("company_name", "") if prev else "",
            "cik": cik,
            "sector_subgroup": "general",
            "subsector": "",
            "core": "Y" if ticker in core_set else "",
            "filer_type": "domestic",  # S&P 500 constituents are US 10-K filers
            "added_date": prev["added_date"] if prev and prev.get("added_date") else today,
            "notes": prev.get("notes", "") if prev else "",
            "source": "sp500",
        })
        if not prev:
            added.append(ticker)
    return rows, sorted(added), sorted(unresolved)


def write_watchlist(rows: list[dict]) -> None:
    WATCHLIST_CSV.parent.mkdir(parents=True, exist_ok=True)
    with WATCHLIST_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WATCHLIST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    parser.add_argument("--no-sp500", action="store_true",
                        help="Skip the S&P 500 expansion ring (CM universe only)")
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

    # S&P 500 expansion ring: add roster names CM doesn't already carry.
    sp_added: list[str] = []
    sp_unresolved: list[str] = []
    if not args.no_sp500:
        cm_master = load_cm_master_tickers(coverage_csv)
        already = {r["ticker"] for r in new_rows}
        sp_rows, sp_added, sp_unresolved = build_sp500_extras(
            existing, cm_master, already, today
        )
        new_rows.extend(sp_rows)
        new_rows.sort(key=lambda r: (r["sector_subgroup"], r["ticker"]))

    # Recompute removals against the FINAL set (build_new_watchlist only saw the CM
    # pass, so without this the S&P 500 rows the extras step re-adds show as removed).
    final_tickers = {r["ticker"] for r in new_rows}
    removed = sorted(set(existing) - final_tickers)

    # Bake the cohort onto every row (+ disjoint roster totals) so CI — which has no
    # CM/sigma sibling repos — reads cohorts from the committed watchlist, not live.
    cohort_totals: dict[str, int] = {}
    try:
        import coverage_cohorts as cc
        rosters = cc.load_rosters()
        for r in new_rows:
            r["cohort"] = cc.cohort_for(r["ticker"], rosters)
        p, rr, co, sp = (rosters["portfolio"], rosters["researching"],
                         rosters["core"], rosters["sp500"])
        cohort_totals = {
            "portfolio": len(p), "researching": len(rr - p),
            "core": len(co - rr - p), "sp500": len(sp - co - rr - p),
        }
    except Exception as e:
        print(f"WARNING: cohort stamping failed ({e}); rows left without a cohort.",
              file=sys.stderr)
        for r in new_rows:
            r.setdefault("cohort", "")

    by_subgroup: dict[str, int] = {}
    for r in new_rows:
        by_subgroup[r["sector_subgroup"]] = by_subgroup.get(r["sector_subgroup"], 0) + 1

    print(f"Coverage source: {coverage_csv}")
    print(f"Watchlist target: {WATCHLIST_CSV}")
    print(f"Total in new watchlist: {len(new_rows)}")
    for sg in sorted(by_subgroup):
        print(f"  {sg}: {by_subgroup[sg]}")
    foreign = sum(1 for r in new_rows if r["filer_type"] == "foreign")
    print(f"Foreign (20-F/ADR -> Data Gap manual review): {foreign} of {len(new_rows)}")
    n_cm = sum(1 for r in new_rows if r.get("source") == "cm")
    n_sp = sum(1 for r in new_rows if r.get("source") == "sp500")
    print(f"By source: cm={n_cm}  sp500={n_sp}")
    print(f"Added (CM): {len(added)}")
    print(f"Added (S&P 500 ring): {len(sp_added)}")
    if sp_unresolved:
        print(f"S&P 500 names skipped (no CIK in SEC map): {len(sp_unresolved)} "
              f"-> {', '.join(sp_unresolved[:15])}{' ...' if len(sp_unresolved) > 15 else ''}")
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
    if cohort_totals:
        COHORT_TOTALS_JSON.write_text(json.dumps(cohort_totals, indent=2), encoding="utf-8")
        print(f"Wrote cohort totals to {COHORT_TOTALS_JSON}: {cohort_totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
