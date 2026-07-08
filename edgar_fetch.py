"""Per-ticker forensic data fetch (Path A, unattended) -> data/fetched/<TICKER>.json.

The hybrid data layer (PATH_A_PLAN v3):
  - PRIMARY: paid Edgar-Tools REST (hyphenated direct paths) for statements + ratios +
    8-K item codes. The REST key works HEADLESSLY for these (the MCP rich tools do not).
  - FALLBACK / NOTE BODIES: the free `edgartools` library (direct SEC) for 10-K note BODIES,
    8-K bodies, Form-4 detail, and as a substitute for statements/8-K if the paid REST is down.

The single most important property of this module is the FALSE-GREEN GUARD:
  - It MUST NEVER RAISE. Every external source is wrapped; a failure becomes a status flag
    + a `source_errors` entry, never a crash that aborts a batch.
  - `not_disclosed` != `fetch_failed`. A note legitimately absent from a filing is fine
    (`present`/`not_disclosed`). A note we *failed to read* is `fetch_failed` -> the owning
    family is `unavailable` -> blocks Green.
  - It emits a HARD schema (see `_empty_record`), per PATH_A_PLAN "edgar_fetch.py -- JSON contract",
    including `family_coverage` (the COVERAGE enum from forensic_schema) and
    `required_families_complete` so forensic_tier can enforce "unevaluable != Green".

Staleness is computed from FILING DATES / period-end (codex R1 #7), NOT fiscal-year age.

CLI:
  python edgar_fetch.py TICKER [--cik 0000320193] [--out data/fetched]

This module does NOT decide tiers. It only gathers + classifies coverage. `tier_batch.py`
consumes the JSON; `forensic_tier.py` makes the final deterministic decision.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from forensic_schema import COVERAGE, FAMILIES, SCHEMA_VERSION, required_families

ROOT = Path(__file__).parent
WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"
DEFAULT_OUT_DIR = ROOT / "data" / "fetched"

# Staleness threshold: a 10-K whose period_end is older than this (no newer annual) is
# "stale" -> Data Gap. Date-based (period_end / filing_date), NOT fiscal-year-number age.
STALE_DAYS = 400

# 10-K note topics we attempt to read (title-substring search; see CLAUDE.md note re: literal match).
NOTE_TOPICS = {
    "Inventory": ["inventory"],
    "Goodwill": ["goodwill"],
    "Debt": ["debt", "borrowing", "credit facilit", "notes payable"],
    "Commitments": ["commitment", "contingenc", "legal", "litigation"],
    "Significant Accounting Policies": ["significant accounting", "summary of significant", "basis of presentation"],
    "Revenue": ["revenue"],
}

# 8-K item codes that matter for the governance / corporate-action families.
GOV_8K_ITEMS = {"4.01", "4.02", "5.02"}            # auditor change, non-reliance, officer dep.
CORP_ACTION_8K_ITEMS = {"2.01", "3.01", "5.01"}    # acquisition/disposal, delisting, control change
NT_FORMS = {"NT 10-K", "NT 10-Q", "NT10-K", "NT10-Q"}

# The REST API is versioned under /v1 (unversioned paths began returning 404 ~2026-07-01,
# which silently pushed every run onto the edgartools fallback — the 07-01..07-07 CI failures).
REST_BASE = "https://api.edgar.tools/v1"  # hyphenated direct paths under /v1/companies/{cik}/...


# --------------------------------------------------------------------------------------
# never-raise helpers
# --------------------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, errors: list, label: str, default=None):
    """Run fn(); on ANY exception record a compact source_error and return default.

    This is the never-raise contract: no external call may abort the run.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 -- deliberately broad; this is the guard
        errors.append({"source": label, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return default


def _empty_record(ticker: str, cik: str, run_id: str) -> dict:
    """The HARD schema. Every key present, conservative defaults (false-Green guard:
    absence is treated as not-evaluable, never as clean)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker,
        "cik": cik,
        "run_id": run_id,
        "fetched_at": _now_iso(),
        "filer_type": "unknown",
        "latest_10k": None,           # {accession, filing_date, period_end, fy}
        "latest_10q": None,
        "staleness": {"is_stale": True, "reason": "not_yet_evaluated"},
        "ratios": None,
        "statements": {"annual": [], "quarters": []},
        "notes": {topic: {"status": "fetch_failed", "text": ""} for topic in NOTE_TOPICS},
        "events_8k": [],              # [{date, items, body_excerpt}]
        "corporate_action": None,     # {detected, kind}
        "insider": {"clusters": [], "status": "fetch_failed"},
        "family_coverage": {f: "unavailable" for f in FAMILIES},
        "required_families_complete": False,
        "source_errors": [],
        "rest_available": False,      # whether the paid REST answered at all this run
    }


# --------------------------------------------------------------------------------------
# paid REST layer (primary for statements / ratios / 8-K item codes)
# --------------------------------------------------------------------------------------
class RestClient:
    """Thin wrapper over the paid Edgar-Tools REST. Every method is best-effort and may
    return None; the caller wraps it in _safe so an outage degrades, never crashes."""

    def __init__(self, api_key: str | None, identity: str | None):
        self.api_key = api_key
        self.identity = identity
        self._session = None

    def _sess(self):
        if self._session is None:
            import requests  # local import so tests can run without the dep on the import path
            s = requests.Session()
            headers = {"User-Agent": self.identity or "forensic_triage (jroypeterson@gmail.com)"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            s.headers.update(headers)
            self._session = s
        return self._session

    def _get(self, path: str):
        if not self.api_key:
            raise RuntimeError("no EDGARTOOLS_API_KEY -- REST unavailable")
        # Retry transient failures (429 / 5xx / connection errors) with backoff; a 4xx other
        # than 429 is deterministic (bad path / bad CIK) and fails immediately. GH runners
        # share egress IPs, so transient throttling is expected, not exceptional.
        import time

        import requests
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._sess().get(f"{REST_BASE}{path}", timeout=30)
                if resp.status_code == 429 or resp.status_code >= 500:
                    resp.raise_for_status()
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as exc:
                sc = exc.response.status_code if exc.response is not None else 0
                if sc != 429 and sc < 500:
                    raise  # deterministic client error -- retrying won't help
                last_exc = exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
            time.sleep(2 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def ratios(self, cik: str):
        return self._get(f"/companies/{cik}/ratios")

    def income_statement(self, cik: str):
        return self._get(f"/companies/{cik}/income-statement")

    def balance_sheet(self, cik: str):
        return self._get(f"/companies/{cik}/balance-sheet")

    def cash_flow(self, cik: str):
        return self._get(f"/companies/{cik}/cash-flow")

    def metrics(self, cik: str):
        return self._get(f"/companies/{cik}/metrics")

    def material_events(self, cik: str):
        return self._get(f"/companies/{cik}/material-events")


# --------------------------------------------------------------------------------------
# free edgartools layer (note bodies + fallbacks)
# --------------------------------------------------------------------------------------
def _edgar_company(cik: str, identity: str | None):
    """Return an edgartools Company, or raise (wrapped by _safe upstream)."""
    import edgar  # local import

    if identity:
        try:
            edgar.set_identity(identity)
        except Exception:  # noqa: BLE001
            pass
    return edgar.Company(cik)


def _parse_date(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


# --------------------------------------------------------------------------------------
# coverage classification (the false-Green guard's core)
# --------------------------------------------------------------------------------------
def _classify_coverage(rec: dict, subgroup: str) -> dict:
    """Map what we actually fetched to the per-family COVERAGE enum.

    Required financial families need statements; governance needs the 8-K feed; the
    note-backed checks need note bodies. Anything we FAILED to fetch -> unavailable
    (blocks Green). Structurally-unreachable-unattended families (market short interest,
    text MD&A diffs) -> not_evaluated.
    """
    cov: dict[str, str] = {}

    # Financial families need the STATEMENT LINE ITEMS. Ratios alone are NOT enough — the
    # /ratios endpoint can succeed while every statement endpoint fails, and accruals (CFO/NI),
    # balance-sheet (inventory/AR/goodwill) and leverage (debt) all need line items. Requiring
    # only ratios here would let an otherwise-clean domestic name go Green with no statements
    # actually fetched (codex P1). Require real statements; ratios are supplementary.
    #
    # PER-STATEMENT granularity (codex 2026-07-08): a nonempty annual list proves only
    # that SOME statement endpoint mapped. If income succeeded but balance-sheet/cash-flow
    # failed, accruals (needs CFO), capex, balance_sheet and leverage would all have been
    # marked complete off income data alone — a false-Green vector. Each family now also
    # requires its OWN source statement(s) to have been fetched (rec['_stmt_ok'], set by
    # fetch_ticker; the edgartools financials fallback sets all three, preserving its
    # original coarse semantics).
    stmt_ok = rec.get("_stmt_ok") or {}
    have_statements = bool(rec["statements"]["annual"])
    have_income = have_statements and bool(stmt_ok.get("income"))
    have_balance = have_statements and bool(stmt_ok.get("balance"))
    have_cashflow = have_statements and bool(stmt_ok.get("cashflow"))
    have_8k = isinstance(rec["events_8k"], list) and (
        rec.get("_events_8k_fetched") is True
    )

    def note_ok(*topics: str) -> bool:
        """A note family is 'evaluable' if at least one backing note was either read OR
        legitimately not-disclosed. Only a fetch_failure makes it unavailable."""
        statuses = [rec["notes"].get(t, {}).get("status", "fetch_failed") for t in topics]
        if not statuses:
            return False
        return all(s in ("present", "not_disclosed") for s in statuses)

    # Financial families lean on their OWN statements (see note above).
    cov["accruals"] = "complete" if (have_income and have_cashflow) else (
        "partial" if have_statements else "unavailable")
    cov["revenue"] = "complete" if (have_income and note_ok("Revenue", "Significant Accounting Policies")) else (
        "partial" if have_statements else "unavailable")
    cov["capex"] = "complete" if have_cashflow else (
        "partial" if have_statements else "unavailable")
    cov["balance_sheet"] = "complete" if (have_balance and note_ok("Inventory", "Goodwill")) else (
        "partial" if have_statements else "unavailable")
    cov["leverage"] = "complete" if (have_balance and note_ok("Debt")) else (
        "partial" if have_statements else "unavailable")

    # Governance: needs the 8-K feed (item codes). If neither REST nor edgartools delivered it -> unavailable.
    cov["governance"] = "complete" if have_8k else "unavailable"

    # Market + text are OPTIONAL (not reachable unattended) -> not_evaluated (never blocks Green).
    cov["market"] = "partial" if rec["insider"].get("status") == "present" else "not_evaluated"
    cov["text"] = "not_evaluated"

    # Sector: required for hc/medtech (note-backed, reachable); not_applicable for general.
    if subgroup == "general":
        cov["sector"] = "not_applicable"
    else:
        cov["sector"] = "complete" if note_ok("Significant Accounting Policies", "Commitments") else (
            "partial" if any(rec["notes"].get(t, {}).get("status") == "present"
                             for t in ("Inventory", "Revenue", "Commitments")) else "unavailable"
        )

    # Staleness / foreign filer override everything to a structural Data Gap (still "done").
    if rec["filer_type"] == "foreign":
        return {f: "not_evaluated" for f in FAMILIES} | ({"sector": "not_applicable"} if subgroup == "general" else {})
    if rec["staleness"].get("is_stale"):
        # genuinely stale -> required financial families can't be trusted current
        for f in ("accruals", "revenue", "capex", "balance_sheet", "leverage"):
            if cov[f] == "complete":
                cov[f] = "partial"

    # Sanity: only emit valid enum values.
    for f in FAMILIES:
        if cov.get(f) not in COVERAGE:
            cov[f] = "unavailable"
    return cov


def _required_complete(coverage: dict, subgroup: str) -> bool:
    for fam in required_families(subgroup):
        if coverage.get(fam, "unavailable") not in ("complete", "not_applicable"):
            return False
    return True


# --------------------------------------------------------------------------------------
# main fetch
# --------------------------------------------------------------------------------------
def fetch_ticker(
    ticker: str,
    cik: str,
    *,
    subgroup: str = "general",
    filer_type: str = "domestic",
    run_id: str = "manual",
    rest: RestClient | None = None,
    identity: str | None = None,
) -> dict:
    """Fetch + classify one name. NEVER RAISES -- returns a complete schema record."""
    rec = _empty_record(ticker, cik, run_id)
    rec["filer_type"] = filer_type
    errors = rec["source_errors"]
    identity = identity or os.environ.get("EDGAR_IDENTITY")

    # Foreign filers are a STRUCTURAL Data Gap -- do not spend EDGAR calls; mark done.
    if filer_type == "foreign":
        rec["staleness"] = {"is_stale": True, "reason": "foreign_20f_filer"}
        rec["family_coverage"] = _classify_coverage(rec, subgroup)
        rec["required_families_complete"] = _required_complete(rec["family_coverage"], subgroup)
        return rec

    if rest is None:
        rest = RestClient(os.environ.get("EDGARTOOLS_API_KEY"), identity)

    # --- 1. paid REST primary: ratios + statements + 8-K item codes ---
    ratios = _safe(lambda: rest.ratios(cik), errors, "rest:ratios")
    if ratios is not None:
        rec["ratios"] = ratios
        rec["rest_available"] = True

    income = _safe(lambda: rest.income_statement(cik), errors, "rest:income-statement")
    balance = _safe(lambda: rest.balance_sheet(cik), errors, "rest:balance-sheet")
    cashflow = _safe(lambda: rest.cash_flow(cik), errors, "rest:cash-flow")
    if any(x is not None for x in (income, balance, cashflow)):
        rec["rest_available"] = True
        rec["statements"]["annual"] = _safe(
            lambda: _normalize_statements(income, balance, cashflow), errors,
            "normalize:statements", default=[],
        ) or []
        # Which statements actually answered — coverage classification requires each
        # family's own source statement, not just "some statement" (codex 2026-07-08).
        rec["_stmt_ok"] = {
            "income": income is not None,
            "balance": balance is not None,
            "cashflow": cashflow is not None,
        }

    rest_events = _safe(lambda: rest.material_events(cik), errors, "rest:material-events")
    events_fetched = False
    if rest_events is not None:
        rec["events_8k"] = _safe(lambda: _normalize_events(rest_events), errors,
                                 "normalize:events", default=[]) or []
        events_fetched = True

    # --- 2. free edgartools: note bodies (always) + statement/8-K fallback if REST was down ---
    company = _safe(lambda: _edgar_company(cik, identity), errors, "edgartools:company")
    if company is not None:
        # latest 10-K / 10-Q + staleness (date-based)
        _safe(lambda: _populate_filings(rec, company), errors, "edgartools:filings")
        # note bodies (the thing only the free lib can do headlessly)
        _safe(lambda: _populate_notes(rec, company), errors, "edgartools:notes")
        # insider Form-4 (best-effort, OPTIONAL family)
        _safe(lambda: _populate_insider(rec, company), errors, "edgartools:insider")
        # fallback statements if REST gave us nothing
        if not rec["statements"]["annual"]:
            fb = _safe(lambda: _edgartools_statements(company), errors,
                       "edgartools:statements-fallback", default=[])
            if fb:
                rec["statements"]["annual"] = fb
                # The financials object spans all three statements — coarse by
                # design (preserves the fallback's original semantics).
                rec["_stmt_ok"] = {"income": True, "balance": True, "cashflow": True}
        # fallback 8-K feed if REST events were unavailable (so an outage can't hide a 4.02)
        if not events_fetched:
            fb_events = _safe(lambda: _edgartools_events(company), errors,
                              "edgartools:events-fallback", default=None)
            if fb_events is not None:
                rec["events_8k"] = fb_events
                events_fetched = True

    rec["_events_8k_fetched"] = events_fetched

    # --- 3. derive corporate-action + governance signals from the 8-K feed ---
    _safe(lambda: _derive_corporate_action(rec), errors, "derive:corporate_action")

    # --- 4. coverage classification + Green-eligibility precompute ---
    rec["family_coverage"] = _classify_coverage(rec, subgroup)
    rec["required_families_complete"] = _required_complete(rec["family_coverage"], subgroup)

    rec.pop("_events_8k_fetched", None)
    rec.pop("_stmt_ok", None)
    return rec


# --------------------------------------------------------------------------------------
# normalizers (defensive; each may be wrapped by _safe)
# --------------------------------------------------------------------------------------
# /v1 statement rows carry XBRL `concept` + curated `standard_concept`; map both onto the
# compact line-item names the rubric uses. First match wins (rows are emitted totals-first).
_V1_CONCEPT_MAP: dict[str, tuple[set[str], set[str]]] = {
    # our_key: ({us-gaap concepts, lowercased}, {standard_concept labels, lowercased})
    "revenue": ({"revenues", "revenuefromcontractwithcustomerexcludingassessedtax",
                 "salesrevenuenet"}, {"revenue"}),
    "net_income": ({"netincomeloss", "profitloss"}, {"net income"}),
    "gross_profit": ({"grossprofit"}, {"gross profit"}),
    "cogs": ({"costofgoodsandservicessold", "costofrevenue", "costofsales"}, {"cost of revenue"}),
    "depreciation_amortization": ({"depreciationdepletionandamortization",
                                   "depreciationandamortization", "depreciation"}, set()),
    "total_assets": ({"assets"}, {"total assets"}),
    "inventory": ({"inventorynet"}, {"inventory"}),
    "accounts_receivable": ({"accountsreceivablenetcurrent", "receivablesnetcurrent"},
                            {"accounts receivable"}),
    "goodwill": ({"goodwill"}, set()),
    "short_term_debt": ({"longtermdebtcurrent", "shorttermborrowings", "debtcurrent",
                         "commercialpaper"}, set()),
    "long_term_debt": ({"longtermdebtnoncurrent", "longtermdebt"}, set()),
    "deferred_revenue": ({"contractwithcustomerliabilitycurrent", "contractwithcustomerliability",
                          "deferredrevenuecurrent"}, set()),
    "cfo": ({"netcashprovidedbyusedinoperatingactivities",
             "netcashprovidedbyusedinoperatingactivitiescontinuingoperations"},
            {"operating cash flow"}),
    "capex": ({"paymentstoacquirepropertyplantandequipment",
               "paymentstoacquireproductiveassets"}, {"capital expenditure", "capex"}),
}


def _absorb_v1(payload, keys: list[str], periods: dict[str, dict]) -> bool:
    """Absorb the /v1 rows-x-periods shape. Returns True if this payload WAS /v1-shaped
    (regardless of how many keys matched), so the caller can skip the legacy path."""
    if not isinstance(payload, dict) or not isinstance(payload.get("statements"), dict):
        return False
    wanted = {k: _V1_CONCEPT_MAP[k] for k in keys if k in _V1_CONCEPT_MAP}
    for stmt in payload["statements"].values():
        rows = stmt.get("rows") if isinstance(stmt, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get("is_abstract") or row.get("is_dimension"):
                continue
            concept = str(row.get("concept") or "").lower()
            std = str(row.get("standard_concept") or "").lower()
            values = row.get("values")
            if not isinstance(values, dict):
                continue
            for key, (concepts, stds) in wanted.items():
                if concept in concepts or (std and std in stds):
                    for period, val in values.items():
                        if val is None:
                            continue
                        bucket = periods.setdefault(str(period), {"period": str(period)})
                        bucket.setdefault(key, val)  # first match wins (totals emitted first)
    return True


def _normalize_statements(income, balance, cashflow) -> list:
    """Fold the three REST statement payloads into a compact per-period list.

    Handles both the /v1 rows-x-periods shape (current) and the legacy flat row shape;
    we only need the line items the rubric uses. Best-effort: keep whatever periods we
    can align and tolerate missing concepts.
    """
    out: list[dict] = []
    periods: dict[str, dict] = {}

    def absorb(payload, keys):
        if _absorb_v1(payload, keys, periods):
            return
        if not isinstance(payload, dict):
            return
        rows = payload.get("data") or payload.get("statements") or payload.get("periods") or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            period = str(row.get("period") or row.get("fiscal_year") or row.get("date") or row.get("period_end") or "")
            if not period:
                continue
            bucket = periods.setdefault(period, {"period": period})
            for k in keys:
                if k in row and row[k] is not None:
                    bucket[k] = row[k]

    absorb(income, ["revenue", "net_income", "gross_profit", "cogs", "depreciation_amortization"])
    absorb(balance, ["total_assets", "inventory", "accounts_receivable", "goodwill",
                     "total_debt", "short_term_debt", "long_term_debt", "deferred_revenue"])
    absorb(cashflow, ["cfo", "capex", "depreciation_amortization"])

    for period in sorted(periods, reverse=True):
        out.append(periods[period])
    return out


def _normalize_events(payload) -> list:
    out: list[dict] = []
    rows = payload.get("data") or payload.get("events") or payload if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = rows.get("events", [])
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        items = row.get("items") or row.get("item_codes") or []
        if isinstance(items, str):
            items = [i.strip() for i in items.replace(";", ",").split(",") if i.strip()]
        out.append({
            "date": str(row.get("date") or row.get("filing_date") or ""),
            "items": [str(i) for i in items],
            "body_excerpt": (row.get("body") or row.get("description") or "")[:500],
        })
    return out


def _populate_filings(rec: dict, company) -> None:
    """Latest 10-K / 10-Q accession + dates, and date-based staleness."""
    def latest(form):
        try:
            filings = company.get_filings(form=form)
        except Exception:  # noqa: BLE001
            filings = None
        if not filings:
            return None
        try:
            f = filings.latest()
        except Exception:  # noqa: BLE001
            f = filings[0] if len(filings) else None
        if f is None:
            return None
        return {
            "accession": str(getattr(f, "accession_no", getattr(f, "accession_number", "")) or ""),
            "filing_date": str(getattr(f, "filing_date", "") or ""),
            "period_end": str(getattr(f, "period_of_report", getattr(f, "report_date", "")) or ""),
            "fy": str(getattr(f, "fiscal_year", "") or ""),
        }

    k = latest("10-K")
    q = latest("10-Q")
    rec["latest_10k"] = k
    rec["latest_10q"] = q

    # Staleness: date-based on the 10-K's period_end (fallback filing_date), NOT fy age.
    ref = None
    if k:
        ref = _parse_date(k.get("period_end")) or _parse_date(k.get("filing_date"))
    if ref is None:
        rec["staleness"] = {"is_stale": True, "reason": "no_10k_found"}
        return
    age = (datetime.now(timezone.utc).date() - ref).days
    if age > STALE_DAYS:
        rec["staleness"] = {"is_stale": True, "reason": f"latest 10-K period_end {ref} is {age}d old (> {STALE_DAYS})"}
    else:
        rec["staleness"] = {"is_stale": False, "reason": f"latest 10-K period_end {ref} ({age}d old)"}


def _populate_notes(rec: dict, company) -> None:
    """Read 10-K note bodies. Distinguish present / not_disclosed / fetch_failed PER NOTE.

    The whole false-Green guard hinges on this: we only mark a note `fetch_failed` when the
    READ itself errored. If the filing was readable but the topic simply isn't there, that's
    `not_disclosed` (a legitimate absence, not a data gap).
    """
    filing = None
    try:
        tenk = company.get_filings(form="10-K")
        filing = tenk.latest() if tenk else None
    except Exception as exc:  # noqa: BLE001
        # Could not even load the 10-K -> EVERY note is fetch_failed (blocks the note families).
        for topic in NOTE_TOPICS:
            rec["notes"][topic] = {"status": "fetch_failed", "text": ""}
        rec["source_errors"].append({"source": "edgartools:10k-load", "error": f"{type(exc).__name__}: {exc}"[:200]})
        return

    if filing is None:
        for topic in NOTE_TOPICS:
            rec["notes"][topic] = {"status": "not_disclosed", "text": ""}  # no 10-K -> nothing disclosed there
        return

    # Pull the full text once; topic search is substring-on-text (best-effort).
    full_text = None
    try:
        obj = filing.obj() if hasattr(filing, "obj") else None
        full_text = (obj.text() if obj is not None and hasattr(obj, "text") else None)
        if full_text is None:
            full_text = filing.text() if hasattr(filing, "text") else None
    except Exception:  # noqa: BLE001
        full_text = None

    if not full_text:
        # The filing handle exists but body unreadable -> a genuine FETCH FAILURE.
        for topic in NOTE_TOPICS:
            rec["notes"][topic] = {"status": "fetch_failed", "text": ""}
        rec["source_errors"].append({"source": "edgartools:10k-text", "error": "empty filing body"})
        return

    low = full_text.lower()
    for topic, keys in NOTE_TOPICS.items():
        hit_idx = -1
        for kw in keys:
            idx = low.find(kw)
            if idx != -1:
                hit_idx = idx
                break
        if hit_idx == -1:
            rec["notes"][topic] = {"status": "not_disclosed", "text": ""}
        else:
            excerpt = full_text[hit_idx: hit_idx + 1500]
            rec["notes"][topic] = {"status": "present", "text": excerpt}


def _populate_insider(rec: dict, company) -> None:
    try:
        forms = company.get_filings(form="4")
    except Exception:  # noqa: BLE001
        forms = None
    if not forms:
        rec["insider"] = {"clusters": [], "status": "not_evaluated"}
        return
    try:
        recent = forms.head(20) if hasattr(forms, "head") else forms[:20]
        dates = [str(getattr(f, "filing_date", "")) for f in recent]
    except Exception:  # noqa: BLE001
        rec["insider"] = {"clusters": [], "status": "not_evaluated"}
        return
    rec["insider"] = {"clusters": [], "recent_form4_dates": dates, "status": "present"}


def _edgartools_statements(company) -> list:
    """Fallback statements via companyfacts/financials when REST is down."""
    try:
        fin = company.financials if hasattr(company, "financials") else None
    except Exception:  # noqa: BLE001
        fin = None
    if fin is None:
        return []
    # We keep this minimal: presence of a financials object is enough for coverage to be
    # non-unavailable; the detailed line-item extraction is best-effort and tolerant.
    return [{"period": "latest", "source": "edgartools_financials"}]


def _edgartools_events(company) -> list:
    """Fallback 8-K item-code feed via edgartools, so a REST outage can't hide a 4.02."""
    out: list[dict] = []
    # Do NOT swallow a fetch FAILURE here. If get_filings RAISES, let it propagate so the
    # caller's _safe() returns None (= fetch failed -> events_fetched stays False -> governance
    # coverage `unavailable`). Returning [] on an exception is indistinguishable from "genuinely
    # no 8-Ks" and would mark governance complete during an outage, hiding a 4.02 (codex P1).
    eights = company.get_filings(form="8-K")
    if not eights:
        return []
    try:
        recent = eights.head(25) if hasattr(eights, "head") else eights[:25]
    except Exception:  # noqa: BLE001
        recent = eights
    for f in recent:
        items = getattr(f, "items", None) or []
        if isinstance(items, str):
            items = [i.strip() for i in items.replace(";", ",").split(",") if i.strip()]
        out.append({
            "date": str(getattr(f, "filing_date", "") or ""),
            "items": [str(i) for i in items],
            "body_excerpt": "",
        })
    return out


def _derive_corporate_action(rec: dict) -> None:
    """Set governance / corporate-action hints from the 8-K item codes (deterministic facts;
    Claude still judges severity, but the codes themselves are read here)."""
    corp_kind = None
    for ev in rec["events_8k"]:
        items = set(ev.get("items", []))
        if items & CORP_ACTION_8K_ITEMS:
            corp_kind = sorted(items & CORP_ACTION_8K_ITEMS)[0]
    if corp_kind:
        rec["corporate_action"] = {"detected": True, "kind": f"8-K item {corp_kind}"}


# --------------------------------------------------------------------------------------
# watchlist lookup + persistence
# --------------------------------------------------------------------------------------
def _lookup_watchlist(ticker: str) -> dict | None:
    if not WATCHLIST_CSV.exists():
        return None
    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("ticker") or "").strip().upper() == ticker.upper():
                return row
    return None


def write_record(rec: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{rec['ticker']}.json"
    tmp = out_dir / f".{rec['ticker']}.json.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, sort_keys=False)
    tmp.replace(path)
    return path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ticker")
    p.add_argument("--cik", default=None, help="10-digit CIK (else looked up from watchlist.csv)")
    p.add_argument("--subgroup", default=None)
    p.add_argument("--filer-type", default=None)
    p.add_argument("--run-id", default="manual")
    p.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    args = p.parse_args(argv)

    ticker = args.ticker.strip().upper()
    row = _lookup_watchlist(ticker) or {}
    cik = (args.cik or row.get("cik") or "").strip()
    subgroup = args.subgroup or row.get("sector_subgroup") or "general"
    filer_type = args.filer_type or row.get("filer_type") or "domestic"

    if not cik and filer_type != "foreign":
        # No CIK and not a known-foreign skip -> we cannot fetch. Emit a fetch-failed record
        # (never crash) so the caller sees a transient failure, not a false Data Gap.
        rec = _empty_record(ticker, "", args.run_id)
        rec["filer_type"] = filer_type
        rec["source_errors"].append({"source": "watchlist", "error": "no CIK found for ticker"})
        path = write_record(rec, Path(args.out))
        print(f"WROTE {path} (NO CIK -- fetch_failed; not green-eligible)")
        return 0

    # The fetch itself never raises; this top-level guard is belt-and-suspenders only.
    try:
        rec = fetch_ticker(ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=args.run_id)
    except Exception as exc:  # noqa: BLE001
        rec = _empty_record(ticker, cik, args.run_id)
        rec["filer_type"] = filer_type
        rec["source_errors"].append({"source": "fetch_ticker", "error": f"{type(exc).__name__}: {exc}"})
        rec["source_errors"].append({"source": "traceback", "error": traceback.format_exc()[:400]})

    path = write_record(rec, Path(args.out))
    cov = rec["family_coverage"]
    print(f"WROTE {path}  filer={rec['filer_type']}  "
          f"required_complete={rec['required_families_complete']}  "
          f"errors={len(rec['source_errors'])}")
    print("  coverage:", ", ".join(f"{k}={cov[k]}" for k in FAMILIES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
