-- queries/kpis/mql.sql
-- MQL count for the given date range.
--
-- Placeholders: {catalog}, {schema}, {start_date}, {end_date}, {filter_clause}
-- Note: {filter_clause} is constructed from VALIDATED whitelist values only.
SELECT
    COUNT(*)                                         AS mql_count,
    SUM(CASE WHEN mqls  = 1 THEN 1 ELSE 0 END)      AS mql_reached,
    SUM(CASE WHEN trial = 1 THEN 1 ELSE 0 END)       AS trial_count
FROM {catalog}.{schema}.gaim_mql_daily_snapshot
WHERE report_date BETWEEN '{start_date}' AND '{end_date}'
  {filter_clause}
