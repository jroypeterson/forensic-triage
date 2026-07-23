# Path A — unattended forensic_triage (hybrid data layer)  [v2, post-codex-round-1]

## Goal
Run the "a few each day" forensic screen **unattended**, at full reachable data quality, posting
Red/Yellow/Green/Data-Gap results + per-name concerns to Slack — without ever letting a partial run
(missing data) masquerade as a clean Green. Today it runs only interactively because the rich
Edgar-Tools data needs the MCP, which scheduled triggers can't reach.

## Data layer (decided 2026-06-21; reshaped per codex R1)
Live probing: the paid Edgar-Tools **REST key works headlessly** only for company profile,
`/companies/{cik}/ratios` (12 ratios + health), `/companies/{cik}/material-events` (8-K item
codes), `/filings`, `/search`. The rich tools (statement line items, trends, insider detail, **note
bodies**) are MCP-only and the MCP **rejects API keys** (OAuth-only = interactive). The free
`edgartools` library (direct SEC, free) gets ALL of that headlessly (verified: STAA 10-K full text
incl. consigned-inventory note + structured statements + 8-K bodies + Form 4).

**CORRECTION (2026-06-23):** the paid REST key actually reaches the **statement line items** too —
`/companies/{cik}/income-statement` · `/balance-sheet` · `/cash-flow` · `/metrics` · `/ratios`
(use the hyphenated direct paths; `/financials/*` 404s) + `/material-events` (8-K item codes). So the
paid REST is the **primary** source for statements + ratios + 8-K item codes. The **ONLY** thing it
can't do headlessly is **10-K note BODIES** (`edgar_notes` full text — MCP-only, key rejected). The
free `edgartools` library is needed for **note bodies** (required for Red-tier quoting + several
sector/note-backed checks) + 8-K item *bodies* (4.01-disagreement detail, corp-action context) +
Form-4 detail, and serves as a **fallback for statements/8-K if the paid REST is down**. So a
paid-REST outage degrades to free-edgartools-for-everything (incl. governance via 8-K bodies) — it
can NOT silently hide a 4.02 and false-Green (codex R1 #1).

| Rubric need | Source | If unavailable |
|---|---|---|
| 12 ratios + health (leverage, liquidity, net-debt/EBITDA) | Paid REST `/ratios` | recompute key ratios from `edgartools` statements; flag `ratios:degraded` |
| Statement line items — **annual 10-K + trailing 8 quarters** (inventory, AR, goodwill, CFO, NI, revenue, deferred rev, debt) | Free `edgartools` 10-K + 10-Qs / companyfacts | family → `unavailable` (blocks Green) |
| 10-K note bodies (Inventory, Goodwill, Debt, Commitments, Sig. Policies, Revenue) | Free `edgartools` section/text extract | **distinguish** not-disclosed vs fetch-failed (see schema) |
| 8-K item codes **+ bodies** (4.02/4.01-disagreement/NT; 5.01/2.01/3.01 corp-action) | Free `edgartools` (paid REST events = cross-check) | family → `unavailable` (blocks Green) |
| Insider Form-4 clusters | Free `edgartools` form=4 | `market:partial` |
| Legal / FCA / restatement language | Free `edgartools` 10-K text (+ optional paid full-text) | `legal:not_evaluated` |
| MD&A / risk-factor YoY diffs (text family) | Free `edgartools` prior-year section extract | `text:not_evaluated` |

**Families NOT reachable unattended (codex R1 #4) — reported `not_evaluated`, never "clean":**
short interest / borrow cost / utilization (market), FDA recall database & transcripts & peer
medians (sector medtech), some MLR/same-store/340B color (sector hc). Interactive runs had
WebSearch for these; unattended runs declare them `not_evaluated` so a name isn't called clean on
absent data. (These rarely *alone* drive a tier; the financial + governance + note families do.)

## edgar_fetch.py — JSON contract (codex R1 #2; the false-Green guard)
Per ticker → `data/fetched/<TICKER>.json`. **Hard schema**, not "whatever we got":
```
{ ticker, cik, run_id, fetched_at,
  filer_type, latest_10k:{accession,filing_date,period_end,fy}, latest_10q:{...},
  staleness:{is_stale,reason},                 # filing-date/period-end based (R1 #7), NOT fy-age
  ratios:{...}|null, statements:{annual[],quarters[]},
  notes:{Inventory:{status:"present|not_disclosed|fetch_failed", text}, Goodwill:{...}, ...},
  events_8k:[{date,items,body_excerpt}], corporate_action:{detected,kind}|null,
  insider:{...},
  family_coverage:{accruals:"complete|partial|unavailable|not_applicable", revenue:..., capex:...,
                   balance_sheet:..., leverage:..., governance:..., market:..., text:..., sector:...},
  required_families_complete: bool,            # all Green-required families complete or not_applicable
  source_errors:[...] }
```
- **`not_disclosed` ≠ `fetch_failed`** — a note legitimately absent is fine; a *failed* fetch makes
  that family `unavailable`. **Green is legal only when `required_families_complete == true`** (every
  Green-required family `complete` or `not_applicable`); any `unavailable` → tier is **Data Gap**, not
  Green (enforces CLAUDE.md "unevaluable ≠ Green").
- **Never raises.** Each source wrapped; failure → status flag + `source_errors`, not a crash.

## Architecture (codex R1 #3): GitHub Actions + Anthropic API
**Switch from the claude.ai trigger to a GitHub Actions cron** (the fleet standard). Reasons: real
retries, durable logs, secret management, `concurrency` locks, pinned Python, failure surfacing.
Pipeline per run:
1. `concurrency: forensic-triage` (no overlapping runs). Checkout repo.
2. `pip install -r requirements.txt`.
3. `python -m forensic_triage.next_batch` → next N domestic names (committed watchlist; see §sync).
4. For each: `python -m forensic_triage.edgar_fetch TICKER` → JSON.
5. **Tiering = Anthropic API call** (Claude reads `rubrics/*.md` + the JSON, returns **structured
   output** = per-family flags + tier + concerns). Judgment stays in the model (R1 #10) — but wrapped
   by **deterministic guardrails**: ratio math, Data-Gap/Corporate-Action precedence, critical-gov
   auto-Red, new-name auto-Yellow, **Green-eligibility gate** (`required_families_complete`), and
   **schema validation** of Claude's output (reject/retry if malformed).
6. Append `flags_history.csv` (atomic) + write/append report. **Mark a ticker done only after
   fetch+judgment+history all succeed** (R1 #8 idempotency; `run_id` per row).
7. `git commit/push` (rebase-before-push, fleet pattern). Post Slack (#forensic-flags) + a
   `#status-reports` heartbeat with run_id, tickers, counts, missing-family counts, commit hash.
   Any step failure → `if: failure()` alarm to #status-reports (no silent failure).

Model: Claude via Anthropic API (per MODEL_POLICY — Fable 5 for forensic_triage). Cost: a few
names/day × 1 API call each = negligible.

## Watchlist in cloud (codex R1 #9)
`sync_watchlist.py` needs the sibling Coverage Manager CSV, absent in CI. Fix: **cloud uses the
committed `data/watchlist.csv` as-is (no re-sync)** — sync stays a local step (universe changes
weekly, not daily). **Add a `cik` column to `watchlist.csv`** (sync_watchlist already reads CIK from
CM — just emit it) so cloud `edgar_fetch.py` needs no CIK lookup. New names still auto-Yellow.

## Components / files
- `edgar_fetch.py` (REST+edgartools → JSON, the schema above, never-raise, Data-Gap detection).
- `tier_batch.py` (Anthropic API tiering + deterministic guardrails + output schema validation).
- `notify.py` (#forensic-flags Block Kit + #status-reports v1 heartbeat; context blocks use `elements[]`).
- `.github/workflows/forensic_triage.yml` (cron, concurrency, secrets, retries, failure alarm).
- `requirements.txt` (edgartools, requests, anthropic — pinned).
- `sync_watchlist.py` (+`cik` column), `next_batch.py` (+idempotent "done only when complete").
- Tests: `tests/test_edgar_fetch.py` (schema, staleness via dates, not_disclosed-vs-fetch_failed,
  REST-down degradation, never-raises), `tests/test_tier_guardrails.py` (Green-eligibility gate,
  precedence, malformed-output rejection).
- Docs: CLAUDE.md Path-A section; AUTHENTICATIONS (key used-by + REST-vs-MCP/OAuth finding);
  SCHEDULED_JOBS row; PROJECT_BRIEF status update.

## Secrets / handoff (user)
- `EDGARTOOLS_API_KEY` (have it) + `ANTHROPIC_API_KEY` + `SLACK_WEBHOOK_FORENSIC` (create #forensic-flags
  webhook) + `SLACK_WEBHOOK_STATUS_REPORTS` (fleet) + `EDGAR_IDENTITY` → as **GitHub Actions secrets**.
- Disable the old degraded claude.ai trigger `trig_…9Cd6` (superseded by GH Actions).

## Operational hygiene (codex R1 #11)
Retry/backoff on SEC + REST; throttle < SEC 10 req/s; cache fetched JSON per run; **never log
secrets**; commit compact report/history (not the big full-text JSON — gitignore `data/fetched/`);
GH Actions `concurrency` + `if: failure()` alarm.

## Open questions for codex round 2
1. Is the evaluability schema + Green-eligibility gate now airtight against false-Green?
2. Is moving governance/legal/text to the free library (paid REST = ratios only) the right split?
3. GH Actions + Anthropic-API tiering with deterministic guardrails — is the guardrail set complete
   (anything that should be deterministic still left to the model, or vice-versa)?
4. Idempotency model (done-only-when-complete + run_id) — does it fully prevent cycle poisoning?
5. Any remaining way an unattended run silently under-reports vs the interactive screen?

---
## v3 deltas (incorporated from codex round 2 — build against these)
- **`family_coverage` enum** = `complete | partial | unavailable | not_evaluated | not_applicable`.
  Green requires every REQUIRED family ∈ {complete, not_applicable}; any {partial, unavailable,
  not_evaluated} on a required family → not Green (Data Gap unless a positive signal sets Red/Yellow).
- **Required-vs-optional family matrix (per subgroup).** Required for a clean Green: accruals,
  revenue, balance_sheet, leverage, governance, + note-backed sector checks. Optional/best-effort
  (may be `not_evaluated` without blocking Green): market (short-interest/borrow), text (MD&A diffs),
  and the non-EDGAR sector inputs (FDA recall db, transcripts, peer medians, some MLR/340B color).
- **Deterministic final tiering** computed in code from Claude's validated per-family flags + coverage:
  precedence = Corporate-Action (only if NO accounting concern) → critical-gov auto-Red →
  high-severity-accounting ≥ Yellow → families≥3 Red / ≥2 Yellow → Data-Gap (required coverage
  incomplete AND no positive signal) → Green. **Critical-gov and high-severity OVERRIDE Data Gap**
  (a known 4.02 is Red even if other families are unevaluable). Claude does NOT emit the final tier.
- **Idempotency:** `flags_history.csv` gains `run_id`, `status` (`complete`), `schema_version`.
  `next_batch.py` counts a ticker done ONLY when a `status=complete` row exists since cycle start;
  a transient fetch-failure does NOT mark done (retries next run); a STRUCTURAL Data Gap (foreign
  filer / genuinely stale / not-disclosed) IS done.
- **Run-level circuit breaker:** if fetch-failure / required-family-missing rate exceeds a threshold
  (broad SEC/REST outage), FAIL the run loudly (alarm #status-reports) and do NOT commit a batch of
  false Data Gaps.
- **First-run checklist:** `cik` column emitted by sync_watchlist + present in watchlist.csv;
  `requirements.txt` (edgartools, requests, anthropic, pinned); concrete model id `claude-fable-5`
  (MODEL_POLICY: Fable 5 for forensic_triage); GH Actions `permissions: contents: write`, commit
  identity, `EDGAR_IDENTITY`, secrets, structured-output retry + fail-closed.
