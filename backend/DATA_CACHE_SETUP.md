# Data Cache Setup Guide

## Overview

This dashboard uses a **local SQLite cache** for fast performance instead of querying Databricks in real-time. This provides:

- ⚡ **Sub-second response times** (vs. 2-5 seconds for Databricks queries)
- 💰 **Cost savings** (no warehouse compute costs)
- 🎯 **Demo-ready** (works offline)
- 🔒 **Simple architecture** (no connection management)

## Quick Start

### Step 1: Extract Data from Databricks

Run the extraction script to pull 3 years of data:

```powershell
cd backend
python scripts/extract_data.py
```

This will:
- Connect to Databricks using credentials in `.env`
- Query 3 years of data from:
  - `gaim_pipeline_daily_snapshot`
  - `opportunity_scoring`
  - `forecast_prophet`
- Create `backend/data/cache.db` (~20-50MB)
- Store all data in SQLite for fast queries

**Expected output:**
```
🚀 ATLAS Executive Insights - Data Extraction
📊 Extracting pipeline daily snapshot...
✅ Extracted 10,523 rows
📊 Extracting opportunity scoring data...
✅ Extracted 5,892 rows
📊 Extracting forecast data...
✅ Extracted 1,247 rows
💾 Storing data in SQLite...
📦 Database size: 35.42 MB
✅ EXTRACTION COMPLETE!
```

### Step 2: Restart Backend

The backend will automatically detect and use the cache:

```powershell
python main.py
```

You'll see:
```
💾 SQLite cache: FOUND at C:\...\backend\data\cache.db
```

### Step 3: Verify Cache Status

Check cache info via API:

```powershell
curl http://localhost:8000/api/cache/info
```

Response:
```json
{
  "status": "ready",
  "size_mb": 35.42,
  "last_refresh": "2026-05-12T13:45:23",
  "date_range": {
    "start": "2023-05-12",
    "end": "2026-05-12"
  },
  "row_counts": {
    "pipeline": 10523,
    "opportunities": 5892,
    "forecasts": 1247
  }
}
```

## Scheduled Refresh

### Option A: Manual Refresh

Run whenever you want fresh data:

```powershell
cd backend
python scripts/refresh_weekly.py
```

### Option B: Windows Task Scheduler (Recommended)

Set up automatic weekly refresh:

```powershell
# Run as Administrator
cd backend\scripts
.\setup_scheduler.ps1
```

This creates a scheduled task that runs **every Sunday at 2:00 AM**.

**Manual trigger:**
```powershell
schtasks /run /tn "Atlas-Executive-Insights-Weekly-Refresh"
```

## Database Schema

### Tables

**pipeline_daily**
- `snapshot_date` - Date of snapshot
- `kpi_name` - Metric name (won_pipeline, active_pipeline, etc.)
- `kpi_value` - Current value
- `target_value` - Target/goal
- `segment`, `region`, `product_line` - Dimensions

**opportunities**
- `opportunity_id` - Unique ID
- `amount` - Deal size
- `stage` - Current stage
- `probability` - Win probability (0-100)
- `win_score` - ML win score (0-1)

**forecasts**
- `forecast_date` - Future date
- `metric_name` - What's being forecasted
- `forecast_value` - Predicted value
- `lower_bound`, `upper_bound` - Confidence interval

**refresh_metadata**
- Tracks when data was last refreshed
- Row counts per table
- Success/failure status

## Troubleshooting

### Cache Not Found

**Error:**
```
⚠️ No local cache - run 'python scripts/extract_data.py' to create it
```

**Solution:**
Run the extraction script (Step 1 above)

### Databricks Connection Fails

**Error:**
```
❌ ERROR: Cannot connect to Databricks
```

**Check:**
1. `.env` file exists with correct credentials
2. Access token is valid
3. Network connection to Databricks

**Test connection:**
```powershell
python -c "from databricks import sql; print('OK')"
```

### Empty Results

**Issue:** Cache exists but queries return no data

**Solution:**
1. Check date ranges in queries
2. Verify data was extracted:
   ```powershell
   python -c "import sqlite3; conn = sqlite3.connect('data/cache.db'); print('Rows:', conn.execute('SELECT COUNT(*) FROM pipeline_daily').fetchone()[0])"
   ```
3. Re-run extraction if needed

## Data Refresh Strategy

### Recommended Schedule

| Dashboard Usage | Refresh Frequency | Why |
|---|---|---|
| Executive reviews (weekly) | Weekly | Data stays current without overhead |
| Board meetings (monthly) | Monthly | Sufficient for high-level trends |
| Daily operations | Daily | Keep up with fast-moving metrics |

### Hybrid Approach (Advanced)

For best of both worlds:

1. **Historical data** (>7 days old) → SQLite cache
2. **Recent data** (<7 days) → Live Databricks query

Modify `data_fetcher_sqlite.py` to query Databricks for recent dates.

## File Locations

```
backend/
├── data/
│   └── cache.db                    # SQLite database (created by extraction)
├── scripts/
│   ├── extract_data.py             # Initial extraction from Databricks
│   ├── refresh_weekly.py           # Weekly refresh script
│   └── setup_scheduler.ps1         # Windows Task Scheduler setup
├── services/
│   └── data_fetcher_sqlite.py      # SQLite-based data fetcher
└── .env                             # Databricks credentials
```

## Performance Comparison

| Operation | Databricks (Real-time) | SQLite (Cache) |
|---|---|---|
| KPI query | 2-5 seconds | 50-100ms |
| Historical trend | 3-8 seconds | 100-200ms |
| Full dashboard load | 10-20 seconds | 500ms-1s |
| Warehouse cost | $$$  | $0 |

## Next Steps

1. ✅ Run `extract_data.py` to create cache
2. ✅ Restart backend
3. ✅ Verify cache with `/api/cache/info`
4. ✅ Set up weekly refresh (optional)
5. 🎯 Enjoy instant dashboard performance!

## Questions?

- **"Will this affect my Databricks tables?"** - No, we only READ data (SELECT queries)
- **"Can I still use Power BI?"** - Yes, completely independent systems
- **"What if cache gets stale?"** - Run `refresh_weekly.py` anytime
- **"Can I version control the cache?"** - It's a binary file, so add `data/*.db` to `.gitignore`
