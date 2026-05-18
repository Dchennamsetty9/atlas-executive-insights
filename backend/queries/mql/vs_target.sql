-- queries/mql/vs_target.sql
-- Daily MQL actuals vs the daily target for the current quarter.
-- Placeholders: {table}, {quarter_start}
SELECT
    snapshot_date              AS date,
    COUNT(DISTINCT interest_name) AS actual,
    MAX(daily_mql_target)         AS target
FROM {table}
WHERE mqls = 'True'
  AND snapshot_date >= '{quarter_start}'
GROUP BY snapshot_date
ORDER BY snapshot_date
