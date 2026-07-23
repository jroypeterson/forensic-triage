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

from forensic_triage import edgar_fetch  # noqa: E402
from forensic_triage.forensic_schema import COVERAGE, FAMILIES  # noqa: E402


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


def test_normalize_statements_v1_rows_shape():
    """The /v1 API returns statements as rows x periods with XBRL concepts; the
    normalizer must pivot them into per-period line-item buckets (regression for the
    2026-07 CI failures after the API moved under /v1)."""
    income = {"statements": {"income_statement": {"rows": [
        {"concept": "Revenues", "standard_concept": "Revenue",
         "values": {"2025-12-31": 100, "2024-12-31": 90}, "is_abstract": False},
        {"concept": "NetIncomeLoss", "standard_concept": "Net Income",
         "values": {"2025-12-31": 10, "2024-12-31": 9}, "is_abstract": False},
        {"concept": "SomethingAbstract", "standard_concept": "Revenue",
         "values": {"2025-12-31": 999}, "is_abstract": True},
    ]}}}
    balance = {"statements": {"balance_sheet": {"rows": [
        {"concept": "Assets", "standard_concept": "Total Assets",
         "values": {"2025-12-31": 500}, "is_abstract": False},
        {"concept": "InventoryNet", "standard_concept": None,
         "values": {"2025-12-31": 50}, "is_abstract": False},
    ]}}}
    cashflow = {"statements": {"cash_flow": {"rows": [
        {"concept": "NetCashProvidedByUsedInOperatingActivities", "standard_concept": None,
         "values": {"2025-12-31": 12}, "is_abstract": False},
        {"concept": "PaymentsToAcquirePropertyPlantAndEquipment", "standard_concept": None,
         "values": {"2025-12-31": 4}, "is_abstract": False},
    ]}}}
    out = edgar_fetch._normalize_statements(income, balance, cashflow)
    assert len(out) == 2  # two periods, newest first
    latest = out[0]
    assert latest["period"] == "2025-12-31"
    assert latest["revenue"] == 100          # abstract row must NOT have overwritten this
    assert latest["net_income"] == 10
    assert latest["total_assets"] == 500
    assert latest["inventory"] == 50
    assert latest["cfo"] == 12
    assert latest["capex"] == 4
    assert out[1]["revenue"] == 90


def test_normalize_statements_legacy_flat_shape_still_works():
    income = {"data": [{"period": "2025", "revenue": 100, "net_income": 10}]}
    out = edgar_fetch._normalize_statements(income, None, None)
    assert out and out[0]["revenue"] == 100


def test_income_only_fetch_cannot_complete_cashflow_and_balance_families():
    """codex 2026-07-08: income succeeding while balance/cash-flow FAIL must not
    mark accruals/capex/balance_sheet/leverage complete (false-Green vector)."""
    rec = edgar_fetch._empty_record("TST", "0000000001", "t")
    rec["statements"]["annual"] = [{"period": "2025-12-31", "revenue": 100}]
    rec["_stmt_ok"] = {"income": True, "balance": False, "cashflow": False}
    rec["_events_8k_fetched"] = True
    for topic in edgar_fetch.NOTE_TOPICS:
        rec["notes"][topic] = {"status": "present", "text": "x"}
    rec["staleness"] = {"is_stale": False, "reason": "fresh"}
    cov = edgar_fetch._classify_coverage(rec, "general")
    assert cov["accruals"] == "partial"       # no cash-flow -> no CFO
    assert cov["capex"] == "partial"          # no cash-flow
    assert cov["balance_sheet"] == "partial"  # no balance sheet
    assert cov["leverage"] == "partial"       # no balance sheet
    assert cov["revenue"] == "complete"       # income DID come back


def test_all_statements_ok_still_completes_families():
    rec = edgar_fetch._empty_record("TST", "0000000001", "t")
    rec["statements"]["annual"] = [{"period": "2025-12-31", "revenue": 100, "cfo": 5}]
    rec["_stmt_ok"] = {"income": True, "balance": True, "cashflow": True}
    rec["_events_8k_fetched"] = True
    for topic in edgar_fetch.NOTE_TOPICS:
        rec["notes"][topic] = {"status": "present", "text": "x"}
    rec["staleness"] = {"is_stale": False, "reason": "fresh"}
    cov = edgar_fetch._classify_coverage(rec, "general")
    assert cov["accruals"] == "complete"
    assert cov["capex"] == "complete"
    assert cov["balance_sheet"] == "complete"
    assert cov["leverage"] == "complete"


class _EmptyEventsRest:
    """REST where statements work but material-events returns a junk {} (HTTP 200, no container)."""
    def __init__(self):
        self.api_key = "x"
        self.identity = "id"

    def ratios(self, cik): return {"net_debt_ebitda": 2.0}
    def income_statement(self, cik):
        return {"data": [{"period": "2025", "revenue": 100, "net_income": 10}]}
    def balance_sheet(self, cik):
        return {"data": [{"period": "2025", "total_assets": 500, "inventory": 50, "goodwill": 80}]}
    def cash_flow(self, cik):
        return {"data": [{"period": "2025", "cfo": 12, "capex": 8}]}
    def metrics(self, cik): return {"data": []}
    def material_events(self, cik): return {}   # junk empty payload (no data/events container)


def test_empty_rest_events_falls_back_to_edgartools(monkeypatch):
    # REST material-events returns {} (no container) -> must NOT mark governance complete on
    # zero events; the edgartools fallback supplies the real 8-K (a 4.02) so it isn't hidden
    # (codex 2026-07-17: parallels the _stmt_ok_from {} guard for statements).
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
                                   filer_type="domestic", run_id="t", rest=_EmptyEventsRest())
    _schema_keys_present(rec)
    items = [i for ev in rec["events_8k"] for i in ev.get("items", [])]
    assert "4.02" in items, "empty {} REST events must fall back to edgartools, not hide the 4.02"
    assert rec["family_coverage"]["governance"] == "complete"


def test_empty_rest_events_without_fallback_blocks_governance(monkeypatch):
    # REST events {} and NO edgartools 8-K available -> governance must be `unavailable`,
    # not falsely `complete` on a junk empty payload.
    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: None)
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_EmptyEventsRest())
    assert rec["family_coverage"]["governance"] == "unavailable"


def test_events_payload_ok_distinguishes_junk_from_empty():
    # A well-formed 'genuinely no 8-Ks' response keeps its container key and IS accepted;
    # a bare {} (no container) is rejected so it can't mark governance complete on nothing.
    assert edgar_fetch._events_payload_ok({"data": []}) is True
    assert edgar_fetch._events_payload_ok({"events": []}) is True
    assert edgar_fetch._events_payload_ok([]) is True
    assert edgar_fetch._events_payload_ok({}) is False
    assert edgar_fetch._events_payload_ok(None) is False


def test_stmt_ok_requires_mapped_line_items_not_just_http_200():
    """codex R2 2026-07-08: an empty {} response (HTTP 200, no rows) must not
    count as statement coverage."""
    annual = [{"period": "2025-12-31", "revenue": 100, "net_income": 10}]
    ok = edgar_fetch._stmt_ok_from(annual, income={}, balance={}, cashflow={})
    assert ok["income"] is True        # income keys actually mapped
    assert ok["balance"] is False      # endpoint answered but nothing mapped
    assert ok["cashflow"] is False
    # endpoint failed outright -> False regardless of keys
    ok2 = edgar_fetch._stmt_ok_from(annual, income=None, balance={}, cashflow={})
    assert ok2["income"] is False


# --- codex 2026-07-17 F1: NT 10-K/10-Q late filings must be fetched + surfaced --------
class _NTFiling:
    def __init__(self, filing_date="2026-06-01", period_end="2026-03-31",
                 accession="0000000001-26-000009"):
        self.filing_date = filing_date
        self.period_of_report = period_end
        self.accession_no = accession


class _CompanyWithNT(_FakeCompany):
    def get_filings(self, form=None):
        if form == "10-K":
            return _FakeFilings(_FakeFiling("Inventory. Goodwill. Debt covenants."))
        if form == "NT 10-K":
            return _FakeFilings(_NTFiling())
        return _FakeFilings(None)


def test_nt_late_filing_is_fetched_and_surfaced(monkeypatch):
    # A recent NT 10-K is a CRITICAL-governance auto-Red (general.md §6a). NT forms are not
    # 8-Ks, so they were never fetched (NT_FORMS was dead code) and late filers tiered Green.
    # The fetch must now surface the NT so the per-family judge can fire critical_governance.
    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _CompanyWithNT())
    rec = edgar_fetch.fetch_ticker("LATE", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_OkRest())
    _schema_keys_present(rec)
    assert isinstance(rec["late_filings"], list)
    forms = [lf["form"] for lf in rec["late_filings"]]
    assert "NT 10-K" in forms, "a recent NT 10-K must be surfaced (auto-Red signal)"
    nt = next(lf for lf in rec["late_filings"] if lf["form"] == "NT 10-K")
    assert nt["filing_date"] == "2026-06-01"
    assert nt["accession"] == "0000000001-26-000009"


def test_no_nt_filing_leaves_late_filings_empty(monkeypatch):
    monkeypatch.setattr(edgar_fetch, "_edgar_company",
                        lambda cik, identity: _FakeCompany(tenk_text="Inventory. Goodwill. Debt."))
    rec = edgar_fetch.fetch_ticker("CLEAN", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_OkRest())
    assert rec["late_filings"] == []  # no NT -> no false late-filing signal


# --- codex 2026-07-17 F3: statements fallback must not mark complete off a placeholder --
def test_stmt_ok_from_periods_derives_from_line_item_keys():
    real = [{"period": "FY-0", "revenue": 100, "net_income": 10, "cfo": 5,
             "capex": 3, "total_assets": 500}]
    assert edgar_fetch._stmt_ok_from_periods(real) == {
        "income": True, "balance": True, "cashflow": True}
    placeholder = [{"period": "latest", "source": "edgartools_financials"}]
    assert edgar_fetch._stmt_ok_from_periods(placeholder) == {
        "income": False, "balance": False, "cashflow": False}


def test_statements_fallback_placeholder_marks_partial_not_complete(monkeypatch):
    # REST down; edgartools Financials object loads but exposes NO usable line items (the
    # base _FakeCompany.financials is a bare object()). The fallback must mark the financial
    # families `partial`, NEVER `complete` on a contentless placeholder (false-Green when REST
    # is down; codex 2026-07-17 F3). Before the fix the caller hardcoded _stmt_ok all-True.
    monkeypatch.setattr(edgar_fetch, "_edgar_company",
                        lambda cik, identity: _FakeCompany(tenk_text="Inventory. Goodwill. Debt covenants."))
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    assert rec["statements"]["annual"]  # a placeholder IS present...
    for fam in ("accruals", "revenue", "capex", "balance_sheet", "leverage"):
        assert rec["family_coverage"][fam] == "partial", f"{fam} must be partial, not complete"
    assert rec["required_families_complete"] is False


class _FakeFinancials:
    """A minimal edgartools-Financials stand-in exposing the getter API we extract from."""
    def get_revenue(self, offset=0): return [100, 90, 80][offset]
    def get_net_income(self, offset=0): return [10, 9, 8][offset]
    def get_operating_cash_flow(self, offset=0): return [12, 11, 10][offset]
    def get_capital_expenditures(self, offset=0): return [4, 4, 3][offset]
    def get_total_assets(self, offset=0): return [500, 480, 460][offset]


class _CoWithFinancials(_FakeCompany):
    def get_filings(self, form=None):
        if form == "10-K":
            return _FakeFilings(_FakeFiling("Inventory. Goodwill. Debt covenants."))
        if form == "8-K":
            f = _FakeFiling("routine", filing_date="2026-05-01")
            f.items = ""  # no governance item
            return _FakeFilings(f)
        return _FakeFilings(None)

    def get_financials(self):
        return _FakeFinancials()


def test_statements_fallback_extracts_real_line_items(monkeypatch):
    # REST down but edgartools Financials yields REAL line items -> the financial families are
    # evaluated on data (complete), proving the fallback extracts rather than placeholders.
    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _CoWithFinancials())
    rec = edgar_fetch.fetch_ticker("REAL", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    assert rec["statements"]["annual"][0]["revenue"] == 100
    assert rec["statements"]["annual"][0]["cfo"] == 12
    for fam in ("accruals", "capex", "balance_sheet", "leverage"):
        assert rec["family_coverage"][fam] == "complete", f"{fam} should be complete on real line items"


# --- codex 2026-07-17 F4: 8-K fallback must read the body for governance items ---------
def test_8k_fallback_reads_body_for_governance_item(monkeypatch):
    # REST down; an 8-K Item 4.01 whose body discloses a DISAGREEMENT is an auto-Red, while a
    # routine re-tender is soft. The fallback dropped the body_excerpt, collapsing both to the
    # same Green. It must now read the body so the judge can tell them apart (codex 2026-07-17 F4).
    class _Co401(_FakeCompany):
        def get_filings(self, form=None):
            if form == "10-K":
                return _FakeFilings(_FakeFiling("Inventory. Goodwill. Debt."))
            if form == "8-K":
                f = _FakeFiling(
                    "Item 4.01 Changes in Registrant's Certifying Accountant. The dismissal "
                    "involved a disagreement regarding revenue recognition.",
                    filing_date="2026-05-01")
                f.items = "4.01"
                return _FakeFilings(f)
            return _FakeFilings(None)

    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _Co401())
    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    _schema_keys_present(rec)
    ev = next(e for e in rec["events_8k"] if "4.01" in e.get("items", []))
    assert "disagreement" in ev["body_excerpt"].lower(), \
        "the 4.01 body must be read so a disagreement (auto-Red) isn't hidden as a routine re-tender"
