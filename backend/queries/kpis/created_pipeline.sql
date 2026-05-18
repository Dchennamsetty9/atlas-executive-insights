-- queries/kpis/created_pipeline.sql
-- Opportunities created and associated pipeline value in the given date range.
--
-- Placeholders: {catalog}, {schema}, {start_date}, {end_date}, {filter_clause}
-- Note: {filter_clause} is constructed from VALIDATED whitelist values only.
SELECT
    COUNT(DISTINCT opportunities_created_ids)     AS opps_created,
    COALESCE(SUM(amount_towards_plan), 0)         AS created_pipeline
FROM {catalog}.{schema}.gaim_snapshot_pipeline_created_cq_daily
WHERE xtxtype <> 'Cancel'
  AND pipeline_entered_date BETWEEN '{start_date}' AND '{end_date}'
  {filter_clause}
