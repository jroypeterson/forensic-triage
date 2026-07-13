"""Tests for the coverage dashboard + cohort partition (coverage_cohorts, dashboard)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import coverage_cohorts as cc  # noqa: E402
import dashboard  # noqa: E402


# --- cohort priority (disjoint rings) ---

def test_cohort_priority_portfolio_wins():
    rosters = {"portfolio": {"AAA"}, "researching": {"AAA"},
               "core": {"AAA"}, "sp500": {"AAA"}}
    # A name in every ring resolves to the highest-priority one.
    assert cc.cohort_for("AAA", rosters) == "portfolio"


def test_cohort_priority_ladder():
    rosters = {"portfolio": {"P"}, "researching": {"R"}, "core": {"C"}, "sp500": {"S"}}
    assert cc.cohort_for("R", rosters) == "researching"
    assert cc.cohort_for("C", rosters) == "core"
    assert cc.cohort_for("S", rosters) == "sp500"
    assert cc.cohort_for("Z", rosters) == "other"  # in no ring


def test_cohort_case_insensitive():
    rosters = {"portfolio": {"AAA"}, "researching": set(), "core": set(), "sp500": set()}
    assert cc.cohort_for("aaa", rosters) == "portfolio"


# --- dashboard.gather partition + counts + excluded ---

def _wl_row(ticker, cohort, filer="domestic"):
    return {"ticker": ticker, "cohort": cohort, "filer_type": filer}


def test_gather_partition_counts_and_excluded(monkeypatch):
    watchlist = [
        _wl_row("AAA", "portfolio"),               # screened Red
        _wl_row("BBB", "portfolio"),               # pending
        _wl_row("CCC", "portfolio", "foreign"),    # data-gap
        _wl_row("DDD", "core"),                    # screened Green
        _wl_row("FFF", "core"),                    # screened Yellow
        _wl_row("EEE", "sp500"),                   # pending
    ]
    screens = {
        "AAA": {"tier": "Red", "flag_details": "revenue: DSO +61%", "run_date": "2026-07-01"},
        "DDD": {"tier": "Green", "flag_details": "", "run_date": "2026-07-01"},
        "FFF": {"tier": "Yellow", "flag_details": "governance soft", "run_date": "2026-07-01"},
    }
    totals = {"portfolio": 5, "researching": 0, "core": 4, "sp500": 10}

    monkeypatch.setattr(dashboard, "load_watchlist", lambda: watchlist)
    monkeypatch.setattr(dashboard, "latest_screens", lambda cs: screens)
    monkeypatch.setattr(dashboard, "_load_cohort_totals", lambda: totals)
    monkeypatch.setattr(dashboard, "_load_history", lambda: [])
    monkeypatch.setattr(cc, "load_rosters", lambda: {k: set() for k in
                                                     ("portfolio", "researching", "core", "sp500")})

    data = dashboard.gather(cycle_start="2026-06-20", per_day=6, today="2026-07-13")
    coh = data["cohorts"]

    # Portfolio: 2 domestic (AAA screened, BBB pending) + 1 foreign; roster 5 -> excluded 3.
    assert coh["portfolio"]["domestic"] == 2
    assert coh["portfolio"]["foreign"] == 1
    assert coh["portfolio"]["screened"] == 1
    assert coh["portfolio"]["pending"] == 1
    assert coh["portfolio"]["tiers"]["Red"] == 1
    assert coh["portfolio"]["excluded"] == 2  # 5 roster - (2 dom + 1 foreign in watchlist)

    # Core: 2 screened (Green + Yellow), 0 pending; roster 4 -> excluded 2.
    assert coh["core"]["screened"] == 2
    assert coh["core"]["tiers"]["Green"] == 1
    assert coh["core"]["tiers"]["Yellow"] == 1
    assert coh["core"]["pending"] == 0
    assert coh["core"]["excluded"] == 2

    # S&P 500: 1 domestic pending; roster 10 -> excluded 9.
    assert coh["sp500"]["domestic"] == 1
    assert coh["sp500"]["pending"] == 1
    assert coh["sp500"]["excluded"] == 9

    t = data["totals"]
    assert t["domestic"] == 5           # 2 + 2 + 1
    assert t["screened"] == 3
    assert t["red"] == 1 and t["yellow"] == 1
    assert t["pending"] == 2            # BBB + EEE
    assert t["foreign"] == 1
    assert t["excluded"] == 2 + 0 + 2 + 9

    # Flagged: priority order (portfolio before core), Red before Yellow within a ring.
    flagged = [(f["ticker"], f["tier"], f["cohort"]) for f in data["flagged"]]
    assert flagged == [("AAA", "Red", "portfolio"), ("FFF", "Yellow", "core")]

    # ETA is set (pending > 0).
    assert data["eta_date"] is not None


def test_gather_live_cohort_fallback(monkeypatch):
    """A watchlist row with no baked cohort falls back to live roster lookup."""
    watchlist = [{"ticker": "XYZ", "filer_type": "domestic"}]  # no 'cohort' key
    monkeypatch.setattr(dashboard, "load_watchlist", lambda: watchlist)
    monkeypatch.setattr(dashboard, "latest_screens", lambda cs: {})
    monkeypatch.setattr(dashboard, "_load_cohort_totals", lambda: None)
    monkeypatch.setattr(dashboard, "_load_history", lambda: [])
    monkeypatch.setattr(cc, "load_rosters", lambda: {
        "portfolio": {"XYZ"}, "researching": set(), "core": set(), "sp500": set()})

    data = dashboard.gather(today="2026-07-13")
    assert data["cohorts"]["portfolio"]["domestic"] == 1


def test_diff_vs_prior(monkeypatch):
    watchlist = [_wl_row("AAA", "core")]
    monkeypatch.setattr(dashboard, "load_watchlist", lambda: watchlist)
    monkeypatch.setattr(dashboard, "latest_screens", lambda cs:
                        {"AAA": {"tier": "Red", "flag_details": "x", "run_date": "2026-07-10"}})
    monkeypatch.setattr(dashboard, "_load_cohort_totals", lambda: {"core": 1})
    monkeypatch.setattr(cc, "load_rosters", lambda: {k: set() for k in
                                                     ("portfolio", "researching", "core", "sp500")})
    monkeypatch.setattr(dashboard, "_load_history", lambda: [
        {"date": "2026-07-12", "screened": 0, "pending": 1, "red": 0, "yellow": 0}])

    data = dashboard.gather(today="2026-07-13")
    assert data["diff"]["screened"] == 1
    assert data["diff"]["red"] == 1


def test_plaintext_renders(monkeypatch):
    monkeypatch.setattr(dashboard, "load_watchlist", lambda: [_wl_row("AAA", "core")])
    monkeypatch.setattr(dashboard, "latest_screens", lambda cs: {})
    monkeypatch.setattr(dashboard, "_load_cohort_totals", lambda: {"core": 1})
    monkeypatch.setattr(dashboard, "_load_history", lambda: [])
    monkeypatch.setattr(cc, "load_rosters", lambda: {k: set() for k in
                                                     ("portfolio", "researching", "core", "sp500")})
    data = dashboard.gather(today="2026-07-13")
    txt = dashboard.to_plaintext(data)
    assert "coverage dashboard" in txt
    assert "Core coverage" in txt
    # build_blocks + html must not raise
    blocks, fallback = dashboard.build_blocks(data)
    assert blocks and fallback
    assert "<table" in dashboard.render_html(data)
