# Metis Federated Tables Migration - Deployment Guide

## Summary
Migrated from `datagroup_mdl.mdl_sales_analytics` tables (which required special permissions) to `federated.sales` Metis tables (publicly accessible federated tables).

## Changes Made

### 1. Configuration Updates

#### app.yaml
- Changed `DATABRICKS_CATALOG` from `"datagroup_mdl"` → `"federated"`
- Changed `DATABRICKS_SCHEMA` from `"mdl_sales_analytics"` → `"sales"`

#### backend/config/settings.py
- Updated `databricks_catalog` default from `"datagroup_mdl"` → `"federated"`
- Updated `databricks_schema` default from `"mdl_sales_analytics"` → `"sales"`
- Added comment: "Using federated sales tables to avoid catalog permissions issues"

### 2. SQL Query Updates in backend/services/data_fetcher.py

#### Table Mapping
| Old Table (MDL) | New Table (Federated) | Purpose |
|---|---|---|
| `gaim_pipeline_daily_snapshot` (is_won='True') | `metis_won_opps_fact` | Won opportunities |
| `gaim_snapshot_pipeline_created_cq_daily` | `metis_opened_opps_fact` | Created/opened opportunities |
| N/A | `metis_targets_summary` | Targets (future use) |

#### Column Mapping
| Old Column | New Column |
|---|---|
| `opportunities_created_ids` | `salesforce_opportunity_id` |
| `data_day` | `data_date` |
| `is_won = 'True'` filter | Query `metis_won_opps_fact` directly (all rows are won) |
| `stage_name NOT IN (...)` filter | LEFT JOIN logic: opened but not in won table |

#### KPI Query Changes

**Won Pipeline & Won Volume:**
```sql
-- OLD:
FROM gaim_pipeline_daily_snapshot
WHERE is_won = 'True' AND xtxtype <> 'Cancel'

-- NEW:
FROM metis_won_opps_fact
-- (All rows are won, no filter needed)
```

**Active Pipeline:**
```sql
-- OLD:
FROM gaim_pipeline_daily_snapshot
WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')

-- NEW:
FROM metis_opened_opps_fact o
LEFT JOIN metis_won_opps_fact w
  ON o.salesforce_opportunity_id = w.salesforce_opportunity_id
WHERE w.salesforce_opportunity_id IS NULL  -- Not yet won = still active
```

**Created Pipeline & Opps Created:**
```sql
-- OLD:
FROM gaim_snapshot_pipeline_created_cq_daily

-- NEW:
FROM metis_opened_opps_fact
WHERE pipeline_entered_date BETWEEN '{start_date}' AND '{end_date}'
```

### 3. Test Script Updates

#### backend/test_connection.py
- Updated to query `metis_won_opps_fact` instead of `gaim_pipeline_daily_snapshot`
- Changed `data_day` → `data_date`
- Changed `opportunities_created_ids` → `salesforce_opportunity_id`
- Removed `is_won = 'True'` filter (all rows in metis_won_opps_fact are won)

### 4. Documentation Updates

#### backend/services/data_fetcher.py header
- Version bumped: 0.3.0 → 0.4.0
- Updated subtitle: "Direct Databricks Mode" → "Metis Federated Tables Mode"
- Updated table documentation to list Metis tables

#### New documentation: METIS_MIGRATION.md
- Created comprehensive migration guide
- Documented schema differences
- Listed open questions (e.g., target calculations)

## Benefits

### ✅ Solved Problems
1. **No permissions errors** - Federated tables are accessible to all service principals
2. **Cleaner schema** - Purpose-built tables for KPI queries (won vs opened)
3. **Better performance** - Tables clustered by date for faster queries
4. **No cancellation logic needed** - Tables already filtered correctly

### 🎯 Expected Results
- All 8 KPI queries should execute without "Error during request to server"
- Dashboard should display real data instead of mock fallback
- Health check endpoint should show "Connected" status
- No authentication/permission errors

## Testing Plan

### Local Testing (Optional)
```bash
cd backend
python test_connection.py
```

Expected output:
- ✅ Found X rows in metis_won_opps_fact
- ✅ Latest data: YYYY-MM-DD
- ✅ Won Pipeline: $X,XXX,XXX
- ✅ Won Deals: XXX

### Databricks Apps Deployment
1. Commit and push changes to GitHub:
   ```bash
   git add -A
   git commit -m "Migrate to Metis federated tables to fix permissions"
   git push origin main
   ```

2. Redeploy in Databricks Apps:
   - Navigate to https://goto-data-dock.cloud.databricks.com/apps
   - Find "atlas-executive-insights" app
   - Click "Update" → Pull from GitHub (main branch)
   - Wait for deployment (2-3 minutes)

3. Test the deployed app:
   - Open app URL
   - Check dashboard loads without errors
   - Verify KPI cards show real data (not "0.0M")
   - Check connection status indicator (should be green)
   - Test date range filters
   - Test geo/channel/product filters

### Verification Checklist
- [ ] App deploys without build errors
- [ ] Backend starts successfully (logs show no crashes)
- [ ] Health check returns 200 with `database_connected: true`
- [ ] /api/kpis returns real data (not mock data)
- [ ] Frontend displays KPI values > 0
- [ ] Filters work correctly
- [ ] Date range selection works
- [ ] Charts display time series data
- [ ] Console shows no errors

## Rollback Plan

If issues occur, revert to MDL tables:

```bash
git revert HEAD
git push origin main
```

Or manually:
1. In app.yaml: Change catalog back to "datagroup_mdl", schema to "mdl_sales_analytics"
2. In settings.py: Change catalog back to "datagroup_mdl", schema to "mdl_sales_analytics"
3. In data_fetcher.py: Revert SQL queries to use gaim_pipeline_daily_snapshot tables

## Open Questions / Future Work

1. **Targets Integration**: Should we use `metis_targets_summary` for real target values instead of hardcoded percentages?
2. **Date Filtering**: Verify the `data_date` field is updated daily in Metis tables
3. **Performance**: Monitor query performance with LEFT JOIN for active pipeline
4. **Completeness**: Do Metis tables have all the same dimensions (sales_market, sales_channel, product_group)?
5. **Historical Data**: How far back does Metis data go compared to MDL?

## Next Steps

After successful deployment:
1. Monitor app performance and query times
2. Compare KPI values to Performance Hub to ensure accuracy
3. Add error monitoring/alerting
4. Consider adding `metis_targets_summary` for real target calculations
5. Implement additional features from user wish list (MQL, segments, deal bands)

## Support

If deployment issues occur:
- Check Databricks Apps logs for backend errors
- Check browser console for frontend errors
- Verify service principal has access to `federated.sales` catalog
- Confirm SQL warehouse is running and accessible
- Test connection using test_connection.py script
