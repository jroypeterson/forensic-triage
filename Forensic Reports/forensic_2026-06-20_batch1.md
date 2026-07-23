# Forensic Triage — 2026-06-20 (batch 1 of the "a few each day" cycle)

First real batch on the recalibrated rubrics. 6 core Healthcare-Services names (next_batch.py pick, core-first): ACH, ACHC, ADUS, AGL, AHCO, ALHC. EDGAR-Tools **Pro** (~10 calls this batch). Progress: **8/274 domestic screened this cycle** (incl. the HCA/STAA pipeline confirmation).

**Tally:** 3 Red · 1 Yellow · 1 Green · 1 Data Gap.

This batch exercised every recalibration feature — goodwill-via-impairment-corroborator (ACHC fires, AHCO doesn't), the new Data Gap tier (ALHC), soft-vs-critical governance (CFO transitions = soft), accruals correctly *not* firing on negative-NI names, and a healthy roll-up staying Green (ADUS).

---

## Red (deep dive)

| Ticker | Subgroup | Flags fired | One-liner concern |
|---|---|---|---|
| **ACHC** | hc_services (Behavioral) | sector, leverage, governance(soft) | **$968M goodwill impairment** FY2025 (goodwill $2,265M→$1,296M) = the −$1.10B net loss (CFO +$132M, so non-cash); LT debt +$591M; CFO transition. Roll-up goodwill firing via the impairment corroborator. |
| **AGL** | hc_services (VBC) | balance_sheet, sector, market, governance(soft) | Stressed VBC: equity collapsed to $127M, CFO −$106M, debt/equity 9.0x; bearish insiders (10 sells); securities class action survived MTD. Likely IBNR/risk-adjustment under-reserve — verify medical-claims-payable next pass. |
| **ACH** | hc_services (Distributor) | balance_sheet, leverage, sector | **−$1.10B loss, negative equity −$461M, CFO −$102M** (Accendra Health, fka Owens & Minor); repeated refinancing 8-Ks under stress. Loss likely a large goodwill impairment. _financial_snapshot timed out → re-escalate next batch for impairment/covenant specifics._ |

## Yellow (watch)

| Ticker | Subgroup | Flags fired | One-liner concern |
|---|---|---|---|
| **AHCO** | hc_services (DME) | sector, governance(soft) | Goodwill 58% of assets ($2.5B) but **CFO +$602M (strong)** and deleveraging — goodwill-% alone doesn't fire (recalibration). $175M goodwill reduction looks divestiture-driven (assets-held-for-sale $53M→$0) — **verify impairment vs divestiture** (would tip to Red). Small −$71M loss. _(April smoke test had AdaptHealth Red on historical issues; correctly Yellow now.)_ |

## Green (evaluated clean)

| Ticker | Subgroup | One-liner |
|---|---|---|
| **ADUS** | hc_services (Home Health) | Profitable (NI +$96M), CFO/NI **1.16**; home-care roll-up but goodwill has no impairment/distress corroborator → doesn't fire. Clean. |

## Data Gap (manual review — NOT screened)

| Ticker | Subgroup | Why |
|---|---|---|
| **ALHC** | hc_services (Mgd Care) | Latest annual XBRL = **FY2024** (~18mo stale); no FY2025 10-K surfaced — can't evaluate the rubric. **Manual:** verify genuine late-filing (would be a critical-gov signal) vs MCP XBRL lag. Reviewer context: current bearish insider cluster (19 sells, −$28M, 90d). _(June had it Yellow on stale data; recalibration routes it to Data Gap.)_ |

## Diffs since last run
- **AGL:** Red → Red (carried; family attribution now balance_sheet + sector + market + soft-gov).
- **AHCO:** April-smoke-test Red → **Yellow** (goodwill no longer fires on % alone — strong CFO, deleveraging).
- **ALHC:** June Yellow → **Data Gap** (stale FY2024; correctly unscreenable).
- ACH, ACHC, ADUS: first appearance this cycle.

## Pending escalation (next batch)
- **ACH** — financial_snapshot timed out; pull balance sheet + debt note for the impairment/covenant detail.
- **AGL** — confirm medical-claims-payable / IBNR under-reserve in the financial statements.
- **AHCO** — confirm the $175M goodwill move is divestiture vs impairment (edgar_notes "Goodwill").
- **ACHC / AGL** — check legal-proceedings notes for any new DOJ/FCA matter (behavioral-health admissions; VBC).
