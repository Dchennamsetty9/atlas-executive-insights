---
title: "KPI Scorecard Blocks"
category: visual
dashboard: kpi_pacing
sources: [kpi_pacing_sfdc, cds_targets_monthly, dates]
updated: 2026-04-27
---

# KPI Scorecard Blocks

## What this visual is

The KPI Scorecard Blocks are colour-coded card clusters arranged into two funnel diagrams on the Overview page. They show the same three data points for each KPI: **Current Value**, **Current Target**, and **Dollarized Impact**.

The blocks are not independent — they are arranged to show the arithmetic relationships between KPIs. The Opp Volume Funnel and Dollar Funnel each chain three KPI blocks together with × and = symbols to show how the metrics multiply together to produce Closed Won Amount.

## How to read a block

Each block has three card rows stacked vertically:

| Row | Label | What it shows | Format |
|-----|-------|--------------|--------|
| **Top** | Current Value | Today's actual metric value (QTD as of latest data) | Dollar, count, or % |
| **Middle** | Current Target | Where this metric should be at today's point in the quarter | Same format |
| **Bottom** | Dollarized Impact | Revenue impact of this KPI's gap from target | Always dollars |

The **background colour** tells you at a glance whether this KPI is helping or hurting:
- **Green** — performing above target
- **Red** — performing below target
- Colour intensity scales with the size of the dollarized impact

## The two funnels

### Opp Volume Funnel

Shows how deal volume drives won revenue:

```
Opened Opps  ×  Close Rate (Opps)  =  Won Opps
                Won Opps  ×  ADS   =  Won Amount
```

The Won Opps block appears in both equations. An arrow in the layout carries it from the first row to the second. The **+** symbol between rows connects the dollarized impact layer — the impacts from each block add up (directionally) to the total Won Amount impact.

### Dollar Funnel

Shows how dollar-value metrics drive won revenue:

```
Opened Opps  ×  Average Opp Size  =  Pipeline
               Pipeline  ×  Close Rate ($)  =  Won Amount
```

The same block structure applies. Won Amount appears at the end of both funnels, showing the same outcome reached by two different decomposition paths.

## The eight KPI blocks

### Opened Opps
How many new sales opportunities have been opened this quarter vs. target.
- **Current Value:** `opened_opps_today`
- **Current Target:** `opened_opps_target_today`
- **Dollarized Impact:** `Current Opened Opps Dollarized Impact`

### Close Rate (Opps)
What fraction of opened opportunities have been won, vs. target.
- **Current Value:** `close_rate_opps_today` (%)
- **Current Target:** `close_rate_opps_target_today` (%)
- **Dollarized Impact:** `Current Close Rate (Opps) Dollarized Impact`

### ADS — Average Deal Size
Average dollar value per closed-won deal, vs. target.
- **Current Value:** `ads_today`
- **Current Target:** `ads_target_today`
- **Dollarized Impact:** `Current ADS Dollarized Impact`

### Won Opps
Total deals closed won this quarter vs. target.
- **Current Value:** `won_opps_today`
- **Current Target:** `won_opps_target_today`
- **Dollarized Impact:** `Current Won Opps Dollarized Impact`

### Closed Won Amount
Total revenue closed this quarter vs. target. The headline outcome that all other impacts decompose.
- **Current Value:** `closed_won_amount_today`
- **Current Target:** `closed_won_amount_target_today`
- **Dollarized Impact:** `Current Won Amount Dollarized Impact` (this is the total revenue gap itself)

### Pipeline
Total dollar value of pipeline *opened/created this quarter* vs. target. This is a **flow metric** — it counts the dollar value of opportunities that have entered the funnel this quarter, regardless of whether those deals are still open today.

> ⚠ **"Pipeline" here is not the same as "Active Pipeline" (stock of currently-open deals)**. If you want to see how much pipeline is currently open right now (all open deals, not just those created this quarter), use the **Active Pipeline Pulse** page in Performance Hub.

- **Current Value:** `pipeline_today`
- **Current Target:** `pipeline_target_today`
- **Dollarized Impact:** `Current Pipeline Dollarized Impact`

### Average Opp Size (AOS)
Average dollar value per open opportunity vs. target.
- **Current Value:** `aos_today`
- **Current Target:** `average_opp_size_target_today`
- **Dollarized Impact:** `Current AOS Dollarized Impact`

### Close Rate ($)
Dollar-value conversion rate (won amount ÷ opened pipeline) vs. target.
- **Current Value:** `close_rate_$_today`
- **Current Target:** `close_rate_$_target_today`
- **Dollarized Impact:** `Current Close Rate ($) Dollarized Impact`

## Understanding the dollarized impacts

The dollarized impact answers: *"If this KPI had been exactly on target, how much of the closed-won revenue gap would have been eliminated?"*

For example, if Closed Won Amount is $1M below target and the ADS impact is –$300K, it means deal sizes being smaller than target accounts for $300K of the $1M shortfall.

**Additivity rule:** Within each funnel equation, the two input impacts sum exactly to the output impact:
- Opened Opps impact + Close Rate (Opps) impact = Won Opps impact
- Won Opps impact + ADS impact = Won Amount impact (Opp Volume path)
- Opened Opps impact + Average Opp Size impact = Pipeline impact
- Pipeline impact + Close Rate ($) impact = Won Amount impact (Dollar path)

This makes the decomposition complete within each equation — the two inputs fully account for the output gap. You can directly compare impacts across KPIs to prioritise which lever is driving the miss most.

See [[kpi-pacing.metric.dollarized-impact]] for the full calculation methodology and formulas.

## Related pages

- [[kpi-pacing.page.overview]] — Full page layout including the two funnel structures
- [[kpi-pacing.metric.running-value]] — How Current Values are calculated
- [[kpi-pacing.metric.target-median-pacing]] — How Current Targets are set
- [[kpi-pacing.metric.dollarized-impact]] — How Dollarized Impacts are derived
- [[kpi-pacing.filters]] — How slicers affect these cards

---

> **Metric definitions:** [[kpi-pacing.metrics-glossary]] | [[shared.metrics-glossary]]
