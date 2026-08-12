# Migration to Metis Federated Tables

## Overview
Migrating from `datagroup_mdl.mdl_sales_analytics` (requires special permissions) to `federated.sales` (publicly accessible federated tables).

## Table Mapping

### Current (MDL):
- `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot`
- `datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily`

### New (Federated):
- `federated.sales.metis_opened_opps_fact` - Opened opportunities (daily granularity)
- `federated.sales.metis_won_opps_fact` - Won opportunities (daily granularity)  
- `federated.sales.metis_targets_summary` - Quarterly targets with pacing

## Metis Schema

### metis_opened_opps_fact
- `pipeline_entered_date` DATE - When opp entered pipeline
- `salesforce_opportunity_id` STRING
- `amount_towards_plan` DECIMAL(38,2)
- `sales_market` STRING (Geo)
- `sales_channel` STRING (Channel - smoothed)
- `product_group`, `product_family`, `product_genus` STRING
- `fuel_source` STRING
- `data_date` DATE

### metis_won_opps_fact  
- `close_date` DATE - When opp was closed/won
- `salesforce_opportunity_id` STRING
- `amount_towards_plan` DECIMAL(38,2)
- `sales_market` STRING
- `sales_channel` STRING
- `product_group`, `product_family`, `product_genus` STRING
- `fuel_source` STRING
- `data_date` DATE

### metis_targets_summary
- Quarterly targets
- Pacing calculations

## KPI Calculation Changes

| KPI | Current Query | New Query |
|-----|---------------|-----------|
| Won Pipeline $ | `gaim_pipeline_daily_snapshot WHERE is_won='True'` | `metis_won_opps_fact` aggregated by date range |
| Won Volume # | `COUNT(DISTINCT opportunities_created_ids)` | `COUNT(DISTINCT salesforce_opportunity_id) FROM metis_won_opps_fact` |
| Opps Created # | `gaim_snapshot_pipeline_created_cq_daily` | `COUNT(DISTINCT salesforce_opportunity_id) FROM metis_opened_opps_fact` |
| Created Pipeline $ | `gaim_snapshot_pipeline_created_cq_daily` | `SUM(amount_towards_plan) FROM metis_opened_opps_fact` |
| Active Pipeline | Need to determine logic from opened vs won | TBD |

## Benefits
1. ✅ No special catalog permissions required
2. ✅ Federated tables accessible to all users
3. ✅ Cleaner schema optimized for KPI queries
4. ✅ Daily granularity with clustering for performance

## Implementation
1. Update `app.yaml` - Change catalog/schema to `federated.sales`
2. Update `settings.py` - Change defaults
3. Update `data_fetcher.py` - Rewrite SQL queries for Metis tables
4. Deploy and test

## Open Questions
- How to calculate "Active Pipeline" from Metis tables?
- Do we need `metis_targets_summary` for target calculations?
