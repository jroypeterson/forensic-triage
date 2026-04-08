# Medtech Forensic Flags

Apply *in addition to* `general.md` for any company tagged `medtech` in the watchlist. Subgroups: implantable devices, capital equipment, consumables / single-use, diagnostics (IVD), digital health hardware, dental.

Medtech blowups historically come from a different place than biotech or HC services. The recurring patterns: distributor channel stuffing, capital-equipment-vs-consumables mix games, warranty/recall under-reserving, R&D capitalization, FCPA, and ASC 606 allocation in bundled deals.

---

## 1. Distributor Channel Inventory (high priority for medtech)

### Inputs
- Disclosed % of revenue through distributors vs. direct
- Distributor inventory disclosure (sometimes in MD&A)
- Days in inventory at distributor (if disclosed)
- Sell-in vs. sell-through commentary in transcripts

### Flag fires if
- Revenue growth > 1.5x reported end-market growth and distributor mix is high
- OR end-of-quarter / end-of-year revenue concentration disclosed
- OR distributor inventory builds disclosed
- OR change from sell-in to sell-through accounting (or vice versa)

### Why it matters
Sell-in accounting lets a device company recognize revenue on shipment to a distributor, regardless of actual hospital uptake. Symmetry Medical, Bausch (Valeant) Salix, and several smaller orthopedic players have all blown up on channel stuffing. This is the single most common medtech accounting issue.

---

## 2. Consignment Inventory at Hospitals (orthopedics, cardiac, surgical)

### Inputs
- Inventory composition note: "consignment" or "field inventory" line items
- Inventory days vs. peers
- Inventory write-down history

### Flag fires if
- Consignment / field inventory growing >1.5x revenue
- OR repeated inventory write-downs (suggests prior over-build)
- OR inventory days materially above peer median with no disclosed reason

### Why it matters
Orthopedic and cardiac device companies stage inventory at hospital sites — instrument trays, implant consignments. This inventory is real but often stale. Stryker, Zimmer, and smaller competitors have all taken material write-downs. The line between "field-ready inventory" and "channel stuffing" is thin.

---

## 3. Capital Equipment vs. Consumables Mix (Intuitive Surgical model, IVD instruments, etc.)

### Inputs
- Segment revenue split: equipment vs. consumables / service
- Placements vs. utilization disclosures
- Operating lease / "placed equipment" programs (reagent-rental model)
- Deferred revenue from service contracts

### Flag fires if
- System placements growing without proportional consumable / procedure growth (placed but unused)
- OR shift from sale to lease/placement model with no clear cash flow disclosure
- OR service revenue deferred declining while equipment placements rising

### Why it matters
The razor/razorblade model is the medtech ideal — but companies that aren't selling enough razors will sometimes "place" systems on favorable terms to keep the headline placement number up. Diagnostics (Quidel, Hologic, Cepheid in the past) and surgical robotics (Intuitive imitators) are vulnerable.

---

## 4. Bundled Sales / ASC 606 Allocation (capital equipment + service + consumables)

### Inputs
- Revenue note: standalone selling price (SSP) methodology
- Changes in deferred revenue components
- Disclosure of multi-element arrangements

### Flag fires if
- SSP methodology change disclosed
- OR allocation between equipment / service / consumables shifts >5% YoY
- OR upfront equipment revenue growing while deferred service revenue not building proportionally

### Why it matters
Under ASC 606, companies have to allocate transaction price across performance obligations. Pulling more value into the upfront equipment piece accelerates revenue. Hewlett-Packard / Autonomy and several software cases set the precedent; medtech is doing the same thing on bundled hospital deals.

---

## 5. R&D Capitalization

### Inputs
- Capitalized software / development costs in intangibles roll-forward
- R&D as % of revenue trend
- Notes on internal-use vs. external-use software (ASC 350-40)

### Flag fires if
- Capitalized development costs growing > 2x R&D expense growth
- OR R&D % declining materially while product launch cadence is constant
- OR new disclosure of capitalizing development costs that were previously expensed

### Why it matters
US GAAP requires expensing R&D until technological feasibility. Aggressive companies capitalize earlier than peers. IFRS reporters (European medtech with US listings) capitalize more aggressively by default — calibrate against the peer group, not the rule.

---

## 6. Warranty Reserves & Product Liability

### Inputs
- Warranty reserve roll-forward (current and noncurrent)
- Warranty expense as % of equipment revenue
- Product liability accruals trend
- Recall history (FDA recall database — pull via WebSearch if material)

### Flag fires if
- Warranty reserve / equipment revenue declining > 50bps with no product mix explanation
- OR product liability accrual additions exceed 1% of revenue without disclosed settlements
- OR Class I / Class II FDA recall in last 12 months not yet reflected in reserves

### Why it matters
Under-reserving warranty is a slow leak — small reserve releases each quarter that reverse when the recall hits. Philips Respironics CPAP recall is the textbook recent disaster. Reserve adequacy is one of the highest-value forensic checks for capital equipment makers.

---

## 7. FCPA Exposure (international medical sales)

### Inputs
- Legal proceedings: search for "FCPA," "anti-corruption," "DOJ inquiry"
- % revenue from emerging markets (China, MENA, LATAM, Eastern Europe)
- Disclosed compliance program changes / monitor appointments

### Flag fires if
- New FCPA inquiry or settlement disclosed
- OR > 30% revenue from high-FCPA-risk geographies and no compliance program disclosure
- OR change in distributor relationships in those regions disclosed

### Why it matters
Medical device sales in emerging markets routinely run through distributors who use payments to physicians. SEC FCPA enforcement against medtech is a recurring theme — Stryker, Smith & Nephew, Biomet, Olympus, Orthofix have all settled. The first sign is often a vague disclosure that "the Company is cooperating with an inquiry."

---

## 8. Royalty / Milestone Revenue (diagnostics, licensed platforms)

### Inputs
- License revenue as % of total
- Lumpy license revenue patterns
- Bill-and-hold or upfront license disclosures

### Flag fires if
- License / milestone revenue concentrated in a single quarter > 5% of TTM revenue
- OR upfront license fees recognized fully at contract inception with multi-year deliverables disclosed
- OR collaborative arrangement revenue netted vs. grossed up inconsistently

### Why it matters
License and milestone revenue is high-margin and lumpy, which makes it useful for hitting quarters. Watch for whether the "performance obligation" is really delivered at signing.

---

## 9. Recall / Inventory Write-Off Cadence

### Flag fires if
- Inventory write-offs in 2+ of last 4 quarters
- OR "excess and obsolete" reserve building > 5% of inventory
- OR product discontinuation announcements followed by inventory charge in subsequent quarter

### Why it matters
Pattern of write-offs suggests structural over-production or product life-cycle mismanagement. Often correlates with channel stuffing earlier in the cycle.

---

## Subgroup quick map

| Subgroup | Top 3 things to check |
|---|---|
| Implantable devices (ortho, cardio, spine) | Consignment inventory, distributor sell-in, FCPA |
| Capital equipment (surgical robots, imaging) | Placement vs. utilization, bundled ASC 606 allocation, deferred service |
| Consumables / single-use | Channel inventory days, customer concentration, sell-through |
| Diagnostics (IVD) | Reagent-rental placement programs, instrument vs. consumable mix, CLIA / payer denials |
| Digital health hardware | R&D capitalization, warranty reserves, recall history |
| Dental / orthodontic | Distributor inventory, consumer financing receivables (if applicable) |
