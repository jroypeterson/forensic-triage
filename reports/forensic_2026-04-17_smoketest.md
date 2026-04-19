# Forensic Triage Smoke Test — 2026-04-17

**Purpose:** validate the rubric + data pipeline end-to-end on 8 hand-picked tickers before running the full pilot. This is **not** a scored baseline — it's a mechanics check on what the 3-call baseline (snapshot + brief + trends) can and cannot catch.

**Calls consumed:** 24 Pro API calls (3 per ticker × 8). Pro cap 500/day; AHCO reused from this morning's verification.

## Summary

- **Red:** 0
- **Yellow:** 5
- **Green:** 3

## Yellow (watch / escalate)

| Ticker | Subgroup | Flags fired | CFO/NI | Health | One-liner |
|---|---|---|---|---|---|
| AHCO | hc_services | leverage, sector | -0.53 | distressed | Fresh 2.03 debt event 4 days ago. Distressed health + known roll-up sector with $1.74B long-term debt (from edgar_notes( |
| CVS | hc_services | leverage, governance | 6.02 | weak | Net debt/EBITDA 6.06 (high), NI down 62% YoY, operating margin 1.2%, health_hint='weak'. 5.02 Director change last month |
| HIMS | hc_services | market | 1.03 | moderate | 3-insider sell cluster Dec 17-22 (amount threshold unverifiable from company_brief — needs holdings data). Rev +59% but  |
| DXCM | medtech | accruals, governance | 0.07 | moderate | **CFO/NI = 0.075** — rule fires (<0.5 with positive NI). $836M NI vs $62.7M CFO is a $773M earnings-vs-cash gap. FCF mar |
| TMDX | medtech | accruals | 0.00 | strong | **CFO/NI = 0.004** — most extreme reading in smoke test. $190M NI but CFO is essentially $0 ($795k). 31% net margin with |

## Green (no action)

| Ticker | Subgroup | Flags fired | CFO/NI | Health | One-liner |
|---|---|---|---|---|---|
| AAPL | general | — | 1.00 | strong | clean baseline; CFO/NI 0.99 |
| CVNA | general | — | 0.74 | moderate | CFO/NI 0.74 (close to 0.8 threshold but single year — rule requires 2yr pattern). Baseline misses historical concerns (h |
| JNJ | medtech | — | 0.92 | strong | clean baseline; fresh 8.01 worth a follow-read in full run |

## Standout findings

### 1. Accruals flag fires cleanly on baseline (the high-signal check works)

The single most replicated finding in forensic accounting research — Sloan's earnings-vs-cash gap — is visible from **just `company_brief`** (no additional calls needed):

- **TMDX: CFO/NI = 0.004** — $190M reported net income, $795k cash from operations. 31% net margin with essentially zero operating cash. Rule fires (<0.5 with positive NI).
- **DXCM: CFO/NI = 0.075** — $836M NI vs $62.7M CFO = $773M gap. FCF margin -6.5% despite 18% net margin. Rule fires.

Both are medtech growth names where AR buildup on new-product launch could plausibly explain part of the gap — but magnitudes this extreme demand a deep dive. Neither would be on a casual watchlist.

### 2. Governance events surface via `recent_events` without extra calls

- **AHCO:** 2.03 Creation of Direct Financial Obligation on **2026-04-13** (4 days ago) — fresh debt event on a distressed roll-up
- **DXCM:** two 5.02 Director changes within 4 days (2026-02-26 and 2026-03-02) — unusual cadence
- **CVS:** 5.02 Director change 2026-03-19
- **JNJ:** 8.01 Other Events 2026-04-14 — not rubric-critical but worth a follow-read

None trip the automatic Red criteria (4.01 auditor change, 4.02 non-reliance, NT late filings) but they're visible signal.

### 3. Rubric is correctly non-false-positive on CVNA

Carvana is a historically controversial name (high leverage, past inventory/accounting questions). Baseline shows CFO/NI 0.74 (close to the 0.8 threshold but the rule requires a 2-year pattern) and a single $18M insider sale (not a 3-insider cluster). **No family fires** on baseline alone — which is the rubric doing its job. The real signals (goodwill %, DSO, floor-plan financing, securitization) all live in balance sheet notes. **Action:** the full run should auto-escalate any historically-flagged name to `financial_statements` + targeted `edgar_notes`.

### 4. HIMS insider cluster geometry fires, dollar test unverifiable

Three insiders sold within 5 days (Dec 17–22, 2025). The rubric additionally requires each sale >25% of holdings — `company_brief` gives transaction values but not pct of holdings. **Calibration need:** either lower the dollar bar or pull Form 4 detail via a second call on any 3-in-30 cluster.

## Calibration notes for the full run

1. **The 3-call baseline catches the big signals.** Accruals, governance cadence, leverage ratios, financial health, gross insider activity, and recent 8-K items all surface without additional calls.
2. **Sector-specific flags require `edgar_notes`.** Every hc_services flag (bad debt, MLR, risk-adjustment, goodwill, 340B) and every medtech flag (distributor channel, consignment, warranty, FCPA, R&D cap) needs note body text. Recommend auto-escalation when subgroup ∈ {hc_services, medtech} AND (health_hint != 'strong' OR CFO/NI < 0.7).
3. **Balance sheet bloat (DSO, inventory days, Sloan accruals, goodwill %) requires `financial_statements`.** Auto-escalate on any revenue decelerator, moderate/weak health_hint, or confirmed accruals flag.
4. **The `financial_trends` API sometimes omits revenue/gross_profit** (saw this on CVS and TMDX despite requesting 4 concepts). Don't rely on trend for YoY revenue growth — compute from `company_brief` + prior-year `financial_statements` call.
5. **Full-run call budget estimate:** 3 baseline calls × 77 core hc_services names + ~30 escalation calls (1–2 each) + ~5 Red deep-dives × 2 calls = **~280 calls**, comfortably inside the 500/day cap.

## Baseline diff caveat

`flags_history.csv` now has its first 8 rows. Per project memory, **all 8 names appear 'new this run'** — the rubric's Green→Yellow diff logic can only fire from the second run onward.

## What's next

1. Review this smoke test — does the tiering match your gut on these 8 names?
2. If calibration looks right, kick off the pilot pass on all 77 `core=true` hc_services tickers.
3. If you want to tighten any rule (e.g., lower the insider-cluster bar, add auto-escalation triggers), do it in `rubrics/*.md` before the pilot so the rules are codified.