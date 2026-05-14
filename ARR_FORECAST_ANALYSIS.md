# 🎯 ARR Forecast Dashboard - Complete Analysis

**Dashboard:** ARR Forecast (Prophet-based Forecasting)  
**Location:** `powerbi-reference/dashboards/ARR Forecast.pbip`  
**Last Analyzed:** May 12, 2026

---

## 📊 Overview

ARR Forecast uses **Facebook Prophet** to predict future pipeline performance with **3 confidence scenarios** (best case, most likely, worst case). It integrates with the same `gaim_pipeline_daily_snapshot` table as Performance Hub.

---

## 🔮 Forecasting Methodology

### **Core Algorithm: Facebook Prophet**

**Prophet Configuration:**
- **Daily seasonality:** Enabled
- **Weekly seasonality:** Enabled  
- **Yearly seasonality:** Enabled
- **Interval width:** Configurable (typically 0.80 = 80% confidence)
- **Aggregation:** Weekly (ISO week numbering, Monday start)
- **Forecast Horizon:** Typically 90-180 days ahead

### **Three Forecast Scenarios:**

| Scenario | Description | Technical Source |
|---|---|---|
| **Best Case** | Upper confidence bound (optimistic) | Prophet `yhat_upper` |
| **Most Likely** | Point estimate (expected value) | Prophet `yhat` |
| **Worst Case** | Lower confidence bound (pessimistic) | Prophet `yhat_lower` |

### **Seasonality Features:**

```dax
// Seasonal flags used in forecast model
summer: BOOLEAN          -- Summer months seasonality
winter: BOOLEAN          -- Winter months seasonality  
isweek1: BOOLEAN         -- First week of month (often has spikes)
```

---

## 📋 Data Model

### **Table: forecast_prophet**

**Purpose:** Main forecast output table with actuals + predictions

| Column | Type | Description |
|---|---|---|
| `ds` | DateTime | Date (Prophet standard column name) |
| `actuals` | Double | Historical ARR values |
| `best_case` | Double | Upper confidence bound forecast |
| `most_likely` | Double | Point estimate forecast |
| `worst_case` | Double | Lower confidence bound forecast |
| `year` | Int | Calendar year |
| `ISOYear` | Int | ISO year (for week-based fiscal calendars) |
| `ISOWeek` | Int | ISO week number (1-53) |
| `WeekYearKey` | Int | `ISOYear * 100 + ISOWeek` for sorting |
| `ARR YTD` | Double | Year-to-date cumulative ARR |

**Key Measures:**

```dax
// Running total of actuals (YTD)
'Running Totals Actuals' = 
    IF(
        MAX('forecast_prophet'[ds]) > LastClosedWeekEnd,
        BLANK(),
        CALCULATE([2025actuals$], DATESYTD('forecast_prophet'[ds]))
    )

// Running total of best case forecast (YTD)
'Running Totals Best Case' = 
    CALCULATE([2025bestcase$], DATESYTD('forecast_prophet'[ds]))

// Running total quarterly
'Running Totals Best Case (Quarterly)' = 
    CALCULATE([2025bestcase$], DATESQTD('forecast_prophet'[ds]))
```

---

### **Table: forecast_prophet_2024**

**Purpose:** Segmented forecast with business context

**Dimensions:**
- `product` (string) — Product category
- `sales_market` (string) — Geographic market (NA/EMEA/LATAM)
- `pe_account_flag` (string) — Partner/Enterprise account flag

**Business Metrics:**
- `avg_deal_size` (double) — Average deal size in segment
- `avg_sales_cycle` (double) — Average days to close
- `number_of_opps` (double) — Opportunity count
- `all_created_arr` (double) — Total ARR created

**Marketing Metrics:**
- `marketing_generated_pipeline` (double) — Pipeline from marketing
- `marketing_influenced_pipeline` (double) — Pipeline influenced by marketing
- `total_partner_pipeline` (double) — Partner-sourced pipeline

**Sales Activity Metrics:**
- `avg_dials` (double) — Average sales dials per opp
- `avg_touches` (double) — Average touchpoints per opp
- `avg_push_counter` (double) — Average close date pushes

**Seasonality Flags:**
- `summer` (boolean) — Summer seasonality indicator
- `winter` (boolean) — Winter seasonality indicator
- `isweek1` (boolean) — First week of month indicator

---

### **Table: opportunity_scoring**

**Purpose:** ML-based opportunity win probability predictions

**Model Metrics:**
- `Accuracy` — (TP + TN) / Total
- `Precision` — TP / (TP + FP)
- `Recall` — TP / (TP + FN)

**Predictions:**
- `class1_probability` — Probability of winning (0.0 - 1.0)
- `prediction` — Binary prediction (0 = Lost, 1 = Won)
- `Probability Bins` — Binned probability ranges

**Confusion Matrix:**
```dax
TP = True Positive (actual=Won, predicted=Won)
TN = True Negative (actual=Lost, predicted=Lost)
FP = False Positive (actual=Lost, predicted=Won)
FN = False Negative (actual=Won, predicted=Lost)
```

---

## 🔗 Integration with Performance Hub

### **Shared Infrastructure:**

| Component | ARR Forecast | Performance Hub | Shared? |
|---|---|---|---|
| **Main Table** | `gaim_pipeline_daily_snapshot` | `gaim_pipeline_daily_snapshot` | ✅ YES |
| **Date Table** | `Dates Table` | `Dates Table` | ✅ YES |
| **Catalog** | `datagroup_mdl.mdl_sales_analytics` | `datagroup_mdl.mdl_sales_analytics` | ✅ YES |
| **Snapshot Logic** | `data_day` snapshots | `data_day` snapshots | ✅ YES |

### **Key Overlapping Fields:**

```sql
-- Both dashboards use these columns from gaim_pipeline_daily_snapshot:
- opportunities_created_ids (for DISTINCTCOUNT)
- amount_towards_plan (for pipeline $)
- stage_name (for Open/Won/Lost filtering)
- close_date (for time-based filtering)
- pipeline_entered_date (for created metrics)
- product_genus, product_group, product_family (segmentation)
- sales_market, sales_channel (segmentation)
- forecast_category_name (forecast category)
```

---

## 🚀 Forecasting Pipeline (How It Works)

### **Step 1: Historical Data Extraction**

```sql
-- Extract historical actuals from gaim_pipeline_daily_snapshot
SELECT 
    data_day as ds,                              -- Prophet requires 'ds' column
    SUM(amount_towards_plan) as y               -- Prophet requires 'y' column
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND xtxtype <> 'Cancel'
  AND data_day >= DATE_ADD(CURRENT_DATE(), -730)  -- 2 years history
GROUP BY data_day
ORDER BY data_day
```

### **Step 2: Feature Engineering**

```python
# Add seasonality flags
df['summer'] = df['ds'].dt.month.isin([6,7,8])
df['winter'] = df['ds'].dt.month.isin([12,1,2])
df['isweek1'] = df['ds'].dt.day <= 7

# Add ISO week information
df['ISOYear'] = df['ds'].dt.isocalendar().year
df['ISOWeek'] = df['ds'].dt.isocalendar().week
df['WeekYearKey'] = df['ISOYear'] * 100 + df['ISOWeek']
```

### **Step 3: Prophet Model Training**

```python
from prophet import Prophet

model = Prophet(
    interval_width=0.80,          # 80% confidence interval
    daily_seasonality=True,
    weekly_seasonality=True,
    yearly_seasonality=True
)

# Add custom seasonality
model.add_seasonality(name='summer', period=365.25, fourier_order=5)
model.add_seasonality(name='winter', period=365.25, fourier_order=5)

# Train model
model.fit(df[['ds', 'y']])
```

### **Step 4: Generate Forecasts**

```python
# Create future dataframe
future = model.make_future_dataframe(periods=180)  # 180 days ahead

# Generate predictions
forecast = model.predict(future)

# Extract scenarios
forecast['best_case'] = forecast['yhat_upper']      # Upper bound
forecast['most_likely'] = forecast['yhat']          # Point estimate
forecast['worst_case'] = forecast['yhat_lower']     # Lower bound
```

### **Step 5: Load to Power BI**

```python
# Combine actuals with forecasts
final_df = pd.merge(
    df[['ds', 'y']].rename(columns={'y': 'actuals'}),
    forecast[['ds', 'best_case', 'most_likely', 'worst_case']],
    on='ds',
    how='outer'
)

# Write to Databricks table or CSV for Power BI import
```

---

## 📊 Key DAX Measures

### **Scenario Switching Logic**

```dax
// Display correct scenario based on slicer selection
'Series Value' = 
VAR s = SELECTEDVALUE('Legend Series'[Series])
VAR IsForecast = LEFT(s, 8) = "Forecast"
VAR YearNum = VALUE(RIGHT(s, 4))

RETURN
IF(
    IsForecast,
    CALCULATE(SUM('forecast_prophet'[most_likely]), ...),
    CALCULATE(SUM('forecast_prophet'[actuals]), ...)
)
```

### **Actuals vs Forecast Cutoff**

```dax
// Show actuals only for completed weeks
'Running Totals Actuals' = 
VAR LastClosedWeekEnd = TODAY() - WEEKDAY(TODAY(), 2)  -- Previous Sunday
VAR CurrentAxisDate = MAX('forecast_prophet'[ds])

RETURN
IF(
    CurrentAxisDate > LastClosedWeekEnd,
    BLANK(),                                           -- Hide future actuals
    CALCULATE([2025actuals$], DATESYTD('forecast_prophet'[ds]))
)
```

---

## 🎯 SQL Queries for Backend Integration

### **Query 1: Extract Historical Data for Prophet**

```sql
-- Get 2 years of historical won pipeline for forecasting
SELECT 
    data_day as ds,
    SUM(amount_towards_plan) as y
FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
WHERE is_won = 'True'
  AND xtxtype <> 'Cancel'
  AND data_day >= DATE_ADD(CURRENT_DATE(), -730)
GROUP BY data_day
ORDER BY data_day
```

### **Query 2: Get Latest Forecast Results**

```sql
-- If forecast table is pre-built in Databricks
SELECT 
    ds as forecast_date,
    actuals,
    best_case,
    most_likely,
    worst_case
FROM datagroup_mdl.mdl_sales_analytics.forecast_prophet
WHERE ds >= CURRENT_DATE()
  AND ds <= DATE_ADD(CURRENT_DATE(), 180)
ORDER BY ds
```

### **Query 3: Segmented Forecast Data**

```sql
SELECT 
    ds as forecast_date,
    product,
    sales_market,
    pe_account_flag,
    actuals,
    best_case,
    most_likely,
    worst_case,
    avg_deal_size,
    number_of_opps
FROM datagroup_mdl.mdl_sales_analytics.forecast_prophet_2024
WHERE ds >= CURRENT_DATE()
ORDER BY ds, product, sales_market
```

---

## ✅ Implementation Checklist for Atlas Executive Insights

### **Backend Updates Needed:**

- [ ] Update `forecasting.py` to match Prophet configuration
  - Daily/weekly/yearly seasonality enabled
  - 80% confidence interval (interval_width=0.80)
  - Generate 3 scenarios (best/most likely/worst)
  
- [ ] Add seasonality features
  - Summer/winter flags
  - Week 1 of month flag
  - ISO week numbering
  
- [ ] Update forecast endpoint to return 3 scenarios
  - `/api/forecast?scenario=best_case`
  - `/api/forecast?scenario=most_likely`
  - `/api/forecast?scenario=worst_case`
  
- [ ] Add YTD/QTD running totals logic
  - DATESYTD equivalent in Python
  - DATESQTD equivalent in Python

### **Frontend Updates Needed:**

- [ ] Add scenario selector (Best/Most Likely/Worst)
- [ ] Update forecast chart to show confidence bounds
  - Area chart with shaded region between best/worst
  - Line chart for most likely
  - Toggle to show/hide confidence bands
  
- [ ] Add YTD/QTD toggle

### **Data Updates Needed:**

- [ ] Query historical data (2 years minimum)
- [ ] Pre-compute forecasts if Prophet is slow
- [ ] Cache forecast results (refresh weekly)

---

## 🎯 Key Takeaways

### **What ARR Forecast Teaches Us:**

1. **Use Prophet for time series** — Better than linear regression for business data with seasonality
2. **Show confidence bounds** — Don't just show point estimate; show range of possibilities
3. **Weekly aggregation** — More stable than daily for business metrics
4. **Seasonality matters** — Summer slowdowns, year-end spikes, week 1 patterns
5. **Segment forecasts** — Different products/markets behave differently

### **Integration with Performance Hub:**

✅ **Same source data** → Forecasts are grounded in actual KPI metrics  
✅ **Consistent definitions** → Won pipeline = same calculation  
✅ **Unified platform** → Both use Databricks + same semantic model

---

## 📊 Example: Atlas Executive Insights Forecast Chart

```
   │                                     ╱ Best Case ($3.2M)
$  │                            ╱╲     ╱
   │                       ╱╲  ╱  ╲   ╱
   │              ╱╲     ╱  ╲╱    ╲ ╱   ← Most Likely ($2.8M)
   │         ╱╲  ╱  ╲   ╱          ╲
   │    ╱╲  ╱  ╲╱    ╲ ╱            ╲ ╱
   │___╱__╲╱_________╲╱______________╲╱_ Worst Case ($2.3M)
   └───────────────────────────────────────────────────────────
     Jan  Feb  Mar  Apr │ May  Jun  Jul  Aug
                    TODAY
     ← Actuals →     ← Forecast (shaded confidence band) →
```

---

**Ready to implement Prophet forecasting in Atlas Executive Insights!** 🚀

See `UPDATE_SUMMARY.md` for complete architecture overview.
