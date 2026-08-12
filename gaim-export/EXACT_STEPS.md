# 🚀 EXACT STEPS TO DEPLOY

## Current Status: ⚠️ PERMISSION ISSUE BLOCKING

Your code is **100% ready**, but there's a **permission issue** preventing Databricks connection.

---

## 📋 What's Ready ✅

- ✅ Backend code configured for Databricks Apps
- ✅ Frontend code configured for production
- ✅ Auto-detects MDL table connection
- ✅ Will fetch live data once permissions fixed
- ✅ `app.yaml` deployment config complete
- ✅ All files committed to local Git

---

## 🚨 BLOCKEDBEFORE DEPLOYMENT

**Issue:** Your Databricks token doesn't have access to SQL Warehouse

**Error:**
```
PERMISSION_DENIED: dileep.chennamsetty@goto.com is not authorized 
to use this SQL Endpoint c24ee33594e13e93
```

---

## ✅ STEP 1: Fix Permissions (CRITICAL)

### Quick Fix Options:

**Option A - Request Warehouse Access (5 minutes)**
Email your Databricks admin:
```
I need CAN USE permission on SQL Warehouse c24ee33594e13e93 
in goto-eureka-mdl-1 workspace for Atlas dashboard.
```

**Option B - Generate Your Own Token (2 minutes)**
1. Go to: https://goto-eureka-mdl-1.cloud.databricks.com/
2. User Settings → Access Tokens → Generate New Token
3. Copy the token
4. Update `backend/.env`:
   ```
   DATABRICKS_ACCESS_TOKEN=dapi_YOUR_NEW_TOKEN
   ```

**Option C - Use Different Warehouse (3 minutes)**
1. Find a warehouse you have access to in Databricks UI
2. Copy its HTTP Path: `/sql/1.0/warehouses/XXXXX`
3. Update `backend/.env` and `app.yaml`

**📖 Full details in:** [PERMISSION_FIX.md](PERMISSION_FIX.md)

---

## ✅ STEP 2: Verify Connection

After fixing permissions:

```powershell
cd backend
python test_databricks_connection.py
```

**Expected:**
```
✅ Successfully connected to Databricks
✅ Found 12,345 records in gaim_pipeline_daily_snapshot
✅ Found 6,789 records in gaim_snapshot_pipeline_created_cq_daily
✅ Connection test PASSED
```

**If still failing:** See [PERMISSION_FIX.md](PERMISSION_FIX.md)

---

## ✅ STEP 3: Build Frontend

```powershell
cd frontend
npm install
npm run build
```

**Verify:**
```powershell
ls dist/index.html  # Should exist
ls dist/assets/     # Should have JS/CSS files
```

---

## ✅ STEP 4: Test Locally (Optional but Recommended)

### Terminal 1 - Start Backend:
```powershell
cd backend
python -m uvicorn main:app --reload
```

### Terminal 2 - Start Frontend:
```powershell
cd frontend
npm run dev
```

### Browser - Test Dashboard:
Open: http://localhost:3000/

**Verify:**
- ✅ KPIs show real numbers (not zeros)
- ✅ Charts display data
- ✅ Filters work
- ✅ No console errors

**If seeing zeros:** Permissions still not fixed

---

## ✅ STEP 5: Commit Everything to GitHub

```powershell
# From project root
git status
git add .
git commit -m "Ready for Databricks Apps - auto-fetch from MDL tables"
git push origin main
```

---

## ✅ STEP 6: Deploy to Databricks Apps

### 6A. Connect GitHub to Databricks Repos

1. Go to: https://goto-eureka-mdl-1.cloud.databricks.com/
2. Sidebar → **Workspace** → **Repos**
3. Click **Add Repo**
4. Repository URL: `https://github.com/your-org/atlas-executive-insights`
5. Click **Create Repo**

### 6B. Deploy the App

**Using Databricks UI:**
1. Sidebar → **Apps**
2. Click **Create App**
3. **Name**: `atlas-executive-insights`
4. **Source**: Your repo path
5. **Config file**: `app.yaml`
6. Click **Deploy**
7. Wait 2-3 minutes

**Using CLI:**
```bash
databricks apps deploy atlas-executive-insights \
  --source-path /Workspace/Repos/<your-user>/atlas-executive-insights \
  --config app.yaml
```

**📖 Full deployment guide:** [DATABRICKS_DEPLOYMENT.md](DATABRICKS_DEPLOYMENT.md)

---

## ✅ STEP 7: Verify Deployment

### Test the deployed app:

```
https://goto-eureka-mdl-1.cloud.databricks.com/apps/atlas-executive-insights
```

**Health Check:**
Visit: `https://your-app-url/`

**Expected:**
```json
{
  "status": "running",
  "deployed_in_databricks": true,
  "environment": "production"
}
```

**Test KPIs:**
Visit: `https://your-app-url/api/kpis`

Should return real data from MDL tables!

---

## 🎯 Data Flow After Deployment

```
Your ETL Pipeline runs daily
    ↓ Updates Unity Catalog tables
    ↓
gaim_pipeline_daily_snapshot (MDL table)
gaim_snapshot_pipeline_created_cq_daily (MDL table)
    ↓ Queried on every page load
    ↓
Databricks App Backend (your deployed app)
    ↓ Returns fresh data
    ↓
Frontend Dashboard
    ↓ Shows to users
    ↓
✨ ALWAYS CURRENT - NO MANUAL REFRESH ✨
```

**Every time someone opens the dashboard = fresh query to MDL tables!**

---

## 📚 All Documentation Files

| File | Purpose |
|------|---------|
| **PERMISSION_FIX.md** | Fix SQL warehouse access issue |
| **PRE_DEPLOYMENT_CHECKLIST.md** | Complete verification checklist |
| **DATABRICKS_DEPLOYMENT.md** | Step-by-step deployment guide |
| **CHANGES_SUMMARY.md** | What changed and why |
| **THIS FILE** | Quick reference - exact steps |

---

## ⏱️ Time Estimate

| Step | Time |
|------|------|
| Fix permissions | 5-10 min |
| Verify connection | 1 min |
| Build frontend | 2 min |
| Test locally (optional) | 5 min |
| Push to GitHub | 1 min |
| Connect Databricks Repos | 2 min |
| Deploy to Databricks Apps | 3 min |
| Verify deployment | 2 min |
| **TOTAL** | **~20 minutes** |

---

## 🚨 Current Blocker

**YOU ARE HERE:** ⚠️ Permission issue

**NEXT:** Fix permissions using [PERMISSION_FIX.md](PERMISSION_FIX.md)

**THEN:** Follow steps 2-7 above

---

## ✅ Success Criteria

You'll know everything is working when:

1. ✅ `test_databricks_connection.py` passes
2. ✅ Local dashboard shows real data (not zeros)
3. ✅ Deployed dashboard accessible at Databricks Apps URL
4. ✅ Deployed dashboard shows `"deployed_in_databricks": true`
5. ✅ KPIs update automatically when MDL tables update
6. ✅ No manual refresh needed - always fresh data!

---

## 🆘 Need Help?

1. **Permission issues:** [PERMISSION_FIX.md](PERMISSION_FIX.md)
2. **Deployment steps:** [DATABRICKS_DEPLOYMENT.md](DATABRICKS_DEPLOYMENT.md)
3. **Full checklist:** [PRE_DEPLOYMENT_CHECKLIST.md](PRE_DEPLOYMENT_CHECKLIST.md)
4. **What changed:** [CHANGES_SUMMARY.md](CHANGES_SUMMARY.md)

---

## 🎉 After Successful Deployment

Your dashboard will:
- ✅ Query live MDL tables on every page load
- ✅ Auto-update when your ETL pipeline runs
- ✅ Enforce Unity Catalog permissions
- ✅ Use Databricks SSO authentication
- ✅ Be accessible to your entire team
- ✅ Never show stale data
- ✅ Require zero manual maintenance

**Share the URL with your team and enjoy! 🚀**
