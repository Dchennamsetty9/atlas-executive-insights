-- queries/performance/trend_quarterly.sql
-- ============================================================
-- Quarterly Trend — All Core KPIs for the Last N Quarters
-- Returns one row per quarter with actuals, targets, and attainment.
-- Used by the KPI Trends charts (bar/line overlays).
-- ============================================================
--
-- Structural placeholders:
--   {n_quarters}    integer  number of past quarters to include (e.g. 6)
--   {plan_version}  Plan | FY4 | FY7
--   {won_filter}    AND-prefixed fragment for metis_won_opps_fact
--   {opened_filter} AND-prefixed fragment for metis_opened_opps_fact
--   {targets_filter}AND-prefixed fragment for metis_targets_summary
-- ============================================================

WITH

latest_date AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),

-- Generate the list of quarter start dates to include
quarters AS (
    SELECT DISTINCT DATE_TRUNC('quarter', DATEADD(MONTH, -3 * n, CURRENT_DATE())) AS quarter_start
    FROM (
        SELECT EXPLODE(SEQUENCE(0, {n_quarters} - 1)) AS n
    )
),

won_by_quarter AS (
    SELECT
        DATE_TRUNC('quarter', w.close_date)              AS quarter_start,
        COUNT(DISTINCT w.salesforce_opportunity_id)      AS won_opps,
        COALESCE(SUM(w.amount_towards_plan), 0)          AS won_amount
    FROM federated.sales.metis_won_opps_fact  w
    CROSS JOIN latest_date  ld
    -- Use full-quarter actuals for past quarters; YTD for current quarter
    WHERE w.data_date = ld.max_date
      {won_filter}
    GROUP BY 1
),

opened_by_quarter AS (
    SELECT
        DATE_TRUNC('quarter', o.pipeline_entered_date)   AS quarter_start,
        COUNT(DISTINCT o.salesforce_opportunity_id)      AS opened_opps,
        COALESCE(SUM(o.amount_towards_plan), 0)          AS opened_amount
    FROM federated.sales.metis_opened_opps_fact  o
    CROSS JOIN latest_date  ld
    WHERE o.data_date = ld.max_date
      {opened_filter}
    GROUP BY 1
),

targets_by_quarter AS (
    SELECT
        t.quarter_start_date                               AS quarter_start,
        COALESCE(SUM(t.full_won_amount),     0)            AS full_won_amount,
        COALESCE(SUM(t.full_won_opps),       0)            AS full_won_opps,
        COALESCE(SUM(t.full_opened_amount),  0)            AS full_opened_amount,
        COALESCE(SUM(t.full_opened_opps),    0)            AS full_opened_opps,
        -- Use paced target for current quarter, full for past
        COALESCE(SUM(
            CASE WHEN t.quarter_start_date = DATE_TRUNC('quarter', CURRENT_DATE())
                 THEN t.paced_won_amount
                 ELSE t.full_won_amount
            END
        ), 0)                                              AS effective_won_target,
        COALESCE(SUM(
            CASE WHEN t.quarter_start_date = DATE_TRUNC('quarter', CURRENT_DATE())
                 THEN t.paced_opened_amount
                 ELSE t.full_opened_amount
            END
        ), 0)                                              AS effective_pipeline_target
    FROM federated.sales.metis_targets_summary  t
    WHERE plan_version = '{plan_version}'
      {targets_filter}
    GROUP BY 1
)

SELECT
    q.quarter_start,
    DATE_FORMAT(q.quarter_start, 'QQ YYYY')                                      AS quarter_label,

    -- ── Won Amount ────────────────────────────────────────────────────────────
    COALESCE(w.won_amount, 0)                                                     AS won_amount,
    COALESCE(t.full_won_amount, 0)                                                AS full_won_target,
    COALESCE(t.effective_won_target, 0)                                           AS paced_won_target,
    CASE WHEN COALESCE(t.effective_won_target, 0) > 0
         THEN ROUND(COALESCE(w.won_amount, 0) / t.effective_won_target * 100, 1)
         ELSE NULL END                                                            AS won_amount_attainment_pct,

    -- ── Won Opps ──────────────────────────────────────────────────────────────
    COALESCE(w.won_opps, 0)                                                       AS won_opps,
    COALESCE(t.full_won_opps, 0)                                                  AS full_won_opps_target,

    -- ── Pipeline ──────────────────────────────────────────────────────────────
    COALESCE(o.opened_amount, 0)                                                  AS pipeline_amount,
    COALESCE(t.full_opened_amount, 0)                                             AS full_pipeline_target,
    COALESCE(t.effective_pipeline_target, 0)                                      AS paced_pipeline_target,
    CASE WHEN COALESCE(t.effective_pipeline_target, 0) > 0
         THEN ROUND(COALESCE(o.opened_amount, 0) / t.effective_pipeline_target * 100, 1)
         ELSE NULL END                                                            AS pipeline_attainment_pct,

    -- ── Opened Opps ───────────────────────────────────────────────────────────
    COALESCE(o.opened_opps, 0)                                                    AS opened_opps,
    COALESCE(t.full_opened_opps, 0)                                               AS full_opened_opps_target,

    -- ── Derived KPIs (quarterly) ──────────────────────────────────────────────
    CASE WHEN COALESCE(w.won_opps, 0)    > 0 THEN ROUND(w.won_amount / w.won_opps, 2)         ELSE 0 END AS ads,
    CASE WHEN COALESCE(o.opened_opps, 0) > 0 THEN ROUND(o.opened_amount / o.opened_opps, 2)   ELSE 0 END AS aos,
    CASE WHEN COALESCE(o.opened_opps, 0) > 0 THEN ROUND(w.won_opps * 1.0 / o.opened_opps, 4) ELSE 0 END AS close_rate_opps,
    CASE WHEN COALESCE(o.opened_amount, 0) > 0 THEN ROUND(w.won_amount / o.opened_amount, 4)  ELSE 0 END AS close_rate_dollar,
    CASE WHEN COALESCE(t.effective_won_target, 0) > 0
         THEN ROUND(COALESCE(o.opened_amount, 0) / t.effective_won_target, 4)
         ELSE NULL END                                                            AS coverage_ratio,

    -- ── Is this the current quarter? ──────────────────────────────────────────
    CASE WHEN q.quarter_start = DATE_TRUNC('quarter', CURRENT_DATE())
         THEN TRUE ELSE FALSE END                                                  AS is_current_quarter

FROM quarters  q
LEFT JOIN won_by_quarter      w  ON w.quarter_start = q.quarter_start
LEFT JOIN opened_by_quarter   o  ON o.quarter_start = q.quarter_start
LEFT JOIN targets_by_quarter  t  ON t.quarter_start = q.quarter_start
ORDER BY q.quarter_start
