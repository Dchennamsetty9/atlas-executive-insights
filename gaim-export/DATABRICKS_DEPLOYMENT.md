# Databricks Apps Deployment Guide

## 🚀 Deploy Atlas Executive Insights to Databricks Apps

This guide shows how to deploy the dashboard to Databricks Apps for automatic data updates and proper governance.

---

## ✅ Benefits

**Governance & Security:**
- ✅ Data never leaves Databricks
- ✅ Unity Catalog permissions enforced
- ✅ SSO authentication
- ✅ Audit logs

**Auto-Updating KPIs:**
- ✅ Queries live Unity Catalog tables
- ✅ No manual refreshes needed
- ✅ Real-time data on every page load

---

## 📋 Prerequisites

1. **Databricks Workspace** - Access to goto-eureka-mdl-1 workspace
2. **Unity Catalog Access** - Read permissions on:
   - `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot`
   - `datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily`
3. **Databricks SQL Warehouse** - Access to warehouse: `c24ee33594e13e93`
4. **GitHub Access** - To push code to repository

---

## 🏗️ Architecture

```
GitHub Repository
    ↓ (auto-sync)
Databricks Repos
    ↓ (deploy)
Databricks Apps
    ↓ (queries)
Unity Catalog Tables (live data)
    ↓ (displays)
Users (via Databricks workspace URL)
```

---

## 📦 Step 1: Prepare the Code

### Build the Frontend

```bash
cd frontend
npm install
npm run build
```

This creates `frontend/dist/` with the production build.

### Commit Everything to Git

```bash
git add .
git commit -m "Prepare for Databricks Apps deployment"
git push origin main
```

---

## 🔗 Step 2: Connect to Databricks Repos

1. **Go to Databricks Workspace**
   - Navigate to: https://goto-data-dock.cloud.databricks.com/

2. **Open Repos**
   - Sidebar → **Workspace** → **Repos**

3. **Add Repository**
   - Click **Add Repo**
   - **Git repository URL**: `https://github.com/<your-org>/atlas-executive-insights`
   - **Git provider**: GitHub
   - **Repository name**: `atlas-executive-insights`
   - Click **Create Repo**

4. **Auto-Sync** (Optional but Recommended)
   - Settings → Enable **Auto-sync with remote**
   - Now every push to GitHub automatically updates Databricks

---

## 🚀 Step 3: Deploy to Databricks Apps

### Option A: Using Databricks CLI (Recommended)

```bash
# Install Databricks CLI
pip install databricks-cli

# Configure authentication
databricks configure --token

# Deploy the app
databricks apps deploy atlas-executive-insights \
  --source-path /Workspace/Repos/<your-user>/atlas-executive-insights \
  --config app.yaml
```

### Option B: Using Databricks UI

1. **Go to Apps**
   - Sidebar → **Compute** → **Apps**

2. **Create New App**
   - Click **Create App**
   - **Name**: `atlas-executive-insights`
   - **Source**: Select your repo path

3. **Configure Environment**
   - Use the settings from `app.yaml`:
     ```yaml
     DATABRICKS_HTTP_PATH: /sql/1.0/warehouses/c24ee33594e13e93
     DATABRICKS_CATALOG: datagroup_mdl
     DATABRICKS_SCHEMA: mdl_sales_analytics
     ENVIRONMENT: production
     ```

4. **Deploy**
   - Click **Deploy**
   - Wait 2-3 minutes for deployment

---

## 🌐 Step 4: Access Your Dashboard

After deployment, you'll get a URL like:

```
https://goto-data-dock.cloud.databricks.com/apps/atlas-executive-insights
```

**Share this URL with your team!** Everyone with Databricks workspace access can use it.

---

## 🔄 Step 5: Auto-Updates Work Automatically

Now your dashboard updates automatically:

```
Your ETL pipeline runs
    ↓ Updates Unity Catalog tables
    ↓ (gaim_pipeline_daily_snapshot)
    ↓
User opens dashboard
    ↓ Backend queries live tables
    ↓ Returns fresh data
    ↓
Dashboard shows latest KPIs ✅
```

**No manual refresh needed!** KPIs update on every page load.

---

## 🔧 Step 6: Update Your Dashboard

To make changes:

```bash
# Make your changes locally
git add .
git commit -m "Update dashboard"
git push origin main
```

If auto-sync is enabled:
- ✅ Changes appear in Databricks Repos immediately
- ✅ Re-deploy from Databricks Apps UI (or CLI)

---

## 🎯 Key Environment Variables

These are automatically provided by Databricks Apps:

| Variable | Value | Description |
|----------|-------|-------------|
| `DATABRICKS_HOST` | Auto-provided | Workspace hostname |
| `DATABRICKS_TOKEN` | Auto-provided | Service principal token |
| `PORT` | 8000 | Application port |

Your `app.yaml` configures:

| Variable | Value | Description |
|----------|-------|-------------|
| `DATABRICKS_CATALOG` | datagroup_mdl | Unity Catalog catalog |
| `DATABRICKS_SCHEMA` | mdl_sales_analytics | Schema name |
| `DATABRICKS_HTTP_PATH` | /sql/1.0/warehouses/... | SQL warehouse path |

---

## 🛠️ Troubleshooting

### Dashboard Not Loading Data

```bash
# Check backend logs
databricks apps logs atlas-executive-insights
```

**Common issues:**
- Missing Unity Catalog permissions → Contact workspace admin
- Wrong warehouse path → Update `DATABRICKS_HTTP_PATH` in `app.yaml`

### Backend Connection Error

Test the connection manually:

```python
from databricks import sql
import os

connection = sql.connect(
    server_hostname=os.getenv("DATABRICKS_HOST"),
    http_path="/sql/1.0/warehouses/c24ee33594e13e93",
    access_token=os.getenv("DATABRICKS_TOKEN")
)

cursor = connection.cursor()
cursor.execute("SELECT COUNT(*) FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot")
print(cursor.fetchone())
```

### Frontend Not Loading

Build locally first to check for errors:

```bash
cd frontend
npm run build
# Check for any errors
```

---

## 📊 Monitoring

### Health Check

Visit: `https://your-app-url/` to see:

```json
{
  "service": "Atlas Executive Insights API",
  "status": "running",
  "version": "0.3.0",
  "environment": "production",
  "deployed_in_databricks": true
}
```

### Check Data Freshness

Visit: `https://your-app-url/api/kpis`

Look at the `last_updated` field - it should match your latest ETL run.

---

## ✅ Success Checklist

- [ ] Frontend built (`npm run build` successful)
- [ ] Code pushed to GitHub
- [ ] Databricks Repo connected and synced
- [ ] App deployed to Databricks Apps
- [ ] Dashboard URL accessible
- [ ] KPIs loading (shows data, not "0")
- [ ] Health check returns `"deployed_in_databricks": true`
- [ ] Filters working (Geo, Channel, Product)
- [ ] Auto-refresh working (wait 5 min, data updates)

---

## 🎉 You're Done!

Your dashboard is now:
- ✅ **Live** - Running on Databricks Apps
- ✅ **Secure** - Using Databricks authentication & Unity Catalog permissions
- ✅ **Auto-updating** - Queries fresh data on every load
- ✅ **Governed** - Data never leaves Databricks environment

Share the URL with your team and they can start using it immediately!
