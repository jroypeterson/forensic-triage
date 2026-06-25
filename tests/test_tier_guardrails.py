"""Tests for tier_batch.py — the Anthropic-judge wrapper + deterministic guardrails.

The Anthropic API is NEVER called. Either a mock client is injected, or the judge verdict is
passed directly via tier_one(judge=...). Covers:
  - structured-output validation (malformed rejection, fail-closed)
  - Green-eligibility gate + precedence (via tier_one + finalize_tier)
  - critical-gov / high-severity OVERRIDE a Data Gap
  - idempotency status (fetch_failed vs complete; structural gap = complete)
  - run-level circuit breaker
  - flags_history migration (13-col -> 16-col)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tier_batch  # noqa: E402
from forensic_schema import FAMILIES, HISTORY_COLUMNS  # noqa: E402


def _flags(*fired):
    return {f: (1 if f in fired else 0) for f in FAMILIES}


def _verdict(*fired, critical=False, high=False, corp=None, concerns=None, details=""):
    return {
        "ticker": "ACME",
        "flags": _flags(*fired),
        "critical_governance": critical,
        "high_severity": high,
        "corporate_action": corp,
        "concerns": concerns or [],
        "flag_details": details,
    }


def _record(subgroup="hc_services", *, coverage=None, filer_type="domestic",
            stale=False, source_errors=None):
    cov = {f: "complete" for f in FAMILIES}
    cov["sector"] = "complete" if subgroup != "general" else "not_applicable"
    if coverage:
        cov.update(coverage)
    return {
        "ticker": "ACME",
        "filer_type": filer_type,
        "family_coverage": cov,
        "staleness": {"is_stale": stale, "reason": ("latest 10-K period_end 2023-12-31 is 600d old (> 400)" if stale else "ok")},
        "source_errors": source_errors or [],
    }


# --- structured-output validation ------------------------------------------------------
def test_validate_rejects_non_binary_flag():
    bad = _verdict()
    bad["flags"]["accruals"] = 2
    try:
        tier_batch.validate_judge_output(bad, "ACME")
        assert False, "should have raised"
    except tier_batch.JudgeValidationError:
        pass


def test_validate_rejects_missing_family():
    bad = _verdict()
    del bad["flags"]["leverage"]
    try:
        tier_batch.validate_judge_output(bad, "ACME")
        assert False
    except tier_batch.JudgeValidationError:
        pass


def test_validate_rejects_bad_severity_type():
    bad = _verdict()
    bad["critical_governance"] = "yes"
    try:
        tier_batch.validate_judge_output(bad, "ACME")
        assert False
    except tier_batch.JudgeValidationError:
        pass


def test_validate_accepts_clean():
    ok = tier_batch.validate_judge_output(_verdict("revenue"), "ACME")
    assert ok["flags"]["revenue"] == 1


# --- call_judge fail-closed after retries (mock client returning garbage) --------------
class _GarbageClient:
    class _Msgs:
        def create(self, **kw):
            class R:
                stop_reason = "end_turn"
                content = [type("B", (), {"type": "text", "text": "not json at all"})()]
            return R()
    def __init__(self):
        self.messages = self._Msgs()


def test_call_judge_fails_closed_on_garbage():
    try:
        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=_GarbageClient())
        assert False, "should raise JudgeValidationError, never a silent clean verdict"
    except tier_batch.JudgeValidationError:
        pass


class _RefusalClient:
    class _Msgs:
        def create(self, **kw):
            class R:
                stop_reason = "refusal"
                content = []
            return R()
    def __init__(self):
        self.messages = self._Msgs()


def test_call_judge_treats_refusal_as_failure():
    try:
        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=_RefusalClient())
        assert False
    except tier_batch.JudgeValidationError:
        pass


class _GoodClient:
    """Returns a valid structured object as JSON text."""
    def __init__(self, verdict):
        import json
        self._json = json.dumps(verdict)
        outer = self

        class _Msgs:
            def create(self, **kw):
                class R:
                    stop_reason = "end_turn"
                    content = [type("B", (), {"type": "text", "text": outer._json})()]
                return R()
        self.messages = _Msgs()


def test_call_judge_parses_valid():
    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=_GoodClient(_verdict("revenue")))
    assert out["flags"]["revenue"] == 1


# --- tiering via tier_one (judge injected; no API) ------------------------------------
def test_green_when_clean_and_complete():
    res = tier_batch.tier_one(_record(), subgroup="hc_services", judge=_verdict())
    assert res["tier"] == "Green"
    assert res["status"] == "complete"


def test_two_families_yellow():
    res = tier_batch.tier_one(_record(), subgroup="hc_services",
                              judge=_verdict("revenue", "leverage"))
    assert res["tier"] == "Yellow"


def test_three_families_red():
    res = tier_batch.tier_one(_record(), subgroup="hc_services",
                              judge=_verdict("revenue", "leverage", "sector"))
    assert res["tier"] == "Red"


def test_green_eligibility_gate_blocks_green_on_unavailable():
    rec = _record(coverage={"balance_sheet": "unavailable"}, source_errors=[{"source": "x", "error": "y"}])
    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict())
    assert res["tier"] == "DataGap"  # incomplete coverage + no signal -> NOT Green


def test_critical_gov_overrides_datagap():
    # 4.02 known even though balance_sheet coverage is unavailable -> Red, not DataGap.
    rec = _record(coverage={"balance_sheet": "unavailable"}, source_errors=[{"source": "x", "error": "y"}])
    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict(critical=True))
    assert res["tier"] == "Red"
    assert res["status"] == "complete"  # a known critical signal IS a complete evaluation


def test_high_severity_overrides_datagap_to_yellow():
    rec = _record(coverage={"sector": "unavailable"}, source_errors=[{"source": "x", "error": "y"}])
    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict("revenue", high=True))
    assert res["tier"] == "Yellow"  # signal present, coverage incomplete -> watch


# --- idempotency status ----------------------------------------------------------------
def test_transient_fetch_failure_is_not_complete():
    # domestic, not stale, required family unavailable, source_errors present, NO signal
    rec = _record(coverage={"accruals": "unavailable", "revenue": "unavailable",
                            "balance_sheet": "unavailable", "leverage": "unavailable",
                            "capex": "unavailable", "governance": "unavailable",
                            "sector": "unavailable"},
                  source_errors=[{"source": "rest:ratios", "error": "down"}])
    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict())
    assert res["status"] == "fetch_failed"  # retries next run; does NOT mark done


def test_structural_foreign_gap_is_complete():
    rec = _record(filer_type="foreign",
                  coverage={f: "not_evaluated" for f in FAMILIES})
    res = tier_batch.tier_one(rec, subgroup="medtech", judge=_verdict())
    assert res["status"] == "complete"  # foreign = structural gap = done this cycle


def test_stale_filer_gap_is_complete():
    rec = _record(stale=True,
                  coverage={"accruals": "partial", "revenue": "partial", "capex": "partial",
                            "balance_sheet": "partial", "leverage": "partial"},
                  source_errors=[])
    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict())
    assert res["status"] == "complete"  # genuinely stale = structural = done


def test_fetch_failure_with_critical_signal_is_complete():
    rec = _record(coverage={"balance_sheet": "unavailable"},
                  source_errors=[{"source": "x", "error": "y"}])
    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict(critical=True))
    assert res["status"] == "complete"  # a known signal means we DID evaluate it


# --- run-level circuit breaker ---------------------------------------------------------
def test_circuit_breaker_trips_on_majority_fetch_failed():
    results = [{"status": "fetch_failed"} for _ in range(3)] + [{"status": "complete"}]
    tripped, why = tier_batch.circuit_breaker_tripped(results)
    assert tripped and "fetch_failed" in why


def test_circuit_breaker_quiet_on_healthy_batch():
    results = [{"status": "complete"} for _ in range(5)] + [{"status": "fetch_failed"}]
    tripped, _ = tier_batch.circuit_breaker_tripped(results)
    assert tripped is False


def test_circuit_breaker_ignores_tiny_batch():
    results = [{"status": "fetch_failed"}, {"status": "fetch_failed"}]
    tripped, _ = tier_batch.circuit_breaker_tripped(results)
    assert tripped is False  # below CIRCUIT_BREAKER_MIN_BATCH


# --- history rows + migration ----------------------------------------------------------
def test_history_row_has_new_columns():
    res = tier_batch.tier_one(_record(), subgroup="hc_services", judge=_verdict("revenue"))
    row = tier_batch.result_to_history_row(res, run_id="RUN42", run_date="2026-06-24")
    assert set(row.keys()) == set(HISTORY_COLUMNS)
    assert row["run_id"] == "RUN42"
    assert row["status"] == "complete"
    assert str(row["schema_version"]) != ""
    assert row["revenue_flag"] == 1


def test_append_migrates_old_13col_history(tmp_path):
    old = tmp_path / "flags_history.csv"
    old_cols = ["run_date", "ticker", "tier", "accruals_flag", "revenue_flag", "capex_flag",
                "balance_sheet_flag", "leverage_flag", "governance_flag", "market_flag",
                "text_flag", "sector_flag", "flag_details"]
    with old.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_cols)
        w.writeheader()
        w.writerow({c: "" for c in old_cols} | {"run_date": "2026-04-17", "ticker": "AAPL", "tier": "Green"})

    res = tier_batch.tier_one(_record(), subgroup="hc_services", judge=_verdict())
    new_row = tier_batch.result_to_history_row(res, run_id="RUN1", run_date="2026-06-24")
    tier_batch.append_history([new_row], path=old)

    with old.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == HISTORY_COLUMNS
        rows = list(reader)
    # legacy row preserved + defaulted, new row appended
    assert rows[0]["ticker"] == "AAPL" and rows[0]["status"] == "complete"
    assert rows[-1]["ticker"] == "ACME" and rows[-1]["run_id"] == "RUN1"
