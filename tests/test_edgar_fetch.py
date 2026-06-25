"""Tests for edgar_fetch.py — the false-Green guard's data layer.

All EDGAR access is MOCKED. No live SEC / Anthropic calls. Covers:
  - hard schema validity (every key present)
  - staleness via filing DATES (not fy-age)
  - not_disclosed vs fetch_failed distinction
  - REST-down -> edgartools degradation (an outage can't hide a 4.02)
  - never-raises contract
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edgar_fetch  # noqa: E402
from forensic_schema import COVERAGE, FAMILIES  # noqa: E402


# --- fakes -----------------------------------------------------------------------------
class _BoomRest:
    """A REST client where everything raises (paid REST down)."""
    def __init__(self):
        self.api_key = "x"
        self.identity = "id"

    def ratios(self, cik): raise RuntimeError("rest down")
    def income_statement(self, cik): raise RuntimeError("rest down")
    def balance_sheet(self, cik): raise RuntimeError("rest down")
    def cash_flow(self, cik): raise RuntimeError("rest down")
    def metrics(self, cik): raise RuntimeError("rest down")
    def material_events(self, cik): raise RuntimeError("rest down")


class _OkRest:
    """A REST client returning minimal usable payloads + a 4.02 in the 8-K feed."""
    def __init__(self):
        self.api_key = "x"
        self.identity = "id"

    def ratios(self, cik): return {"net_debt_ebitda": 2.1, "current_ratio": 1.5}
    def income_statement(self, cik):
        return {"data": [{"period": "2025", "revenue": 100, "net_income": 10}]}
    def balance_sheet(self, cik):
        return {"data": [{"period": "2025", "total_assets": 500, "inventory": 50, "goodwill": 80}]}
    def cash_flow(self, cik):
        return {"data": [{"period": "2025", "cfo": 12, "capex": 8}]}
    def metrics(self, cik): return {"data": []}
    def material_events(self, cik):
        return {"data": [{"date": "2026-05-01", "items": "4.02", "body": "non-reliance"}]}


def _schema_keys_present(rec: dict) -> None:
    for key in ("schema_version", "ticker", "cik", "run_id", "fetched_at", "filer_type",
                "latest_10k", "latest_10q", "staleness", "ratios", "statements", "notes",
                "events_8k", "corporate_action", "insider", "family_coverage",
                "required_families_complete", "source_errors"):
        assert key in rec, f"missing key {key}"
    assert set(rec["family_coverage"].keys()) == set(FAMILIES)
    for fam, cov in rec["family_coverage"].items():
        assert cov in COVERAGE, f"{fam}={cov} not a valid coverage enum"
    for topic, body in rec["notes"].items():
        assert body["status"] in ("present", "not_disclosed", "fetch_failed")
    json.dumps(rec, default=str)  # must be JSON-serializable


# --- foreign filer -> structural Data Gap, no EDGAR calls ------------------------------
def test_foreign_filer_is_structural_gap():
    rec = edgar_fetch.fetch_ticker("ADYEY", "", subgroup="medtech", filer_type="foreign",
                                   run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    assert rec["filer_type"] == "foreign"
    assert rec["staleness"]["is_stale"] is True
    assert rec["required_families_complete"] is False  # never green-eligible


# --- never raises, even with everything broken ----------------------------------------
def test_never_raises_with_total_failure(monkeypatch):
    # REST down AND edgartools import/use raising.
    def _boom_company(cik, identity):
        raise RuntimeError("edgartools exploded")
    monkeypatch.setattr(edgar_fetch, "_edgar_company", _boom_company)

    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    # Everything failed -> required families unavailable -> NOT green-eligible.
    assert rec["required_families_complete"] is False
    assert len(rec["source_errors"]) > 0
    # financial families should be unavailable (fetch failure)
    assert rec["family_coverage"]["accruals"] == "unavailable"


# --- not_disclosed vs fetch_failed -----------------------------------------------------
class _FakeFiling:
    def __init__(self, text, *, filing_date="2026-03-01", period_end="2025-12-31"):
        self._text = text
        self.filing_date = filing_date
        self.period_of_report = period_end
        self.accession_no = "0000-25-000001"

    def text(self):
        return self._text


class _FakeFilings:
    def __init__(self, filing):
        self._filing = filing

    def latest(self):
        return self._filing

    def __bool__(self):
        return self._filing is not None

    def __len__(self):
        return 1 if self._filing else 0

    def head(self, n):
        return [self._filing] if self._filing else []

    def __getitem__(self, i):
        return self._filing


class _FakeCompany:
    def __init__(self, tenk_text=None, has_10k=True):
        self._tenk = _FakeFiling(tenk_text) if has_10k else None

    def get_filings(self, form=None):
        if form == "10-K":
            return _FakeFilings(self._tenk)
        return _FakeFilings(None)

    @property
    def financials(self):
        return object()


def test_note_present_vs_not_disclosed(monkeypatch):
    # 10-K body mentions inventory + goodwill but NOT 'debt' -> Inventory/Goodwill present,
    # Debt not_disclosed (a legitimate absence, NOT a fetch failure).
    body = "Note 3. Inventory consists of consigned field inventory. Note 5. Goodwill of $80M."
    monkeypatch.setattr(edgar_fetch, "_edgar_company",
                        lambda cik, identity: _FakeCompany(tenk_text=body))
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="medtech",
                                   filer_type="domestic", run_id="t", rest=_OkRest())
    _schema_keys_present(rec)
    assert rec["notes"]["Inventory"]["status"] == "present"
    assert rec["notes"]["Goodwill"]["status"] == "present"
    assert rec["notes"]["Debt"]["status"] == "not_disclosed"  # absent, not failed


def test_note_fetch_failed_when_body_unreadable(monkeypatch):
    # 10-K handle exists but body is empty -> every note is fetch_failed (a real failure).
    monkeypatch.setattr(edgar_fetch, "_edgar_company",
                        lambda cik, identity: _FakeCompany(tenk_text=""))
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="medtech",
                                   filer_type="domestic", run_id="t", rest=_OkRest())
    for topic in edgar_fetch.NOTE_TOPICS:
        assert rec["notes"][topic]["status"] == "fetch_failed"


# --- staleness via dates ---------------------------------------------------------------
def test_staleness_uses_filing_dates_not_fy_age(monkeypatch):
    old = _FakeFiling("Inventory note.", filing_date="2024-02-01", period_end="2023-12-31")

    class _OldCompany(_FakeCompany):
        def get_filings(self, form=None):
            if form == "10-K":
                return _FakeFilings(old)
            return _FakeFilings(None)

    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _OldCompany())
    rec = edgar_fetch.fetch_ticker("OLD", "0000000002", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_OkRest())
    assert rec["staleness"]["is_stale"] is True
    assert "2023-12-31" in rec["staleness"]["reason"]


def test_recent_filing_not_stale(monkeypatch):
    monkeypatch.setattr(edgar_fetch, "_edgar_company",
                        lambda cik, identity: _FakeCompany(tenk_text="Inventory note. Goodwill. Debt covenants."))
    rec = edgar_fetch.fetch_ticker("NEW", "0000000003", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_OkRest())
    assert rec["staleness"]["is_stale"] is False


# --- REST-down degradation can't hide a 4.02 ------------------------------------------
def test_rest_down_still_captures_8k_via_edgartools(monkeypatch):
    # REST is down; edgartools must supply the 8-K feed so a 4.02 isn't hidden.
    class _Co8K(_FakeCompany):
        def get_filings(self, form=None):
            if form == "10-K":
                return _FakeFilings(_FakeFiling("Inventory. Goodwill. Debt."))
            if form == "8-K":
                f = _FakeFiling("non-reliance", filing_date="2026-05-01")
                f.items = "4.02"
                return _FakeFilings(f)
            return _FakeFilings(None)

    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _Co8K())
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    items = [i for ev in rec["events_8k"] for i in ev.get("items", [])]
    assert "4.02" in items, "REST-down must not drop the 8-K governance feed"
    # governance family is therefore evaluable (the feed was fetched).
    assert rec["family_coverage"]["governance"] == "complete"


def test_no_cik_domestic_writes_fetch_failed(tmp_path, monkeypatch):
    # A domestic name with no CIK can't be fetched -> fetch_failed record, never a crash.
    monkeypatch.setattr(edgar_fetch, "WATCHLIST_CSV", tmp_path / "nope.csv")
    rc = edgar_fetch.main(["NOCIK", "--out", str(tmp_path), "--filer-type", "domestic"])
    assert rc == 0
    rec = json.loads((tmp_path / "NOCIK.json").read_text())
    assert rec["required_families_complete"] is False
    assert any(e["source"] == "watchlist" for e in rec["source_errors"])


# --- codex P1 regressions: false-Green guards -----------------------------------------
class _RatiosOnlyRest:
    """REST where ONLY /ratios works; every statement endpoint fails (the codex P1 case)."""
    def __init__(self):
        self.api_key = "x"
        self.identity = "id"

    def ratios(self, cik): return {"net_debt_ebitda": 2.0}
    def income_statement(self, cik): raise RuntimeError("stmt down")
    def balance_sheet(self, cik): raise RuntimeError("stmt down")
    def cash_flow(self, cik): raise RuntimeError("stmt down")
    def metrics(self, cik): return {"data": []}
    def material_events(self, cik): return {"data": []}


def test_ratios_only_does_not_make_financial_complete(monkeypatch):
    # /ratios succeeds but all statement endpoints fail and there is NO edgartools fallback.
    # Financial families must stay `unavailable` (ratios alone != evaluable) -> not Green-eligible.
    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: None)
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_RatiosOnlyRest())
    assert rec["ratios"] is not None            # ratios DID come back
    assert rec["statements"]["annual"] == []    # but no statement line items
    assert rec["family_coverage"]["accruals"] == "unavailable"
    assert rec["required_families_complete"] is False


def test_8k_fetch_failure_blocks_governance(monkeypatch):
    # REST down; the 10-K reads but the edgartools 8-K fetch RAISES -> governance must be
    # `unavailable` (a swallowed [] would wrongly mark it complete and could hide a 4.02).
    class _Co8KBoom(_FakeCompany):
        def get_filings(self, form=None):
            if form == "10-K":
                return _FakeFilings(_FakeFiling("Inventory. Goodwill. Debt covenants."))
            if form == "8-K":
                raise RuntimeError("8-K fetch failed")
            return _FakeFilings(None)

    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _Co8KBoom())
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    assert rec["family_coverage"]["governance"] == "unavailable"
    assert rec["required_families_complete"] is False
