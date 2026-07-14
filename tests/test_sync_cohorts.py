"""Regression tests for the S&P 500 sync + cohort wiring (Codex round-1 findings)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import coverage_cohorts as cc  # noqa: E402
import next_batch as nb  # noqa: E402
import sync_watchlist as sw  # noqa: E402


def test_ckey_folds_class_punctuation():
    # BRK.B / BRK-B are the same security across sources; GOOG vs GOOGL are not.
    assert sw.ckey("BRK.B") == "BRK-B"
    assert sw.ckey("brk.b") == "BRK-B"
    assert sw.ckey("GOOGL") == "GOOGL"
    assert sw.ckey("GOOG") != sw.ckey("GOOGL")


def test_sort_key_defensive_without_rosters():
    # Codex Critical: run_unattended called sort_key() with no rosters -> TypeError.
    # sort_key must be callable without rosters (uses the baked cohort column).
    k = nb.sort_key({"ticker": "AAA", "cohort": "portfolio"})
    assert k[0] == cc.COHORT_RANK["portfolio"]
    k2 = nb.sort_key({"ticker": "ZZZ", "cohort": "sp500"})
    assert k2[0] == cc.COHORT_RANK["sp500"]
    assert k < k2  # portfolio sorts before sp500


def test_sp500_extras_preserves_cik_on_sec_failure(monkeypatch):
    # Codex High: a transient SEC-map outage must NOT drop an existing S&P row
    # (which would then be reported "removed" and written out of the watchlist).
    monkeypatch.setattr(cc, "load_rosters", lambda: {
        "portfolio": set(), "researching": set(), "core": set(), "sp500": {"ABNB"}})
    monkeypatch.setattr(sw, "load_sec_ticker_ciks", lambda: {})  # SEC map unavailable
    existing = {"ABNB": {"cik": "0001559720", "added_date": "2026-01-01",
                         "company_name": "Airbnb"}}
    rows, added, unresolved = sw.build_sp500_extras(
        existing, cm_master=set(), already_added=set(), today="2026-07-13")
    assert unresolved == []                       # NOT dropped
    assert len(rows) == 1 and rows[0]["cik"] == "0001559720"


def test_sp500_extras_dedup_class_ticker(monkeypatch):
    # Codex High: CM carrying BRK-B must suppress re-adding sigma's BRK.B spelling.
    monkeypatch.setattr(cc, "load_rosters", lambda: {
        "portfolio": set(), "researching": set(), "core": set(), "sp500": {"BRK.B"}})
    monkeypatch.setattr(sw, "load_sec_ticker_ciks", lambda: {"BRK-B": "0001067983"})
    rows, added, unresolved = sw.build_sp500_extras(
        {}, cm_master={"BRK-B"}, already_added=set(), today="2026-07-13")
    assert rows == [] and added == []             # no duplicate row


def test_sp500_extras_new_name_without_cik_is_skipped(monkeypatch):
    # A brand-new S&P name with no prev row and no SEC CIK is skipped loudly (can't screen).
    monkeypatch.setattr(cc, "load_rosters", lambda: {
        "portfolio": set(), "researching": set(), "core": set(), "sp500": {"NEWCO"}})
    monkeypatch.setattr(sw, "load_sec_ticker_ciks", lambda: {})
    rows, added, unresolved = sw.build_sp500_extras(
        {}, cm_master=set(), already_added=set(), today="2026-07-13")
    assert rows == [] and unresolved == ["NEWCO"]
