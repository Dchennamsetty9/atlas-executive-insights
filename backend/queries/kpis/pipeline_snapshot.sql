-- queries/kpis/pipeline_snapshot.sql
-- Won pipeline KPIs from federated.sales.metis_won_opps_fact.
-- Active pipeline, win rate, and lost volume are not available in the federated
-- layer; they return NULL (coerced to 0 in gaim_data_service.py).
-- Compares current period vs 90 days prior (same-length window shifted back).
--
-- Placeholders: {start_date}, {end_date}, {filter_clause}
-- Note: {filter_clause} is constructed from VALIDATED whitelist values only —
--       never from raw user input.
WITH latest AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),
won AS (
    SELECT
        COALESCE(SUM(w.amount_towards_plan), 0)           AS won_pipeline,
        COUNT(DISTINCT w.salesforce_opportunity_id)        AS won_volume
    FROM federated.sales.metis_won_opps_fact w
    CROSS JOIN latest ld
    WHERE w.data_date  = ld.max_date
      AND w.close_date BETWEEN DATE('{start_date}') AND DATE('{end_date}')
      {filter_clause}
),
prev AS (
    SELECT
        COALESCE(SUM(w.amount_towards_plan), 0)           AS prev_won_pipeline,
        COUNT(DISTINCT w.salesforce_opportunity_id)        AS prev_won_volume
    FROM federated.sales.metis_won_opps_fact w
    CROSS JOIN latest ld
    WHERE w.data_date  = ld.max_date
      AND w.close_date BETWEEN DATE_ADD(DATE('{start_date}'), -90)
                           AND DATE_ADD(DATE('{end_date}'),   -90)
      {filter_clause}
)
SELECT
    w.won_pipeline,
    w.won_volume,
    CAST(NULL AS DOUBLE)  AS lost_volume,
    CAST(NULL AS DOUBLE)  AS active_pipeline,
    CAST(NULL AS DOUBLE)  AS open_volume,
    p.prev_won_pipeline,
    p.prev_won_volume,
    CAST(NULL AS DOUBLE)  AS win_rate_pct,
    -- Average Deal Size
    CASE WHEN w.won_volume > 0
         THEN w.won_pipeline / w.won_volume
         ELSE 0 END       AS ads,
    CAST(NULL AS DOUBLE)  AS open_opp_size
FROM won w
CROSS JOIN prev p
