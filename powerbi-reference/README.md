# Power BI Reference Files

This folder contains reference Power BI dashboards, notebooks, and documentation used by the Atlas Executive Insights forecasting module.

## Folder Structure

### 📊 `dashboards/`
Upload Power BI dashboard files here:
- `.pbix` files (Power BI Desktop files)
- `.pbip` folders (Power BI Projects - preferred for version control)
- `.pbit` template files

**Example files to upload:**
- ARR Forecast dashboard
- Revenue forecasting dashboard
- Pipeline analytics dashboard

### 📓 `notebooks/`
Upload related Jupyter notebooks or SQL scripts:
- Data transformation notebooks (`.ipynb`)
- ETL scripts (`.py`)
- SQL queries (`.sql`)

### 📝 `documentation/`
Upload supporting documentation:
- Data dictionary
- Table schemas
- Business logic documentation
- Dashboard user guides

## How to Use

1. **Upload your downloaded dashboard** to `dashboards/`
2. The backend will automatically discover tables from:
   - `.pbip/SemanticModel/definition/tables/` folder
   - Database connections in the semantic model
3. Update backend queries in `backend/services/data_fetcher.py` based on discovered tables

## Tables Already Integrated

The following tables from Performance Hub are already integrated:

- `gaim_pipeline_daily_snapshot` - Pipeline metrics
- `gaim_snapshot_pipeline_created_cq_daily` - Created pipeline
- `partner_ending_arr` - ARR data
- `cm_salesforce_account_portfolio` - Account portfolio

## Next Steps After Upload

1. Examine the semantic model to find table names
2. Check DAX measures for metric calculations
3. Update `data_fetcher.py` with new table queries
4. Add new metrics to forecasting service
5. Test with `/api/forecast?metric=your_metric` endpoint
