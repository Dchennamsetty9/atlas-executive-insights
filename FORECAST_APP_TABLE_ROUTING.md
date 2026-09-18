# GAIM Executive App — Forecast Backend Table Routing Guide

> **Purpose**: Give this file to VS Code AI (Cursor / Copilot) as context so it can
> reroute every backend endpoint to read from the correct Delta table.
>
> **Last updated**: 2026-09-18 (after V2 pipeline run + BOQ calibration + forecast_type V1→V2 migration)

---

## 1. Architecture Overview

The forecast pipeline writes to a **two-table architecture** plus supporting tables:

| Layer | Table | Rows | Purpose | Freshness |
|-------|-------|------|---------|-----------|
| **DYNAMIC** | `forecast_app_snapshot` | 582 | Best current view: actuals + forward forecast. One row per `ds × product × sales_market`. Latest run only (no `MAX(run_date)` subquery needed). | 2026-09-18 |
| **STATIC** | `forecast_pure_predictions` | 1,602 | Model predictions only — what each model predicted. For audit, PowerBI, and backtesting. | 2026-09-18 |
| **WIDE** | `arr_forecast_powerbi_wide` | 1,648 | Pivoted from static table. One row per `ds × product`. 6 models × 5 quantiles = 30 model columns. Total-level (267 rows) + market-level actuals (1,381 rows). | 2026-09-18 |
| **LONG** | `arr_forecast_long` | 8,010 | Unpivoted from wide. One row per `ds × product × model × quantile`. Best for Power BI slicers. | 2026-09-18 |

All tables live in: **`datagroup_mdl.mdl_sales_analytics`**

---

## 2. Canonical Table Schemas

### 2a. `forecast_app_snapshot` (PRIMARY for app UI)

```
ds              TIMESTAMP   -- Week start (Monday)
product         STRING      -- 'UCC', 'ITSG', 'Total'
sales_market    STRING      -- 'Total', 'NA', 'EMEA', 'APAC', 'LATAM', 'Unknown'
forecast_type   STRING      -- 'actuals', 'forecast', 'boq_forward'
forecast_view   STRING      -- 'adaptive' (single value)
run_date        DATE        -- Pipeline run date (single value per snapshot)
Actuals         DOUBLE      -- Closed-week actual ARR (NULL for future weeks)
Most_Likely     DOUBLE      -- Blended P50 (actual where closed, Ensemble P50 where forecast)
Worst_Case      DOUBLE      -- P30 (tighter executive range)
Best_Case       DOUBLE      -- P70 (tighter executive range)
p10             DOUBLE      -- Full fan chart quantiles
p20             DOUBLE
p30             DOUBLE
p40             DOUBLE
p50             DOUBLE
p60             DOUBLE
p70             DOUBLE
p80             DOUBLE
p90             DOUBLE
blended_p50     DOUBLE      -- Same as Most_Likely
source          STRING      -- 'v5_current', 'hindcast', 'backtest_cv', 'boq_forward', 'total_rollup'
bands_method    STRING      -- 'calibrated_wape', 'calibrated_interp', 'calibrated_boq', 'real'
arr_ets         DOUBLE      -- Individual model point forecasts
arr_prophet     DOUBLE
arr_lightgbm    DOUBLE
arr_mstl_v2     DOUBLE
arr_dhr_arima   DOUBLE
mape_ets        DOUBLE      -- Per-model MAPE
mape_prophet    DOUBLE
mape_lightgbm   DOUBLE
mape_mstl_v2    DOUBLE
mape_dhr_arima  DOUBLE
```

**Key rules**:
- Contains ONLY the latest run. No `WHERE run_date = (SELECT MAX(...))` needed.
- `_latest_run()` should return `"TRUE"` (no-op filter).
- Actuals are NULL for future weeks. `forecast_type = 'actuals'` for closed weeks.
- `Worst_Case = p30`, `Best_Case = p70` (executive P30/P70 range, NOT p10/p90).

### 2b. `forecast_pure_predictions` (STATIC — for PowerBI wide + audit)

```
ds              DATE
product         STRING      -- 'UCC', 'ITSG', 'Total'
model           STRING      -- 6 models: Adaptive_Ensemble, Prophet_trend, MSTL_v2, ETS, DHR_ARIMA, Global_LGB_Q50_UCC/ITSG
actual          DOUBLE
blended_p50     DOUBLE
p10-p90         DOUBLE      -- All 9 quantiles (p10, p20, p30, p40, p50, p60, p70, p80, p90)
source          STRING      -- 'v5_current', 'hindcast', 'backtest_cv', 'boq_forward', 'total_rollup'
bands_method    STRING
run_date        DATE
```

### 2c. `arr_forecast_powerbi_wide` (WIDE — for monthly/quarterly summaries)

```
ds              DATE
product         STRING      -- 'UCC', 'ITSG', 'Total'
sales_market    STRING      -- 'Total' (for total rows) or market name (for market actuals)
grain_level     STRING      -- 'total' or 'market'
forecast_type   STRING      -- 'actuals' or 'forecast'
year, quarter, month, ISOWeek  INT
RelWeekNumber   INT
WeekLabel       STRING
Product_group   STRING

-- 6 models × 5 quantiles = 30 model columns:
Adaptive_Ensemble_P10, _P30, _P50, _P70, _P90  DOUBLE
DHR_ARIMA_P10, _P30, _P50, _P70, _P90          DOUBLE
ETS_P10, _P30, _P50, _P70, _P90                DOUBLE
Global_LGB_Q50_P10, _P30, _P50, _P70, _P90     DOUBLE
MSTL_v2_P10, _P30, _P50, _P70, _P90            DOUBLE
Prophet_P10, _P30, _P50, _P70, _P90            DOUBLE

actuals         DOUBLE      -- Closed-week actual (NULL for forecast weeks)
mc_actuals      DOUBLE      -- Marketing actuals (market-level only, NULL at total)
miradore_plan   DOUBLE
most_likely     DOUBLE      -- blended_p50 (actual where closed, Ensemble P50 where forecast)
worst_case      DOUBLE      -- Adaptive_Ensemble_P30
best_case       DOUBLE      -- Adaptive_Ensemble_P70
ARR_YTD         DOUBLE      -- Running sum of actuals (NULL past last actual)
model_fill_source STRING    -- 'backtest_cv', 'hindcast', 'v5_current', 'total_rollup', 'historical'
run_date        TIMESTAMP
published_at_utc TIMESTAMP
```

**Key rules for wide table**:
- Total-level rows (grain_level='total'): have all 30 model columns + scenarios
- Market-level rows (grain_level='market'): actuals only, model columns are NULL
- Quantiles are P10/P30/P50/P70/P90 (NOT P05/P25/P75/P95)
- `most_likely = blended_p50`, `worst_case = Ensemble_P30`, `best_case = Ensemble_P70`

---

## 3. Frontend Tab → API Endpoint → Backend Table Mapping

### Tab: **Overview / Plan Tracking**

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2Weekly` | `get_weekly` | `forecast_app_snapshot` + `arr_forecast_powerbi_wide` | `forecast_app_snapshot` | Primary weekly series. Wide table used only as fallback for `most_likely_all_periods`. Read `Most_Likely`, `Worst_Case`, `Best_Case`, `p10`-`p90` directly — NO band math. |
| `getForecastV2YTD` | `get_ytd` | `forecast_app_snapshot` | `forecast_app_snapshot` | Running cumulative sum of `Actuals` column. |
| `getForecastV2Models` | `get_models` | `forecast_app_snapshot` | `forecast_app_snapshot` | List of available models/products. |
| `getForecastV2Freshness` | `get_freshness` | `forecast_app_snapshot` | `forecast_app_snapshot` | `MAX(run_date)` from snapshot. |
| `getForecastV2ConfidenceBands` | `get_confidence_bands` | `forecast_app_snapshot` | `forecast_app_snapshot` | Full fan: p10, p20, p30, p40, p50, p60, p70, p80, p90. |
| `getForecastV2RunDelta` | `get_run_delta` | `forecast_app_snapshot` | `forecast_app_snapshot` | Week-over-week delta. |
| `getForecastV2DriverBridge` | `get_driver_bridge` | `forecast_app_snapshot` | `forecast_app_snapshot` | Waterfall chart data. |

### Tab: **Multi-Year**

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2Historical` | `get_historical` | `forecast_app_snapshot` | `forecast_app_snapshot` | Multi-year time series with year-over-year overlay. |

### Tab: **By Product**

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2ByProduct` | `get_by_product` | `forecast_leaderboard_v2compat` | `forecast_leaderboard_v2compat` | Per-product MAPE comparison. |

### Tab: **Monthly**

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2Monthly` | `get_monthly` | `arr_forecast_powerbi_wide` + `forecast_app_snapshot` | `arr_forecast_powerbi_wide` | Monthly aggregation. Use wide table for `grain_level='total'` rows. Group by `DATE_FORMAT(ds, 'yyyy-MM')`. Scenarios: `most_likely`, `worst_case`, `best_case` columns directly. |

### Tab: **Accuracy** (including Model Lab + Backtest)

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2Leaderboard` | `get_leaderboard` | `forecast_leaderboard_v2compat` + `forecast_quarterly_accuracy` + `forecast_app_snapshot` | Same — all 3 are correct | Leaderboard uses compat view. Quarterly uses dedicated table. |
| `getForecastV2Backtest` | `get_backtest` | `ucc_forecast_vintages` / `itsg_forecast_vintages` + `ucc_forecast_cbe` / `itsg_forecast_cbe` | Same — correct | Retained-vintage backtests. Product-specific tables. |
| `getForecastV2ModelLab` | `get_model_lab` | `arr_forecast_app_latest` + `ucc_forecast_v5` + `itsg_forecast_v5` | **CHANGE TO** `forecast_app_snapshot` | PROBLEM: reads `arr_forecast_app_latest` (old table, 1548 rows) and raw V5 tables. Should read `forecast_app_snapshot` which has all models unified. See fix instructions below. |
| `getForecastV2AccuracyByQuarter` | `get_accuracy_by_quarter` | `ucc_forecast_vintages` + `ucc_forecast_cbe` | Same — correct | Quarterly accuracy matrix. |
| `getForecastV2Confidence` | `get_confidence` | `forecast_app_snapshot` + `forecast_leaderboard_v2compat` | Same — correct | Confidence score computation. |

### Tab: **Exec Mode**

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2Confidence` | `get_confidence` | `forecast_app_snapshot` | `forecast_app_snapshot` | Confidence score. |
| `getForecastV2DriverBridge` | `get_driver_bridge` | `forecast_app_snapshot` | `forecast_app_snapshot` | Waterfall bridge. |
| `getForecastV2RiskRadar` | `get_risk_radar` | `forecast_app_snapshot` | `forecast_app_snapshot` | Risk assessment. |
| `getForecastV2MeetingMode` | `get_meeting_mode` | (demo/computed) | N/A | Computed from other data. |
| `getForecastV2ScenarioGrid` | `get_scenario_grid` | `forecast_scenario_grid` | `forecast_scenario_grid` | Pre-computed scenario grid (6 rows). |
| `getForecastV2Sensitivity` | `get_sensitivity_coefficients` | `forecast_sensitivity` | `forecast_sensitivity` | Sensitivity coefficients (24 rows). |
| `getForecastV2ModelScenarios` | `get_model_scenarios` | `forecast_model_scenarios` | `forecast_model_scenarios` | Per-model scenarios (19 rows). |
| `getForecastV2HistoricalScenarios` | `get_historical_scenarios` | `forecast_historical_scenarios` | `forecast_historical_scenarios` | Historical scenario analysis (135 rows). |

### Tab: **AI Insights**

| API Call | Backend Endpoint | Current Table | Correct Table | Notes |
|----------|-----------------|---------------|---------------|-------|
| `getForecastV2Intelligence` | `get_intelligence` | `forecast_insights` / `forecast_insights_v2compat` + Volume JSON | Same — correct | AI-generated insights. |
| `getForecastV2GraphExplanation` | `get_graph_explanation` | `forecast_graph_explanations` | `forecast_graph_explanations` | Pre-computed chart explanations (60 rows). |

### Other Endpoints (not tab-specific)

| Endpoint | Current Table | Correct Table | Notes |
|----------|---------------|---------------|-------|
| `get_forward_outlook` | `arr_forecast_app_latest` + `ucc_forecast_v5` + `itsg_forecast_v5` | **CHANGE TO** `forecast_app_snapshot` | Same issue as model_lab — reads stale table. |
| `get_monthly_combined` | `arr_forecast_app_latest` + `ucc_forecast_v5` + `itsg_forecast_v5` | **CHANGE TO** `arr_forecast_powerbi_wide` | Monthly combined should use wide table. |
| `get_weekly_all_models` | (helper/demo) | `forecast_app_snapshot` | Needs implementation — read `arr_*` model columns from snapshot. |
| `get_run_history` | `forecast_app_snapshot` | `forecast_app_snapshot` | Correct. |

---

## 4. REQUIRED FIXES — Endpoints Reading Wrong Tables

### Fix 1: `get_model_lab` — reads `arr_forecast_app_latest` (STALE)

**Problem**: Reads `arr_forecast_app_latest` (old table from pre-V2 pipeline) and raw V5 tables (`ucc_forecast_v5`, `itsg_forecast_v5`). These have different schemas and are not unified.

**Fix**: Read from `forecast_app_snapshot` instead. This table has per-model columns (`arr_ets`, `arr_prophet`, `arr_lightgbm`, `arr_mstl_v2`, `arr_dhr_arima`) and MAPE columns (`mape_ets`, etc.) already unified.

```python
# BEFORE (wrong):
APP_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_app_latest`"
# ... complex UNION of UCC_V5_TABLE + ITSG_V5_TABLE

# AFTER (correct):
# Just use FC_TABLE (forecast_app_snapshot) which already has all models unified.
# Query: SELECT ds, product, arr_ets, arr_prophet, arr_lightgbm, arr_mstl_v2, arr_dhr_arima,
#        Actuals, Most_Likely, Worst_Case, Best_Case, p10-p90
# FROM forecast_app_snapshot WHERE product = ? AND sales_market = 'Total'
```

### Fix 2: `get_forward_outlook` — same issue as model_lab

**Fix**: Replace `APP_TABLE` / `UCC_V5_TABLE` / `ITSG_V5_TABLE` references with `FC_TABLE` (`forecast_app_snapshot`).

### Fix 3: `get_monthly_combined` — reads raw V5 tables

**Fix**: Read from `arr_forecast_powerbi_wide` for monthly data. It already has per-model P50 columns and proper calendar fields.

```sql
SELECT product, DATE_FORMAT(ds, 'yyyy-MM') AS month, quarter,
       SUM(actuals) AS actuals,
       SUM(Adaptive_Ensemble_P50) AS ensemble_p50,
       SUM(most_likely) AS most_likely,
       SUM(worst_case) AS worst_case,
       SUM(best_case) AS best_case
FROM forecast_app_snapshot  -- or arr_forecast_powerbi_wide for model detail
WHERE product = ? AND sales_market = 'Total'
GROUP BY product, DATE_FORMAT(ds, 'yyyy-MM'), quarter
ORDER BY month
```

### Fix 4: `MODEL_SOURCES` dict — Prophet still reads `forecast_all_models`

**Problem**: The `prophet` entry in `MODEL_SOURCES` points to `PROPHET_TABLE` (`forecast_all_models`) with different column names and `is_current` filter logic. All other models correctly read `FC_TABLE`.

**Fix**: Point Prophet to `FC_TABLE` too:
```python
"prophet": {
    "display_name": "Prophet",
    "table": FC_TABLE,            # was PROPHET_TABLE
    "most_likely_col": "arr_prophet",  # was "forecast_p50"
    "lower_col": "p30",           # was "forecast_p05"
    "upper_col": "p70",           # was "forecast_p95"
    "mape_field": "Prophet",
    "has_forecast_type": True,
    # REMOVE: "model_filter", "no_run_date", "actuals_col"
},
```

---

## 5. Table Variable Consolidation

After fixes, the backend should use these table variables:

```python
# ━━━ PRIMARY TABLES (keep) ━━━
FC_TABLE          = forecast_app_snapshot          # Primary for ALL app UI reads
POWERBI_WIDE_TABLE = arr_forecast_powerbi_wide     # Monthly summaries, PowerBI
LB_TABLE          = forecast_leaderboard_v2compat  # Leaderboard/accuracy
QUARTERLY_ACCURACY_TABLE = forecast_quarterly_accuracy  # Quarterly matrix
INSIGHTS_TABLE    = forecast_insights              # AI insights
GRAPH_EXPLAIN_TABLE = forecast_graph_explanations  # Graph explanations

# ━━━ BACKTEST TABLES (keep — product-specific) ━━━
UCC_VINTAGES_TABLE = ucc_forecast_vintages         # UCC vintage history
ITSG_VINTAGES_TABLE = itsg_forecast_vintages       # ITSG vintage history (ADD THIS)
UCC_CBE_TABLE     = ucc_forecast_cbe               # UCC actuals for backtest
ITSG_CBE_TABLE    = itsg_forecast_cbe              # ITSG actuals for backtest (ADD THIS)

# ━━━ SCENARIO TABLES (keep) ━━━
SCENARIO_GRID_TABLE = forecast_scenario_grid
SENSITIVITY_TABLE   = forecast_sensitivity
MODEL_SCENARIOS_TABLE = forecast_model_scenarios
HIST_SCENARIOS_TABLE  = forecast_historical_scenarios

# ━━━ REMOVE THESE (stale/redundant) ━━━
# APP_TABLE         = arr_forecast_app_latest       # REMOVE — replaced by FC_TABLE
# UCC_V5_TABLE      = ucc_forecast_v5              # REMOVE — raw V5 output, not for app
# ITSG_V5_TABLE     = itsg_forecast_v5             # REMOVE — raw V5 output, not for app
# PROPHET_TABLE     = forecast_all_models           # REMOVE — Prophet now in FC_TABLE
# FORECAST_PROPHET_TABLE = forecast_prophet          # REMOVE — V1 legacy
# ACCURACY_HISTORY_TABLE = ucc_forecast_accuracy_history  # KEEP only for specific accuracy views
```

---

## 6. Column Name Mapping (for query rewrites)

### forecast_app_snapshot columns to use:

| What you need | Column name | Notes |
|--------------|-------------|-------|
| Actual ARR | `Actuals` | Capital A. NULL for future weeks. |
| Most likely forecast | `Most_Likely` | Blended: actual where closed, Ensemble P50 where forecast |
| Worst case (exec) | `Worst_Case` | = p30 |
| Best case (exec) | `Best_Case` | = p70 |
| Full fan quantiles | `p10`, `p20`, `p30`, `p40`, `p50`, `p60`, `p70`, `p80`, `p90` | All 9 available |
| ETS point forecast | `arr_ets` | |
| Prophet point forecast | `arr_prophet` | |
| LightGBM point forecast | `arr_lightgbm` | |
| MSTL point forecast | `arr_mstl_v2` | |
| DHR-ARIMA point forecast | `arr_dhr_arima` | |
| ETS MAPE | `mape_ets` | |
| Prophet MAPE | `mape_prophet` | |
| LightGBM MAPE | `mape_lightgbm` | |
| MSTL MAPE | `mape_mstl_v2` | |
| DHR-ARIMA MAPE | `mape_dhr_arima` | |
| Forecast type | `forecast_type` | 'actuals', 'forecast', 'boq_forward' |
| Data source | `source` | 'v5_current', 'hindcast', 'backtest_cv', 'boq_forward' |
| Run date | `run_date` | Single value — no MAX subquery needed |

### arr_forecast_powerbi_wide model columns:

| Model | P10 | P30 | P50 | P70 | P90 |
|-------|-----|-----|-----|-----|-----|
| Adaptive_Ensemble | `Adaptive_Ensemble_P10` | `_P30` | `_P50` | `_P70` | `_P90` |
| DHR_ARIMA | `DHR_ARIMA_P10` | `_P30` | `_P50` | `_P70` | `_P90` |
| ETS | `ETS_P10` | `_P30` | `_P50` | `_P70` | `_P90` |
| Global_LGB_Q50 | `Global_LGB_Q50_P10` | `_P30` | `_P50` | `_P70` | `_P90` |
| MSTL_v2 | `MSTL_v2_P10` | `_P30` | `_P50` | `_P70` | `_P90` |
| Prophet | `Prophet_P10` | `_P30` | `_P50` | `_P70` | `_P90` |

---

## 7. Critical Rules for Backend Queries

1. **No `MAX(run_date)` subqueries** — `forecast_app_snapshot` contains only the latest run.
2. **No band math** — `Worst_Case` and `Best_Case` are pre-computed. Never multiply p50 by 0.90/1.10.
3. **No `sqrt` reconstruction** — All quantiles are exact pass-throughs from calibrated models.
4. **Product filter defaults to 'Total'** — When no product selected, filter to `product = 'Total'`, not `SUM(all products)` which double-counts.
5. **Market filter defaults to 'Total'** — Same logic. `sales_market = 'Total'` is a pre-computed rollup.
6. **Quantiles are P10/P30/P50/P70/P90** — NOT P05/P25/P75/P95 (old schema).
7. **6 models, not 7** — Adaptive_Ensemble, DHR_ARIMA, ETS, Global_LGB_Q50, MSTL_v2, Prophet. Chronos was removed.
8. **ITSG backtest** — `itsg_forecast_vintages` + `itsg_forecast_cbe` exist (100K + 540 rows). Backend currently only has UCC backtest wired — add ITSG support.

---

## 8. File Locations

```
backend/
  routes/
    forecast_v2_impl.py          # ← MAIN FILE TO EDIT (all endpoint implementations)
    forecast_backtest.py         # Backtest logic (vintages + CBE tables)
    forecast.py                  # DEPRECATED V1 — only /intelligence still used
    forecast_v2/
      series.py                  # Routes: weekly, monthly, ytd, by-product, historical, etc.
      accuracy.py                # Routes: leaderboard, backtest, model-lab, confidence
      intelligence.py            # Routes: intelligence, driver-bridge, risk-radar, meeting-mode
      governance.py              # Routes: governance log, freshness, models, run-delta
```

---

## 9. VS Code Prompt

Copy everything above, then use this prompt:

```
Using the table routing guide above, refactor backend/routes/forecast_v2_impl.py to:

1. Remove these stale table variables: APP_TABLE, UCC_V5_TABLE, ITSG_V5_TABLE, PROPHET_TABLE, FORECAST_PROPHET_TABLE

2. Update MODEL_SOURCES["prophet"] to read from FC_TABLE (forecast_app_snapshot) instead of PROPHET_TABLE (forecast_all_models). Use column arr_prophet for most_likely_col, p30 for lower_col, p70 for upper_col. Remove the model_filter, no_run_date, and actuals_col overrides.

3. Rewrite get_model_lab to read from FC_TABLE instead of APP_TABLE/UCC_V5_TABLE/ITSG_V5_TABLE. The snapshot table has arr_ets, arr_prophet, arr_lightgbm, arr_mstl_v2, arr_dhr_arima columns for per-model series.

4. Rewrite get_forward_outlook to read from FC_TABLE instead of APP_TABLE/UCC_V5_TABLE/ITSG_V5_TABLE.

5. Rewrite get_monthly_combined to read from FC_TABLE (or arr_forecast_powerbi_wide for model-level detail) instead of APP_TABLE/V5 tables.

6. Add ITSG_VINTAGES_TABLE and ITSG_CBE_TABLE for ITSG backtest support.

7. **CRITICAL — forecast_type value mismatch**: The snapshot table uses `'actuals'`, `'forecast'`, `'boq_forward'`. The backend code passes V1 values `'rolling'`, `'roy'`, `'forward_1yr'` which will match ZERO rows. Fix the `VALID_FORECAST_TYPES` set and all forecast_type filter logic:
   - V1 `'rolling'` + `'roy'` + `'forward_1yr'` → V2 `'forecast'` (all non-actual weeks)
   - V1 `'actuals'` → V2 `'actuals'` (same)
   - New: `'boq_forward'` = BOQ extension weeks (treat as forecast)
   - Update `VALID_FORECAST_TYPES = {'actuals', 'forecast', 'boq_forward'}`
   - The `_monthly_forecast_type_condition()` and `_normalized_forecast_sql()` functions need rewriting to use V2 values.

8. Preserve all existing endpoint signatures, error handling, caching, and demo fallback logic.
```
