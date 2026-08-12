---
title: "Dollarized Impact"
category: metric
dashboard: kpi_pacing
sources: [kpi_pacing_sfdc, cds_targets_monthly, dates]
updated: 2026-04-27
---

# Dollarized Impact

## What it is

For each KPI, the **dollarized impact** translates the gap between actual and target performance into a revenue dollar figure. It answers: *"If this KPI had been exactly on target, how much would that have changed our Closed Won Amount?"*

This is shown in the bottom row of each KPI card block, and as a percentage of the total revenue gap.

## The total gap

The **Closed Won Amount** impact (`Current Won Amount Dollarized Impact`) is the simplest — it is just the raw dollar gap:

```
Closed Won Amount Impact = Actual CWA today − Target CWA today
```

Positive = ahead of target. Negative = behind. This is the total gap that all other impacts try to explain.

## How each KPI's impact is calculated

Each of the other seven KPIs represents a different driver of the Closed Won Amount gap. The formulas isolate one driver at a time by holding others constant at target:

| KPI | Impact formula |
|-----|----------------|
| **Won Opps** | (Actual won opps − Target won opps) × Target ADS |
| **ADS** | (Actual ADS − Target ADS) × Actual won opps |
| **Opened Opps** | (Actual opened opps − Target opened opps) × Target close rate (opps) × Target ADS |
| **Close Rate (Opps)** | Actual opened opps × (Actual close rate opps − Target close rate opps) × Target ADS |
| **Pipeline** | (Actual pipeline − Target pipeline) × Target close rate ($) |
| **Average Opp Size** | Actual opened opps × (Actual AOS − Target AOS) × Target close rate ($) |
| **Close Rate ($)** | Actual pipeline × (Actual close rate $ − Target close rate $) |

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

## How to use the impact percentage

Each block also shows the impact as a **percentage of the total Closed Won Amount gap**:

```
Impact % = KPI Dollarized Impact ÷ |Closed Won Amount Gap|
```

For example, if total CWA is $1M below target and the ADS impact is –$300K, the ADS impact percentage is –30%. This tells you ADS under-performance accounts for 30% of the total revenue shortfall.

**Note:** Impacts within the same funnel equation are additive and will together sum to 100% of the output gap (e.g., Opened Opps % + Close Rate (Opps) % = Won Opps % = some portion of total CWA gap). An impact percentage greater than 100% is possible when one input is over-performing while the other is under-performing.

## Practical use

Use the impact percentages to **prioritise focus**:
- Which KPIs show the largest negative impacts? Those are the levers most worth pulling.
- A large negative pipeline impact + small close rate impact suggests a volume problem (not enough deals in the funnel).
- A large negative close rate impact + small pipeline impact suggests a conversion problem (enough opportunities but not winning them).

## Related pages

- [[kpi-pacing.metric.running-value]] — The actual values used in these calculations
- [[kpi-pacing.metric.target-median-pacing]] — The target values used in these calculations
- [[kpi-pacing.visual.kpi-scorecard-blocks]] — Where impact values appear on the page
