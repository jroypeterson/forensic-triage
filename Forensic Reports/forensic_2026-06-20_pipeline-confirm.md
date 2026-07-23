# Forensic Triage — 2026-06-20 (2-name pipeline confirmation)

**Purpose:** confirm the live pipeline works end-to-end on the **recalibrated** rubrics (Codex-reviewed, commit `4252d13`) before a full-universe run. Two names chosen to exercise both paths: **HCA** (large hospital operator — clean baseline) and **STAA** (the June-run Red — confirm a genuine red flag survives recalibration via *legitimate* families, not the now-tightened accruals/goodwill rules).

**Data:** EDGAR-Tools **Pro** (10,000/day cap confirmed; **~6 calls used, 6/10,000**). FY2025 10-Ks.

**Result:** pipeline works (sync → company_brief / financial_snapshot / financial_trends / financial_statements / edgar_notes → rubric → tier → history). Both names tier correctly; the recalibration behaves as designed.

---

## Red (deep dive)

| Ticker | Subgroup | Flags fired | New this run? | One-liner concern |
|---|---|---|---|---|
| **STAA** | medtech (Ophthalmology) | balance_sheet, sector, governance(soft) | No (Red in June) | Field-inventory build into a demand collapse: total inventory **+28%** ($43.3M→$55.5M) and **consigned inventory +548%** ($1.48M→$9.62M) while revenue/gross-profit fell **~−24%**; returns allowance +55%; CFO −$34.2M (from +$15.7M), NI −$80.4M. |

### STAA — source note quote
- **Inventory (Note 4):** *"Finished goods inventory includes consigned inventory of $9,619,000 and $1,484,000 for 2025 and 2024, respectively. … Total inventories, gross 58,425 / 44,583 … Less inventory reserves (2,929)/(1,278) … Total inventories, net $55,496 / $43,305."*

**Recalibration check (STAA):** Red is preserved, but via the *correct* families. **Accruals NOT fired** — NI is −$80M (the tightened `CFO/NI<0.5` rule only applies to *positive* NI, and the one-time-gain exclusion isn't even reached). **Goodwill irrelevant** — only $1.8M (0.4% of assets), so no balance-sheet/sector double-count. **Governance is soft** (interim co-CEO / repeated 5.02), not critical (no 4.02/restatement/NT). June's `revenue_flag` refines **off**: AR actually *fell* (−36%) so there's no DSO/premature-recognition fingerprint — the signal is inventory, scored once in balance_sheet + sector. Net: same Red verdict, cleaner family attribution.

## Green (evaluated clean)

| Ticker | Subgroup | Flags fired | One-liner |
|---|---|---|---|
| **HCA** | hc_services (Hospitals) | none | CFO/NI **1.86** (strong cash backing); negative equity (−$6.0B) is **structural from buybacks**, not a flag; net-debt/EBITDA 3.04x is *visible* leverage; recent 5.02/2.03 routine. Clean. |

**Recalibration check (HCA):** stays Green, now with **0 families** vs. June's Green-with-`leverage_flag=1`. Net-debt/EBITDA 3.04x is ordinary *visible* on-BS leverage — the **Leverage-Hiding** family fires on off-BS / factoring / supplier-finance / VIE / ST-vs-LT shifts, none of which are present — so that flag correctly clears. Demonstrates the fixes don't over-fire on a structurally-levered, negative-equity operator with a routine officer event.

## Diffs since last run (2026-06-14)
- **HCA:** Green → Green; `leverage_flag` 1 → 0 (spurious — visible leverage is not the leverage-hiding family).
- **STAA:** Red → Red; family attribution refined (`revenue_flag` 1 → 0; primary drivers now balance_sheet + sector(consignment); accruals correctly never fired).

## Data Gap (manual review — NOT screened)
_(none in this 2-name set; the 27 foreign 20-F/ADR filers tagged by sync route here in a full run)_

---

**Conclusion: pipeline confirmed live and the recalibrated rubrics behave as intended.** Cleared for a full-universe interactive run (~274 domestic names, ~700–1,100 calls, one day under the 10k cap).
