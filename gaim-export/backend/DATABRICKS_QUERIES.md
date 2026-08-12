# Complete Databricks Query for All Dashboard KPIs

## 🎯 Dashboard KPIs Needed

Your dashboard has **8 KPI cards** that need different data:

1. **Won Pipeline** ($) - Closed Won deals amount
2. **Won Volume** (#) - Count of closed won deals  
3. **Average Deal Size** ($) - Won Pipeline ÷ Won Volume
4. **Opportunities Created** (#) - New opportunities in period
5. **Created Pipeline** ($) - Total value of created opportunities
6. **Active Pipeline** ($) - Open opportunities value
7. **Close Rate** (%) - Won Volume ÷ Total Opportunities
8. **Pipeline Coverage** (x) - Active Pipeline ÷ Quota

---

## 📊 Recommended Query (Copy/Paste into Databricks)

This single query gets everything you need:

```sql
-- Complete KPI data for Executive Dashboard
-- Last 3 years of daily snapshots

WITH daily_metrics AS (
  SELECT 
    data_day as snapshot_date,
    fiscal_quarter_name as fiscal_quarter,
    fiscal_year,
    
    -- Won Metrics (Closed Won deals)
    COUNT(DISTINCT CASE 
      WHEN is_won = 'True' AND xtxtype <> 'Cancel' 
      THEN opportunities_created_ids 
    END) as won_volume,
    
    SUM(CASE 
      WHEN is_won = 'True' AND xtxtype <> 'Cancel' 
      THEN amount_towards_plan 
      ELSE 0 
    END) as won_pipeline,
    
    -- Created Metrics (New opportunities)
    COUNT(DISTINCT CASE 
      WHEN pipeline_entered_date = data_day 
      THEN opportunities_created_ids 
    END) as opps_created,
    
    SUM(CASE 
      WHEN pipeline_entered_date = data_day 
      THEN amount 
      ELSE 0 
    END) as created_pipeline,
    
    -- Active Pipeline (Open opportunities)
    COUNT(DISTINCT CASE 
      WHEN stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
      THEN opportunities_created_ids 
    END) as active_opps,
    
    SUM(CASE 
      WHEN stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
      THEN amount_towards_plan 
      ELSE 0 
    END) as active_pipeline,
    
    -- Total opportunities (for close rate)
    COUNT(DISTINCT opportunities_created_ids) as total_opps,
    
    -- Targets (adjust multipliers based on your business)
    2000000 as won_pipeline_target,     -- $2M monthly target
    90 as won_volume_target,            -- 90 deals monthly
    28000 as ads_target,                -- $28K average deal size
    220 as opps_created_target,         -- 220 new opps monthly
    7500000 as created_pipeline_target, -- $7.5M created
    10000000 as active_pipeline_target, -- $10M active
    30.0 as close_rate_target,          -- 30% close rate
    3.0 as coverage_target,             -- 3x coverage
    
    -- Dimensions for filtering
    segment,
    geo_region as region,
    product_line
    
  FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
  
  WHERE data_day >= DATE_SUB(CURRENT_DATE(), 1095)  -- Last 3 years
  
  GROUP BY 
    data_day,
    fiscal_quarter_name,
    fiscal_year,
    segment,
    geo_region,
    product_line
)

-- Transform into format for dashboard (one row per KPI per day)
SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'won_pipeline' as kpi_name, 
       won_pipeline as kpi_value,
       won_pipeline_target as target_value
FROM daily_metrics WHERE won_pipeline > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'won_volume' as kpi_name,
       won_volume as kpi_value,
       won_volume_target as target_value
FROM daily_metrics WHERE won_volume > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'ads' as kpi_name,
       CASE WHEN won_volume > 0 THEN won_pipeline / won_volume ELSE 0 END as kpi_value,
       ads_target as target_value
FROM daily_metrics WHERE won_volume > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'opps_created' as kpi_name,
       opps_created as kpi_value,
       opps_created_target as target_value
FROM daily_metrics WHERE opps_created > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'created_pipeline' as kpi_name,
       created_pipeline as kpi_value,
       created_pipeline_target as target_value
FROM daily_metrics WHERE created_pipeline > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'active_pipeline' as kpi_name,
       active_pipeline as kpi_value,
       active_pipeline_target as target_value
FROM daily_metrics WHERE active_pipeline > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'close_rate' as kpi_name,
       CASE WHEN total_opps > 0 THEN (won_volume * 100.0 / total_opps) ELSE 0 END as kpi_value,
       close_rate_target as target_value
FROM daily_metrics WHERE total_opps > 0

UNION ALL

SELECT snapshot_date, fiscal_quarter, fiscal_year, segment, region, product_line,
       'coverage' as kpi_name,
       CASE WHEN won_pipeline > 0 THEN active_pipeline / won_pipeline ELSE 0 END as kpi_value,
       coverage_target as target_value
FROM daily_metrics WHERE won_pipeline > 0

ORDER BY snapshot_date DESC, kpi_name
```

**Save as:** `dashboard_kpis_complete.csv`

---

## 🚀 Simplified Version (If Above Query is Too Complex)

If that query is too slow or complex, try this **streamlined version** - gets most recent snapshot only:

```sql
SELECT 
  MAX(data_day) as snapshot_date,
  'won_pipeline' as kpi_name,
  SUM(CASE WHEN is_won = 'True' THEN amount_towards_plan ELSE 0 END) as kpi_value,
  2000000 as target_value,
  segment,
  geo_region as region
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 7)  -- Last week only
GROUP BY segment, geo_region

UNION ALL

SELECT 
  MAX(data_day) as snapshot_date,
  'active_pipeline' as kpi_name,
  SUM(CASE WHEN stage_name NOT IN ('Closed Won', 'Closed Lost') THEN amount_towards_plan ELSE 0 END) as kpi_value,
  10000000 as target_value,
  segment,
  geo_region as region
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 7)
GROUP BY segment, geo_region
```

**Save as:** `dashboard_kpis_simple.csv`

---

## 📋 Column Mapping Reference

Match your Databricks columns to dashboard needs:

| Dashboard KPI | Databricks Column(s) | Calculation |
|---|---|---|
| Won Pipeline | `amount_towards_plan` | WHERE `is_won = 'True'` |
| Won Volume | `opportunities_created_ids` | COUNT DISTINCT won |
| Avg Deal Size | Calculated | Won Pipeline ÷ Won Volume |
| Opps Created | `opportunities_created_ids` | WHERE `pipeline_entered_date = today` |
| Created Pipeline | `amount` | WHERE `pipeline_entered_date = today` |
| Active Pipeline | `amount_towards_plan` | WHERE stage NOT closed |
| Close Rate | Calculated | Won ÷ Total opps |
| Coverage | Calculated | Active ÷ Target |

---

## 🔧 Customize for Your Available Columns

If your table has **different column names**, tell me what columns you see, and I'll adjust the query. Common variations:

- `amount_towards_plan` → `amount`, `deal_value`, `opportunity_amount`
- `is_won` → `stage = 'Closed Won'`, `status = 'Won'`
- `geo_region` → `region`, `geography`, `market`
- `opportunities_created_ids` → `opportunity_id`, `opp_id`

---

## ⚡ Quick Start Option

**Don't want to write SQL?** Just export the **entire table** as-is:

```sql
SELECT *
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE data_day >= DATE_SUB(CURRENT_DATE(), 365)
LIMIT 50000
```

Then send me the column names, and I'll write a custom import script that transforms your data into the 8 KPIs!

---

## 💡 Best Practice Recommendation

**Option A: Full Historical (Best for trends)**
- Run the complete query above
- Gets 3 years of daily snapshots
- ~10K-50K rows
- Shows trends over time
- Takes 2-5 minutes to download

**Option B: Latest Snapshot (Best for current state)**
- Run the simplified query
- Gets most recent week only
- ~100-500 rows
- Fast download (30 seconds)
- Good for current KPI values

**Option C: Hybrid (Recommended)**
- Last 90 days of daily data
- Change `1095` to `90` in the query
- ~2K-5K rows
- Perfect balance of history + speed

---

## 🎯 Next Steps

1. **Try the Complete Query** in Databricks SQL Editor
2. If it fails, tell me the **error message** or **column names you have**
3. I'll customize it for your exact table structure
4. Download CSV → Run `py scripts/load_csv.py` → Real data! 🚀

**Which query would you like to try first?** Or **send me your table's column names** and I'll write a perfect query for you!
