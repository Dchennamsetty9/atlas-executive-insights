---
title: "Overview Page"
category: page
dashboard: kpi_pacing
sources: [kpi_pacing_sfdc, cds_targets_monthly, TargetedMetrics]
similar_to: ["[[performance-hub.page.target-tracker]]"]
updated: 2026-04-28
---

# Overview Page

## What this page shows

The Overview page is the scorecard for the KPI Pacing dashboard. It presents all eight KPIs simultaneously as two side-by-side **funnel diagrams** — the Opp Volume Funnel and the Dollar Funnel — each showing the arithmetic relationship between KPIs and their contribution to the Closed Won Amount outcome.

The page is not a set of charts. It is built entirely from colour-coded card visuals that communicate performance at a glance.

## Page-level filter

The entire page is filtered to **exclude future dates** (`dates.future_flag = false`). All metrics show only data up to and including today.

## Layout

The page is 1,500 × 2,200 pixels. The layout flows top to bottom.

### Header (y ~0–80px)

A dark blue header bar spans the full width. The GoTo company logo appears in the top-left. Two **PolarisAI assistant buttons** appear in the top-right — clicking either opens the PolarisAI chat interface.

### Slicers (y ~80–160px)

Six slicers sit in a horizontal row below the header:

| Slicer | Field | Source table |
|--------|-------|-------------|
| Category | `TargetedMetrics[Category]` | TargetedMetrics |
| Fuel Source | `TargetedMetrics[Fuel_Source]` | TargetedMetrics |
| Sales Channel | `TargetedMetrics[Sales_Channel]` | TargetedMetrics |
| Product | `TargetedMetrics[Product_Group/Family/Genus]` | TargetedMetrics |
| Sales Market | `TargetedMetrics[Sales_Market]` | TargetedMetrics |
| Purchase Type | `TargetedMetrics[Purchase_Type]` | TargetedMetrics |

### Opp Volume Funnel (y ~160–1,180px)

The top half of the page shows the **Opp Volume Funnel** — the chain of multiplications that links pipeline activity to won opportunities:

```
Opened Opps  ×  Close Rate (Opps)  =  Won Opps
                Won Opps  ×  ADS   =  Won Amount
```

The funnel is laid out as two rows of three KPI blocks:

**Row 1:** Opened Opps × Close Rate (Opps) = Won Opps

**Row 2:** Won Opps × ADS = Won Amount

The Won Opps block appears in both rows — its value carries down from the first equation into the second. A visual arrow connects the Won Opps block in row 1 to Won Opps in row 2 to make this relationship explicit.

Between each pair of blocks, a large **×** or **=** symbol shows the arithmetic relationship. Between the two rows, a **+** symbol connects the dollarized impact row.

### Dollar Funnel (y ~1,180–2,200px)

The bottom half shows the **Dollar Funnel** — the equivalent chain in dollar terms:

```
Opened Opps  ×  Average Opp Size  =  Pipeline
                Pipeline  ×  Close Rate ($)  =  Won Amount
```

**Row 1:** Opened Opps × Average Opp Size = Pipeline

**Row 2:** Pipeline × Close Rate ($) = Won Amount

The same arithmetic symbols (×, =, +) connect the blocks.

### KPI block structure

Each KPI block in both funnels has a consistent three-row layout:

| Row | Label | What it shows |
|-----|-------|--------------|
| **Top** | Current Value | Today's actual metric value |
| **Middle** | Current Target | Where this metric should be today (Target Median Pacing) |
| **Bottom** | Dollarized Impact | Revenue impact of this KPI's gap vs. target (always in dollars) |

The block's **background colour** indicates performance:
- **Green** — KPI is at or above target (positive contribution)
- **Red** — KPI is below target (negative contribution)
- Colour intensity scales with the size of the impact

### Colour coding

Colour is driven by the dollarized impact measure for each KPI — not just whether actuals beat target. A KPI slightly above target in a low-impact dimension may be lighter green than a KPI significantly below target in a high-impact dimension.

## User-facing visuals on this page

| Visual | Type | Description |
|--------|------|-------------|
| Opp Volume Funnel | Card groups (6 KPI blocks) | Opened Opps × Close Rate (Opps) = Won Opps × ADS = Won Amount |
| Dollar Funnel | Card groups (6 KPI blocks) | Opened Opps × AOS = Pipeline × Close Rate ($) = Won Amount |
| 6 slicers | Slicer | Segment filtering |
| PolarisAI buttons (×2) | Image links | Opens PolarisAI chat |

For individual visual documentation see:
- [[kpi-pacing.visual.kpi-scorecard-blocks]]
- [[kpi-pacing.visual.polaris-ai-buttons]]
- [[kpi-pacing.filters]]

---

## Revenue decomposition methodology

The page explains the Won Amount variance by decomposing it across two parallel funnel paths. Both funnels start from the same opportunity base and converge on the same Won Amount outcome.

| Funnel | Path | Best for |
|--------|------|----------|
| **Opp Volume Funnel** | Opened Opps × Close Rate (Opps) = Won Opps → Won Opps × ADS = Won Amount | Volume-focused diagnoses: is the gap in lead volume or conversion? |
| **Dollar Funnel** | Opened Opps × Average Opp Size = Pipeline → Pipeline × Close Rate ($) = Won Amount | Value-focused diagnoses: is the gap in deal size or dollar conversion rate? |

Shared nodes — Opened Opps, Won Opps, Pipeline, and Won Amount — appear in both funnels to keep the two views aligned.

### Dollarized impact formulas

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

**Additivity rule:** Within each funnel equation, the two input impacts sum exactly to the output impact. For example:
- Opened Opps impact + Close Rate (Opps) impact = Won Opps impact
- Pipeline impact + Close Rate ($) impact = Won Amount impact

This makes the decomposition complete — no gap is left unattributed within each equation.

### Pacing targets — not pro-rata

The targets used are **not simple time-pro-rated targets**. They are derived from the historical median attainment path over the past five years, accounting for typical within-quarter pacing patterns (e.g., end-of-quarter surges). Full methodology is in [[kpi-pacing.metric.target-median-pacing]] and the [[kpi-pacing.page.historical-analysis]] page.

---

## How to read this page

1. **Start at Won Amount** — see the total variance to target (the headline gap).
2. **Scan Dollarized Impacts** across all KPI rows — the darkest red block is your primary drag; the darkest green is your tailwind.
3. **Volume vs. value** — volume issues (few Opened Opps or low Close Rate (Opps)) show up more clearly in the Opp Volume Funnel; value issues (Average Opp Size, Close Rate $) are more visible in the Dollar Funnel.
4. **Apply filters** (Sales Channel, Product, Sales Market, etc.) to localise the driver by segment before prescribing action.

> 🔴 **Card colour = severity** — the deeper the red, the larger the dollar miss on that KPI.
>
> 🖱 **Click any KPI card** to drill into the Historical Analysis page for trend detail.
>
> 📐 **Use dollarized impacts to compare levers directly** — e.g., "Is the miss in Opened Opps or Close Rate more impactful right now?"

---

## How this differs from [[performance-hub.page.target-tracker]]

Both pages show KPI performance against targets, but they serve different audiences and use cases.

| | KPI Trends — Overview | Performance Hub — Target Tracker |
|---|---|---|
| Layout | Two funnel diagrams (Opp Volume + Dollar) with colour-coded KPI cards | Five bullet charts + a wide pivot grid |
| KPIs shown | 8 KPIs arranged as arithmetic funnels showing how they relate | 5 headline KPIs + 13 columns in the grid (Won $, Deals, ADS, Close Rate, Created Pipeline, Active Pipeline, MQLs, etc.) |
| Targets | CDS planning targets; shows Target Median Pacing (historical benchmark) | Pro-rated daily targets; shows daily plan values |
| Gap metric | Dollarized Impact — translates every KPI gap into revenue dollars | Attainment % and absolute gap per KPI |
| Segmentation | 6 slicers (Category, Fuel Source, Channel, Product, Market, Purchase Type) | 10 segment dimensions via Column Selection slicer (Fuel Source, Geo, Channel, Product hierarchy, Purchase Type, Deal Band) |
| Time scope | Current quarter only | Any selectable quarter |
| Best for | "Are we on pace this quarter? Where is the gap?" | "How does each segment contribute to target? Show me any KPI by any dimension." |

---

> **Metric definitions:** [[kpi-pacing.metrics-glossary]] | [[shared.metrics-glossary]]
