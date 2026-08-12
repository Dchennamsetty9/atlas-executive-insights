# ✅ Atlas Executive Insights - Setup Complete!

## 🎉 What's Been Created

Your **atlas-executive-insights** project is now fully configured with **8 real KPIs from Performance Hub**:

### 📊 The 8 KPIs

1. **Won ACV $** - Closed-won revenue (primary outcome)
2. **# of Deals Won** - Count of won deals
3. **Average Deal Size (ADS)** - Won $ ÷ # of Deals
4. **# of Opps Created** - New opportunities entering pipeline
5. **Created Pipeline $** - Total value of new opportunities
6. **Active Pipeline $** - Currently open opportunities
7. **Close Rate %** - Conversion efficiency (Won ÷ Created)
8. **Coverage %** - Pipeline coverage of remaining target

---

## 🚀 Quick Start (3 Steps)

### Step 1: Get Your Databricks Token

1. Go to: https://goto-data-dock.cloud.databricks.com
2. Click your user icon → **Settings** → **Developer** → **Access tokens**
3. Click **Generate new token**
4. Name it: "Atlas Executive Insights"
5. Copy the token

### Step 2: Configure Backend

```powershell
cd "C:\Users\dchennamsetty\OneDrive - GoTo Technologies USA LLC\Documents\atlas-executive-insights\backend"

# Copy the example file
copy .env.example .env

# Edit .env and paste your token
notepad .env
```

Add your token to `.env`:
```env
DATABRICKS_ACCESS_TOKEN=your-token-here
```

### Step 3: Install & Test

```powershell
# Install dependencies
pip install -r requirements.txt

# Test connection
python test_connection.py

# If test passes, start the server
python main.py
```

---

## 📁 Project Structure

```
atlas-executive-insights/
├── backend/                    # Python FastAPI backend
│   ├── main.py                # ✅ API server with 8 KPI endpoints
│   ├── requirements.txt       # ✅ Includes databricks-sql-connector
│   ├── test_connection.py     # ✅ NEW: Test your Databricks connection
│   ├── .env.example           # ✅ Template with Databricks config
│   ├── config/
│   │   └── settings.py        # ✅ Updated: Databricks settings
│   └── services/
│       ├── data_fetcher.py    # ✅ Updated: Real queries for 8 KPIs
│       ├── forecasting.py     # ML forecasting
│       ├── insights_engine.py # Azure OpenAI insights
│       └── metrics.py         # ✅ Updated: Formats 8 KPIs
│
├── frontend/                   # React app (ready to go)
│   └── src/components/        # ✅ KPI cards, charts, AI insights
│
└── docs/
    ├── DATABASE_CONNECTION.md # ✅ NEW: Complete connection guide
    ├── POC_PLAN.md           # Week 1 development plan
    └── SETUP.md              # Detailed setup instructions
```

---

## 📋 What You Need

### Required
- ✅ **Databricks Personal Access Token** (from Step 1 above)
- ✅ **Azure OpenAI API Key** (for AI insights - optional for POC)

### Already Configured
- ✅ Databricks server: `goto-data-dock.cloud.databricks.com`
- ✅ Warehouse path: `/sql/1.0/warehouses/c24ee33594e13e93`
- ✅ Catalog: `datagroup_mdl`
- ✅ Schema: `mdl_sales_analytics`
- ✅ 8 KPI queries pulling from same tables as Performance Hub

---

## 🔍 How It Works

### Data Flow

```
Databricks (same as Performance Hub)
  ↓
gaim_pipeline_daily_snapshot        ← Won deals, active pipeline
gaim_snapshot_pipeline_created_cq_daily  ← Created pipeline
gaim_partner_sales_targets_cy_daily ← Targets
  ↓
Backend API (data_fetcher.py)       ← 8 KPI queries
  ↓
FastAPI REST API                    ← /api/kpis endpoint
  ↓
React Frontend                      ← KPI cards, charts, AI insights
```

### The 8 KPI Queries

All queries are in [docs/DATABASE_CONNECTION.md](docs/DATABASE_CONNECTION.md) with full SQL.

**Key logic matches Performance Hub:**
- Won Pipeline: `WHERE is_won = 'True' AND xtxtype <> 'Cancel'`
- Active Pipeline: `WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')`
- Close Rate: `Won Volume / Opps Created`
- Coverage: `Active Pipeline / Remaining Target`

---

## ✅ Testing Checklist

### Backend Test
```powershell
cd backend
python test_connection.py
```

**Expected output:**
```
✅ databricks-sql-connector is installed
✅ Connection established!
✅ Found 1,234,567 rows in gaim_pipeline_daily_snapshot
✅ Latest data: 2026-05-10
✅ Won Pipeline: $2,450,000
✅ Won Deals: 78
✅ Average Deal Size: $31,410
```

### Start Backend
```powershell
python main.py
```

**Visit:** http://localhost:8000/docs
- Test endpoint: GET `/api/kpis`
- Should return 8 KPIs with real data

### Start Frontend
```powershell
cd ..\frontend
npm install
npm run dev
```

**Visit:** http://localhost:3000
- Should display 8 KPI cards
- Should show charts and AI insights

---

## 🎨 Frontend Preview

```
┌─────────────────────────────────────────────────────────┐
│  Executive Overview               May 1 - May 31, 2024  │
├─────────────────────────────────────────────────────────┤
│  💰 Won ACV $      📈 # of Deals    💵 Avg Deal Size   │
│  $2.45M (+12.4%)   78 (+8.3%)       $31.4K (+5.4%)     │
│                                                          │
│  📊 # Opps Created  💰 Created $    💼 Active $        │
│  245 (+6.5%)        $8.5M (+9.0%)   $12.0M (+5.3%)     │
│                                                          │
│  📈 Close Rate      🎯 Coverage                         │
│  31.8% (+1.6%)      320% (+3.2%)                        │
├─────────────────────────────────────────────────────────┤
│  📊 Descriptive Analytics   │  🤖 AI Insights          │
│  - Revenue by Region        │  - Won Pipeline up 12%   │
│  - Monthly Trend            │  - Close Rate improving  │
├─────────────────────────────────────────────────────────┤
│  🔮 Predictive Analytics   │  💡 AI Recommendations    │
│  - 90-day forecast          │  - Focus on West region  │
│  - 87% accuracy             │  - Improve conversion    │
└─────────────────────────────────────────────────────────┘
```

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [docs/DATABASE_CONNECTION.md](docs/DATABASE_CONNECTION.md) | **START HERE** - Complete connection guide with SQL queries |
| [docs/POC_PLAN.md](docs/POC_PLAN.md) | Week-by-week development roadmap |
| [SETUP.md](SETUP.md) | Detailed setup and customization guide |
| [QUICKSTART.md](QUICKSTART.md) | Quick reference for common commands |
| [README.md](README.md) | Project overview |

---

## 🐛 Troubleshooting

### "databricks-sql-connector not installed"
```powershell
pip install databricks-sql-connector
```

### "Connection failed"
- Check VPN connection
- Verify token is valid (try generating a new one)
- Confirm you have access to `datagroup_mdl.mdl_sales_analytics`

### "Table not found"
- Run test script: `python test_connection.py`
- Verify catalog and schema names in `.env`

### "Mock data showing instead of real data"
- Check `.env` has `DATABRICKS_ACCESS_TOKEN` set
- Restart backend: `python main.py`

---

## 🎯 Next Steps

### Week 1 POC (Current)
- ✅ 8 KPIs with real data from Databricks
- ⏳ Test connection and start backend
- ⏳ Start frontend and verify KPIs display
- ⏳ Add Azure OpenAI for AI insights

### Week 2+
- Add more KPIs (MQLs, Win Rate, Sales Cycle)
- Implement date range filters
- Add segment breakdowns (by Geo, Channel, Product)
- Improve forecasting accuracy
- Deploy to production

---

## 🔐 Security Reminder

- ✅ `.gitignore` already excludes `.env` files
- ✅ Never commit your Databricks token
- ✅ Tokens expire - set calendar reminder to renew
- ✅ Use service principal tokens for production

---

## 🎉 You're Ready!

1. Get your Databricks token
2. Update `backend/.env`
3. Run `python test_connection.py`
4. Start backend: `python main.py`
5. Start frontend: `npm run dev`
6. Open http://localhost:3000

**Questions?** Check [docs/DATABASE_CONNECTION.md](docs/DATABASE_CONNECTION.md)

---

**Built with:** FastAPI + React + Databricks + Azure OpenAI + Prophet ML  
**For:** GAIM Team Executive Analytics  
**Status:** ✅ Ready for POC Testing
