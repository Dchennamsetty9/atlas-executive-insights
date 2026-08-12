# Database Connection Guide for Atlas Executive Insights

## 📊 Data Source Information

Your Performance Hub dashboards connect to **Databricks Unity Catalog**.

### Connection Details

```
Databricks Endpoint: goto-data-dock.cloud.databricks.com
SQL Warehouse Path: /sql/1.0/warehouses/c24ee33594e13e93
Catalog: datagroup_mdl
Schema: mdl_sales_analytics
```

### Main Tables Used by Performance Hub

| Table Name | Contains |
|------------|----------|
| `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot` | Won deals, active pipeline, all opportunity data |
| `datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily` | Created pipeline (new opps) |
| `datagroup_mdl.mdl_sales_analytics.gaim_partner_sales_targets_cy_daily` | Targets and quotas |
| `datagroup_mdl.mdl_sales_analytics.gaim_mql_daily_snapshot` | Marketing qualified leads |

---

## 🔐 What You Need to Provide

To connect atlas-executive-insights to your Databricks data source, you need:

### 1. Personal Access Token (PAT)
Generate a Databricks personal access token:

1. Log into Databricks workspace: `https://goto-data-dock.cloud.databricks.com`
2. Click your user icon (top right) → **Settings**
3. Go to **Developer** → **Access tokens**
4. Click **Generate new token**
5. Give it a name: "Atlas Executive Insights"
6. Set expiration: 90 days (or longer)
7. Copy the token (you won't see it again!)

### 2. Update backend/.env

Open `atlas-executive-insights/backend/.env` and set:

```env
# Databricks Connection
DATABRICKS_SERVER_HOSTNAME=goto-data-dock.cloud.databricks.com
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/c24ee33594e13e93
DATABRICKS_ACCESS_TOKEN=your-token-here

# Catalogs and Schemas
DATABRICKS_CATALOG=datagroup_mdl
DATABRICKS_SCHEMA=mdl_sales_analytics

# Azure OpenAI (you already have this)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4
```

---

## 🎯 8 KPIs - SQL Queries

Here are the exact SQL queries for the 8 KPIs, based on Performance Hub logic:

### 1. Won ACV $ (Revenue)

```sql
SELECT 
    SUM(amount_towards_plan) as won_pipeline
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND data_day = (SELECT MAX(data_day) FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot)
  AND YEAR(close_date) = YEAR(CURRENT_DATE())
  AND QUARTER(close_date) = QUARTER(CURRENT_DATE())
```

### 2. # of Deals Won

```sql
SELECT 
    COUNT(DISTINCT opportunities_created_ids) as won_volume
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND xtxtype <> 'Cancel'
  AND data_day = (SELECT MAX(data_day) FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot)
  AND YEAR(close_date) = YEAR(CURRENT_DATE())
  AND QUARTER(close_date) = QUARTER(CURRENT_DATE())
```

### 3. ADS (Average Deal Size)

```sql
SELECT 
    SUM(amount_towards_plan) / COUNT(DISTINCT opportunities_created_ids) as ads
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND xtxtype <> 'Cancel'
  AND data_day = (SELECT MAX(data_day) FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot)
  AND YEAR(close_date) = YEAR(CURRENT_DATE())
  AND QUARTER(close_date) = QUARTER(CURRENT_DATE())
```

### 4. # of Opps Created

```sql
SELECT 
    COUNT(DISTINCT opportunities_created_ids) as opps_created
FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
WHERE YEAR(pipeline_entered_date) = YEAR(CURRENT_DATE())
  AND QUARTER(pipeline_entered_date) = QUARTER(CURRENT_DATE())
```

### 5. Created Pipeline $

```sql
SELECT 
    SUM(amount) as created_pipeline
FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
WHERE YEAR(pipeline_entered_date) = YEAR(CURRENT_DATE())
  AND QUARTER(pipeline_entered_date) = QUARTER(CURRENT_DATE())
```

### 6. Active Pipeline $

```sql
SELECT 
    SUM(amount_towards_plan) as active_pipeline
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
  AND data_day = (SELECT MAX(data_day) FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot)
```

### 7. Close Rate %

```sql
WITH won AS (
    SELECT COUNT(DISTINCT opportunities_created_ids) as won_count
    FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
    WHERE is_won = 'True'
      AND YEAR(close_date) = YEAR(CURRENT_DATE())
      AND QUARTER(close_date) = QUARTER(CURRENT_DATE())
),
created AS (
    SELECT COUNT(DISTINCT opportunities_created_ids) as created_count
    FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
    WHERE YEAR(pipeline_entered_date) = YEAR(CURRENT_DATE())
      AND QUARTER(pipeline_entered_date) = QUARTER(CURRENT_DATE())
)
SELECT (won_count * 1.0 / created_count) * 100 as close_rate
FROM won, created
```

### 8. Coverage %

```sql
WITH active AS (
    SELECT SUM(amount_towards_plan) as active_total
    FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
    WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
),
remaining_target AS (
    SELECT (target_amount - SUM(amount_towards_plan)) as remaining
    FROM datagroup_mdl.mdl_sales_analytics.gaim_partner_sales_targets_cy_daily t
    LEFT JOIN datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot p
      ON t.fiscal_quarter = QUARTER(p.close_date)
    WHERE is_won = 'True'
)
SELECT (active_total / remaining) * 100 as coverage_percent
FROM active, remaining_target
```

---

## 📦 Python Package Requirements

You need the Databricks SQL connector. Add to `backend/requirements.txt`:

```
databricks-sql-connector==3.0.0
```

---

## ✅ Test Connection

Run this test script to verify your connection works:

```python
# test_databricks_connection.py
from databricks import sql
import os
from dotenv import load_dotenv

load_dotenv()

connection = sql.connect(
    server_hostname=os.getenv("DATABRICKS_SERVER_HOSTNAME"),
    http_path=os.getenv("DATABRICKS_HTTP_PATH"),
    access_token=os.getenv("DATABRICKS_ACCESS_TOKEN")
)

cursor = connection.cursor()
cursor.execute("SELECT COUNT(*) FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot")
result = cursor.fetchone()
print(f"✅ Connection successful! Row count: {result[0]}")

cursor.close()
connection.close()
```

Run with:
```powershell
cd backend
python test_databricks_connection.py
```

---

## 🚀 Next Steps

1. ✅ Generate Databricks Personal Access Token
2. ✅ Update `backend/.env` with token and connection details
3. ✅ Install databricks-sql-connector: `pip install databricks-sql-connector`
4. ✅ Test connection with script above
5. ✅ Backend will automatically use real data instead of mock data

---

## 🔒 Security Notes

- **Never commit your `.env` file** - it contains your access token
- Personal access tokens have expiration dates - renew before they expire
- Use service principal tokens for production deployments
- Your token grants read access to the tables - keep it secure

---

## 📞 Troubleshooting

### "Connection timed out"
- Check if you're on the corporate VPN
- Verify the server hostname and HTTP path are correct

### "Permission denied"
- Ensure your Databricks user has SELECT permission on the tables
- Ask data team to grant access to `datagroup_mdl.mdl_sales_analytics.*`

### "Table not found"
- Double-check catalog and schema names
- Run `SHOW TABLES IN datagroup_mdl.mdl_sales_analytics` to list available tables

---

**Ready to connect? Follow the steps above and your dashboard will show real data!** 🎉
