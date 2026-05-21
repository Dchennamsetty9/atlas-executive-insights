-- queries/kpis/targets.sql
-- Full-quarter and paced-to-date targets from federated.sales.metis_targets_summary.
-- Both full_* and paced_* columns are pre-computed in the table; no Python pro-ration needed.
-- MQL target (lead_target) is not in the federated layer; target_mql returns NULL.
--
-- Placeholders: {start_date}, {filter_clause}
-- Note: {start_date} must be the first day of the reporting quarter (YYYY-MM-DD).
--       {filter_clause} is constructed from VALIDATED whitelist values only.
SELECT
    SUM(full_won_amount)     AS target_won_pipeline,
    SUM(full_won_opps)       AS target_won_volume,
    SUM(full_opened_amount)  AS target_pipeline,
    SUM(full_opened_opps)    AS target_pipeline_volume,
    CAST(NULL AS DOUBLE)     AS target_mql,
    SUM(paced_won_amount)    AS paced_won_amount,
    SUM(paced_opened_amount) AS paced_opened_amount
FROM federated.sales.metis_targets_summary
WHERE quarter_start_date = DATE('{start_date}')
  AND plan_version        = 'Plan'
  {filter_clause}
