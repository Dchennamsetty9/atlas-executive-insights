-- queries/mql/volume.sql
-- MQL count aggregated by the requested time bucket.
-- Placeholders: {table}, {trunc}, {quarter_start}
--
-- Column notes (gaim_mql_daily_snapshot):
--   date column = report_date  (not snapshot_date)
--   mql flag    = mqls = 1     (integer, not 'True')
--   trial flag  = trial = 1    (integer, not 'True')
SELECT
    DATE_TRUNC('{trunc}', report_date)                                     AS date,
    SUM(CASE WHEN mqls  = 1 THEN 1 ELSE 0 END)                            AS mql_count,
    SUM(CASE WHEN trial = 1 THEN 1 ELSE 0 END)                            AS trial_count
FROM {table}
WHERE report_date >= '{quarter_start}'
GROUP BY 1
ORDER BY 1
