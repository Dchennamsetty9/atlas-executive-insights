# Revenue Decomposition Methodology

This document describes how the dollarized impact decomposition works in the KPI pacing context and how those concepts map to the `/api/insights/impact-decomposition` endpoint.

---

## Two parallel funnel paths

The Won Amount variance is explained by decomposing it across two parallel funnel paths. Both start from the same opportunity base and converge on the same Won Amount outcome.

| Funnel | Path | Best for |
|--------|------|----------|
| **Opp Volume Funnel** | Opened Opps × Close Rate (Opps) = Won Opps → Won Opps × ADS = Won Amount | Volume-focused diagnoses: is the gap in lead volume or conversion? |
| **Dollar Funnel** | Opened Opps × Average Opp Size = Pipeline → Pipeline × Close Rate ($) = Won Amount | Value-focused diagnoses: is the gap in deal size or dollar conversion rate? |

Shared nodes — Opened Opps, Won Opps, Pipeline, and Won Amount — appear in both funnels to keep the two views aligned.

---

## Dollarized impact formulas

For each KPI, the dollarized impact isolates that KPI's contribution to the revenue gap by holding all other inputs at their targets:

| KPI | Dollarized Impact formula |
|-----|--------------------------|
| Opened Opps | (Actual − Target) × Close Rate (Opps) Target × ADS Target |
| Close Rate (Opps) | Opened Opps Actual × (Actual − Target) × ADS Target |
| Won Opps | (Actual − Target) × ADS Target |
| ADS | Won Opps Actual × (Actual − Target) |
| Won Amount | Actual − Target |
| Average Opp Size | Opened Opps Actual × (Actual − Target) × Close Rate ($) Target |
| Pipeline | (Actual − Target) × Close Rate ($) Target |
| Close Rate ($) | Pipeline Actual × (Actual − Target) |

---

## Additivity rule

Within each funnel equation, the dollarized impacts of the two input KPIs **sum exactly to the output KPI's impact**:

| Equation | Additivity |
|----------|------------|
| Opened Opps × Close Rate (Opps) = Won Opps | Opened Opps impact + Close Rate (Opps) impact = Won Opps impact |
| Won Opps × ADS = Won Amount | Won Opps impact + ADS impact = Won Amount impact |
| Opened Opps × Average Opp Size = Pipeline | Opened Opps impact + Average Opp Size impact = Pipeline impact |
| Pipeline × Close Rate ($) = Won Amount | Pipeline impact + Close Rate ($) impact = Won Amount impact |

This means the impacts are a **complete, non-overlapping decomposition** within each equation. The two inputs fully explain the output gap — nothing is left unattributed.

Cross-funnel comparisons (e.g., comparing an Opp Volume Funnel impact against a Dollar Funnel impact) should be done with care, since the two funnels are parallel paths, not additive paths.

---

## How to read the impact decomposition

1. **Start at Won Amount** — see the total variance to target (the headline gap).
2. **Scan Dollarized Impacts** across all KPI rows — the darkest red block is your primary drag; the darkest green is your tailwind.
3. **Volume vs. value** — volume issues (few Opened Opps or low Close Rate (Opps)) show up more clearly in the Opp Volume Funnel; value issues (Average Opp Size, Close Rate $) are more visible in the Dollar Funnel.
4. **Apply segment filters** to localise the driver before prescribing action.

---

## Impact percentage

Each block also shows the impact as a percentage of the total Closed Won Amount gap:

```
Impact % = KPI Dollarized Impact ÷ |Closed Won Amount Gap|
```

For example, if total CWA is $1M below target and the ADS impact is –$300K, the ADS impact percentage is –30% — ADS under-performance accounts for 30% of the total revenue shortfall.

**Note:** Impacts within the same funnel equation are additive and will together sum to 100% of the output gap (e.g., Opened Opps % + Close Rate (Opps) % = Won Opps % = some portion of total CWA gap). An impact percentage greater than 100% is possible when one input is over-performing while the other is under-performing.

---

## Pacing targets — not pro-rata

The targets used are **not simple time-pro-rated targets**. They are derived from the historical median attainment path over the past five years, accounting for typical within-quarter pacing patterns (e.g., end-of-quarter surges).

---

## API endpoint

The `/api/insights/impact-decomposition` endpoint returns decomposition results following this methodology. Each item in the `decomposition` array corresponds to one KPI row with fields:
- `type` — KPI name
- `impact_dollars` — dollarized impact value
- `impact_pct` — impact as a percentage of the total gap
- `actual` / `target` — current vs. target values
