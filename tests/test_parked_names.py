"""#677: case-variant tickers count as done, and a confirmed no-10-K registrant stops retrying."""
from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensic_triage import dashboard, edgar_fetch, next_batch, run_unattended, tier_batch  # noqa: E402
from forensic_triage.forensic_schema import (  # noqa: E402
    FAMILIES,
    NO_10K_FOUND,
    STATUS_PARKED_NO_10K,
    TEN_K_LOOKUP_FAILED,
)

UNAVAILABLE = {f: "unavailable" for f in FAMILIES}
ERRORS = [{"source": "rest:statements", "error": "404"}]
VERDICT = {
    "ticker": "ACME",
    "flags": {f: 0 for f in FAMILIES},
    "critical_governance": False,
    "high_severity": False,
    "corporate_action": None,
    "concerns": [],
    "flag_details": "",
}


class _Company:
    """get_filings answers per form: a list of filings, or an exception to raise."""

    def __init__(self, ten_k):
        self.ten_k = ten_k

    def get_filings(self, form=None):
        if form != "10-K":
            return []
        if isinstance(self.ten_k, Exception):
            raise self.ten_k
        return self.ten_k


class _UndatedFiling:
    accession_no = "x"
    filing_date = ""
    period_of_report = ""
    fiscal_year = ""


class _Filings(list):
    def latest(self):
        return self[0]


def _staleness(company) -> dict:
    rec: dict = {}
    edgar_fetch._populate_filings(rec, company)
    return rec["staleness"]


def _status_for(company) -> str:
    record = {
        "ticker": "ACME",
        "filer_type": "domestic",
        "family_coverage": UNAVAILABLE,
        "staleness": _staleness(company),
        "source_errors": ERRORS,
    }
    return tier_batch.tier_one(record, subgroup="general", judge=VERDICT)["status"]


def test_an_empty_answer_is_a_confirmed_no_10k():
    assert _staleness(_Company([])) == {"is_stale": True, "reason": NO_10K_FOUND}


def test_a_failed_lookup_is_not_reported_as_no_10k():
    assert _staleness(_Company(ConnectionError("SEC 429")))["reason"] != NO_10K_FOUND


def test_a_10k_with_no_readable_date_is_not_reported_as_no_10k():
    assert _staleness(_Company(_Filings([_UndatedFiling()])))["reason"] != NO_10K_FOUND


def test_a_confirmed_no_10k_registrant_is_parked():
    assert _status_for(_Company([])) == STATUS_PARKED_NO_10K


class _NotFoundCompany(_Company):
    """edgartools' placeholder when SEC 404s a CIK: empty filings, and no exception."""

    not_found = True


def test_edgartools_not_found_placeholder_is_not_a_confirmed_no_10k():
    assert _staleness(_NotFoundCompany([]))["reason"] == TEN_K_LOOKUP_FAILED
    assert _status_for(_NotFoundCompany([])) == "fetch_failed"


PARTIAL = {f: "partial" for f in FAMILIES}


@pytest.mark.parametrize("errors", [[], ERRORS])
@pytest.mark.parametrize("coverage", [PARTIAL, UNAVAILABLE])
def test_a_failed_10k_lookup_retries_whatever_coverage_looks_like(coverage, errors):
    record = {
        "ticker": "ACME",
        "filer_type": "domestic",
        "family_coverage": coverage,
        "staleness": {"is_stale": True, "reason": TEN_K_LOOKUP_FAILED},
        "source_errors": errors,
    }
    assert tier_batch.tier_one(record, subgroup="general", judge=VERDICT)["status"] == "fetch_failed"


def test_a_new_no_10k_name_is_a_data_gap_not_a_screened_yellow():
    record = {
        "ticker": "ACME",
        "filer_type": "domestic",
        "family_coverage": UNAVAILABLE,
        "staleness": _staleness(_Company([])),
        "source_errors": ERRORS,
    }
    assert tier_batch.tier_one(record, subgroup="general", judge=VERDICT, is_new=True)["tier"] == "DataGap"


def test_a_critical_signal_on_a_no_10k_name_closes_the_evaluation():
    record = {
        "ticker": "ACME",
        "filer_type": "domestic",
        "family_coverage": UNAVAILABLE,
        "staleness": _staleness(_Company([])),
        "source_errors": ERRORS,
    }
    res = tier_batch.tier_one(record, subgroup="general", judge={**VERDICT, "critical_governance": True})
    assert (res["tier"], res["status"]) == ("Red", "complete")


def _history(path, *rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_date", "ticker", "status"])
        writer.writerows(rows)


@pytest.mark.parametrize(
    "run_date, is_done",
    [("2026-11-09", True), ("2026-10-10", True), ("2026-10-09", False)],
)
def test_a_parked_name_is_done_only_for_the_recheck_window(tmp_path, monkeypatch, run_date, is_done):
    history = tmp_path / "flags_history.csv"
    _history(history, [run_date, "ALMR", STATUS_PARKED_NO_10K])
    monkeypatch.setattr(next_batch, "FLAGS_HISTORY_CSV", history)
    done = next_batch.screened_since("2026-06-20", today=date(2026, 11, 9))
    assert ("ALMR" in done) is is_done


def test_a_complete_screen_stays_done_past_the_recheck_window(tmp_path, monkeypatch):
    history = tmp_path / "flags_history.csv"
    _history(history, ["2026-07-01", "ACME", "complete"])
    monkeypatch.setattr(next_batch, "FLAGS_HISTORY_CSV", history)
    assert "ACME" in next_batch.screened_since("2026-06-20", today=date(2026, 11, 9))


@pytest.mark.parametrize(
    "rows, is_done",
    [
        ([["2026-07-01", "ACME", "complete"], ["2026-09-01", "ACME", STATUS_PARKED_NO_10K]], False),
        ([["2026-07-01", "ACME", "complete"], ["2026-11-01", "ACME", STATUS_PARKED_NO_10K]], True),
        ([["2026-09-01", "ACME", STATUS_PARKED_NO_10K], ["2026-10-01", "ACME", "complete"]], True),
        ([["2026-07-01", "ACME", "complete"], ["2026-10-01", "ACME", "fetch_failed"]], True),
        ([["2026-09-01", "ACME", STATUS_PARKED_NO_10K], ["2026-11-01", "ACME", "fetch_failed"]], False),
    ],
)
def test_the_newest_real_outcome_decides_whether_a_name_is_done(tmp_path, monkeypatch, rows, is_done):
    history = tmp_path / "flags_history.csv"
    _history(history, *rows)
    monkeypatch.setattr(next_batch, "FLAGS_HISTORY_CSV", history)
    assert ("ACME" in next_batch.screened_since("2026-06-20", today=date(2026, 11, 9))) is is_done


@pytest.mark.parametrize("today, pending", [("2026-11-09", 1), ("2026-12-15", 2)])
def test_the_dashboard_counts_a_parked_name_as_neither_screened_nor_pending(tmp_path, monkeypatch, today, pending):
    history = tmp_path / "flags_history.csv"
    with history.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_date", "ticker", "tier", "flag_details", "status"])
        writer.writerow(["2026-11-05", "ACME", "DataGap", "", STATUS_PARKED_NO_10K])
    monkeypatch.setattr(dashboard, "FLAGS_HISTORY_CSV", history)
    monkeypatch.setattr(
        dashboard,
        "load_watchlist",
        lambda: [
            {"ticker": "ACME", "cohort": "core", "filer_type": "domestic"},
            {"ticker": "WXYZ", "cohort": "core", "filer_type": "domestic"},
        ],
    )
    monkeypatch.setattr(dashboard, "_load_cohort_totals", lambda: {"core": 2})
    monkeypatch.setattr(dashboard, "_load_history", lambda: [])
    monkeypatch.setattr(dashboard.cc, "load_rosters", lambda: {})
    core = dashboard.gather(cycle_start="2026-06-20", per_day=6, today=today)["cohorts"]["core"]
    assert (core["screened"], core["pending"]) == (0, pending)


def test_the_heartbeat_does_not_count_a_parked_or_failed_name_as_screened():
    results = [{"status": "complete"}, {"status": STATUS_PARKED_NO_10K}, {"status": "judge_failed"}]
    assert run_unattended._n_screened(results) == 1


def test_a_parked_result_reaches_the_picker_through_the_real_history_row(tmp_path, monkeypatch):
    record = {
        "ticker": "ACME",
        "filer_type": "domestic",
        "family_coverage": UNAVAILABLE,
        "staleness": _staleness(_Company([])),
        "source_errors": ERRORS,
    }
    row = tier_batch.result_to_history_row(
        tier_batch.tier_one(record, subgroup="general", judge=VERDICT), run_id="r"
    )
    history = tmp_path / "flags_history.csv"
    with history.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    monkeypatch.setattr(next_batch, "FLAGS_HISTORY_CSV", history)
    run_day = date.fromisoformat(row["run_date"])
    assert "ACME" in next_batch.screened_since("2026-06-20", today=run_day)
    assert "ACME" not in next_batch.screened_since("2026-06-20", today=run_day + timedelta(days=31))


def test_an_edgar_outage_keeps_retrying():
    assert _status_for(_Company(ConnectionError("SEC 429"))) == "fetch_failed"


def test_an_undated_10k_keeps_retrying():
    assert _status_for(_Company(_Filings([_UndatedFiling()]))) == "fetch_failed"


def test_a_parked_name_is_not_green():
    record = {
        "ticker": "ACME",
        "filer_type": "domestic",
        "family_coverage": UNAVAILABLE,
        "staleness": _staleness(_Company([])),
        "source_errors": ERRORS,
    }
    assert tier_batch.tier_one(record, subgroup="general", judge=VERDICT)["tier"] == "DataGap"


@pytest.fixture
def mixed_case_store(tmp_path, monkeypatch):
    history = tmp_path / "flags_history.csv"
    with history.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_date", "ticker", "status"])
        writer.writerow(["2026-10-01", "VCEL", "complete"])
        writer.writerow(["2026-10-01", "abcd", "complete"])
    monkeypatch.setattr(next_batch, "FLAGS_HISTORY_CSV", history)
    monkeypatch.setattr(next_batch.cc, "load_rosters", lambda: {})
    monkeypatch.setattr(
        next_batch,
        "load_watchlist",
        lambda: [
            {"ticker": "VCEl", "filer_type": "domestic", "cohort": "core", "sector_subgroup": "medtech"},
            {"ticker": "ABCD", "filer_type": "domestic", "cohort": "core", "sector_subgroup": "medtech"},
            {"ticker": "WXYZ", "filer_type": "domestic", "cohort": "core", "sector_subgroup": "medtech"},
        ],
    )


def test_the_unattended_picker_treats_a_case_variant_as_done(mixed_case_store):
    assert run_unattended._pick_batch(5, "2026-06-20") == ["WXYZ"]


def test_the_interactive_picker_treats_a_case_variant_as_done(mixed_case_store, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["next_batch"])
    assert next_batch.main() == 0
    out = capsys.readouterr().out
    assert "screened this cycle: 2/3" in out
    assert "VCEl" not in out


def test_the_committed_watchlist_has_only_upper_case_tickers():
    with next_batch.WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
        offenders = [r["ticker"] for r in csv.DictReader(f) if r["ticker"] != r["ticker"].upper()]
    assert offenders == []
