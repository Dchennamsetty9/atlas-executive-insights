-- queries/coverage/trend.sql
-- Daily coverage ratio throughout the current quarter.
-- Coverage = in-quarter open pipeline / (full-quarter plan target - QTD won pipeline)
--
-- Placeholders: {catalog}, {schema}, {q_start}, {q_end}
WITH targets AS (
    SELECT SUM(Daily_Plan_Dollar) AS plan_target
    FROM {catalog}.{schema}.gaim_partner_sales_targets_cy_daily
    WHERE report_date BETWEEN '{q_start}' AND '{q_end}'
),
daily_open AS (
    SELECT
        data_day,
        SUM(CASE WHEN close_date <= '{q_end}' THEN amount ELSE 0 END) AS same_q_pipeline
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
    WHERE data_day BETWEEN '{q_start}' AND CURRENT_DATE
      AND xtxtype <> 'Cancel'
      AND stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
    GROUP BY data_day
),
daily_won AS (
    SELECT
        data_day,
        SUM(amount) AS won_pipeline
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
    WHERE data_day BETWEEN '{q_start}' AND CURRENT_DATE
      AND is_won = 'True'
      AND xtxtype <> 'Cancel'
    GROUP BY data_day
)
SELECT
    o.data_day AS snapshot_date,
    ROUND(
        o.same_q_pipeline / NULLIF(
            t.plan_target - COALESCE(w.won_pipeline, 0),
            0
        ),
    2) AS coverage_ratio
FROM daily_open o
LEFT JOIN daily_won w ON o.data_day = w.data_day
CROSS JOIN targets t
ORDER BY o.data_day
