# 🎯 Performance Hub - Exact KPI Calculations

## Based on Actual Power BI Semantic Model

This document contains the **exact DAX formulas** from Performance Hub and their SQL equivalents for Databricks.

---

## 📊 Core KPIs (8 Dashboard Metrics)

### 1. **Won Pipeline** ($)

**Power BI DAX:**
```dax
Won_Pipeline = 
CALCULATE(
    SUM(gaim_pipeline_daily_snapshot[amount_towards_plan]),
    gaim_pipeline_daily_snapshot[is_won] = "True",
    'Dates Table'[Today?] <> "No"
)
```

**Databricks SQL:**
```sql
SELECT 
    data_day as snapshot_date,
    'won_pipeline' as kpi_name,
    SUM(amount_towards_plan) as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY data_day
```

---

### 2. **Won Volume** (#)

**Power BI DAX:**
```dax
Won_Volume = 
CALCULATE(
    DISTINCTCOUNT(gaim_pipeline_daily_snapshot[opportunities_created_ids]),
    gaim_pipeline_daily_snapshot[is_won] = "True",
    'Dates Table'[Today?] <> "No",
    gaim_pipeline_daily_snapshot[xtxtype] <> "Cancel"
)
```

**Databricks SQL:**
```sql
SELECT 
    data_day as snapshot_date,
    'won_volume' as kpi_name,
    COUNT(DISTINCT opportunities_created_ids) as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND xtxtype <> 'Cancel'
  AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY data_day
```

---

### 3. **Average Deal Size (ADS)** ($)

**Power BI DAX:**
```dax
ADS = Won_Pipeline / Won_Volume
```

**Databricks SQL:**
```sql
SELECT 
    data_day as snapshot_date,
    'ads' as kpi_name,
    SUM(amount_towards_plan) / NULLIF(COUNT(DISTINCT opportunities_created_ids), 0) as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND xtxtype <> 'Cancel'
  AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY data_day
```

---

### 4. **Opportunities Created** (#)

**Power BI DAX:**
```dax
x_OppsCreated_mdl = 
CALCULATE(
    DISTINCTCOUNT(gaim_snapshot_pipeline_created_cq_daily[opportunities_created_ids]),
    gaim_snapshot_pipeline_created_cq_daily[xtxtype] <> "Cancel"
)
```

**Databricks SQL:**
```sql
SELECT 
    pipeline_entered_date as snapshot_date,
    'opps_created' as kpi_name,
    COUNT(DISTINCT opportunities_created_ids) as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
WHERE xtxtype <> 'Cancel'
  AND pipeline_entered_date >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY pipeline_entered_date
```

---

### 5. **Created Pipeline** ($)

**Power BI DAX:**
```dax
xCreated_Pipeline = 
CALCULATE(
    SUM(gaim_snapshot_pipeline_created_cq_daily[amount_towards_plan])
)
```

**Databricks SQL:**
```sql
SELECT 
    pipeline_entered_date as snapshot_date,
    'created_pipeline' as kpi_name,
    SUM(amount_towards_plan) as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
WHERE pipeline_entered_date >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY pipeline_entered_date
```

---

### 6. **Active Pipeline** ($)

**Power BI DAX:**
```dax
Active_Pipeline = 
CALCULATE(
    SUM(gaim_pipeline_daily_snapshot[amount_towards_plan]),
    gaim_pipeline_daily_snapshot[Opp Stage] = "1.Open"
)
```

**Note:** `Opp Stage = "1.Open"` is a calculated column that filters for open stages.

**Databricks SQL:**
```sql
SELECT 
    data_day as snapshot_date,
    'active_pipeline' as kpi_name,
    SUM(amount_towards_plan) as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
  AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY data_day
```

---

### 7. **Close Rate** (%)

**Power BI DAX:**
```dax
close_rate_vol = Won_Volume / x_OppsCreated_mdl
```

**Databricks SQL:**
```sql
WITH won AS (
    SELECT 
        data_day,
        COUNT(DISTINCT opportunities_created_ids) as won_count
    FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
    WHERE is_won = 'True' AND xtxtype <> 'Cancel'
    GROUP BY data_day
),
created AS (
    SELECT 
        pipeline_entered_date as data_day,
        COUNT(DISTINCT opportunities_created_ids) as created_count
    FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
    WHERE xtxtype <> 'Cancel'
    GROUP BY pipeline_entered_date
)
SELECT 
    w.data_day as snapshot_date,
    'close_rate' as kpi_name,
    (w.won_count * 100.0 / NULLIF(c.created_count, 0)) as kpi_value
FROM won w
INNER JOIN created c ON w.data_day = c.data_day
WHERE w.data_day >= DATE_SUB(CURRENT_DATE(), 90)
```

---

### 8. **Pipeline Coverage** (x)

**Power BI DAX:**
```dax
xCvg_mdl = 
IF(
    SUM(gaim_pipeline_daily_snapshot[Total Pipe]) / [Daily_Plan$] > 10,
    10,
    SUM(gaim_pipeline_daily_snapshot[Total Pipe]) / [Daily_Plan$]
)
```

**Databricks SQL:**
```sql
-- Coverage = Active Pipeline / Target
SELECT 
    data_day as snapshot_date,
    'coverage' as kpi_name,
    CASE 
        WHEN SUM(amount_towards_plan) / NULLIF([target_value], 0) > 10 
        THEN 10 
        ELSE SUM(amount_towards_plan) / NULLIF([target_value], 0)
    END as kpi_value
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE stage_name NOT IN ('Closed Won', 'Closed Lost')
  AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
GROUP BY data_day
```

---

## 🔧 Key Tables Reference

### **gaim_pipeline_daily_snapshot**
- Primary fact table for pipeline metrics
- Contains: amount_towards_plan, is_won, opportunities_created_ids, xtxtype, stage_name
- Filtered by: data_day (date)

### **gaim_snapshot_pipeline_created_cq_daily**
- Created pipeline metrics
- Contains: amount_towards_plan, opportunities_created_ids, pipeline_entered_date
- Filtered by: pipeline_entered_date (date)

### **gaim_mql_daily_snapshot**
- Marketing qualified leads
- Contains: MQL counts and metrics

---

## 📋 Important Filters

**From Power BI Model:**

1. **Exclude Cancellations:** `xtxtype <> "Cancel"`
2. **Won Deals:** `is_won = "True"`
3. **Open Opportunities:** `stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')`
4. **Today Filter:** `'Dates Table'[Today?] <> "No"` (filters to current snapshot only)

---

## 🚀 Complete Unified Query

Use this single query to get ALL 8 KPIs:

```sql
-- All 8 KPIs in one query
WITH latest_date AS (
    SELECT MAX(data_day) as latest_day
    FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
),
won_metrics AS (
    SELECT 
        data_day,
        SUM(amount_towards_plan) as won_pipeline,
        COUNT(DISTINCT opportunities_created_ids) as won_volume
    FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
    WHERE is_won = 'True'
      AND xtxtype <> 'Cancel'
      AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
    GROUP BY data_day
),
active_metrics AS (
    SELECT 
        data_day,
        SUM(amount_towards_plan) as active_pipeline,
        COUNT(DISTINCT opportunities_created_ids) as active_volume
    FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
    WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
      AND data_day >= DATE_SUB(CURRENT_DATE(), 90)
    GROUP BY data_day
),
created_metrics AS (
    SELECT 
        pipeline_entered_date as data_day,
        SUM(amount_towards_plan) as created_pipeline,
        COUNT(DISTINCT opportunities_created_ids) as opps_created
    FROM datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily
    WHERE xtxtype <> 'Cancel'
      AND pipeline_entered_date >= DATE_SUB(CURRENT_DATE(), 90)
    GROUP BY pipeline_entered_date
)

SELECT data_day as snapshot_date, 'won_pipeline' as kpi_name, won_pipeline as kpi_value, NULL as target_value
FROM won_metrics

UNION ALL

SELECT data_day as snapshot_date, 'won_volume' as kpi_name, won_volume as kpi_value, NULL as target_value
FROM won_metrics

UNION ALL

SELECT data_day as snapshot_date, 'ads' as kpi_name, 
       won_pipeline / NULLIF(won_volume, 0) as kpi_value, NULL as target_value
FROM won_metrics

UNION ALL

SELECT data_day as snapshot_date, 'opps_created' as kpi_name, opps_created as kpi_value, NULL as target_value
FROM created_metrics

UNION ALL

SELECT data_day as snapshot_date, 'created_pipeline' as kpi_name, created_pipeline as kpi_value, NULL as target_value
FROM created_metrics

UNION ALL

SELECT data_day as snapshot_date, 'active_pipeline' as kpi_name, active_pipeline as kpi_value, NULL as target_value
FROM active_metrics

UNION ALL

SELECT w.data_day as snapshot_date, 'close_rate' as kpi_name, 
       (w.won_volume * 100.0 / NULLIF(c.opps_created, 0)) as kpi_value, 30.0 as target_value
FROM won_metrics w
INNER JOIN created_metrics c ON w.data_day = c.data_day

UNION ALL

SELECT data_day as snapshot_date, 'coverage' as kpi_name,
       CASE WHEN active_pipeline / 2000000 > 10 THEN 10 ELSE active_pipeline / 2000000 END as kpi_value,
       3.0 as target_value
FROM active_metrics

ORDER BY snapshot_date DESC, kpi_name
```

---

## ✅ Validation Checklist

When implementing, verify:

- [ ] Uses `gaim_pipeline_daily_snapshot` for Won/Active metrics
- [ ] Uses `gaim_snapshot_pipeline_created_cq_daily` for Created metrics  
- [ ] Excludes `xtxtype = 'Cancel'` from counts
- [ ] Uses `DISTINCTCOUNT` for opportunity volumes
- [ ] Filters open stages correctly for Active Pipeline
- [ ] Close Rate = Won Volume ÷ Created Volume (not ÷ Total)
- [ ] Coverage caps at 10x maximum

---

## 🎯 Next Steps

1. **Test Query** - Run unified query in Databricks
2. **Download CSV** - Save results
3. **Load to Dashboard** - Use `py scripts/load_csv.py`
4. **Verify** - Compare values against Performance Hub

---

**Last Updated:** Based on Performance Hub semantic model analyzed on 2026-05-12
