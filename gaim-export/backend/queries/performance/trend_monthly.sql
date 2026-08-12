-- queries/performance/trend_monthly.sql
-- ============================================================
-- Monthly Trend — All Core KPIs Aggregated by Month
-- Returns one row per calendar month within the selected quarter range.
-- Used by "monthly view" toggles in KPI Trends charts.
-- ============================================================
--
-- Structural placeholders:
--   {period_start}   YYYY-MM-DD  earliest date to include (e.g. start of 6 quarters ago)
--   {period_end}     YYYY-MM-DD  latest date to include   (usually today)
--   {plan_version}   Plan | FY4 | FY7
--   {won_filter}     AND-prefixed fragment for metis_won_opps_fact
--   {opened_filter}  AND-prefixed fragment for metis_opened_opps_fact
--   {targets_filter} AND-prefixed fragment for metis_targets_summary
-- ============================================================

WITH

latest_date AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),

won_by_month AS (
    SELECT
        DATE_TRUNC('month', w.close_date)              AS month_start,
        COUNT(DISTINCT w.salesforce_opportunity_id)    AS won_opps,
        COALESCE(SUM(w.amount_towards_plan), 0)        AS won_amount
    FROM federated.sales.metis_won_opps_fact  w
    CROSS JOIN latest_date  ld
    WHERE w.data_date  = ld.max_date
      AND w.close_date BETWEEN DATE('{period_start}') AND DATE('{period_end}')
      {won_filter}
    GROUP BY 1
),

opened_by_month AS (
    SELECT
        DATE_TRUNC('month', o.pipeline_entered_date)   AS month_start,
        COUNT(DISTINCT o.salesforce_opportunity_id)    AS opened_opps,
        COALESCE(SUM(o.amount_towards_plan), 0)        AS opened_amount
    FROM federated.sales.metis_opened_opps_fact  o
    CROSS JOIN latest_date  ld
    WHERE o.data_date            = ld.max_date
      AND o.pipeline_entered_date BETWEEN DATE('{period_start}') AND DATE('{period_end}')
      {opened_filter}
    GROUP BY 1
),

-- Monthly targets: divide quarterly targets evenly across 3 months
-- (A more precise approach would use a monthly targets table if available.)
monthly_targets AS (
    SELECT
        ADD_MONTHS(t.quarter_start_date, m.offset)                AS month_start,
        COALESCE(SUM(t.full_won_amount),    0) / 3                AS monthly_won_target,
        COALESCE(SUM(t.full_won_opps),      0) / 3                AS monthly_won_opps_target,
        COALESCE(SUM(t.full_opened_amount), 0) / 3                AS monthly_pipeline_target,
        COALESCE(SUM(t.full_opened_opps),   0) / 3                AS monthly_opened_opps_target
    FROM federated.sales.metis_targets_summary  t
    CROSS JOIN (SELECT 0 AS offset UNION ALL SELECT 1 UNION ALL SELECT 2) m
    WHERE t.quarter_start_date >= DATE_TRUNC('quarter', DATE('{period_start}'))
      AND t.quarter_start_date <= DATE_TRUNC('quarter', DATE('{period_end}'))
      AND t.plan_version        = '{plan_version}'
      {targets_filter}
    GROUP BY 1
)

SELECT
    COALESCE(w.month_start, o.month_start)                         AS month_start,
    DATE_FORMAT(COALESCE(w.month_start, o.month_start), 'MMM yyyy') AS month_label,

    -- ── Actuals ───────────────────────────────────────────────────────────────
    COALESCE(w.won_amount,   0)                                     AS won_amount,
    COALESCE(w.won_opps,     0)                                     AS won_opps,
    COALESCE(o.opened_amount, 0)                                    AS pipeline_amount,
    COALESCE(o.opened_opps,  0)                                     AS opened_opps,

    -- ── Monthly Targets ───────────────────────────────────────────────────────
    COALESCE(t.monthly_won_target,         0)                       AS monthly_won_target,
    COALESCE(t.monthly_won_opps_target,    0)                       AS monthly_won_opps_target,
    COALESCE(t.monthly_pipeline_target,    0)                       AS monthly_pipeline_target,
    COALESCE(t.monthly_opened_opps_target, 0)                       AS monthly_opened_opps_target,

    -- ── Derived KPIs ──────────────────────────────────────────────────────────
    CASE WHEN COALESCE(w.won_opps, 0)    > 0 THEN ROUND(w.won_amount / w.won_opps, 2)        ELSE 0 END AS ads,
    CASE WHEN COALESCE(o.opened_opps, 0) > 0 THEN ROUND(o.opened_amount / o.opened_opps, 2)  ELSE 0 END AS aos,
    CASE WHEN COALESCE(o.opened_opps, 0) > 0 THEN ROUND(w.won_opps * 1.0 / o.opened_opps, 4) ELSE 0 END AS close_rate_opps,
    CASE WHEN COALESCE(o.opened_amount, 0) > 0 THEN ROUND(w.won_amount / o.opened_amount, 4) ELSE 0 END AS close_rate_dollar,

    -- ── Attainment % ──────────────────────────────────────────────────────────
    CASE WHEN COALESCE(t.monthly_won_target, 0) > 0
         THEN ROUND(COALESCE(w.won_amount, 0) / t.monthly_won_target * 100, 1)
         ELSE NULL END                                              AS won_amount_attainment_pct,
    CASE WHEN COALESCE(t.monthly_pipeline_target, 0) > 0
         THEN ROUND(COALESCE(o.opened_amount, 0) / t.monthly_pipeline_target * 100, 1)
         ELSE NULL END                                              AS pipeline_attainment_pct

FROM won_by_month   w
FULL OUTER JOIN opened_by_month  o ON o.month_start = w.month_start
LEFT  JOIN monthly_targets       t ON t.month_start = COALESCE(w.month_start, o.month_start)
ORDER BY 1
