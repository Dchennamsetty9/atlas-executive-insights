-- queries/mql/conversion.sql
-- Daily MQL count for the current quarter (gaim_mql_daily_snapshot).
-- NOTE: mql-to-opp conversion rate is not available from this table;
--       conversion_rate is returned as null for future enrichment.
-- Placeholders: {table}, {quarter_start}
--
-- Column notes (gaim_mql_daily_snapshot):
--   date column = report_date  (not snapshot_date)
--   mql flag    = mqls = 1     (integer, not 'True')
SELECT
    report_date                                      AS date,
    SUM(CASE WHEN mqls = 1 THEN 1 ELSE 0 END)       AS mql_count,
    CAST(NULL AS DOUBLE)                             AS conversion_rate
FROM {table}
WHERE report_date >= '{quarter_start}'
GROUP BY report_date
ORDER BY report_date
