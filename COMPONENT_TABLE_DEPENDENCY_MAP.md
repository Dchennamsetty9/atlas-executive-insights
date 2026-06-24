# Atlas Executive Insights — Component × Table Dependency Map

**Purpose:** Show exactly which pre-computed tables each app component requires, enabling incremental rollout and impact analysis.

---

## 📱 Component Inventory & Table Dependencies

### **View 1: Business Performance** (KPI Health Summary)

#### Component 1.1: KPI Card — Current Status

**Purpose:** Display single KPI with target achievement %, color-coded status badge

**Current Approach (On-Demand)**
```sql
SELECT kpi_value, target FROM gaim_kpi_current_state WHERE kpi_id = ?
-- Compute: achievement_pct = (value / target) * 100
-- Compute: status = 'exceeding' | 'on_track' | 'at_risk'
-- Latency: 2–3 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT current_value, target_value, target_achievement_pct, variance_vs_target
FROM mdl_kpi_snapshot_daily
WHERE snapshot_date = CURRENT_DATE() AND kpi_id = ?
-- Latency: 100–150 ms
```

| Requirement | Table | Query Purpose |
|---|---|---|
| Current KPI value | `mdl_kpi_snapshot_daily` | Lookup current value + achievement |
| Previous day comparison | `mdl_kpi_snapshot_daily` | Trend arrow + variance |
| Status classification | Computed from `mdl_kpi_snapshot_daily` | Color badge (exceeding/on-track/at-risk) |
| KPI definition | `mdl_dim_kpi` | Title, description, owner info |

**Tables Required:** 2 (`mdl_kpi_snapshot_daily`, `mdl_dim_kpi`)  
**Response Time Gain:** 2–3s → 100–150ms

---

#### Component 1.2: Business Performance Panel — Health Summary

**Purpose:** Show aggregate KPI status across all metrics (summary card: X at risk, Y on track, Z exceeding)

**Current Approach**
```python
# Load 10+ KPI cards, classify each, aggregate counts
# Latency: 5–8 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT 
  SUM(CASE WHEN target_achievement_pct >= 110 THEN 1 ELSE 0 END) as exceeding_count,
  SUM(CASE WHEN target_achievement_pct >= 90 AND target_achievement_pct < 110 THEN 1 ELSE 0 END) as on_track_count,
  SUM(CASE WHEN target_achievement_pct < 90 THEN 1 ELSE 0 END) as at_risk_count
FROM mdl_kpi_snapshot_daily
WHERE snapshot_date = CURRENT_DATE() AND product = 'Total'
-- Latency: 100–200 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| All KPI snapshot data | `mdl_kpi_snapshot_daily` | Aggregate counts + classification |
| Weekly sparkline for chart | `mdl_kpi_trend_weekly` | Historical trend (52 weeks) |
| KPI metadata | `mdl_dim_kpi` | Display names, thresholds |

**Tables Required:** 3 (`mdl_kpi_snapshot_daily`, `mdl_kpi_trend_weekly`, `mdl_dim_kpi`)  
**Response Time Gain:** 5–8s → 150–300ms

---

#### Component 1.3: ARR Trend Chart — Time Series

**Purpose:** Show ARR historical trend + forecast scenarios (actuals, best/worst case)

**Current Approach**
```sql
-- Join gaim_pipeline_daily_snapshot (historical ARR)
-- Union with arr_forecast_v2 (forecast)
-- Compute weekly aggregates on-the-fly
-- Latency: 4–6 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT forecast_date, arr_value, arr_worst_case, arr_best_case, model
FROM mdl_arr_forecast_consolidated
WHERE product = 'Total' AND geography = 'All'
ORDER BY forecast_date
-- Latency: 50–100 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| ARR actuals + forecast | `mdl_arr_forecast_consolidated` | Dual series (actuals + forecast) |
| Historical context | `mdl_arr_historical_context` | 5-year context for confidence bands |
| Forecast accuracy | `mdl_forecast_accuracy_leaderboard` | Show model MAPE scores |
| Refresh timestamp | `mdl_forecast_refresh_log` | Display "updated X hours ago" |

**Tables Required:** 4 (`mdl_arr_forecast_consolidated`, `mdl_arr_historical_context`, `mdl_forecast_accuracy_leaderboard`, `mdl_forecast_refresh_log`)  
**Response Time Gain:** 4–6s → 50–150ms

---

#### Component 1.4: Pipeline Chart — Waterfall by Stage

**Purpose:** Show pipeline breakdown by stage (Prospect → Decision → Closed)

**Current Approach**
```sql
-- Query gaim_pipeline_daily_snapshot
-- Group by stage, product, geography
-- Compute YoY/QoQ deltas on-the-fly
-- Latency: 3–5 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT stage, deal_count, total_arr, avg_deal_size, growth_pct_qoq
FROM mdl_pipeline_daily_rollup
WHERE snapshot_date = CURRENT_DATE() AND product = 'Total' AND geography = 'All'
ORDER BY stage
-- Latency: 50–100 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| Current pipeline snapshot | `mdl_pipeline_daily_rollup` | Stage breakdown + counts |
| YoY/QoQ comparison | `mdl_pipeline_segment_comparison` | Growth % overlay |
| Segment labels | `mdl_dim_product`, `mdl_dim_geography` | Stage names, geo labels |

**Tables Required:** 4 (`mdl_pipeline_daily_rollup`, `mdl_pipeline_segment_comparison`, `mdl_dim_product`, `mdl_dim_geography`)  
**Response Time Gain:** 3–5s → 100–200ms

---

### **View 2: Key Performance Indicators (KPI Dashboard)**

#### Component 2.1: KPI Grid — Leaderboard / Rankings

**Purpose:** Show all KPIs ranked by achievement, filterable by product/geo/channel

**Current Approach**
```python
# Load all KPI snapshots, rank them, paginate
# Latency: 3–5 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT kpi_id, dimension_value, achievement_pct, rank, is_top_performer
FROM mdl_kpi_scorecard_ranks
WHERE snapshot_date = CURRENT_DATE() AND dimension_name = 'product' AND dimension_value = 'UCC'
ORDER BY rank
-- Latency: 50–150 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| All KPI rankings | `mdl_kpi_scorecard_ranks` | Ranked list by dimension |
| KPI definitions | `mdl_dim_kpi` | Display names, metric types |

**Tables Required:** 2 (`mdl_kpi_scorecard_ranks`, `mdl_dim_kpi`)  
**Response Time Gain:** 3–5s → 50–150ms

---

#### Component 2.2: KPI Detail Modal — Drill-Down

**Purpose:** Show deep-dive for one KPI: current + historical + variance breakdown

**Current Approach**
```sql
-- Load current KPI data
-- Load 52 weeks of history (separate query)
-- Compute variance vs. target (separate calc)
-- Latency: 4–6 seconds (3 queries)
```

**New Approach (Pre-Computed)**
```sql
SELECT current_value, target_value, variance_vs_target FROM mdl_kpi_snapshot_daily
WHERE snapshot_date = CURRENT_DATE() AND kpi_id = 'arr'
UNION ALL
SELECT NULL, NULL, NULL FROM mdl_kpi_trend_weekly
WHERE kpi_id = 'arr' AND fiscal_year >= YEAR(CURRENT_DATE()) - 1
-- Latency: 100–300 ms (single query)
```

| Requirement | Table | Purpose |
|---|---|---|
| Current snapshot | `mdl_kpi_snapshot_daily` | Current value, target, variance |
| Weekly trend | `mdl_kpi_trend_weekly` | 52-week sparkline + trend line |
| Variance analysis | `mdl_kpi_variance_analysis` | Detailed breakdown (by segment) |
| KPI metadata | `mdl_dim_kpi` | Threshold definitions, owner |

**Tables Required:** 4 (`mdl_kpi_snapshot_daily`, `mdl_kpi_trend_weekly`, `mdl_kpi_variance_analysis`, `mdl_dim_kpi`)  
**Response Time Gain:** 4–6s → 150–300ms

---

#### Component 2.3: Impact Waterfall — Attribution

**Purpose:** Show what drove KPI change (new business + expansion − churn − price)

**Current Approach**
```python
# Complex multi-table join + DAX-like calculation
# Requires Salesforce API calls + local compute
# Latency: 8–12 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT component_name, impact_dollars, impact_pct_of_total, component_trend
FROM mdl_impact_waterfall_components
WHERE impact_date = CURRENT_DATE() AND kpi_id = 'arr'
ORDER BY impact_dollars DESC
-- Latency: 100–200 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| Impact components | `mdl_impact_waterfall_components` | Waterfall segments + values |
| Current KPI value | `mdl_kpi_snapshot_daily` | For % calculations |

**Tables Required:** 2 (`mdl_impact_waterfall_components`, `mdl_kpi_snapshot_daily`)  
**Response Time Gain:** 8–12s → 150–300ms

---

### **View 3: Forecast (V2 Panel)**

#### Component 3.1: Forecast Chart — Model Visualization

**Purpose:** Display selected model (Prophet/Ensemble/ETS) with confidence bands

**Current Approach**
```sql
-- SELECT from arr_forecast_v2 OR forecast_prophet (different schemas)
-- Union results + filter by model/forecast_type
-- Latency: 2–4 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT forecast_date, arr_value, arr_worst_case, arr_best_case, model_confidence_pct
FROM mdl_arr_forecast_consolidated
WHERE product = 'Total' AND model = 'prophet'
ORDER BY forecast_date
-- Latency: 50–100 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| Forecast data | `mdl_arr_forecast_consolidated` | Time series with confidence bands |
| Model metadata | Cached in ForecastingPanel state | Display name, freshness |

**Tables Required:** 1 (`mdl_arr_forecast_consolidated`)  
**Response Time Gain:** 2–4s → 50–100ms

---

#### Component 3.2: Model Selector & Badges

**Purpose:** Show available models + MAPE accuracy scores

**Current Approach**
```sql
-- Query arr_forecast_v2_leaderboard
-- Latency: 1–2 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT model, mape_pct, rank_by_mape
FROM mdl_forecast_accuracy_leaderboard
WHERE evaluation_date = (SELECT MAX(evaluation_date) FROM mdl_forecast_accuracy_leaderboard)
ORDER BY rank_by_mape
-- Latency: 50–100 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| Model accuracy | `mdl_forecast_accuracy_leaderboard` | MAPE % for each model |
| Forecast metadata | Cached in component | Last refresh time |

**Tables Required:** 1 (`mdl_forecast_accuracy_leaderboard`)  
**Response Time Gain:** 1–2s → 50–100ms

---

#### Component 3.3: AI Insights Panel — Under Forecast

**Purpose:** Show AI-generated insights about forecast (momentum, confidence, risks)

**Current Approach**
```python
# Load forecast + KPI data → Pass to LLM → Stream response
# Latency: 10–15 seconds (includes LLM)
```

**New Approach (Pre-Computed)**
```sql
-- Pre-compute insight context, prompt LLM with cache
SELECT upside, downside, confidence, key_drivers, risks
FROM mdl_hidden_insights_cache  -- Pre-computed flags
-- Use as context for LLM prompt (faster narrowing)
-- Latency: 500–800 ms (LLM inference still dominates)
```

| Requirement | Table | Purpose |
|---|---|---|
| Insight cache | `mdl_hidden_insights_cache` | Pre-computed anomaly + risk flags |
| KPI correlation | `mdl_kpi_correlation_matrix` | Related metrics for context |
| Forecast data | `mdl_arr_forecast_consolidated` | Reference for LLM prompt |

**Tables Required:** 3 (`mdl_hidden_insights_cache`, `mdl_kpi_correlation_matrix`, `mdl_arr_forecast_consolidated`)  
**Response Time Gain:** 10–15s → 5–8s (LLM call still ~2–3s, but context pre-computed)

---

### **View 4: Extended Analysis (MQL, Deals, Coverage)**

#### Component 4.1: MQL Analytics Dashboard

**Purpose:** Show MQL volume, conversion funnel, trend analysis

**Current Approach**
```sql
-- Query gaim_mql_daily_snapshot
-- Compute conversion rates, trends on-the-fly
-- Latency: 3–4 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT mql_count, trial_count, cost_per_mql FROM mdl_mql_daily_summary
WHERE snapshot_date = CURRENT_DATE() AND product = 'Total'
-- Latency: 50–100 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| MQL daily snapshot | `mdl_mql_daily_summary` | Volume by source/segment |
| Conversion funnel | `mdl_mql_conversion_funnel` | Cohort-based conversion % |
| MQL trend | `mdl_mql_trend_analysis` | Weekly growth % |
| Dimension tables | `mdl_dim_product`, `mdl_dim_date` | Joins + filtering |

**Tables Required:** 5 (`mdl_mql_daily_summary`, `mdl_mql_conversion_funnel`, `mdl_mql_trend_analysis`, `mdl_dim_product`, `mdl_dim_date`)  
**Response Time Gain:** 3–4s → 100–150ms

---

#### Component 4.2: Deal Bands Visualization

**Purpose:** Show deal count/ARR distribution across size bands

**Current Approach**
```sql
-- Query gaim_deal_bands_snapshot
-- Compute distributions, ratios
-- Latency: 2–3 seconds
```

**New Approach (Pre-Computed)**
```sql
SELECT band_name, deal_count, total_arr, avg_arr
FROM mdl_deal_bands_snapshot
WHERE snapshot_date = CURRENT_DATE() AND product = 'Total'
-- Latency: 50–100 ms
```

| Requirement | Table | Purpose |
|---|---|---|
| Deal bands | `mdl_deal_bands_snapshot` | Distribution by size band |
| Segment comparison | `mdl_pipeline_segment_comparison` | YoY trends |

**Tables Required:** 2 (`mdl_deal_bands_snapshot`, `mdl_pipeline_segment_comparison`)  
**Response Time Gain:** 2–3s → 50–100ms

---

### **View 5: AI & Genie (Freeform Q&A)**

#### Component 5.1: Genie Assistant — Multi-Table Query

**Purpose:** Answer arbitrary questions (e.g., "What's driving MQL volume down?")

**Current Approach**
```python
# User question → Parse intent → Multi-table SQL query → LLM interpretation
# Latency: 10–20 seconds (5 queries + LLM)
```

**New Approach (Pre-Computed with RLS)**
```python
# User question → Parse intent → Single/few pre-computed table queries (RLS applied)
# → LLM interpretation
# Latency: 5–10 seconds (fewer queries + faster lookup)
```

| Requirement | Table | Purpose | RLS Applied? |
|---|---|---|---|
| All KPI data | `mdl_kpi_snapshot_daily` | Answer KPI questions | ✅ Yes |
| All pipeline data | `mdl_pipeline_daily_rollup` | Answer pipeline questions | ✅ Yes |
| All MQL data | `mdl_mql_daily_summary` | Answer marketing questions | ✅ Yes |
| Forecast data | `mdl_arr_forecast_consolidated` | Answer forecast questions | ✅ Yes |
| Insight cache | `mdl_hidden_insights_cache` | Pre-computed context | ✅ Yes |
| Correlations | `mdl_kpi_correlation_matrix` | Related metrics | ✅ Yes |
| Dimensions | `mdl_dim_*` (all) | Context + joining | ✅ Yes |

**Tables Required:** ALL 22 (with RLS per role)  
**Response Time Gain:** 10–20s → 5–10s (LLM streaming still ~2–3s)

---

## 🗂️ Summary Table Count by Feature

### Total Tables Required: 22

| Feature Area | # Tables | Tier | API Response |
|---|---|---|---|
| **Business Performance** | 7 | Core | 100–300 ms |
| **KPI Dashboard** | 6 | Core | 100–300 ms |
| **Forecast** | 5 | Core | 100–300 ms |
| **MQL Analytics** | 7 | Core | 100–200 ms |
| **Deal Bands** | 5 | Core | 50–150 ms |
| **AI Insights** | 8 | Core | 500–1000 ms |
| **Genie Q&A** | 22 | Extended | 5–10 sec |
| **Coverage Analysis** | 4 | Extended | 200–400 ms |

**Notes:**
- Many tables appear in multiple features (shared reference tables)
- Tier 1 "Core" = required for basic app functionality
- Tier 2 "Extended" = optional/enhancement features
- Response times include API + DB query (exclude LLM for AI features)

---

## 🔄 Incremental Rollout Path

### **Phase 1: MVP (Week 1)** — 8 tables, 4 core features
```
✅ mdl_dim_* (5 tables)           [Reference data]
✅ mdl_kpi_snapshot_daily          [Business Performance + KPI Grid]
✅ mdl_arr_forecast_consolidated   [Forecast panel]
✅ mdl_pipeline_daily_rollup       [Pipeline chart]
✅ mdl_job_run_history             [Audit]

Result: 4/8 features live, 95% performance gain for KPI/Forecast
```

### **Phase 2: Extended (Week 2)** — +7 tables, +3 features
```
✅ mdl_kpi_trend_weekly
✅ mdl_kpi_scorecard_ranks
✅ mdl_kpi_variance_analysis
✅ mdl_mql_daily_summary
✅ mdl_mql_conversion_funnel
✅ mdl_deal_bands_snapshot
✅ mdl_pipeline_segment_comparison

Result: 7/8 features live, all core analytics working
```

### **Phase 3: AI & Full Feature (Week 3)** — +6 tables, +1 feature
```
✅ mdl_forecast_accuracy_leaderboard
✅ mdl_arr_historical_context
✅ mdl_hidden_insights_cache
✅ mdl_kpi_correlation_matrix
✅ mdl_impact_waterfall_components
✅ mdl_mql_trend_analysis

Result: 8/8 features live, AI insights + Genie enabled
```

---

## 📊 Table Interdependencies (Build Order)

```
Level 0 (Independence)
  ├─ mdl_dim_kpi
  ├─ mdl_dim_product
  ├─ mdl_dim_geography
  ├─ mdl_dim_channel
  └─ mdl_dim_date

Level 1 (Source tables only)
  ├─ mdl_kpi_snapshot_daily        (src: gaim_kpi_current_state)
  ├─ mdl_pipeline_daily_rollup     (src: gaim_pipeline_daily_snapshot)
  ├─ mdl_mql_daily_summary         (src: gaim_mql_daily_snapshot)
  ├─ mdl_deal_bands_snapshot       (src: gaim_deal_bands_snapshot)
  └─ mdl_arr_forecast_consolidated (src: forecast_prophet, arr_forecast_v2)

Level 2 (Depends on Level 1)
  ├─ mdl_kpi_trend_weekly          (src: mdl_kpi_snapshot_daily)
  ├─ mdl_kpi_scorecard_ranks       (src: mdl_kpi_snapshot_daily)
  ├─ mdl_kpi_variance_analysis     (src: mdl_kpi_snapshot_daily)
  ├─ mdl_pipeline_segment_comparison (src: mdl_pipeline_daily_rollup)
  ├─ mdl_mql_trend_analysis        (src: mdl_mql_daily_summary)
  ├─ mdl_forecast_accuracy_leaderboard (src: arr_forecast_v2_leaderboard)
  ├─ mdl_impact_waterfall_components (src: mdl_kpi_snapshot_daily)
  └─ mdl_arr_historical_context    (src: external + mdl_arr_forecast_consolidated)

Level 3 (Depends on Levels 1–2)
  ├─ mdl_hidden_insights_cache     (src: mdl_kpi_*, mdl_pipeline_*, mdl_forecast_*)
  └─ mdl_kpi_correlation_matrix    (src: mdl_kpi_snapshot_daily)

Audit (Continuous)
  └─ mdl_job_run_history           (populated by all jobs)
```

---

## ✅ Verification Checklist — Per Component

### Business Performance View
```
[ ] KPI Card loads in < 200ms
[ ] Card shows current value, target, achievement %, status badge
[ ] Previous day comparison arrow correct
[ ] Sparkline displays 52-week trend
[ ] Health summary aggregates update same time as individual cards
```

### KPI Dashboard View
```
[ ] KPI Grid loads < 150ms
[ ] Leaderboard ranks correctly (1=best)
[ ] Detail modal shows current + 52w history + variance
[ ] Impact waterfall segments correct
[ ] Filters by product/geo/channel work with RLS
```

### Forecast View
```
[ ] Forecast chart loads < 100ms
[ ] Prophet + Ensemble models selectable
[ ] Model accuracy badges show (MAPE %)
[ ] Confidence bands display (worst/likely/best case)
[ ] Refresh time shows "Updated X hours ago"
[ ] AI insights load within 5s (LLM call)
```

### Extended Analysis View
```
[ ] MQL dashboard loads < 200ms
[ ] Deal bands chart displays < 150ms
[ ] Conversion funnel calculates correctly
[ ] YoY/QoQ trends compare correctly
[ ] All data respects RLS by user role
```

### Genie Q&A
```
[ ] Questions answered with pre-computed tables
[ ] Role-based filtering applied (user sees only own data)
[ ] Response time < 10s (including LLM)
[ ] Streaming works (progressive token generation)
```

---

## 🎯 Key Metrics Post-Deployment

| Metric | Target | Measurement |
|--------|--------|---|
| **KPI page load time** | < 500ms | Frontend + API |
| **Forecast load time** | < 300ms | Frontend + API |
| **Query latency (p95)** | < 300ms | Databricks query log |
| **Job success rate** | > 99% | mdl_job_run_history |
| **Data freshness** | < 4 hours | CURRENT_TIMESTAMP() - data_freshness |
| **Concurrent users** | 100+ | APP metrics |
| **Cost per query** | < $0.01 | Databricks consumption |

---

## 🔗 Cross-References

- **Full Architecture:** See `ARCHITECTURE_PRECOMPUTED_METRICS.md`
- **Job Definitions:** See `IMPLEMENTATION_GUIDE_JOBS.md`
- **Quick Reference:** See `QUICK_REFERENCE_PRECOMPUTED_METRICS.md`

---

**Status:** ✅ Complete Component Mapping Ready for Build  
**Last Updated:** June 23, 2026
