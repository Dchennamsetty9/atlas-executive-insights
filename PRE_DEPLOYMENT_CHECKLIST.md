# 🚀 PRE-DEPLOYMENT CHECKLIST

## Complete these steps BEFORE uploading to Databricks Apps

---

## ✅ STEP 1: Verify Backend Configuration

### Check .env file exists and has correct values

```powershell
cd backend
cat .env
```

**Expected values:**
```
DATABRICKS_SERVER_HOSTNAME=goto-eureka-mdl-1.cloud.databricks.com
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/c24ee33594e13e93
DATABRICKS_ACCESS_TOKEN=dapi...  # Your actual token
DATABRICKS_CATALOG=datagroup_mdl
DATABRICKS_SCHEMA=mdl_sales_analytics
```

✅ **Verify:**
- [ ] `DATABRICKS_SERVER_HOSTNAME` = goto-eureka-mdl-1.cloud.databricks.com
- [ ] `DATABRICKS_HTTP_PATH` = /sql/1.0/warehouses/c24ee33594e13e93
- [ ] `DATABRICKS_ACCESS_TOKEN` = Your actual token (starts with `dapi`)
- [ ] `DATABRICKS_CATALOG` = datagroup_mdl
- [ ] `DATABRICKS_SCHEMA` = mdl_sales_analytics

---

## ✅ STEP 2: Test Backend Connection to MDL Tables

### Run the test script:

```powershell
cd backend
python test_databricks_connection.py
```

**Expected output:**
```
✅ Successfully connected to Databricks
✅ Found X records in gaim_pipeline_daily_snapshot
✅ Found Y records in gaim_snapshot_pipeline_created_cq_daily
✅ Connection test PASSED
```

❌ **If you see errors:**
- Check your Databricks token is valid
- Verify you have permissions to the tables
- Confirm warehouse is running

✅ **Verify:**
- [ ] Connection test passes
- [ ] Both tables return data (not 0 records)

---

## ✅ STEP 3: Test Backend API Locally

### Start the backend:

```powershell
cd backend
python -m uvicorn main:app --reload
```

### In a new terminal, test the endpoints:

```powershell
# Test health check
curl http://localhost:8000/

# Test KPIs endpoint (should return real data from MDL)
curl http://localhost:8000/api/kpis
```

**Expected health check response:**
```json
{
  "service": "Atlas Executive Insights API",
  "status": "running",
  "mode": "direct_databricks",
  "deployed_in_databricks": false
}
```

**Expected KPIs response:**
- Should return an array of 8 KPI objects
- Each should have `value`, `target`, `trend` fields
- Values should NOT be all zeros (if they are, data connection failed)

✅ **Verify:**
- [ ] Backend starts without errors
- [ ] Health check returns `"status": "running"`
- [ ] `/api/kpis` returns real data (not zeros)
- [ ] No errors in console about Databricks connection

---

## ✅ STEP 4: Build Frontend for Production

### Install dependencies (if needed):

```powershell
cd frontend
npm install
```

### Build the production bundle:

```powershell
npm run build
```

**Expected output:**
```
✓ built in X seconds
dist/index.html
dist/assets/...
```

### Verify the build:

```powershell
ls dist
```

**Should see:**
- `index.html`
- `assets/` folder with JS and CSS files

✅ **Verify:**
- [ ] Build completes without errors
- [ ] `frontend/dist/index.html` exists
- [ ] `frontend/dist/assets/` folder exists with files

---

## ✅ STEP 5: Test Frontend Locally

### Start backend (if not already running):

```powershell
cd backend
python -m uvicorn main:app --reload
```

### In a new terminal, start frontend:

```powershell
cd frontend
npm run dev
```

### Open browser and test:

Open: http://localhost:3000/

✅ **Verify:**
- [ ] Dashboard loads without errors
- [ ] KPIs show real numbers (not zeros)
- [ ] "Last updated" shows current time
- [ ] Charts display data
- [ ] Filters work (Geo, Channel, Product)
- [ ] No console errors about API connection

---

## ✅ STEP 6: Verify Files for Databricks Upload

### Check all required files exist:

```powershell
# Check app.yaml exists
cat app.yaml

# Check backend files
ls backend/main.py
ls backend/requirements.txt
ls backend/services/
ls backend/config/
ls backend/models/

# Check frontend build
ls frontend/dist/index.html
ls frontend/dist/assets/
```

✅ **Verify:**
- [ ] `app.yaml` exists in root
- [ ] `backend/` folder complete with all files
- [ ] `frontend/dist/` folder exists with built files
- [ ] No `.env` file will be committed (it's local only)

---

## ✅ STEP 7: Commit and Push to GitHub

### Stage all changes:

```powershell
git add .
```

### Commit:

```powershell
git commit -m "Ready for Databricks Apps deployment"
```

### Push to GitHub:

```powershell
git push origin main
```

✅ **Verify:**
- [ ] All changes committed
- [ ] Pushed to GitHub successfully
- [ ] Go to GitHub and verify files are there

---

## ✅ STEP 8: Final Pre-Flight Check

Before deploying to Databricks Apps, verify:

### Configuration Files:
- [ ] `app.yaml` - Databricks Apps config exists
- [ ] `backend/.env` - Has valid Databricks credentials (LOCAL ONLY, not in Git)
- [ ] `backend/requirements.txt` - All dependencies listed

### Code Changes:
- [ ] `backend/config/settings.py` - Uses `DATABRICKS_HOST` environment variable
- [ ] `backend/services/data_fetcher.py` - Auto-detects Databricks Apps mode
- [ ] `backend/main.py` - Serves static frontend files in production
- [ ] `frontend/src/services/api.js` - Uses relative URLs in production

### Build Artifacts:
- [ ] `frontend/dist/` folder exists
- [ ] `frontend/dist/index.html` present
- [ ] `frontend/dist/assets/` has JS/CSS bundles

### Data Connection:
- [ ] Backend successfully queries `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot`
- [ ] Backend successfully queries `datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily`
- [ ] KPIs return real data (not zeros or mock data)

---

## 🎯 YOU'RE READY TO DEPLOY!

Once all checkboxes above are ✅, proceed to:

**→ DATABRICKS_DEPLOYMENT.md** for deployment steps

---

## 🔍 Quick Verification Commands

Run these to verify everything before deploying:

```powershell
# 1. Check backend connection
cd backend
python test_databricks_connection.py

# 2. Check frontend build exists
ls ../frontend/dist/index.html

# 3. Test API locally
python -m uvicorn main:app --reload
# In browser: http://localhost:8000/api/kpis

# 4. Verify Git status
cd ..
git status

# 5. Check GitHub (should see all files)
# Visit: https://github.com/your-org/atlas-executive-insights
```

---

## ❌ Common Issues Before Deployment

### Issue: Backend can't connect to Databricks
**Fix:** 
```powershell
cd backend
# Check token is valid
cat .env | grep DATABRICKS_ACCESS_TOKEN
# Regenerate token if needed from Databricks UI
```

### Issue: KPIs show all zeros
**Fix:**
- Verify you have READ permissions on MDL tables
- Check warehouse is running
- Test query manually in Databricks SQL

### Issue: Frontend build fails
**Fix:**
```powershell
cd frontend
# Clean install
rm -r node_modules
rm package-lock.json
npm install
npm run build
```

### Issue: Git push fails
**Fix:**
```powershell
# Pull latest changes first
git pull origin main
# Then push
git push origin main
```

---

## 📊 Expected Data Flow After Deployment

```
Your ETL Pipeline
    ↓ Updates tables
Unity Catalog Tables:
  - gaim_pipeline_daily_snapshot
  - gaim_snapshot_pipeline_created_cq_daily
    ↓ Queried by
Databricks Apps (Your Deployed App)
    ↓ Serves to
Users (via Databricks workspace URL)
```

**Every time a user opens the dashboard, it queries fresh data from Unity Catalog.**

---

## 🎉 Next Steps After Checklist Complete

1. ✅ All items checked above
2. 📖 Follow **DATABRICKS_DEPLOYMENT.md** 
3. 🚀 Deploy to Databricks Apps
4. 🌐 Share URL with team
5. ✨ Enjoy auto-updating KPIs!
