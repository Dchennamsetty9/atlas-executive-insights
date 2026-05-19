-- queries/kpis/targets.sql
-- Full-quarter targets from cds_targets_monthly (monthly grain → SUM for quarter).
-- ⚠️ No paced_* columns in direct source — use full quarterly totals.
--    Proration to QTD is done in Python (days_elapsed / days_in_quarter).
--
-- Placeholders: {catalog}, {schema}, {quarter_start}, {filter_clause}
-- Note: {filter_clause} uses TARGET table column names:
--         sales_market, sales_channel, product_group, product_family, product_genus
SELECT
    SUM(acv_generated_target)  AS target_won_pipeline,
    SUM(num_won_opps)          AS target_won_volume,
    SUM(pipeline)              AS target_pipeline,
    SUM(num_pipe_opps)         AS target_pipeline_volume,
    SUM(lead_target)           AS target_mql
FROM {catalog}.{schema}.cds_targets_monthly
WHERE DATE_TRUNC('quarter', month) = DATE_TRUNC('quarter', CAST('{quarter_start}' AS DATE))
  AND plan_version = 'Plan'
  {filter_clause}
