# ARR Forecast Dashboard - Tables & Calculations Analysis

**Data Source**: Databricks  
**Catalog**: `hive_metastore`  
**Schema**: `mdl_sales_analytics`  
**Analysis Date**: May 12, 2026

---

## 📊 Overview

The ARR Forecast dashboard contains **29 tables** with 3 primary forecasting tables and supporting dimension/fact tables.

---

## 🔑 Key Tables

### 1. **forecast_prophet** (Main Forecast Table)
**Source**: `hive_metastore.mdl_sales_analytics.forecast_prophet`

#### Columns (48 total):
**Date/Time Dimensions:**
- `ds` - Date (primary date column)
- `year`, `month`, `week_number`, `quarter`
- `WeekStart`, `WeekNumber`, `ISOWeek`, `ISOYear`, `ISOWeekLabel`, `WeekYearKey`
- `RelWeekNumber` - Relative week number
- `MinDateThisYear` - Minimum date of current year
- `summer`, `winter`, `isweek1`, `IsQuarterEnd` - Seasonal flags

**Product/Market Segmentation:**
- `product` - Product name
- `Product_group` - Product grouping
- `sales_market` - Sales market/region
- `pe_account_flag` - Partner/end-user account flag

**Actual Performance Metrics:**
- `actuals` - Actual ARR closed (main actuals column)
- `mc_actuals` - Monte Carlo actuals
- `ARR YTD` - ARR Year-to-Date
- `avg_deal_size` - Average deal size
- `avg_sales_cycle` - Average sales cycle length
- `number_of_opps` - Number of opportunities
- `avg_opportunity_age` - Average opportunity age

**Pipeline & Marketing Metrics:**
- `all_created_arr` - All created ARR
- `total_partner_pipeline` - Total partner pipeline
- `marketing_generated_pipeline` - Marketing-generated pipeline
- `marketing_influenced_pipeline` - Marketing-influenced pipeline

**Sales Activity Metrics:**
- `headcount` - Sales headcount
- `avg_dials` - Average number of dials
- `avg_touches` - Average touches
- `avg_push_counter` - Average push count

**Forecast Scenarios:**
- `most_likely` - Most likely forecast (primary forecast)
- `worst_case` - Worst case scenario
- `best_case` - Best case scenario
- `adjusted most_likely` - Adjusted most likely forecast
- `Most Likely Amount` - Most likely amount
- `Most Likely Amount (Self Serve and Miradore Adjusted)` - Adjusted for self-serve
- `Worst Case Amount (Self Serve and Miradore Adjusted)`
- `Best Case Amount (Self Serve and Miradore Adjusted)`
- `SelfServeAdjustment` - Self-serve adjustment factor

**Helper Columns:**
- `Today?` - Flag indicating if date is today/past/future
- `Week` - Week label
- `xkey` - Cross-reference key

#### Key DAX Measures (21 total):

**1. Running Totals Actuals**
```dax
VAR LastClosedWeekEnd = TODAY() - WEEKDAY(TODAY(), 2)   -- previous Sunday
VAR CurrentAxisDate = MAX('forecast_prophet'[ds])
RETURN
IF(
    CurrentAxisDate > LastClosedWeekEnd,
    BLANK(),
    CALCULATE([2025actuals$], DATESYTD('forecast_prophet'[ds]))
)
```
**Purpose**: Calculates year-to-date running total of actuals, only showing up to last closed week

**2. 2025actuals$**
```dax
CALCULATE(SUM('forecast_prophet'[Actuals]))
```
**Purpose**: Sum of actual ARR

**3. 2025mostlikely$**
```dax
CALCULATE(SUM('forecast_prophet'[most_likely]))
```
**Purpose**: Sum of most likely forecast

**4. 2025bestcase$ / 2025worstcase$**
```dax
CALCULATE(SUM('forecast_prophet'[best_case/worst_case]))
```
**Purpose**: Sum of scenario forecasts

**5. Running Totals Most Likely**
```dax
CALCULATE(CALCULATE([2025mostlikely$], DATESYTD('forecast_prophet'[ds])))
```
**Purpose**: Year-to-date running total of forecast

**6. Running Totals Best Case (Quarterly)**
```dax
CALCULATE(CALCULATE([2025bestcase$], DATESQTD('forecast_prophet'[ds])))
```
**Purpose**: Quarter-to-date running total of best case

**7. adjusted most_likely past_date**
```dax
CALCULATE(
    sum(gaim_pipeline_daily_snapshot[amount_towards_plan]),
    'forecast_prophet'[Today?] = "Past Date"
)
```
**Purpose**: Links to actual pipeline data for past dates

**8. Actuals_AllYears**
```dax
CALCULATE(
    SUM('forecast_prophet'[ARR YTD]),
    REMOVEFILTERS('forecast_prophet'[year])
)
```
**Purpose**: Cross-year comparison removing year filter

**9. Forecast_AllYears**
```dax
VAR y = SELECTEDVALUE('forecast_prophet'[year])
RETURN
IF(
    y >= 2024 && y <= 2026,
    CALCULATE(SUM('forecast_prophet'[most_likely]), REMOVEFILTERS('forecast_prophet'[ISOYear])),
    BLANK()
)
```
**Purpose**: Multi-year forecast view (2024-2026)

**10. Series Value** (Complex)
- Handles both actuals and forecasts
- Works with year selection
- Respects ISO week boundaries
- Automatically blanks future weeks beyond last closed week

**11. Actuals As Of (Label)**
```dax
VAR StartDate = [Actuals Closed Week Start (Mon)]
VAR EndDate = [Actuals Closed Week End (Sun)]
VAR WeekNo = [Actuals Closed Week No]
RETURN "Week " & WeekNo & " " & FORMAT(StartDate, "mmm d") & " - " & FORMAT(EndDate, "mmm d")
```
**Purpose**: Creates "Week X Mon DD - Sun DD" labels

**12. Tooltip Week Label**
- Dynamically generates week labels for tooltips
- Handles both forecast_prophet and Dates Table contexts

---

### 2. **forecast_prophet_2024** (Historical 2024 Forecast)
**Source**: `hive_metastore.mdl_sales_analytics.forecast_prophet_2024`

#### Columns (33 total):
Similar structure to main forecast table but specific to 2024:
- Same date/time dimensions
- Same product/market segmentation
- Same metrics: actuals, avg_deal_size, avg_sales_cycle, etc.
- **Additional columns**:
  - `Running Total Actuals`
  - `Running Total Most Likely`
  - `Running Total Best Case`
  - `Running Total Worst Case`
  - `Difference` - Difference between forecast and actuals
  - `Percent Difference (%)` - Percentage difference

**Purpose**: Historical comparison and accuracy tracking for 2024 forecasts

---

### 3. **opportunity_scoring** (ML Scoring Table)
**Source**: Connected to same Databricks instance

#### Columns (92 total):
**Opportunity Identifiers:**
- `salesforce_opportunity_line_item_id`
- `opportunity_name`
- `owner_id`, `owner_name`
- `account_id_18_char`

**Product/Market:**
- `product`, `product_group`, `product_family`
- `sales_market`
- `market_emea`, `market_na`, `market_latam` - Regional flags
- `ucaas`, `itsg` - Product line flags

**Dates:**
- `pipeline_entered_date`
- `close_date`
- `data_day`, `data_day_date`
- `opportunity_age`

**Amounts & Pipeline:**
- `amount_towards_plan`
- `total_partner_pipeline`
- `marketing_generated_pipeline`
- `marketing_influenced_pipeline`

**Categorization:**
- `purchase_type`, `purchase_type_new`
- `stage_name`, `stage_group`
- `competitor`, `has_competitor`
- `dnb_sic_description`, `dnb_naics_description` - Industry codes
- `industry_services`, `industry_education`, `industry_healthcare`, etc. - Industry flags

**Sales Activity:**
- `dials`, `touches`, `push_counter`
- `fuel_mix`, `fuel_marketing`, `fuel_partner`, `fuel_ae`, `fuel_bdr`
- `comment_lenght` - Length of manager comments
- `number_of_free_months`

**Time Encoding (Cyclical Features for ML):**
- `week_sin`, `week_cos`
- `month_sin`, `month_cos`
- `qoy_sin`, `qoy_cos` - Quarter of year
- `moq_sin`, `moq_cos` - Month of quarter
- `week_of_quarter`, `month_of_quarter`, `quarter_of_year`

**Win Rate Features:**
- `win_rate_per_rep` - Rep-level win rate
- `win_rate_per_product_market` - Product-market win rate
- `win_rate_per_month` - Monthly win rate
- `win_rate_rep_x_pmgroup` - Interaction: rep × product-market

**Interaction Features:**
- `age_x_stage_group` - Opportunity age × stage
- `push_x_stage` - Push count × stage
- `new_x_partner` - New business × partner flag

**ARR Context:**
- `existing_arr_by_product` - Existing ARR for this product
- `existing_arr_total` - Total existing ARR
- `avg_deal_size_product`, `avg_deal_size_market`, `avg_deal_size_rep`
- `avg_deal_size_rpm` - Rep-product-market average
- `rep_x_market_dealsize`, `product_x_market_dealsize`, `product_x_rep_dealsize`
- `deal_size_to_rep_avg`, `deal_size_to_market_avg`

**ML Outputs:**
- `prob_won` - Probability of winning (0-1)
- `is_won` - Actual outcome (binary)
- `data_split` - Train/test split indicator
- `Probability Bins` - Binned probability ranges
- `deal_size_group` - Deal size categories

**Account Flags:**
- `pe_account_id`, `pe_account_flag` - Partner-engaged accounts

**Other:**
- `SalesforceURL` - Link to SFDC record

#### Key Measures (11 total):
*(Measures are defined in the TMDL but not yet extracted - would need to read the file)*

**Purpose**: Machine learning features and opportunity-level predictions used to generate the aggregate forecasts in `forecast_prophet`

---

### 4. **gaim_pipeline_daily_snapshot** (Pipeline Snapshot)
**Source**: `datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot`

#### Columns (112 total):
Comprehensive daily pipeline snapshot - already integrated in your forecasting module!

**Purpose**: Provides actual pipeline data that feeds into the forecast tables

---

### 5. **Dates Table** (Date Dimension)
**Columns (8):**
- Date dimension columns
- Standard date hierarchy
- 1 measure for date calculations

**Purpose**: Standard date dimension for time intelligence

---

### 6. **Refresh Week** (Metadata Table)
**Columns (3):**
- Tracks refresh/update weeks
- Used for data freshness indicators

---

## 🔄 Data Flow

```
┌─────────────────────────────────────┐
│ gaim_pipeline_daily_snapshot (112)  │ ← Actual closed deals
└──────────────┬──────────────────────┘
               │
               ↓ (aggregated by week/product/market)
┌──────────────────────────────────────┐
│  opportunity_scoring (92)             │ ← ML features & predictions
└──────────────┬───────────────────────┘
               │
               ↓ (Prophet forecast model)
┌──────────────────────────────────────┐
│  forecast_prophet (48) + 21 measures  │ ← Main forecast output
│  • most_likely                        │
│  • best_case / worst_case             │
│  • actuals (from pipeline)            │
└──────────────┬───────────────────────┘
               │
               ↓ (historical reference)
┌──────────────────────────────────────┐
│  forecast_prophet_2024 (33)           │ ← 2024 baseline
└───────────────────────────────────────┘
```

---

## 🎯 Key Calculations Explained

### 1. **Actuals Calculation**
- Source: `gaim_pipeline_daily_snapshot[amount_towards_plan]`
- Filtered by: `is_won = True`, past dates only
- Aggregated to weekly level

### 2. **Most Likely Forecast**
- Generated by Prophet ML model
- Factors: seasonality, trends, historical patterns, external variables
- Adjusted for self-serve and specific products (Miradore)

### 3. **Best/Worst Case Scenarios**
- Confidence interval around most likely
- Typically ±15-20% from most likely
- Represents uncertainty bounds

### 4. **Running Totals**
- Uses `DATESYTD()` for YTD calculations
- Uses `DATESQTD()` for QTD calculations
- Respects ISO week boundaries (Monday start)

### 5. **Week Boundaries**
- ISO weeks: Monday-Sunday
- "Last closed week" = Previous Sunday before today
- Actuals shown only up to last closed week

---

## 📈 Integration with Atlas Executive Insights

### Tables to Integrate:

1. **forecast_prophet** → Add to `data_fetcher.py`
   ```python
   query = f"""
   SELECT 
       ds as date,
       product,
       sales_market,
       SUM(actuals) as actual_arr,
       SUM(most_likely) as forecast_arr,
       SUM(best_case) as best_case_arr,
       SUM(worst_case) as worst_case_arr
   FROM hive_metastore.mdl_sales_analytics.forecast_prophet
   WHERE ds >= DATE_SUB(CURRENT_DATE(), 365)
   GROUP BY ds, product, sales_market
   ORDER BY ds
   ```

2. **opportunity_scoring** → For win probability features
   ```python
   query = f"""
   SELECT 
       close_date,
       product,
       sales_market,
       AVG(prob_won) as avg_win_probability,
       SUM(amount_towards_plan) as total_pipeline
   FROM hive_metastore.mdl_sales_analytics.opportunity_scoring
   WHERE close_date >= CURRENT_DATE()
   GROUP BY close_date, product, sales_market
   ```

### New API Endpoints Needed:

1. `GET /api/forecast/arr/prophet` - Get Prophet-based ARR forecast
2. `GET /api/forecast/arr/scenarios` - Get best/worst case scenarios  
3. `GET /api/forecast/arr/by-product` - ARR forecast by product
4. `GET /api/forecast/arr/by-market` - ARR forecast by market
5. `GET /api/forecast/win-probability` - Opportunity win probabilities
6. `GET /api/forecast/accuracy` - Forecast vs actuals comparison (using 2024 data)

---

## 📊 Dashboard Metrics Reference

| Metric | Source Column | Calculation |
|--------|---------------|-------------|
| ARR Actuals | `forecast_prophet[actuals]` | `SUM(actuals)` |
| ARR Forecast (Most Likely) | `forecast_prophet[most_likely]` | `SUM(most_likely)` |
| ARR Forecast (Best Case) | `forecast_prophet[best_case]` | `SUM(best_case)` |
| ARR Forecast (Worst Case) | `forecast_prophet[worst_case]` | `SUM(worst_case)` |
| YTD ARR | `forecast_prophet[ARR YTD]` | Running total with `DATESYTD()` |
| Average Deal Size | `forecast_prophet[avg_deal_size]` | Pre-aggregated from opps |
| Sales Cycle | `forecast_prophet[avg_sales_cycle]` | Pre-aggregated average |
| Win Probability | `opportunity_scoring[prob_won]` | ML model output (0-1) |
| Pipeline Value | `opportunity_scoring[amount_towards_plan]` | Open opp amounts |

---

## 🔍 Next Steps

1. **Integrate forecast_prophet table** into `data_fetcher.py`
2. **Add Prophet forecasting** to the existing forecasting service (already enabled!)
3. **Create scenario analysis endpoints** (best/worst case)
4. **Add product/market segmentation** to forecast API
5. **Implement win probability tracking** from opportunity_scoring
6. **Build forecast accuracy dashboard** using 2024 baseline data

---

**Generated**: May 12, 2026  
**Source**: ARR Forecast.pbip semantic model analysis
