# Manual Data Load from Databricks

## Quick Overview

Since you don't have programmatic access to the Databricks SQL warehouse, you can **manually download** the data and load it into your local SQLite cache.

**Time required:** 10-15 minutes  
**Difficulty:** Easy (point-and-click)

---

## Step 1: Access Databricks SQL

1. Open your browser and go to: **https://goto-eureka-mdl-1.cloud.databricks.com**
2. Click **SQL** or **SQL Editor** in the left sidebar
3. Select warehouse: **c24ee33594e13e93** (or any warehouse you have access to)

---

## Step 2: Run Queries and Download Data

Run each query below in the SQL Editor, then download results as CSV.

### Query 1: Pipeline Daily Snapshot (REQUIRED)

This is the main table with KPI data.

```sql
SELECT 
    data_day as snapshot_date,
    fiscal_quarter_name as fiscal_quarter,
    fiscal_year,
    'won_pipeline' as kpi_name,
    SUM(CASE WHEN is_won = 'True' THEN amount_towards_plan ELSE 0 END) as kpi_value,
    SUM(CASE WHEN is_won = 'True' THEN amount_towards_plan ELSE 0 END) * 0.9 as target_value,
    segment,
    geo_region as region,
    product_line
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 1095)  -- Last 3 years
GROUP BY data_day, fiscal_quarter_name, fiscal_year, segment, geo_region, product_line

UNION ALL

SELECT 
    data_day as snapshot_date,
    fiscal_quarter_name as fiscal_quarter,
    fiscal_year,
    'created_pipeline' as kpi_name,
    SUM(amount) as kpi_value,
    SUM(amount) * 0.9 as target_value,
    segment,
    geo_region as region,
    product_line
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 1095)
GROUP BY data_day, fiscal_quarter_name, fiscal_year, segment, geo_region, product_line

UNION ALL

SELECT 
    data_day as snapshot_date,
    fiscal_quarter_name as fiscal_quarter,
    fiscal_year,
    'active_pipeline' as kpi_name,
    SUM(CASE WHEN stage_name NOT IN ('Closed Won', 'Closed Lost') THEN amount_towards_plan ELSE 0 END) as kpi_value,
    SUM(CASE WHEN stage_name NOT IN ('Closed Won', 'Closed Lost') THEN amount_towards_plan ELSE 0 END) * 0.8 as target_value,
    segment,
    geo_region as region,
    product_line
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 1095)
GROUP BY data_day, fiscal_quarter_name, fiscal_year, segment, geo_region, product_line

ORDER BY snapshot_date DESC
```

**Download as:** `pipeline_snapshot.csv`

---

### Query 2: Opportunities (OPTIONAL - for win probability)

```sql
SELECT 
    opportunity_id,
    opportunity_name,
    created_date,
    close_date,
    amount,
    stage_name as stage,
    probability,
    0.5 as win_score,  -- Placeholder if you don't have ML scores
    segment,
    geo_region as region,
    owner_name
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE created_date >= DATE_SUB(CURRENT_DATE(), 1095)
  AND opportunity_id IS NOT NULL
GROUP BY opportunity_id, opportunity_name, created_date, close_date, amount, 
         stage_name, probability, segment, geo_region, owner_name
ORDER BY created_date DESC
LIMIT 10000
```

**Download as:** `opportunities.csv`

---

### Query 3: Simple Alternative (If the above queries don't work)

If the complex queries fail, try this simpler approach - just get the raw data:

```sql
SELECT 
    data_day as snapshot_date,
    'pipeline' as kpi_name,
    SUM(amount_towards_plan) as kpi_value,
    SUM(amount_towards_plan) * 0.9 as target_value,
    segment,
    geo_region as region,
    product_line,
    fiscal_quarter_name as fiscal_quarter,
    fiscal_year
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 365)  -- Last year only for speed
GROUP BY data_day, segment, geo_region, product_line, fiscal_quarter_name, fiscal_year
ORDER BY data_day DESC
```

**Download as:** `pipeline_simple.csv`

---

## Step 3: Save CSV Files

1. In Databricks SQL Editor, after running each query:
   - Click **Download** button (or **Export**)
   - Choose **CSV** format
   - Save to your computer

2. Create the CSV import folder:
   ```powershell
   cd "c:\Users\dchennamsetty\OneDrive - GoTo Technologies USA LLC\Documents\atlas-executive-insights\backend"
   mkdir data\csv_imports
   ```

3. Move your CSV files into this folder:
   ```
   backend/data/csv_imports/
   ├── pipeline_snapshot.csv
   └── opportunities.csv  (optional)
   ```

---

## Step 4: Load CSV into SQLite

Run the import script:

```powershell
cd "c:\Users\dchennamsetty\OneDrive - GoTo Technologies USA LLC\Documents\atlas-executive-insights\backend"
py scripts/load_csv.py
```

You should see:
```
📥 CSV Import - Manual Data Load
✅ Schema created
📂 Found 1 CSV file(s)
📊 Loading: pipeline_snapshot.csv
   Rows: 15,234
   ✅ Loaded 15,234 rows into pipeline_daily
✅ IMPORT COMPLETE!
```

---

## Step 5: Start Backend with Real Data

```powershell
cd backend
py main.py
```

You should see:
```
💾 SQLite cache: FOUND at ...\data\cache.db
INFO:     Uvicorn running on http://localhost:8000
```

Then refresh your browser at http://localhost:3001 - you'll see real data! 🎉

---

## Troubleshooting

### "Table not found" or "Permission denied"

**Solution:** You may not have access to `gaim_pipeline_daily_snapshot`. Ask your admin for:
- The correct table name for pipeline/KPI data
- Read permissions to that table

Then modify the queries above with the correct table name.

### "Missing columns" error during CSV load

**Solution:** The CSV column names don't match what the script expects. Options:

1. **Rename columns in Excel/CSV editor:**
   - Open the CSV file
   - Change column headers to match: `snapshot_date`, `kpi_name`, `kpi_value`, `target_value`

2. **Modify the script:** Edit `scripts/load_csv.py` to match your column names

### CSV file has different structure

**Solution:** Send me a sample of your CSV columns, and I'll adjust the import script to match.

---

## Alternative: Use Any Table You Have Access To

If you have access to **different tables** in Databricks:

1. Find any table with sales/pipeline data
2. Export whatever fields you have
3. I'll adjust the import script to match your data structure

**Just need these basic fields:**
- Date
- Metric name (won deals, pipeline, etc.)
- Metric value (dollar amount or count)

---

## Benefits of This Approach

✅ **Works with any permissions** - only needs read access  
✅ **One-time setup** - load once, use forever  
✅ **Fast dashboard** - no network latency  
✅ **Offline capable** - works without Databricks connection  
✅ **Easy updates** - re-run query monthly/quarterly

---

## Next Steps

Once you have CSV files:
1. Run `py scripts/load_csv.py`
2. Start backend: `py main.py`
3. Refresh browser - see your real data! 🚀

**Questions?** Let me know what table names you have access to, and I'll customize the queries for you!
