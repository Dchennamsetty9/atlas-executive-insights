-- ============================================================================
-- verify_dashboard_numbers.sql
-- Paste-ready Databricks SQL: reproduces every number the Forecasting panel
-- shows, using the EXACT math of each backend endpoint (forecast_v2_impl.py).
-- Run top to bottom in the SQL editor (warehouse c24ee33594e13e93).
--
-- Deployed app config (app.yaml):
--   results     = forecast_results_v2compat   (view over forecast_results)
--   insights    = forecast_insights_v2compat  (view over forecast_insights)
--   leaderboard = arr_forecast_v2_leaderboard (LEGACY - env var not set!)
--   accuracy matrix reads arr_forecast_v2 directly (append-only vintages)
--
-- To check another slice, change the literals marked  <<< EDIT
-- ============================================================================


-- ────────────────────────────────────────────────────────────────────────────
-- 0. FRESHNESS — run this FIRST. If forecast_results' max run_date is older
--    than arr_forecast_v2's, every unified number on the dashboard is stale
--    and nothing below will reconcile. (Root cause 2026-08-03: the daily 7am
--    unify job still points at an old branch → repoint to main.)
-- ────────────────────────────────────────────────────────────────────────────
SELECT 'arr_forecast_v2'    AS tbl, MAX(run_date) AS latest_run, MAX(CASE WHEN forecast_type='actuals' THEN CAST(ds AS DATE) END) AS last_actual_week FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
UNION ALL
SELECT 'forecast_results',        MAX(run_date), MAX(CASE WHEN forecast_type='actuals' THEN CAST(ds AS DATE) END) FROM datagroup_mdl.mdl_sales_analytics.forecast_results
UNION ALL
SELECT 'forecast_insights',       MAX(run_date), NULL FROM datagroup_mdl.mdl_sales_analytics.forecast_insights
UNION ALL
SELECT 'graph_explanations',      MAX(run_date), NULL FROM datagroup_mdl.mdl_sales_analytics.forecast_graph_explanations
UNION ALL
SELECT 'ucc_forecast_v5',         MAX(CAST(run_date_utc AS DATE)), NULL FROM datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5
UNION ALL
SELECT 'itsg_forecast_v5',        MAX(CAST(run_date_utc AS DATE)), NULL FROM datagroup_mdl.mdl_sales_analytics.itsg_forecast_v5;


-- ────────────────────────────────────────────────────────────────────────────
-- 1. KPI CARDS (Most Likely / Risk Floor / Stretch / Actuals-in-period)
--    Mirrors get_weekly() kpi_sql + _summary_kpis():
--      landing  = Σ Most_Likely over actuals rows in period
--                 + forecast rows (rolling|roy) strictly AFTER last closed
--                   actual week   ← canonical splice, no double-count
--      band     = quadrature: √Σ(Best−ML)² up, √Σ(ML−Worst)² down
--    Dashboard: Overview KPI row. Compare per product / period selection.
-- ────────────────────────────────────────────────────────────────────────────
WITH params AS (
  SELECT 'Total' AS product, 'Total' AS market, 2026 AS yr, 3 AS qtr   -- <<< EDIT (qtr NULL = full year)
),
v AS (
  SELECT r.* FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat r
  JOIN params p
    ON r.product = p.product
   AND CASE WHEN UPPER(TRIM(CAST(r.sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(r.sales_market AS STRING)) END = p.market
  WHERE r.run_date = (SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat)
    AND YEAR(r.ds) = p.yr
    AND (p.qtr IS NULL OR QUARTER(r.ds) = p.qtr)
),
last_act AS (
  SELECT MAX(CAST(ds AS DATE)) AS d FROM v
  WHERE forecast_type='actuals' AND COALESCE(CAST(Actuals AS DOUBLE),0) > 0
),
kpi_rows AS (
  SELECT COALESCE(CAST(Most_Likely AS DOUBLE),0) AS ml,
         COALESCE(CAST(Worst_Case  AS DOUBLE),0) AS wc,
         COALESCE(CAST(Best_Case   AS DOUBLE),0) AS bc,
         COALESCE(CAST(Actuals     AS DOUBLE),0) AS act,
         forecast_type
  FROM v, last_act
  WHERE forecast_type = 'actuals'
     OR (forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > COALESCE(last_act.d, DATE'1900-01-01'))
)
SELECT
  ROUND(SUM(CASE WHEN ml > 0 OR forecast_type IN ('rolling','roy') THEN ml END), 0)                                    AS most_likely_landing,
  ROUND(SUM(CASE WHEN ml > 0 OR forecast_type IN ('rolling','roy') THEN ml END)
        - SQRT(SUM(CASE WHEN ml > 0 OR forecast_type IN ('rolling','roy') THEN POWER(GREATEST(ml - wc, 0), 2) END)), 0) AS risk_floor,
  ROUND(SUM(CASE WHEN ml > 0 OR forecast_type IN ('rolling','roy') THEN ml END)
        + SQRT(SUM(CASE WHEN ml > 0 OR forecast_type IN ('rolling','roy') THEN POWER(GREATEST(bc - ml, 0), 2) END)), 0) AS stretch_case,
  ROUND(SUM(CASE WHEN forecast_type='actuals' AND act > 0 THEN act END), 0)                                             AS actuals_in_period
FROM kpi_rows;


-- ────────────────────────────────────────────────────────────────────────────
-- 2. QUARTERLY OUTLOOK BARS (Overview bottom-left, stacked orange/blue)
--    Per quarter: realized actuals + spliced forecast = landing.
--    Bands per quarter via the same quadrature rule (QuarterlyBarChart JS).
-- ────────────────────────────────────────────────────────────────────────────
WITH params AS (
  SELECT 'Total' AS product, 'Total' AS market, 2026 AS yr                 -- <<< EDIT
),
v AS (
  SELECT r.* FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat r
  JOIN params p
    ON r.product = p.product
   AND CASE WHEN UPPER(TRIM(CAST(r.sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(r.sales_market AS STRING)) END = p.market
  WHERE r.run_date = (SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat)
    AND YEAR(r.ds) = p.yr
),
last_act AS (
  SELECT MAX(CAST(ds AS DATE)) AS d FROM v
  WHERE forecast_type='actuals' AND COALESCE(CAST(Actuals AS DOUBLE),0) > 0
)
SELECT
  QUARTER(ds) AS qtr,
  ROUND(SUM(CASE WHEN forecast_type='actuals' THEN COALESCE(CAST(Actuals AS DOUBLE),0) END), 0)   AS realized_actuals_orange,
  ROUND(SUM(CASE WHEN forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > COALESCE((SELECT d FROM last_act), DATE'1900-01-01')
                 THEN COALESCE(CAST(Most_Likely AS DOUBLE),0) END), 0)                             AS remaining_forecast_blue,
  ROUND(SUM(CASE WHEN forecast_type='actuals' THEN COALESCE(CAST(Actuals AS DOUBLE),0)
                 WHEN forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > COALESCE((SELECT d FROM last_act), DATE'1900-01-01')
                 THEN COALESCE(CAST(Most_Likely AS DOUBLE),0) END), 0)                             AS landing_label,
  ROUND(SQRT(SUM(CASE WHEN forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > COALESCE((SELECT d FROM last_act), DATE'1900-01-01')
                 THEN POWER(GREATEST(COALESCE(CAST(Best_Case AS DOUBLE),0) - COALESCE(CAST(Most_Likely AS DOUBLE),0), 0), 2) ELSE 0 END)), 0) AS band_up,
  ROUND(SQRT(SUM(CASE WHEN forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > COALESCE((SELECT d FROM last_act), DATE'1900-01-01')
                 THEN POWER(GREATEST(COALESCE(CAST(Most_Likely AS DOUBLE),0) - COALESCE(CAST(Worst_Case AS DOUBLE),0), 0), 2) ELSE 0 END)), 0) AS band_down
FROM v
GROUP BY QUARTER(ds)
ORDER BY qtr;
-- NOTE: Q4 must include roy rows. If remaining_forecast_blue for Q4 is tiny,
-- the roy horizon in forecast_results is truncated (13-wk rolling only) —
-- the frontend fix (yearRows = rolling+roy) only helps if roy rows exist.


-- ────────────────────────────────────────────────────────────────────────────
-- 3. MONTHLY TOTALS (Running Totals / monthly chart)
--    Same splice rule, grouped by month.
-- ────────────────────────────────────────────────────────────────────────────
WITH params AS (
  SELECT 'Total' AS product, 'Total' AS market, 2026 AS yr                 -- <<< EDIT
),
v AS (
  SELECT r.* FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat r
  JOIN params p
    ON r.product = p.product
   AND CASE WHEN UPPER(TRIM(CAST(r.sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(r.sales_market AS STRING)) END = p.market
  WHERE r.run_date = (SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat)
    AND YEAR(r.ds) = p.yr
),
last_act AS (
  SELECT MAX(CAST(ds AS DATE)) AS d FROM v
  WHERE forecast_type='actuals' AND COALESCE(CAST(Actuals AS DOUBLE),0) > 0
)
SELECT DATE_TRUNC('MONTH', ds) AS month,
  ROUND(SUM(CASE WHEN forecast_type='actuals' THEN COALESCE(CAST(Actuals AS DOUBLE),0) END), 0) AS actuals,
  ROUND(SUM(CASE WHEN forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > COALESCE((SELECT d FROM last_act), DATE'1900-01-01')
                 THEN COALESCE(CAST(Most_Likely AS DOUBLE),0) END), 0)                          AS forecast
FROM v GROUP BY DATE_TRUNC('MONTH', ds) ORDER BY month;


-- ────────────────────────────────────────────────────────────────────────────
-- 4. BY-PRODUCT LANDING (By Product tab)
-- ────────────────────────────────────────────────────────────────────────────
WITH v AS (
  SELECT r.* FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat r
  WHERE r.run_date = (SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat)
    AND CASE WHEN UPPER(TRIM(CAST(r.sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(r.sales_market AS STRING)) END = 'Total'
    AND YEAR(r.ds) = 2026                                                  -- <<< EDIT
),
last_act AS (
  SELECT product, MAX(CAST(ds AS DATE)) AS d FROM v
  WHERE forecast_type='actuals' AND COALESCE(CAST(Actuals AS DOUBLE),0) > 0
  GROUP BY product
)
SELECT v.product,
  ROUND(SUM(CASE WHEN v.forecast_type='actuals' THEN COALESCE(CAST(v.Actuals AS DOUBLE),0)
                 WHEN v.forecast_type IN ('rolling','roy') AND CAST(v.ds AS DATE) > COALESCE(la.d, DATE'1900-01-01')
                 THEN COALESCE(CAST(v.Most_Likely AS DOUBLE),0) END), 0) AS landing
FROM v LEFT JOIN last_act la ON v.product = la.product
GROUP BY v.product ORDER BY landing DESC;
-- Sanity: UCC + ITSG must equal Total (unify notebook builds Total = UCC+ITSG).


-- ────────────────────────────────────────────────────────────────────────────
-- 5. ACCURACY TAB — QUARTERLY MAPE MATRIX
--    EXACT copy of get_accuracy_by_quarter() SQL (product_line = Total):
--    earliest vintage per week from append-only arr_forecast_v2, sMAPE vs
--    closed actuals, current quarter included as (QTD).
-- ────────────────────────────────────────────────────────────────────────────
WITH actuals AS (
  SELECT ds, product, MAX(CAST(Actuals AS DOUBLE)) AS actual
  FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
  WHERE forecast_type = 'actuals'
    AND COALESCE(CAST(Actuals AS DOUBLE), 0) > 0
    AND product = 'Total'                                                  -- <<< EDIT
    AND CASE WHEN UPPER(TRIM(CAST(sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(sales_market AS STRING)) END = 'Total'
  GROUP BY ds, product
),
fc AS (
  SELECT f.*, ROW_NUMBER() OVER (PARTITION BY f.product, f.ds ORDER BY CAST(f.run_date AS DATE) ASC) AS rn
  FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2 f
  WHERE f.forecast_type IN ('rolling','roy')
    AND CAST(f.ds AS DATE) < CURRENT_DATE()
    AND COALESCE(CAST(f.Most_Likely AS DOUBLE), 0) > 0
    AND f.product = 'Total'                                                -- <<< EDIT
    AND CASE WHEN UPPER(TRIM(CAST(f.sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(f.sales_market AS STRING)) END = 'Total'
)
SELECT YEAR(f.ds) AS yr, QUARTER(f.ds) AS qtr, COUNT(*) AS n_weeks,
  ROUND(AVG(CASE WHEN COALESCE(CAST(f.Most_Likely AS DOUBLE),0)>0 AND COALESCE(CAST(a.actual AS DOUBLE),0)>0 THEN ABS(CAST(f.Most_Likely AS DOUBLE)-a.actual)/((ABS(CAST(f.Most_Likely AS DOUBLE))+ABS(a.actual))/2.0)*100 END),1) AS ens_mape,
  ROUND(AVG(CASE WHEN COALESCE(CAST(f.arr_ets AS DOUBLE),0)>0 AND COALESCE(CAST(a.actual AS DOUBLE),0)>0 THEN ABS(CAST(f.arr_ets AS DOUBLE)-a.actual)/((ABS(CAST(f.arr_ets AS DOUBLE))+ABS(a.actual))/2.0)*100 END),1) AS ets_mape,
  ROUND(AVG(CASE WHEN COALESCE(CAST(f.arr_prophet AS DOUBLE),0)>0 AND COALESCE(CAST(a.actual AS DOUBLE),0)>0 THEN ABS(CAST(f.arr_prophet AS DOUBLE)-a.actual)/((ABS(CAST(f.arr_prophet AS DOUBLE))+ABS(a.actual))/2.0)*100 END),1) AS prophet_mape,
  ROUND(AVG(CASE WHEN COALESCE(CAST(f.arr_lightgbm AS DOUBLE),0)>0 AND COALESCE(CAST(a.actual AS DOUBLE),0)>0 THEN ABS(CAST(f.arr_lightgbm AS DOUBLE)-a.actual)/((ABS(CAST(f.arr_lightgbm AS DOUBLE))+ABS(a.actual))/2.0)*100 END),1) AS lgbm_mape,
  ROUND(AVG(CASE WHEN COALESCE(CAST(f.arr_mstl_v2 AS DOUBLE),0)>0 AND COALESCE(CAST(a.actual AS DOUBLE),0)>0 THEN ABS(CAST(f.arr_mstl_v2 AS DOUBLE)-a.actual)/((ABS(CAST(f.arr_mstl_v2 AS DOUBLE))+ABS(a.actual))/2.0)*100 END),1) AS mstl_mape,
  ROUND(AVG(CASE WHEN COALESCE(CAST(f.arr_dhr_arima AS DOUBLE),0)>0 AND COALESCE(CAST(a.actual AS DOUBLE),0)>0 THEN ABS(CAST(f.arr_dhr_arima AS DOUBLE)-a.actual)/((ABS(CAST(f.arr_dhr_arima AS DOUBLE))+ABS(a.actual))/2.0)*100 END),1) AS dhr_mape
FROM fc f INNER JOIN actuals a ON f.ds = a.ds AND f.product = a.product
WHERE f.rn = 1
GROUP BY YEAR(f.ds), QUARTER(f.ds) ORDER BY yr, qtr;


-- ────────────────────────────────────────────────────────────────────────────
-- 6. LEADERBOARD (Accuracy tab table) — table the DEPLOYED app actually reads
--    (legacy: no mape_ensemble column; Ensemble row comes from holdout/
--    realized fallback in the endpoint, not from this table).
-- ────────────────────────────────────────────────────────────────────────────
SELECT * FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard
WHERE run_date = (SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard)
ORDER BY product, sales_market;
-- Unified equivalent once the 7am job is repointed to main:
-- SELECT * FROM datagroup_mdl.mdl_sales_analytics.forecast_leaderboard_v2compat;


-- ────────────────────────────────────────────────────────────────────────────
-- 7. AI INSIGHTS — latest run per product; headline numbers inside
--    insights_json must equal query #1 (same splice + quadrature math is
--    used by the unify notebook's _stats()).
-- ────────────────────────────────────────────────────────────────────────────
SELECT product, run_date, insights_json
FROM datagroup_mdl.mdl_sales_analytics.forecast_insights
WHERE run_date = (SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.forecast_insights)
ORDER BY product;

-- Graph explanations coverage: needs rows for all 10 keys incl. the two new
-- ones (quarterly_outlook, multi_model) after the notebook re-runs on main.
SELECT graph, COUNT(*) AS n_rows, MAX(run_date) AS latest
FROM datagroup_mdl.mdl_sales_analytics.forecast_graph_explanations
GROUP BY graph ORDER BY graph;


-- ────────────────────────────────────────────────────────────────────────────
-- 8. CROSS-SOURCE DRIFT — unified actuals vs source-of-truth actuals.
--    Any non-zero diff = unify job hasn't run since the source updated.
-- ────────────────────────────────────────────────────────────────────────────
WITH src AS (
  SELECT product, CAST(ds AS DATE) AS ds, MAX(CAST(Actuals AS DOUBLE)) AS actual
  FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
  WHERE forecast_type='actuals' AND run_date=(SELECT MAX(run_date) FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_v2)
    AND CASE WHEN UPPER(TRIM(CAST(sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(sales_market AS STRING)) END='Total'
  GROUP BY product, CAST(ds AS DATE)
),
uni AS (
  SELECT product, CAST(ds AS DATE) AS ds, MAX(CAST(Actuals AS DOUBLE)) AS actual
  FROM datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat
  WHERE forecast_type='actuals'
    AND CASE WHEN UPPER(TRIM(CAST(sales_market AS STRING)))='UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST(sales_market AS STRING)) END='Total'
  GROUP BY product, CAST(ds AS DATE)
)
SELECT COALESCE(s.product, u.product) AS product,
       COUNT(*) AS weeks_compared,
       SUM(CASE WHEN u.ds IS NULL THEN 1 ELSE 0 END)                       AS weeks_missing_in_unified,
       ROUND(SUM(ABS(COALESCE(s.actual,0) - COALESCE(u.actual,0))), 2)     AS total_abs_diff
FROM src s FULL OUTER JOIN uni u ON s.product = u.product AND s.ds = u.ds
WHERE YEAR(COALESCE(s.ds, u.ds)) >= 2025
GROUP BY COALESCE(s.product, u.product) ORDER BY product;


-- ────────────────────────────────────────────────────────────────────────────
-- 9. INDEPENDENT REFERENCE (Metis, queried 2026-08-04 via Genie —
--    federated.sales.metis_won_opps_fact, close_date through 2026-08-03).
--    Different lineage than the pipeline (cds_sfdc_opp_products_latest),
--    so expect DIRECTIONAL agreement, not to-the-dollar:
--      UCaaS+Core Collab (≈ UCC):  Q1'26 $13.11M   Q2'26 $13.81M   Q3'26 QTD $5.01M
--      ITSG:                       Q1'26 $3.46M    Q2'26 $3.43M    Q3'26 QTD $1.02M
--    Dashboard UCC quarterly actuals should land within a few % of these.
-- ────────────────────────────────────────────────────────────────────────────
