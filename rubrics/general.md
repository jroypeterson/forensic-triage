# General Forensic Flags (sector-agnostic)

Apply these to every company. Each family lists the diagnostic ratios and the flag rules. **A family fires only when a *combination* triggers** — single-ratio flags are too noisy to act on.

---

## 1. Accruals Quality

### Ratios
- **Sloan accruals** = (ΔCurrent Assets − ΔCash − ΔCurrent Liabilities + ΔShort-term Debt − Depreciation) / Avg Total Assets
- **CFO/NI ratio** = Cash Flow from Operations / Net Income (TTM)
- **Cash conversion gap** = Net Income − CFO (4-quarter trailing)

### Flag fires if
- Sloan accruals > 10% of total assets **AND** CFO/NI < 0.8 for 2+ consecutive years
- OR CFO/NI < 0.5 in current year while reported NI is positive

### Why it matters
The single most replicated finding in forensic accounting research (Sloan 1996). High accruals predict earnings reversals. Companies that report earnings without cash backing are either growing aggressively into working capital or recognizing revenue too early.

---

## 2. Revenue Quality

### Ratios
- **DSO** = (AR / Revenue) × 365, computed on TTM
- **DSO YoY change** in days
- **Deferred revenue Δ** vs. revenue Δ
- **Gross margin trend** (3-yr)
- **Revenue growth deceleration** = (current YoY growth) − (prior YoY growth)

### Flag fires if
- DSO up >15% YoY **AND** revenue growth decelerating
- OR DSO up >25% YoY in any single year
- OR deferred revenue declining while revenue accelerating (consuming the backlog)
- OR gross margin expansion >300bps in a single year with no disclosed mix/pricing reason

### Why it matters
Channel stuffing, bill-and-hold, and premature recognition all leave fingerprints in receivables. Deferred revenue is the cleanest leading indicator for subscription/long-cycle businesses — when it shrinks while revenue grows, the company is eating its backlog.

---

## 3. Expense Capitalization

### Ratios
- **Capex / D&A** ratio (3-yr trend)
- **Capitalized software development costs** (from notes)
- **Intangibles / total assets** trend
- **R&D as % of revenue** trend (if previously meaningful)

### Flag fires if
- Capex/D&A > 1.5x with margin expansion in same period (suggests under-depreciation or aggressive capitalization)
- OR capitalized software dev costs growing > 2x revenue growth
- OR R&D % of revenue declining materially YoY without disclosed program completion

### Why it matters
The cleanest way to manufacture earnings is to move opex into the balance sheet. WorldCom did it with line costs. Modern software companies do it with capitalized dev. Watch for the ratio of what's expensed vs. capitalized.

---

## 4. Balance Sheet Bloat

### Ratios
- **Inventory days** = (Inventory / COGS) × 365
- **Inventory YoY growth** vs. revenue YoY growth
- **AR YoY growth** vs. revenue YoY growth
- **Goodwill / total assets**

### Flag fires if
- Inventory growing >1.5x revenue growth for 2+ quarters
- OR AR growing >1.5x revenue growth for 2+ quarters
- OR goodwill > 40% of total assets (impairment risk, often roll-up)

### Why it matters
Inventory and AR bloat both indicate the income statement is running ahead of underlying demand. Goodwill bloat is a different problem — it signals roll-up accounting where impairment becomes a single-event earnings hit.

---

## 5. Leverage Hiding

### Inputs
- Operating lease liabilities (post-ASC 842 — should be on BS)
- Mentions of "supplier finance," "factoring," "receivables securitization" in notes
- VIE disclosures
- Change in short-term debt vs. long-term debt mix

### Flag fires if
- Supplier finance / factoring program disclosed for the first time, or expanded materially
- OR new VIE disclosed
- OR ratio of short-term debt rising while long-term debt falling (refi risk hiding)

### Why it matters
Carillion, Greensill — supplier finance programs let companies hide payables as off-balance-sheet debt. Factoring does the same for receivables. SEC and FASB have been tightening disclosure but it's still a warning sign on its own.

---

## 6. Governance / Disclosure (CRITICAL — single flag = Red tier)

### Inputs
- 8-K Item 4.02 (non-reliance on prior financial statements) — **any one of these = automatic Red**
- 8-K Item 4.01 (auditor change) — investigate
- NT 10-K / NT 10-Q (late filing notification) — investigate
- Restatement disclosed in latest 10-K
- CFO turnover (especially repeat)
- Audit committee chair turnover

### Flag fires if
- Any of the above in the last 12 months

### Why it matters
These are the highest-signal events in forensic accounting. An 8-K 4.02 means management is telling you not to trust prior financials. An auditor leaving without a clean handoff is the auditor speaking through their feet.

---

## 7. Market Signals

### Inputs
- Form 4 insider sales (clusters of 3+ insiders selling within 30 days)
- Short interest as % of float
- Borrow cost / utilization (if available)
- 10b5-1 plan adoption clustering

### Flag fires if
- 3+ insiders selling within 30 days **AND** sales > 25% of holdings each
- OR short interest > 15% of float and rising
- OR multiple new 10b5-1 plans adopted in same quarter (often pre-announcement insulation)

### Why it matters
Insiders aren't always right but clusters are informative. High short interest plus rising borrow cost means sophisticated capital is paying real money to be short.

---

## 8. Text Signals (qualitative)

### Inputs
- 10-K MD&A word count YoY
- Risk factors section length YoY
- New risk factors added vs. prior year
- Management hedging language ("substantially," "approximately," "generally")

### Flag fires if
- MD&A length up >25% YoY with no major business change
- OR 3+ new risk factors added that relate to revenue recognition, internal controls, or going concern
- OR going-concern language appears for the first time

### Why it matters
Lawyers add language when there's something to defend. The Loughran-McDonald financial dictionary studies show that hedging and uncertainty language in 10-Ks predicts negative future returns and restatements. Use `edgar_notes` to pull risk factor diffs.

---

## Composite scores (computed but not headline)

Compute these for context, but **do not tier on them alone**:
- **Beneish M-Score** — original 8-variable model. Threshold: M > −1.78 = elevated. Weak for non-manufacturers.
- **Dechow F-Score** — accruals-based misstatement model. > 1.0 = above average risk.
- **Altman Z** — bankruptcy, not fraud, but useful context. < 1.8 = distress zone.
- **Sloan accruals decile** — already captured in Family 1 above.

Record these in `ratios_latest.csv` for trending. Mention them in the report only when they corroborate a family flag.
