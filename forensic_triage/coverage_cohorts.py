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
  - sp500        <- Coverage Manager/data/index_membership/sp500_latest.json
                   (board #354; sigma-alert/sources/sp500.txt is the fallback)

`other` = a name in forensic's watchlist that is in none of the four rings (a CM
coverage name that is not Portfolio/Researching/Core and not in the S&P 500). It's
surfaced, never hidden — silent truncation is the failure mode we avoid.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # package file -> project root
CM_EXPORTS = ROOT.parent / "Coverage Manager" / "exports"
SP500_SNAPSHOT = (ROOT.parent / "Coverage Manager" / "data" /
                  "index_membership" / "sp500_latest.json")
# The retiring second copy; read only when the snapshot is unusable.
SP500_FILE = ROOT.parent / "sigma-alert" / "sources" / "sp500.txt"
# Below this the snapshot is refused rather than used: a short S&P list does not
# fail here, it demotes real S&P names into the `other` residual ring.
SP500_MIN_PLAUSIBLE = 400
SP500_MAX_AGE_DAYS = 45

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
    """S&P 500 tickers, from Coverage Manager's index-membership snapshot.

    Board #354 step 4. The snapshot lane shipped 2026-09-08 and `sector_chart_pack`
    and `screens_equity` both read it; `sigma-alert/sources/sp500.txt` is the retiring
    second copy and stays here only as a fallback.

    ⛑ **An empty return is a real answer here, not an error**, and that is why the
    plausibility floor matters. `sp500` is the widest ring: a name in no other roster
    lands in `other`, so a SHORT S&P list does not fail, it silently demotes real S&P
    names into the residual bucket and changes which companies get screened first.
    Measured before migrating: the snapshot and the text file agreed on 503 of 503
    names, so this is a verified no-op today.

    Returns `set()` when neither source exists -- the caller already treats an empty
    roster as fatal for a sync (see the module docstring), and inventing membership
    would be worse than saying nothing.
    """
    names, why = _sp500_from_snapshot()
    if names is not None:
        return names
    if not SP500_FILE.exists():
        print(f"  WARN: S&P 500 snapshot {why} and no fallback at {SP500_FILE}; "
              f"the sp500 ring will be EMPTY")
        return set()
    # ⛑ SAY WHICH SOURCE SERVED. A silent fallback is how a dead source stays invisible
    # -- the fleet has already paid for that once, and it is the precise state this
    # migration exists to end: two lists, two cadences, nothing announcing which one is
    # in play. When the text file is finally retired this branch becomes the empty ring
    # above, and going quiet about it would drop the whole S&P cohort with a green run.
    print(f"  WARN: S&P 500 snapshot {why}; falling back to {SP500_FILE.name}")
    out: set[str] = set()
    for line in SP500_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(_norm(line))
    # The floor applies to the FALLBACK too; a half-written monthly refresh would
    # otherwise demote real S&P names into the residual ring with nothing reported.
    if 0 < len(out) < SP500_MIN_PLAUSIBLE:
        print(f"  WARN: {SP500_FILE.name} has only {len(out)} names (expected ~503); "
              f"treating the S&P ring as UNKNOWN rather than short")
        return set()
    return out


def _sp500_from_snapshot() -> tuple[set[str] | None, str]:
    """(members, reason). `None` means "use the fallback", never "the index is empty"."""
    import datetime

    if not SP500_SNAPSHOT.exists():
        return None, "absent"
    try:
        doc = json.loads(SP500_SNAPSHOT.read_text(encoding="utf-8"))
        names = {_norm(h["ticker"]) for h in doc.get("holdings") or []
                 if isinstance(h, dict) and h.get("ticker")}
    # ⛑ OSError belongs here. Without it a Dropbox lock on the snapshot -- WinError 5,
    # the most common IO failure in this workspace -- propagates out of `load_rosters()`
    # into `dashboard.py` and `next_batch.py`, neither of which wraps the call, instead
    # of taking the fallback. Note `_load_json_keys` and `load_core` in this same file
    # already catch broadly; this reader was the odd one out (review, 2026-09-16).
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"unreadable ({type(exc).__name__}: {exc})"
    if len(names) < SP500_MIN_PLAUSIBLE:
        return None, f"only {len(names)} names (expected ~503)"
    as_of = str(doc.get("as_of") or "")
    if not as_of:
        return None, "carries no as_of date"   # undatable is not "never stale"
    # CM writes `stale_days` per index; read it rather than keeping a local copy that
    # drifts the day CM changes it.
    limit = doc.get("stale_days")
    if not isinstance(limit, int) or limit <= 0:
        limit = SP500_MAX_AGE_DAYS
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(as_of[:10])).days
    except ValueError:
        return None, f"unparseable as_of {as_of!r}"
    if age > limit:
        return None, f"as_of {as_of} is {age}d old (limit {limit})"
    return names, "ok"


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
