-- queries/kpis/created_pipeline.sql
-- Opportunities created and associated pipeline value in the given date range.
-- Source: federated.sales.metis_opened_opps_fact
--
-- Bound parameters: start_date, end_date.
-- Note: {filter_clause} is constructed from VALIDATED whitelist values only.
WITH latest AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_opened_opps_fact
)
SELECT
    COUNT(DISTINCT o.salesforce_opportunity_id)  AS opps_created,
    COALESCE(SUM(o.amount_towards_plan), 0)      AS created_pipeline
FROM federated.sales.metis_opened_opps_fact o
CROSS JOIN latest ld
WHERE o.data_date             = ld.max_date
    AND o.pipeline_entered_date BETWEEN DATE(?) AND DATE(?)
  {filter_clause}
