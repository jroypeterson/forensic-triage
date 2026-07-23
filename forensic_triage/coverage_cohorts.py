"""Coverage cohorts — partition the screenable universe into JP's priority rings.

The forensic coverage dashboard (and the screening priority order) group every
name into ONE of four disjoint rings, widest-priority first:

    portfolio  ->  researching  ->  core  ->  sp500   (+ `other` residual)

A name counts under its HIGHEST-priority ring only (a Portfolio name that is also
in the S&P 500 is `portfolio`, never `sp500`). This mirrors the tier partition in
``transcripts/coverage.py`` (`_tiers_partition`) so the two projects read the same
Coverage-Manager exports the same way.

Rosters read (all free, local files):
  - portfolio    <- Coverage Manager/exports/portfolio.json      (keys = tickers)
  - researching  <- Coverage Manager/exports/researching.json
  - core         <- Coverage Manager/exports/universe_metadata.json  (core == "Y")
  - sp500        <- sigma-alert/sources/sp500.txt                 (one ticker/line)

`other` = a name in forensic's watchlist that is in none of the four rings (a CM
coverage name that is not Portfolio/Researching/Core and not in the S&P 500). It's
surfaced, never hidden — silent truncation is the failure mode we avoid.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # package file -> project root
CM_EXPORTS = ROOT.parent / "Coverage Manager" / "exports"
SP500_FILE = ROOT.parent / "sigma-alert" / "sources" / "sp500.txt"

# Priority order, widest ring last. `other` is the residual bucket.
COHORT_ORDER = ["portfolio", "researching", "core", "sp500", "other"]
COHORT_RANK = {c: i for i, c in enumerate(COHORT_ORDER)}
COHORT_LABEL = {
    "portfolio": "Portfolio",
    "researching": "Researching",
    "core": "Core coverage",
    "sp500": "S&P 500",
    "other": "Other coverage",
}


def _norm(t: str) -> str:
    return (t or "").strip().upper()


def _load_json_keys(fname: str) -> set[str]:
    p = CM_EXPORTS / fname
    if not p.exists():
        return set()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {_norm(k) for k in d.keys() if k}
    except Exception:
        return set()


def load_portfolio() -> set[str]:
    return _load_json_keys("portfolio.json")


def load_researching() -> set[str]:
    return _load_json_keys("researching.json")


def load_core() -> set[str]:
    """Core = universe_metadata.json entries flagged core == 'Y'."""
    p = CM_EXPORTS / "universe_metadata.json"
    if not p.exists():
        return set()
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
        return {_norm(t) for t, v in meta.items() if (v or {}).get("core") == "Y"}
    except Exception:
        return set()


def load_sp500() -> set[str]:
    """S&P 500 tickers from sigma-alert's Wikipedia-scrape source file."""
    if not SP500_FILE.exists():
        return set()
    out: set[str] = set()
    for line in SP500_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(_norm(line))
    return out


def load_rosters() -> dict[str, set[str]]:
    """All four rosters as RAW (non-disjoint) sets, keyed by cohort name."""
    return {
        "portfolio": load_portfolio(),
        "researching": load_researching(),
        "core": load_core(),
        "sp500": load_sp500(),
    }


def cohort_for(ticker: str, rosters: dict[str, set[str]] | None = None) -> str:
    """Return the ticker's cohort by priority (portfolio>researching>core>sp500>other)."""
    if rosters is None:
        rosters = load_rosters()
    t = _norm(ticker)
    for c in ("portfolio", "researching", "core", "sp500"):
        if t in rosters.get(c, set()):
            return c
    return "other"


def assign_cohorts(tickers: list[str] | set[str],
                   rosters: dict[str, set[str]] | None = None) -> dict[str, str]:
    """Map each ticker -> its disjoint cohort. Every input ticker lands somewhere."""
    if rosters is None:
        rosters = load_rosters()
    return {_norm(t): cohort_for(t, rosters) for t in tickers}


def sort_key(cohort: str, ticker: str) -> tuple:
    """Screening priority: portfolio -> researching -> core -> sp500 -> other, then A-Z."""
    return (COHORT_RANK.get(cohort, 99), _norm(ticker))
