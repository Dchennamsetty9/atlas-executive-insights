# 🚨 PERMISSION ISSUE - ACTION REQUIRED

## Issue Detected

Your Databricks token **does not have permission** to access the SQL warehouse:
```
Warehouse ID: c24ee33594e13e93
Path: /sql/1.0/warehouses/c24ee33594e13e93
```

**Error:**
```
PERMISSION_DENIED: dileep.chennamsetty@goto.com is not authorized to use this SQL Endpoint.
```

---

## 🔧 How to Fix This

### Option 1: Request Access to the Current Warehouse (RECOMMENDED)

1. **Contact your Databricks Admin** and request access to:
   - Warehouse ID: `c24ee33594e13e93`
   - Workspace: `goto-eureka-mdl-1.cloud.databricks.com`

2. **What to ask for:**
   ```
   "Hi, I need access to SQL Warehouse c24ee33594e13e93 on goto-eureka-mdl-1 
   to run queries on datagroup_mdl.mdl_sales_analytics tables for the Atlas 
   Executive Insights dashboard."
   ```

3. **After access granted:**
   ```powershell
   cd backend
   python test_databricks_connection.py
   ```
   Should now show ✅ Connection successful

---

### Option 2: Use a Different SQL Warehouse

If you have access to a different warehouse:

1. **Find your accessible warehouse:**
   - Go to: https://goto-eureka-mdl-1.cloud.databricks.com/
   - Click **SQL Warehouses** in the sidebar
   - Look for warehouses where you have "Can Use" permission
   - Copy the **HTTP Path** (looks like `/sql/1.0/warehouses/...`)

2. **Update your configuration:**

   Edit `backend/.env`:
   ```
   DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/YOUR_WAREHOUSE_ID
   ```

   Also edit `app.yaml`:
   ```yaml
   - name: DATABRICKS_HTTP_PATH
     value: "/sql/1.0/warehouses/YOUR_WAREHOUSE_ID"
   ```

3. **Test the connection:**
   ```powershell
   cd backend
   python test_databricks_connection.py
   ```

---

### Option 3: Get Your Own Personal Access Token

If the token is from someone else's account:

1. **Generate your own token:**
   - Go to: https://goto-eureka-mdl-1.cloud.databricks.com/
   - Click your user icon (top right) → **User Settings**
   - Click **Access Tokens** tab
   - Click **Generate New Token**
   - **Lifetime**: 90 days (or longer)
   - **Comment**: "Atlas Executive Insights Dashboard"
   - Click **Generate**
   - **COPY THE TOKEN** (you can't see it again!)

2. **Update .env file:**
   ```powershell
   cd backend
   notepad .env
   ```
   
   Replace the token:
   ```
   DATABRICKS_ACCESS_TOKEN=dapi_YOUR_NEW_TOKEN_HERE
   ```

3. **Test:**
   ```powershell
   python test_databricks_connection.py
   ```

---

## ✅ What You Need Before Deployment

### Required Permissions:

1. **SQL Warehouse Access** ✅
   - Can use a SQL warehouse (any warehouse with compute)

2. **Unity Catalog Table Access** ✅
   - READ permission on: `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot`
   - READ permission on: `datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily`

3. **Databricks Apps Permission** (for deployment)
   - Workspace User role or higher

---

## 🔍 Verify Permissions

### Check SQL Warehouse Access:

```sql
-- Run this in Databricks SQL Editor
-- If it works, you have access!

SELECT COUNT(*) 
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
LIMIT 1;
```

**Expected:** Should return a number (not an error)

### Check Table Permissions:

```sql
-- Test both tables
SELECT COUNT(*) as pipeline_records
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot;

SELECT COUNT(*) as created_records  
FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily;
```

**Expected:** Both queries return numbers (not permission errors)

---

## 🚀 After Fixing Permissions

Once the connection test passes:

```powershell
cd backend
python test_databricks_connection.py
```

**Expected output:**
```
✅ Successfully connected to Databricks
✅ Found 12,345 records in gaim_pipeline_daily_snapshot
✅ Found 6,789 records in gaim_snapshot_pipeline_created_cq_daily
✅ Connection test PASSED
```

**Then proceed to:**
1. Build the frontend: `cd ../frontend && npm run build`
2. Follow the rest of **PRE_DEPLOYMENT_CHECKLIST.md**
3. Deploy using **DATABRICKS_DEPLOYMENT.md**

---

## 💡 Common Issues

### "Invalid token" error
**Fix:** Generate a new personal access token (Option 3 above)

### "Warehouse not running" error
**Fix:** 
- Go to Databricks SQL Warehouses
- Find your warehouse
- Click **Start** if it's stopped
- Wait 1-2 minutes
- Run test again

### "Table not found" error
**Fix:**
- Verify table names are exactly:
  - `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot`
  - `datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily`
- Request READ access from Unity Catalog admin

---

## 📧 Email Template for Admin

Copy/paste this to request access:

```
Subject: Request SQL Warehouse Access for Atlas Executive Insights

Hi [Admin Name],

I'm working on the Atlas Executive Insights dashboard and need access to query 
MDL tables. Could you please grant me:

1. CAN USE permission on SQL Warehouse: c24ee33594e13e93
   (or any other SQL warehouse with compute)

2. READ access to Unity Catalog tables:
   - datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
   - datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily

3. Workspace User role (for deploying to Databricks Apps later)

Workspace: goto-eureka-mdl-1.cloud.databricks.com

Thank you!
```

---

## 🎯 Next Steps

1. ✅ Fix the permission issue using one of the options above
2. ✅ Verify connection test passes
3. ✅ Continue with **PRE_DEPLOYMENT_CHECKLIST.md**
4. ✅ Deploy using **DATABRICKS_DEPLOYMENT.md**
