# Healthcare Services Forensic Flags

Apply *in addition to* `general.md` for any company tagged `hc_services` in the watchlist. Subgroups: hospitals & physician groups, managed care / payers, PBMs, drug distributors, post-acute (SNF, home health, hospice), dialysis, lab services.

Healthcare services has its own accounting vocabulary that hides things general flags miss. The biggest historical accounting blowups in this sector — HealthSouth, Tenet, McKesson HBOC, MiMedx, US Physical Therapy issues, the long line of dialysis/hospice DOJ cases — almost all involved one of the items below.

---

## 1. Bad Debt / Allowance for Doubtful Accounts (hospitals, physician groups, labs)

### Inputs
- Provision for bad debts as % of revenue (TTM trend)
- Allowance for doubtful accounts as % of gross AR
- Self-pay AR as % of total AR (if disclosed)
- Pre-ASC 606 vs. post-ASC 606 reclassification — under ASC 606 most providers reclassed bad debt as a revenue reduction (implicit price concession). Reversals or methodology changes are red flags.

### Flag fires if
- Bad debt provision % of revenue declining >100bps YoY while self-pay mix is rising
- OR allowance / gross AR declining while DSO rising
- OR change in implicit price concession methodology disclosed in revenue note
- OR "favorable adjustments to estimates" of patient revenue exceed 2% of revenue in a quarter

### Why it matters
Hospitals control reported revenue largely through estimates of what they'll actually collect. HealthSouth and Tenet both manipulated these estimates. ASC 606 made it worse by burying bad debt inside the revenue line.

---

## 2. Contractual Allowances vs. Gross Charges

### Inputs
- Gross charges vs. net patient revenue (if disclosed)
- Contractual allowance % trend
- Payer mix shift commentary

### Flag fires if
- Net-to-gross ratio improving >200bps without disclosed payer mix or rate change
- OR contractual allowance methodology change disclosed

### Why it matters
The difference between gross charges and net revenue is an estimate. Small percentage changes flow straight to net income on huge dollar bases.

---

## 3. Risk-Adjustment Revenue & Medical Loss Ratio (managed care, MA plans)

### Inputs
- Medical loss ratio (MLR) trend by segment
- Prior-period reserve releases / strengthening (disclosed in 10-Q/10-K)
- Risk adjustment revenue from CMS as % of premium
- DOJ / OIG investigation disclosures (often in legal proceedings)

### Flag fires if
- Prior-period favorable reserve releases > 1% of premium for 2+ consecutive years (smoothing)
- OR MLR improving in absence of premium re-pricing or utilization commentary
- OR new or expanded DOJ risk-adjustment investigation disclosed
- OR risk-adjustment revenue growing faster than membership for 2+ years

### Why it matters
This is the live wire. UnitedHealth, Humana, Elevance, Centene have all faced DOJ scrutiny over Medicare Advantage risk-adjustment coding (HCC upcoding). Reserve releases are the cleanest tool payers have to smooth EPS — Health Net, WellCare, and others have been called out historically.

---

## 4. IBNR (Incurred But Not Reported) Reserves

### Inputs
- IBNR reserves as % of medical claims expense (managed care)
- Days claims payable trend
- Prior-period development table (ASC 944 disclosure)

### Flag fires if
- Days claims payable declining >2 days YoY (under-reserving)
- OR favorable prior-period development > 2% of reserves consistently
- OR IBNR / claims expense declining without disclosed claim cycle improvement

### Why it matters
IBNR is a discretionary estimate. Under-reserving inflates current EPS at the cost of future "surprise" charges.

---

## 5. Roll-Up / Goodwill Risk (physician groups, dental, vet, behavioral health, dialysis, post-acute)

### Inputs
- Acquisition cadence (deals per year, 3-yr trend)
- Goodwill / total assets
- Goodwill / equity
- "Same-store" or "same-facility" revenue growth vs. reported growth
- Earnouts / contingent consideration on BS

### Flag fires if
- Goodwill > 50% of total assets in a roll-up structure
- OR same-store growth turning negative while reported growth stays positive (acquisitions masking organic decline)
- OR contingent consideration adjustments boosting EBITDA materially
- OR "transaction and integration costs" run-rated at >3% of revenue for 3+ years (becomes recurring)

### Why it matters
Healthcare services is full of PE-backed and PE-exited roll-ups (US Physical Therapy, Surgery Partners, AdaptHealth, Option Care). The classic failure mode is organic decline hidden by deal flow until deal flow stops. AdaptHealth's accounting issues in 2021 are the textbook recent case.

---

## 6. 340B Program Revenue (hospitals, specialty pharmacies)

### Inputs
- 340B program disclosures in revenue notes
- Specialty pharmacy revenue growth vs. infusion/clinic visit volume

### Flag fires if
- 340B revenue or related contract pharmacy revenue growing >2x underlying volume
- OR new 340B-related litigation or HRSA action disclosed

### Why it matters
340B is under regulatory pressure. Companies leaning on it for margin (CHS, HCA-adjacent specialty pharmacy plays, Apria-like models) carry policy tail risk that doesn't show in ratios.

---

## 7. Distributor & PBM-Specific (McKesson, Cardinal, Cencora, CVS Caremark, ESI/Cigna, OptumRx)

### Inputs
- Gross-to-net manufacturer rebate disclosures
- DIR fee disclosures (PBMs / pharmacies)
- Inventory days at distributors (channel positioning)
- Customer concentration disclosures
- Generic drug pricing investigations

### Flag fires if
- Inventory days at a distributor rising >5 days YoY (channel stuffing into pharmacies)
- OR change in gross vs. net revenue presentation
- OR new generic pricing or rebate-related investigation disclosed
- OR "revenue from agency relationships" reclassified

### Why it matters
McKesson HBOC is the historical case. More recently, all three big distributors and PBMs have ongoing FTC and DOJ exposure on generics pricing and rebate pass-through. Gross vs. net presentation is the lever for PBMs — recharacterizing rebates moves billions.

---

## 8. Self-Pay / Charity Care Reclassifications (hospitals)

### Flag fires if
- Material reclassification between charity care and bad debt disclosed in latest 10-K
- OR uncompensated care % of gross charges changing >100bps without policy disclosure

### Why it matters
Tenet and HCA have both been investigated for steering self-pay accounts between buckets to optimize reported margins.

---

## 9. DOJ / False Claims Act Exposure (sector-wide)

### Inputs
- Legal proceedings note: search for "False Claims Act," "qui tam," "DOJ," "OIG," "CIA" (corporate integrity agreement)
- Any settlement accruals

### Flag fires if
- New FCA / qui tam matter disclosed
- OR settlement accrual recorded > 1% of revenue
- OR CIA in place and 10-K mentions compliance "matters"

### Why it matters
DOJ healthcare fraud actions are not random — they cluster on specific business models. A new qui tam complaint usually means an insider with documents has alleged something specific. These are leading indicators of restatements and management changes.

---

## Subgroup quick map

| Subgroup | Top 3 things to check |
|---|---|
| Hospitals | Bad debt provision trend, 340B exposure, payer mix |
| Managed care / MA | Risk-adjust revenue, MLR reserve releases, DOJ disclosures |
| PBMs | Gross-vs-net presentation, rebate accounting, FTC actions |
| Distributors | Channel inventory days, customer concentration, opioid settlements |
| Physician / dental / vet roll-ups | Same-store vs. reported growth, goodwill bloat, contingent consideration |
| Post-acute (SNF, home health, hospice) | Length-of-stay metrics, RAC audit exposure, FCA matters |
| Dialysis | Commercial mix shift commentary, Medicare Advantage transition, FCA matters |
| Labs | Bad debt, Medicare lab fee schedule exposure, payer denials |
