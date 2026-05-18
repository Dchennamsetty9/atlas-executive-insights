-- queries/mql/volume.sql
-- MQL count aggregated by the requested time bucket.
-- Placeholders: {table}, {trunc}, {quarter_start}
SELECT
    DATE_TRUNC('{trunc}', snapshot_date) AS date,
    COUNT(DISTINCT interest_name)         AS mql_count,
    COUNT(DISTINCT CASE WHEN trial = 'True' THEN interest_name END) AS trial_count
FROM {table}
WHERE mqls = 'True'
  AND snapshot_date >= '{quarter_start}'
GROUP BY 1
ORDER BY 1
