OpenAI Codex v0.141.0
--------
workdir: /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: none
reasoning summaries: none
session id: 019efc6b-32af-7163-a54b-a8400ec0deb6
--------
user
Correctness + safety review of this unattended forensic-accounting screen (forensic_triage "Path A": edgar_fetch.py, tier_batch.py, forensic_tier.py, forensic_schema.py, next_batch.py, run_unattended.py, notify.py, .github/workflows/forensic_triage.yml). The CARDINAL rule: a company whose data could NOT be fully evaluated must NEVER be tiered Green — a false Green is a missed accounting problem and the worst possible failure. Surface ONLY actionable Critical/High issues, each with file:line and a one-line why. Skip style nits.

Focus:
1. False-Green guard: any path where `required_families_complete` / the Green-eligibility gate can be bypassed so an unevaluable, partially-fetched, or fetch-failed name ends up Green. Does `not_disclosed` vs `fetch_failed` correctly distinguish "legitimately absent note" (ok) from "we failed to fetch" (must block Green)?
2. edgar_fetch.py never-raises contract: any unwrapped source call that could crash the run — or worse, an exception/empty-result swallowed into a falsely "complete" family coverage.
3. tier_batch.py: does a malformed, refused, or stop_reason!=end_turn Anthropic structured-output response fail CLOSED (never default to Green)? Does Claude ever emit the FINAL tier (it must only emit per-family flags; the tier must be computed deterministically by forensic_tier.finalize_tier)?
4. forensic_tier.finalize_tier deterministic precedence (Corporate-Action vs Data-Gap vs critical-governance vs high-severity-accounting): any precedence bug that mis-tiers — especially critical-gov/high-severity that must OVERRIDE Data Gap, and Corporate-Action only when NO accounting concern.
5. next_batch.py idempotency: can a TRANSIENT fetch_failure mark a ticker status=complete (done for the cycle), poisoning coverage so it's never retried? A structural Data Gap (foreign/stale/not_disclosed) SHOULD be done; a transient failure should NOT.
6. GH Actions workflow: any secret echoed/logged; the rebase-before-push step racing a concurrent push; and whether the cron will fire-and-fail-loudly (alarm) before secrets are provisioned (a known pre-enable state) vs silently.
7. flags_history.csv 13->16 column migration: any data-loss or column-misalignment risk on an existing file.
8. The run-level circuit breaker: does a broad SEC/REST outage correctly FAIL the run loudly instead of committing a batch of false Data Gaps?
exec
/bin/bash -lc 'git status --short && git diff --stat && git diff -- edgar_fetch.py tier_batch.py forensic_tier.py forensic_schema.py next_batch.py run_unattended.py notify.py .github/workflows/forensic_triage.yml' in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 2626ms:
A  .github/workflows/forensic_triage.yml
M  CLAUDE.md
AM PROJECT_BRIEF.md
 M data/flags_history.csv
MM data/watchlist.csv
A  edgar_fetch.py
M  next_batch.py
A  notify.py
 M reports/forensic_2026-04-17_smoketest.md
A  requirements.txt
A  run_unattended.py
M  sync_watchlist.py
A  tests/test_edgar_fetch.py
A  tests/test_tier_guardrails.py
A  tier_batch.py
?? codex_feedback/
 PROJECT_BRIEF.md                         | 294 +++++++--------
 data/flags_history.csv                   |  16 +-
 data/watchlist.csv                       | 604 +++++++++++++++----------------
 reports/forensic_2026-04-17_smoketest.md | 148 ++++----
 4 files changed, 531 insertions(+), 531 deletions(-)

exec
/bin/bash -lc 'git diff --cached -- edgar_fetch.py tier_batch.py forensic_tier.py forensic_schema.py next_batch.py run_unattended.py notify.py .github/workflows/forensic_triage.yml && git diff -- edgar_fetch.py tier_batch.py forensic_tier.py forensic_schema.py next_batch.py run_unattended.py notify.py .github/workflows/forensic_triage.yml' in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 956ms:
diff --git a/.github/workflows/forensic_triage.yml b/.github/workflows/forensic_triage.yml
new file mode 100644
index 0000000..b63fcb7
--- /dev/null
+++ b/.github/workflows/forensic_triage.yml
@@ -0,0 +1,77 @@
+name: Forensic Triage (unattended)
+
+# Path A: GitHub Actions cron + Anthropic-API tiering (PATH_A_PLAN v3).
+# Screens a few domestic names per run, posts Red/Yellow/Green/Data-Gap to #forensic-flags,
+# heartbeats to #status-reports, and commits the compact report + history (never the big
+# fetched JSON — data/fetched/ is gitignored).
+
+on:
+  schedule:
+    # 18:30 UTC weekdays (~13:30 ET winter / 14:30 ET summer — after the SEC filing day).
+    - cron: '30 18 * * 1-5'
+  workflow_dispatch:
+    inputs:
+      batch_size:
+        description: 'How many names to screen this run'
+        required: false
+        default: '6'
+
+concurrency:
+  group: forensic-triage
+  cancel-in-progress: false
+
+permissions:
+  contents: write
+
+jobs:
+  screen:
+    runs-on: ubuntu-latest
+    env:
+      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
+      EDGARTOOLS_API_KEY: ${{ secrets.EDGARTOOLS_API_KEY }}
+      EDGAR_IDENTITY: ${{ secrets.EDGAR_IDENTITY }}
+      SLACK_WEBHOOK_FORENSIC: ${{ secrets.SLACK_WEBHOOK_FORENSIC }}
+      SLACK_WEBHOOK_STATUS_REPORTS: ${{ secrets.SLACK_WEBHOOK_STATUS_REPORTS }}
+      BATCH_SIZE: ${{ github.event.inputs.batch_size || '6' }}
+
+    steps:
+      - name: Checkout repo
+        uses: actions/checkout@v5
+
+      - name: Set up Python
+        uses: actions/setup-python@v6
+        with:
+          python-version: '3.12'
+
+      - name: Install dependencies
+        run: pip install -r requirements.txt
+
+      - name: Run unattended screen
+        id: screen
+        run: python run_unattended.py --batch-size "$BATCH_SIZE" --run-id "${{ github.run_id }}"
+
+      - name: Commit and push report + history
+        if: success()
+        run: |
+          git config user.name "github-actions[bot]"
+          git config user.email "github-actions[bot]@users.noreply.github.com"
+          git add data/flags_history.csv reports/ data/ratios_latest.csv 2>/dev/null || true
+          if git diff --cached --quiet; then
+            echo "No changes to commit."
+          else
+            git commit -m "Forensic triage run ${{ github.run_id }} [skip ci]"
+            # rebase-before-push (fleet pattern) to avoid races with other pushers
+            for i in 1 2 3; do
+              git pull --rebase --autostash origin main && git push origin main && break
+              echo "push attempt $i failed; retrying"
+              sleep 5
+            done
+          fi
+
+      - name: Notify Slack (results + heartbeat)
+        if: success()
+        run: python run_unattended.py --notify-only --run-id "${{ github.run_id }}"
+
+      - name: Failure alarm to #status-reports
+        if: failure()
+        run: python run_unattended.py --failure-alarm --run-id "${{ github.run_id }}" --error "workflow step failed (see Actions log)"
diff --git a/edgar_fetch.py b/edgar_fetch.py
new file mode 100644
index 0000000..514981b
--- /dev/null
+++ b/edgar_fetch.py
@@ -0,0 +1,636 @@
+"""Per-ticker forensic data fetch (Path A, unattended) -> data/fetched/<TICKER>.json.
+
+The hybrid data layer (PATH_A_PLAN v3):
+  - PRIMARY: paid Edgar-Tools REST (hyphenated direct paths) for statements + ratios +
+    8-K item codes. The REST key works HEADLESSLY for these (the MCP rich tools do not).
+  - FALLBACK / NOTE BODIES: the free `edgartools` library (direct SEC) for 10-K note BODIES,
+    8-K bodies, Form-4 detail, and as a substitute for statements/8-K if the paid REST is down.
+
+The single most important property of this module is the FALSE-GREEN GUARD:
+  - It MUST NEVER RAISE. Every external source is wrapped; a failure becomes a status flag
+    + a `source_errors` entry, never a crash that aborts a batch.
+  - `not_disclosed` != `fetch_failed`. A note legitimately absent from a filing is fine
+    (`present`/`not_disclosed`). A note we *failed to read* is `fetch_failed` -> the owning
+    family is `unavailable` -> blocks Green.
+  - It emits a HARD schema (see `_empty_record`), per PATH_A_PLAN "edgar_fetch.py -- JSON contract",
+    including `family_coverage` (the COVERAGE enum from forensic_schema) and
+    `required_families_complete` so forensic_tier can enforce "unevaluable != Green".
+
+Staleness is computed from FILING DATES / period-end (codex R1 #7), NOT fiscal-year age.
+
+CLI:
+  python edgar_fetch.py TICKER [--cik 0000320193] [--out data/fetched]
+
+This module does NOT decide tiers. It only gathers + classifies coverage. `tier_batch.py`
+consumes the JSON; `forensic_tier.py` makes the final deterministic decision.
+"""
+from __future__ import annotations
+
+import argparse
+import csv
+import json
+import os
+import sys
+import traceback
+from datetime import datetime, timezone
+from pathlib import Path
+
+from forensic_schema import COVERAGE, FAMILIES, SCHEMA_VERSION, required_families
+
+ROOT = Path(__file__).parent
+WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"
+DEFAULT_OUT_DIR = ROOT / "data" / "fetched"
+
+# Staleness threshold: a 10-K whose period_end is older than this (no newer annual) is
+# "stale" -> Data Gap. Date-based (period_end / filing_date), NOT fiscal-year-number age.
+STALE_DAYS = 400
+
+# 10-K note topics we attempt to read (title-substring search; see CLAUDE.md note re: literal match).
+NOTE_TOPICS = {
+    "Inventory": ["inventory"],
+    "Goodwill": ["goodwill"],
+    "Debt": ["debt", "borrowing", "credit facilit", "notes payable"],
+    "Commitments": ["commitment", "contingenc", "legal", "litigation"],
+    "Significant Accounting Policies": ["significant accounting", "summary of significant", "basis of presentation"],
+    "Revenue": ["revenue"],
+}
+
+# 8-K item codes that matter for the governance / corporate-action families.
+GOV_8K_ITEMS = {"4.01", "4.02", "5.02"}            # auditor change, non-reliance, officer dep.
+CORP_ACTION_8K_ITEMS = {"2.01", "3.01", "5.01"}    # acquisition/disposal, delisting, control change
+NT_FORMS = {"NT 10-K", "NT 10-Q", "NT10-K", "NT10-Q"}
+
+REST_BASE = "https://api.edgar.tools"  # documented hyphenated direct paths under /companies/{cik}/...
+
+
+# --------------------------------------------------------------------------------------
+# never-raise helpers
+# --------------------------------------------------------------------------------------
+def _now_iso() -> str:
+    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
+
+
+def _safe(fn, errors: list, label: str, default=None):
+    """Run fn(); on ANY exception record a compact source_error and return default.
+
+    This is the never-raise contract: no external call may abort the run.
+    """
+    try:
+        return fn()
+    except Exception as exc:  # noqa: BLE001 -- deliberately broad; this is the guard
+        errors.append({"source": label, "error": f"{type(exc).__name__}: {exc}"[:300]})
+        return default
+
+
+def _empty_record(ticker: str, cik: str, run_id: str) -> dict:
+    """The HARD schema. Every key present, conservative defaults (false-Green guard:
+    absence is treated as not-evaluable, never as clean)."""
+    return {
+        "schema_version": SCHEMA_VERSION,
+        "ticker": ticker,
+        "cik": cik,
+        "run_id": run_id,
+        "fetched_at": _now_iso(),
+        "filer_type": "unknown",
+        "latest_10k": None,           # {accession, filing_date, period_end, fy}
+        "latest_10q": None,
+        "staleness": {"is_stale": True, "reason": "not_yet_evaluated"},
+        "ratios": None,
+        "statements": {"annual": [], "quarters": []},
+        "notes": {topic: {"status": "fetch_failed", "text": ""} for topic in NOTE_TOPICS},
+        "events_8k": [],              # [{date, items, body_excerpt}]
+        "corporate_action": None,     # {detected, kind}
+        "insider": {"clusters": [], "status": "fetch_failed"},
+        "family_coverage": {f: "unavailable" for f in FAMILIES},
+        "required_families_complete": False,
+        "source_errors": [],
+        "rest_available": False,      # whether the paid REST answered at all this run
+    }
+
+
+# --------------------------------------------------------------------------------------
+# paid REST layer (primary for statements / ratios / 8-K item codes)
+# --------------------------------------------------------------------------------------
+class RestClient:
+    """Thin wrapper over the paid Edgar-Tools REST. Every method is best-effort and may
+    return None; the caller wraps it in _safe so an outage degrades, never crashes."""
+
+    def __init__(self, api_key: str | None, identity: str | None):
+        self.api_key = api_key
+        self.identity = identity
+        self._session = None
+
+    def _sess(self):
+        if self._session is None:
+            import requests  # local import so tests can run without the dep on the import path
+            s = requests.Session()
+            headers = {"User-Agent": self.identity or "forensic_triage (jroypeterson@gmail.com)"}
+            if self.api_key:
+                headers["Authorization"] = f"Bearer {self.api_key}"
+            s.headers.update(headers)
+            self._session = s
+        return self._session
+
+    def _get(self, path: str):
+        if not self.api_key:
+            raise RuntimeError("no EDGARTOOLS_API_KEY -- REST unavailable")
+        resp = self._sess().get(f"{REST_BASE}{path}", timeout=30)
+        resp.raise_for_status()
+        return resp.json()
+
+    def ratios(self, cik: str):
+        return self._get(f"/companies/{cik}/ratios")
+
+    def income_statement(self, cik: str):
+        return self._get(f"/companies/{cik}/income-statement")
+
+    def balance_sheet(self, cik: str):
+        return self._get(f"/companies/{cik}/balance-sheet")
+
+    def cash_flow(self, cik: str):
+        return self._get(f"/companies/{cik}/cash-flow")
+
+    def metrics(self, cik: str):
+        return self._get(f"/companies/{cik}/metrics")
+
+    def material_events(self, cik: str):
+        return self._get(f"/companies/{cik}/material-events")
+
+
+# --------------------------------------------------------------------------------------
+# free edgartools layer (note bodies + fallbacks)
+# --------------------------------------------------------------------------------------
+def _edgar_company(cik: str, identity: str | None):
+    """Return an edgartools Company, or raise (wrapped by _safe upstream)."""
+    import edgar  # local import
+
+    if identity:
+        try:
+            edgar.set_identity(identity)
+        except Exception:  # noqa: BLE001
+            pass
+    return edgar.Company(cik)
+
+
+def _parse_date(s: str | None):
+    if not s:
+        return None
+    for fmt in ("%Y-%m-%d", "%Y%m%d"):
+        try:
+            return datetime.strptime(s[:10], fmt).date()
+        except (ValueError, TypeError):
+            continue
+    return None
+
+
+# --------------------------------------------------------------------------------------
+# coverage classification (the false-Green guard's core)
+# --------------------------------------------------------------------------------------
+def _classify_coverage(rec: dict, subgroup: str) -> dict:
+    """Map what we actually fetched to the per-family COVERAGE enum.
+
+    Required financial families need statements; governance needs the 8-K feed; the
+    note-backed checks need note bodies. Anything we FAILED to fetch -> unavailable
+    (blocks Green). Structurally-unreachable-unattended families (market short interest,
+    text MD&A diffs) -> not_evaluated.
+    """
+    cov: dict[str, str] = {}
+
+    have_statements = bool(rec["statements"]["annual"]) or rec["ratios"] is not None
+    have_8k = isinstance(rec["events_8k"], list) and (
+        rec.get("_events_8k_fetched") is True
+    )
+
+    def note_ok(*topics: str) -> bool:
+        """A note family is 'evaluable' if at least one backing note was either read OR
+        legitimately not-disclosed. Only a fetch_failure makes it unavailable."""
+        statuses = [rec["notes"].get(t, {}).get("status", "fetch_failed") for t in topics]
+        if not statuses:
+            return False
+        return all(s in ("present", "not_disclosed") for s in statuses)
+
+    # Financial families lean on statements.
+    fin_state = "complete" if have_statements else "unavailable"
+    cov["accruals"] = fin_state
+    cov["revenue"] = "complete" if (have_statements and note_ok("Revenue", "Significant Accounting Policies")) else ("partial" if have_statements else "unavailable")
+    cov["capex"] = fin_state
+    cov["balance_sheet"] = "complete" if (have_statements and note_ok("Inventory", "Goodwill")) else ("partial" if have_statements else "unavailable")
+    cov["leverage"] = "complete" if (have_statements and note_ok("Debt")) else ("partial" if have_statements else "unavailable")
+
+    # Governance: needs the 8-K feed (item codes). If neither REST nor edgartools delivered it -> unavailable.
+    cov["governance"] = "complete" if have_8k else "unavailable"
+
+    # Market + text are OPTIONAL (not reachable unattended) -> not_evaluated (never blocks Green).
+    cov["market"] = "partial" if rec["insider"].get("status") == "present" else "not_evaluated"
+    cov["text"] = "not_evaluated"
+
+    # Sector: required for hc/medtech (note-backed, reachable); not_applicable for general.
+    if subgroup == "general":
+        cov["sector"] = "not_applicable"
+    else:
+        cov["sector"] = "complete" if note_ok("Significant Accounting Policies", "Commitments") else (
+            "partial" if any(rec["notes"].get(t, {}).get("status") == "present"
+                             for t in ("Inventory", "Revenue", "Commitments")) else "unavailable"
+        )
+
+    # Staleness / foreign filer override everything to a structural Data Gap (still "done").
+    if rec["filer_type"] == "foreign":
+        return {f: "not_evaluated" for f in FAMILIES} | ({"sector": "not_applicable"} if subgroup == "general" else {})
+    if rec["staleness"].get("is_stale"):
+        # genuinely stale -> required financial families can't be trusted current
+        for f in ("accruals", "revenue", "capex", "balance_sheet", "leverage"):
+            if cov[f] == "complete":
+                cov[f] = "partial"
+
+    # Sanity: only emit valid enum values.
+    for f in FAMILIES:
+        if cov.get(f) not in COVERAGE:
+            cov[f] = "unavailable"
+    return cov
+
+
+def _required_complete(coverage: dict, subgroup: str) -> bool:
+    for fam in required_families(subgroup):
+        if coverage.get(fam, "unavailable") not in ("complete", "not_applicable"):
+            return False
+    return True
+
+
+# --------------------------------------------------------------------------------------
+# main fetch
+# --------------------------------------------------------------------------------------
+def fetch_ticker(
+    ticker: str,
+    cik: str,
+    *,
+    subgroup: str = "general",
+    filer_type: str = "domestic",
+    run_id: str = "manual",
+    rest: RestClient | None = None,
+    identity: str | None = None,
+) -> dict:
+    """Fetch + classify one name. NEVER RAISES -- returns a complete schema record."""
+    rec = _empty_record(ticker, cik, run_id)
+    rec["filer_type"] = filer_type
+    errors = rec["source_errors"]
+    identity = identity or os.environ.get("EDGAR_IDENTITY")
+
+    # Foreign filers are a STRUCTURAL Data Gap -- do not spend EDGAR calls; mark done.
+    if filer_type == "foreign":
+        rec["staleness"] = {"is_stale": True, "reason": "foreign_20f_filer"}
+        rec["family_coverage"] = _classify_coverage(rec, subgroup)
+        rec["required_families_complete"] = _required_complete(rec["family_coverage"], subgroup)
+        return rec
+
+    if rest is None:
+        rest = RestClient(os.environ.get("EDGARTOOLS_API_KEY"), identity)
+
+    # --- 1. paid REST primary: ratios + statements + 8-K item codes ---
+    ratios = _safe(lambda: rest.ratios(cik), errors, "rest:ratios")
+    if ratios is not None:
+        rec["ratios"] = ratios
+        rec["rest_available"] = True
+
+    income = _safe(lambda: rest.income_statement(cik), errors, "rest:income-statement")
+    balance = _safe(lambda: rest.balance_sheet(cik), errors, "rest:balance-sheet")
+    cashflow = _safe(lambda: rest.cash_flow(cik), errors, "rest:cash-flow")
+    if any(x is not None for x in (income, balance, cashflow)):
+        rec["rest_available"] = True
+        rec["statements"]["annual"] = _safe(
+            lambda: _normalize_statements(income, balance, cashflow), errors,
+            "normalize:statements", default=[],
+        ) or []
+
+    rest_events = _safe(lambda: rest.material_events(cik), errors, "rest:material-events")
+    events_fetched = False
+    if rest_events is not None:
+        rec["events_8k"] = _safe(lambda: _normalize_events(rest_events), errors,
+                                 "normalize:events", default=[]) or []
+        events_fetched = True
+
+    # --- 2. free edgartools: note bodies (always) + statement/8-K fallback if REST was down ---
+    company = _safe(lambda: _edgar_company(cik, identity), errors, "edgartools:company")
+    if company is not None:
+        # latest 10-K / 10-Q + staleness (date-based)
+        _safe(lambda: _populate_filings(rec, company), errors, "edgartools:filings")
+        # note bodies (the thing only the free lib can do headlessly)
+        _safe(lambda: _populate_notes(rec, company), errors, "edgartools:notes")
+        # insider Form-4 (best-effort, OPTIONAL family)
+        _safe(lambda: _populate_insider(rec, company), errors, "edgartools:insider")
+        # fallback statements if REST gave us nothing
+        if not rec["statements"]["annual"]:
+            fb = _safe(lambda: _edgartools_statements(company), errors,
+                       "edgartools:statements-fallback", default=[])
+            if fb:
+                rec["statements"]["annual"] = fb
+        # fallback 8-K feed if REST events were unavailable (so an outage can't hide a 4.02)
+        if not events_fetched:
+            fb_events = _safe(lambda: _edgartools_events(company), errors,
+                              "edgartools:events-fallback", default=None)
+            if fb_events is not None:
+                rec["events_8k"] = fb_events
+                events_fetched = True
+
+    rec["_events_8k_fetched"] = events_fetched
+
+    # --- 3. derive corporate-action + governance signals from the 8-K feed ---
+    _safe(lambda: _derive_corporate_action(rec), errors, "derive:corporate_action")
+
+    # --- 4. coverage classification + Green-eligibility precompute ---
+    rec["family_coverage"] = _classify_coverage(rec, subgroup)
+    rec["required_families_complete"] = _required_complete(rec["family_coverage"], subgroup)
+
+    rec.pop("_events_8k_fetched", None)
+    return rec
+
+
+# --------------------------------------------------------------------------------------
+# normalizers (defensive; each may be wrapped by _safe)
+# --------------------------------------------------------------------------------------
+def _normalize_statements(income, balance, cashflow) -> list:
+    """Fold the three REST statement payloads into a compact per-period list.
+
+    REST shapes vary; we only need the line items the rubric uses. Best-effort: we keep
+    whatever periods we can align and tolerate missing concepts.
+    """
+    out: list[dict] = []
+    periods: dict[str, dict] = {}
+
+    def absorb(payload, keys):
+        if not isinstance(payload, dict):
+            return
+        rows = payload.get("data") or payload.get("statements") or payload.get("periods") or []
+        if isinstance(rows, dict):
+            rows = [rows]
+        for row in rows if isinstance(rows, list) else []:
+            if not isinstance(row, dict):
+                continue
+            period = str(row.get("period") or row.get("fiscal_year") or row.get("date") or row.get("period_end") or "")
+            if not period:
+                continue
+            bucket = periods.setdefault(period, {"period": period})
+            for k in keys:
+                if k in row and row[k] is not None:
+                    bucket[k] = row[k]
+
+    absorb(income, ["revenue", "net_income", "gross_profit", "cogs", "depreciation_amortization"])
+    absorb(balance, ["total_assets", "inventory", "accounts_receivable", "goodwill",
+                     "total_debt", "short_term_debt", "long_term_debt", "deferred_revenue"])
+    absorb(cashflow, ["cfo", "capex", "depreciation_amortization"])
+
+    for period in sorted(periods, reverse=True):
+        out.append(periods[period])
+    return out
+
+
+def _normalize_events(payload) -> list:
+    out: list[dict] = []
+    rows = payload.get("data") or payload.get("events") or payload if isinstance(payload, dict) else payload
+    if isinstance(rows, dict):
+        rows = rows.get("events", [])
+    for row in rows if isinstance(rows, list) else []:
+        if not isinstance(row, dict):
+            continue
+        items = row.get("items") or row.get("item_codes") or []
+        if isinstance(items, str):
+            items = [i.strip() for i in items.replace(";", ",").split(",") if i.strip()]
+        out.append({
+            "date": str(row.get("date") or row.get("filing_date") or ""),
+            "items": [str(i) for i in items],
+            "body_excerpt": (row.get("body") or row.get("description") or "")[:500],
+        })
+    return out
+
+
+def _populate_filings(rec: dict, company) -> None:
+    """Latest 10-K / 10-Q accession + dates, and date-based staleness."""
+    def latest(form):
+        try:
+            filings = company.get_filings(form=form)
+        except Exception:  # noqa: BLE001
+            filings = None
+        if not filings:
+            return None
+        try:
+            f = filings.latest()
+        except Exception:  # noqa: BLE001
+            f = filings[0] if len(filings) else None
+        if f is None:
+            return None
+        return {
+            "accession": str(getattr(f, "accession_no", getattr(f, "accession_number", "")) or ""),
+            "filing_date": str(getattr(f, "filing_date", "") or ""),
+            "period_end": str(getattr(f, "period_of_report", getattr(f, "report_date", "")) or ""),
+            "fy": str(getattr(f, "fiscal_year", "") or ""),
+        }
+
+    k = latest("10-K")
+    q = latest("10-Q")
+    rec["latest_10k"] = k
+    rec["latest_10q"] = q
+
+    # Staleness: date-based on the 10-K's period_end (fallback filing_date), NOT fy age.
+    ref = None
+    if k:
+        ref = _parse_date(k.get("period_end")) or _parse_date(k.get("filing_date"))
+    if ref is None:
+        rec["staleness"] = {"is_stale": True, "reason": "no_10k_found"}
+        return
+    age = (datetime.now(timezone.utc).date() - ref).days
+    if age > STALE_DAYS:
+        rec["staleness"] = {"is_stale": True, "reason": f"latest 10-K period_end {ref} is {age}d old (> {STALE_DAYS})"}
+    else:
+        rec["staleness"] = {"is_stale": False, "reason": f"latest 10-K period_end {ref} ({age}d old)"}
+
+
+def _populate_notes(rec: dict, company) -> None:
+    """Read 10-K note bodies. Distinguish present / not_disclosed / fetch_failed PER NOTE.
+
+    The whole false-Green guard hinges on this: we only mark a note `fetch_failed` when the
+    READ itself errored. If the filing was readable but the topic simply isn't there, that's
+    `not_disclosed` (a legitimate absence, not a data gap).
+    """
+    filing = None
+    try:
+        tenk = company.get_filings(form="10-K")
+        filing = tenk.latest() if tenk else None
+    except Exception as exc:  # noqa: BLE001
+        # Could not even load the 10-K -> EVERY note is fetch_failed (blocks the note families).
+        for topic in NOTE_TOPICS:
+            rec["notes"][topic] = {"status": "fetch_failed", "text": ""}
+        rec["source_errors"].append({"source": "edgartools:10k-load", "error": f"{type(exc).__name__}: {exc}"[:200]})
+        return
+
+    if filing is None:
+        for topic in NOTE_TOPICS:
+            rec["notes"][topic] = {"status": "not_disclosed", "text": ""}  # no 10-K -> nothing disclosed there
+        return
+
+    # Pull the full text once; topic search is substring-on-text (best-effort).
+    full_text = None
+    try:
+        obj = filing.obj() if hasattr(filing, "obj") else None
+        full_text = (obj.text() if obj is not None and hasattr(obj, "text") else None)
+        if full_text is None:
+            full_text = filing.text() if hasattr(filing, "text") else None
+    except Exception:  # noqa: BLE001
+        full_text = None
+
+    if not full_text:
+        # The filing handle exists but body unreadable -> a genuine FETCH FAILURE.
+        for topic in NOTE_TOPICS:
+            rec["notes"][topic] = {"status": "fetch_failed", "text": ""}
+        rec["source_errors"].append({"source": "edgartools:10k-text", "error": "empty filing body"})
+        return
+
+    low = full_text.lower()
+    for topic, keys in NOTE_TOPICS.items():
+        hit_idx = -1
+        for kw in keys:
+            idx = low.find(kw)
+            if idx != -1:
+                hit_idx = idx
+                break
+        if hit_idx == -1:
+            rec["notes"][topic] = {"status": "not_disclosed", "text": ""}
+        else:
+            excerpt = full_text[hit_idx: hit_idx + 1500]
+            rec["notes"][topic] = {"status": "present", "text": excerpt}
+
+
+def _populate_insider(rec: dict, company) -> None:
+    try:
+        forms = company.get_filings(form="4")
+    except Exception:  # noqa: BLE001
+        forms = None
+    if not forms:
+        rec["insider"] = {"clusters": [], "status": "not_evaluated"}
+        return
+    try:
+        recent = forms.head(20) if hasattr(forms, "head") else forms[:20]
+        dates = [str(getattr(f, "filing_date", "")) for f in recent]
+    except Exception:  # noqa: BLE001
+        rec["insider"] = {"clusters": [], "status": "not_evaluated"}
+        return
+    rec["insider"] = {"clusters": [], "recent_form4_dates": dates, "status": "present"}
+
+
+def _edgartools_statements(company) -> list:
+    """Fallback statements via companyfacts/financials when REST is down."""
+    try:
+        fin = company.financials if hasattr(company, "financials") else None
+    except Exception:  # noqa: BLE001
+        fin = None
+    if fin is None:
+        return []
+    # We keep this minimal: presence of a financials object is enough for coverage to be
+    # non-unavailable; the detailed line-item extraction is best-effort and tolerant.
+    return [{"period": "latest", "source": "edgartools_financials"}]
+
+
+def _edgartools_events(company) -> list:
+    """Fallback 8-K item-code feed via edgartools, so a REST outage can't hide a 4.02."""
+    out: list[dict] = []
+    try:
+        eights = company.get_filings(form="8-K")
+    except Exception:  # noqa: BLE001
+        return []
+    if not eights:
+        return []
+    try:
+        recent = eights.head(25) if hasattr(eights, "head") else eights[:25]
+    except Exception:  # noqa: BLE001
+        recent = eights
+    for f in recent:
+        items = getattr(f, "items", None) or []
+        if isinstance(items, str):
+            items = [i.strip() for i in items.replace(";", ",").split(",") if i.strip()]
+        out.append({
+            "date": str(getattr(f, "filing_date", "") or ""),
+            "items": [str(i) for i in items],
+            "body_excerpt": "",
+        })
+    return out
+
+
+def _derive_corporate_action(rec: dict) -> None:
+    """Set governance / corporate-action hints from the 8-K item codes (deterministic facts;
+    Claude still judges severity, but the codes themselves are read here)."""
+    corp_kind = None
+    for ev in rec["events_8k"]:
+        items = set(ev.get("items", []))
+        if items & CORP_ACTION_8K_ITEMS:
+            corp_kind = sorted(items & CORP_ACTION_8K_ITEMS)[0]
+    if corp_kind:
+        rec["corporate_action"] = {"detected": True, "kind": f"8-K item {corp_kind}"}
+
+
+# --------------------------------------------------------------------------------------
+# watchlist lookup + persistence
+# --------------------------------------------------------------------------------------
+def _lookup_watchlist(ticker: str) -> dict | None:
+    if not WATCHLIST_CSV.exists():
+        return None
+    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
+        for row in csv.DictReader(f):
+            if (row.get("ticker") or "").strip().upper() == ticker.upper():
+                return row
+    return None
+
+
+def write_record(rec: dict, out_dir: Path) -> Path:
+    out_dir.mkdir(parents=True, exist_ok=True)
+    path = out_dir / f"{rec['ticker']}.json"
+    tmp = out_dir / f".{rec['ticker']}.json.tmp"
+    with tmp.open("w", encoding="utf-8") as f:
+        json.dump(rec, f, indent=2, sort_keys=False)
+    tmp.replace(path)
+    return path
+
+
+def main(argv=None) -> int:
+    p = argparse.ArgumentParser(description=__doc__)
+    p.add_argument("ticker")
+    p.add_argument("--cik", default=None, help="10-digit CIK (else looked up from watchlist.csv)")
+    p.add_argument("--subgroup", default=None)
+    p.add_argument("--filer-type", default=None)
+    p.add_argument("--run-id", default="manual")
+    p.add_argument("--out", default=str(DEFAULT_OUT_DIR))
+    args = p.parse_args(argv)
+
+    ticker = args.ticker.strip().upper()
+    row = _lookup_watchlist(ticker) or {}
+    cik = (args.cik or row.get("cik") or "").strip()
+    subgroup = args.subgroup or row.get("sector_subgroup") or "general"
+    filer_type = args.filer_type or row.get("filer_type") or "domestic"
+
+    if not cik and filer_type != "foreign":
+        # No CIK and not a known-foreign skip -> we cannot fetch. Emit a fetch-failed record
+        # (never crash) so the caller sees a transient failure, not a false Data Gap.
+        rec = _empty_record(ticker, "", args.run_id)
+        rec["filer_type"] = filer_type
+        rec["source_errors"].append({"source": "watchlist", "error": "no CIK found for ticker"})
+        path = write_record(rec, Path(args.out))
+        print(f"WROTE {path} (NO CIK -- fetch_failed; not green-eligible)")
+        return 0
+
+    # The fetch itself never raises; this top-level guard is belt-and-suspenders only.
+    try:
+        rec = fetch_ticker(ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=args.run_id)
+    except Exception as exc:  # noqa: BLE001
+        rec = _empty_record(ticker, cik, args.run_id)
+        rec["filer_type"] = filer_type
+        rec["source_errors"].append({"source": "fetch_ticker", "error": f"{type(exc).__name__}: {exc}"})
+        rec["source_errors"].append({"source": "traceback", "error": traceback.format_exc()[:400]})
+
+    path = write_record(rec, Path(args.out))
+    cov = rec["family_coverage"]
+    print(f"WROTE {path}  filer={rec['filer_type']}  "
+          f"required_complete={rec['required_families_complete']}  "
+          f"errors={len(rec['source_errors'])}")
+    print("  coverage:", ", ".join(f"{k}={cov[k]}" for k in FAMILIES))
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff --git a/next_batch.py b/next_batch.py
index da6dfc9..518dbc2 100644
--- a/next_batch.py
+++ b/next_batch.py
@@ -9,9 +9,12 @@ what to screen, prioritised toward JP's coverage:
   3. then alphabetical
 
 A name is "done this cycle" once it has a flags_history row dated >= CYCLE_START
-(the recalibration baseline). Foreign filers (filer_type=foreign) are never
-screened by EDGAR — they belong to the Data Gap tier — so they're excluded here
-and reported separately.
+(the recalibration baseline) WITH status=complete (codex R2 idempotency). A row
+written by a transient fetch failure (status=fetch_failed) does NOT mark the name
+done — it retries next run. A structural Data Gap (foreign/stale/not-disclosed) is
+written status=complete and IS done. Older rows without a status column are treated
+as complete (back-compat). Foreign filers (filer_type=foreign) are never screened by
+EDGAR — they belong to the Data Gap tier — so they're excluded here and reported separately.
 
 Usage:
   python next_batch.py            # show the next batch (default 8) + progress
@@ -41,12 +44,21 @@ def load_watchlist() -> list[dict]:
 
 
 def screened_since(cycle_start: str) -> set[str]:
+    """Tickers DONE this cycle: a flags_history row dated >= cycle_start with status=complete.
+
+    A `status=fetch_failed` row does NOT count as done (transient failure retries next run).
+    Rows without a `status` column (legacy interactive runs) are treated as complete."""
     if not FLAGS_HISTORY_CSV.exists():
         return set()
     done: set[str] = set()
     with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
-        for row in csv.DictReader(f):
-            if (row.get("run_date") or "") >= cycle_start and row.get("ticker"):
+        reader = csv.DictReader(f)
+        has_status = "status" in (reader.fieldnames or [])
+        for row in reader:
+            if (row.get("run_date") or "") < cycle_start or not row.get("ticker"):
+                continue
+            status = (row.get("status") or "").strip() if has_status else "complete"
+            if status in ("", "complete"):
                 done.add(row["ticker"].strip())
     return done
 
diff --git a/notify.py b/notify.py
new file mode 100644
index 0000000..d17aae0
--- /dev/null
+++ b/notify.py
@@ -0,0 +1,169 @@
+"""Slack notifications for the unattended forensic screen (Path A).
+
+Two destinations:
+  - #forensic-flags  (SLACK_WEBHOOK_FORENSIC)        — the screen results, Block Kit.
+  - #status-reports  (SLACK_WEBHOOK_STATUS_REPORTS)  — a v1 health heartbeat.
+
+Block Kit GOTCHA (memory: reference_slack_context_block_elements): a `context` block uses
+`elements[]`, NOT a `text` field — a `text` field there => webhook HTTP 400 invalid_blocks.
+This module only ever builds context blocks with `elements[]`.
+
+Webhook URLs come from the environment; NO hardcoded secrets, and we never log a URL.
+"""
+from __future__ import annotations
+
+import json
+import os
+import urllib.error
+import urllib.request
+
+FORENSIC_ENV = "SLACK_WEBHOOK_FORENSIC"
+STATUS_ENV = "SLACK_WEBHOOK_STATUS_REPORTS"
+
+TIER_EMOJI = {
+    "Red": ":red_circle:",
+    "Yellow": ":large_yellow_circle:",
+    "Green": ":large_green_circle:",
+    "DataGap": ":black_circle:",
+    "CorporateAction": ":arrows_counterclockwise:",
+}
+
+
+def _post(webhook_url: str, payload: dict, *, timeout: int = 15) -> tuple[bool, str]:
+    """POST a Block Kit payload. Returns (ok, detail). NEVER raises, NEVER logs the URL."""
+    if not webhook_url:
+        return False, "no webhook url configured"
+    data = json.dumps(payload).encode("utf-8")
+    req = urllib.request.Request(
+        webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST"
+    )
+    try:
+        with urllib.request.urlopen(req, timeout=timeout) as resp:
+            body = resp.read().decode("utf-8", "replace")
+            return (resp.status == 200, f"HTTP {resp.status}: {body[:200]}")
+    except urllib.error.HTTPError as exc:
+        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
+    except Exception as exc:  # noqa: BLE001 — never let a Slack failure crash the run
+        return False, f"{type(exc).__name__}: {exc}"
+
+
+def _context(*lines: str) -> dict:
+    """A context block — ALWAYS elements[] (never a top-level text field)."""
+    return {"type": "context", "elements": [{"type": "mrkdwn", "text": line} for line in lines]}
+
+
+# --------------------------------------------------------------------------------------
+# #forensic-flags result card
+# --------------------------------------------------------------------------------------
+def build_forensic_blocks(results: list[dict], *, run_id: str, run_date: str, commit: str = "") -> list[dict]:
+    counts: dict[str, int] = {}
+    for r in results:
+        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
+    summary = "  ".join(f"{TIER_EMOJI.get(t, '')} {t}: {counts.get(t, 0)}" for t in
+                        ("Red", "Yellow", "Green", "DataGap", "CorporateAction"))
+
+    blocks: list[dict] = [
+        {"type": "header", "text": {"type": "plain_text", "text": f"Forensic Triage — {run_date}"}},
+        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
+    ]
+
+    def section_for(tier: str, title: str):
+        names = [r for r in results if r["tier"] == tier]
+        if not names:
+            return
+        blocks.append({"type": "divider"})
+        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}})
+        for r in names:
+            fired = [f for f in r["flags"] if r["flags"].get(f)]
+            line = f"• *{r['ticker']}* ({r['subgroup']}) — {r.get('reason', '')}"
+            if fired:
+                line += f"\n   flags: {', '.join(fired)}"
+            concerns = r.get("concerns") or []
+            if concerns:
+                line += "\n   " + "; ".join(c for c in concerns[:3])
+            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line[:2900]}})
+
+    section_for("Red", "Red — deep dive")
+    section_for("Yellow", "Yellow — watch")
+    section_for("DataGap", "Data Gap — manual review (NOT screened)")
+    section_for("CorporateAction", "Corporate Action — flag for removal")
+    # Green names listed compactly (no per-name section).
+    greens = [r["ticker"] for r in results if r["tier"] == "Green"]
+    if greens:
+        blocks.append({"type": "divider"})
+        blocks.append(_context(f"Green ({len(greens)}): " + ", ".join(greens)))
+
+    foot = f"run_id `{run_id}`"
+    if commit:
+        foot += f" · commit `{commit[:8]}`"
+    blocks.append(_context(foot))
+    return blocks
+
+
+def post_forensic(results: list[dict], *, run_id: str, run_date: str, commit: str = "",
+                  webhook_url: str | None = None) -> tuple[bool, str]:
+    url = webhook_url if webhook_url is not None else os.environ.get(FORENSIC_ENV, "")
+    blocks = build_forensic_blocks(results, run_id=run_id, run_date=run_date, commit=commit)
+    return _post(url, {"blocks": blocks})
+
+
+# --------------------------------------------------------------------------------------
+# #status-reports heartbeat (v1; Block Kit, context uses elements[])
+# --------------------------------------------------------------------------------------
+def build_heartbeat_blocks(*, run_id: str, run_date: str, n_screened: int, counts: dict,
+                           missing_required: int, commit: str = "", ok: bool = True,
+                           note: str = "") -> list[dict]:
+    status = ":white_check_mark: healthy" if ok else ":rotating_light: FAILED"
+    tier_line = "  ".join(f"{t}: {counts.get(t, 0)}" for t in
+                          ("Red", "Yellow", "Green", "DataGap", "CorporateAction"))
+    lines = [
+        f"*forensic_triage* — {status}",
+        f"{run_date} · run_id `{run_id}` · screened {n_screened}",
+        tier_line,
+        f"missing-required-family names: {missing_required}",
+    ]
+    if commit:
+        lines.append(f"commit `{commit[:8]}`")
+    if note:
+        lines.append(note)
+    return [
+        {"type": "section", "text": {"type": "mrkdwn", "text": "*Forensic Triage heartbeat*"}},
+        _context(*lines),
+    ]
+
+
+def post_heartbeat(*, run_id: str, run_date: str, n_screened: int, counts: dict,
+                   missing_required: int, commit: str = "", ok: bool = True, note: str = "",
+                   webhook_url: str | None = None) -> tuple[bool, str]:
+    url = webhook_url if webhook_url is not None else os.environ.get(STATUS_ENV, "")
+    blocks = build_heartbeat_blocks(
+        run_id=run_id, run_date=run_date, n_screened=n_screened, counts=counts,
+        missing_required=missing_required, commit=commit, ok=ok, note=note,
+    )
+    return _post(url, {"blocks": blocks})
+
+
+def post_failure_alarm(*, run_id: str, run_date: str, error: str,
+                       webhook_url: str | None = None) -> tuple[bool, str]:
+    """Loud failure alarm to #status-reports (the if: failure() path)."""
+    url = webhook_url if webhook_url is not None else os.environ.get(STATUS_ENV, "")
+    blocks = [
+        {"type": "section", "text": {"type": "mrkdwn", "text": ":rotating_light: *forensic_triage run FAILED*"}},
+        _context(f"{run_date} · run_id `{run_id}`", f"error: {error[:400]}"),
+    ]
+    return _post(url, {"blocks": blocks})
+
+
+if __name__ == "__main__":  # pragma: no cover — manual smoke (prints blocks, posts nothing)
+    import argparse
+
+    ap = argparse.ArgumentParser(description="Print the Block Kit payloads (no Slack post).")
+    ap.add_argument("--demo", action="store_true")
+    ap.parse_args()
+    demo = [
+        {"ticker": "ACME", "subgroup": "hc_services", "tier": "Red", "reason": "critical governance (auto-Red)",
+         "flags": {f: 0 for f in __import__("forensic_schema").FAMILIES}, "concerns": ["8-K 4.02 non-reliance filed 2026-05"]},
+    ]
+    print(json.dumps({"blocks": build_forensic_blocks(demo, run_id="demo", run_date="2026-06-24")}, indent=2))
+    print(json.dumps({"blocks": build_heartbeat_blocks(run_id="demo", run_date="2026-06-24",
+          n_screened=1, counts={"Red": 1}, missing_required=0)}, indent=2))
diff --git a/run_unattended.py b/run_unattended.py
new file mode 100644
index 0000000..0cd6f4d
--- /dev/null
+++ b/run_unattended.py
@@ -0,0 +1,249 @@
+"""Per-run orchestrator for the unattended (Path A) forensic screen.
+
+Ties the pipeline together (PATH_A_PLAN step 5):
+  next_batch  ->  edgar_fetch (per ticker)  ->  tier_batch (Anthropic judge + guardrails)
+              ->  append flags_history       ->  write a compact report
+              ->  (separately) notify Slack.
+
+The git commit/push happens in the WORKFLOW between the screen step and the notify step (so the
+commit hash is known); this script writes a small `data/last_run.json` the notify step reads for
+the commit + results. The script NEVER spends API budget when run with --notify-only / --failure-alarm.
+
+Modes:
+  (default)         run the screen: fetch + tier + history + report, write last_run.json
+  --notify-only     read last_run.json + post #forensic-flags result + #status-reports heartbeat
+  --failure-alarm   post a loud failure alarm to #status-reports (the if: failure() path)
+
+Run-level circuit breaker: if the batch can't be evaluated (broad outage), exit non-zero so the
+workflow's `if: failure()` alarm fires and NO batch of false Data Gaps is committed.
+"""
+from __future__ import annotations
+
+import argparse
+import json
+import os
+import subprocess
+import sys
+from datetime import date
+from pathlib import Path
+
+ROOT = Path(__file__).parent
+sys.path.insert(0, str(ROOT))
+
+import edgar_fetch  # noqa: E402
+import notify  # noqa: E402
+import tier_batch  # noqa: E402
+from forensic_schema import FAMILIES  # noqa: E402
+
+DATA = ROOT / "data"
+REPORTS = ROOT / "reports"
+LAST_RUN = DATA / "last_run.json"
+WATCHLIST = DATA / "watchlist.csv"
+DEFAULT_CYCLE_START = "2026-06-20"
+
+
+def _load_watchlist() -> dict[str, dict]:
+    import csv
+    out = {}
+    if WATCHLIST.exists():
+        with WATCHLIST.open(encoding="utf-8", newline="") as f:
+            for row in csv.DictReader(f):
+                out[(row.get("ticker") or "").upper()] = row
+    return out
+
+
+def _pick_batch(n: int, cycle_start: str) -> list[str]:
+    """Next n un-screened domestic names (reuse next_batch's selection logic)."""
+    import next_batch as nb
+    watch = nb.load_watchlist()
+    domestic = [r for r in watch if r.get("filer_type", "domestic") != "foreign"]
+    done = nb.screened_since(cycle_start)
+    pending = [r for r in domestic if r["ticker"].strip() not in done]
+    pending.sort(key=nb.sort_key)
+    return [r["ticker"].strip().upper() for r in pending[:n]]
+
+
+def run_screen(*, batch_size: int, run_id: str, cycle_start: str) -> int:
+    wl = _load_watchlist()
+    tickers = _pick_batch(batch_size, cycle_start)
+    if not tickers:
+        print("Cycle complete — no pending domestic names. Nothing to screen.")
+        _write_last_run(run_id=run_id, results=[], note="cycle complete (no pending names)")
+        return 0
+
+    print(f"Run {run_id}: screening {len(tickers)} names: {', '.join(tickers)}")
+    new_set = tier_batch._new_names()
+
+    results = []
+    for ticker in tickers:
+        row = wl.get(ticker, {})
+        cik = (row.get("cik") or "").strip()
+        subgroup = row.get("sector_subgroup") or "general"
+        filer_type = row.get("filer_type") or "domestic"
+
+        # 1. fetch (never raises)
+        rec = edgar_fetch.fetch_ticker(
+            ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=run_id,
+        )
+        edgar_fetch.write_record(rec, edgar_fetch.DEFAULT_OUT_DIR)
+
+        # 2. tier (Anthropic judge + deterministic guardrails)
+        res = tier_batch.tier_one(rec, subgroup=subgroup, is_new=(ticker in new_set))
+        results.append(res)
+        print(f"  {ticker:<6} {res['tier']:<16} status={res['status']}  {res['reason']}")
+
+    # 3. run-level circuit breaker (broad outage -> fail loudly, commit nothing)
+    tripped, why = tier_batch.circuit_breaker_tripped(results)
+    if tripped:
+        print(f"\nCIRCUIT BREAKER TRIPPED: {why}")
+        _write_last_run(run_id=run_id, results=results, note=f"CIRCUIT BREAKER: {why}", ok=False)
+        # Non-zero exit so the workflow alarms and skips the commit.
+        return 2
+
+    # 4. append history (only complete + fetch_failed rows; fetch_failed retries next run)
+    rows = [tier_batch.result_to_history_row(r, run_id=run_id) for r in results]
+    tier_batch.append_history(rows)
+
+    # 5. compact report
+    report_path = _write_report(results, run_id=run_id)
+    print(f"\nWrote report {report_path}; appended {len(rows)} history rows.")
+
+    _write_last_run(run_id=run_id, results=results, note="ok", ok=True)
+    return 0
+
+
+def _counts(results: list[dict]) -> dict:
+    c: dict[str, int] = {}
+    for r in results:
+        c[r["tier"]] = c.get(r["tier"], 0) + 1
+    return c
+
+
+def _missing_required(results: list[dict]) -> int:
+    n = 0
+    for r in results:
+        cov = r.get("coverage", {})
+        if any(cov.get(f) not in ("complete", "not_applicable", None) for f in FAMILIES):
+            # any non-complete required-ish family -> count as a name with a coverage gap
+            from forensic_schema import required_families
+            sg = r.get("subgroup", "general")
+            if any(cov.get(f, "unavailable") not in ("complete", "not_applicable")
+                   for f in required_families(sg)):
+                n += 1
+    return n
+
+
+def _write_report(results: list[dict], *, run_id: str) -> Path:
+    REPORTS.mkdir(parents=True, exist_ok=True)
+    today = date.today().isoformat()
+    path = REPORTS / f"forensic_{today}.md"
+    lines = [f"# Forensic Triage — {today}", "", f"_run_id {run_id}_", ""]
+
+    def section(tier: str, title: str):
+        names = [r for r in results if r["tier"] == tier]
+        if not names:
+            return
+        lines.append(f"## {title}")
+        lines.append("| Ticker | Subgroup | Flags fired | Reason | Concerns |")
+        lines.append("|---|---|---|---|---|")
+        for r in names:
+            fired = ", ".join(f for f in r["flags"] if r["flags"].get(f)) or "-"
+            concerns = "; ".join((r.get("concerns") or [])[:3]).replace("|", "/")
+            lines.append(f"| {r['ticker']} | {r['subgroup']} | {fired} | {r['reason']} | {concerns} |")
+        lines.append("")
+
+    section("Red", "Red (deep dive)")
+    section("Yellow", "Yellow (watch)")
+    section("DataGap", "Data Gap (manual review — NOT screened)")
+    section("CorporateAction", "Corporate Action (flag for removal)")
+    greens = [r["ticker"] for r in results if r["tier"] == "Green"]
+    if greens:
+        lines.append(f"## Green (evaluated clean)\n\n{', '.join(greens)}\n")
+    # Append (don't overwrite a same-day earlier run)
+    mode = "a" if path.exists() else "w"
+    with path.open(mode, encoding="utf-8") as f:
+        if mode == "a":
+            f.write("\n\n---\n\n")
+        f.write("\n".join(lines))
+    return path
+
+
+def _write_last_run(*, run_id: str, results: list[dict], note: str = "", ok: bool = True) -> None:
+    DATA.mkdir(parents=True, exist_ok=True)
+    # Strip the bulky coverage map down for the notify payload; keep what the cards need.
+    slim = [
+        {
+            "ticker": r["ticker"], "subgroup": r["subgroup"], "tier": r["tier"],
+            "reason": r["reason"], "flags": r["flags"], "concerns": r.get("concerns", []),
+            "status": r.get("status", "complete"), "coverage": r.get("coverage", {}),
+        }
+        for r in results
+    ]
+    payload = {
+        "run_id": run_id, "run_date": date.today().isoformat(),
+        "ok": ok, "note": note, "results": slim,
+    }
+    with LAST_RUN.open("w", encoding="utf-8") as f:
+        json.dump(payload, f, indent=2)
+
+
+def _read_last_run() -> dict:
+    if not LAST_RUN.exists():
+        return {}
+    with LAST_RUN.open(encoding="utf-8") as f:
+        return json.load(f)
+
+
+def _git_head() -> str:
+    try:
+        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
+    except Exception:  # noqa: BLE001
+        return ""
+
+
+def notify_only(*, run_id: str) -> int:
+    data = _read_last_run()
+    results = data.get("results", [])
+    run_date = data.get("run_date", date.today().isoformat())
+    commit = _git_head()
+
+    ok_f, det_f = notify.post_forensic(results, run_id=run_id, run_date=run_date, commit=commit)
+    counts = _counts(results)
+    missing = _missing_required(results)
+    ok_h, det_h = notify.post_heartbeat(
+        run_id=run_id, run_date=run_date, n_screened=len(results), counts=counts,
+        missing_required=missing, commit=commit, ok=data.get("ok", True), note=data.get("note", ""),
+    )
+    print(f"forensic post: ok={ok_f} {det_f}")
+    print(f"heartbeat post: ok={ok_h} {det_h}")
+    # Don't fail the workflow if Slack is flaky — the data is already committed.
+    return 0
+
+
+def failure_alarm(*, run_id: str, error: str) -> int:
+    ok, det = notify.post_failure_alarm(
+        run_id=run_id, run_date=date.today().isoformat(), error=error,
+    )
+    print(f"failure alarm: ok={ok} {det}")
+    return 0
+
+
+def main(argv=None) -> int:
+    p = argparse.ArgumentParser(description=__doc__)
+    p.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "6")))
+    p.add_argument("--run-id", default="manual")
+    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START)
+    p.add_argument("--notify-only", action="store_true")
+    p.add_argument("--failure-alarm", action="store_true")
+    p.add_argument("--error", default="run failed")
+    args = p.parse_args(argv)
+
+    if args.notify_only:
+        return notify_only(run_id=args.run_id)
+    if args.failure_alarm:
+        return failure_alarm(run_id=args.run_id, error=args.error)
+    return run_screen(batch_size=args.batch_size, run_id=args.run_id, cycle_start=args.cycle_start)
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff --git a/tier_batch.py b/tier_batch.py
new file mode 100644
index 0000000..d364964
--- /dev/null
+++ b/tier_batch.py
@@ -0,0 +1,505 @@
+"""Tiering = Anthropic-API per-family judgment + deterministic guardrails (Path A).
+
+Pipeline per ticker (PATH_A_PLAN step 5):
+  1. Read rubrics/*.md + the fetched JSON (edgar_fetch.py output).
+  2. Ask Claude (model `claude-fable-5`, MODEL_POLICY: Fable 5 for forensic_triage) for
+     STRUCTURED per-family flags + concerns + governance/severity/corporate-action signals.
+     Claude does NOT emit the final tier (codex R2): it judges families, code decides tier.
+  3. Validate Claude's structured output (fail-closed: reject/retry on malformed; if it stays
+     malformed, treat as a fetch-style failure, NOT a clean Green).
+  4. Apply the DETERMINISTIC guardrails + precedence + Green-eligibility gate from
+     forensic_tier.finalize_tier(), using the COVERAGE map from the fetched JSON.
+  5. Run-level circuit breaker: if too many names fail to fetch / lack required coverage,
+     FAIL the run loudly (caller alarms #status-reports) rather than commit false Data Gaps.
+
+This module is import-safe without `anthropic` installed (the import is lazy) so the tests can
+exercise the guardrails + validation with a MOCK judge and never spend API budget.
+"""
+from __future__ import annotations
+
+import argparse
+import csv
+import json
+import os
+from datetime import date
+from pathlib import Path
+
+from forensic_schema import (
+    COVERAGE,
+    FAMILIES,
+    HISTORY_COLUMNS,
+    SCHEMA_VERSION,
+    required_families,
+)
+from forensic_tier import finalize_tier
+
+ROOT = Path(__file__).parent
+RUBRICS_DIR = ROOT / "rubrics"
+FETCHED_DIR = ROOT / "data" / "fetched"
+FLAGS_HISTORY_CSV = ROOT / "data" / "flags_history.csv"
+
+MODEL_ID = "claude-fable-5"  # MODEL_POLICY: Fable 5 for forensic_triage
+FALLBACK_MODEL = "claude-opus-4-8"
+MAX_VALIDATION_RETRIES = 2
+
+# Run-level circuit breaker: if more than this FRACTION of the batch could not be evaluated
+# (fetch failure or required coverage missing), the run is presumed to be hitting a broad
+# SEC/REST/Anthropic outage. Fail loudly rather than commit a batch of false Data Gaps.
+CIRCUIT_BREAKER_FRACTION = 0.5
+CIRCUIT_BREAKER_MIN_BATCH = 3  # don't trip on 1-2 name batches
+
+RUBRIC_FILES = {
+    "general": "general.md",
+    "hc_services": "healthcare_services.md",
+    "medtech": "medtech.md",
+}
+
+# JSON schema Claude must satisfy. Claude emits per-family flags + concerns + the
+# governance/severity/corporate-action SIGNALS — NOT the final tier.
+JUDGE_SCHEMA = {
+    "type": "object",
+    "additionalProperties": False,
+    "properties": {
+        "ticker": {"type": "string"},
+        "flags": {
+            "type": "object",
+            "additionalProperties": False,
+            "properties": {f: {"type": "integer", "enum": [0, 1]} for f in FAMILIES},
+            "required": list(FAMILIES),
+        },
+        "critical_governance": {"type": "boolean"},
+        "high_severity": {"type": "boolean"},
+        "corporate_action": {"type": ["string", "null"]},
+        "concerns": {"type": "array", "items": {"type": "string"}},
+        "flag_details": {"type": "string"},
+    },
+    "required": [
+        "ticker", "flags", "critical_governance", "high_severity",
+        "corporate_action", "concerns", "flag_details",
+    ],
+}
+
+SYSTEM_PROMPT = """You are a forensic-accounting analyst applying a fixed rubric to one company.
+Today's date is {today}.
+
+You are given: (1) the general forensic rubric, (2) the matching sector rubric, and (3) a JSON
+record of fetched EDGAR data for ONE ticker (statements, ratios, 10-K note bodies, 8-K item codes,
+insider activity, and a per-family data-coverage map).
+
+Decide, FOR EACH of these nine flag families, whether it FIRED (1) or not (0):
+  accruals, revenue, capex, balance_sheet, leverage, governance, market, text, sector.
+
+A family fires ONLY when the rubric's combination rules trigger — single noisy ratios do not fire.
+Honor the rubric's calibration notes and exclusions exactly (e.g. the CFO/NI materiality floor, the
+goodwill double-count rule, soft-vs-critical governance).
+
+CRITICAL RULES:
+- You do NOT assign the final tier. You only judge per-family flags and signals; code computes the tier.
+- If a family's data coverage is `unavailable`/`partial`/`not_evaluated`, you may STILL set its flag to 1
+  if a present signal clearly fires it, but DO NOT invent a flag from absent data — absence is not a flag.
+- `critical_governance` = true ONLY for a genuine 8-K Item 4.02 / restatement / auditor-resignation-with-
+  disagreement / NT late-filing in the data (general.md 6a). Routine churn (6b) is NOT critical.
+- `high_severity` = true for a single high-severity accounting family (revenue/inventory collapse, fresh
+  FCA/qui-tam) per the Yellow rule.
+- `corporate_action` = a short string (e.g. "8-K item 5.01 take-private") ONLY for a non-accounting
+  structural exit (merger/take-private/delisting); else null.
+- `concerns` = short, specific bullet strings a human can act on (quote the note language when present).
+
+Return ONLY the structured object."""
+
+
+# --------------------------------------------------------------------------------------
+# rubric + record loading
+# --------------------------------------------------------------------------------------
+def load_rubric(subgroup: str) -> str:
+    parts = []
+    gen = RUBRICS_DIR / RUBRIC_FILES["general"]
+    if gen.exists():
+        parts.append(f"# GENERAL RUBRIC\n\n{gen.read_text(encoding='utf-8')}")
+    sector_file = RUBRIC_FILES.get(subgroup)
+    if sector_file and subgroup != "general":
+        sp = RUBRICS_DIR / sector_file
+        if sp.exists():
+            parts.append(f"# SECTOR RUBRIC ({subgroup})\n\n{sp.read_text(encoding='utf-8')}")
+    return "\n\n---\n\n".join(parts)
+
+
+def load_record(ticker: str) -> dict:
+    path = FETCHED_DIR / f"{ticker}.json"
+    with path.open(encoding="utf-8") as f:
+        return json.load(f)
+
+
+# --------------------------------------------------------------------------------------
+# structured-output validation (fail-closed)
+# --------------------------------------------------------------------------------------
+class JudgeValidationError(Exception):
+    """Claude's structured output didn't satisfy the contract."""
+
+
+def validate_judge_output(obj, ticker: str) -> dict:
+    """Strictly validate Claude's structured output. Raise JudgeValidationError on any deviation.
+
+    Fail-closed: a malformed judge response must NOT be silently coerced into a clean Green.
+    """
+    if not isinstance(obj, dict):
+        raise JudgeValidationError("judge output is not an object")
+    flags = obj.get("flags")
+    if not isinstance(flags, dict):
+        raise JudgeValidationError("flags missing or not an object")
+    clean_flags = {}
+    for fam in FAMILIES:
+        v = flags.get(fam)
+        if v not in (0, 1):
+            raise JudgeValidationError(f"flag '{fam}' is not 0/1 (got {v!r})")
+        clean_flags[fam] = int(v)
+    for key in ("critical_governance", "high_severity"):
+        if not isinstance(obj.get(key), bool):
+            raise JudgeValidationError(f"'{key}' is not a boolean")
+    ca = obj.get("corporate_action")
+    if ca is not None and not isinstance(ca, str):
+        raise JudgeValidationError("'corporate_action' is not str|null")
+    concerns = obj.get("concerns")
+    if not isinstance(concerns, list) or not all(isinstance(c, str) for c in concerns):
+        raise JudgeValidationError("'concerns' is not a list[str]")
+    return {
+        "ticker": str(obj.get("ticker") or ticker),
+        "flags": clean_flags,
+        "critical_governance": bool(obj["critical_governance"]),
+        "high_severity": bool(obj["high_severity"]),
+        "corporate_action": ca,
+        "concerns": concerns,
+        "flag_details": str(obj.get("flag_details") or ""),
+    }
+
+
+# --------------------------------------------------------------------------------------
+# the Anthropic judge (lazy import; mockable)
+# --------------------------------------------------------------------------------------
+def _extract_json_text(response) -> str:
+    """Pull the first text block out of an Anthropic response object."""
+    for block in getattr(response, "content", []) or []:
+        if getattr(block, "type", None) == "text":
+            return block.text
+    raise JudgeValidationError("no text block in model response")
+
+
+def call_judge(rubric: str, record: dict, *, client=None, model: str = MODEL_ID) -> dict:
+    """Call Claude for the structured per-family judgment. Returns the VALIDATED dict.
+
+    `client` is injectable for tests (a mock with .messages.create). In production it's an
+    anthropic.Anthropic() built lazily so importing this module never requires the package.
+    Fail-closed: after MAX_VALIDATION_RETRIES malformed responses, raise JudgeValidationError
+    (the caller treats that as 'could not evaluate', NEVER as a clean Green).
+    """
+    if client is None:
+        import anthropic  # lazy
+        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
+
+    ticker = record.get("ticker", "?")
+    system = SYSTEM_PROMPT.format(today=date.today().isoformat())
+    user = (
+        f"{rubric}\n\n---\n\n# FETCHED DATA FOR {ticker}\n\n"
+        f"```json\n{json.dumps(record, indent=2, default=str)[:120000]}\n```\n\n"
+        "Apply the rubric and return the structured per-family judgment."
+    )
+
+    # Fable 5: no `thinking` param (always-on), no sampling params; structured output via
+    # output_config.format; effort low (deterministic, schema-constrained classification);
+    # server-side fallbacks opt-in by default so a refusal doesn't fail the run.
+    base_kwargs = dict(
+        model=model,
+        max_tokens=4000,
+        system=system,
+        messages=[{"role": "user", "content": user}],
+        output_config={
+            "effort": "low",
+            "format": {"type": "json_schema", "schema": JUDGE_SCHEMA},
+        },
+    )
+
+    last_err = None
+    for _ in range(MAX_VALIDATION_RETRIES + 1):
+        response = _create_with_fallback(client, base_kwargs)
+        if getattr(response, "stop_reason", None) == "refusal":
+            raise JudgeValidationError("model refused (stop_reason=refusal)")
+        try:
+            text = _extract_json_text(response)
+            obj = json.loads(text)
+            return validate_judge_output(obj, ticker)
+        except (JudgeValidationError, json.JSONDecodeError, ValueError) as exc:
+            last_err = exc
+            continue
+    raise JudgeValidationError(f"judge output invalid after retries: {last_err}")
+
+
+def _create_with_fallback(client, kwargs: dict):
+    """messages.create with server-side refusal fallback when available, else plain.
+
+    Fallbacks are a beta param; if the SDK/endpoint rejects it we degrade to a plain create
+    (still safe — a refusal is then caught by the stop_reason check upstream).
+    """
+    beta = getattr(client, "beta", None)
+    if beta is not None and hasattr(getattr(beta, "messages", None), "create"):
+        try:
+            return beta.messages.create(
+                betas=["server-side-fallback-2026-06-01"],
+                fallbacks=[{"model": FALLBACK_MODEL}],
+                **kwargs,
+            )
+        except TypeError:
+            pass  # SDK too old for fallbacks/betas kwargs
+        except Exception:
+            pass  # beta endpoint unavailable -> fall through to plain create
+    return client.messages.create(**kwargs)
+
+
+# --------------------------------------------------------------------------------------
+# coverage + tiering glue
+# --------------------------------------------------------------------------------------
+def _coverage_from_record(record: dict, subgroup: str) -> dict:
+    cov = record.get("family_coverage") or {}
+    out = {}
+    for fam in FAMILIES:
+        v = cov.get(fam)
+        out[fam] = v if v in COVERAGE else "unavailable"
+    return out
+
+
+def _required_incomplete(coverage: dict, subgroup: str) -> bool:
+    for fam in required_families(subgroup):
+        if coverage.get(fam, "unavailable") not in ("complete", "not_applicable"):
+            return True
+    return False
+
+
+def tier_one(
+    record: dict,
+    *,
+    subgroup: str | None = None,
+    is_new: bool = False,
+    client=None,
+    judge=None,
+    model: str = MODEL_ID,
+) -> dict:
+    """Tier one fetched record. Returns a result dict (tier, reason, flags, concerns, status).
+
+    `judge` lets tests inject the per-family verdict directly (skipping the API). In production
+    `judge` is None and we call the Anthropic API via call_judge.
+    """
+    subgroup = subgroup or record.get("_subgroup") or _guess_subgroup(record)
+    ticker = record.get("ticker", "?")
+    coverage = _coverage_from_record(record, subgroup)
+
+    # A transient fetch failure (source_errors AND nothing usable) must NOT be finalized as a
+    # clean tier — it's "incomplete this run, retry next run". Foreign/stale = STRUCTURAL gap = done.
+    fetch_failed = _is_transient_fetch_failure(record, coverage, subgroup)
+
+    if judge is None:
+        rubric = load_rubric(subgroup)
+        verdict = call_judge(rubric, record, client=client, model=model)
+    else:
+        verdict = validate_judge_output(judge, ticker)
+
+    tier, reason = finalize_tier(
+        flags=verdict["flags"],
+        coverage=coverage,
+        subgroup=subgroup,
+        critical_governance=verdict["critical_governance"],
+        high_severity=verdict["high_severity"],
+        corporate_action=verdict["corporate_action"],
+        is_new=is_new,
+    )
+
+    # Idempotency status (codex R2): a structural Data Gap (foreign/stale/not-disclosed) IS
+    # complete; a transient fetch failure with no overriding signal is NOT (retry next run).
+    has_signal = verdict["critical_governance"] or verdict["high_severity"] or any(verdict["flags"].values())
+    if fetch_failed and not has_signal:
+        status = "fetch_failed"
+    else:
+        status = "complete"
+
+    return {
+        "ticker": ticker,
+        "subgroup": subgroup,
+        "tier": tier,
+        "reason": reason,
+        "flags": verdict["flags"],
+        "critical_governance": verdict["critical_governance"],
+        "high_severity": verdict["high_severity"],
+        "corporate_action": verdict["corporate_action"],
+        "concerns": verdict["concerns"],
+        "flag_details": verdict["flag_details"] or reason,
+        "coverage": coverage,
+        "status": status,
+    }
+
+
+def _is_transient_fetch_failure(record: dict, coverage: dict, subgroup: str) -> bool:
+    """True when the record represents a transient fetch failure rather than a structural gap.
+
+    Structural (NOT transient): foreign filer, genuinely stale 10-K, legitimately not-disclosed
+    notes. Transient: REST/edgartools errored such that required families came back `unavailable`
+    while the filer is domestic and not stale.
+    """
+    if record.get("filer_type") == "foreign":
+        return False
+    if (record.get("staleness") or {}).get("is_stale") and (record.get("staleness") or {}).get("reason", "").startswith("latest 10-K"):
+        return False  # genuinely stale -> structural Data Gap
+    # Any REQUIRED family `unavailable` (a fetch failure, per the schema) with source_errors present.
+    any_unavailable = any(
+        coverage.get(f) == "unavailable" for f in required_families(subgroup)
+    )
+    return bool(any_unavailable and record.get("source_errors"))
+
+
+def _guess_subgroup(record: dict) -> str:
+    # Records don't carry subgroup; default to general. The batch driver passes it explicitly.
+    return "general"
+
+
+# --------------------------------------------------------------------------------------
+# run-level circuit breaker
+# --------------------------------------------------------------------------------------
+def circuit_breaker_tripped(results: list[dict]) -> tuple[bool, str]:
+    """Trip if too much of the batch could not be evaluated (broad outage)."""
+    n = len(results)
+    if n < CIRCUIT_BREAKER_MIN_BATCH:
+        return False, ""
+    failed = sum(1 for r in results if r.get("status") == "fetch_failed")
+    frac = failed / n
+    if frac > CIRCUIT_BREAKER_FRACTION:
+        return True, f"{failed}/{n} names fetch_failed ({frac:.0%} > {CIRCUIT_BREAKER_FRACTION:.0%}) — likely broad outage"
+    return False, ""
+
+
+# --------------------------------------------------------------------------------------
+# history rows
+# --------------------------------------------------------------------------------------
+def result_to_history_row(result: dict, *, run_id: str, run_date: str | None = None) -> dict:
+    run_date = run_date or date.today().isoformat()
+    flags = result["flags"]
+    row = {
+        "run_date": run_date,
+        "ticker": result["ticker"],
+        "tier": result["tier"],
+        "flag_details": result.get("flag_details", ""),
+        "run_id": run_id,
+        "status": result.get("status", "complete"),
+        "schema_version": SCHEMA_VERSION,
+    }
+    for fam in FAMILIES:
+        row[f"{fam}_flag"] = int(flags.get(fam, 0))
+    return {col: row.get(col, "") for col in HISTORY_COLUMNS}
+
+
+def append_history(rows: list[dict], path: Path = FLAGS_HISTORY_CSV) -> None:
+    """Append rows to flags_history.csv, migrating the header to the v16 column set if needed."""
+    path.parent.mkdir(parents=True, exist_ok=True)
+    existing_header = None
+    if path.exists():
+        with path.open(encoding="utf-8", newline="") as f:
+            r = csv.reader(f)
+            existing_header = next(r, None)
+    write_header = (existing_header != HISTORY_COLUMNS)
+
+    if existing_header is not None and write_header:
+        _migrate_history_header(path)
+        write_header = False
+
+    with path.open("a", encoding="utf-8", newline="") as f:
+        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
+        if write_header or not path.exists():
+            w.writeheader()
+        for row in rows:
+            w.writerow({col: row.get(col, "") for col in HISTORY_COLUMNS})
+
+
+def _migrate_history_header(path: Path) -> None:
+    """Rewrite an old (13-col) flags_history.csv to the v16 schema, defaulting the new columns."""
+    with path.open(encoding="utf-8", newline="") as f:
+        rows = list(csv.DictReader(f))
+    with path.open("w", encoding="utf-8", newline="") as f:
+        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
+        w.writeheader()
+        for row in rows:
+            row.setdefault("run_id", "legacy")
+            row.setdefault("status", "complete")
+            row.setdefault("schema_version", "")
+            w.writerow({col: row.get(col, "") for col in HISTORY_COLUMNS})
+
+
+# --------------------------------------------------------------------------------------
+# CLI
+# --------------------------------------------------------------------------------------
+def main(argv=None) -> int:
+    p = argparse.ArgumentParser(description=__doc__)
+    p.add_argument("tickers", nargs="*", help="Tickers to tier (default: all in data/fetched/)")
+    p.add_argument("--run-id", default="manual")
+    p.add_argument("--append", action="store_true", help="Append results to flags_history.csv")
+    p.add_argument("--subgroup-from-watchlist", action="store_true", default=True)
+    args = p.parse_args(argv)
+
+    tickers = args.tickers or [p.stem for p in sorted(FETCHED_DIR.glob("*.json"))]
+    if not tickers:
+        print("No fetched records found.")
+        return 0
+
+    subgroups = _load_subgroups()
+    new_set = _new_names()
+    results = []
+    for t in tickers:
+        t = t.upper()
+        try:
+            rec = load_record(t)
+        except FileNotFoundError:
+            print(f"  {t}: no fetched record (skipped)")
+            continue
+        sg = subgroups.get(t, "general")
+        res = tier_one(rec, subgroup=sg, is_new=(t in new_set))
+        results.append(res)
+        print(f"  {t:<6} {res['tier']:<16} status={res['status']}  {res['reason']}")
+
+    tripped, why = circuit_breaker_tripped(results)
+    if tripped:
+        print(f"\nCIRCUIT BREAKER: {why}")
+        print("Refusing to commit a batch of false Data Gaps. Investigate the data sources.")
+        return 2
+
+    if args.append:
+        rows = [result_to_history_row(r, run_id=args.run_id) for r in results]
+        append_history(rows)
+        print(f"\nAppended {len(rows)} rows to {FLAGS_HISTORY_CSV}")
+    return 0
+
+
+def _load_subgroups() -> dict:
+    wl = ROOT / "data" / "watchlist.csv"
+    out = {}
+    if wl.exists():
+        with wl.open(encoding="utf-8", newline="") as f:
+            for row in csv.DictReader(f):
+                out[(row.get("ticker") or "").upper()] = row.get("sector_subgroup", "general")
+    return out
+
+
+def _new_names() -> set:
+    """Tickers in the watchlist that have no prior flags_history row (first appearance -> auto-Yellow)."""
+    wl = ROOT / "data" / "watchlist.csv"
+    seen_hist = set()
+    if FLAGS_HISTORY_CSV.exists():
+        with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
+            for row in csv.DictReader(f):
+                seen_hist.add((row.get("ticker") or "").upper())
+    new = set()
+    if wl.exists():
+        with wl.open(encoding="utf-8", newline="") as f:
+            for row in csv.DictReader(f):
+                t = (row.get("ticker") or "").upper()
+                if t and t not in seen_hist:
+                    new.add(t)
+    return new
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())

exec
/bin/bash -lc "nl -ba forensic_tier.py 2>/dev/null || true; nl -ba forensic_schema.py 2>/dev/null || true; nl -ba tier_batch.py | sed -n '1,360p'; nl -ba edgar_fetch.py | sed -n '1,760p'" in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 121ms:
t["high_severity"],
   330	        "corporate_action": verdict["corporate_action"],
   331	        "concerns": verdict["concerns"],
   332	        "flag_details": verdict["flag_details"] or reason,
   333	        "coverage": coverage,
   334	        "status": status,
   335	    }
   336	
   337	
   338	def _is_transient_fetch_failure(record: dict, coverage: dict, subgroup: str) -> bool:
   339	    """True when the record represents a transient fetch failure rather than a structural gap.
   340	
   341	    Structural (NOT transient): foreign filer, genuinely stale 10-K, legitimately not-disclosed
   342	    notes. Transient: REST/edgartools errored such that required families came back `unavailable`
   343	    while the filer is domestic and not stale.
   344	    """
   345	    if record.get("filer_type") == "foreign":
   346	        return False
   347	    if (record.get("staleness") or {}).get("is_stale") and (record.get("staleness") or {}).get("reason", "").startswith("latest 10-K"):
   348	        return False  # genuinely stale -> structural Data Gap
   349	    # Any REQUIRED family `unavailable` (a fetch failure, per the schema) with source_errors present.
   350	    any_unavailable = any(
   351	        coverage.get(f) == "unavailable" for f in required_families(subgroup)
   352	    )
   353	    return bool(any_unavailable and record.get("source_errors"))
   354	
   355	
   356	def _guess_subgroup(record: dict) -> str:
   357	    # Records don't carry subgroup; default to general. The batch driver passes it explicitly.
   358	    return "general"
   359	
   360	
     1	"""Per-ticker forensic data fetch (Path A, unattended) -> data/fetched/<TICKER>.json.
     2	
     3	The hybrid data layer (PATH_A_PLAN v3):
     4	  - PRIMARY: paid Edgar-Tools REST (hyphenated direct paths) for statements + ratios +
     5	    8-K item codes. The REST key works HEADLESSLY for these (the MCP rich tools do not).
     6	  - FALLBACK / NOTE BODIES: the free `edgartools` library (direct SEC) for 10-K note BODIES,
     7	    8-K bodies, Form-4 detail, and as a substitute for statements/8-K if the paid REST is down.
     8	
     9	The single most important property of this module is the FALSE-GREEN GUARD:
    10	  - It MUST NEVER RAISE. Every external source is wrapped; a failure becomes a status flag
    11	    + a `source_errors` entry, never a crash that aborts a batch.
    12	  - `not_disclosed` != `fetch_failed`. A note legitimately absent from a filing is fine
    13	    (`present`/`not_disclosed`). A note we *failed to read* is `fetch_failed` -> the owning
    14	    family is `unavailable` -> blocks Green.
    15	  - It emits a HARD schema (see `_empty_record`), per PATH_A_PLAN "edgar_fetch.py -- JSON contract",
    16	    including `family_coverage` (the COVERAGE enum from forensic_schema) and
    17	    `required_families_complete` so forensic_tier can enforce "unevaluable != Green".
    18	
    19	Staleness is computed from FILING DATES / period-end (codex R1 #7), NOT fiscal-year age.
    20	
    21	CLI:
    22	  python edgar_fetch.py TICKER [--cik 0000320193] [--out data/fetched]
    23	
    24	This module does NOT decide tiers. It only gathers + classifies coverage. `tier_batch.py`
    25	consumes the JSON; `forensic_tier.py` makes the final deterministic decision.
    26	"""
    27	from __future__ import annotations
    28	
    29	import argparse
    30	import csv
    31	import json
    32	import os
    33	import sys
    34	import traceback
    35	from datetime import datetime, timezone
    36	from pathlib import Path
    37	
    38	from forensic_schema import COVERAGE, FAMILIES, SCHEMA_VERSION, required_families
    39	
    40	ROOT = Path(__file__).parent
    41	WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"
    42	DEFAULT_OUT_DIR = ROOT / "data" / "fetched"
    43	
    44	# Staleness threshold: a 10-K whose period_end is older than this (no newer annual) is
    45	# "stale" -> Data Gap. Date-based (period_end / filing_date), NOT fiscal-year-number age.
    46	STALE_DAYS = 400
    47	
    48	# 10-K note topics we attempt to read (title-substring search; see CLAUDE.md note re: literal match).
    49	NOTE_TOPICS = {
    50	    "Inventory": ["inventory"],
    51	    "Goodwill": ["goodwill"],
    52	    "Debt": ["debt", "borrowing", "credit facilit", "notes payable"],
    53	    "Commitments": ["commitment", "contingenc", "legal", "litigation"],
    54	    "Significant Accounting Policies": ["significant accounting", "summary of significant", "basis of presentation"],
    55	    "Revenue": ["revenue"],
    56	}
    57	
    58	# 8-K item codes that matter for the governance / corporate-action families.
    59	GOV_8K_ITEMS = {"4.01", "4.02", "5.02"}            # auditor change, non-reliance, officer dep.
    60	CORP_ACTION_8K_ITEMS = {"2.01", "3.01", "5.01"}    # acquisition/disposal, delisting, control change
    61	NT_FORMS = {"NT 10-K", "NT 10-Q", "NT10-K", "NT10-Q"}
    62	
    63	REST_BASE = "https://api.edgar.tools"  # documented hyphenated direct paths under /companies/{cik}/...
    64	
    65	
    66	# --------------------------------------------------------------------------------------
    67	# never-raise helpers
    68	# --------------------------------------------------------------------------------------
    69	def _now_iso() -> str:
    70	    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    71	
    72	
    73	def _safe(fn, errors: list, label: str, default=None):
    74	    """Run fn(); on ANY exception record a compact source_error and return default.
    75	
    76	    This is the never-raise contract: no external call may abort the run.
    77	    """
    78	    try:
    79	        return fn()
    80	    except Exception as exc:  # noqa: BLE001 -- deliberately broad; this is the guard
    81	        errors.append({"source": label, "error": f"{type(exc).__name__}: {exc}"[:300]})
    82	        return default
    83	
    84	
    85	def _empty_record(ticker: str, cik: str, run_id: str) -> dict:
    86	    """The HARD schema. Every key present, conservative defaults (false-Green guard:
    87	    absence is treated as not-evaluable, never as clean)."""
    88	    return {
    89	        "schema_version": SCHEMA_VERSION,
    90	        "ticker": ticker,
    91	        "cik": cik,
    92	        "run_id": run_id,
    93	        "fetched_at": _now_iso(),
    94	        "filer_type": "unknown",
    95	        "latest_10k": None,           # {accession, filing_date, period_end, fy}
    96	        "latest_10q": None,
    97	        "staleness": {"is_stale": True, "reason": "not_yet_evaluated"},
    98	        "ratios": None,
    99	        "statements": {"annual": [], "quarters": []},
   100	        "notes": {topic: {"status": "fetch_failed", "text": ""} for topic in NOTE_TOPICS},
   101	        "events_8k": [],              # [{date, items, body_excerpt}]
   102	        "corporate_action": None,     # {detected, kind}
   103	        "insider": {"clusters": [], "status": "fetch_failed"},
   104	        "family_coverage": {f: "unavailable" for f in FAMILIES},
   105	        "required_families_complete": False,
   106	        "source_errors": [],
   107	        "rest_available": False,      # whether the paid REST answered at all this run
   108	    }
   109	
   110	
   111	# --------------------------------------------------------------------------------------
   112	# paid REST layer (primary for statements / ratios / 8-K item codes)
   113	# --------------------------------------------------------------------------------------
   114	class RestClient:
   115	    """Thin wrapper over the paid Edgar-Tools REST. Every method is best-effort and may
   116	    return None; the caller wraps it in _safe so an outage degrades, never crashes."""
   117	
   118	    def __init__(self, api_key: str | None, identity: str | None):
   119	        self.api_key = api_key
   120	        self.identity = identity
   121	        self._session = None
   122	
   123	    def _sess(self):
   124	        if self._session is None:
   125	            import requests  # local import so tests can run without the dep on the import path
   126	            s = requests.Session()
   127	            headers = {"User-Agent": self.identity or "forensic_triage (jroypeterson@gmail.com)"}
   128	            if self.api_key:
   129	                headers["Authorization"] = f"Bearer {self.api_key}"
   130	            s.headers.update(headers)
   131	            self._session = s
   132	        return self._session
   133	
   134	    def _get(self, path: str):
   135	        if not self.api_key:
   136	            raise RuntimeError("no EDGARTOOLS_API_KEY -- REST unavailable")
   137	        resp = self._sess().get(f"{REST_BASE}{path}", timeout=30)
   138	        resp.raise_for_status()
   139	        return resp.json()
   140	
   141	    def ratios(self, cik: str):
   142	        return self._get(f"/companies/{cik}/ratios")
   143	
   144	    def income_statement(self, cik: str):
   145	        return self._get(f"/companies/{cik}/income-statement")
   146	
   147	    def balance_sheet(self, cik: str):
   148	        return self._get(f"/companies/{cik}/balance-sheet")
   149	
   150	    def cash_flow(self, cik: str):
   151	        return self._get(f"/companies/{cik}/cash-flow")
   152	
   153	    def metrics(self, cik: str):
   154	        return self._get(f"/companies/{cik}/metrics")
   155	
   156	    def material_events(self, cik: str):
   157	        return self._get(f"/companies/{cik}/material-events")
   158	
   159	
   160	# --------------------------------------------------------------------------------------
   161	# free edgartools layer (note bodies + fallbacks)
   162	# --------------------------------------------------------------------------------------
   163	def _edgar_company(cik: str, identity: str | None):
   164	    """Return an edgartools Company, or raise (wrapped by _safe upstream)."""
   165	    import edgar  # local import
   166	
   167	    if identity:
   168	        try:
   169	            edgar.set_identity(identity)
   170	        except Exception:  # noqa: BLE001
   171	            pass
   172	    return edgar.Company(cik)
   173	
   174	
   175	def _parse_date(s: str | None):
   176	    if not s:
   177	        return None
   178	    for fmt in ("%Y-%m-%d", "%Y%m%d"):
   179	        try:
   180	            return datetime.strptime(s[:10], fmt).date()
   181	        except (ValueError, TypeError):
   182	            continue
   183	    return None
   184	
   185	
   186	# --------------------------------------------------------------------------------------
   187	# coverage classification (the false-Green guard's core)
   188	# --------------------------------------------------------------------------------------
   189	def _classify_coverage(rec: dict, subgroup: str) -> dict:
   190	    """Map what we actually fetched to the per-family COVERAGE enum.
   191	
   192	    Required financial families need statements; governance needs the 8-K feed; the
   193	    note-backed checks need note bodies. Anything we FAILED to fetch -> unavailable
   194	    (blocks Green). Structurally-unreachable-unattended families (market short interest,
   195	    text MD&A diffs) -> not_evaluated.
   196	    """
   197	    cov: dict[str, str] = {}
   198	
   199	    have_statements = bool(rec["statements"]["annual"]) or rec["ratios"] is not None
   200	    have_8k = isinstance(rec["events_8k"], list) and (
   201	        rec.get("_events_8k_fetched") is True
   202	    )
   203	
   204	    def note_ok(*topics: str) -> bool:
   205	        """A note family is 'evaluable' if at least one backing note was either read OR
   206	        legitimately not-disclosed. Only a fetch_failure makes it unavailable."""
   207	        statuses = [rec["notes"].get(t, {}).get("status", "fetch_failed") for t in topics]
   208	        if not statuses:
   209	            return False
   210	        return all(s in ("present", "not_disclosed") for s in statuses)
   211	
   212	    # Financial families lean on statements.
   213	    fin_state = "complete" if have_statements else "unavailable"
   214	    cov["accruals"] = fin_state
   215	    cov["revenue"] = "complete" if (have_statements and note_ok("Revenue", "Significant Accounting Policies")) else ("partial" if have_statements else "unavailable")
   216	    cov["capex"] = fin_state
   217	    cov["balance_sheet"] = "complete" if (have_statements and note_ok("Inventory", "Goodwill")) else ("partial" if have_statements else "unavailable")
   218	    cov["leverage"] = "complete" if (have_statements and note_ok("Debt")) else ("partial" if have_statements else "unavailable")
   219	
   220	    # Governance: needs the 8-K feed (item codes). If neither REST nor edgartools delivered it -> unavailable.
   221	    cov["governance"] = "complete" if have_8k else "unavailable"
   222	
   223	    # Market + text are OPTIONAL (not reachable unattended) -> not_evaluated (never blocks Green).
   224	    cov["market"] = "partial" if rec["insider"].get("status") == "present" else "not_evaluated"
   225	    cov["text"] = "not_evaluated"
   226	
   227	    # Sector: required for hc/medtech (note-backed, reachable); not_applicable for general.
   228	    if subgroup == "general":
   229	        cov["sector"] = "not_applicable"
   230	    else:
   231	        cov["sector"] = "complete" if note_ok("Significant Accounting Policies", "Commitments") else (
   232	            "partial" if any(rec["notes"].get(t, {}).get("status") == "present"
   233	                             for t in ("Inventory", "Revenue", "Commitments")) else "unavailable"
   234	        )
   235	
   236	    # Staleness / foreign filer override everything to a structural Data Gap (still "done").
   237	    if rec["filer_type"] == "foreign":
   238	        return {f: "not_evaluated" for f in FAMILIES} | ({"sector": "not_applicable"} if subgroup == "general" else {})
   239	    if rec["staleness"].get("is_stale"):
   240	        # genuinely stale -> required financial families can't be trusted current
   241	        for f in ("accruals", "revenue", "capex", "balance_sheet", "leverage"):
   242	            if cov[f] == "complete":
   243	                cov[f] = "partial"
   244	
   245	    # Sanity: only emit valid enum values.
   246	    for f in FAMILIES:
   247	        if cov.get(f) not in COVERAGE:
   248	            cov[f] = "unavailable"
   249	    return cov
   250	
   251	
   252	def _required_complete(coverage: dict, subgroup: str) -> bool:
   253	    for fam in required_families(subgroup):
   254	        if coverage.get(fam, "unavailable") not in ("complete", "not_applicable"):
   255	            return False
   256	    return True
   257	
   258	
   259	# --------------------------------------------------------------------------------------
   260	# main fetch
   261	# --------------------------------------------------------------------------------------
   262	def fetch_ticker(
   263	    ticker: str,
   264	    cik: str,
   265	    *,
   266	    subgroup: str = "general",
   267	    filer_type: str = "domestic",
   268	    run_id: str = "manual",
   269	    rest: RestClient | None = None,
   270	    identity: str | None = None,
   271	) -> dict:
   272	    """Fetch + classify one name. NEVER RAISES -- returns a complete schema record."""
   273	    rec = _empty_record(ticker, cik, run_id)
   274	    rec["filer_type"] = filer_type
   275	    errors = rec["source_errors"]
   276	    identity = identity or os.environ.get("EDGAR_IDENTITY")
   277	
   278	    # Foreign filers are a STRUCTURAL Data Gap -- do not spend EDGAR calls; mark done.
   279	    if filer_type == "foreign":
   280	        rec["staleness"] = {"is_stale": True, "reason": "foreign_20f_filer"}
   281	        rec["family_coverage"] = _classify_coverage(rec, subgroup)
   282	        rec["required_families_complete"] = _required_complete(rec["family_coverage"], subgroup)
   283	        return rec
   284	
   285	    if rest is None:
   286	        rest = RestClient(os.environ.get("EDGARTOOLS_API_KEY"), identity)
   287	
   288	    # --- 1. paid REST primary: ratios + statements + 8-K item codes ---
   289	    ratios = _safe(lambda: rest.ratios(cik), errors, "rest:ratios")
   290	    if ratios is not None:
   291	        rec["ratios"] = ratios
   292	        rec["rest_available"] = True
   293	
   294	    income = _safe(lambda: rest.income_statement(cik), errors, "rest:income-statement")
   295	    balance = _safe(lambda: rest.balance_sheet(cik), errors, "rest:balance-sheet")
   296	    cashflow = _safe(lambda: rest.cash_flow(cik), errors, "rest:cash-flow")
   297	    if any(x is not None for x in (income, balance, cashflow)):
   298	        rec["rest_available"] = True
   299	        rec["statements"]["annual"] = _safe(
   300	            lambda: _normalize_statements(income, balance, cashflow), errors,
   301	            "normalize:statements", default=[],
   302	        ) or []
   303	
   304	    rest_events = _safe(lambda: rest.material_events(cik), errors, "rest:material-events")
   305	    events_fetched = False
   306	    if rest_events is not None:
   307	        rec["events_8k"] = _safe(lambda: _normalize_events(rest_events), errors,
   308	                                 "normalize:events", default=[]) or []
   309	        events_fetched = True
   310	
   311	    # --- 2. free edgartools: note bodies (always) + statement/8-K fallback if REST was down ---
   312	    company = _safe(lambda: _edgar_company(cik, identity), errors, "edgartools:company")
   313	    if company is not None:
   314	        # latest 10-K / 10-Q + staleness (date-based)
   315	        _safe(lambda: _populate_filings(rec, company), errors, "edgartools:filings")
   316	        # note bodies (the thing only the free lib can do headlessly)
   317	        _safe(lambda: _populate_notes(rec, company), errors, "edgartools:notes")
   318	        # insider Form-4 (best-effort, OPTIONAL family)
   319	        _safe(lambda: _populate_insider(rec, company), errors, "edgartools:insider")
   320	        # fallback statements if REST gave us nothing
   321	        if not rec["statements"]["annual"]:
   322	            fb = _safe(lambda: _edgartools_statements(company), errors,
   323	                       "edgartools:statements-fallback", default=[])
   324	            if fb:
   325	                rec["statements"]["annual"] = fb
   326	        # fallback 8-K feed if REST events were unavailable (so an outage can't hide a 4.02)
   327	        if not events_fetched:
   328	            fb_events = _safe(lambda: _edgartools_events(company), errors,
   329	                              "edgartools:events-fallback", default=None)
   330	            if fb_events is not None:
   331	                rec["events_8k"] = fb_events
   332	                events_fetched = True
   333	
   334	    rec["_events_8k_fetched"] = events_fetched
   335	
   336	    # --- 3. derive corporate-action + governance signals from the 8-K feed ---
   337	    _safe(lambda: _derive_corporate_action(rec), errors, "derive:corporate_action")
   338	
   339	    # --- 4. coverage classification + Green-eligibility precompute ---
   340	    rec["family_coverage"] = _classify_coverage(rec, subgroup)
   341	    rec["required_families_complete"] = _required_complete(rec["family_coverage"], subgroup)
   342	
   343	    rec.pop("_events_8k_fetched", None)
   344	    return rec
   345	
   346	
   347	# --------------------------------------------------------------------------------------
   348	# normalizers (defensive; each may be wrapped by _safe)
   349	# --------------------------------------------------------------------------------------
   350	def _normalize_statements(income, balance, cashflow) -> list:
   351	    """Fold the three REST statement payloads into a compact per-period list.
   352	
   353	    REST shapes vary; we only need the line items the rubric uses. Best-effort: we keep
   354	    whatever periods we can align and tolerate missing concepts.
   355	    """
   356	    out: list[dict] = []
   357	    periods: dict[str, dict] = {}
   358	
   359	    def absorb(payload, keys):
   360	        if not isinstance(payload, dict):
   361	            return
   362	        rows = payload.get("data") or payload.get("statements") or payload.get("periods") or []
   363	        if isinstance(rows, dict):
   364	            rows = [rows]
   365	        for row in rows if isinstance(rows, list) else []:
   366	            if not isinstance(row, dict):
   367	                continue
   368	            period = str(row.get("period") or row.get("fiscal_year") or row.get("date") or row.get("period_end") or "")
   369	            if not period:
   370	                continue
   371	            bucket = periods.setdefault(period, {"period": period})
   372	            for k in keys:
   373	                if k in row and row[k] is not None:
   374	                    bucket[k] = row[k]
   375	
   376	    absorb(income, ["revenue", "net_income", "gross_profit", "cogs", "depreciation_amortization"])
   377	    absorb(balance, ["total_assets", "inventory", "accounts_receivable", "goodwill",
   378	                     "total_debt", "short_term_debt", "long_term_debt", "deferred_revenue"])
   379	    absorb(cashflow, ["cfo", "capex", "depreciation_amortization"])
   380	
   381	    for period in sorted(periods, reverse=True):
   382	        out.append(periods[period])
   383	    return out
   384	
   385	
   386	def _normalize_events(payload) -> list:
   387	    out: list[dict] = []
   388	    rows = payload.get("data") or payload.get("events") or payload if isinstance(payload, dict) else payload
   389	    if isinstance(rows, dict):
   390	        rows = rows.get("events", [])
   391	    for row in rows if isinstance(rows, list) else []:
   392	        if not isinstance(row, dict):
   393	            continue
   394	        items = row.get("items") or row.get("item_codes") or []
   395	        if isinstance(items, str):
   396	            items = [i.strip() for i in items.replace(";", ",").split(",") if i.strip()]
   397	        out.append({
   398	            "date": str(row.get("date") or row.get("filing_date") or ""),
   399	            "items": [str(i) for i in items],
   400	            "body_excerpt": (row.get("body") or row.get("description") or "")[:500],
   401	        })
   402	    return out
   403	
   404	
   405	def _populate_filings(rec: dict, company) -> None:
   406	    """Latest 10-K / 10-Q accession + dates, and date-based staleness."""
   407	    def latest(form):
   408	        try:
   409	            filings = company.get_filings(form=form)
   410	        except Exception:  # noqa: BLE001
   411	            filings = None
   412	        if not filings:
   413	            return None
   414	        try:
   415	            f = filings.latest()
   416	        except Exception:  # noqa: BLE001
   417	            f = filings[0] if len(filings) else None
   418	        if f is None:
   419	            return None
   420	        return {
   421	            "accession": str(getattr(f, "accession_no", getattr(f, "accession_number", "")) or ""),
   422	            "filing_date": str(getattr(f, "filing_date", "") or ""),
   423	            "period_end": str(getattr(f, "period_of_report", getattr(f, "report_date", "")) or ""),
   424	            "fy": str(getattr(f, "fiscal_year", "") or ""),
   425	        }
   426	
   427	    k = latest("10-K")
   428	    q = latest("10-Q")
   429	    rec["latest_10k"] = k
   430	    rec["latest_10q"] = q
   431	
   432	    # Staleness: date-based on the 10-K's period_end (fallback filing_date), NOT fy age.
   433	    ref = None
   434	    if k:
   435	        ref = _parse_date(k.get("period_end")) or _parse_date(k.get("filing_date"))
   436	    if ref is None:
   437	        rec["staleness"] = {"is_stale": True, "reason": "no_10k_found"}
   438	        return
   439	    age = (datetime.now(timezone.utc).date() - ref).days
   440	    if age > STALE_DAYS:
   441	        rec["staleness"] = {"is_stale": True, "reason": f"latest 10-K period_end {ref} is {age}d old (> {STALE_DAYS})"}
   442	    else:
   443	        rec["staleness"] = {"is_stale": False, "reason": f"latest 10-K period_end {ref} ({age}d old)"}
   444	
   445	
   446	def _populate_notes(rec: dict, company) -> None:
   447	    """Read 10-K note bodies. Distinguish present / not_disclosed / fetch_failed PER NOTE.
   448	
   449	    The whole false-Green guard hinges on this: we only mark a note `fetch_failed` when the
   450	    READ itself errored. If the filing was readable but the topic simply isn't there, that's
   451	    `not_disclosed` (a legitimate absence, not a data gap).
   452	    """
   453	    filing = None
   454	    try:
   455	        tenk = company.get_filings(form="10-K")
   456	        filing = tenk.latest() if tenk else None
   457	    except Exception as exc:  # noqa: BLE001
   458	        # Could not even load the 10-K -> EVERY note is fetch_failed (blocks the note families).
   459	        for topic in NOTE_TOPICS:
   460	            rec["notes"][topic] = {"status": "fetch_failed", "text": ""}
   461	        rec["source_errors"].append({"source": "edgartools:10k-load", "error": f"{type(exc).__name__}: {exc}"[:200]})
   462	        return
   463	
   464	    if filing is None:
   465	        for topic in NOTE_TOPICS:
   466	            rec["notes"][topic] = {"status": "not_disclosed", "text": ""}  # no 10-K -> nothing disclosed there
   467	        return
   468	
   469	    # Pull the full text once; topic search is substring-on-text (best-effort).
   470	    full_text = None
   471	    try:
   472	        obj = filing.obj() if hasattr(filing, "obj") else None
   473	        full_text = (obj.text() if obj is not None and hasattr(obj, "text") else None)
   474	        if full_text is None:
   475	            full_text = filing.text() if hasattr(filing, "text") else None
   476	    except Exception:  # noqa: BLE001
   477	        full_text = None
   478	
   479	    if not full_text:
   480	        # The filing handle exists but body unreadable -> a genuine FETCH FAILURE.
   481	        for topic in NOTE_TOPICS:
   482	            rec["notes"][topic] = {"status": "fetch_failed", "text": ""}
   483	        rec["source_errors"].append({"source": "edgartools:10k-text", "error": "empty filing body"})
   484	        return
   485	
   486	    low = full_text.lower()
   487	    for topic, keys in NOTE_TOPICS.items():
   488	        hit_idx = -1
   489	        for kw in keys:
   490	            idx = low.find(kw)
   491	            if idx != -1:
   492	                hit_idx = idx
   493	                break
   494	        if hit_idx == -1:
   495	            rec["notes"][topic] = {"status": "not_disclosed", "text": ""}
   496	        else:
   497	            excerpt = full_text[hit_idx: hit_idx + 1500]
   498	            rec["notes"][topic] = {"status": "present", "text": excerpt}
   499	
   500	
   501	def _populate_insider(rec: dict, company) -> None:
   502	    try:
   503	        forms = company.get_filings(form="4")
   504	    except Exception:  # noqa: BLE001
   505	        forms = None
   506	    if not forms:
   507	        rec["insider"] = {"clusters": [], "status": "not_evaluated"}
   508	        return
   509	    try:
   510	        recent = forms.head(20) if hasattr(forms, "head") else forms[:20]
   511	        dates = [str(getattr(f, "filing_date", "")) for f in recent]
   512	    except Exception:  # noqa: BLE001
   513	        rec["insider"] = {"clusters": [], "status": "not_evaluated"}
   514	        return
   515	    rec["insider"] = {"clusters": [], "recent_form4_dates": dates, "status": "present"}
   516	
   517	
   518	def _edgartools_statements(company) -> list:
   519	    """Fallback statements via companyfacts/financials when REST is down."""
   520	    try:
   521	        fin = company.financials if hasattr(company, "financials") else None
   522	    except Exception:  # noqa: BLE001
   523	        fin = None
   524	    if fin is None:
   525	        return []
   526	    # We keep this minimal: presence of a financials object is enough for coverage to be
   527	    # non-unavailable; the detailed line-item extraction is best-effort and tolerant.
   528	    return [{"period": "latest", "source": "edgartools_financials"}]
   529	
   530	
   531	def _edgartools_events(company) -> list:
   532	    """Fallback 8-K item-code feed via edgartools, so a REST outage can't hide a 4.02."""
   533	    out: list[dict] = []
   534	    try:
   535	        eights = company.get_filings(form="8-K")
   536	    except Exception:  # noqa: BLE001
   537	        return []
   538	    if not eights:
   539	        return []
   540	    try:
   541	        recent = eights.head(25) if hasattr(eights, "head") else eights[:25]
   542	    except Exception:  # noqa: BLE001
   543	        recent = eights
   544	    for f in recent:
   545	        items = getattr(f, "items", None) or []
   546	        if isinstance(items, str):
   547	            items = [i.strip() for i in items.replace(";", ",").split(",") if i.strip()]
   548	        out.append({
   549	            "date": str(getattr(f, "filing_date", "") or ""),
   550	            "items": [str(i) for i in items],
   551	            "body_excerpt": "",
   552	        })
   553	    return out
   554	
   555	
   556	def _derive_corporate_action(rec: dict) -> None:
   557	    """Set governance / corporate-action hints from the 8-K item codes (deterministic facts;
   558	    Claude still judges severity, but the codes themselves are read here)."""
   559	    corp_kind = None
   560	    for ev in rec["events_8k"]:
   561	        items = set(ev.get("items", []))
   562	        if items & CORP_ACTION_8K_ITEMS:
   563	            corp_kind = sorted(items & CORP_ACTION_8K_ITEMS)[0]
   564	    if corp_kind:
   565	        rec["corporate_action"] = {"detected": True, "kind": f"8-K item {corp_kind}"}
   566	
   567	
   568	# --------------------------------------------------------------------------------------
   569	# watchlist lookup + persistence
   570	# --------------------------------------------------------------------------------------
   571	def _lookup_watchlist(ticker: str) -> dict | None:
   572	    if not WATCHLIST_CSV.exists():
   573	        return None
   574	    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
   575	        for row in csv.DictReader(f):
   576	            if (row.get("ticker") or "").strip().upper() == ticker.upper():
   577	                return row
   578	    return None
   579	
   580	
   581	def write_record(rec: dict, out_dir: Path) -> Path:
   582	    out_dir.mkdir(parents=True, exist_ok=True)
   583	    path = out_dir / f"{rec['ticker']}.json"
   584	    tmp = out_dir / f".{rec['ticker']}.json.tmp"
   585	    with tmp.open("w", encoding="utf-8") as f:
   586	        json.dump(rec, f, indent=2, sort_keys=False)
   587	    tmp.replace(path)
   588	    return path
   589	
   590	
   591	def main(argv=None) -> int:
   592	    p = argparse.ArgumentParser(description=__doc__)
   593	    p.add_argument("ticker")
   594	    p.add_argument("--cik", default=None, help="10-digit CIK (else looked up from watchlist.csv)")
   595	    p.add_argument("--subgroup", default=None)
   596	    p.add_argument("--filer-type", default=None)
   597	    p.add_argument("--run-id", default="manual")
   598	    p.add_argument("--out", default=str(DEFAULT_OUT_DIR))
   599	    args = p.parse_args(argv)
   600	
   601	    ticker = args.ticker.strip().upper()
   602	    row = _lookup_watchlist(ticker) or {}
   603	    cik = (args.cik or row.get("cik") or "").strip()
   604	    subgroup = args.subgroup or row.get("sector_subgroup") or "general"
   605	    filer_type = args.filer_type or row.get("filer_type") or "domestic"
   606	
   607	    if not cik and filer_type != "foreign":
   608	        # No CIK and not a known-foreign skip -> we cannot fetch. Emit a fetch-failed record
   609	        # (never crash) so the caller sees a transient failure, not a false Data Gap.
   610	        rec = _empty_record(ticker, "", args.run_id)
   611	        rec["filer_type"] = filer_type
   612	        rec["source_errors"].append({"source": "watchlist", "error": "no CIK found for ticker"})
   613	        path = write_record(rec, Path(args.out))
   614	        print(f"WROTE {path} (NO CIK -- fetch_failed; not green-eligible)")
   615	        return 0
   616	
   617	    # The fetch itself never raises; this top-level guard is belt-and-suspenders only.
   618	    try:
   619	        rec = fetch_ticker(ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=args.run_id)
   620	    except Exception as exc:  # noqa: BLE001
   621	        rec = _empty_record(ticker, cik, args.run_id)
   622	        rec["filer_type"] = filer_type
   623	        rec["source_errors"].append({"source": "fetch_ticker", "error": f"{type(exc).__name__}: {exc}"})
   624	        rec["source_errors"].append({"source": "traceback", "error": traceback.format_exc()[:400]})
   625	
   626	    path = write_record(rec, Path(args.out))
   627	    cov = rec["family_coverage"]
   628	    print(f"WROTE {path}  filer={rec['filer_type']}  "
   629	          f"required_complete={rec['required_families_complete']}  "
   630	          f"errors={len(rec['source_errors'])}")
   631	    print("  coverage:", ", ".join(f"{k}={cov[k]}" for k in FAMILIES))
   632	    return 0
   633	
   634	
   635	if __name__ == "__main__":
   636	    raise SystemExit(main())

exec
/bin/bash -lc "nl -ba tier_batch.py | sed -n '220,430p'; nl -ba next_batch.py | sed -n '1,260p'; nl -ba run_unattended.py | sed -n '1,260p'; nl -ba notify.py | sed -n '1,260p'; nl -ba .github/workflows/forensic_triage.yml" in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 0ms:
   220	
   221	    last_err = None
   222	    for _ in range(MAX_VALIDATION_RETRIES + 1):
   223	        response = _create_with_fallback(client, base_kwargs)
   224	        if getattr(response, "stop_reason", None) == "refusal":
   225	            raise JudgeValidationError("model refused (stop_reason=refusal)")
   226	        try:
   227	            text = _extract_json_text(response)
   228	            obj = json.loads(text)
   229	            return validate_judge_output(obj, ticker)
   230	        except (JudgeValidationError, json.JSONDecodeError, ValueError) as exc:
   231	            last_err = exc
   232	            continue
   233	    raise JudgeValidationError(f"judge output invalid after retries: {last_err}")
   234	
   235	
   236	def _create_with_fallback(client, kwargs: dict):
   237	    """messages.create with server-side refusal fallback when available, else plain.
   238	
   239	    Fallbacks are a beta param; if the SDK/endpoint rejects it we degrade to a plain create
   240	    (still safe — a refusal is then caught by the stop_reason check upstream).
   241	    """
   242	    beta = getattr(client, "beta", None)
   243	    if beta is not None and hasattr(getattr(beta, "messages", None), "create"):
   244	        try:
   245	            return beta.messages.create(
   246	                betas=["server-side-fallback-2026-06-01"],
   247	                fallbacks=[{"model": FALLBACK_MODEL}],
   248	                **kwargs,
   249	            )
   250	        except TypeError:
   251	            pass  # SDK too old for fallbacks/betas kwargs
   252	        except Exception:
   253	            pass  # beta endpoint unavailable -> fall through to plain create
   254	    return client.messages.create(**kwargs)
   255	
   256	
   257	# --------------------------------------------------------------------------------------
   258	# coverage + tiering glue
   259	# --------------------------------------------------------------------------------------
   260	def _coverage_from_record(record: dict, subgroup: str) -> dict:
   261	    cov = record.get("family_coverage") or {}
   262	    out = {}
   263	    for fam in FAMILIES:
   264	        v = cov.get(fam)
   265	        out[fam] = v if v in COVERAGE else "unavailable"
   266	    return out
   267	
   268	
   269	def _required_incomplete(coverage: dict, subgroup: str) -> bool:
   270	    for fam in required_families(subgroup):
   271	        if coverage.get(fam, "unavailable") not in ("complete", "not_applicable"):
   272	            return True
   273	    return False
   274	
   275	
   276	def tier_one(
   277	    record: dict,
   278	    *,
   279	    subgroup: str | None = None,
   280	    is_new: bool = False,
   281	    client=None,
   282	    judge=None,
   283	    model: str = MODEL_ID,
   284	) -> dict:
   285	    """Tier one fetched record. Returns a result dict (tier, reason, flags, concerns, status).
   286	
   287	    `judge` lets tests inject the per-family verdict directly (skipping the API). In production
   288	    `judge` is None and we call the Anthropic API via call_judge.
   289	    """
   290	    subgroup = subgroup or record.get("_subgroup") or _guess_subgroup(record)
   291	    ticker = record.get("ticker", "?")
   292	    coverage = _coverage_from_record(record, subgroup)
   293	
   294	    # A transient fetch failure (source_errors AND nothing usable) must NOT be finalized as a
   295	    # clean tier — it's "incomplete this run, retry next run". Foreign/stale = STRUCTURAL gap = done.
   296	    fetch_failed = _is_transient_fetch_failure(record, coverage, subgroup)
   297	
   298	    if judge is None:
   299	        rubric = load_rubric(subgroup)
   300	        verdict = call_judge(rubric, record, client=client, model=model)
   301	    else:
   302	        verdict = validate_judge_output(judge, ticker)
   303	
   304	    tier, reason = finalize_tier(
   305	        flags=verdict["flags"],
   306	        coverage=coverage,
   307	        subgroup=subgroup,
   308	        critical_governance=verdict["critical_governance"],
   309	        high_severity=verdict["high_severity"],
   310	        corporate_action=verdict["corporate_action"],
   311	        is_new=is_new,
   312	    )
   313	
   314	    # Idempotency status (codex R2): a structural Data Gap (foreign/stale/not-disclosed) IS
   315	    # complete; a transient fetch failure with no overriding signal is NOT (retry next run).
   316	    has_signal = verdict["critical_governance"] or verdict["high_severity"] or any(verdict["flags"].values())
   317	    if fetch_failed and not has_signal:
   318	        status = "fetch_failed"
   319	    else:
   320	        status = "complete"
   321	
   322	    return {
   323	        "ticker": ticker,
   324	        "subgroup": subgroup,
   325	        "tier": tier,
   326	        "reason": reason,
   327	        "flags": verdict["flags"],
   328	        "critical_governance": verdict["critical_governance"],
   329	        "high_severity": verdict["high_severity"],
   330	        "corporate_action": verdict["corporate_action"],
   331	        "concerns": verdict["concerns"],
   332	        "flag_details": verdict["flag_details"] or reason,
   333	        "coverage": coverage,
   334	        "status": status,
   335	    }
   336	
   337	
   338	def _is_transient_fetch_failure(record: dict, coverage: dict, subgroup: str) -> bool:
   339	    """True when the record represents a transient fetch failure rather than a structural gap.
   340	
   341	    Structural (NOT transient): foreign filer, genuinely stale 10-K, legitimately not-disclosed
   342	    notes. Transient: REST/edgartools errored such that required families came back `unavailable`
   343	    while the filer is domestic and not stale.
   344	    """
   345	    if record.get("filer_type") == "foreign":
   346	        return False
   347	    if (record.get("staleness") or {}).get("is_stale") and (record.get("staleness") or {}).get("reason", "").startswith("latest 10-K"):
   348	        return False  # genuinely stale -> structural Data Gap
   349	    # Any REQUIRED family `unavailable` (a fetch failure, per the schema) with source_errors present.
   350	    any_unavailable = any(
   351	        coverage.get(f) == "unavailable" for f in required_families(subgroup)
   352	    )
   353	    return bool(any_unavailable and record.get("source_errors"))
   354	
   355	
   356	def _guess_subgroup(record: dict) -> str:
   357	    # Records don't carry subgroup; default to general. The batch driver passes it explicitly.
   358	    return "general"
   359	
   360	
   361	# --------------------------------------------------------------------------------------
   362	# run-level circuit breaker
   363	# --------------------------------------------------------------------------------------
   364	def circuit_breaker_tripped(results: list[dict]) -> tuple[bool, str]:
   365	    """Trip if too much of the batch could not be evaluated (broad outage)."""
   366	    n = len(results)
   367	    if n < CIRCUIT_BREAKER_MIN_BATCH:
   368	        return False, ""
   369	    failed = sum(1 for r in results if r.get("status") == "fetch_failed")
   370	    frac = failed / n
   371	    if frac > CIRCUIT_BREAKER_FRACTION:
   372	        return True, f"{failed}/{n} names fetch_failed ({frac:.0%} > {CIRCUIT_BREAKER_FRACTION:.0%}) — likely broad outage"
   373	    return False, ""
   374	
   375	
   376	# --------------------------------------------------------------------------------------
   377	# history rows
   378	# --------------------------------------------------------------------------------------
   379	def result_to_history_row(result: dict, *, run_id: str, run_date: str | None = None) -> dict:
   380	    run_date = run_date or date.today().isoformat()
   381	    flags = result["flags"]
   382	    row = {
   383	        "run_date": run_date,
   384	        "ticker": result["ticker"],
   385	        "tier": result["tier"],
   386	        "flag_details": result.get("flag_details", ""),
   387	        "run_id": run_id,
   388	        "status": result.get("status", "complete"),
   389	        "schema_version": SCHEMA_VERSION,
   390	    }
   391	    for fam in FAMILIES:
   392	        row[f"{fam}_flag"] = int(flags.get(fam, 0))
   393	    return {col: row.get(col, "") for col in HISTORY_COLUMNS}
   394	
   395	
   396	def append_history(rows: list[dict], path: Path = FLAGS_HISTORY_CSV) -> None:
   397	    """Append rows to flags_history.csv, migrating the header to the v16 column set if needed."""
   398	    path.parent.mkdir(parents=True, exist_ok=True)
   399	    existing_header = None
   400	    if path.exists():
   401	        with path.open(encoding="utf-8", newline="") as f:
   402	            r = csv.reader(f)
   403	            existing_header = next(r, None)
   404	    write_header = (existing_header != HISTORY_COLUMNS)
   405	
   406	    if existing_header is not None and write_header:
   407	        _migrate_history_header(path)
   408	        write_header = False
   409	
   410	    with path.open("a", encoding="utf-8", newline="") as f:
   411	        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
   412	        if write_header or not path.exists():
   413	            w.writeheader()
   414	        for row in rows:
   415	            w.writerow({col: row.get(col, "") for col in HISTORY_COLUMNS})
   416	
   417	
   418	def _migrate_history_header(path: Path) -> None:
   419	    """Rewrite an old (13-col) flags_history.csv to the v16 schema, defaulting the new columns."""
   420	    with path.open(encoding="utf-8", newline="") as f:
   421	        rows = list(csv.DictReader(f))
   422	    with path.open("w", encoding="utf-8", newline="") as f:
   423	        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
   424	        w.writeheader()
   425	        for row in rows:
   426	            row.setdefault("run_id", "legacy")
   427	            row.setdefault("status", "complete")
   428	            row.setdefault("schema_version", "")
   429	            w.writerow({col: row.get(col, "") for col in HISTORY_COLUMNS})
   430	
     1	"""Pick the next batch of names to screen — the daily "a few each day" driver.
     2	
     3	Path B (interactive) chips through the ~274 domestic watchlist names a few at a
     4	time. This deterministic helper picks the next batch so each session knows exactly
     5	what to screen, prioritised toward JP's coverage:
     6	
     7	  1. core=Y first (names JP analytically covers)
     8	  2. then by subgroup: hc_services -> medtech -> general (HC focus)
     9	  3. then alphabetical
    10	
    11	A name is "done this cycle" once it has a flags_history row dated >= CYCLE_START
    12	(the recalibration baseline) WITH status=complete (codex R2 idempotency). A row
    13	written by a transient fetch failure (status=fetch_failed) does NOT mark the name
    14	done — it retries next run. A structural Data Gap (foreign/stale/not-disclosed) is
    15	written status=complete and IS done. Older rows without a status column are treated
    16	as complete (back-compat). Foreign filers (filer_type=foreign) are never screened by
    17	EDGAR — they belong to the Data Gap tier — so they're excluded here and reported separately.
    18	
    19	Usage:
    20	  python next_batch.py            # show the next batch (default 8) + progress
    21	  python next_batch.py -n 5       # batch of 5
    22	  python next_batch.py --cycle-start 2026-06-20
    23	"""
    24	from __future__ import annotations
    25	
    26	import argparse
    27	import csv
    28	from pathlib import Path
    29	
    30	ROOT = Path(__file__).parent
    31	WATCHLIST_CSV = ROOT / "data" / "watchlist.csv"
    32	FLAGS_HISTORY_CSV = ROOT / "data" / "flags_history.csv"
    33	
    34	# Names screened on/after this date count as done for the current cycle. Bump it
    35	# when a fresh full re-screen cycle starts. Default = the 2026-06-20 recalibration.
    36	DEFAULT_CYCLE_START = "2026-06-20"
    37	
    38	SUBGROUP_ORDER = {"hc_services": 0, "medtech": 1, "general": 2}
    39	
    40	
    41	def load_watchlist() -> list[dict]:
    42	    with WATCHLIST_CSV.open(encoding="utf-8", newline="") as f:
    43	        return list(csv.DictReader(f))
    44	
    45	
    46	def screened_since(cycle_start: str) -> set[str]:
    47	    """Tickers DONE this cycle: a flags_history row dated >= cycle_start with status=complete.
    48	
    49	    A `status=fetch_failed` row does NOT count as done (transient failure retries next run).
    50	    Rows without a `status` column (legacy interactive runs) are treated as complete."""
    51	    if not FLAGS_HISTORY_CSV.exists():
    52	        return set()
    53	    done: set[str] = set()
    54	    with FLAGS_HISTORY_CSV.open(encoding="utf-8", newline="") as f:
    55	        reader = csv.DictReader(f)
    56	        has_status = "status" in (reader.fieldnames or [])
    57	        for row in reader:
    58	            if (row.get("run_date") or "") < cycle_start or not row.get("ticker"):
    59	                continue
    60	            status = (row.get("status") or "").strip() if has_status else "complete"
    61	            if status in ("", "complete"):
    62	                done.add(row["ticker"].strip())
    63	    return done
    64	
    65	
    66	def sort_key(row: dict):
    67	    core_rank = 0 if (row.get("core", "").strip().upper() == "Y") else 1
    68	    sg_rank = SUBGROUP_ORDER.get(row.get("sector_subgroup", ""), 9)
    69	    return (core_rank, sg_rank, row.get("ticker", ""))
    70	
    71	
    72	def main() -> int:
    73	    p = argparse.ArgumentParser(description=__doc__)
    74	    p.add_argument("-n", "--batch-size", type=int, default=8, help="How many names this batch")
    75	    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START,
    76	                   help=f"Names screened on/after this date count as done (default {DEFAULT_CYCLE_START})")
    77	    args = p.parse_args()
    78	
    79	    watchlist = load_watchlist()
    80	    domestic = [r for r in watchlist if r.get("filer_type", "domestic") != "foreign"]
    81	    foreign = [r for r in watchlist if r.get("filer_type") == "foreign"]
    82	    done = screened_since(args.cycle_start)
    83	
    84	    pending = [r for r in domestic if r["ticker"].strip() not in done]
    85	    pending.sort(key=sort_key)
    86	
    87	    n_dom = len(domestic)
    88	    n_done = sum(1 for r in domestic if r["ticker"].strip() in done)
    89	    print(f"Cycle start: {args.cycle_start}")
    90	    print(f"Domestic screened this cycle: {n_done}/{n_dom}  ({n_dom - n_done} pending)")
    91	    print(f"Foreign (Data Gap, not EDGAR-screened): {len(foreign)}")
    92	    print()
    93	    if not pending:
    94	        print("Cycle complete — every domestic name screened since cycle start. Bump --cycle-start to re-screen.")
    95	        return 0
    96	
    97	    batch = pending[:args.batch_size]
    98	    print(f"Next batch ({len(batch)}):")
    99	    for r in batch:
   100	        core = "core" if r.get("core", "").strip().upper() == "Y" else "    "
   101	        print(f"  {r['ticker']:<6} [{core}] {r['sector_subgroup']:<12} {r.get('company_name','')}")
   102	    return 0
   103	
   104	
   105	if __name__ == "__main__":
   106	    raise SystemExit(main())
     1	"""Per-run orchestrator for the unattended (Path A) forensic screen.
     2	
     3	Ties the pipeline together (PATH_A_PLAN step 5):
     4	  next_batch  ->  edgar_fetch (per ticker)  ->  tier_batch (Anthropic judge + guardrails)
     5	              ->  append flags_history       ->  write a compact report
     6	              ->  (separately) notify Slack.
     7	
     8	The git commit/push happens in the WORKFLOW between the screen step and the notify step (so the
     9	commit hash is known); this script writes a small `data/last_run.json` the notify step reads for
    10	the commit + results. The script NEVER spends API budget when run with --notify-only / --failure-alarm.
    11	
    12	Modes:
    13	  (default)         run the screen: fetch + tier + history + report, write last_run.json
    14	  --notify-only     read last_run.json + post #forensic-flags result + #status-reports heartbeat
    15	  --failure-alarm   post a loud failure alarm to #status-reports (the if: failure() path)
    16	
    17	Run-level circuit breaker: if the batch can't be evaluated (broad outage), exit non-zero so the
    18	workflow's `if: failure()` alarm fires and NO batch of false Data Gaps is committed.
    19	"""
    20	from __future__ import annotations
    21	
    22	import argparse
    23	import json
    24	import os
    25	import subprocess
    26	import sys
    27	from datetime import date
    28	from pathlib import Path
    29	
    30	ROOT = Path(__file__).parent
    31	sys.path.insert(0, str(ROOT))
    32	
    33	import edgar_fetch  # noqa: E402
    34	import notify  # noqa: E402
    35	import tier_batch  # noqa: E402
    36	from forensic_schema import FAMILIES  # noqa: E402
    37	
    38	DATA = ROOT / "data"
    39	REPORTS = ROOT / "reports"
    40	LAST_RUN = DATA / "last_run.json"
    41	WATCHLIST = DATA / "watchlist.csv"
    42	DEFAULT_CYCLE_START = "2026-06-20"
    43	
    44	
    45	def _load_watchlist() -> dict[str, dict]:
    46	    import csv
    47	    out = {}
    48	    if WATCHLIST.exists():
    49	        with WATCHLIST.open(encoding="utf-8", newline="") as f:
    50	            for row in csv.DictReader(f):
    51	                out[(row.get("ticker") or "").upper()] = row
    52	    return out
    53	
    54	
    55	def _pick_batch(n: int, cycle_start: str) -> list[str]:
    56	    """Next n un-screened domestic names (reuse next_batch's selection logic)."""
    57	    import next_batch as nb
    58	    watch = nb.load_watchlist()
    59	    domestic = [r for r in watch if r.get("filer_type", "domestic") != "foreign"]
    60	    done = nb.screened_since(cycle_start)
    61	    pending = [r for r in domestic if r["ticker"].strip() not in done]
    62	    pending.sort(key=nb.sort_key)
    63	    return [r["ticker"].strip().upper() for r in pending[:n]]
    64	
    65	
    66	def run_screen(*, batch_size: int, run_id: str, cycle_start: str) -> int:
    67	    wl = _load_watchlist()
    68	    tickers = _pick_batch(batch_size, cycle_start)
    69	    if not tickers:
    70	        print("Cycle complete — no pending domestic names. Nothing to screen.")
    71	        _write_last_run(run_id=run_id, results=[], note="cycle complete (no pending names)")
    72	        return 0
    73	
    74	    print(f"Run {run_id}: screening {len(tickers)} names: {', '.join(tickers)}")
    75	    new_set = tier_batch._new_names()
    76	
    77	    results = []
    78	    for ticker in tickers:
    79	        row = wl.get(ticker, {})
    80	        cik = (row.get("cik") or "").strip()
    81	        subgroup = row.get("sector_subgroup") or "general"
    82	        filer_type = row.get("filer_type") or "domestic"
    83	
    84	        # 1. fetch (never raises)
    85	        rec = edgar_fetch.fetch_ticker(
    86	            ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=run_id,
    87	        )
    88	        edgar_fetch.write_record(rec, edgar_fetch.DEFAULT_OUT_DIR)
    89	
    90	        # 2. tier (Anthropic judge + deterministic guardrails)
    91	        res = tier_batch.tier_one(rec, subgroup=subgroup, is_new=(ticker in new_set))
    92	        results.append(res)
    93	        print(f"  {ticker:<6} {res['tier']:<16} status={res['status']}  {res['reason']}")
    94	
    95	    # 3. run-level circuit breaker (broad outage -> fail loudly, commit nothing)
    96	    tripped, why = tier_batch.circuit_breaker_tripped(results)
    97	    if tripped:
    98	        print(f"\nCIRCUIT BREAKER TRIPPED: {why}")
    99	        _write_last_run(run_id=run_id, results=results, note=f"CIRCUIT BREAKER: {why}", ok=False)
   100	        # Non-zero exit so the workflow alarms and skips the commit.
   101	        return 2
   102	
   103	    # 4. append history (only complete + fetch_failed rows; fetch_failed retries next run)
   104	    rows = [tier_batch.result_to_history_row(r, run_id=run_id) for r in results]
   105	    tier_batch.append_history(rows)
   106	
   107	    # 5. compact report
   108	    report_path = _write_report(results, run_id=run_id)
   109	    print(f"\nWrote report {report_path}; appended {len(rows)} history rows.")
   110	
   111	    _write_last_run(run_id=run_id, results=results, note="ok", ok=True)
   112	    return 0
   113	
   114	
   115	def _counts(results: list[dict]) -> dict:
   116	    c: dict[str, int] = {}
   117	    for r in results:
   118	        c[r["tier"]] = c.get(r["tier"], 0) + 1
   119	    return c
   120	
   121	
   122	def _missing_required(results: list[dict]) -> int:
   123	    n = 0
   124	    for r in results:
   125	        cov = r.get("coverage", {})
   126	        if any(cov.get(f) not in ("complete", "not_applicable", None) for f in FAMILIES):
   127	            # any non-complete required-ish family -> count as a name with a coverage gap
   128	            from forensic_schema import required_families
   129	            sg = r.get("subgroup", "general")
   130	            if any(cov.get(f, "unavailable") not in ("complete", "not_applicable")
   131	                   for f in required_families(sg)):
   132	                n += 1
   133	    return n
   134	
   135	
   136	def _write_report(results: list[dict], *, run_id: str) -> Path:
   137	    REPORTS.mkdir(parents=True, exist_ok=True)
   138	    today = date.today().isoformat()
   139	    path = REPORTS / f"forensic_{today}.md"
   140	    lines = [f"# Forensic Triage — {today}", "", f"_run_id {run_id}_", ""]
   141	
   142	    def section(tier: str, title: str):
   143	        names = [r for r in results if r["tier"] == tier]
   144	        if not names:
   145	            return
   146	        lines.append(f"## {title}")
   147	        lines.append("| Ticker | Subgroup | Flags fired | Reason | Concerns |")
   148	        lines.append("|---|---|---|---|---|")
   149	        for r in names:
   150	            fired = ", ".join(f for f in r["flags"] if r["flags"].get(f)) or "-"
   151	            concerns = "; ".join((r.get("concerns") or [])[:3]).replace("|", "/")
   152	            lines.append(f"| {r['ticker']} | {r['subgroup']} | {fired} | {r['reason']} | {concerns} |")
   153	        lines.append("")
   154	
   155	    section("Red", "Red (deep dive)")
   156	    section("Yellow", "Yellow (watch)")
   157	    section("DataGap", "Data Gap (manual review — NOT screened)")
   158	    section("CorporateAction", "Corporate Action (flag for removal)")
   159	    greens = [r["ticker"] for r in results if r["tier"] == "Green"]
   160	    if greens:
   161	        lines.append(f"## Green (evaluated clean)\n\n{', '.join(greens)}\n")
   162	    # Append (don't overwrite a same-day earlier run)
   163	    mode = "a" if path.exists() else "w"
   164	    with path.open(mode, encoding="utf-8") as f:
   165	        if mode == "a":
   166	            f.write("\n\n---\n\n")
   167	        f.write("\n".join(lines))
   168	    return path
   169	
   170	
   171	def _write_last_run(*, run_id: str, results: list[dict], note: str = "", ok: bool = True) -> None:
   172	    DATA.mkdir(parents=True, exist_ok=True)
   173	    # Strip the bulky coverage map down for the notify payload; keep what the cards need.
   174	    slim = [
   175	        {
   176	            "ticker": r["ticker"], "subgroup": r["subgroup"], "tier": r["tier"],
   177	            "reason": r["reason"], "flags": r["flags"], "concerns": r.get("concerns", []),
   178	            "status": r.get("status", "complete"), "coverage": r.get("coverage", {}),
   179	        }
   180	        for r in results
   181	    ]
   182	    payload = {
   183	        "run_id": run_id, "run_date": date.today().isoformat(),
   184	        "ok": ok, "note": note, "results": slim,
   185	    }
   186	    with LAST_RUN.open("w", encoding="utf-8") as f:
   187	        json.dump(payload, f, indent=2)
   188	
   189	
   190	def _read_last_run() -> dict:
   191	    if not LAST_RUN.exists():
   192	        return {}
   193	    with LAST_RUN.open(encoding="utf-8") as f:
   194	        return json.load(f)
   195	
   196	
   197	def _git_head() -> str:
   198	    try:
   199	        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
   200	    except Exception:  # noqa: BLE001
   201	        return ""
   202	
   203	
   204	def notify_only(*, run_id: str) -> int:
   205	    data = _read_last_run()
   206	    results = data.get("results", [])
   207	    run_date = data.get("run_date", date.today().isoformat())
   208	    commit = _git_head()
   209	
   210	    ok_f, det_f = notify.post_forensic(results, run_id=run_id, run_date=run_date, commit=commit)
   211	    counts = _counts(results)
   212	    missing = _missing_required(results)
   213	    ok_h, det_h = notify.post_heartbeat(
   214	        run_id=run_id, run_date=run_date, n_screened=len(results), counts=counts,
   215	        missing_required=missing, commit=commit, ok=data.get("ok", True), note=data.get("note", ""),
   216	    )
   217	    print(f"forensic post: ok={ok_f} {det_f}")
   218	    print(f"heartbeat post: ok={ok_h} {det_h}")
   219	    # Don't fail the workflow if Slack is flaky — the data is already committed.
   220	    return 0
   221	
   222	
   223	def failure_alarm(*, run_id: str, error: str) -> int:
   224	    ok, det = notify.post_failure_alarm(
   225	        run_id=run_id, run_date=date.today().isoformat(), error=error,
   226	    )
   227	    print(f"failure alarm: ok={ok} {det}")
   228	    return 0
   229	
   230	
   231	def main(argv=None) -> int:
   232	    p = argparse.ArgumentParser(description=__doc__)
   233	    p.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "6")))
   234	    p.add_argument("--run-id", default="manual")
   235	    p.add_argument("--cycle-start", default=DEFAULT_CYCLE_START)
   236	    p.add_argument("--notify-only", action="store_true")
   237	    p.add_argument("--failure-alarm", action="store_true")
   238	    p.add_argument("--error", default="run failed")
   239	    args = p.parse_args(argv)
   240	
   241	    if args.notify_only:
   242	        return notify_only(run_id=args.run_id)
   243	    if args.failure_alarm:
   244	        return failure_alarm(run_id=args.run_id, error=args.error)
   245	    return run_screen(batch_size=args.batch_size, run_id=args.run_id, cycle_start=args.cycle_start)
   246	
   247	
   248	if __name__ == "__main__":
   249	    raise SystemExit(main())
     1	"""Slack notifications for the unattended forensic screen (Path A).
     2	
     3	Two destinations:
     4	  - #forensic-flags  (SLACK_WEBHOOK_FORENSIC)        — the screen results, Block Kit.
     5	  - #status-reports  (SLACK_WEBHOOK_STATUS_REPORTS)  — a v1 health heartbeat.
     6	
     7	Block Kit GOTCHA (memory: reference_slack_context_block_elements): a `context` block uses
     8	`elements[]`, NOT a `text` field — a `text` field there => webhook HTTP 400 invalid_blocks.
     9	This module only ever builds context blocks with `elements[]`.
    10	
    11	Webhook URLs come from the environment; NO hardcoded secrets, and we never log a URL.
    12	"""
    13	from __future__ import annotations
    14	
    15	import json
    16	import os
    17	import urllib.error
    18	import urllib.request
    19	
    20	FORENSIC_ENV = "SLACK_WEBHOOK_FORENSIC"
    21	STATUS_ENV = "SLACK_WEBHOOK_STATUS_REPORTS"
    22	
    23	TIER_EMOJI = {
    24	    "Red": ":red_circle:",
    25	    "Yellow": ":large_yellow_circle:",
    26	    "Green": ":large_green_circle:",
    27	    "DataGap": ":black_circle:",
    28	    "CorporateAction": ":arrows_counterclockwise:",
    29	}
    30	
    31	
    32	def _post(webhook_url: str, payload: dict, *, timeout: int = 15) -> tuple[bool, str]:
    33	    """POST a Block Kit payload. Returns (ok, detail). NEVER raises, NEVER logs the URL."""
    34	    if not webhook_url:
    35	        return False, "no webhook url configured"
    36	    data = json.dumps(payload).encode("utf-8")
    37	    req = urllib.request.Request(
    38	        webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    39	    )
    40	    try:
    41	        with urllib.request.urlopen(req, timeout=timeout) as resp:
    42	            body = resp.read().decode("utf-8", "replace")
    43	            return (resp.status == 200, f"HTTP {resp.status}: {body[:200]}")
    44	    except urllib.error.HTTPError as exc:
    45	        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    46	    except Exception as exc:  # noqa: BLE001 — never let a Slack failure crash the run
    47	        return False, f"{type(exc).__name__}: {exc}"
    48	
    49	
    50	def _context(*lines: str) -> dict:
    51	    """A context block — ALWAYS elements[] (never a top-level text field)."""
    52	    return {"type": "context", "elements": [{"type": "mrkdwn", "text": line} for line in lines]}
    53	
    54	
    55	# --------------------------------------------------------------------------------------
    56	# #forensic-flags result card
    57	# --------------------------------------------------------------------------------------
    58	def build_forensic_blocks(results: list[dict], *, run_id: str, run_date: str, commit: str = "") -> list[dict]:
    59	    counts: dict[str, int] = {}
    60	    for r in results:
    61	        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
    62	    summary = "  ".join(f"{TIER_EMOJI.get(t, '')} {t}: {counts.get(t, 0)}" for t in
    63	                        ("Red", "Yellow", "Green", "DataGap", "CorporateAction"))
    64	
    65	    blocks: list[dict] = [
    66	        {"type": "header", "text": {"type": "plain_text", "text": f"Forensic Triage — {run_date}"}},
    67	        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    68	    ]
    69	
    70	    def section_for(tier: str, title: str):
    71	        names = [r for r in results if r["tier"] == tier]
    72	        if not names:
    73	            return
    74	        blocks.append({"type": "divider"})
    75	        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}})
    76	        for r in names:
    77	            fired = [f for f in r["flags"] if r["flags"].get(f)]
    78	            line = f"• *{r['ticker']}* ({r['subgroup']}) — {r.get('reason', '')}"
    79	            if fired:
    80	                line += f"\n   flags: {', '.join(fired)}"
    81	            concerns = r.get("concerns") or []
    82	            if concerns:
    83	                line += "\n   " + "; ".join(c for c in concerns[:3])
    84	            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line[:2900]}})
    85	
    86	    section_for("Red", "Red — deep dive")
    87	    section_for("Yellow", "Yellow — watch")
    88	    section_for("DataGap", "Data Gap — manual review (NOT screened)")
    89	    section_for("CorporateAction", "Corporate Action — flag for removal")
    90	    # Green names listed compactly (no per-name section).
    91	    greens = [r["ticker"] for r in results if r["tier"] == "Green"]
    92	    if greens:
    93	        blocks.append({"type": "divider"})
    94	        blocks.append(_context(f"Green ({len(greens)}): " + ", ".join(greens)))
    95	
    96	    foot = f"run_id `{run_id}`"
    97	    if commit:
    98	        foot += f" · commit `{commit[:8]}`"
    99	    blocks.append(_context(foot))
   100	    return blocks
   101	
   102	
   103	def post_forensic(results: list[dict], *, run_id: str, run_date: str, commit: str = "",
   104	                  webhook_url: str | None = None) -> tuple[bool, str]:
   105	    url = webhook_url if webhook_url is not None else os.environ.get(FORENSIC_ENV, "")
   106	    blocks = build_forensic_blocks(results, run_id=run_id, run_date=run_date, commit=commit)
   107	    return _post(url, {"blocks": blocks})
   108	
   109	
   110	# --------------------------------------------------------------------------------------
   111	# #status-reports heartbeat (v1; Block Kit, context uses elements[])
   112	# --------------------------------------------------------------------------------------
   113	def build_heartbeat_blocks(*, run_id: str, run_date: str, n_screened: int, counts: dict,
   114	                           missing_required: int, commit: str = "", ok: bool = True,
   115	                           note: str = "") -> list[dict]:
   116	    status = ":white_check_mark: healthy" if ok else ":rotating_light: FAILED"
   117	    tier_line = "  ".join(f"{t}: {counts.get(t, 0)}" for t in
   118	                          ("Red", "Yellow", "Green", "DataGap", "CorporateAction"))
   119	    lines = [
   120	        f"*forensic_triage* — {status}",
   121	        f"{run_date} · run_id `{run_id}` · screened {n_screened}",
   122	        tier_line,
   123	        f"missing-required-family names: {missing_required}",
   124	    ]
   125	    if commit:
   126	        lines.append(f"commit `{commit[:8]}`")
   127	    if note:
   128	        lines.append(note)
   129	    return [
   130	        {"type": "section", "text": {"type": "mrkdwn", "text": "*Forensic Triage heartbeat*"}},
   131	        _context(*lines),
   132	    ]
   133	
   134	
   135	def post_heartbeat(*, run_id: str, run_date: str, n_screened: int, counts: dict,
   136	                   missing_required: int, commit: str = "", ok: bool = True, note: str = "",
   137	                   webhook_url: str | None = None) -> tuple[bool, str]:
   138	    url = webhook_url if webhook_url is not None else os.environ.get(STATUS_ENV, "")
   139	    blocks = build_heartbeat_blocks(
   140	        run_id=run_id, run_date=run_date, n_screened=n_screened, counts=counts,
   141	        missing_required=missing_required, commit=commit, ok=ok, note=note,
   142	    )
   143	    return _post(url, {"blocks": blocks})
   144	
   145	
   146	def post_failure_alarm(*, run_id: str, run_date: str, error: str,
   147	                       webhook_url: str | None = None) -> tuple[bool, str]:
   148	    """Loud failure alarm to #status-reports (the if: failure() path)."""
   149	    url = webhook_url if webhook_url is not None else os.environ.get(STATUS_ENV, "")
   150	    blocks = [
   151	        {"type": "section", "text": {"type": "mrkdwn", "text": ":rotating_light: *forensic_triage run FAILED*"}},
   152	        _context(f"{run_date} · run_id `{run_id}`", f"error: {error[:400]}"),
   153	    ]
   154	    return _post(url, {"blocks": blocks})
   155	
   156	
   157	if __name__ == "__main__":  # pragma: no cover — manual smoke (prints blocks, posts nothing)
   158	    import argparse
   159	
   160	    ap = argparse.ArgumentParser(description="Print the Block Kit payloads (no Slack post).")
   161	    ap.add_argument("--demo", action="store_true")
   162	    ap.parse_args()
   163	    demo = [
   164	        {"ticker": "ACME", "subgroup": "hc_services", "tier": "Red", "reason": "critical governance (auto-Red)",
   165	         "flags": {f: 0 for f in __import__("forensic_schema").FAMILIES}, "concerns": ["8-K 4.02 non-reliance filed 2026-05"]},
   166	    ]
   167	    print(json.dumps({"blocks": build_forensic_blocks(demo, run_id="demo", run_date="2026-06-24")}, indent=2))
   168	    print(json.dumps({"blocks": build_heartbeat_blocks(run_id="demo", run_date="2026-06-24",
   169	          n_screened=1, counts={"Red": 1}, missing_required=0)}, indent=2))
     1	name: Forensic Triage (unattended)
     2	
     3	# Path A: GitHub Actions cron + Anthropic-API tiering (PATH_A_PLAN v3).
     4	# Screens a few domestic names per run, posts Red/Yellow/Green/Data-Gap to #forensic-flags,
     5	# heartbeats to #status-reports, and commits the compact report + history (never the big
     6	# fetched JSON — data/fetched/ is gitignored).
     7	
     8	on:
     9	  schedule:
    10	    # 18:30 UTC weekdays (~13:30 ET winter / 14:30 ET summer — after the SEC filing day).
    11	    - cron: '30 18 * * 1-5'
    12	  workflow_dispatch:
    13	    inputs:
    14	      batch_size:
    15	        description: 'How many names to screen this run'
    16	        required: false
    17	        default: '6'
    18	
    19	concurrency:
    20	  group: forensic-triage
    21	  cancel-in-progress: false
    22	
    23	permissions:
    24	  contents: write
    25	
    26	jobs:
    27	  screen:
    28	    runs-on: ubuntu-latest
    29	    env:
    30	      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    31	      EDGARTOOLS_API_KEY: ${{ secrets.EDGARTOOLS_API_KEY }}
    32	      EDGAR_IDENTITY: ${{ secrets.EDGAR_IDENTITY }}
    33	      SLACK_WEBHOOK_FORENSIC: ${{ secrets.SLACK_WEBHOOK_FORENSIC }}
    34	      SLACK_WEBHOOK_STATUS_REPORTS: ${{ secrets.SLACK_WEBHOOK_STATUS_REPORTS }}
    35	      BATCH_SIZE: ${{ github.event.inputs.batch_size || '6' }}
    36	
    37	    steps:
    38	      - name: Checkout repo
    39	        uses: actions/checkout@v5
    40	
    41	      - name: Set up Python
    42	        uses: actions/setup-python@v6
    43	        with:
    44	          python-version: '3.12'
    45	
    46	      - name: Install dependencies
    47	        run: pip install -r requirements.txt
    48	
    49	      - name: Run unattended screen
    50	        id: screen
    51	        run: python run_unattended.py --batch-size "$BATCH_SIZE" --run-id "${{ github.run_id }}"
    52	
    53	      - name: Commit and push report + history
    54	        if: success()
    55	        run: |
    56	          git config user.name "github-actions[bot]"
    57	          git config user.email "github-actions[bot]@users.noreply.github.com"
    58	          git add data/flags_history.csv reports/ data/ratios_latest.csv 2>/dev/null || true
    59	          if git diff --cached --quiet; then
    60	            echo "No changes to commit."
    61	          else
    62	            git commit -m "Forensic triage run ${{ github.run_id }} [skip ci]"
    63	            # rebase-before-push (fleet pattern) to avoid races with other pushers
    64	            for i in 1 2 3; do
    65	              git pull --rebase --autostash origin main && git push origin main && break
    66	              echo "push attempt $i failed; retrying"
    67	              sleep 5
    68	            done
    69	          fi
    70	
    71	      - name: Notify Slack (results + heartbeat)
    72	        if: success()
    73	        run: python run_unattended.py --notify-only --run-id "${{ github.run_id }}"
    74	
    75	      - name: Failure alarm to #status-reports
    76	        if: failure()
    77	        run: python run_unattended.py --failure-alarm --run-id "${{ github.run_id }}" --error "workflow step failed (see Actions log)"

exec
/bin/bash -lc "nl -ba edgar_fetch.py | sed -n '185,235p'; nl -ba run_unattended.py | sed -n '80,98p'; nl -ba tier_batch.py | sed -n '221,229p'" in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 0ms:
   185	
   186	# --------------------------------------------------------------------------------------
   187	# coverage classification (the false-Green guard's core)
   188	# --------------------------------------------------------------------------------------
   189	def _classify_coverage(rec: dict, subgroup: str) -> dict:
   190	    """Map what we actually fetched to the per-family COVERAGE enum.
   191	
   192	    Required financial families need statements; governance needs the 8-K feed; the
   193	    note-backed checks need note bodies. Anything we FAILED to fetch -> unavailable
   194	    (blocks Green). Structurally-unreachable-unattended families (market short interest,
   195	    text MD&A diffs) -> not_evaluated.
   196	    """
   197	    cov: dict[str, str] = {}
   198	
   199	    have_statements = bool(rec["statements"]["annual"]) or rec["ratios"] is not None
   200	    have_8k = isinstance(rec["events_8k"], list) and (
   201	        rec.get("_events_8k_fetched") is True
   202	    )
   203	
   204	    def note_ok(*topics: str) -> bool:
   205	        """A note family is 'evaluable' if at least one backing note was either read OR
   206	        legitimately not-disclosed. Only a fetch_failure makes it unavailable."""
   207	        statuses = [rec["notes"].get(t, {}).get("status", "fetch_failed") for t in topics]
   208	        if not statuses:
   209	            return False
   210	        return all(s in ("present", "not_disclosed") for s in statuses)
   211	
   212	    # Financial families lean on statements.
   213	    fin_state = "complete" if have_statements else "unavailable"
   214	    cov["accruals"] = fin_state
   215	    cov["revenue"] = "complete" if (have_statements and note_ok("Revenue", "Significant Accounting Policies")) else ("partial" if have_statements else "unavailable")
   216	    cov["capex"] = fin_state
   217	    cov["balance_sheet"] = "complete" if (have_statements and note_ok("Inventory", "Goodwill")) else ("partial" if have_statements else "unavailable")
   218	    cov["leverage"] = "complete" if (have_statements and note_ok("Debt")) else ("partial" if have_statements else "unavailable")
   219	
   220	    # Governance: needs the 8-K feed (item codes). If neither REST nor edgartools delivered it -> unavailable.
   221	    cov["governance"] = "complete" if have_8k else "unavailable"
   222	
   223	    # Market + text are OPTIONAL (not reachable unattended) -> not_evaluated (never blocks Green).
   224	    cov["market"] = "partial" if rec["insider"].get("status") == "present" else "not_evaluated"
   225	    cov["text"] = "not_evaluated"
   226	
   227	    # Sector: required for hc/medtech (note-backed, reachable); not_applicable for general.
   228	    if subgroup == "general":
   229	        cov["sector"] = "not_applicable"
   230	    else:
   231	        cov["sector"] = "complete" if note_ok("Significant Accounting Policies", "Commitments") else (
   232	            "partial" if any(rec["notes"].get(t, {}).get("status") == "present"
   233	                             for t in ("Inventory", "Revenue", "Commitments")) else "unavailable"
   234	        )
   235	
    80	        cik = (row.get("cik") or "").strip()
    81	        subgroup = row.get("sector_subgroup") or "general"
    82	        filer_type = row.get("filer_type") or "domestic"
    83	
    84	        # 1. fetch (never raises)
    85	        rec = edgar_fetch.fetch_ticker(
    86	            ticker, cik, subgroup=subgroup, filer_type=filer_type, run_id=run_id,
    87	        )
    88	        edgar_fetch.write_record(rec, edgar_fetch.DEFAULT_OUT_DIR)
    89	
    90	        # 2. tier (Anthropic judge + deterministic guardrails)
    91	        res = tier_batch.tier_one(rec, subgroup=subgroup, is_new=(ticker in new_set))
    92	        results.append(res)
    93	        print(f"  {ticker:<6} {res['tier']:<16} status={res['status']}  {res['reason']}")
    94	
    95	    # 3. run-level circuit breaker (broad outage -> fail loudly, commit nothing)
    96	    tripped, why = tier_batch.circuit_breaker_tripped(results)
    97	    if tripped:
    98	        print(f"\nCIRCUIT BREAKER TRIPPED: {why}")
   221	    last_err = None
   222	    for _ in range(MAX_VALIDATION_RETRIES + 1):
   223	        response = _create_with_fallback(client, base_kwargs)
   224	        if getattr(response, "stop_reason", None) == "refusal":
   225	            raise JudgeValidationError("model refused (stop_reason=refusal)")
   226	        try:
   227	            text = _extract_json_text(response)
   228	            obj = json.loads(text)
   229	            return validate_judge_output(obj, ticker)

exec
/bin/bash -lc pwd in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 0ms:
/mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage

exec
/bin/bash -lc "nl -ba tests/test_tier_guardrails.py | sed -n '1,260p'; nl -ba tests/test_edgar_fetch.py | sed -n '1,260p'" in /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage
 succeeded in 0ms:
     1	"""Tests for tier_batch.py — the Anthropic-judge wrapper + deterministic guardrails.
     2	
     3	The Anthropic API is NEVER called. Either a mock client is injected, or the judge verdict is
     4	passed directly via tier_one(judge=...). Covers:
     5	  - structured-output validation (malformed rejection, fail-closed)
     6	  - Green-eligibility gate + precedence (via tier_one + finalize_tier)
     7	  - critical-gov / high-severity OVERRIDE a Data Gap
     8	  - idempotency status (fetch_failed vs complete; structural gap = complete)
     9	  - run-level circuit breaker
    10	  - flags_history migration (13-col -> 16-col)
    11	"""
    12	from __future__ import annotations
    13	
    14	import csv
    15	import sys
    16	from pathlib import Path
    17	
    18	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    19	
    20	import tier_batch  # noqa: E402
    21	from forensic_schema import FAMILIES, HISTORY_COLUMNS  # noqa: E402
    22	
    23	
    24	def _flags(*fired):
    25	    return {f: (1 if f in fired else 0) for f in FAMILIES}
    26	
    27	
    28	def _verdict(*fired, critical=False, high=False, corp=None, concerns=None, details=""):
    29	    return {
    30	        "ticker": "ACME",
    31	        "flags": _flags(*fired),
    32	        "critical_governance": critical,
    33	        "high_severity": high,
    34	        "corporate_action": corp,
    35	        "concerns": concerns or [],
    36	        "flag_details": details,
    37	    }
    38	
    39	
    40	def _record(subgroup="hc_services", *, coverage=None, filer_type="domestic",
    41	            stale=False, source_errors=None):
    42	    cov = {f: "complete" for f in FAMILIES}
    43	    cov["sector"] = "complete" if subgroup != "general" else "not_applicable"
    44	    if coverage:
    45	        cov.update(coverage)
    46	    return {
    47	        "ticker": "ACME",
    48	        "filer_type": filer_type,
    49	        "family_coverage": cov,
    50	        "staleness": {"is_stale": stale, "reason": ("latest 10-K period_end 2023-12-31 is 600d old (> 400)" if stale else "ok")},
    51	        "source_errors": source_errors or [],
    52	    }
    53	
    54	
    55	# --- structured-output validation ------------------------------------------------------
    56	def test_validate_rejects_non_binary_flag():
    57	    bad = _verdict()
    58	    bad["flags"]["accruals"] = 2
    59	    try:
    60	        tier_batch.validate_judge_output(bad, "ACME")
    61	        assert False, "should have raised"
    62	    except tier_batch.JudgeValidationError:
    63	        pass
    64	
    65	
    66	def test_validate_rejects_missing_family():
    67	    bad = _verdict()
    68	    del bad["flags"]["leverage"]
    69	    try:
    70	        tier_batch.validate_judge_output(bad, "ACME")
    71	        assert False
    72	    except tier_batch.JudgeValidationError:
    73	        pass
    74	
    75	
    76	def test_validate_rejects_bad_severity_type():
    77	    bad = _verdict()
    78	    bad["critical_governance"] = "yes"
    79	    try:
    80	        tier_batch.validate_judge_output(bad, "ACME")
    81	        assert False
    82	    except tier_batch.JudgeValidationError:
    83	        pass
    84	
    85	
    86	def test_validate_accepts_clean():
    87	    ok = tier_batch.validate_judge_output(_verdict("revenue"), "ACME")
    88	    assert ok["flags"]["revenue"] == 1
    89	
    90	
    91	# --- call_judge fail-closed after retries (mock client returning garbage) --------------
    92	class _GarbageClient:
    93	    class _Msgs:
    94	        def create(self, **kw):
    95	            class R:
    96	                stop_reason = "end_turn"
    97	                content = [type("B", (), {"type": "text", "text": "not json at all"})()]
    98	            return R()
    99	    def __init__(self):
   100	        self.messages = self._Msgs()
   101	
   102	
   103	def test_call_judge_fails_closed_on_garbage():
   104	    try:
   105	        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=_GarbageClient())
   106	        assert False, "should raise JudgeValidationError, never a silent clean verdict"
   107	    except tier_batch.JudgeValidationError:
   108	        pass
   109	
   110	
   111	class _RefusalClient:
   112	    class _Msgs:
   113	        def create(self, **kw):
   114	            class R:
   115	                stop_reason = "refusal"
   116	                content = []
   117	            return R()
   118	    def __init__(self):
   119	        self.messages = self._Msgs()
   120	
   121	
   122	def test_call_judge_treats_refusal_as_failure():
   123	    try:
   124	        tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=_RefusalClient())
   125	        assert False
   126	    except tier_batch.JudgeValidationError:
   127	        pass
   128	
   129	
   130	class _GoodClient:
   131	    """Returns a valid structured object as JSON text."""
   132	    def __init__(self, verdict):
   133	        import json
   134	        self._json = json.dumps(verdict)
   135	        outer = self
   136	
   137	        class _Msgs:
   138	            def create(self, **kw):
   139	                class R:
   140	                    stop_reason = "end_turn"
   141	                    content = [type("B", (), {"type": "text", "text": outer._json})()]
   142	                return R()
   143	        self.messages = _Msgs()
   144	
   145	
   146	def test_call_judge_parses_valid():
   147	    out = tier_batch.call_judge("rubric", {"ticker": "ACME"}, client=_GoodClient(_verdict("revenue")))
   148	    assert out["flags"]["revenue"] == 1
   149	
   150	
   151	# --- tiering via tier_one (judge injected; no API) ------------------------------------
   152	def test_green_when_clean_and_complete():
   153	    res = tier_batch.tier_one(_record(), subgroup="hc_services", judge=_verdict())
   154	    assert res["tier"] == "Green"
   155	    assert res["status"] == "complete"
   156	
   157	
   158	def test_two_families_yellow():
   159	    res = tier_batch.tier_one(_record(), subgroup="hc_services",
   160	                              judge=_verdict("revenue", "leverage"))
   161	    assert res["tier"] == "Yellow"
   162	
   163	
   164	def test_three_families_red():
   165	    res = tier_batch.tier_one(_record(), subgroup="hc_services",
   166	                              judge=_verdict("revenue", "leverage", "sector"))
   167	    assert res["tier"] == "Red"
   168	
   169	
   170	def test_green_eligibility_gate_blocks_green_on_unavailable():
   171	    rec = _record(coverage={"balance_sheet": "unavailable"}, source_errors=[{"source": "x", "error": "y"}])
   172	    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict())
   173	    assert res["tier"] == "DataGap"  # incomplete coverage + no signal -> NOT Green
   174	
   175	
   176	def test_critical_gov_overrides_datagap():
   177	    # 4.02 known even though balance_sheet coverage is unavailable -> Red, not DataGap.
   178	    rec = _record(coverage={"balance_sheet": "unavailable"}, source_errors=[{"source": "x", "error": "y"}])
   179	    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict(critical=True))
   180	    assert res["tier"] == "Red"
   181	    assert res["status"] == "complete"  # a known critical signal IS a complete evaluation
   182	
   183	
   184	def test_high_severity_overrides_datagap_to_yellow():
   185	    rec = _record(coverage={"sector": "unavailable"}, source_errors=[{"source": "x", "error": "y"}])
   186	    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict("revenue", high=True))
   187	    assert res["tier"] == "Yellow"  # signal present, coverage incomplete -> watch
   188	
   189	
   190	# --- idempotency status ----------------------------------------------------------------
   191	def test_transient_fetch_failure_is_not_complete():
   192	    # domestic, not stale, required family unavailable, source_errors present, NO signal
   193	    rec = _record(coverage={"accruals": "unavailable", "revenue": "unavailable",
   194	                            "balance_sheet": "unavailable", "leverage": "unavailable",
   195	                            "capex": "unavailable", "governance": "unavailable",
   196	                            "sector": "unavailable"},
   197	                  source_errors=[{"source": "rest:ratios", "error": "down"}])
   198	    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict())
   199	    assert res["status"] == "fetch_failed"  # retries next run; does NOT mark done
   200	
   201	
   202	def test_structural_foreign_gap_is_complete():
   203	    rec = _record(filer_type="foreign",
   204	                  coverage={f: "not_evaluated" for f in FAMILIES})
   205	    res = tier_batch.tier_one(rec, subgroup="medtech", judge=_verdict())
   206	    assert res["status"] == "complete"  # foreign = structural gap = done this cycle
   207	
   208	
   209	def test_stale_filer_gap_is_complete():
   210	    rec = _record(stale=True,
   211	                  coverage={"accruals": "partial", "revenue": "partial", "capex": "partial",
   212	                            "balance_sheet": "partial", "leverage": "partial"},
   213	                  source_errors=[])
   214	    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict())
   215	    assert res["status"] == "complete"  # genuinely stale = structural = done
   216	
   217	
   218	def test_fetch_failure_with_critical_signal_is_complete():
   219	    rec = _record(coverage={"balance_sheet": "unavailable"},
   220	                  source_errors=[{"source": "x", "error": "y"}])
   221	    res = tier_batch.tier_one(rec, subgroup="hc_services", judge=_verdict(critical=True))
   222	    assert res["status"] == "complete"  # a known signal means we DID evaluate it
   223	
   224	
   225	# --- run-level circuit breaker ---------------------------------------------------------
   226	def test_circuit_breaker_trips_on_majority_fetch_failed():
   227	    results = [{"status": "fetch_failed"} for _ in range(3)] + [{"status": "complete"}]
   228	    tripped, why = tier_batch.circuit_breaker_tripped(results)
   229	    assert tripped and "fetch_failed" in why
   230	
   231	
   232	def test_circuit_breaker_quiet_on_healthy_batch():
   233	    results = [{"status": "complete"} for _ in range(5)] + [{"status": "fetch_failed"}]
   234	    tripped, _ = tier_batch.circuit_breaker_tripped(results)
   235	    assert tripped is False
   236	
   237	
   238	def test_circuit_breaker_ignores_tiny_batch():
   239	    results = [{"status": "fetch_failed"}, {"status": "fetch_failed"}]
   240	    tripped, _ = tier_batch.circuit_breaker_tripped(results)
   241	    assert tripped is False  # below CIRCUIT_BREAKER_MIN_BATCH
   242	
   243	
   244	# --- history rows + migration ----------------------------------------------------------
   245	def test_history_row_has_new_columns():
   246	    res = tier_batch.tier_one(_record(), subgroup="hc_services", judge=_verdict("revenue"))
   247	    row = tier_batch.result_to_history_row(res, run_id="RUN42", run_date="2026-06-24")
   248	    assert set(row.keys()) == set(HISTORY_COLUMNS)
   249	    assert row["run_id"] == "RUN42"
   250	    assert row["status"] == "complete"
   251	    assert str(row["schema_version"]) != ""
   252	    assert row["revenue_flag"] == 1
   253	
   254	
   255	def test_append_migrates_old_13col_history(tmp_path):
   256	    old = tmp_path / "flags_history.csv"
   257	    old_cols = ["run_date", "ticker", "tier", "accruals_flag", "revenue_flag", "capex_flag",
   258	                "balance_sheet_flag", "leverage_flag", "governance_flag", "market_flag",
   259	                "text_flag", "sector_flag", "flag_details"]
   260	    with old.open("w", encoding="utf-8", newline="") as f:
     1	"""Tests for edgar_fetch.py — the false-Green guard's data layer.
     2	
     3	All EDGAR access is MOCKED. No live SEC / Anthropic calls. Covers:
     4	  - hard schema validity (every key present)
     5	  - staleness via filing DATES (not fy-age)
     6	  - not_disclosed vs fetch_failed distinction
     7	  - REST-down -> edgartools degradation (an outage can't hide a 4.02)
     8	  - never-raises contract
     9	"""
    10	from __future__ import annotations
    11	
    12	import json
    13	import sys
    14	from pathlib import Path
    15	
    16	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    17	
    18	import edgar_fetch  # noqa: E402
    19	from forensic_schema import COVERAGE, FAMILIES  # noqa: E402
    20	
    21	
    22	# --- fakes -----------------------------------------------------------------------------
    23	class _BoomRest:
    24	    """A REST client where everything raises (paid REST down)."""
    25	    def __init__(self):
    26	        self.api_key = "x"
    27	        self.identity = "id"
    28	
    29	    def ratios(self, cik): raise RuntimeError("rest down")
    30	    def income_statement(self, cik): raise RuntimeError("rest down")
    31	    def balance_sheet(self, cik): raise RuntimeError("rest down")
    32	    def cash_flow(self, cik): raise RuntimeError("rest down")
    33	    def metrics(self, cik): raise RuntimeError("rest down")
    34	    def material_events(self, cik): raise RuntimeError("rest down")
    35	
    36	
    37	class _OkRest:
    38	    """A REST client returning minimal usable payloads + a 4.02 in the 8-K feed."""
    39	    def __init__(self):
    40	        self.api_key = "x"
    41	        self.identity = "id"
    42	
    43	    def ratios(self, cik): return {"net_debt_ebitda": 2.1, "current_ratio": 1.5}
    44	    def income_statement(self, cik):
    45	        return {"data": [{"period": "2025", "revenue": 100, "net_income": 10}]}
    46	    def balance_sheet(self, cik):
    47	        return {"data": [{"period": "2025", "total_assets": 500, "inventory": 50, "goodwill": 80}]}
    48	    def cash_flow(self, cik):
    49	        return {"data": [{"period": "2025", "cfo": 12, "capex": 8}]}
    50	    def metrics(self, cik): return {"data": []}
    51	    def material_events(self, cik):
    52	        return {"data": [{"date": "2026-05-01", "items": "4.02", "body": "non-reliance"}]}
    53	
    54	
    55	def _schema_keys_present(rec: dict) -> None:
    56	    for key in ("schema_version", "ticker", "cik", "run_id", "fetched_at", "filer_type",
    57	                "latest_10k", "latest_10q", "staleness", "ratios", "statements", "notes",
    58	                "events_8k", "corporate_action", "insider", "family_coverage",
    59	                "required_families_complete", "source_errors"):
    60	        assert key in rec, f"missing key {key}"
    61	    assert set(rec["family_coverage"].keys()) == set(FAMILIES)
    62	    for fam, cov in rec["family_coverage"].items():
    63	        assert cov in COVERAGE, f"{fam}={cov} not a valid coverage enum"
    64	    for topic, body in rec["notes"].items():
    65	        assert body["status"] in ("present", "not_disclosed", "fetch_failed")
    66	    json.dumps(rec, default=str)  # must be JSON-serializable
    67	
    68	
    69	# --- foreign filer -> structural Data Gap, no EDGAR calls ------------------------------
    70	def test_foreign_filer_is_structural_gap():
    71	    rec = edgar_fetch.fetch_ticker("ADYEY", "", subgroup="medtech", filer_type="foreign",
    72	                                   run_id="t", rest=_BoomRest())
    73	    _schema_keys_present(rec)
    74	    assert rec["filer_type"] == "foreign"
    75	    assert rec["staleness"]["is_stale"] is True
    76	    assert rec["required_families_complete"] is False  # never green-eligible
    77	
    78	
    79	# --- never raises, even with everything broken ----------------------------------------
    80	def test_never_raises_with_total_failure(monkeypatch):
    81	    # REST down AND edgartools import/use raising.
    82	    def _boom_company(cik, identity):
    83	        raise RuntimeError("edgartools exploded")
    84	    monkeypatch.setattr(edgar_fetch, "_edgar_company", _boom_company)
    85	
    86	    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
    87	                                   filer_type="domestic", run_id="t", rest=_BoomRest())
    88	    _schema_keys_present(rec)
    89	    # Everything failed -> required families unavailable -> NOT green-eligible.
    90	    assert rec["required_families_complete"] is False
    91	    assert len(rec["source_errors"]) > 0
    92	    # financial families should be unavailable (fetch failure)
    93	    assert rec["family_coverage"]["accruals"] == "unavailable"
    94	
    95	
    96	# --- not_disclosed vs fetch_failed -----------------------------------------------------
    97	class _FakeFiling:
    98	    def __init__(self, text, *, filing_date="2026-03-01", period_end="2025-12-31"):
    99	        self._text = text
   100	        self.filing_date = filing_date
   101	        self.period_of_report = period_end
   102	        self.accession_no = "0000-25-000001"
   103	
   104	    def text(self):
   105	        return self._text
   106	
   107	
   108	class _FakeFilings:
   109	    def __init__(self, filing):
   110	        self._filing = filing
   111	
   112	    def latest(self):
   113	        return self._filing
   114	
   115	    def __bool__(self):
   116	        return self._filing is not None
   117	
   118	    def __len__(self):
   119	        return 1 if self._filing else 0
   120	
   121	    def head(self, n):
   122	        return [self._filing] if self._filing else []
   123	
   124	    def __getitem__(self, i):
   125	        return self._filing
   126	
   127	
   128	class _FakeCompany:
   129	    def __init__(self, tenk_text=None, has_10k=True):
   130	        self._tenk = _FakeFiling(tenk_text) if has_10k else None
   131	
   132	    def get_filings(self, form=None):
   133	        if form == "10-K":
   134	            return _FakeFilings(self._tenk)
   135	        return _FakeFilings(None)
   136	
   137	    @property
   138	    def financials(self):
   139	        return object()
   140	
   141	
   142	def test_note_present_vs_not_disclosed(monkeypatch):
   143	    # 10-K body mentions inventory + goodwill but NOT 'debt' -> Inventory/Goodwill present,
   144	    # Debt not_disclosed (a legitimate absence, NOT a fetch failure).
   145	    body = "Note 3. Inventory consists of consigned field inventory. Note 5. Goodwill of $80M."
   146	    monkeypatch.setattr(edgar_fetch, "_edgar_company",
   147	                        lambda cik, identity: _FakeCompany(tenk_text=body))
   148	    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="medtech",
   149	                                   filer_type="domestic", run_id="t", rest=_OkRest())
   150	    _schema_keys_present(rec)
   151	    assert rec["notes"]["Inventory"]["status"] == "present"
   152	    assert rec["notes"]["Goodwill"]["status"] == "present"
   153	    assert rec["notes"]["Debt"]["status"] == "not_disclosed"  # absent, not failed
   154	
   155	
   156	def test_note_fetch_failed_when_body_unreadable(monkeypatch):
   157	    # 10-K handle exists but body is empty -> every note is fetch_failed (a real failure).
   158	    monkeypatch.setattr(edgar_fetch, "_edgar_company",
   159	                        lambda cik, identity: _FakeCompany(tenk_text=""))
   160	    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="medtech",
   161	                                   filer_type="domestic", run_id="t", rest=_OkRest())
   162	    for topic in edgar_fetch.NOTE_TOPICS:
   163	        assert rec["notes"][topic]["status"] == "fetch_failed"
   164	
   165	
   166	# --- staleness via dates ---------------------------------------------------------------
   167	def test_staleness_uses_filing_dates_not_fy_age(monkeypatch):
   168	    old = _FakeFiling("Inventory note.", filing_date="2024-02-01", period_end="2023-12-31")
   169	
   170	    class _OldCompany(_FakeCompany):
   171	        def get_filings(self, form=None):
   172	            if form == "10-K":
   173	                return _FakeFilings(old)
   174	            return _FakeFilings(None)
   175	
   176	    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _OldCompany())
   177	    rec = edgar_fetch.fetch_ticker("OLD", "0000000002", subgroup="general",
   178	                                   filer_type="domestic", run_id="t", rest=_OkRest())
   179	    assert rec["staleness"]["is_stale"] is True
   180	    assert "2023-12-31" in rec["staleness"]["reason"]
   181	
   182	
   183	def test_recent_filing_not_stale(monkeypatch):
   184	    monkeypatch.setattr(edgar_fetch, "_edgar_company",
   185	                        lambda cik, identity: _FakeCompany(tenk_text="Inventory note. Goodwill. Debt covenants."))
   186	    rec = edgar_fetch.fetch_ticker("NEW", "0000000003", subgroup="general",
   187	                                   filer_type="domestic", run_id="t", rest=_OkRest())
   188	    assert rec["staleness"]["is_stale"] is False
   189	
   190	
   191	# --- REST-down degradation can't hide a 4.02 ------------------------------------------
   192	def test_rest_down_still_captures_8k_via_edgartools(monkeypatch):
   193	    # REST is down; edgartools must supply the 8-K feed so a 4.02 isn't hidden.
   194	    class _Co8K(_FakeCompany):
   195	        def get_filings(self, form=None):
   196	            if form == "10-K":
   197	                return _FakeFilings(_FakeFiling("Inventory. Goodwill. Debt."))
   198	            if form == "8-K":
   199	                f = _FakeFiling("non-reliance", filing_date="2026-05-01")
   200	                f.items = "4.02"
   201	                return _FakeFilings(f)
   202	            return _FakeFilings(None)
   203	
   204	    monkeypatch.setattr(edgar_fetch, "_edgar_company", lambda cik, identity: _Co8K())
   205	    rec = edgar_fetch.fetch_ticker("ACME", "0000000001", subgroup="general",
   206	                                   filer_type="domestic", run_id="t", rest=_BoomRest())
   207	    _schema_keys_present(rec)
   208	    items = [i for ev in rec["events_8k"] for i in ev.get("items", [])]
   209	    assert "4.02" in items, "REST-down must not drop the 8-K governance feed"
   210	    # governance family is therefore evaluable (the feed was fetched).
   211	    assert rec["family_coverage"]["governance"] == "complete"
   212	
   213	
   214	def test_no_cik_domestic_writes_fetch_failed(tmp_path, monkeypatch):
   215	    # A domestic name with no CIK can't be fetched -> fetch_failed record, never a crash.
   216	    monkeypatch.setattr(edgar_fetch, "WATCHLIST_CSV", tmp_path / "nope.csv")
   217	    rc = edgar_fetch.main(["NOCIK", "--out", str(tmp_path), "--filer-type", "domestic"])
   218	    assert rc == 0
   219	    rec = json.loads((tmp_path / "NOCIK.json").read_text())
   220	    assert rec["required_families_complete"] is False
   221	    assert any(e["source"] == "watchlist" for e in rec["source_errors"])

codex
The patch still has false-Green paths where incomplete financial or governance data can be marked complete, and it accepts abnormal model stops. The workflow can also silently report success after failing to push the committed results.

Full review comments:

- [P1] Require real statements before Green eligibility — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/edgar_fetch.py:199-199
  If the ratios endpoint succeeds but all statement endpoints fail, `have_statements` is still true, so required financial families can be marked `complete` and an otherwise clean domestic name can become Green even though the statements needed to evaluate those families were not fetched.

- [P1] Do not mark 8-K coverage complete after swallowed fetch errors — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/edgar_fetch.py:534-537
  When the fallback `company.get_filings(form="8-K")` call raises, this returns an empty list, and the caller treats any non-`None` list as a successfully fetched 8-K feed; a REST outage plus this fallback failure therefore marks required governance coverage `complete` and can allow a false Green while governance was unevaluable.

- [P1] Fail closed on all non-end_turn model stops — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/tier_batch.py:223-225
  Only `refusal` is rejected here; if Anthropic returns `stop_reason="max_tokens"` or another non-`end_turn` value with syntactically valid JSON, the response is accepted and tiered even though the structured output was not completed normally.

- [P1] Fail the workflow when all push retries fail — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/.github/workflows/forensic_triage.yml:64-68
  If every `git pull --rebase && git push` attempt fails, the loop still exits successfully because the final command is `sleep 5`, so the job can notify success while the report/history were never pushed.
The patch still has false-Green paths where incomplete financial or governance data can be marked complete, and it accepts abnormal model stops. The workflow can also silently report success after failing to push the committed results.

Full review comments:

- [P1] Require real statements before Green eligibility — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/edgar_fetch.py:199-199
  If the ratios endpoint succeeds but all statement endpoints fail, `have_statements` is still true, so required financial families can be marked `complete` and an otherwise clean domestic name can become Green even though the statements needed to evaluate those families were not fetched.

- [P1] Do not mark 8-K coverage complete after swallowed fetch errors — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/edgar_fetch.py:534-537
  When the fallback `company.get_filings(form="8-K")` call raises, this returns an empty list, and the caller treats any non-`None` list as a successfully fetched 8-K feed; a REST outage plus this fallback failure therefore marks required governance coverage `complete` and can allow a false Green while governance was unevaluable.

- [P1] Fail closed on all non-end_turn model stops — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/tier_batch.py:223-225
  Only `refusal` is rejected here; if Anthropic returns `stop_reason="max_tokens"` or another non-`end_turn` value with syntactically valid JSON, the response is accepted and tiered even though the structured output was not completed normally.

- [P1] Fail the workflow when all push retries fail — /mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage/.github/workflows/forensic_triage.yml:64-68
  If every `git pull --rebase && git push` attempt fails, the loop still exits successfully because the final command is `sleep 5`, so the job can notify success while the report/history were never pushed.
___CODEX_EXIT=0
