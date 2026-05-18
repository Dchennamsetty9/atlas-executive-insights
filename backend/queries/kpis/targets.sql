-- queries/kpis/targets.sql
-- QTD pro-rated plan targets from the daily targets table.
--
-- Placeholders: {catalog}, {schema}, {start_date}, {end_date}, {filter_clause}
-- Note: {filter_clause} is constructed from VALIDATED whitelist values only.
SELECT
    SUM(Daily_Plan_Dollar)        AS target_won_pipeline,
    SUM(Daily_Target_WonVol)      AS target_won_volume,
    SUM(Daily_Target_ADS)         AS target_ads_sum,
    COUNT(*)                      AS target_days
FROM {catalog}.{schema}.gaim_partner_sales_targets_cy_daily
WHERE report_date BETWEEN '{start_date}' AND '{end_date}'
  {filter_clause}
