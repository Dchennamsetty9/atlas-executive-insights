-- queries/mql/conversion.sql
-- Daily MQL-to-Opportunity conversion rate for the current quarter.
-- Placeholders: {table}, {quarter_start}
SELECT
    snapshot_date                                                         AS date,
    mql_count,
    marketing_opps,
    ROUND(SAFE_DIVIDE(marketing_opps, mql_count) * 100, 1)               AS conversion_rate
FROM (
    SELECT
        snapshot_date,
        COUNT(DISTINCT interest_name)    AS mql_count,
        SUM(created_opp_flag)            AS marketing_opps
    FROM {table}
    WHERE mqls = 'True'
      AND snapshot_date >= '{quarter_start}'
    GROUP BY snapshot_date
) sub
ORDER BY snapshot_date
