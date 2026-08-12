-- queries/mql/vs_target.sql
-- Daily MQL actuals vs the daily target for the current quarter.
-- Placeholders: {table}, {quarter_start}
--
-- Column notes (gaim_mql_daily_snapshot):
--   date column = report_date  (not snapshot_date)
--   mql flag    = mqls = 1     (integer, not 'True')
SELECT
    report_date                                       AS date,
    SUM(CASE WHEN mqls = 1 THEN 1 ELSE 0 END)        AS actual,
    MAX(COALESCE(daily_mql_target, 0))                AS target
FROM {table}
WHERE report_date >= '{quarter_start}'
GROUP BY report_date
ORDER BY report_date
