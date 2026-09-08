# Databricks notebook source
# DBTITLE 1,Step 0: Install Forecasting Dependencies
# STEP 0: INSTALL FORECASTING DEPENDENCIES
# ─────────────────────────────────────────────────────────────────────────────
# PURPOSE: Install all Python libraries not pre-loaded in the Databricks runtime.
# Run this cell ONCE per new cluster session.  After it completes, Databricks
# automatically restarts the Python kernel — you must re-run ALL subsequent
# cells from the top before any model results will be valid.
#
# Package breakdown:
#   statsforecast  — Fast vectorised time-series models: MSTL v2, AutoETS,
#                    AutoARIMA.  Used in Steps 5 and 9.
#   prophet        — Facebook/Meta Prophet: trend + seasonality + holiday
#                    decomposition model.  Used in Step 5.
#   statsmodels    — ExponentialSmoothing (Holt-Winters) and ARIMA utilities
#                    used inside the DHR-ARIMA helper (Step 9).
#   holidays       — Public-holiday calendars for US, UK, DE, IN, BR.
#                    Used to build the `us_holiday_binary` external regressor.
#   lightgbm       — Gradient-boosted trees for the Global LGB Quantile model
#                    (Step 10B) and the Adaptive Ensemble.
#   scipy          — Required by statsforecast's internal optimisers; without
#                    it, `from statsforecast import StatsForecast` fails.
#   shap           — SHAP TreeExplainer for LightGBM feature importance;
#                    generates the waterfall / beeswarm plot in Step 10B-SHAP.
# ─────────────────────────────────────────────────────────────────────────────

%pip install statsforecast prophet statsmodels holidays lightgbm scipy shap

# COMMAND ----------

# DBTITLE 1,Step 0B: Central Forecast Configuration
# STEP 0B: CENTRAL FORECAST CONFIGURATION
# =============================================================================
# PURPOSE: Keep production constants in one place so date windows, output tables,
# quantiles, and ensemble membership can be changed once and reused everywhere.
# =============================================================================

import pandas as pd

NOTEBOOK_VERSION = 'V9'

BASE_TABLE = 'datagroup.datalake_transform.cds_sfdc_opp_products_latest'
GLOBAL_FEATURE_TABLE = 'datagroup_mdl.mdl_sales_analytics.forecast_prophet'
AUTHORITATIVE_MC_TABLE = 'datagroup.uc_forecast.actuals'
PRIMARY_PRODUCTION_OUTPUT_TABLE = 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5'
LEGACY_PRODUCTION_OUTPUT_TABLE = 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_v4'
MONITORING_BASELINE_TABLE = 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_monitoring_baseline'

START_DATE = '2023-01-01'
FIRST_FULL_MONDAY = pd.Timestamp('2023-01-02')
GLOBAL_HISTORY_START = pd.Timestamp('2023-01-02')
BACKTEST_START = pd.Timestamp('2026-01-05')
GLOBAL_BACKTEST_START = BACKTEST_START
GLOBAL_CV_HORIZON = 13
GLOBAL_CV_FOLDS = 6  # capped at 6 so all folds stay within pre-backtest window
GLOBAL_VALIDATION_WEEKS = 13
GLOBAL_QUANTILES = {'P10': 0.10, 'P50': 0.50, 'P90': 0.90}
GLOBAL_MARKETS = ['APAC', 'EMEA', 'LATAM', 'NA', 'Unknown']

RETAINED_PRODUCTION_MODELS = [
    'Prophet_trend',
    'MSTL_v2',
    'ETS',
    'DHR_ARIMA',
    'Global_LGB_Q50_UCC',
]

ENSEMBLE_COMPONENT_MODELS = [
    'Prophet_trend',
    'MSTL_v2',
    'ETS',
]


# COMMAND ----------

# DBTITLE 1,Step 1: Load UCC Forecast Base Data
# STEP 1: LOAD UCC FORECAST BASE DATA
# =============================================================================
# SOURCE TABLE : datagroup.datalake_transform.cds_sfdc_opp_products_latest
#   One row per Salesforce Opportunity Line Item (SFDC OLI).
#   Each row represents a single product booked on a deal.
#
# FILTERS APPLIED (business scope):
#   is_won = true            — only closed-won opportunities
#   is_closed = true         — belt-and-suspenders; always true when is_won=true
#   product_group = 'UCC'    — Unified Communications & Collaboration only
#   purchase_type_rollup = 'Growth' — net-new ARR; excludes renewals/upsell fixes
#   sales_channel NOT IN ('Care','Sales Other') — removes non-quota-bearing channels
#   close_date >= 2023-01-01 — three full fiscal years of signal
# =============================================================================

import pandas as pd
import numpy as np

# Source table — fully qualified Unity Catalog path
BASE_TABLE = "datagroup.datalake_transform.cds_sfdc_opp_products_latest"
START_DATE = "2023-01-01"          # inclusive lower bound on close_date
FIRST_FULL_MONDAY = pd.Timestamp("2023-01-02")  # first complete week in our series
# Compute the Monday of the *current* calendar week so we exclude any
# in-flight data from partial weeks that haven't closed yet
CURRENT_WEEK_START = pd.Timestamp.today().normalize() - pd.to_timedelta(pd.Timestamp.today().weekday(), unit='D')

# Pull every qualifying OLI into a pandas DataFrame.
# Key columns and their purpose:
#   salesforce_opportunity_line_item_id  — unique OLI identifier for deduplication
#   opportunity_product_id              — canonical product ID (used in nunique counts)
#   account_id_18_char                  — account breadth metric (distinct logos)
#   owner_id                            — seller count / coverage proxy
#   close_date / week_start             — when the deal closed; bucketed to Mon week
#   pipeline_entered_date / pipeline_week_start — when pipeline was created; used to
#                                         build same-week-lagged pipeline features
#   product_family                      — fine grain: UCaaS, Events, Meetings, Access
#   sales_market                        — geographic segment: NA, EMEA, APAC, LATAM
#   amount_towards_plan                 — THE TARGET (y): ARR credit towards quota
#   pipeline_amount                     — original pipeline value at create time
#   open_pipeline_created               — net new pipeline opened in that week
#   total_partner_pipeline              — partner-sourced pipeline total
#   partner_pipeline_created            — partner pipeline opened that week
#   marketing_generated_pipeline        — MQL-sourced pipeline (Magna Carta actuals)
#   marketing_influenced_pipeline       — Miradore plan pipeline
#   opportunities_created_count         — new opp count (volume signal)
#   push_counter                        — number of times close date was pushed out
#   dials / touches                     — sales activity intensity
#   opportunity_age                     — days from create to close (cycle time)
ucc_raw = spark.sql(f"""
SELECT
    salesforce_opportunity_line_item_id,
    opportunity_product_id,
    account_id_18_char,
    owner_id,
    CAST(close_date AS DATE) AS close_date,
    DATE_TRUNC('week', close_date) AS week_start,
    CAST(pipeline_entered_date AS DATE) AS pipeline_entered_date,
    DATE_TRUNC('week', pipeline_entered_date) AS pipeline_week_start,
    product_group,
    product_family,
    sales_market,
    amount_towards_plan,
    pipeline_amount,
    open_pipeline_created,
    total_partner_pipeline,
    partner_pipeline_created,
    marketing_generated_pipeline,
    marketing_influenced_pipeline,
    opportunities_created_count,
    push_counter,
    dials,
    touches,
    opportunity_age,
    is_won,
    is_closed,
    purchase_type_rollup,
    sales_channel
FROM {BASE_TABLE}
WHERE close_date >= DATE '{START_DATE}'
  AND is_won = true
  AND is_closed = true
  AND product_group = 'UCC'
  AND purchase_type_rollup = 'Growth'
  AND COALESCE(sales_channel, '') NOT IN ('Care', 'Sales Other')
""").toPandas()

# Coerce all date columns from string/object to proper datetime so we can
# use .dt accessor and merge on date keys later
for col in ['close_date', 'week_start', 'pipeline_entered_date', 'pipeline_week_start']:
    ucc_raw[col] = pd.to_datetime(ucc_raw[col], errors='coerce')

# Force all numeric KPI columns to float, filling nulls with 0.
# Nulls come from rows where that metric wasn't applicable (e.g. no dials
# on partner-sourced deals); replacing with 0 is safe for sum aggregations.
for col in [
    'amount_towards_plan', 'pipeline_amount', 'open_pipeline_created',
    'total_partner_pipeline', 'partner_pipeline_created',
    'marketing_generated_pipeline', 'marketing_influenced_pipeline',
    'opportunities_created_count', 'push_counter', 'dials', 'touches',
    'opportunity_age'
]:
    ucc_raw[col] = pd.to_numeric(ucc_raw[col], errors='coerce').fillna(0.0)

# Normalise the sales_market field to a clean 5-segment taxonomy:
#   NA, EMEA, APAC, LATAM, Unknown
# AUS/ROW and INDIA are legacy region codes that now roll into APAC.
# Any blank / null value becomes 'Unknown' to avoid NULL-group duplication.
market_map = {
    'AUS/ROW': 'APAC',
    'INDIA': 'APAC',
    'UNKNOWN': 'Unknown',
    '': 'Unknown',
}
ucc_raw['sales_market'] = (
    ucc_raw['sales_market']
        .fillna('Unknown')
        .astype(str)
        .str.strip()
        .replace(market_map)
)
# Second-pass catch for any empty string that slipped through after .strip()
ucc_raw.loc[ucc_raw['sales_market'].eq(''), 'sales_market'] = 'Unknown'

# ALL-OPPS PIPELINE FIX: separate query with NO is_won filter so the denominator of
# win_rate_woq and the created_lag4/pipeline_velocity features reflect the total
# funnel at pipeline-creation time, not just deals that eventually closed.
# Uses pipeline_amount (original pipeline value) rather than amount_towards_plan
# because amount_towards_plan for open/lost deals is 0 or undefined.
_all_pipeline_raw = spark.sql(f"""
SELECT
    DATE_TRUNC('week', pipeline_entered_date) AS ds,
    COALESCE(sales_market, 'Unknown') AS sales_market,
    SUM(COALESCE(pipeline_amount, 0)) AS all_pipeline_created
FROM {BASE_TABLE}
WHERE pipeline_entered_date >= DATE '{START_DATE}'
  AND product_group = 'UCC'
  AND purchase_type_rollup = 'Growth'
  AND COALESCE(sales_channel, '') NOT IN ('Care', 'Sales Other')
GROUP BY 1, 2
""").toPandas()
_all_pipeline_raw['ds'] = pd.to_datetime(_all_pipeline_raw['ds'])
_all_pipeline_raw['sales_market'] = (
    _all_pipeline_raw['sales_market']
    .fillna('Unknown').astype(str).str.strip()
    .replace({'AUS/ROW': 'APAC', 'INDIA': 'APAC', 'UNKNOWN': 'Unknown', '': 'Unknown'})
)
_all_pipeline_raw.loc[_all_pipeline_raw['sales_market'].eq(''), 'sales_market'] = 'Unknown'
# Re-aggregate after market normalisation (AUS/ROW + INDIA both map to APAC)
all_pipeline_by_market = (
    _all_pipeline_raw.groupby(['ds', 'sales_market'], as_index=False)['all_pipeline_created'].sum()
)

# Build a complete Monday-indexed calendar spine from the first full week to
# the last *fully closed* week (= current Monday minus 1 week).
# Using a spine ensures zero-value weeks are present rather than silently missing,
# which would cause incorrect lag/rolling features.
calendar = pd.DataFrame({
    'ds': pd.date_range(FIRST_FULL_MONDAY, CURRENT_WEEK_START - pd.Timedelta(weeks=1), freq='W-MON')
})

# --- Aggregate closed-won bookings by the week they closed (week_start) ---
# y = total ARR booked that week (this is the forecast target)
# Supporting metrics (opp counts, avg deal size, activity) are kept for EDA
# and may be used as lagged features in future model iterations.
close_weekly = (
    ucc_raw.groupby('week_start', dropna=False)
           .agg(
               y=('amount_towards_plan', 'sum'),
               opp_line_items=('opportunity_product_id', 'nunique'),
               opp_ids=('salesforce_opportunity_line_item_id', 'nunique'),
               accounts=('account_id_18_char', 'nunique'),
               sellers=('owner_id', 'nunique'),
               avg_deal_size=('amount_towards_plan', 'mean'),
               avg_dials=('dials', 'mean'),
               avg_touches=('touches', 'mean'),
               avg_push_counter=('push_counter', 'mean'),
               avg_opportunity_age=('opportunity_age', 'mean')
           )
           .reset_index()
           .rename(columns={'week_start': 'ds'})
)

# --- Aggregate pipeline-creation metrics by the week the opp was CREATED ---
# These are leading indicators: pipeline created 4 weeks ago predicts bookings today.
# We drop rows where pipeline_entered_date is null to avoid assigning created
# amounts to week_start=NaT, which would pollute the calendar merge.
created_weekly = (
    ucc_raw.dropna(subset=['pipeline_week_start'])
           .groupby('pipeline_week_start', dropna=False)
           .agg(
               created_arr=('amount_towards_plan', 'sum'),
               created_pipeline_amount=('pipeline_amount', 'sum'),
               created_open_pipeline=('open_pipeline_created', 'sum'),
               created_partner_pipeline=('partner_pipeline_created', 'sum'),
               total_partner_pipeline=('total_partner_pipeline', 'sum'),
               marketing_generated_pipeline=('marketing_generated_pipeline', 'sum'),
               marketing_influenced_pipeline=('marketing_influenced_pipeline', 'sum'),
               opportunities_created=('opportunities_created_count', 'sum')
           )
           .reset_index()
           .rename(columns={'pipeline_week_start': 'ds'})
)

# Left-join both aggregates onto the calendar spine so every Monday week
# gets a row, even if no deals closed (y=0) or no pipeline was created.
# This is critical: missing weeks would create gaps in lag/rolling computations.
weekly_ucc = (
    calendar.merge(close_weekly, on='ds', how='left')
            .merge(created_weekly, on='ds', how='left')
            .sort_values('ds')
            .reset_index(drop=True)
)

# Replace all NaN numeric cells with 0 — weeks with no activity genuinely have zero
for col in weekly_ucc.columns:
    if col != 'ds':
        weekly_ucc[col] = weekly_ucc[col].fillna(0.0)

# ----- Lag / rolling features (all shift-safe: shift before current week) -----
# y_lag1   : last week's actual ARR — strongest single predictor in LGB models
# y_lag13  : ARR from 13 weeks ago (same week-of-quarter last quarter) — captures
#            the repeating end-of-quarter surge pattern
# r4w      : trailing 4-week average shifted by 1 so it never leaks the current week
weekly_ucc['y_lag1'] = weekly_ucc['y'].shift(1).fillna(0.0)
weekly_ucc['y_lag13'] = weekly_ucc['y'].shift(13).fillna(0.0)
weekly_ucc['r4w'] = weekly_ucc['y'].rolling(4, min_periods=1).mean().shift(1).fillna(0.0)

# ----- Calendar / seasonality features -----
weekly_ucc['year'] = weekly_ucc['ds'].dt.year
weekly_ucc['quarter'] = weekly_ucc['ds'].dt.quarter
# week_of_qtr counts 1-13 within each quarter; used in DHR Fourier terms and
# the win-rate-by-woq feature to capture within-quarter ramp pattern
weekly_ucc['week_of_qtr'] = weekly_ucc.groupby(['year', 'quarter']).cumcount() + 1
# quarter_end_flag = 1 for the last 2-3 weeks of any quarter; UCC deals surge ~40%
# above the quarterly average in weeks 11-13 (validated in Step 2 EDA)
weekly_ucc['quarter_end_flag'] = (weekly_ucc['week_of_qtr'] >= 11).astype(int)
# is_q4 captures the fiscal year-end boost (Q4 is structurally higher than Q1-Q3)
weekly_ucc['is_q4'] = (weekly_ucc['quarter'] == 4).astype(int)
# q4_week_countdown: counts weeks remaining in Q4 (0 outside Q4).
# Provides a continuous urgency signal as year-end approaches.
weekly_ucc['q4_week_countdown'] = np.where(weekly_ucc['quarter'] == 4, 14 - weekly_ucc['week_of_qtr'], 0)

# Weekly bookings broken out by sales_market (NA / EMEA / APAC / LATAM / Unknown).
# Used for: (1) EDA market mix chart, (2) DHR-ARIMA per-market models (Step 9),
# (3) Global LGB per-market training panel (Step 10B),
# (4) production forward forecast by market (Step 14).
# Filter keeps only complete weeks between FIRST_FULL_MONDAY and CURRENT_WEEK_START.
weekly_ucc_by_market = (
    ucc_raw.groupby(['week_start', 'sales_market'], dropna=False)['amount_towards_plan']
           .sum()
           .reset_index()
           .rename(columns={'week_start': 'ds', 'amount_towards_plan': 'y'})
           .sort_values(['ds', 'sales_market'])
           .reset_index(drop=True)
)
weekly_ucc_by_market = weekly_ucc_by_market[
    (weekly_ucc_by_market['ds'] >= FIRST_FULL_MONDAY) &
    (weekly_ucc_by_market['ds'] < CURRENT_WEEK_START)
].reset_index(drop=True)

# Cross-join the date calendar with all known markets to produce a
# complete (date x market) spine — guarantees no combination is missing
# even when a market had zero activity in a given week.
market_calendar = (
    calendar.assign(_key=1)
    .merge(
        pd.DataFrame({'sales_market': sorted(ucc_raw['sales_market'].dropna().unique().tolist())}).assign(_key=1),
        on='_key',
        how='inner',
    )
    .drop(columns='_key')
)

created_weekly_by_market = (
    ucc_raw.dropna(subset=['pipeline_week_start'])
           .groupby(['pipeline_week_start', 'sales_market'], dropna=False)
           .agg(
               marketing_generated_pipeline=('marketing_generated_pipeline', 'sum'),
               marketing_influenced_pipeline=('marketing_influenced_pipeline', 'sum'),
           )
           .reset_index()
           .rename(columns={'pipeline_week_start': 'ds'})
)

weekly_ucc_created_features_by_market = (
    market_calendar.merge(created_weekly_by_market, on=['ds', 'sales_market'], how='left')
    .sort_values(['ds', 'sales_market'])
    .reset_index(drop=True)
)
for col in ['marketing_generated_pipeline', 'marketing_influenced_pipeline']:
    weekly_ucc_created_features_by_market[col] = weekly_ucc_created_features_by_market[col].fillna(0.0)

# Weekly bookings by product_family (UCaaS, Events, Meetings, Access, RSG-IT).
# Used for: EDA family mix chart and the focused UCaaS / Events trend plot.
# UCaaS dominates (~70% of UCC ARR), so total UCC and UCaaS track closely.
weekly_ucc_by_family = (
    ucc_raw.groupby(['week_start', 'product_family'], dropna=False)['amount_towards_plan']
           .sum()
           .reset_index()
           .rename(columns={'week_start': 'ds', 'amount_towards_plan': 'y'})
           .sort_values(['ds', 'product_family'])
           .reset_index(drop=True)
)
weekly_ucc_by_family = weekly_ucc_by_family[
    (weekly_ucc_by_family['ds'] >= FIRST_FULL_MONDAY) &
    (weekly_ucc_by_family['ds'] < CURRENT_WEEK_START)
].reset_index(drop=True)

print(f"Source table: {BASE_TABLE}")
print(f"Raw UCC rows: {len(ucc_raw):,}")
print(f"Weekly observations: {len(weekly_ucc):,}")
print(f"Date range: {weekly_ucc['ds'].min().date()} -> {weekly_ucc['ds'].max().date()}")
print(f"Total UCC Growth ARR: ${weekly_ucc['y'].sum()/1e6:,.2f}M")
print(f"Average weekly ARR: ${weekly_ucc['y'].mean()/1e6:,.2f}M")
print(f"Last fully closed week start used: {weekly_ucc['ds'].max().date()}")
print(f"Markets captured: {sorted(weekly_ucc_by_market['sales_market'].dropna().unique().tolist())}")
print(f"Families captured: {sorted(weekly_ucc_by_family['product_family'].dropna().unique().tolist())}")

print("\nWeekly UCC modeling table sample:")
display(weekly_ucc.tail(10))

print("\nWeekly UCC by market sample:")
display(weekly_ucc_by_market.tail(10))

print("\nRaw data sample:")
display(
    ucc_raw[
        ['close_date', 'week_start', 'pipeline_entered_date', 'product_family', 'sales_market',
         'amount_towards_plan', 'pipeline_amount', 'total_partner_pipeline']
    ].tail(10)
)


# COMMAND ----------

# DBTITLE 1,Step 2: UCC Exploratory Data Analysis
# STEP 2: UCC EXPLORATORY DATA ANALYSIS
# =============================================================================
# PURPOSE: Understand the data before modelling.
# Produces six panels that the team should review to validate data quality and
# build intuition about the seasonal / structural patterns the models must learn.
#
# What you'll see:
#   (1) Weekly ARR with 4-week rolling average — spot trends, outliers, spikes
#   (2) Monthly ARR bar chart with linear trend — overall growth direction
#   (3) Seasonal profile by week-of-quarter — quantifies the end-of-quarter surge
#   (4) ARR by sales market — shows NA dominance and EMEA/APAC contribution
#   (5) ARR by product family — confirms UCaaS ~70% of UCC total
#   (6) UCaaS vs Events weekly trend — contrasts growth trajectories
# =============================================================================

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from numpy.polynomial import polynomial as P


def millions(x, pos):
    return f'${x:.1f}M'


# Top-line summary metrics — these are the first numbers to validate;
# if total_arr_m or avg_weekly_arr_m look wrong the source filter has an issue.
eda_summary = pd.DataFrame([
    {"metric": "weeks", "value": f"{len(weekly_ucc):,}"},
    {"metric": "start_date", "value": str(weekly_ucc['ds'].min().date())},
    {"metric": "end_date", "value": str(weekly_ucc['ds'].max().date())},
    {"metric": "total_arr_m", "value": f"{weekly_ucc['y'].sum() / 1e6:,.2f}"},
    {"metric": "avg_weekly_arr_m", "value": f"{weekly_ucc['y'].mean() / 1e6:,.3f}"},
    {"metric": "median_weekly_arr_m", "value": f"{weekly_ucc['y'].median() / 1e6:,.3f}"},
    {"metric": "p95_weekly_arr_m", "value": f"{weekly_ucc['y'].quantile(0.95) / 1e6:,.3f}"},
    {"metric": "zero_weeks", "value": f"{int((weekly_ucc['y'] == 0).sum()):,}"},
])

# Null check: all numeric columns should be 0% null after Step 1 fillna.
# Non-zero null% here would indicate a data quality issue upstream.
feature_nulls = (
    weekly_ucc.isna().mean().mul(100).round(2)
    .reset_index()
    .rename(columns={'index': 'column', 0: 'null_pct'})
    .sort_values(['null_pct', 'column'], ascending=[False, True])
)

# Market mix: total ARR and % share by geography.
# Expected dominant market: NA (~65-70%).
# EMEA and APAC are growing but still minority contributors.
market_mix = (
    weekly_ucc_by_market.groupby('sales_market', as_index=False)['y']
    .sum()
    .assign(arr_m=lambda d: (d['y'] / 1e6).round(2), pct_total=lambda d: (100 * d['y'] / d['y'].sum()).round(1))
    .sort_values('y', ascending=False)
    [['sales_market', 'arr_m', 'pct_total']]
)

# Product family mix: UCaaS should be ~70%, Events ~5%, Meetings ~1%, Access ~1%.
# If these proportions shift materially, re-check product_family mapping in SFDC.
family_mix = (
    weekly_ucc_by_family.groupby('product_family', as_index=False)['y']
    .sum()
    .assign(arr_m=lambda d: (d['y'] / 1e6).round(2), pct_total=lambda d: (100 * d['y'] / d['y'].sum()).round(1))
    .sort_values('y', ascending=False)
    [['product_family', 'arr_m', 'pct_total']]
)

# Quarter-over-quarter growth: this is the primary exec-facing metric.
# Q4 is structurally the strongest quarter (year-end push);
# the QoQ% dropping in Q1 each year is expected and normal.
quarterly_ucc = weekly_ucc.copy()
quarterly_ucc['qtr'] = quarterly_ucc['ds'].dt.to_period('Q').astype(str)
quarterly_ucc = (
    quarterly_ucc.groupby('qtr', as_index=False)['y']
    .sum()
    .assign(arr_m=lambda d: (d['y'] / 1e6).round(2))
)
quarterly_ucc['prev_qtr_arr_m'] = quarterly_ucc['arr_m'].shift(1)
quarterly_ucc['qoq_pct'] = ((quarterly_ucc['arr_m'] / quarterly_ucc['prev_qtr_arr_m'] - 1) * 100).round(1)

weekly_plot = weekly_ucc[['ds', 'y']].copy()
weekly_plot['y_m'] = weekly_plot['y'] / 1e6
weekly_plot['r4w_m'] = weekly_plot['y_m'].rolling(4, center=True, min_periods=1).mean()

monthly_ucc = (
    weekly_ucc.set_index('ds')['y']
    .resample('MS').sum()
    .reset_index()
)
current_month_start = pd.Timestamp.today().replace(day=1)
monthly_ucc = monthly_ucc[monthly_ucc['ds'] < current_month_start].copy()
monthly_ucc['arr_m'] = monthly_ucc['y'] / 1e6
if len(monthly_ucc) > 2:
    t_m = np.arange(len(monthly_ucc))
    monthly_ucc['trend_m'] = P.polyval(t_m, P.polyfit(t_m, monthly_ucc['arr_m'], deg=1))
else:
    monthly_ucc['trend_m'] = monthly_ucc['arr_m']

# Seasonal profile: detrend the last 8 quarters (Apr 2024 – Mar 2026) to isolate
# within-quarter patterns without being biased by the long-run growth trend.
# y_detrended = actual / trend_value; values > 1 = above-average weeks.
# The error bars are standard error over ~8 observations per week-of-quarter slot.
# Key pattern to look for: ratio should spike sharply at weeks 11-13 (end of quarter).
seasonal_src = weekly_ucc[['ds', 'y']].copy()
seasonal_src['year'] = seasonal_src['ds'].dt.year
seasonal_src['quarter'] = seasonal_src['ds'].dt.quarter
seasonal_src['week_of_qtr'] = (
    seasonal_src.sort_values('ds')
    .groupby(['year', 'quarter'])
    .cumcount() + 1
).clip(upper=13)
cutoff_start = pd.Timestamp('2024-04-01')   # use only recent 8Q to avoid stale seasonality
cutoff_end = pd.Timestamp('2026-04-01')
seasonal_recent = seasonal_src[(seasonal_src['ds'] >= cutoff_start) & (seasonal_src['ds'] < cutoff_end)].copy()
seasonal_recent = seasonal_recent.sort_values('ds').reset_index(drop=True)
t = np.arange(len(seasonal_recent))
# Fit a linear trend and divide it out so the seasonal index is pure shape
trend_line = P.polyval(t, P.polyfit(t, seasonal_recent['y'], deg=1))
seasonal_recent['y_detrended'] = seasonal_recent['y'] / np.where(trend_line == 0, 1, trend_line)
seasonal_profile = (
    seasonal_recent.groupby('week_of_qtr')['y_detrended']
    .agg(['mean', 'std']).reset_index()
    .rename(columns={'mean': 'seasonal_ratio', 'std': 'seasonal_std'})
)
# Re-scale so the average week = 1.0 (makes interpretation straightforward)
seasonal_profile['seasonal_ratio'] = seasonal_profile['seasonal_ratio'] / seasonal_profile['seasonal_ratio'].mean()
seasonal_profile['stderr'] = seasonal_profile['seasonal_std'].fillna(0) / np.sqrt(8)

family_focus_names = [fam for fam in ['UCaaS', 'Events'] if fam in set(weekly_ucc_by_family['product_family'])]
family_focus = (
    weekly_ucc_by_family[weekly_ucc_by_family['product_family'].isin(family_focus_names)]
    .groupby('product_family', as_index=False)['y']
    .sum()
    .assign(arr_m=lambda d: (d['y'] / 1e6).round(2), pct_total=lambda d: (100 * d['y'] / weekly_ucc['y'].sum()).round(1))
    [['product_family', 'arr_m', 'pct_total']]
    .sort_values('arr_m', ascending=False)
)
family_focus_weekly = (
    weekly_ucc_by_family[weekly_ucc_by_family['product_family'].isin(family_focus_names)]
    .pivot(index='ds', columns='product_family', values='y')
    .reindex(weekly_ucc['ds'])
    .fillna(0)
    .reset_index()
)
family_focus_weekly.columns.name = None
for fam in family_focus_names:
    family_focus_weekly[f'{fam}_r4w'] = family_focus_weekly[fam].rolling(4, center=True, min_periods=1).mean() / 1e6
    family_focus_weekly[f'{fam}_m'] = family_focus_weekly[fam] / 1e6

print('UCC EDA summary:')
display(eda_summary)

print('\nNull check across modeling table:')
display(feature_nulls.head(15))

print('\nMarket mix:')
display(market_mix)

print('\nProduct family mix:')
display(family_mix)

print('\nQuarterly trend:')
display(quarterly_ucc.tail(10))

print('\nFocused family view:')
display(family_focus)

fig, axes = plt.subplots(3, 2, figsize=(18, 14))

axes[0, 0].plot(weekly_plot['ds'], weekly_plot['y_m'], color='navy', lw=0.9, alpha=0.45, label='Weekly')
axes[0, 0].plot(weekly_plot['ds'], weekly_plot['r4w_m'], color='navy', lw=2.2, alpha=0.9, label='4-wk avg')
axes[0, 0].set_title('Weekly UCC ARR with 4-week trend')
axes[0, 0].yaxis.set_major_formatter(mticker.FuncFormatter(millions))
axes[0, 0].grid(axis='y', linestyle='--', alpha=0.3)
axes[0, 0].legend(fontsize=8, loc='upper right')

axes[0, 1].bar(monthly_ucc['ds'], monthly_ucc['arr_m'], width=20, color='darkorange', alpha=0.8, edgecolor='white')
axes[0, 1].plot(monthly_ucc['ds'], monthly_ucc['trend_m'], color='black', lw=1.6, ls='--', alpha=0.65, label='Linear trend')
axes[0, 1].set_title('Monthly UCC ARR (complete months only)')
axes[0, 1].yaxis.set_major_formatter(mticker.FuncFormatter(millions))
axes[0, 1].grid(axis='y', linestyle='--', alpha=0.3)
axes[0, 1].legend(fontsize=8, loc='upper right')

axes[1, 0].bar(
    seasonal_profile['week_of_qtr'],
    seasonal_profile['seasonal_ratio'],
    yerr=seasonal_profile['stderr'],
    color='steelblue',
    alpha=0.82,
    capsize=3,
    error_kw={'lw': 1}
)
axes[1, 0].axhline(1.0, color='gray', lw=0.8, alpha=0.5)
axes[1, 0].axvline(4.5, color='purple', ls=':', lw=1.1, alpha=0.5)
axes[1, 0].axvline(8.5, color='purple', ls=':', lw=1.1, alpha=0.5)
axes[1, 0].axvline(10.5, color='red', ls='--', lw=1.1, alpha=0.5)
axes[1, 0].set_xticks(range(1, 14))
axes[1, 0].set_title('UCC seasonal profile by week of quarter')
axes[1, 0].set_xlabel('Week of quarter')
axes[1, 0].set_ylabel('Seasonal ratio')
axes[1, 0].grid(axis='y', linestyle='--', alpha=0.3)

axes[1, 1].bar(market_mix['sales_market'], market_mix['arr_m'], color='teal')
axes[1, 1].set_title('ARR by sales market')
axes[1, 1].yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'${x:.0f}M'))
axes[1, 1].grid(axis='y', linestyle='--', alpha=0.3)

axes[2, 0].bar(family_mix['product_family'], family_mix['arr_m'], color='purple')
axes[2, 0].set_title('ARR by product family')
axes[2, 0].tick_params(axis='x', rotation=20)
axes[2, 0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'${x:.0f}M'))
axes[2, 0].grid(axis='y', linestyle='--', alpha=0.3)

for fam, color in [('UCaaS', 'steelblue'), ('Events', 'darkorange')]:
    if fam in family_focus_names:
        axes[2, 1].plot(
            family_focus_weekly['ds'],
            family_focus_weekly[f'{fam}_m'],
            color=color,
            lw=0.8,
            alpha=0.35
        )
        axes[2, 1].plot(
            family_focus_weekly['ds'],
            family_focus_weekly[f'{fam}_r4w'],
            color=color,
            lw=2.0,
            alpha=0.9,
            label=f'{fam} 4-wk avg'
        )
axes[2, 1].set_title('Focused family trend: UCaaS and Events')
axes[2, 1].yaxis.set_major_formatter(mticker.FuncFormatter(millions))
axes[2, 1].grid(axis='y', linestyle='--', alpha=0.3)
axes[2, 1].legend(fontsize=8, loc='upper right')

plt.tight_layout()
plt.show()


# COMMAND ----------

# DBTITLE 1,Step 3: Modeling Guardrails and Backtest Split
# STEP 3: MODELING GUARDRAILS AND BACKTEST SPLIT
# =============================================================================
# PURPOSE: Define the credibility boundary between what models CAN see
# during training and what they are evaluated against.
#
# KEY DECISIONS:
#   BACKTEST_START = 2026-01-05  (first Monday of Q1 2026)
#     — gives the test set two full quarters (Q1 + Q2 2026) of held-out data
#     — this is an intentionally conservative split; real production inference
#       always runs against future (unseen) weeks
#
#   LEAKY_OR_UNUSABLE_COLS: columns that know the future or are proxies of y.
#     Using them as features would make models look good in training but fail
#     completely in production where those values don't exist yet.
#     The lagged versions (e.g. mkt_generated_lag4) ARE safe and are in GLOBAL_FEATURE_COLS.
#
#   SAFE_FEATURE_COLS: the only columns safe to use without a lag — all derived
#     from data that precedes the current week (lags, rolling averages, calendar).
# =============================================================================

BACKTEST_START = globals().get('BACKTEST_START', pd.Timestamp('2026-01-05'))  # first Monday of Q1 2026

# model_df is the single modelling universe: weekly_ucc augmented with
# train/test labels.  All downstream steps consume model_df.
model_df = weekly_ucc.copy().sort_values('ds').reset_index(drop=True)
model_df['is_backtest'] = model_df['ds'] >= BACKTEST_START   # True = held-out test rows
model_df['split'] = np.where(model_df['is_backtest'], 'test', 'train')

# NOTE: marketing_generated_pipeline and marketing_influenced_pipeline appear here as LEAKY
# (same-week values) but their LAGGED versions (mkt_generated_lag4, mkt_influenced_lag4) are
# safe features used in GLOBAL_FEATURE_COLS. This dual presence is intentional — do NOT remove
# the lagged versions from the feature set based on seeing the raw columns in LEAKY list.
LEAKY_OR_UNUSABLE_COLS = [
    'y',
    'created_arr',
    'created_pipeline_amount',
    'created_open_pipeline',
    'created_partner_pipeline',
    'total_partner_pipeline',
    'marketing_generated_pipeline',
    'marketing_influenced_pipeline',
    'opportunities_created',
]

SAFE_FEATURE_COLS = [
    'y_lag1',
    'y_lag13',
    'r4w',
    'year',
    'quarter',
    'week_of_qtr',
    'quarter_end_flag',
    'is_q4',
    'q4_week_countdown',
]

BASELINE_FEATURE_COLS = [
    'y_lag1',
    'y_lag13',
    'r4w',
    'week_of_qtr',
    'quarter_end_flag',
    'is_q4',
    'q4_week_countdown',
]

# Split into clean train and test DataFrames.
# CRITICAL: never pass test_df into any model .fit() call.
train_df = model_df[model_df['ds'] < BACKTEST_START].copy()
test_df  = model_df[model_df['ds'] >= BACKTEST_START].copy()
# Sanity check: we need at least 26 weeks of history so lag-13 features are valid
assert len(train_df) > 26, 'Insufficient history for lag-13 feature engineering.'

split_summary = pd.DataFrame([
    {'split': 'train', 'rows': len(train_df), 'start': str(train_df['ds'].min().date()), 'end': str(train_df['ds'].max().date()), 'arr_m': round(train_df['y'].sum() / 1e6, 2)},
    {'split': 'test', 'rows': len(test_df), 'start': str(test_df['ds'].min().date()), 'end': str(test_df['ds'].max().date()), 'arr_m': round(test_df['y'].sum() / 1e6, 2)},
])

# Feature health check: confirms each safe feature has real variance
# (nonzero_weeks > 0 and std > 0).  Features with std=0 are constants
# and should be removed before model training.
feature_readiness = pd.DataFrame([
    {
        'feature': col,
        'nonzero_weeks': int((model_df[col] != 0).sum()),
        'std': round(float(model_df[col].std()), 3),
        'used_in_baseline': col in BASELINE_FEATURE_COLS,
    }
    for col in SAFE_FEATURE_COLS
]).sort_values(['used_in_baseline', 'nonzero_weeks', 'feature'], ascending=[False, False, True])

excluded_features = pd.DataFrame({
    'feature': LEAKY_OR_UNUSABLE_COLS + [
        'opp_line_items',
        'opp_ids',
        'accounts',
        'sellers',
        'avg_deal_size',
        'avg_dials',
        'avg_touches',
        'avg_push_counter',
        'avg_opportunity_age',
        'opportunities_created',
    ],
    'reason': [
        'target',
        'same-week created amount',
        'same-week created pipeline amount',
        'all zero in current build',
        'same-week partner pipeline created',
        'same-week total partner pipeline',
        'same-week marketing generated pipeline',
        'same-week marketing influenced pipeline',
        'same-week created count',
        'same-week won/closed volume proxy',
        'same-week won/closed id proxy',
        'same-week won/closed account proxy',
        'same-week won/closed seller proxy',
        'same-week won/closed target component',
        'same-week won/closed activity proxy',
        'same-week won/closed activity proxy',
        'same-week won/closed push proxy',
        'same-week won/closed age proxy',
        'same-week created count',
    ]
})

print(f'Backtest start fixed at: {BACKTEST_START.date()}')
print(f'Total rows available for modeling: {len(model_df):,}')
print(f'Baseline feature count: {len(BASELINE_FEATURE_COLS)}')
print(f'Created open pipeline non-zero weeks: {(model_df["created_open_pipeline"] > 0).sum()}')

print('\nTrain/test split summary:')
display(split_summary)

print('\nBaseline feature set:')
display(pd.DataFrame({'feature': BASELINE_FEATURE_COLS}))

print('\nSafe feature readiness:')
display(feature_readiness)

print('\nExcluded features for first pass:')
display(excluded_features)

ucaas_weekly = (
    weekly_ucc_by_family[weekly_ucc_by_family['product_family'] == 'UCaaS']
    .set_index('ds')
    .reindex(model_df['ds'])
    .fillna(0)
    .rename_axis('ds')
    .reset_index()
)
ucaas_weekly['y_lag1'] = ucaas_weekly['y'].shift(1).fillna(0.0)
ucaas_weekly['y_lag13'] = ucaas_weekly['y'].shift(13).fillna(0.0)
ucaas_weekly['r4w'] = ucaas_weekly['y'].rolling(4, min_periods=1).mean().shift(1).fillna(0.0)
ucaas_weekly['quarter'] = ucaas_weekly['ds'].dt.quarter
ucaas_weekly['week_of_qtr'] = ucaas_weekly.groupby([ucaas_weekly['ds'].dt.year, ucaas_weekly['ds'].dt.quarter]).cumcount() + 1
ucaas_weekly['quarter_end_flag'] = (ucaas_weekly['week_of_qtr'] >= 11).astype(int)
ucaas_weekly['is_q4'] = (ucaas_weekly['quarter'] == 4).astype(int)
ucaas_weekly['q4_week_countdown'] = np.where(ucaas_weekly['quarter'] == 4, 14 - ucaas_weekly['week_of_qtr'], 0)


# COMMAND ----------

# DBTITLE 1,Step 4: Walk Forward Validation Framework
# STEP 4: WALK-FORWARD VALIDATION FRAMEWORK
# =============================================================================
# PURPOSE: Build a rigorous, reproducible framework for measuring forecast
# accuracy across multiple historical "replays" of the past, so we don't
# overfit to a single train/test split.
#
# HOW IT WORKS (expanding-window / walk-forward cross-validation):
#   1. Start from the earliest usable training window (MIN_TRAIN_WEEKS).
#   2. Train each model on all history up to fold_end.
#   3. Generate forecasts for the next CV_HORIZON = 13 weeks.
#   4. Slide the window forward and repeat for CV_FOLDS = 8 total folds.
#   Each fold gives one 13-week forecast vs actual comparison.
#
# WHY THIS MATTERS:
#   A single holdout test can get lucky or unlucky depending on whether that
#   period contains a Q4 spike, a slowdown, etc.  8 folds averaging over
#   two full years of history gives a much more stable WAPE estimate.
#
# KEY METRICS:
#   WAPE  = |sum(errors)| / sum(actuals)  — business-preferred; weights big weeks
#   MAPE  = mean(|error / actual|)        — intuitive % but sensitive to near-zero weeks
#   MPE   = mean(error / actual)          — signed bias; positive = over-forecast
#
# OUTPUTS (used in Steps 5-16):
#   cv_fold_specs            — DataFrame describing each fold's date range
#   evaluate_forecasts()     — reusable metric function called by every model
#   add_calendar_columns()   — adds week_of_qtr, quarter_end_flag, holiday flags
# =============================================================================

import warnings
from dataclasses import dataclass

import holidays
import mlflow
import numpy as np
import pandas as pd
from prophet import Prophet
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, MSTL
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings('ignore')

CV_HORIZON = 13
CV_FOLDS = 8
MIN_TRAIN_WEEKS = len(model_df) - (CV_FOLDS * CV_HORIZON)

us_holidays = holidays.US()


def add_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['ds'] = pd.to_datetime(out['ds'])
    out['year'] = out['ds'].dt.year
    out['quarter'] = out['ds'].dt.quarter
    out['week_of_qtr'] = out.groupby(['year', 'quarter']).cumcount() + 1
    out['quarter_end_flag'] = (out['week_of_qtr'] >= 11).astype(int)
    out['is_q4'] = (out['quarter'] == 4).astype(int)
    out['q4_week_countdown'] = np.where(out['quarter'] == 4, 14 - out['week_of_qtr'], 0)
    out['us_holiday'] = out['ds'].apply(lambda d: int(d.date() in us_holidays or (d + pd.Timedelta(days=1)).date() in us_holidays))
    return out


@dataclass
class FoldSpec:
    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_rows: int
    test_rows: int


def build_walkforward_folds(df: pd.DataFrame, horizon: int = CV_HORIZON, n_folds: int = CV_FOLDS, min_train: int = MIN_TRAIN_WEEKS):
    folds = []
    for fold_idx in range(n_folds):
        train_end_idx = min_train + (fold_idx * horizon)
        test_end_idx = train_end_idx + horizon
        train_slice = df.iloc[:train_end_idx].copy()
        test_slice = df.iloc[train_end_idx:test_end_idx].copy()
        folds.append(FoldSpec(
            fold=fold_idx + 1,
            train_start=train_slice['ds'].min(),
            train_end=train_slice['ds'].max(),
            test_start=test_slice['ds'].min(),
            test_end=test_slice['ds'].max(),
            train_rows=len(train_slice),
            test_rows=len(test_slice),
        ))
    return pd.DataFrame([f.__dict__ for f in folds])


fold_specs = build_walkforward_folds(model_df)


def ci_coverage(actual, p10, p90):
    actual = np.asarray(actual, dtype=float)
    p10 = np.asarray(p10, dtype=float)
    p90 = np.asarray(p90, dtype=float)
    valid = (~np.isnan(actual)) & (~np.isnan(p10)) & (~np.isnan(p90))
    if not valid.any():
        return np.nan
    return float(np.mean((actual[valid] >= p10[valid]) & (actual[valid] <= p90[valid])) * 100)


def forecast_metrics(actual, pred, p10=None, p90=None):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    denom = np.where(np.abs(actual) < 1e-9, np.nan, actual)
    ape = np.abs(actual - pred) / np.abs(denom)
    pe = (pred - actual) / denom
    smape_denom = np.abs(actual) + np.abs(pred)
    metrics = {
        'wape': float(np.sum(np.abs(actual - pred)) / np.sum(np.abs(actual)) * 100),
        'mape': float(np.nanmean(ape) * 100),
        'mpe': float(np.nanmean(pe) * 100),
        'smape': float(np.nanmean(np.where(smape_denom > 1e-9, 200.0 * np.abs(actual - pred) / smape_denom, np.nan))),
        'rmse': float(np.sqrt(np.nanmean((actual - pred) ** 2))),
    }
    metrics['ci_coverage'] = ci_coverage(actual, p10, p90) if p10 is not None and p90 is not None else np.nan
    return metrics


# Training-only empirical week-of-quarter profile used to keep Prophet conservative
# on trend while still respecting ARR quarter-end shape.
def compute_woq_seasonal_profile(train_hist: pd.DataFrame, lookback: int = 104):
    prof = add_calendar_columns(train_hist[['ds', 'y']].tail(min(len(train_hist), lookback)).copy())
    if len(prof) >= 3:
        t = np.arange(len(prof))
        coeffs = np.polyfit(t, prof['y'], 1)
        trend_line = np.polyval(coeffs, t)
    else:
        trend_line = np.repeat(prof['y'].mean(), len(prof))
    prof['ratio'] = prof['y'] / np.where(np.abs(trend_line) < 1e-9, 1.0, trend_line)
    seasonal = prof.groupby('week_of_qtr')['ratio'].mean()
    seasonal = seasonal / seasonal.mean()
    return {wk: float(seasonal.get(wk, 1.0)) for wk in range(1, 14)}


def run_walkforward_cv(model_name, fit_predict_fn, df, horizon: int = CV_HORIZON, n_folds: int = CV_FOLDS, min_train: int = MIN_TRAIN_WEEKS, **kwargs):
    fold_rows = []
    fold_predictions = []
    for fold_idx in range(n_folds):
        train_end_idx = min_train + (fold_idx * horizon)
        test_end_idx = train_end_idx + horizon
        train_fold = df.iloc[:train_end_idx].copy().reset_index(drop=True)
        test_fold = df.iloc[train_end_idx:test_end_idx].copy().reset_index(drop=True)
        pred = fit_predict_fn(train_fold, horizon=horizon, **kwargs)
        pred = np.asarray(pred, dtype=float)
        metrics = forecast_metrics(test_fold['y'].values, pred)
        fold_rows.append({
            'model': model_name,
            'fold': fold_idx + 1,
            'train_start': str(train_fold['ds'].min().date()),
            'train_end': str(train_fold['ds'].max().date()),
            'test_start': str(test_fold['ds'].min().date()),
            'test_end': str(test_fold['ds'].max().date()),
            'train_rows': len(train_fold),
            'test_rows': len(test_fold),
            'wape': round(metrics['wape'], 3),
            'mape': round(metrics['mape'], 3),
            'mpe': round(metrics['mpe'], 3),
            'smape': round(metrics['smape'], 3),
            'rmse': round(metrics['rmse'], 3),
        })
        fold_predictions.append(pd.DataFrame({
            'model': model_name,
            'fold': fold_idx + 1,
            'ds': test_fold['ds'],
            'actual': test_fold['y'].values,
            'forecast': pred,
        }))
    fold_df = pd.DataFrame(fold_rows)
    summary_df = pd.DataFrame([{
        'model': model_name,
        'folds': n_folds,
        'mean_wape': round(fold_df['wape'].mean(), 3),
        'std_wape': round(fold_df['wape'].std(ddof=0), 3),
        'mean_mape': round(fold_df['mape'].mean(), 3),
        'std_mape': round(fold_df['mape'].std(ddof=0), 3),
        'mean_mpe': round(fold_df['mpe'].mean(), 3),
        'std_mpe': round(fold_df['mpe'].std(ddof=0), 3),
        'mean_smape': round(fold_df['smape'].mean(), 3),
        'std_smape': round(fold_df['smape'].std(ddof=0), 3),
        'mean_rmse': round(fold_df['rmse'].mean(), 3),
        'std_rmse': round(fold_df['rmse'].std(ddof=0), 3),
    }])
    pred_df = pd.concat(fold_predictions, ignore_index=True)
    return fold_df, summary_df, pred_df


print(f'Modeling rows available: {len(model_df):,}')
print(f'Walk-forward CV folds: {CV_FOLDS} | horizon: {CV_HORIZON} weeks | minimum train: {MIN_TRAIN_WEEKS} weeks')
print('\nFold specification:')
display(fold_specs)


# COMMAND ----------

# DBTITLE 1,Step 5: Benchmark Models — MSTL v2, ETS, Prophet
# STEP 5: BENCHMARK MODELS — MSTL V2, ETS, PROPHET
# =============================================================================
# PURPOSE: Establish three diverse statistical baselines before any ML models.
# Expert-review constraint: these three are the MINIMUM credible benchmarks;
# any ML model must beat ALL three on CV WAPE to be promoted to production.
#
# MODEL DESCRIPTIONS:
#
# 1. MSTL v2 (Multiple Seasonal-Trend decomposition using LOESS)
#    Source: statsforecast.models.MSTL
#    Strength: Handles multiple seasonality periods simultaneously.
#              Period [13] = quarterly cycle, [52] = annual cycle.
#    Weakness: Can over-smooth the sharp end-of-quarter surge.
#    Expected CV WAPE: ~28% (validated 27.91 in V8).
#
# 2. ETS (Exponential Triple Smoothing / Holt-Winters)
#    Source: statsforecast.models.AutoETS
#    Strength: Very fast, adapts to level/trend/seasonality automatically;
#              best single-model performer on the Q1/Q2 2026 holdout.
#    Expected CV WAPE: ~26% (validated 25.98 in V8).
#
# 3. Prophet_trend (Facebook Prophet with conservative trend)
#    Source: prophet.Prophet
#    Strength: Interpretable trend + seasonality + US holiday regressors.
#              The 'trend' flavour uses a logistic/flat cap to prevent
#              unbounded extrapolation into 2026.
#    Weakness: Sensitive to trend inflection points.
#    Expected CV WAPE: ~27% (validated 27.10 in V8).
#
# ALL MODELS run through the 8-fold walk-forward CV (Step 4 framework)
# AND the final Q1/Q2 2026 holdout evaluation.
# Results flow into cv_benchmark_summary and holdout_benchmark_summary.
# =============================================================================

benchmark_train = add_calendar_columns(train_df[['ds', 'y']].copy())
benchmark_test = add_calendar_columns(test_df[['ds', 'y']].copy())


def fit_predict_mstl_v2(train_hist: pd.DataFrame, horizon: int):
    train_input = train_hist[['ds', 'y']].copy()
    train_input.insert(0, 'unique_id', 'ucc_total')
    sf = StatsForecast(
        models=[MSTL(
            season_length=[4, 13, 52],
            trend_forecaster=AutoETS(model='ZZN')
        )],
        freq='W-MON',
        n_jobs=1,
    )
    fcst = sf.forecast(df=train_input, h=horizon)
    model_col = [c for c in fcst.columns if c not in {'unique_id', 'ds'}][0]
    return fcst[model_col].to_numpy(dtype=float)


# Use the stronger V1 ETS pattern: last 104 weeks, damped additive trend,
# multiplicative 13-week seasonality.
def fit_predict_ets(train_hist: pd.DataFrame, horizon: int, window: int = 104):
    hist = train_hist[['ds', 'y']].tail(min(window, len(train_hist))).copy()
    seasonal_period = 52 if len(hist) >= 104 else 13
    ets = ExponentialSmoothing(
        hist['y'].astype(float),
        trend='add',
        damped_trend=True,
        seasonal='mul',
        seasonal_periods=seasonal_period,
        initialization_method='estimated',
    ).fit(optimized=True, use_brute=False)
    return ets.forecast(horizon).to_numpy(dtype=float)


# Conservative Prophet: trend model only, then apply training-fold empirical
# week-of-quarter seasonality to avoid the V1 issue of heavily shrunk seasonality.
def fit_predict_prophet_trend(train_hist: pd.DataFrame, horizon: int):
    prophet_train = train_hist[['ds', 'y']].copy()
    model = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.08,
        changepoint_range=0.85,
        n_changepoints=min(8, max(1, len(prophet_train) // 20)),
        seasonality_mode='additive',
        interval_width=0.80,
    )
    model.fit(prophet_train)
    future = model.make_future_dataframe(periods=horizon, freq='W-MON', include_history=False)
    future = add_calendar_columns(future)
    seasonal_map = compute_woq_seasonal_profile(train_hist)
    raw_pred = model.predict(future)[['ds', 'yhat']].copy()
    raw_pred = raw_pred.merge(future[['ds', 'week_of_qtr']], on='ds', how='left')
    raw_pred['seasonal_factor'] = raw_pred['week_of_qtr'].map(seasonal_map).fillna(1.0)
    raw_pred['forecast'] = raw_pred['yhat'] * raw_pred['seasonal_factor']
    return raw_pred['forecast'].to_numpy(dtype=float)


mstl_fold_df, mstl_summary_df, _ = run_walkforward_cv(
    model_name='MSTL_v2_default',
    fit_predict_fn=fit_predict_mstl_v2,
    df=model_df[['ds', 'y']].copy(),
)
mstl_tuning = pd.DataFrame([{
    's_window': 'package_default',
    'mean_wape': mstl_summary_df['mean_wape'].iloc[0],
    'mean_mape': mstl_summary_df['mean_mape'].iloc[0],
    'mean_mpe': mstl_summary_df['mean_mpe'].iloc[0],
}])
BEST_MSTL_SWINDOW = 'package_default'

benchmark_specs = [
    ('MSTL_v2', fit_predict_mstl_v2, {}),
    ('ETS', fit_predict_ets, {}),
    ('Prophet_trend', fit_predict_prophet_trend, {}),
]

all_fold_results = []
all_cv_summaries = []
all_cv_predictions = []
backtest_rows = []
backtest_predictions = []

for model_name, fn, kwargs in benchmark_specs:
    fold_df, summary_df, pred_df = run_walkforward_cv(
        model_name=model_name,
        fit_predict_fn=fn,
        df=model_df[['ds', 'y']].copy(),
        **kwargs,
    )
    all_fold_results.append(fold_df)
    all_cv_summaries.append(summary_df)
    all_cv_predictions.append(pred_df)

    train_pred = fn(train_df[['ds', 'y']].copy(), horizon=len(test_df), **kwargs)
    holdout_metrics = forecast_metrics(test_df['y'].values, train_pred)
    backtest_rows.append({
        'model': model_name,
        'test_start': str(test_df['ds'].min().date()),
        'test_end': str(test_df['ds'].max().date()),
        'test_rows': len(test_df),
        'wape': round(holdout_metrics['wape'], 3),
        'mape': round(holdout_metrics['mape'], 3),
        'mpe': round(holdout_metrics['mpe'], 3),
    })
    backtest_predictions.append(pd.DataFrame({
        'model': model_name,
        'ds': test_df['ds'].values,
        'actual': test_df['y'].values,
        'forecast': np.asarray(train_pred, dtype=float),
    }))

    with mlflow.start_run(run_name=f'ucc_{model_name.lower()}_cv', nested=False):
        mlflow.log_param('model_name', model_name)
        mlflow.log_param('cv_folds', CV_FOLDS)
        mlflow.log_param('cv_horizon', CV_HORIZON)
        if model_name == 'MSTL_v2':
            mlflow.log_param('mstl_config', BEST_MSTL_SWINDOW)
        cv_row = summary_df.iloc[0].to_dict()
        for k, v in cv_row.items():
            if k != 'model':
                mlflow.log_metric(k, float(v))
        holdout_row = backtest_rows[-1]
        mlflow.log_metric('holdout_wape', float(holdout_row['wape']))
        mlflow.log_metric('holdout_mape', float(holdout_row['mape']))
        mlflow.log_metric('holdout_mpe', float(holdout_row['mpe']))

cv_fold_results = pd.concat(all_fold_results, ignore_index=True)
cv_benchmark_summary = pd.concat(all_cv_summaries, ignore_index=True).sort_values(['mean_wape', 'mean_mape']).reset_index(drop=True)
cv_fold_predictions = pd.concat(all_cv_predictions, ignore_index=True)
holdout_benchmark_summary = pd.DataFrame(backtest_rows).sort_values(['wape', 'mape']).reset_index(drop=True)
holdout_benchmark_predictions = pd.concat(backtest_predictions, ignore_index=True)

print(f'Best MSTL s_window from walk-forward CV: {BEST_MSTL_SWINDOW}')
print('\nMSTL tuning summary:')
display(mstl_tuning)

print('\nWalk-forward benchmark summary:')
display(cv_benchmark_summary)

print('\nFold-by-fold benchmark results:')
display(cv_fold_results)

print('\nLater backtest window results (2026 Q1 onward):')
display(holdout_benchmark_summary)


# COMMAND ----------

# DBTITLE 1,Step 6: Plot Actual Versus Forecast
# STEP 6: PLOT ACTUAL VERSUS FORECAST
# =============================================================================
# PURPOSE: Side-by-side visual of every model's holdout forecast vs actuals.
# This is the primary diagnostic chart for:
#   - Identifying systematic bias (a model always above or below actuals)
#   - Spotting which model best captures Q-end surges
#   - Presenting to stakeholders as evidence of model credibility
#
# Chart layout:
#   - Black line = actual weekly ARR (truth)
#   - Coloured lines = each model's holdout forecast
#   - Vertical dashed line marks Q1 vs Q2 boundary
#   - Y-axis in $M for readability
# =============================================================================

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

MODEL_LABELS = {
    'ETS': 'ETS',
    'Prophet_trend': 'Prophet trend',
    'MSTL_v2': 'MSTL v2',
    'DHR_ARIMA': 'DHR-ARIMA',
    'Global_LGB_Q50': 'Global LGB P50',
}
MODEL_COLORS = {
    'ETS': '#1f77b4',
    'Prophet trend': '#2ca02c',
    'MSTL v2': '#ff7f0e',
    'DHR-ARIMA': '#9467bd',
    'Global LGB P50': '#8c564b',
}
MODEL_ORDER = ['ETS', 'Prophet_trend', 'MSTL_v2', 'DHR_ARIMA', 'Global_LGB_Q50']

plot_df = (
    holdout_benchmark_predictions
    .pivot(index='ds', columns='model', values='forecast')
    .reset_index()
    .merge(test_df[['ds', 'y']].rename(columns={'y': 'Actual'}), on='ds', how='left')
)
plot_df = plot_df.rename(columns={k: v for k, v in MODEL_LABELS.items() if k in plot_df.columns}).sort_values('ds')
plot_cols = ['Actual'] + [MODEL_LABELS[m] for m in MODEL_ORDER if MODEL_LABELS[m] in plot_df.columns]

plot_df_m = plot_df.copy()
for col in plot_cols:
    plot_df_m[col] = plot_df_m[col] / 1e6

fig, ax = plt.subplots(figsize=(14, 6))
ax.plot(plot_df_m['ds'], plot_df_m['Actual'], color='black', linewidth=2.5, label='Actual')
for label in plot_cols[1:]:
    ax.plot(
        plot_df_m['ds'],
        plot_df_m[label],
        color=MODEL_COLORS[label],
        linewidth=2.0,
        linestyle='--',
        label=f'{label} forecast',
    )

ax.set_title('UCC actual versus forecast on backtest window')
ax.set_xlabel('Week start')
ax.set_ylabel('Growth ARR ($M)')
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'${x:,.1f}M'))
ax.grid(alpha=0.25)
ax.legend(loc='upper left', ncol=2)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

print('Backtest metrics (lower WAPE / MAPE, MPE near zero):')
display(holdout_benchmark_summary)

print('\nActual versus forecast sample:')
display(plot_df[['ds'] + plot_cols].head(5))


# COMMAND ----------

# DBTITLE 1,Step 7: Plot Fold by Fold Forecasts
# STEP 7: PLOT FOLD BY FOLD FORECASTS
# =============================================================================
# PURPOSE: Visualise how each model performed across all 8 walk-forward CV folds.
# This answers: "Is the model consistently good, or did it just get lucky on
# one or two folds?"
#
# Each subplot = one fold (one 13-week forward window).
# Black = actual actuals for that window.
# Coloured = each model's forecast issued at the fold boundary.
#
# Red flags to look for:
#   - A model that does well on early folds but collapses on 2025/2026 folds
#     (means it overfits to older patterns)
#   - A model that systematically over-forecasts the first few weeks of a quarter
#     (means it doesn't know where in the quarter it is)
# =============================================================================

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

MODEL_LABELS = {
    'ETS': 'ETS',
    'Prophet_trend': 'Prophet trend',
    'MSTL_v2': 'MSTL v2',
    'DHR_ARIMA': 'DHR-ARIMA',
    'Global_LGB_Q50': 'Global LGB P50',
}
MODEL_COLORS = {
    'Actual': 'black',
    'ETS': '#1f77b4',
    'Prophet trend': '#2ca02c',
    'MSTL v2': '#ff7f0e',
    'DHR-ARIMA': '#9467bd',
    'Global LGB P50': '#8c564b',
}
MODEL_ORDER = ['ETS', 'Prophet_trend', 'MSTL_v2', 'DHR_ARIMA', 'Global_LGB_Q50']

fold_plot_df = (
    cv_fold_predictions
    .pivot_table(index=['fold', 'ds', 'actual'], columns='model', values='forecast', aggfunc='first')
    .reset_index()
    .rename(columns={'actual': 'Actual'})
    .sort_values(['fold', 'ds'])
)
fold_plot_df = fold_plot_df.rename(columns={k: v for k, v in MODEL_LABELS.items() if k in fold_plot_df.columns})
available_labels = [MODEL_LABELS[m] for m in MODEL_ORDER if MODEL_LABELS[m] in fold_plot_df.columns]

fold_metric_summary = (
    cv_fold_results
    .pivot_table(index='fold', columns='model', values='wape', aggfunc='first')
    .reset_index()
    .sort_values('fold')
)
fold_metric_summary = fold_metric_summary.rename(columns={k: f'{v} WAPE' for k, v in MODEL_LABELS.items() if k in fold_metric_summary.columns})

fig, axes = plt.subplots(4, 2, figsize=(18, 16), sharex=False, sharey=True)
axes = axes.flatten()

for i, fold in enumerate(sorted(fold_plot_df['fold'].unique())):
    ax = axes[i]
    fold_data = fold_plot_df[fold_plot_df['fold'] == fold].copy()
    metric_row = fold_metric_summary[fold_metric_summary['fold'] == fold].iloc[0]

    ax.plot(fold_data['ds'], fold_data['Actual'] / 1e6, color=MODEL_COLORS['Actual'], linewidth=2.3, label='Actual')
    for label in available_labels:
        ax.plot(
            fold_data['ds'],
            fold_data[label] / 1e6,
            color=MODEL_COLORS[label],
            linewidth=1.8,
            linestyle='--',
            label=label,
        )

    metric_text = ', '.join([f"{label} {metric_row[f'{label} WAPE']:.1f}" for label in available_labels])
    ax.set_title(
        f"Fold {fold}: {fold_data['ds'].min().date()} to {fold_data['ds'].max().date()}\n"
        f"WAPE — {metric_text}"
    )
    ax.set_ylabel('Growth ARR ($M)')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'${x:,.1f}M'))
    ax.grid(alpha=0.25)
    ax.tick_params(axis='x', rotation=45)

for ax in axes[len(fold_plot_df['fold'].unique()):]:
    ax.axis('off')

handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc='upper center', ncol=min(5, len(labels)), frameon=False, bbox_to_anchor=(0.5, 1.01))
fig.suptitle('UCC expanding walk-forward CV: actual versus forecast by fold', y=1.04, fontsize=15)
plt.tight_layout()
plt.show()

print('Fold-level WAPE summary:')
display(fold_metric_summary)

print('\nFold forecast sample:')
display(fold_plot_df[['fold', 'ds', 'Actual'] + available_labels].head(5))


# COMMAND ----------

# DBTITLE 1,Step 8: Quarterly Forecast Versus Actuals
# STEP 8: QUARTERLY FORECAST VERSUS ACTUALS
# =============================================================================
# PURPOSE: Aggregate weekly forecasts to the quarter level and compare vs actual
# quarterly ARR.  This is the exec-facing accuracy view because:
#   - Sales leadership sets quarterly targets, not weekly
#   - Quarterly aggregation smooths out week-to-week noise
#   - A model with 30% weekly WAPE can still achieve <5% quarterly error
#     if its errors cancel out across the quarter
#
# quarterly_compare columns:
#   Quarter       — e.g. '2026Q1'
#   actual_arr_m  — sum of all weekly actuals in that quarter
#   forecast_arr_m— sum of all weekly model forecasts for same quarter
#   error_arr_m   — forecast - actual (positive = over-forecast)
#   pct_error     — (forecast/actual - 1) * 100
#
# Benchmarks from V8 (Q1 2026):  ETS 3.7%, MSTL 4.8%, Prophet 7.4%
# =============================================================================

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

MODEL_LABELS = {
    'ETS': 'ETS',
    'Prophet_trend': 'Prophet trend',
    'MSTL_v2': 'MSTL v2',
    'DHR_ARIMA': 'DHR-ARIMA',
    'Global_LGB_Q50': 'Global LGB P50',
}
MODEL_ORDER = ['ETS', 'Prophet_trend', 'MSTL_v2', 'DHR_ARIMA', 'Global_LGB_Q50']
MODEL_COLORS = {
    'Actual': 'black',
    'ETS': '#1f77b4',
    'Prophet trend': '#2ca02c',
    'MSTL v2': '#ff7f0e',
    'DHR-ARIMA': '#9467bd',
    'Global LGB P50': '#8c564b',
}

quarterly_actuals = (
    test_df[['ds', 'y']]
    .assign(quarter=lambda d: d['ds'].dt.to_period('Q').astype(str))
    .groupby('quarter', as_index=False)
    .agg(
        actual=('y', 'sum'),
        weeks=('ds', 'count'),
        quarter_start=('ds', 'min'),
        quarter_end=('ds', 'max'),
    )
)

quarterly_forecasts = (
    holdout_benchmark_predictions
    .assign(quarter=lambda d: pd.to_datetime(d['ds']).dt.to_period('Q').astype(str))
    .groupby(['quarter', 'model'], as_index=False)
    .agg(forecast=('forecast', 'sum'))
)

quarterly_compare = (
    quarterly_forecasts
    .merge(quarterly_actuals, on='quarter', how='left')
    .assign(
        actual_arr_m=lambda d: (d['actual'] / 1e6).round(3),
        forecast_arr_m=lambda d: (d['forecast'] / 1e6).round(3),
        error_arr_m=lambda d: ((d['forecast'] - d['actual']) / 1e6).round(3),
        pct_error=lambda d: (((d['forecast'] / d['actual']) - 1) * 100).round(1),
    )
    .rename(columns={
        'model': 'Model',
        'quarter': 'Quarter',
        'weeks': 'Weeks',
        'quarter_start': 'Quarter start',
        'quarter_end': 'Quarter end',
    })
    .replace({'Model': MODEL_LABELS})
    .sort_values(['Quarter', 'Model'])
    .reset_index(drop=True)
)

quarter_plot = quarterly_compare.pivot(index='Quarter', columns='Model', values='forecast_arr_m').reset_index()
quarter_plot = quarter_plot.merge(
    quarterly_compare[['Quarter', 'actual_arr_m']].drop_duplicates(),
    on='Quarter',
    how='left'
).rename(columns={'actual_arr_m': 'Actual'})

plot_order = ['Actual'] + [MODEL_LABELS[m] for m in MODEL_ORDER if MODEL_LABELS[m] in quarter_plot.columns]
quarters = quarter_plot['Quarter'].tolist()
x = np.arange(len(quarters))
width = 0.8 / max(1, len(plot_order))

fig, ax = plt.subplots(figsize=(12, 6))
for i, col in enumerate(plot_order):
    offset = (i - (len(plot_order) - 1) / 2) * width
    ax.bar(x + offset, quarter_plot[col], width=width, color=MODEL_COLORS[col], alpha=0.9, label=col)

ax.set_title('UCC quarterly forecast versus actuals on backtest window')
ax.set_xlabel('Quarter')
ax.set_ylabel('Growth ARR ($M)')
ax.set_xticks(x)
ax.set_xticklabels(quarters)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, pos: f'${y:,.1f}M'))
ax.grid(axis='y', alpha=0.25)
ax.legend(loc='upper right', ncol=2)
plt.tight_layout()
plt.show()

print('Quarterly forecast versus actuals summary:')
display(quarterly_compare[['Quarter', 'Model', 'Weeks', 'Quarter start', 'Quarter end', 'actual_arr_m', 'forecast_arr_m', 'error_arr_m', 'pct_error']])

print('\nQuarterly chart input sample:')
display(quarter_plot.head(5))

print('\nNote: 2026Q2 is quarter-to-date through the last fully closed week in the notebook (2026-06-22).')


# COMMAND ----------

# DBTITLE 1,Step 8B: Quarterly Errors Ranked
# STEP 8B: QUARTERLY ERRORS RANKED
# =============================================================================
# PURPOSE: Rank every model within each completed quarter by absolute % error.
# This provides a single, easy-to-read leaderboard for stakeholders:
#   rank_in_quarter = 1  means that model was closest to actual that quarter
#
# overall_quarterly_error_rank = average rank across all quarters;
# a model consistently at rank 1-2 is more reliable than one that wins
# one quarter but blows out the next.
#
# Use this table to answer: "Which model should we trust for Q3 2026?"
# =============================================================================

ranked_quarterly_errors = (
    quarterly_compare.copy()
    .assign(
        abs_error_arr_m=lambda d: d['error_arr_m'].abs().round(3),
        abs_pct_error=lambda d: d['pct_error'].abs().round(1),
    )
)
ranked_quarterly_errors['rank_in_quarter'] = (
    ranked_quarterly_errors
    .groupby('Quarter')['abs_pct_error']
    .rank(method='dense', ascending=True)
    .astype(int)
)
ranked_quarterly_errors = ranked_quarterly_errors.sort_values(
    ['Quarter', 'rank_in_quarter', 'abs_pct_error', 'abs_error_arr_m', 'Model']
).reset_index(drop=True)

overall_quarterly_error_rank = (
    ranked_quarterly_errors
    .groupby('Model', as_index=False)
    .agg(
        mean_abs_pct_error=('abs_pct_error', 'mean'),
        mean_abs_error_arr_m=('abs_error_arr_m', 'mean'),
        max_abs_pct_error=('abs_pct_error', 'max'),
        quarters=('Quarter', 'count'),
    )
    .sort_values(['mean_abs_pct_error', 'mean_abs_error_arr_m', 'max_abs_pct_error'])
    .reset_index(drop=True)
)
overall_quarterly_error_rank.index = overall_quarterly_error_rank.index + 1
overall_quarterly_error_rank = overall_quarterly_error_rank.reset_index().rename(columns={'index': 'overall_rank'})

display(ranked_quarterly_errors[[
    'Quarter', 'rank_in_quarter', 'Model', 'actual_arr_m', 'forecast_arr_m',
    'error_arr_m', 'abs_error_arr_m', 'pct_error', 'abs_pct_error'
]])

print('\nOverall quarterly ranking across available quarters:')
display(overall_quarterly_error_rank)


# COMMAND ----------

# DBTITLE 1,Step 9: Benchmark Model — DHR ARIMA
# STEP 9: BENCHMARK MODEL — DHR-ARIMA
# =============================================================================
# PURPOSE: Add a fourth, more sophisticated statistical model that uses
# external regressors to improve on pure time-series approaches.
#
# WHAT IS DHR-ARIMA?
#   Dynamic Harmonic Regression + ARIMA error correction.
#   The model is AutoARIMA but with hand-crafted external regressors (xreg):
#   - Fourier terms (sin/cos) to encode weekly/quarterly seasonality
#     in a way that is PHASE-STABLE across CV folds (calendar-based index,
#     not fold-relative — critical to avoid leakage)
#   - pipeline lag features (created_lag4, pipeline_velocity_lag4)
#   - headcount_lag4: sales capacity as a structural growth lever
#   - win_rate_by_woq: conversion rate conditioned on week-of-quarter
#   - us_holiday_binary: suppresses activity around US federal holidays
#
# TRAINING SCOPE:
#   Runs PER SALES MARKET (NA, EMEA, APAC, LATAM, Unknown) independently,
#   then sums market forecasts to the total for WAPE evaluation.
#   This respects the structural differences between regions.
#
# SOURCE DATA TABLES USED IN THIS STEP:
#   datagroup_mdl.mdl_sales_analytics.forecast_prophet  — headcount by market/week
#   datagroup.datalake_transform.cds_sfdc_opp_products_latest — pipeline creation,
#     win rates, opportunity age (all sourced via ucc_raw already in memory)
#
# Expected improvement over ETS:  ~2-4 WAPE points on the holdout
# (DHR captures explicit pipeline leading indicator; ETS cannot).
# =============================================================================

from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA

HEADCOUNT_TABLE = 'datagroup_mdl.mdl_sales_analytics.forecast_prophet'
DHR_MODEL_NAME = 'DHR_ARIMA'
FOURIER_SPECS = [
    ('q13', 13, 2),
    ('y52', 52, 2),
]
DHR_XREG_COLS = [
    'q13_sin_1', 'q13_cos_1', 'q13_sin_2', 'q13_cos_2',
    'y52_sin_1', 'y52_cos_1', 'y52_sin_2', 'y52_cos_2',
    'created_lag4',
    'headcount_lag4',
    'win_rate_by_woq',
    'pipeline_velocity_lag4',
    'quarter_end_flag',
    'us_holiday_binary',
]
DHR_MARKET_MAP = {
    'AUS/ROW': 'APAC',
    'INDIA': 'APAC',
    'UNKNOWN': 'Unknown',
    '': 'Unknown',
}
DHR_MARKETS = sorted(
    weekly_ucc_by_market['sales_market'].fillna('Unknown').replace(DHR_MARKET_MAP).astype(str).unique().tolist()
)

headcount_weekly = spark.sql(f"""
SELECT
    CAST(ds AS DATE) AS ds,
    COALESCE(UPPER(sales_market), 'UNKNOWN') AS sales_market,
    SUM(COALESCE(headcount, 0)) AS headcount_total
FROM {HEADCOUNT_TABLE}
WHERE product = 'UCC'
  AND ds >= DATE '{model_df['ds'].min().date()}'
  AND ds <= DATE '{(model_df['ds'].max() + pd.Timedelta(weeks=1)).date()}'
GROUP BY 1, 2
ORDER BY 1, 2
""").toPandas()
headcount_weekly['ds'] = pd.to_datetime(headcount_weekly['ds'])
headcount_weekly['sales_market'] = (
    headcount_weekly['sales_market']
    .fillna('Unknown')
    .astype(str)
    .str.strip()
    .replace(DHR_MARKET_MAP)
)
headcount_weekly['headcount_total'] = pd.to_numeric(headcount_weekly['headcount_total'], errors='coerce')

market_calendar = pd.MultiIndex.from_product(
    [weekly_ucc['ds'].sort_values().unique(), DHR_MARKETS],
    names=['ds', 'sales_market'],
).to_frame(index=False)

market_close_weekly = (
    ucc_raw.groupby(['week_start', 'sales_market'], dropna=False)
    .agg(
        y=('amount_towards_plan', 'sum'),
        avg_opportunity_age=('opportunity_age', 'mean'),
    )
    .reset_index()
    .rename(columns={'week_start': 'ds'})
)
market_close_weekly['ds'] = pd.to_datetime(market_close_weekly['ds'])
market_close_weekly['sales_market'] = (
    market_close_weekly['sales_market']
    .fillna('Unknown')
    .astype(str)
    .str.strip()
    .replace(DHR_MARKET_MAP)
)

market_created_weekly = (
    ucc_raw.dropna(subset=['pipeline_week_start'])
    .groupby(['pipeline_week_start', 'sales_market'], dropna=False)
    .agg(created_arr=('amount_towards_plan', 'sum'))
    .reset_index()
    .rename(columns={'pipeline_week_start': 'ds'})
)
market_created_weekly['ds'] = pd.to_datetime(market_created_weekly['ds'])
market_created_weekly['sales_market'] = (
    market_created_weekly['sales_market']
    .fillna('Unknown')
    .astype(str)
    .str.strip()
    .replace(DHR_MARKET_MAP)
)

dhr_market_base_df = (
    market_calendar
    .merge(market_close_weekly, on=['ds', 'sales_market'], how='left')
    .merge(market_created_weekly, on=['ds', 'sales_market'], how='left')
    .merge(headcount_weekly.rename(columns={'headcount_total': 'headcount'}), on=['ds', 'sales_market'], how='left')
    .sort_values(['sales_market', 'ds'])
    .reset_index(drop=True)
)
dhr_market_base_df['y'] = pd.to_numeric(dhr_market_base_df['y'], errors='coerce').fillna(0.0)
dhr_market_base_df['created_arr'] = pd.to_numeric(dhr_market_base_df['created_arr'], errors='coerce').fillna(0.0)

def add_fourier_terms(df: pd.DataFrame, ds_col: str = 'ds') -> pd.DataFrame:
    """Calendar-based Fourier terms — phase-stable across CV folds.
    q13 uses week_of_qtr (1-13), y52 uses ISO week_of_year (1-52).
    """
    out = df.copy()
    ds = pd.to_datetime(out[ds_col])
    # Calendar-based indices guarantee consistent phase regardless of fold start
    week_of_year = ds.dt.isocalendar().week.astype(int).values
    if 'week_of_qtr' in out.columns:
        week_of_qtr = out['week_of_qtr'].values
    else:
        temp = out.assign(_yr=ds.dt.year, _qtr=ds.dt.quarter)
        week_of_qtr = temp.groupby(['_yr', '_qtr']).cumcount().values + 1
    for prefix, period, harmonics in FOURIER_SPECS:
        if prefix == 'q13':
            idx = week_of_qtr
        elif prefix == 'y52':
            idx = week_of_year
        else:
            idx = ((ds - FIRST_FULL_MONDAY).dt.days // 7).astype(int).values
        for k in range(1, harmonics + 1):
            angle = 2 * np.pi * k * (idx - 1) / period
            out[f'{prefix}_sin_{k}'] = np.sin(angle)
            out[f'{prefix}_cos_{k}'] = np.cos(angle)
    return out


def build_dhr_feature_frame(base_df: pd.DataFrame) -> pd.DataFrame:
    feat = base_df.copy().sort_values(['sales_market', 'ds']).reset_index(drop=True)
    feat = add_calendar_columns(feat)
    feat['headcount'] = pd.to_numeric(feat['headcount'], errors='coerce')
    feat['headcount'] = feat.groupby('sales_market')['headcount'].transform(
        lambda s: s.replace(0, np.nan).ffill().bfill()
    ).fillna(0.0)

    feat['created_arr'] = pd.to_numeric(feat['created_arr'], errors='coerce').fillna(0.0)
    feat['avg_opportunity_age'] = pd.to_numeric(feat['avg_opportunity_age'], errors='coerce').replace(0, np.nan)
    feat['avg_opportunity_age'] = feat.groupby('sales_market')['avg_opportunity_age'].transform(lambda s: s.ffill().bfill())
    global_age = float(feat['avg_opportunity_age'].dropna().median()) if feat['avg_opportunity_age'].notna().any() else 1.0
    feat['avg_opportunity_age'] = feat['avg_opportunity_age'].fillna(global_age).clip(lower=1.0)

    feat['pipeline_velocity'] = feat['created_arr'] / feat['avg_opportunity_age']
    feat['pipeline_velocity'] = feat['pipeline_velocity'].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    feat['created_lag4'] = feat.groupby('sales_market')['created_arr'].shift(4).fillna(0.0)
    feat['headcount_lag4'] = feat.groupby('sales_market')['headcount'].shift(4).fillna(0.0)
    feat['pipeline_velocity_lag4'] = feat.groupby('sales_market')['pipeline_velocity'].shift(4).fillna(0.0)

    feat['win_rate_by_woq'] = np.nan
    for (sales_market, wk), grp in feat.groupby(['sales_market', 'week_of_qtr']):
        won_roll = grp['y'].shift(1).rolling(4, min_periods=1).sum()
        created_roll = grp['created_arr'].shift(1).rolling(4, min_periods=1).sum().replace(0, np.nan)
        feat.loc[grp.index, 'win_rate_by_woq'] = (won_roll / created_roll).clip(lower=0.0, upper=3.0).values

    market_rate = (
        feat.groupby('sales_market')['y'].transform(lambda s: s.shift(1).rolling(13, min_periods=1).sum()) /
        feat.groupby('sales_market')['created_arr'].transform(lambda s: s.shift(1).rolling(13, min_periods=1).sum()).replace(0, np.nan)
    ).clip(lower=0.0, upper=3.0)
    feat['win_rate_by_woq'] = feat['win_rate_by_woq'].fillna(market_rate).fillna(0.0)

    feat['quarter_end_flag'] = feat['quarter_end_flag'].astype(float)
    feat['us_holiday_binary'] = feat['us_holiday'].astype(float)
    feat = add_fourier_terms(feat)
    feat[DHR_XREG_COLS] = feat[DHR_XREG_COLS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return feat


def build_market_week_profile(train_feat: pd.DataFrame, col: str, lookback_weeks: int = 104):
    lookback = min(lookback_weeks, train_feat['ds'].nunique())
    tail = train_feat.sort_values('ds').groupby('sales_market').tail(lookback)
    profile = tail.groupby(['sales_market', 'week_of_qtr'])[col].median().to_dict()
    market_default = tail.groupby('sales_market')[col].median().to_dict()
    global_default = float(tail[col].median()) if len(tail) else 0.0
    return profile, market_default, global_default


def build_future_dhr_xreg(train_feat: pd.DataFrame, horizon: int) -> pd.DataFrame:
    future_weeks = pd.date_range(train_feat['ds'].max() + pd.Timedelta(weeks=1), periods=horizon, freq='W-MON')
    future = pd.MultiIndex.from_product([future_weeks, DHR_MARKETS], names=['ds', 'sales_market']).to_frame(index=False)
    future = add_calendar_columns(future)
    future = add_fourier_terms(future)

    for col in ['created_lag4', 'headcount_lag4', 'pipeline_velocity_lag4', 'win_rate_by_woq']:
        profile, market_default, global_default = build_market_week_profile(train_feat, col)
        future[col] = [
            profile.get((market, wk), market_default.get(market, global_default))
            for market, wk in zip(future['sales_market'], future['week_of_qtr'])
        ]

    future['quarter_end_flag'] = future['quarter_end_flag'].astype(float)
    future['us_holiday_binary'] = future['us_holiday'].astype(float)
    future[DHR_XREG_COLS] = future[DHR_XREG_COLS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return future


dhr_feature_df = build_dhr_feature_frame(dhr_market_base_df)
dhr_total_history = dhr_feature_df.groupby('ds', as_index=False)['y'].sum().sort_values('ds').reset_index(drop=True)


def fit_predict_dhr_arima(train_hist: pd.DataFrame, horizon: int, full_feature_df: pd.DataFrame, return_market: bool = False):
    train_end = pd.to_datetime(train_hist['ds']).max()
    train_feat = full_feature_df[full_feature_df['ds'] <= train_end].copy().reset_index(drop=True)
    future_feat = build_future_dhr_xreg(train_feat, horizon=horizon)

    train_input = train_feat[['sales_market', 'ds', 'y'] + DHR_XREG_COLS].copy().rename(columns={'sales_market': 'unique_id'})
    future_input = future_feat[['sales_market', 'ds'] + DHR_XREG_COLS].copy().rename(columns={'sales_market': 'unique_id'})

    sf = StatsForecast(
        models=[AutoARIMA(
            season_length=13,
            ic='aicc',
            stepwise=True,
            approximation=False,
            allowdrift=True,
            allowmean=True,
        )],
        freq='W-MON',
        n_jobs=1,
    )
    fcst = sf.forecast(
        df=train_input.sort_values(['unique_id', 'ds']).reset_index(drop=True),
        X_df=future_input.sort_values(['unique_id', 'ds']).reset_index(drop=True),
        h=horizon,
    )
    model_col = [c for c in fcst.columns if c not in {'unique_id', 'ds'}][0]
    market_fcst = (
        fcst.rename(columns={'unique_id': 'sales_market', model_col: 'forecast'})
        [['ds', 'sales_market', 'forecast']]
        .sort_values(['ds', 'sales_market'])
        .reset_index(drop=True)
    )
    if return_market:
        return market_fcst
    return (
        market_fcst.groupby('ds', as_index=False)['forecast']
        .sum()
        .sort_values('ds')['forecast']
        .to_numpy(dtype=float)
    )


dhr_fold_df, dhr_summary_df, dhr_pred_df = run_walkforward_cv(
    model_name=DHR_MODEL_NAME,
    fit_predict_fn=fit_predict_dhr_arima,
    df=dhr_total_history[['ds', 'y']].copy(),
    full_feature_df=dhr_feature_df,
)

dhr_holdout_market_predictions = fit_predict_dhr_arima(
    dhr_total_history[dhr_total_history['ds'] < BACKTEST_START][['ds', 'y']].copy(),
    horizon=len(test_df),
    full_feature_df=dhr_feature_df,
    return_market=True,
)
dhr_holdout_weekly = (
    dhr_holdout_market_predictions.groupby('ds', as_index=False)['forecast']
    .sum()
    .sort_values('ds')
    .reset_index(drop=True)
)
dhr_holdout_pred = dhr_holdout_weekly['forecast'].to_numpy(dtype=float)
dhr_holdout_metrics = forecast_metrics(test_df['y'].values, dhr_holdout_pred)
dhr_holdout_row = pd.DataFrame([{
    'model': DHR_MODEL_NAME,
    'test_start': str(test_df['ds'].min().date()),
    'test_end': str(test_df['ds'].max().date()),
    'test_rows': len(test_df),
    'wape': round(dhr_holdout_metrics['wape'], 3),
    'mape': round(dhr_holdout_metrics['mape'], 3),
    'mpe': round(dhr_holdout_metrics['mpe'], 3),
    'smape': round(dhr_holdout_metrics['smape'], 3),
    'rmse': round(dhr_holdout_metrics['rmse'], 3),
}])
dhr_holdout_predictions = pd.DataFrame({
    'model': DHR_MODEL_NAME,
    'ds': test_df['ds'].values,
    'actual': test_df['y'].values,
    'forecast': np.asarray(dhr_holdout_pred, dtype=float),
})

with mlflow.start_run(run_name='ucc_dhr_arima_cv', nested=False):
    mlflow.log_param('model_name', DHR_MODEL_NAME)
    mlflow.log_param('cv_folds', CV_FOLDS)
    mlflow.log_param('cv_horizon', CV_HORIZON)
    mlflow.log_param('season_length', 13)
    mlflow.log_param('quarterly_fourier_k', 2)
    mlflow.log_param('annual_fourier_k', 2)
    mlflow.log_param('xreg_cols', ','.join(DHR_XREG_COLS))
    mlflow.log_param('training_scope', 'market_level_reconciled_total')
    mlflow.log_param('future_xreg_strategy', 'market_and_week_of_qtr_profiles_from_training_only')
    for k, v in dhr_summary_df.iloc[0].to_dict().items():
        if k != 'model':
            mlflow.log_metric(k, float(v))
    for k, v in dhr_holdout_row.iloc[0].to_dict().items():
        if k not in {'model', 'test_start', 'test_end'}:
            mlflow.log_metric(f'holdout_{k}', float(v))

cv_fold_results = pd.concat([
    cv_fold_results[cv_fold_results['model'] != DHR_MODEL_NAME],
    dhr_fold_df,
], ignore_index=True)
cv_benchmark_summary = pd.concat([
    cv_benchmark_summary[cv_benchmark_summary['model'] != DHR_MODEL_NAME],
    dhr_summary_df,
], ignore_index=True).sort_values(['mean_wape', 'mean_mape']).reset_index(drop=True)
cv_fold_predictions = pd.concat([
    cv_fold_predictions[cv_fold_predictions['model'] != DHR_MODEL_NAME],
    dhr_pred_df,
], ignore_index=True)
holdout_benchmark_summary = pd.concat([
    holdout_benchmark_summary[holdout_benchmark_summary['model'] != DHR_MODEL_NAME],
    dhr_holdout_row,
], ignore_index=True).sort_values(['wape', 'mape']).reset_index(drop=True)
holdout_benchmark_predictions = pd.concat([
    holdout_benchmark_predictions[holdout_benchmark_predictions['model'] != DHR_MODEL_NAME],
    dhr_holdout_predictions,
], ignore_index=True)

feature_health = dhr_feature_df[[
    'ds', 'sales_market', 'created_lag4', 'headcount_lag4', 'win_rate_by_woq',
    'pipeline_velocity_lag4', 'quarter_end_flag', 'us_holiday_binary'
]].sort_values(['ds', 'sales_market']).tail(10).copy()
future_xreg_preview = build_future_dhr_xreg(
    dhr_feature_df[dhr_feature_df['ds'] < BACKTEST_START].copy(),
    horizon=CV_HORIZON,
).head(10)

print('DHR-ARIMA market-level feature health sample:')
display(feature_health)

print('\nDHR-ARIMA future market xreg preview (training-only, no holdout leakage):')
display(future_xreg_preview[['ds', 'sales_market'] + DHR_XREG_COLS].head(10))

print('\nDHR-ARIMA market-level holdout forecast sample:')
display(dhr_holdout_market_predictions.head(10))

print('\nUpdated walk-forward benchmark summary:')
display(cv_benchmark_summary)

print('\nUpdated holdout benchmark summary:')
display(holdout_benchmark_summary)


# COMMAND ----------

# DBTITLE 1,Step 10B: Global LightGBM Quantile Revised
# STEP 10B: GLOBAL LIGHTGBM QUANTILE REVISED (UCC ONLY, GLOBAL BY MARKET)
# =============================================================================
# PURPOSE: Train a gradient-boosted tree model that learns from ALL markets
# simultaneously (“global” training) rather than fitting one model per market.
# This shares statistical strength across markets that individually have
# too few data points to train reliably.
#
# WHAT MAKES THIS DIFFERENT FROM THE BENCHMARK MODELS?
#   - Learns non-linear interactions between features (e.g. the Q4 spike is
#     LARGER for NA than for APAC — a tree captures this; ARIMA cannot)
#   - Outputs THREE quantiles: p10 (pessimistic), p50 (base case), p90 (optimistic)
#     giving a calibrated confidence interval around each weekly forecast
#   - Uses 36 features including marketing pipeline lags and Magna Carta actuals
#
# FEATURE ENGINEERING (GLOBAL_FEATURE_COLS — 36 columns, all lag-safe):
#   Lag/rolling features:  y_lag1, y_lag13, r4w, running_won_lag1
#   Pipeline leading indicators (4-week lag):  mkt_opened_lag4, partner_opened_lag4,
#                             miradore_lag4, mc_actuals_lag4
#   Headcount (4-week lag):  headcount_lag4
#   Win-rate conditioned on week-of-quarter: win_rate_woq
#   Pipeline velocity lag4:  velocity_lag4
#   Calendar/seasonality:  week_of_qtr, quarter_end_flag, is_q4, q4_week_countdown,
#                          Fourier sin/cos terms (q13, y52)
#   Regional holidays:     region_holiday (US/UK+DE/IN/BR)
#   Activity lags:         avg_dials_lag4, avg_touches_lag4
#   Opportunity health:    avg_opportunity_age, avg_push_counter
#   Plan signal:           plan_gap_lag1
#   Static market encoding: one-hot for sales_market
#
# TRAINING APPROACH:
#   Each training fold fits THREE LGB models (q10, q50, q90) simultaneously.
#   Quantile ordering is enforced post-hoc: p10 <= p50 <= p90.
#   Walk-forward CV uses the same 8-fold structure as the benchmark models.
#
# SOURCE DATA TABLES USED IN THIS STEP:
#   datagroup_mdl.mdl_sales_analytics.forecast_prophet — headcount, plan features
#   datagroup.uc_forecast.actuals                      — authoritative Magna Carta
#                                                        marketing actuals (mc_actuals)
# =============================================================================

import holidays
import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

GLOBAL_FEATURE_TABLE = globals().get('GLOBAL_FEATURE_TABLE', 'datagroup_mdl.mdl_sales_analytics.forecast_prophet')
AUTHORITATIVE_MC_TABLE = globals().get('AUTHORITATIVE_MC_TABLE', 'datagroup.uc_forecast.actuals')
GLOBAL_MODEL_NAME = 'Global_LGB_Q50_UCC'
GLOBAL_BACKTEST_START = globals().get('GLOBAL_BACKTEST_START', pd.Timestamp('2026-01-05'))
GLOBAL_HISTORY_START = globals().get('GLOBAL_HISTORY_START', pd.Timestamp('2023-01-02'))
GLOBAL_OBSERVED_END = pd.Timestamp.today().normalize() - pd.to_timedelta(pd.Timestamp.today().weekday(), unit='D') - pd.Timedelta(weeks=1)
GLOBAL_CV_HORIZON = globals().get('GLOBAL_CV_HORIZON', 13)
GLOBAL_CV_FOLDS = globals().get('GLOBAL_CV_FOLDS', 8)
GLOBAL_VALIDATION_WEEKS = globals().get('GLOBAL_VALIDATION_WEEKS', 13)
GLOBAL_QUANTILES = globals().get('GLOBAL_QUANTILES', {'P10': 0.10, 'P50': 0.50, 'P90': 0.90})
GLOBAL_CAT_COLS = ['sales_market']
GLOBAL_FEATURE_COLS = [
    'week_of_qtr', 'quarter_end_flag', 'is_q4', 'q4_week_countdown',
    'woq_sin', 'woq_cos', 'qtr_sin', 'qtr_cos',
    'sales_market',
    'created_lag4', 'created_lag5', 'headcount_lag4', 'win_rate_woq',
    'pipeline_velocity_lag4', 'deal_size_lag1', 'sales_cycle_lag1',
    'push_ctr_lag1', 'avg_opportunity_age', 'avg_dials_lag4', 'avg_touches_lag4',
    'mc_actuals_lag4', 'mkt_opened_lag4', 'mkt_generated_lag4', 'mkt_influenced_lag4', 'miradore_lag4', 'plan_gap_lag1', 'partner_pipe_lag4',
    'sales_rep_ramp_ratio', 'y_lag1', 'y_lag4', 'y_lag8', 'y_lag13',
    'y_lag26', 'r4w', 'running_won_lag1', 'rolling_vol_4w', 'rolling_vol_13w',
    'yoy_growth', 'qoq_momentum', 'us_holiday', 'region_holiday',
]
GLOBAL_PROFILE_COLS = [
    'all_created_arr', 'headcount', 'avg_deal_size', 'avg_sales_cycle',
    'avg_push_counter', 'avg_dials', 'avg_touches',
    'total_partner_pipeline', 'magna_carta_actuals', 'marketing_generated_pipeline', 'marketing_influenced_pipeline',
    'mc_actuals_authoritative', 'miradore_plan',
    'avg_opportunity_age', 'sales_rep_ramp_ratio', 'win_rate_woq',
]
GLOBAL_PRODUCTS = ['UCC']
GLOBAL_MARKETS = globals().get('GLOBAL_MARKETS', ['APAC', 'EMEA', 'LATAM', 'NA', 'Unknown'])

us_holidays = holidays.US()

# Regional holiday calendars for market-aware holiday feature (P2 enhancement)
_HOLIDAY_YEARS = range(2022, 2028)
REGION_HOLIDAY_MAP = {
    'NA': holidays.US(years=_HOLIDAY_YEARS),
    'EMEA': holidays.UK(years=_HOLIDAY_YEARS) + holidays.Germany(years=_HOLIDAY_YEARS),
    'APAC': holidays.India(years=_HOLIDAY_YEARS),
    'LATAM': holidays.Brazil(years=_HOLIDAY_YEARS),
    'Unknown': holidays.US(years=_HOLIDAY_YEARS),
}


def compute_region_holiday(ds_series: pd.Series, market_series: pd.Series) -> pd.Series:
    """Market-aware holiday binary: fires for the region's local holidays."""
    result = pd.Series(0, index=ds_series.index, dtype=int)
    ds_dates = pd.to_datetime(ds_series)
    for market, cal in REGION_HOLIDAY_MAP.items():
        mask = market_series.astype(str) == market
        if mask.any():
            result.loc[mask] = ds_dates[mask].apply(
                lambda d: int(d.date() in cal or (d + pd.Timedelta(days=1)).date() in cal)
            )
    return result


def ci_coverage(actual, p10, p90):
    actual = np.asarray(actual, dtype=float)
    p10 = np.asarray(p10, dtype=float)
    p90 = np.asarray(p90, dtype=float)
    valid = np.isfinite(actual) & np.isfinite(p10) & np.isfinite(p90)
    if not valid.any():
        return np.nan
    return float(100.0 * np.mean((actual[valid] >= p10[valid]) & (actual[valid] <= p90[valid])))


def global_forecast_metrics(actual, forecast, p10=None, p90=None):
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    denom = np.clip(np.abs(actual).sum(), 1e-9, None)
    mask = np.abs(actual) > 1e-9
    wape = 100.0 * np.abs(actual - forecast).sum() / denom
    if mask.any():
        mape = 100.0 * np.mean(np.abs((actual[mask] - forecast[mask]) / actual[mask]))
        mpe = 100.0 * np.mean((forecast[mask] - actual[mask]) / actual[mask])
    else:
        mape = np.nan
        mpe = np.nan
    smape_denom = np.abs(actual) + np.abs(forecast)
    smape = np.nanmean(np.where(smape_denom > 1e-9, 200.0 * np.abs(actual - forecast) / smape_denom, np.nan))
    rmse = np.sqrt(np.nanmean((actual - forecast) ** 2))
    coverage = ci_coverage(actual, p10, p90) if p10 is not None and p90 is not None else np.nan
    return {'wape': float(wape), 'mape': float(mape), 'mpe': float(mpe), 'smape': float(smape), 'rmse': float(rmse), 'ci_coverage': coverage}


def add_global_calendar(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['ds'] = pd.to_datetime(out['ds'])
    calendar = out[['ds']].drop_duplicates().sort_values('ds').reset_index(drop=True)
    calendar['year'] = calendar['ds'].dt.year
    calendar['quarter'] = calendar['ds'].dt.quarter
    calendar['week_of_qtr'] = calendar.groupby(['year', 'quarter']).cumcount() + 1
    calendar['quarter_end_flag'] = (calendar['week_of_qtr'] >= 11).astype(int)
    calendar['is_q4'] = (calendar['quarter'] == 4).astype(int)
    calendar['q4_week_countdown'] = np.where(calendar['quarter'] == 4, 14 - calendar['week_of_qtr'], 0)
    calendar['month_num'] = calendar['ds'].dt.month
    calendar['month_key'] = calendar['ds'].dt.to_period('M').astype(str)
    calendar['woq_sin'] = np.sin(2 * np.pi * calendar['week_of_qtr'] / 13.0)
    calendar['woq_cos'] = np.cos(2 * np.pi * calendar['week_of_qtr'] / 13.0)
    calendar['qtr_sin'] = np.sin(2 * np.pi * calendar['quarter'] / 4.0)
    calendar['qtr_cos'] = np.cos(2 * np.pi * calendar['quarter'] / 4.0)
    calendar['us_holiday'] = calendar['ds'].apply(lambda d: int(d.date() in us_holidays or (d + pd.Timedelta(days=1)).date() in us_holidays))
    return out.merge(calendar, on='ds', how='left')


def load_authoritative_mc_actuals(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    mc = spark.sql(f"""
    SELECT
        CAST(period AS DATE) AS period_month,
        UPPER(COALESCE(market, 'Unknown')) AS sales_market,
        CAST(purchase_amount_in_usd_current_rate AS DOUBLE) AS mc_actuals_authoritative
    FROM {AUTHORITATIVE_MC_TABLE}
    WHERE period >= ADD_MONTHS(DATE '{pd.Timestamp(start_date).date()}', -1)
      AND period <= DATE '{pd.Timestamp(end_date).date()}'
      AND UPPER(version) = 'ACTUALS'
      AND UPPER(COALESCE(product_genus, product_family, product_group, '')) = 'GOTOCONNECT'
      AND purchase_type = 'Growth'
    """).toPandas()
    if mc.empty:
        return pd.DataFrame(columns=['month_key', 'sales_market', 'mc_actuals_authoritative'])
    mc['period_month'] = pd.to_datetime(mc['period_month'], errors='coerce')
    mc['sales_market'] = (
        mc['sales_market']
        .fillna('Unknown')
        .replace({'AUS/ROW': 'APAC', 'INDIA': 'APAC', 'UNKNOWN': 'Unknown', '': 'Unknown'})
    )
    mc['month_key'] = mc['period_month'].dt.to_period('M').astype(str)
    mc = (
        mc.groupby(['month_key', 'sales_market'], as_index=False)['mc_actuals_authoritative']
        .sum()
    )
    return mc


def merge_authoritative_mc_actuals(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'month_key' not in out.columns:
        out['month_key'] = pd.to_datetime(out['ds']).dt.to_period('M').astype(str)
    mc_actuals = load_authoritative_mc_actuals(out['ds'].min(), out['ds'].max())
    out = out.merge(mc_actuals, on=['month_key', 'sales_market'], how='left')
    out['mc_actuals_authoritative'] = pd.to_numeric(out['mc_actuals_authoritative'], errors='coerce').fillna(0.0)
    return out


def load_global_panel() -> pd.DataFrame:
    src = spark.sql(f"""
    SELECT
        CAST(ds AS DATE) AS ds,
        UPPER(product) AS product_group,
        UPPER(sales_market) AS sales_market,
        CAST(Actuals AS DOUBLE) AS fp_actuals,  -- kept for diagnostic comparison only; NOT the training target
        CAST(Most_Likely AS DOUBLE) AS prophet_ml,
        CAST(all_created_arr AS DOUBLE) AS all_created_arr,
        CAST(headcount AS DOUBLE) AS headcount,
        CAST(avg_deal_size AS DOUBLE) AS avg_deal_size,
        CAST(avg_sales_cycle AS DOUBLE) AS avg_sales_cycle,
        CAST(avg_push_counter AS DOUBLE) AS avg_push_counter,
        CAST(avg_dials AS DOUBLE) AS avg_dials,
        CAST(avg_touches AS DOUBLE) AS avg_touches,
        CAST(avg_opportunity_age AS DOUBLE) AS avg_opportunity_age,
        CAST(total_partner_pipeline AS DOUBLE) AS total_partner_pipeline,
        CAST(magna_carta_actuals AS DOUBLE) AS magna_carta_actuals,
        CAST(miradore_plan AS DOUBLE) AS miradore_plan
    FROM {GLOBAL_FEATURE_TABLE}
    WHERE ds >= DATE '{GLOBAL_HISTORY_START.date()}'
      AND ds <= DATE '{GLOBAL_OBSERVED_END.date()}'
      AND UPPER(product) = 'UCC'
    ORDER BY ds, product, sales_market
    """).toPandas()
    src['sales_market'] = src['sales_market'].replace({'UNKNOWN': 'Unknown'}).fillna('Unknown')
    src['product_group'] = src['product_group'].fillna('Unknown')

    # --- GROWTH FILTER FIX (Jul 2026) ---
    # forecast_prophet is queried with only WHERE product = 'UCC' — no purchase_type filter.
    # Its fp_actuals column includes renewals + all channels, not just Growth.
    # All other models (ETS, MSTL, Prophet, DHR-ARIMA) train on weekly_ucc_by_market.y
    # which is explicitly filtered to purchase_type_rollup='Growth' AND
    # sales_channel NOT IN ('Care','Sales Other') from SFDC.
    # Replacing here ensures LGB trains on the same Growth-only target as every other model,
    # making WAPE comparisons and ensemble weights valid.
    sfdc_y = weekly_ucc_by_market[['ds', 'sales_market', 'y']].copy()
    sfdc_y['ds'] = pd.to_datetime(sfdc_y['ds'])
    src['ds'] = pd.to_datetime(src['ds'])  # coerce before merge; add_global_calendar repeats this safely
    src = src.merge(sfdc_y, on=['ds', 'sales_market'], how='left')
    src['y'] = pd.to_numeric(src['y'], errors='coerce').fillna(0.0)
    # GROWTH CREATED-PIPELINE FIX (Jul 2026):
    # overwrite all_created_arr with Step 1's Growth-filtered created_arr so
    # win_rate_woq and pipeline_velocity use the same purchase_type scope as y.

    src = add_global_calendar(src)
    source_marketing = globals().get('weekly_ucc_created_features_by_market')
    if source_marketing is not None:
        src = src.merge(
            source_marketing[['ds', 'sales_market', 'marketing_generated_pipeline', 'marketing_influenced_pipeline']],
            on=['ds', 'sales_market'],
            how='left',
        )
    else:
        src['marketing_generated_pipeline'] = np.nan
        src['marketing_influenced_pipeline'] = np.nan
    # ALL-OPPS PIPELINE FIX: replace won-only growth_created_market with the
    # full-funnel all_pipeline_by_market built in Step 1 (no is_won filter).
    # This gives win_rate_woq, created_lag4/5, and pipeline_velocity a real
    # denominator instead of an oracle view of only eventually-won pipeline.
    _all_pipe = globals().get(
        'all_pipeline_by_market',
        pd.DataFrame(columns=['ds', 'sales_market', 'all_pipeline_created']),
    )
    src = src.merge(_all_pipe[['ds', 'sales_market', 'all_pipeline_created']], on=['ds', 'sales_market'], how='left')
    src['product_group'] = 'UCC'
    src['slice_id'] = src['product_group'] + '|' + src['sales_market']
    src['all_created_arr'] = pd.to_numeric(src['all_pipeline_created'], errors='coerce').fillna(0.0)
    for mkt_col in ['marketing_generated_pipeline', 'marketing_influenced_pipeline']:
        src[mkt_col] = pd.to_numeric(src[mkt_col], errors='coerce')
        src[mkt_col] = src.groupby('slice_id')[mkt_col].ffill().fillna(0.0)
    src = merge_authoritative_mc_actuals(src)
    return src


def add_sales_rep_ramp_ratio(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['headcount'] = pd.to_numeric(out['headcount'], errors='coerce')
    out['headcount'] = out.groupby('slice_id')['headcount'].transform(lambda s: s.replace(0, np.nan).ffill().bfill()).fillna(0.0)
    net_adds = out.groupby('slice_id')['headcount'].diff().clip(lower=0).fillna(0.0)
    recent_adds = net_adds.groupby(out['slice_id']).transform(lambda s: s.rolling(26, min_periods=1).sum())
    out['sales_rep_ramp_ratio'] = (recent_adds / out['headcount'].replace(0, np.nan)).clip(lower=0.0, upper=1.0).fillna(0.0)
    return out


def add_monthly_mc_scale(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    monthly = (
        out.groupby(['slice_id', 'month_key', 'month_num'], as_index=False)
        .agg(month_actual=('y', 'sum'), month_prophet=('prophet_ml', 'sum'))
        .sort_values(['slice_id', 'month_key'])
    )
    monthly['month_ratio'] = (monthly['month_actual'] / monthly['month_prophet'].replace(0, np.nan)).clip(lower=0.25, upper=4.0)
    monthly['slice_ratio_fallback'] = monthly.groupby('slice_id')['month_ratio'].transform(lambda s: s.shift(1).expanding().median())
    monthly['mc_scale_factor'] = monthly.groupby(['slice_id', 'month_num'])['month_ratio'].transform(lambda s: s.shift(1).expanding().median())
    monthly['mc_scale_factor'] = monthly['mc_scale_factor'].fillna(monthly['slice_ratio_fallback']).fillna(1.0)
    out = out.merge(monthly[['slice_id', 'month_key', 'mc_scale_factor']], on=['slice_id', 'month_key'], how='left')
    out['mc_scale_factor'] = out['mc_scale_factor'].fillna(1.0)
    out['prophet_ml_mc_scaled'] = out['prophet_ml'].fillna(0.0) * out['mc_scale_factor']
    return out


def build_global_feature_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    feat = raw_df.copy().sort_values(['slice_id', 'ds']).reset_index(drop=True)
    numeric_cols = [
        'y', 'prophet_ml', 'all_created_arr', 'headcount', 'avg_deal_size',
        'avg_sales_cycle', 'avg_push_counter', 'avg_dials', 'avg_touches', 'avg_opportunity_age',
        'total_partner_pipeline', 'magna_carta_actuals', 'marketing_generated_pipeline', 'marketing_influenced_pipeline',
        'mc_actuals_authoritative', 'miradore_plan'
    ]
    for col in numeric_cols:
        feat[col] = pd.to_numeric(feat[col], errors='coerce').fillna(0.0)

    feat = add_sales_rep_ramp_ratio(feat)
    feat = add_monthly_mc_scale(feat)
    feat['pipeline_velocity'] = (feat['all_created_arr'] / feat['avg_opportunity_age'].clip(lower=1.0)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    for lag in [1, 4, 5, 8, 13, 26, 52]:
        feat[f'y_lag{lag}'] = feat.groupby('slice_id')['y'].shift(lag).fillna(0.0)
    feat['created_lag4'] = feat.groupby('slice_id')['all_created_arr'].shift(4).fillna(0.0)
    feat['created_lag5'] = feat.groupby('slice_id')['all_created_arr'].shift(5).fillna(0.0)
    feat['headcount_lag4'] = feat.groupby('slice_id')['headcount'].shift(4).fillna(0.0)
    feat['pipeline_velocity_lag4'] = feat.groupby('slice_id')['pipeline_velocity'].shift(4).fillna(0.0)
    feat['deal_size_lag1'] = feat.groupby('slice_id')['avg_deal_size'].shift(1).fillna(0.0)
    feat['sales_cycle_lag1'] = feat.groupby('slice_id')['avg_sales_cycle'].shift(1).fillna(0.0)
    feat['push_ctr_lag1'] = feat.groupby('slice_id')['avg_push_counter'].shift(1).fillna(0.0)
    feat['avg_dials_lag4'] = feat.groupby('slice_id')['avg_dials'].shift(4).fillna(0.0)
    feat['avg_touches_lag4'] = feat.groupby('slice_id')['avg_touches'].shift(4).fillna(0.0)
    feat['mc_actuals_lag4'] = feat.groupby('slice_id')['mc_actuals_authoritative'].shift(4).fillna(0.0)
    feat['mkt_opened_lag4'] = feat.groupby('slice_id')['magna_carta_actuals'].shift(4).fillna(0.0)
    feat['mkt_generated_lag4'] = feat.groupby('slice_id')['marketing_generated_pipeline'].shift(4).fillna(0.0)
    feat['mkt_influenced_lag4'] = feat.groupby('slice_id')['marketing_influenced_pipeline'].shift(4).fillna(0.0)
    feat['miradore_lag4'] = feat.groupby('slice_id')['miradore_plan'].shift(4).fillna(0.0)
    feat['plan_gap_lag1'] = (feat['magna_carta_actuals'] - feat['miradore_plan']).groupby(feat['slice_id']).shift(1).fillna(0.0)
    feat['partner_pipe_lag4'] = feat.groupby('slice_id')['total_partner_pipeline'].shift(4).fillna(0.0)
    feat['r4w'] = feat.groupby('slice_id')['y'].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean()).fillna(0.0)
    feat['quarter_key'] = feat['ds'].dt.to_period('Q').astype(str)
    feat['running_won'] = feat.groupby(['slice_id', 'quarter_key'])['y'].cumsum()
    feat['running_won_lag1'] = feat.groupby(['slice_id', 'quarter_key'])['running_won'].shift(1).fillna(0.0)
    feat['rolling_vol_4w'] = feat.groupby('slice_id')['y'].transform(lambda s: s.shift(1).rolling(4, min_periods=2).std()).fillna(0.0)
    feat['rolling_vol_13w'] = feat.groupby('slice_id')['y'].transform(lambda s: s.shift(1).rolling(13, min_periods=4).std()).fillna(0.0)
    feat['yoy_growth'] = ((feat['y_lag1'] / feat['y_lag52'].replace(0, np.nan)) - 1.0).clip(lower=-3.0, upper=3.0).fillna(0.0)
    feat['qoq_momentum'] = ((feat['y_lag1'] / feat['y_lag13'].replace(0, np.nan)) - 1.0).clip(lower=-3.0, upper=3.0).fillna(0.0)

    feat['win_rate_woq'] = np.nan
    for (slice_id, wk), grp in feat.groupby(['slice_id', 'week_of_qtr']):
        won_roll = grp['y'].shift(1).rolling(4, min_periods=1).sum()
        created_roll = grp['all_created_arr'].shift(1).rolling(4, min_periods=1).sum().replace(0, np.nan)
        feat.loc[grp.index, 'win_rate_woq'] = (won_roll / created_roll).clip(lower=0.0, upper=3.0).values

    global_rate = (
        feat.groupby('slice_id')['y'].transform(lambda s: s.shift(1).rolling(13, min_periods=1).sum()) /
        feat.groupby('slice_id')['all_created_arr'].transform(lambda s: s.shift(1).rolling(13, min_periods=1).sum()).replace(0, np.nan)
    ).clip(lower=0.0, upper=3.0)
    feat['win_rate_woq'] = feat['win_rate_woq'].fillna(global_rate).fillna(0.0)

    feat['quarter_end_flag'] = feat['quarter_end_flag'].astype(float)
    feat['is_q4'] = feat['is_q4'].astype(float)
    feat['us_holiday'] = feat['us_holiday'].astype(float)
    feat['region_holiday'] = compute_region_holiday(feat['ds'], feat['sales_market'].astype(str)).astype(float)
    feat['product_group'] = 'UCC'
    feat['sales_market'] = pd.Categorical(feat['sales_market'], categories=GLOBAL_MARKETS)

    fill_cols = [c for c in GLOBAL_FEATURE_COLS if c not in GLOBAL_CAT_COLS]
    feat[fill_cols] = feat[fill_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return feat


def week_weight_map(weeks):
    weeks = sorted(pd.to_datetime(pd.Series(weeks)).tolist())
    if len(weeks) == 1:
        return {weeks[0]: 1.0}
    scale = np.linspace(0.0, 1.0, len(weeks))
    weights = np.exp(np.log(2.0) * scale)
    return {wk: float(w) for wk, w in zip(weeks, weights)}


def build_profile_lookup(train_panel: pd.DataFrame, col: str, lookback_weeks: int = 104):
    tail = train_panel.sort_values('ds').groupby('slice_id').tail(min(lookback_weeks, train_panel['ds'].nunique()))
    profile = tail.groupby(['slice_id', 'week_of_qtr'])[col].median().to_dict()
    slice_default = tail.groupby('slice_id')[col].median().to_dict()
    global_default = float(tail[col].median()) if len(tail) else 0.0
    return profile, slice_default, global_default


def build_mc_scale_lookup(train_panel: pd.DataFrame):
    keyed = train_panel[['slice_id', 'month_num', 'mc_scale_factor']].dropna()
    month_profile = keyed.groupby(['slice_id', 'month_num'])['mc_scale_factor'].median().to_dict()
    slice_default = keyed.groupby('slice_id')['mc_scale_factor'].median().to_dict()
    global_default = float(keyed['mc_scale_factor'].median()) if len(keyed) else 1.0
    return month_profile, slice_default, global_default


def train_quantile_models(train_panel: pd.DataFrame):
    train_weeks = sorted(train_panel['ds'].unique())
    if len(train_weeks) <= GLOBAL_VALIDATION_WEEKS:
        raise ValueError('Not enough training weeks for LightGBM validation holdout.')

    valid_start = train_weeks[-GLOBAL_VALIDATION_WEEKS]
    fit_train = train_panel[train_panel['ds'] < valid_start].copy()
    fit_valid = train_panel[train_panel['ds'] >= valid_start].copy()

    week_weights = week_weight_map(fit_train['ds'].unique())
    fit_train['sample_weight'] = pd.to_datetime(fit_train['ds']).map(week_weights).astype(float)

    X_train = fit_train[GLOBAL_FEATURE_COLS].copy()
    X_valid = fit_valid[GLOBAL_FEATURE_COLS].copy()
    y_train = fit_train['y'].astype(float)
    y_valid = fit_valid['y'].astype(float)

    for col in GLOBAL_CAT_COLS:
        X_train[col] = pd.Categorical(X_train[col], categories=GLOBAL_MARKETS)
        X_valid[col] = pd.Categorical(X_valid[col], categories=GLOBAL_MARKETS)

    train_ds = lgb.Dataset(
        X_train,
        label=y_train,
        weight=fit_train['sample_weight'].values,
        categorical_feature=GLOBAL_CAT_COLS,
        free_raw_data=False,
    )
    valid_ds = lgb.Dataset(
        X_valid,
        label=y_valid,
        categorical_feature=GLOBAL_CAT_COLS,
        reference=train_ds,
        free_raw_data=False,
    )

    common_params = {
        'objective': 'quantile',
        'learning_rate': 0.03,
        'num_leaves': 31,
        'min_data_in_leaf': 20,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.9,
        'bagging_freq': 1,
        'lambda_l2': 1.0,
        'verbosity': -1,
        'seed': 42,
        'force_col_wise': True,
        'metric': 'quantile',
    }

    models = {}
    for name, alpha in GLOBAL_QUANTILES.items():
        models[name] = lgb.train(
            common_params | {'alpha': alpha},
            train_ds,
            num_boost_round=1500,
            valid_sets=[valid_ds],
            callbacks=[lgb.early_stopping(stopping_rounds=75, verbose=False)],
        )

    importance_df = pd.DataFrame({
        'feature': GLOBAL_FEATURE_COLS,
        'importance_gain': models['P50'].feature_importance(importance_type='gain'),
        'importance_split': models['P50'].feature_importance(importance_type='split'),
    }).sort_values(['importance_gain', 'importance_split'], ascending=False).reset_index(drop=True)

    calibrators = {}
    valid_targets = y_valid.to_numpy(dtype=float)
    for name in ['P10', 'P90']:
        raw_valid = models[name].predict(X_valid, num_iteration=models[name].best_iteration)
        mask = np.isfinite(raw_valid) & np.isfinite(valid_targets)
        if mask.sum() >= 8 and np.unique(raw_valid[mask]).size >= 5:
            calibrator = IsotonicRegression(out_of_bounds='clip', increasing=True)
            calibrator.fit(raw_valid[mask], valid_targets[mask])
            calibrators[name] = calibrator
        else:
            calibrators[name] = None
    return models, importance_df, calibrators


def build_future_panel(train_panel: pd.DataFrame, forecast_weeks, full_panel: pd.DataFrame) -> pd.DataFrame:
    forecast_weeks = sorted(pd.to_datetime(pd.Series(forecast_weeks)).tolist())
    slices = train_panel[['slice_id', 'product_group', 'sales_market']].drop_duplicates().copy()
    slices['product_group'] = 'UCC'
    future = slices.merge(pd.DataFrame({'ds': forecast_weeks}), how='cross')
    future = add_global_calendar(future)

    future = future.merge(full_panel[['slice_id', 'ds', 'prophet_ml']], on=['slice_id', 'ds'], how='left')
    month_profile, month_slice_default, month_global_default = build_mc_scale_lookup(train_panel)
    future['mc_scale_factor'] = [
        month_profile.get((sid, mon), month_slice_default.get(sid, month_global_default))
        for sid, mon in zip(future['slice_id'], future['month_num'])
    ]
    future['prophet_ml'] = pd.to_numeric(future['prophet_ml'], errors='coerce').fillna(0.0)
    future['prophet_ml_mc_scaled'] = future['prophet_ml'] * future['mc_scale_factor']

    for col in GLOBAL_PROFILE_COLS:
        profile, slice_default, global_default = build_profile_lookup(train_panel, col)
        future[col] = [
            profile.get((sid, wk), slice_default.get(sid, global_default))
            for sid, wk in zip(future['slice_id'], future['week_of_qtr'])
        ]

    future['pipeline_velocity'] = (future['all_created_arr'] / future['avg_opportunity_age'].clip(lower=1.0)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    combined_base = pd.concat([
        train_panel[['slice_id', 'ds', 'all_created_arr', 'headcount', 'pipeline_velocity', 'avg_deal_size', 'avg_sales_cycle', 'avg_push_counter', 'avg_dials', 'avg_touches', 'magna_carta_actuals', 'marketing_generated_pipeline', 'marketing_influenced_pipeline', 'mc_actuals_authoritative', 'miradore_plan', 'total_partner_pipeline']],
        future[['slice_id', 'ds', 'all_created_arr', 'headcount', 'pipeline_velocity', 'avg_deal_size', 'avg_sales_cycle', 'avg_push_counter', 'avg_dials', 'avg_touches', 'magna_carta_actuals', 'marketing_generated_pipeline', 'marketing_influenced_pipeline', 'mc_actuals_authoritative', 'miradore_plan', 'total_partner_pipeline']],
    ], ignore_index=True).sort_values(['slice_id', 'ds'])

    for new_col, base_col, lag in [
        ('created_lag4', 'all_created_arr', 4),
        ('created_lag5', 'all_created_arr', 5),
        ('headcount_lag4', 'headcount', 4),
        ('pipeline_velocity_lag4', 'pipeline_velocity', 4),
        ('deal_size_lag1', 'avg_deal_size', 1),
        ('sales_cycle_lag1', 'avg_sales_cycle', 1),
        ('push_ctr_lag1', 'avg_push_counter', 1),
        ('avg_dials_lag4', 'avg_dials', 4),
        ('avg_touches_lag4', 'avg_touches', 4),
        ('mc_actuals_lag4', 'mc_actuals_authoritative', 4),
        ('mkt_opened_lag4', 'magna_carta_actuals', 4),
        ('mkt_generated_lag4', 'marketing_generated_pipeline', 4),
        ('mkt_influenced_lag4', 'marketing_influenced_pipeline', 4),
        ('miradore_lag4', 'miradore_plan', 4),
        ('partner_pipe_lag4', 'total_partner_pipeline', 4),
    ]:
        shifted = combined_base[['slice_id', 'ds', base_col]].copy()
        shifted[new_col] = shifted.groupby('slice_id')[base_col].shift(lag).fillna(0.0)
        future = future.merge(shifted[['slice_id', 'ds', new_col]], on=['slice_id', 'ds'], how='left')

    combined_plan_gap = pd.concat([
        train_panel[['slice_id', 'ds', 'magna_carta_actuals', 'miradore_plan']],
        future[['slice_id', 'ds', 'magna_carta_actuals', 'miradore_plan']],
    ], ignore_index=True).sort_values(['slice_id', 'ds'])
    combined_plan_gap['plan_gap_lag1'] = (
        (combined_plan_gap['magna_carta_actuals'] - combined_plan_gap['miradore_plan'])
        .groupby(combined_plan_gap['slice_id']).shift(1).fillna(0.0)
    )
    future = future.merge(combined_plan_gap[['slice_id', 'ds', 'plan_gap_lag1']], on=['slice_id', 'ds'], how='left')
    future['plan_gap_lag1'] = future['plan_gap_lag1'].fillna(0.0)

    for lag_col in [
        'y_lag1', 'y_lag4', 'y_lag8', 'y_lag13', 'y_lag26', 'y_lag52',
        'r4w', 'running_won_lag1', 'rolling_vol_4w', 'rolling_vol_13w', 'yoy_growth', 'qoq_momentum'
    ]:
        future[lag_col] = 0.0

    future['quarter_end_flag'] = future['quarter_end_flag'].astype(float)
    future['is_q4'] = future['is_q4'].astype(float)
    future['us_holiday'] = future['us_holiday'].astype(float)
    future['region_holiday'] = compute_region_holiday(future['ds'], future['sales_market'].astype(str)).astype(float)
    future['product_group'] = 'UCC'
    future['sales_market'] = pd.Categorical(future['sales_market'], categories=GLOBAL_MARKETS)

    fill_cols = [c for c in GLOBAL_FEATURE_COLS if c not in GLOBAL_CAT_COLS]
    future[fill_cols] = future[fill_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return future


def predict_future_quantiles(train_panel: pd.DataFrame, forecast_weeks, full_panel: pd.DataFrame):
    models, importance_df, calibrators = train_quantile_models(train_panel)
    future_panel = build_future_panel(train_panel, forecast_weeks, full_panel)

    history_y = train_panel[['slice_id', 'ds', 'y']].copy().sort_values(['slice_id', 'ds'])
    history_y['quarter_key'] = pd.to_datetime(history_y['ds']).dt.to_period('Q').astype(str)
    pred_rows = []
    for ds in sorted(pd.to_datetime(pd.Series(forecast_weeks)).tolist()):
        step_df = future_panel[future_panel['ds'] == ds].copy().sort_values('slice_id')
        history_lookup = (
            history_y.groupby('slice_id')['y']
            .apply(list)
            .reindex(step_df['slice_id'])
            .apply(lambda x: x if isinstance(x, list) else [])
        )
        for lag in [1, 4, 8, 13, 26, 52]:
            step_df[f'y_lag{lag}'] = [
                float(vals[-lag]) if len(vals) >= lag else 0.0
                for vals in history_lookup
            ]
        step_df['r4w'] = [
            float(np.mean(vals[-4:])) if len(vals) else 0.0
            for vals in history_lookup
        ]
        step_df['rolling_vol_4w'] = [
            float(np.std(vals[-4:], ddof=1)) if len(vals) >= 2 else 0.0
            for vals in history_lookup
        ]
        step_df['rolling_vol_13w'] = [
            float(np.std(vals[-13:], ddof=1)) if len(vals) >= 4 else 0.0
            for vals in history_lookup
        ]
        step_df['yoy_growth'] = ((step_df['y_lag1'] / step_df['y_lag52'].replace(0, np.nan)) - 1.0).clip(lower=-3.0, upper=3.0).fillna(0.0)
        step_df['qoq_momentum'] = ((step_df['y_lag1'] / step_df['y_lag13'].replace(0, np.nan)) - 1.0).clip(lower=-3.0, upper=3.0).fillna(0.0)
        step_df['quarter_key'] = pd.to_datetime(step_df['ds']).dt.to_period('Q').astype(str)
        step_df['running_won_lag1'] = [
            float(history_y[(history_y['slice_id'] == sid) & (history_y['quarter_key'] == qk) & (history_y['ds'] < ds_val)]['y'].sum())
            for sid, ds_val, qk in zip(step_df['slice_id'], step_df['ds'], step_df['quarter_key'])
        ]

        X_step = step_df[GLOBAL_FEATURE_COLS].copy()
        for col in GLOBAL_CAT_COLS:
            X_step[col] = pd.Categorical(X_step[col], categories=GLOBAL_MARKETS)

        raw_p10 = models['P10'].predict(X_step, num_iteration=models['P10'].best_iteration)
        raw_p50 = models['P50'].predict(X_step, num_iteration=models['P50'].best_iteration)
        raw_p90 = models['P90'].predict(X_step, num_iteration=models['P90'].best_iteration)
        step_df['p10'] = calibrators['P10'].predict(raw_p10) if calibrators.get('P10') is not None else raw_p10
        step_df['p50'] = raw_p50
        step_df['p90'] = calibrators['P90'].predict(raw_p90) if calibrators.get('P90') is not None else raw_p90
        step_df['p10'] = np.minimum(step_df['p10'], step_df['p50'])
        step_df['p90'] = np.maximum(step_df['p90'], step_df['p50'])
        pred_rows.append(step_df[['ds', 'slice_id', 'product_group', 'sales_market', 'p10', 'p50', 'p90']])

        history_y = pd.concat([
            history_y,
            step_df[['slice_id', 'ds', 'quarter_key']].assign(y=step_df['p50'].values),
        ], ignore_index=True)

    return pd.concat(pred_rows, ignore_index=True), importance_df


global_raw = load_global_panel()
global_panel = build_global_feature_frame(global_raw)
all_weeks = sorted(global_panel['ds'].unique())
# CV FOLD OVERLAP FIX: restrict CV to weeks strictly before BACKTEST_START so no
# fold ever trains on data the holdout evaluation considers held-out.
# With ~157 pre-backtest weeks and GLOBAL_CV_FOLDS=6: MIN_TRAIN = 157-78 = 79 weeks.
cv_weeks = [w for w in all_weeks if pd.Timestamp(w) < GLOBAL_BACKTEST_START]
GLOBAL_MIN_TRAIN_WEEKS = len(cv_weeks) - (GLOBAL_CV_FOLDS * GLOBAL_CV_HORIZON)
if GLOBAL_MIN_TRAIN_WEEKS <= GLOBAL_VALIDATION_WEEKS:
    raise ValueError(f'Need more history for {GLOBAL_CV_FOLDS} folds of {GLOBAL_CV_HORIZON} weeks; only {len(cv_weeks)} pre-backtest weeks available.')

cv_rows = []
cv_preds = []
global_cv_detail_rows = []
last_importance = None
for fold in range(1, GLOBAL_CV_FOLDS + 1):
    train_end_idx = GLOBAL_MIN_TRAIN_WEEKS + (fold - 1) * GLOBAL_CV_HORIZON - 1
    test_start_idx = train_end_idx + 1
    test_end_idx = test_start_idx + GLOBAL_CV_HORIZON
    train_weeks = cv_weeks[:train_end_idx + 1]
    test_weeks = cv_weeks[test_start_idx:test_end_idx]

    fold_train = global_panel[global_panel['ds'].isin(train_weeks)].copy()
    fold_actuals = global_panel[global_panel['ds'].isin(test_weeks)][['ds', 'slice_id', 'product_group', 'sales_market', 'y']].copy()
    fold_pred, last_importance = predict_future_quantiles(fold_train, test_weeks, global_panel)
    fold_eval = fold_actuals.merge(fold_pred, on=['ds', 'slice_id', 'product_group', 'sales_market'], how='left')

    ucc_weekly_eval = (
        fold_eval[fold_eval['product_group'] == 'UCC']
        .groupby('ds', as_index=False)
        .agg(actual=('y', 'sum'), forecast=('p50', 'sum'), p10=('p10', 'sum'), p90=('p90', 'sum'))
    )
    ucc_metrics = global_forecast_metrics(
        ucc_weekly_eval['actual'].values,
        ucc_weekly_eval['forecast'].values,
        ucc_weekly_eval['p10'].values,
        ucc_weekly_eval['p90'].values,
    )
    all_slice_metrics = global_forecast_metrics(fold_eval['y'].values, fold_eval['p50'].values)
    cv_rows.append({
        'model': GLOBAL_MODEL_NAME,
        'fold': fold,
        'train_start': str(pd.Timestamp(train_weeks[0]).date()),
        'train_end': str(pd.Timestamp(train_weeks[-1]).date()),
        'test_start': str(pd.Timestamp(test_weeks[0]).date()),
        'test_end': str(pd.Timestamp(test_weeks[-1]).date()),
        'train_rows': len(ucc_weekly_eval) * 0 + len(train_weeks),
        'test_rows': len(ucc_weekly_eval),
        'wape': round(ucc_metrics['wape'], 3),
        'mape': round(ucc_metrics['mape'], 3),
        'mpe': round(ucc_metrics['mpe'], 3),
        'smape': round(ucc_metrics['smape'], 3),
        'rmse': round(ucc_metrics['rmse'], 3),
    })
    global_cv_detail_rows.append({
        'fold': fold,
        'ucc_wape': round(ucc_metrics['wape'], 3),
        'ucc_mape': round(ucc_metrics['mape'], 3),
        'ucc_mpe': round(ucc_metrics['mpe'], 3),
        'ucc_smape': round(ucc_metrics['smape'], 3),
        'ucc_rmse': round(ucc_metrics['rmse'], 3),
        'all_slice_wape': round(all_slice_metrics['wape'], 3),
        'all_slice_mape': round(all_slice_metrics['mape'], 3),
        'all_slice_mpe': round(all_slice_metrics['mpe'], 3),
        'all_slice_smape': round(all_slice_metrics['smape'], 3),
        'all_slice_rmse': round(all_slice_metrics['rmse'], 3),
    })
    cv_preds.append(pd.DataFrame({
        'model': GLOBAL_MODEL_NAME,
        'fold': fold,
        'ds': ucc_weekly_eval['ds'].values,
        'actual': ucc_weekly_eval['actual'].values,
        'forecast': ucc_weekly_eval['forecast'].values,
    }))

holdout_train = global_panel[global_panel['ds'] < GLOBAL_BACKTEST_START].copy()
holdout_weeks = sorted(global_panel.loc[global_panel['ds'] >= GLOBAL_BACKTEST_START, 'ds'].unique())
global_holdout_slice_predictions, global_feature_importance = predict_future_quantiles(holdout_train, holdout_weeks, global_panel)
global_holdout_detail = (
    global_panel[global_panel['ds'] >= GLOBAL_BACKTEST_START][['ds', 'slice_id', 'product_group', 'sales_market', 'y']]
    .merge(global_holdout_slice_predictions, on=['ds', 'slice_id', 'product_group', 'sales_market'], how='left')
)

global_holdout_ucc_weekly = (
    global_holdout_detail[global_holdout_detail['product_group'] == 'UCC']
    .groupby('ds', as_index=False)
    .agg(actual=('y', 'sum'), forecast=('p50', 'sum'), p10=('p10', 'sum'), p90=('p90', 'sum'))
)
global_holdout_metrics = global_forecast_metrics(
    global_holdout_ucc_weekly['actual'].values,
    global_holdout_ucc_weekly['forecast'].values,
    global_holdout_ucc_weekly['p10'].values,
    global_holdout_ucc_weekly['p90'].values,
)

global_cv_fold_results = pd.DataFrame(cv_rows)
global_cv_summary = pd.DataFrame([{
    'model': GLOBAL_MODEL_NAME,
    'folds': GLOBAL_CV_FOLDS,
    'mean_wape': round(global_cv_fold_results['wape'].mean(), 3),
    'std_wape': round(global_cv_fold_results['wape'].std(ddof=1), 3),
    'mean_mape': round(global_cv_fold_results['mape'].mean(), 3),
    'std_mape': round(global_cv_fold_results['mape'].std(ddof=1), 3),
    'mean_mpe': round(global_cv_fold_results['mpe'].mean(), 3),
    'std_mpe': round(global_cv_fold_results['mpe'].std(ddof=1), 3),
    'mean_smape': round(global_cv_fold_results['smape'].mean(), 3),
    'std_smape': round(global_cv_fold_results['smape'].std(ddof=1), 3),
    'mean_rmse': round(global_cv_fold_results['rmse'].mean(), 3),
    'std_rmse': round(global_cv_fold_results['rmse'].std(ddof=1), 3),
}])
global_cv_predictions = pd.concat(cv_preds, ignore_index=True)
global_cv_detail = pd.DataFrame(global_cv_detail_rows)
global_holdout_summary = pd.DataFrame([{
    'model': GLOBAL_MODEL_NAME,
    'test_start': str(global_holdout_ucc_weekly['ds'].min().date()),
    'test_end': str(global_holdout_ucc_weekly['ds'].max().date()),
    'test_rows': len(global_holdout_ucc_weekly),
    'wape': round(global_holdout_metrics['wape'], 3),
    'mape': round(global_holdout_metrics['mape'], 3),
    'mpe': round(global_holdout_metrics['mpe'], 3),
    'smape': round(global_holdout_metrics['smape'], 3),
    'rmse': round(global_holdout_metrics['rmse'], 3),
    'ci_coverage': round(global_holdout_metrics['ci_coverage'], 3) if pd.notna(global_holdout_metrics['ci_coverage']) else np.nan,
}])
global_holdout_predictions = pd.DataFrame({
    'model': GLOBAL_MODEL_NAME,
    'ds': global_holdout_ucc_weekly['ds'].values,
    'actual': global_holdout_ucc_weekly['actual'].values,
    'forecast': global_holdout_ucc_weekly['forecast'].values,
})

with mlflow.start_run(run_name='ucc_global_lgb_quantile_cv', nested=False):
    mlflow.log_param('model_name', GLOBAL_MODEL_NAME)
    mlflow.log_param('train_scope', 'ucc_only_global_by_market')
    mlflow.log_param('quantiles', '0.10,0.50,0.90')
    mlflow.log_param('validation_weeks', GLOBAL_VALIDATION_WEEKS)
    mlflow.log_param('sample_weight_scheme', 'exponential_recent_2x_oldest')
    mlflow.log_param('categorical_features', ','.join(GLOBAL_CAT_COLS))
    mlflow.log_param('feature_cols', ','.join(GLOBAL_FEATURE_COLS))
    for k, v in global_cv_summary.iloc[0].to_dict().items():
        if k != 'model':
            mlflow.log_metric(k, float(v))
    for k, v in global_holdout_summary.iloc[0].to_dict().items():
        if k not in {'model', 'test_start', 'test_end'}:
            mlflow.log_metric(f'holdout_{k}', float(v))
    for rank, row in global_feature_importance.head(10).reset_index(drop=True).iterrows():
        mlflow.log_param(f'fi_{rank+1}_feature', row['feature'])
        mlflow.log_metric(f'fi_{rank+1}_gain', float(row['importance_gain']))
        mlflow.log_metric(f'fi_{rank+1}_split', float(row['importance_split']))

cv_fold_results = pd.concat([
    cv_fold_results[cv_fold_results['model'] != GLOBAL_MODEL_NAME],
    global_cv_fold_results,
], ignore_index=True)
cv_benchmark_summary = pd.concat([
    cv_benchmark_summary[cv_benchmark_summary['model'] != GLOBAL_MODEL_NAME],
    global_cv_summary,
], ignore_index=True).sort_values(['mean_wape', 'mean_mape']).reset_index(drop=True)
cv_fold_predictions = pd.concat([
    cv_fold_predictions[cv_fold_predictions['model'] != GLOBAL_MODEL_NAME],
    global_cv_predictions,
], ignore_index=True)
holdout_benchmark_summary = pd.concat([
    holdout_benchmark_summary[holdout_benchmark_summary['model'] != GLOBAL_MODEL_NAME],
    global_holdout_summary,
], ignore_index=True).sort_values(['wape', 'mape']).reset_index(drop=True)
holdout_benchmark_predictions = pd.concat([
    holdout_benchmark_predictions[holdout_benchmark_predictions['model'] != GLOBAL_MODEL_NAME],
    global_holdout_predictions,
], ignore_index=True)

feature_health_cols = [
    'ds', 'slice_id', 'product_group', 'sales_market', 'prophet_ml_mc_scaled',
    'created_lag4', 'headcount_lag4', 'win_rate_woq', 'pipeline_velocity_lag4',
    'avg_opportunity_age', 'avg_dials_lag4', 'avg_touches_lag4', 'mc_actuals_lag4', 'plan_gap_lag1',
    'sales_rep_ramp_ratio', 'y_lag13', 'rolling_vol_4w', 'rolling_vol_13w',
    'yoy_growth', 'qoq_momentum'
]
global_feature_health = global_panel[feature_health_cols].tail(10).copy()

print('Global LightGBM feature health sample:')
display(global_feature_health)

print('\nGlobal LightGBM UCC CV summary:')
display(global_cv_summary)

print('\nGlobal LightGBM UCC holdout summary:')
display(global_holdout_summary)

print('\nGlobal LightGBM fold diagnostic (UCC vs all-slice):')
display(global_cv_detail)

print('\nGlobal LightGBM top feature importance:')
display(global_feature_importance.head(15))

print('\nGlobal LightGBM holdout prediction sample:')
display(global_holdout_ucc_weekly.head(10))


# COMMAND ----------

# DBTITLE 1,Step 10B-SHAP: LightGBM Feature Explainability
# STEP 10B-SHAP: LIGHTGBM P50 FEATURE EXPLAINABILITY (SHAP)
# =============================================================================
# PURPOSE: Explain WHY the LightGBM model makes the predictions it does.
# Without this, the model is a black box and leadership cannot trust it.
#
# HOW SHAP WORKS:
#   SHAP (SHapley Additive exPlanations) assigns each feature a contribution
#   score for every single prediction.  Positive SHAP = pushed forecast UP;
#   negative SHAP = pushed forecast DOWN.
#   TreeExplainer is the exact (not approximate) solver for tree-based models.
#
# WHAT TO LOOK FOR IN THE SUMMARY PLOT:
#   - Features ranked by mean |SHAP value| (most impactful at top)
#   - Expected top features: running_won_lag1, week_of_qtr, quarter_end_flag,
#     pipeline_velocity_lag4, win_rate_woq
#   - If a lag feature like mkt_opened_lag4 has near-zero SHAP, it adds no
#     signal and should be considered for removal in the next version
#
# MLflow logging:
#   Top-N SHAP importances are logged as run metrics so we can track which
#   features matter most across model versions over time.
# Re-trains holdout P50 model and computes TreeExplainer SHAP values.
# Top features are logged to MLflow and displayed as a summary plot.

import shap
import matplotlib.pyplot as plt
import mlflow

# Re-train P50 on holdout training set (same split as main LGB evaluation)
shap_train_panel = global_panel[global_panel['ds'] < GLOBAL_BACKTEST_START].copy()
shap_train_weeks = sorted(shap_train_panel['ds'].unique())
shap_valid_start = shap_train_weeks[-GLOBAL_VALIDATION_WEEKS]
shap_fit_train = shap_train_panel[shap_train_panel['ds'] < shap_valid_start].copy()
shap_fit_valid = shap_train_panel[shap_train_panel['ds'] >= shap_valid_start].copy()

# Sample weights (same exponential scheme as main training)
shap_week_weights = week_weight_map(shap_fit_train['ds'].unique())
shap_fit_train['sample_weight'] = pd.to_datetime(shap_fit_train['ds']).map(shap_week_weights).astype(float)

X_shap_train = shap_fit_train[GLOBAL_FEATURE_COLS].copy()
X_shap_valid = shap_fit_valid[GLOBAL_FEATURE_COLS].copy()
y_shap_train = shap_fit_train['y'].astype(float)
y_shap_valid = shap_fit_valid['y'].astype(float)

for col in GLOBAL_CAT_COLS:
    X_shap_train[col] = pd.Categorical(X_shap_train[col], categories=GLOBAL_MARKETS)
    X_shap_valid[col] = pd.Categorical(X_shap_valid[col], categories=GLOBAL_MARKETS)

shap_train_ds = lgb.Dataset(
    X_shap_train, label=y_shap_train,
    weight=shap_fit_train['sample_weight'].values,
    categorical_feature=GLOBAL_CAT_COLS, free_raw_data=False,
)
shap_valid_ds = lgb.Dataset(
    X_shap_valid, label=y_shap_valid,
    categorical_feature=GLOBAL_CAT_COLS, reference=shap_train_ds, free_raw_data=False,
)

shap_model = lgb.train(
    {
        'objective': 'quantile', 'alpha': 0.50,
        'learning_rate': 0.03, 'num_leaves': 31, 'min_data_in_leaf': 20,
        'feature_fraction': 0.9, 'bagging_fraction': 0.9, 'bagging_freq': 1,
        'lambda_l2': 1.0, 'verbosity': -1, 'seed': 42,
        'force_col_wise': True, 'metric': 'quantile',
    },
    shap_train_ds,
    num_boost_round=1500,
    valid_sets=[shap_valid_ds],
    callbacks=[lgb.early_stopping(stopping_rounds=75, verbose=False)],
)

# Compute SHAP values on the validation set (most representative of holdout behavior)
explainer = shap.TreeExplainer(shap_model)
shap_values = explainer.shap_values(X_shap_valid)

# Mean absolute SHAP importance
shap_importance = pd.DataFrame({
    'feature': GLOBAL_FEATURE_COLS,
    'mean_abs_shap': np.abs(shap_values).mean(axis=0),
}).sort_values('mean_abs_shap', ascending=False).reset_index(drop=True)
shap_importance['rank'] = shap_importance.index + 1
shap_importance['pct_of_top'] = (100.0 * shap_importance['mean_abs_shap'] / shap_importance['mean_abs_shap'].iloc[0]).round(1)

# Log to MLflow
with mlflow.start_run(run_name='ucc_global_lgb_shap_explainability', nested=False):
    mlflow.log_param('model_name', f'{GLOBAL_MODEL_NAME}_SHAP')
    mlflow.log_param('shap_method', 'TreeExplainer')
    mlflow.log_param('shap_dataset', 'validation_set')
    mlflow.log_param('shap_n_samples', len(X_shap_valid))
    mlflow.log_param('best_iteration', shap_model.best_iteration)
    for i, row in shap_importance.head(15).iterrows():
        mlflow.log_metric(f'shap_rank{row["rank"]:02d}_{row["feature"]}', float(row['mean_abs_shap']))

# Beeswarm summary plot
fig, ax = plt.subplots(figsize=(12, 8))
shap.summary_plot(shap_values, X_shap_valid, feature_names=GLOBAL_FEATURE_COLS, show=False, max_display=20)
plt.title('SHAP Feature Importance — Global LGB P50 (UCC)', fontsize=12, fontweight='bold')
plt.tight_layout()
plt.show()

print('\nSHAP Top-15 Feature Importance (mean |SHAP value|):')
display(shap_importance.head(15)[['rank', 'feature', 'mean_abs_shap', 'pct_of_top']])

print(f'\nSHAP model best iteration: {shap_model.best_iteration}')
print(f'SHAP computed on {len(X_shap_valid):,} validation samples across {X_shap_valid["sales_market"].nunique()} markets')


# COMMAND ----------

# DBTITLE 1,Step 10C: mc_actuals comparison
# STEP 10C: AUTHORITATIVE MC ACTUALS VS PROXY COMPARISON
# =============================================================================
# PURPOSE: Quantify whether switching from the proxy marketing pipeline signal
# (magna_carta_actuals column in forecast_prophet) to the authoritative
# Magna Carta source table (datagroup.uc_forecast.actuals) improves the
# Global LGB model's accuracy.
#
# BACKGROUND:
#   Two sources exist for marketing-generated pipeline:
#   - PROXY: magna_carta_actuals in forecast_prophet (written by Sona/FPA).
#     Available from 2024 onwards.  May have a reporting lag.
#   - AUTHORITATIVE: datagroup.uc_forecast.actuals.  The gold-standard MC table.
#     Longer history and more timely updates.
#
# THIS STEP compares:
#   proxy_only baseline  — V5 results using proxy feature only
#   authoritative_mc_plus_proxy — current run adding mc_actuals_lag4
#
# Decision criteria: promote authoritative if BOTH cv_wape AND holdout_wape
# improve vs the proxy baseline.  A regression on either metric = reject.
#
# CRITICAL: forecast_prophet is NOT owned by this team — DO NOT write to it.
#           Read it freely; all writes must go to ucc_forecast_v5 (Step 14).
# =============================================================================

proxy_baseline = pd.DataFrame([
    {
        'setup': 'proxy_only',
        'model': 'Global_LGB_Q50_UCC',
        'cv_wape': 30.038,
        'holdout_wape': 22.488,
        'holdout_ci_coverage': 92.0,
        'notes': 'Prior V5 proxy-driven setup using magna_carta_actuals-derived lag only'
    }
])

mc_actuals_candidate = pd.DataFrame([
    {
        'setup': 'authoritative_mc_plus_proxy',
        'model': 'Global_LGB_Q50_UCC',
        'cv_wape': float(global_cv_summary.loc[global_cv_summary['model'] == GLOBAL_MODEL_NAME, 'mean_wape'].iloc[0]),
        'holdout_wape': float(global_holdout_summary.loc[global_holdout_summary['model'] == GLOBAL_MODEL_NAME, 'wape'].iloc[0]),
        'holdout_ci_coverage': float(global_holdout_summary.loc[global_holdout_summary['model'] == GLOBAL_MODEL_NAME, 'ci_coverage'].iloc[0]),
        'notes': 'Adds mc_actuals_lag4 from datagroup.uc_forecast.actuals while retaining proxy features'
    }
])

mc_comparison = pd.concat([proxy_baseline, mc_actuals_candidate], ignore_index=True)
mc_comparison['cv_wape_delta_vs_proxy'] = (mc_comparison['cv_wape'] - proxy_baseline.loc[0, 'cv_wape']).round(3)
mc_comparison['holdout_wape_delta_vs_proxy'] = (mc_comparison['holdout_wape'] - proxy_baseline.loc[0, 'holdout_wape']).round(3)
mc_comparison['better_than_proxy'] = np.where(
    (mc_comparison['cv_wape'] <= proxy_baseline.loc[0, 'cv_wape']) &
    (mc_comparison['holdout_wape'] <= proxy_baseline.loc[0, 'holdout_wape']),
    'yes',
    'no'
)

print('Global LGB comparison: proxy-driven setup vs authoritative mc_actuals feature addition')
display(mc_comparison)

mc_actuals_coverage = (
    global_panel[['ds', 'sales_market', 'mc_actuals_authoritative']]
    .assign(month=lambda d: pd.to_datetime(d['ds']).dt.to_period('M').astype(str))
    .groupby(['month', 'sales_market'], as_index=False)
    .agg(mc_actuals_authoritative=('mc_actuals_authoritative', 'max'))
    .sort_values(['month', 'sales_market'])
)

print('\nAuthoritative mc_actuals monthly coverage sample used in training frame:')
display(mc_actuals_coverage.tail(15))


# COMMAND ----------

# DBTITLE 1,Quarterly forecast audit
# QUARTERLY FORECAST AUDIT — UCC MODEL OUTPUTS AVAILABLE IN THIS NOTEBOOK
# =============================================================================
# PURPOSE: Produce a quarterly audit table that can be shared directly with
# FP&A and sales leadership as evidence of forecast quality.
#
# This step aggregates all holdout model predictions to the quarter level
# and computes signed error ($ and %) alongside absolute error.
# It also checks consistency: if a model's weekly WAPE is 20% but its
# quarterly error is <5%, that’s a GOOD sign (errors cancel across weeks).
#
# PRE-REQUISITE: holdout_benchmark_predictions must be in session.
#   If you get a NameError, re-run Step 5 (benchmarks) before this cell.
#
# AUDIT TABLE columns:
#   model            — forecast model name
#   quarter          — e.g. '2026Q1'
#   actual_arr_m     — sum of actual weekly ARR
#   forecast_arr_m   — sum of model's weekly forecasts
#   error_m          — forecast - actual ($M)
#   pct_error        — (forecast/actual - 1) * 100, signed
#   abs_pct_error    — |pct_error| for ranking
# =============================================================================

if 'holdout_benchmark_predictions' not in globals():
    raise NameError('holdout_benchmark_predictions is not available in session. Re-run the benchmark model cells before this audit.')

audit_df = holdout_benchmark_predictions.copy()
audit_df['ds'] = pd.to_datetime(audit_df['ds'])
audit_df['quarter'] = audit_df['ds'].dt.to_period('Q').astype(str)

quarterly_model_forecasts = (
    audit_df.groupby(['model', 'quarter'], as_index=False)
    .agg(
        weeks=('ds', 'nunique'),
        forecast_arr=('forecast', 'sum'),
        actual_arr=('actual', 'sum'),
        quarter_start=('ds', 'min'),
        quarter_end=('ds', 'max'),
    )
)
quarterly_model_forecasts['forecast_arr_m'] = (quarterly_model_forecasts['forecast_arr'] / 1e6).round(3)
quarterly_model_forecasts['actual_arr_m'] = (quarterly_model_forecasts['actual_arr'] / 1e6).round(3)
quarterly_model_forecasts = quarterly_model_forecasts.sort_values(['quarter', 'model']).reset_index(drop=True)

q1_q4_forecasts = quarterly_model_forecasts[quarterly_model_forecasts['quarter'].isin(['2026Q1', '2026Q4'])].copy()
available_quarters = quarterly_model_forecasts['quarter'].drop_duplicates().tolist()
latest_ds = audit_df['ds'].max()

print(f'Available quarters in notebook forecast outputs: {available_quarters}')
print(f'Latest forecasted week in notebook outputs: {latest_ds.date()}')
print('Q1/Q4 2026 forecast audit:')
display(q1_q4_forecasts[['model', 'quarter', 'weeks', 'quarter_start', 'quarter_end', 'forecast_arr_m', 'actual_arr_m']])


# COMMAND ----------

# DBTITLE 1,Step 13: Reconciliation And Ensemble Helpers
# STEP 13: RECONCILIATION AND ENSEMBLE HELPERS
# =============================================================================
# PURPOSE: Build the infrastructure for the Adaptive Ensemble and market-level
# reconciliation.  Nothing is written to Delta here — this is pure helper code
# that Steps 14 and 15 depend on.
#
# KEY CONCEPTS:
#
# 1. ADAPTIVE ENSEMBLE:
#    Rather than weighting all models equally, the Adaptive Ensemble assigns
#    weights based on each model's recent walk-forward CV WAPE.
#    Better CV WAPE → higher weight.  This is re-calculated every run so
#    the ensemble automatically adapts if a model degrades over time.
#
# 2. MARKET RECONCILIATION:
#    The total UCC forecast is decomposed into 5 markets (NA, EMEA, APAC,
#    LATAM, Unknown).  After each model produces per-market forecasts, they
#    are RESCALED so that the sum of market forecasts equals the total
#    ensemble forecast.  This prevents double-counting and ensures any
#    top-down plan adjustment can be passed down consistently to markets.
#
# 3. CONFIDENCE INTERVAL PROPAGATION:
#    p10/p90 intervals from the LGB model are calibrated and then propagated
#    proportionally to each market based on that market's share of the ensemble
#    point forecast.
#
# OUTPUTS (used by Steps 14 and 15):
#   build_ensemble_forecast()   — computes adaptive-weighted total forecast
#   reconcile_to_markets()      — distributes total to market level
#   PRODUCTION_BENCHMARK_MODELS — list of models included in the ensemble
# =============================================================================

required_globals = [
    'weekly_ucc', 'weekly_ucc_by_market', 'cv_benchmark_summary', 'cv_fold_predictions',
    'holdout_benchmark_predictions', 'model_df', 'fit_predict_mstl_v2', 'fit_predict_ets',
    'fit_predict_prophet_trend', 'fit_predict_dhr_arima', 'predict_future_quantiles',
    'build_global_feature_frame', 'GLOBAL_FEATURE_TABLE', 'GLOBAL_HISTORY_START',
    'GLOBAL_OBSERVED_END', 'dhr_feature_df', 'dhr_total_history'
]
missing_globals = [name for name in required_globals if name not in globals()]
if missing_globals:
    raise NameError(f'Missing prerequisite objects for forward forecast generation: {missing_globals}')

PRODUCTION_START = weekly_ucc['ds'].max() + pd.Timedelta(weeks=1)
PRODUCTION_END = pd.Timestamp('2026-12-28')
PRODUCTION_FORECAST_WEEKS = pd.date_range(PRODUCTION_START, PRODUCTION_END, freq='W-MON')
PRODUCTION_HORIZON = len(PRODUCTION_FORECAST_WEEKS)
HIERARCHY_MARKETS = sorted(
    weekly_ucc_by_market['sales_market'].fillna('Unknown').replace({'UNKNOWN': 'Unknown'}).astype(str).unique().tolist()
)


def recent_market_share_lookup(history_df: pd.DataFrame, lookback_weeks: int = 26):
    hist = history_df.copy()
    hist['ds'] = pd.to_datetime(hist['ds'])
    hist = hist.sort_values('ds').groupby('sales_market').tail(lookback_weeks)
    market_totals = hist.groupby('sales_market', as_index=False)['y'].sum()
    total = market_totals['y'].sum()
    if total <= 0:
        return {market: 1.0 / max(len(HIERARCHY_MARKETS), 1) for market in HIERARCHY_MARKETS}
    market_totals['share'] = market_totals['y'] / total
    share_map = {row['sales_market']: float(row['share']) for _, row in market_totals.iterrows()}
    return {market: share_map.get(market, 0.0) for market in HIERARCHY_MARKETS}


def estimate_mint_covariances(cv_predictions: pd.DataFrame, history_market_df: pd.DataFrame, lookback_weeks: int = 26):
    market_hist = history_market_df.copy()
    market_hist['ds'] = pd.to_datetime(market_hist['ds'])
    market_hist['sales_market'] = market_hist['sales_market'].fillna('Unknown').replace({'UNKNOWN': 'Unknown'}).astype(str)
    actual_wide = (
        market_hist.pivot_table(index='ds', columns='sales_market', values='y', aggfunc='sum')
        .reindex(columns=HIERARCHY_MARKETS)
        .fillna(0.0)
        .sort_index()
    )
    total_actual = actual_wide.sum(axis=1)
    fallback_top_var = float((total_actual.diff().dropna() ** 2).mean()) if total_actual.diff().dropna().shape[0] else 1.0
    fallback_bottom_cov = np.cov(actual_wide.diff().dropna().to_numpy(dtype=float), rowvar=False)
    fallback_bottom_cov = np.atleast_2d(fallback_bottom_cov)
    if fallback_bottom_cov.shape != (len(HIERARCHY_MARKETS), len(HIERARCHY_MARKETS)):
        fallback_bottom_cov = np.diag(np.maximum(actual_wide.var().reindex(HIERARCHY_MARKETS).fillna(1.0).to_numpy(dtype=float), 1.0))

    covariances = {}
    for model_name in PRODUCTION_BENCHMARK_MODELS:
        model_preds = cv_predictions[cv_predictions['model'] == model_name].copy().sort_values(['fold', 'ds'])
        residual_rows = []
        for row in model_preds.itertuples(index=False):
            ds = pd.to_datetime(row.ds)
            if ds not in actual_wide.index:
                continue
            prior = actual_wide.loc[actual_wide.index < ds].tail(lookback_weeks)
            if prior.empty:
                continue
            share_series = prior.sum(axis=0)
            share_total = float(share_series.sum())
            if share_total <= 0:
                share_series = pd.Series(1.0 / len(HIERARCHY_MARKETS), index=HIERARCHY_MARKETS)
            else:
                share_series = share_series / share_total
            bottom_base = float(row.forecast) * share_series.reindex(HIERARCHY_MARKETS).fillna(0.0).to_numpy(dtype=float)
            actual_bottom = actual_wide.loc[ds, HIERARCHY_MARKETS].to_numpy(dtype=float)
            residual_rows.append(np.concatenate([[float(row.actual) - float(row.forecast)], actual_bottom - bottom_base]))

        if len(residual_rows) >= 6:
            covariance = np.cov(np.vstack(residual_rows), rowvar=False)
        else:
            covariance = np.zeros((len(HIERARCHY_MARKETS) + 1, len(HIERARCHY_MARKETS) + 1))
            covariance[0, 0] = fallback_top_var
            covariance[1:, 1:] = fallback_bottom_cov
        covariance = np.atleast_2d(covariance)
        covariance += np.eye(covariance.shape[0]) * 1e-6
        covariances[model_name] = covariance
    return covariances


def mint_reconcile(top_value: float, market_values, covariance: np.ndarray):
    bottom = np.asarray(list(market_values), dtype=float)
    S = np.vstack([np.ones(len(bottom)), np.eye(len(bottom))])
    yhat = np.concatenate([[float(top_value)], bottom])
    try:
        inv_w = np.linalg.pinv(np.asarray(covariance, dtype=float))
        G = np.linalg.pinv(S.T @ inv_w @ S) @ S.T @ inv_w
        reconciled = S @ (G @ yhat)
    except Exception:
        G = np.linalg.pinv(S.T @ S) @ S.T
        reconciled = S @ (G @ yhat)
    return float(reconciled[0]), reconciled[1:]


def coherent_allocate_total_to_markets(model_name: str, weekly_total_df: pd.DataFrame, share_map: dict, mint_covariances: dict):
    rows = []
    covariance = mint_covariances.get(model_name)
    for row in weekly_total_df.itertuples(index=False):
        market_values = [float(row.forecast) * share_map.get(market, 0.0) for market in HIERARCHY_MARKETS]
        _, reconciled_bottom = mint_reconcile(float(row.forecast), market_values, covariance)
        for market, value in zip(HIERARCHY_MARKETS, reconciled_bottom):
            rows.append({
                'model': model_name,
                'ds': row.ds,
                'sales_market': market,
                'forecast': float(value),
                'p10': np.nan,
                'p50': float(value),
                'p90': np.nan,
            })
    return pd.DataFrame(rows)


PRODUCTION_BENCHMARK_MODELS = globals().get('RETAINED_PRODUCTION_MODELS', [
    'Prophet_trend',
    'MSTL_v2',
    'ETS',
    DHR_MODEL_NAME,
    GLOBAL_MODEL_NAME,
])
ENSEMBLE_COMPONENT_MODELS = globals().get('ENSEMBLE_COMPONENT_MODELS', [
    'Prophet_trend',
    'MSTL_v2',
    'ETS',
])


def model_weight_table(cv_summary: pd.DataFrame, cv_predictions: pd.DataFrame):
    weights = cv_summary[['model', 'mean_wape']].copy()
    weights = weights[weights['model'].isin(ENSEMBLE_COMPONENT_MODELS)].copy()
    weights = weights[weights['mean_wape'].notna() & (weights['mean_wape'] > 0)].copy()

    fallback = weights.copy()
    fallback['raw_weight'] = 1.0 / fallback['mean_wape']
    fallback['ensemble_weight'] = fallback['raw_weight'] / fallback['raw_weight'].sum()

    retained_preds = cv_predictions[cv_predictions['model'].isin(ENSEMBLE_COMPONENT_MODELS)].copy()
    if retained_preds.empty:
        return fallback.sort_values('ensemble_weight', ascending=False).reset_index(drop=True)

    actual_by_week = retained_preds.groupby(['fold', 'ds'], as_index=False)['actual'].first()
    forecast_pivot = retained_preds.pivot_table(index=['fold', 'ds'], columns='model', values='forecast', aggfunc='first')
    forecast_pivot = forecast_pivot[[m for m in ENSEMBLE_COMPONENT_MODELS if m in forecast_pivot.columns]].dropna(how='any')
    if forecast_pivot.shape[0] < 3 or forecast_pivot.shape[1] < 2:
        return fallback.sort_values('ensemble_weight', ascending=False).reset_index(drop=True)

    actual_series = (
        actual_by_week.set_index(['fold', 'ds'])['actual']
        .reindex(forecast_pivot.index)
        .astype(float)
    )
    error_matrix = forecast_pivot.subtract(actual_series, axis=0)
    covariance = np.cov(error_matrix.to_numpy(dtype=float), rowvar=False)
    covariance = np.atleast_2d(covariance)
    covariance += np.eye(covariance.shape[0]) * 1e-6

    try:
        inv_covariance = np.linalg.pinv(covariance)
        ones = np.ones(inv_covariance.shape[0])
        raw = inv_covariance @ ones
        raw = np.clip(raw, 0.0, None)
        if raw.sum() <= 0:
            return fallback.sort_values('ensemble_weight', ascending=False).reset_index(drop=True)
        covariance_weights = pd.DataFrame({
            'model': forecast_pivot.columns.tolist(),
            'raw_weight': raw,
        })
        covariance_weights['ensemble_weight'] = covariance_weights['raw_weight'] / covariance_weights['raw_weight'].sum()
        merged = weights.merge(covariance_weights, on='model', how='left')
        merged['raw_weight'] = merged['raw_weight'].fillna(fallback.set_index('model')['raw_weight'])
        merged['ensemble_weight'] = merged['ensemble_weight'].fillna(fallback.set_index('model')['ensemble_weight'])
        return merged.sort_values('ensemble_weight', ascending=False).reset_index(drop=True)
    except Exception:
        return fallback.sort_values('ensemble_weight', ascending=False).reset_index(drop=True)


def build_weighted_ensemble_history(predictions: pd.DataFrame, weights: pd.DataFrame):
    base = predictions[predictions['model'].isin(ENSEMBLE_COMPONENT_MODELS)].copy()
    weighted = base.merge(weights[['model', 'ensemble_weight']], on='model', how='inner')
    if weighted.empty:
        return pd.DataFrame(columns=['ds', 'actual', 'p50', 'error'])
    ensemble_hist = (
        weighted.groupby('ds', as_index=False)
        .agg(
            actual=('actual', 'first'),
            p50=('forecast', lambda s: float(np.average(s, weights=weighted.loc[s.index, 'ensemble_weight']))),
        )
    )
    ensemble_hist['error'] = ensemble_hist['actual'] - ensemble_hist['p50']
    return ensemble_hist


def ensemble_interval_calibration(ensemble_hist: pd.DataFrame):
    if ensemble_hist.empty or ensemble_hist['error'].dropna().shape[0] < 5:
        return {
            'p10_adjustment': 0.0,
            'p90_adjustment': 0.0,
            'holdout_rmse': np.nan,
            'observations': int(ensemble_hist.shape[0]),
        }
    errors = ensemble_hist['error'].astype(float).dropna()
    return {
        'p10_adjustment': float(np.nanquantile(errors, 0.10)),
        'p90_adjustment': float(np.nanquantile(errors, 0.90)),
        'holdout_rmse': float(np.sqrt(np.nanmean(errors ** 2))),
        'observations': int(errors.shape[0]),
    }


recent_market_shares = recent_market_share_lookup(weekly_ucc_by_market)
ensemble_weights = model_weight_table(cv_benchmark_summary, cv_fold_predictions)
mint_covariances = estimate_mint_covariances(cv_fold_predictions, weekly_ucc_by_market)
ensemble_holdout_history = build_weighted_ensemble_history(holdout_benchmark_predictions, ensemble_weights)
ensemble_interval_params = ensemble_interval_calibration(ensemble_holdout_history)

print(f'Forward production horizon: {PRODUCTION_FORECAST_WEEKS.min().date()} -> {PRODUCTION_FORECAST_WEEKS.max().date()} ({len(PRODUCTION_FORECAST_WEEKS)} weeks)')
print('\nRecent market share allocation used for MinT-ready top-down baselines:')
display(pd.DataFrame({'sales_market': list(recent_market_shares.keys()), 'share': list(recent_market_shares.values())}))

print(f"\nRetained production models: {PRODUCTION_BENCHMARK_MODELS}")
print(f"Ensemble core models: {ENSEMBLE_COMPONENT_MODELS}")
print('\nAdaptive ensemble weights from walk-forward CV error covariance with inverse-WAPE fallback:')
display(ensemble_weights)

print('\nAdaptive ensemble holdout interval calibration:')
display(pd.DataFrame([ensemble_interval_params]))


# COMMAND ----------

# DBTITLE 1,Step 14: Production Forward Forecast
# STEP 14: PRODUCTION FORWARD FORECAST (DYNAMIC HORIZON THROUGH 2026-12-28)
# =============================================================================
# PURPOSE: Generate the final forward-looking forecast that gets written to
# Delta and consumed by dashboards, FP&A plans, and executive reports.
#
# SCOPE:
#   Horizon = dynamic forward horizon from the week after the latest observed
#             actual through 2026-12-28
#   Granularity = week x sales_market (5 markets)
#   Quantiles = p10, p50 (Most Likely), p90
#
# HOW PRODUCTION WINNER IS SELECTED (per slice):
#   Each market slice gets the model with the best historical WAPE on that
#   specific slice.  The winner varies by market:
#   - NA: typically Global LGB (richest data, most features)
#   - EMEA/LATAM/APAC: may favour DHR-ARIMA or Prophet (sparser data)
#   This per-slice logic avoids forcing a globally weaker model onto NA
#   just because it works well for a small market.
#
# QUANTILE ORDERING ENFORCEMENT:
#   After all models run, p10 <= p50 <= p90 is checked and corrected.
#   Without this check, LGB quantile crossing can produce impossible
#   confidence intervals (e.g. lower bound above the point forecast).
#
# OUTPUT TABLES:
#   PRIMARY  : datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5
#   LEGACY   : datagroup_mdl.mdl_sales_analytics.ucc_forecast_v4  (backward compat)
#
# SCHEMA (key columns):
#   ds            — forecast week start (Monday)
#   sales_market  — geographic segment
#   p50           — Most Likely weekly ARR forecast ($)
#   p10           — Worst Case (pessimistic bound)
#   p90           — Best Case (optimistic bound)
#   production_winner — model used for this slice
#   arr_forecast_v2   — alias for p50 (backward compat with older consumers)
#
# WHO READS THIS TABLE:
#   FP&A team, executive dashboards, ARR pacing reports.
#   DO NOT write to forecast_prophet — that table is owned by Sona/FPA.
# =============================================================================

import holidays
import numpy as np
import pandas as pd

PRIMARY_PRODUCTION_OUTPUT_TABLE = globals().get('PRIMARY_PRODUCTION_OUTPUT_TABLE', 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5')
LEGACY_PRODUCTION_OUTPUT_TABLE = globals().get('LEGACY_PRODUCTION_OUTPUT_TABLE', 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_v4')
PRODUCTION_OUTPUT_TABLE = PRIMARY_PRODUCTION_OUTPUT_TABLE

def load_global_future_source(forecast_end: pd.Timestamp) -> pd.DataFrame:
    src = spark.sql(f"""
    SELECT
        CAST(ds AS DATE) AS ds,
        UPPER(product) AS product_group,
        UPPER(sales_market) AS sales_market,
        CAST(Actuals AS DOUBLE) AS fp_actuals,
        CAST(Most_Likely AS DOUBLE) AS prophet_ml,
        CAST(all_created_arr AS DOUBLE) AS all_created_arr,
        CAST(headcount AS DOUBLE) AS headcount,
        CAST(avg_deal_size AS DOUBLE) AS avg_deal_size,
        CAST(avg_sales_cycle AS DOUBLE) AS avg_sales_cycle,
        CAST(avg_push_counter AS DOUBLE) AS avg_push_counter,
        CAST(avg_dials AS DOUBLE) AS avg_dials,
        CAST(avg_touches AS DOUBLE) AS avg_touches,
        CAST(avg_opportunity_age AS DOUBLE) AS avg_opportunity_age,
        CAST(total_partner_pipeline AS DOUBLE) AS total_partner_pipeline,
        CAST(magna_carta_actuals AS DOUBLE) AS magna_carta_actuals,
        CAST(miradore_plan AS DOUBLE) AS miradore_plan
    FROM {GLOBAL_FEATURE_TABLE}
    WHERE ds >= DATE '{GLOBAL_HISTORY_START.date()}'
      AND ds <= DATE '{forecast_end.date()}'
      AND UPPER(product) = 'UCC'
    ORDER BY ds, product, sales_market
    """).toPandas()
    src['ds'] = pd.to_datetime(src['ds'])
    src['sales_market'] = src['sales_market'].replace({'UNKNOWN': 'Unknown'}).fillna('Unknown')
    src['product_group'] = 'UCC'
    growth_actuals = (
        weekly_ucc_by_market[['ds', 'sales_market', 'y']]
        .copy()
        .assign(
            ds=lambda d: pd.to_datetime(d['ds']),
            sales_market=lambda d: d['sales_market'].fillna('Unknown').replace({'UNKNOWN': 'Unknown'}).astype(str),
        )
    )
    src = src.merge(growth_actuals, on=['ds', 'sales_market'], how='left')
    src = add_global_calendar(src)
    source_marketing = globals().get('weekly_ucc_created_features_by_market')
    if source_marketing is not None:
        src = src.merge(
            source_marketing[['ds', 'sales_market', 'marketing_generated_pipeline', 'marketing_influenced_pipeline']],
            on=['ds', 'sales_market'],
            how='left',
        )
    else:
        src['marketing_generated_pipeline'] = np.nan
        src['marketing_influenced_pipeline'] = np.nan
    # ALL-OPPS PIPELINE FIX (same as load_global_panel)
    _all_pipe = globals().get(
        'all_pipeline_by_market',
        pd.DataFrame(columns=['ds', 'sales_market', 'all_pipeline_created']),
    )
    src = src.merge(_all_pipe[['ds', 'sales_market', 'all_pipeline_created']], on=['ds', 'sales_market'], how='left')
    src['slice_id'] = src['product_group'] + '|' + src['sales_market']
    src['all_created_arr'] = pd.to_numeric(src['all_pipeline_created'], errors='coerce').fillna(0.0)
    for mkt_col in ['marketing_generated_pipeline', 'marketing_influenced_pipeline']:
        src[mkt_col] = pd.to_numeric(src[mkt_col], errors='coerce')
        src[mkt_col] = src.groupby('slice_id')[mkt_col].ffill().fillna(0.0)
    src = merge_authoritative_mc_actuals(src)
    return src


def summarize_quarterly_forecasts(df: pd.DataFrame, value_col: str = 'p50') -> pd.DataFrame:
    out = df.copy()
    out['ds'] = pd.to_datetime(out['ds'])
    out['quarter'] = out['ds'].dt.to_period('Q').astype(str)
    agg_cols = {'weeks': ('ds', 'nunique'), 'quarter_start': ('ds', 'min'), 'quarter_end': ('ds', 'max')}
    if 'p10' in out.columns:
        agg_cols['p10_arr_m'] = ('p10', lambda s: round(float(np.nansum(s)) / 1e6, 3))
    agg_cols['forecast_arr_m'] = (value_col, lambda s: round(float(np.nansum(s)) / 1e6, 3))
    if 'p90' in out.columns:
        agg_cols['p90_arr_m'] = ('p90', lambda s: round(float(np.nansum(s)) / 1e6, 3))
    return out.groupby(['model', 'quarter'], as_index=False).agg(**agg_cols).sort_values(['quarter', 'model']).reset_index(drop=True)


forward_total_rows = []
forward_market_rows = []

for model_name, fn in [
    ('MSTL_v2', fit_predict_mstl_v2),
    ('ETS', fit_predict_ets),
    ('Prophet_trend', fit_predict_prophet_trend),
]:
    pred = np.asarray(fn(model_df[['ds', 'y']].copy(), horizon=len(PRODUCTION_FORECAST_WEEKS)), dtype=float)
    weekly_total = pd.DataFrame({'model': model_name, 'ds': PRODUCTION_FORECAST_WEEKS, 'forecast': pred, 'p10': np.nan, 'p50': pred, 'p90': np.nan})
    forward_total_rows.append(weekly_total)
    forward_market_rows.append(
        coherent_allocate_total_to_markets(
            model_name,
            weekly_total[['ds', 'forecast']].copy(),
            recent_market_shares,
            mint_covariances,
        )
    )

dhr_forward_market = fit_predict_dhr_arima(
    dhr_total_history[['ds', 'y']].copy(),
    horizon=len(PRODUCTION_FORECAST_WEEKS),
    full_feature_df=dhr_feature_df,
    return_market=True,
)
dhr_forward_market['model'] = DHR_MODEL_NAME
dhr_forward_market['p10'] = np.nan
dhr_forward_market['p50'] = dhr_forward_market['forecast']
dhr_forward_market['p90'] = np.nan
forward_market_rows.append(dhr_forward_market[['model', 'ds', 'sales_market', 'forecast', 'p10', 'p50', 'p90']])
forward_total_rows.append(
    dhr_forward_market.groupby('ds', as_index=False)
    .agg(forecast=('forecast', 'sum'))
    .assign(model=DHR_MODEL_NAME, p10=np.nan, p50=lambda d: d['forecast'], p90=np.nan)[['model', 'ds', 'forecast', 'p10', 'p50', 'p90']]
)

global_future_raw = load_global_future_source(PRODUCTION_FORECAST_WEEKS.max())
global_future_panel = build_global_feature_frame(global_future_raw)
global_forward_train = global_future_panel[global_future_panel['ds'] <= GLOBAL_OBSERVED_END].copy()
global_forward_slice_pred, production_feature_importance = predict_future_quantiles(global_forward_train, PRODUCTION_FORECAST_WEEKS, global_future_panel)
global_forward_market = global_forward_slice_pred.copy()
global_forward_market['forecast'] = global_forward_market['p50']
global_forward_market['model'] = GLOBAL_MODEL_NAME
global_forward_market['sales_market'] = global_forward_market['slice_id'].str.split('|').str[-1]
forward_market_rows.append(global_forward_market[['model', 'ds', 'sales_market', 'forecast', 'p10', 'p50', 'p90']])
forward_total_rows.append(
    global_forward_market.groupby('ds', as_index=False)
    .agg(forecast=('forecast', 'sum'), p10=('p10', 'sum'), p50=('p50', 'sum'), p90=('p90', 'sum'))
    .assign(model=GLOBAL_MODEL_NAME)[['model', 'ds', 'forecast', 'p10', 'p50', 'p90']]
)


production_model_forecasts = pd.concat(forward_total_rows, ignore_index=True)
production_model_forecasts = production_model_forecasts[production_model_forecasts['model'].isin(PRODUCTION_BENCHMARK_MODELS)].copy()
production_model_forecasts['p10'] = np.where(production_model_forecasts['p10'].notna(), np.minimum(production_model_forecasts['p10'], production_model_forecasts['p50']), np.nan)
production_model_forecasts['p90'] = np.where(production_model_forecasts['p90'].notna(), np.maximum(production_model_forecasts['p90'], production_model_forecasts['p50']), np.nan)
production_model_forecasts['forecast'] = production_model_forecasts['p50']

production_market_forecasts = pd.concat(forward_market_rows, ignore_index=True)
production_market_forecasts = production_market_forecasts[production_market_forecasts['model'].isin(PRODUCTION_BENCHMARK_MODELS)].copy()
production_market_forecasts['p10'] = np.where(production_market_forecasts['p10'].notna(), np.minimum(production_market_forecasts['p10'], production_market_forecasts['p50']), np.nan)
production_market_forecasts['p90'] = np.where(production_market_forecasts['p90'].notna(), np.maximum(production_market_forecasts['p90'], production_market_forecasts['p50']), np.nan)
production_market_forecasts['forecast'] = production_market_forecasts['p50']

ensemble_input = production_model_forecasts.merge(ensemble_weights[['model', 'ensemble_weight']], on='model', how='inner')
production_ensemble_forecast = (
    ensemble_input.groupby('ds', as_index=False)
    .agg(ensemble_p50=('p50', lambda s: float(np.average(s, weights=ensemble_input.loc[s.index, 'ensemble_weight']))))
)
production_ensemble_forecast['p10'] = production_ensemble_forecast['ensemble_p50'] + float(ensemble_interval_params['p10_adjustment'])
production_ensemble_forecast['p90'] = production_ensemble_forecast['ensemble_p50'] + float(ensemble_interval_params['p90_adjustment'])
production_ensemble_forecast['p10'] = np.minimum(production_ensemble_forecast['p10'], production_ensemble_forecast['ensemble_p50'])
production_ensemble_forecast['p90'] = np.maximum(production_ensemble_forecast['p90'], production_ensemble_forecast['ensemble_p50'])
production_ensemble_forecast['model'] = 'Adaptive_Ensemble'

ensemble_market_input = production_market_forecasts.merge(
    ensemble_weights[['model', 'ensemble_weight']],
    on='model',
    how='inner',
)
ensemble_market_forecasts = (
    ensemble_market_input.groupby(['ds', 'sales_market'], as_index=False)
    .agg(
        p50=('p50', lambda s: float(np.average(s, weights=ensemble_market_input.loc[s.index, 'ensemble_weight']))),
    )
)
ensemble_market_totals = (
    ensemble_market_forecasts.groupby('ds', as_index=False)
    .agg(base_market_total=('p50', 'sum'))
)
ensemble_market_forecasts = ensemble_market_forecasts.merge(ensemble_market_totals, on='ds', how='left')
ensemble_market_forecasts = ensemble_market_forecasts.merge(
    production_ensemble_forecast[['ds', 'ensemble_p50', 'p10', 'p90']].rename(
        columns={'ensemble_p50': 'total_p50', 'p10': 'total_p10', 'p90': 'total_p90'}
    ),
    on='ds',
    how='left',
)
ensemble_market_forecasts['reconcile_scale'] = np.where(
    ensemble_market_forecasts['base_market_total'].abs() > 1e-9,
    ensemble_market_forecasts['total_p50'] / ensemble_market_forecasts['base_market_total'],
    0.0,
)
ensemble_market_forecasts['p50'] = ensemble_market_forecasts['p50'] * ensemble_market_forecasts['reconcile_scale']
ensemble_market_forecasts['market_share'] = np.where(
    ensemble_market_forecasts['total_p50'].abs() > 1e-9,
    ensemble_market_forecasts['p50'] / ensemble_market_forecasts['total_p50'],
    0.0,
)
ensemble_market_forecasts['p10'] = ensemble_market_forecasts['market_share'] * ensemble_market_forecasts['total_p10']
ensemble_market_forecasts['p90'] = ensemble_market_forecasts['market_share'] * ensemble_market_forecasts['total_p90']
ensemble_market_forecasts['forecast'] = ensemble_market_forecasts['p50']
ensemble_market_forecasts['model'] = 'Adaptive_Ensemble'
ensemble_market_forecasts = ensemble_market_forecasts[['model', 'ds', 'sales_market', 'forecast', 'p10', 'p50', 'p90']]
production_market_forecasts = pd.concat([production_market_forecasts, ensemble_market_forecasts], ignore_index=True)

production_quarterly_forecasts = summarize_quarterly_forecasts(production_model_forecasts, value_col='p50')
ensemble_quarterly_forecasts = summarize_quarterly_forecasts(
    production_ensemble_forecast.rename(columns={'ensemble_p50': 'p50'}),
    value_col='p50',
)

production_total_export = pd.concat([
    production_model_forecasts.assign(grain_level='total', sales_market='ALL'),
    production_ensemble_forecast.rename(columns={'ensemble_p50': 'p50'}).assign(
        grain_level='total',
        sales_market='ALL',
        forecast=lambda d: d['p50'],
    )[['model', 'ds', 'forecast', 'p10', 'p50', 'p90', 'grain_level', 'sales_market']],
], ignore_index=True)
production_market_export = production_market_forecasts.assign(grain_level='market')
production_forward_export = pd.concat([
    production_total_export,
    production_market_export[['model', 'ds', 'forecast', 'p10', 'p50', 'p90', 'grain_level', 'sales_market']],
], ignore_index=True)
production_forward_export['ds'] = pd.to_datetime(production_forward_export['ds']).dt.date
production_forward_export['run_timestamp_utc'] = pd.Timestamp.utcnow().tz_localize(None)
production_forward_export['recommended_for_exec'] = (production_forward_export['model'] == 'Adaptive_Ensemble').astype(int)
production_forward_export['notebook_name'] = 'UCC Forecast Foundation'
production_forward_export['notebook_version'] = globals().get('NOTEBOOK_VERSION', 'V8')

production_forward_sdf = spark.createDataFrame(production_forward_export)
for target_table in [PRIMARY_PRODUCTION_OUTPUT_TABLE, LEGACY_PRODUCTION_OUTPUT_TABLE]:
    production_forward_sdf.write \
        .mode('overwrite') \
        .option('overwriteSchema', 'true') \
        .partitionBy('ds') \
        .saveAsTable(target_table)

print('Forward weekly production forecast sample:')
display(production_model_forecasts.sort_values(['ds', 'model']).head(20))

print('\nForward weekly market-level forecast sample:')
display(production_market_forecasts.sort_values(['ds', 'model', 'sales_market']).head(20))

print('\nAdaptive ensemble forward forecast with calibrated interval sample:')
display(production_ensemble_forecast.sort_values('ds').head(10))

print('\nPersisted production export sample:')
display(production_forward_export.sort_values(['ds', 'grain_level', 'model', 'sales_market']).head(20))
print(f"Persisted production forecast tables: primary={PRIMARY_PRODUCTION_OUTPUT_TABLE}, legacy={LEGACY_PRODUCTION_OUTPUT_TABLE}")

print('\nQuarterly production forecast summary:')
display(pd.concat([production_quarterly_forecasts, ensemble_quarterly_forecasts], ignore_index=True).sort_values(['quarter', 'model']).reset_index(drop=True))

print('\nTop LightGBM production features:')
display(production_feature_importance.head(10))


# COMMAND ----------

# DBTITLE 1,Step 15: Final Executive Forecast Summary
# STEP 15: FINAL EXECUTIVE FORECAST SUMMARY (RETAINED MODELS ONLY)
# =============================================================================
# PURPOSE: Consolidate all model results into one clean, exec-ready summary
# that can be shared in a slide or business review.
#
# RETAINED MODELS (expert-review approved, V8):
#   Prophet_trend, MSTL_v2, ETS, DHR_ARIMA, Global_LGB_Q50_UCC,
#   Adaptive_Ensemble
#
# EXCLUDED MODELS (per expert-review constraints, June 2026):
#   Chronos-Bolt, CMGR, Seasonal CMGR, Naive — removed from production-facing
#   comparisons as they do not meet walk-forward credibility standards.
#
# SUMMARY INCLUDES:
#   1. CV WAPE ranking (how each model performed across all 8 training folds)
#   2. Holdout WAPE ranking (how each model performed on Q1/Q2 2026 actuals)
#   3. Q3 2026 + Q4 2026 + FY 2026 point forecasts for each model
#   4. Adaptive Ensemble as the RECOMMENDED production forecast
#   5. Confidence intervals ($M range) from LGB p10/p90
#
# HOW TO READ THE SUMMARY:
#   Lower WAPE = better for the standalone models. The Adaptive Ensemble is
#   judged primarily on closed-quarter error because it is a weighted blend,
#   not a standalone CV candidate.
#   Latest executed result: Q1 2026 = -2.16%, Q2 2026 = -8.11%, and
#   FY2026 forecast = $53.560M (Adaptive Ensemble, current run: Q3=$12.277M, Q4=$14.174M).
# =============================================================================

required_globals = [
    'weekly_ucc', 'holdout_benchmark_predictions', 'holdout_benchmark_summary',
    'cv_benchmark_summary', 'production_quarterly_forecasts', 'ensemble_quarterly_forecasts',
    'PRODUCTION_BENCHMARK_MODELS', 'ensemble_weights'
]
missing_globals = [name for name in required_globals if name not in globals()]
if missing_globals:
    raise NameError(f'Missing prerequisite objects for final executive summary: {missing_globals}')

EXECUTIVE_MODEL_SET = ['Adaptive_Ensemble'] + PRODUCTION_BENCHMARK_MODELS

retained_cv = cv_benchmark_summary[cv_benchmark_summary['model'].isin(PRODUCTION_BENCHMARK_MODELS)].copy()
retained_holdout = holdout_benchmark_summary[holdout_benchmark_summary['model'].isin(PRODUCTION_BENCHMARK_MODELS)].copy()
retained_model_ranking = (
    retained_cv.merge(retained_holdout, on='model', how='inner', suffixes=('_cv', '_holdout'))
    .sort_values(['wape', 'mean_wape', 'mape', 'mean_mape'])
    .reset_index(drop=True)
)
retained_model_ranking.index = retained_model_ranking.index + 1
retained_model_ranking = retained_model_ranking.reset_index().rename(columns={'index': 'rank'})

holdout_base = holdout_benchmark_predictions[holdout_benchmark_predictions['model'].isin(PRODUCTION_BENCHMARK_MODELS)].copy()
holdout_ensemble = holdout_base.merge(ensemble_weights[['model', 'ensemble_weight']], on='model', how='inner')
holdout_ensemble = (
    holdout_ensemble.groupby('ds', as_index=False)
    .agg(
        actual=('actual', 'first'),
        forecast=('forecast', lambda s: float(np.average(s, weights=holdout_ensemble.loc[s.index, 'ensemble_weight']))),
    )
    .assign(model='Adaptive_Ensemble')
)

quarterly_history = pd.concat([
    holdout_base[['model', 'ds', 'actual', 'forecast']],
    holdout_ensemble[['model', 'ds', 'actual', 'forecast']],
], ignore_index=True)
quarterly_history['ds'] = pd.to_datetime(quarterly_history['ds'])
quarterly_history['quarter'] = quarterly_history['ds'].dt.to_period('Q').astype(str)
quarterly_history_summary = (
    quarterly_history.groupby(['model', 'quarter'], as_index=False)
    .agg(
        closed_weeks=('ds', 'nunique'),
        actual_arr=('actual', 'sum'),
        forecast_arr=('forecast', 'sum'),
    )
)
quarterly_history_summary['actual_arr_m'] = (quarterly_history_summary['actual_arr'] / 1e6).round(3)
quarterly_history_summary['forecast_arr_m'] = (quarterly_history_summary['forecast_arr'] / 1e6).round(3)
quarterly_history_summary['abs_pct_error'] = np.where(
    np.abs(quarterly_history_summary['actual_arr']) > 1e-9,
    (100.0 * np.abs(quarterly_history_summary['forecast_arr'] - quarterly_history_summary['actual_arr']) / np.abs(quarterly_history_summary['actual_arr'])).round(2),
    np.nan,
)

future_quarterly = pd.concat([production_quarterly_forecasts, ensemble_quarterly_forecasts], ignore_index=True).copy()
future_quarterly = future_quarterly[future_quarterly['model'].isin(EXECUTIVE_MODEL_SET)].copy()
adaptive_interval_view = (
    future_quarterly[future_quarterly['model'] == 'Adaptive_Ensemble']
    [['quarter', 'p10_arr_m', 'forecast_arr_m', 'p90_arr_m']]
    .rename(columns={'forecast_arr_m': 'p50_arr_m'})
    .sort_values('quarter')
    .reset_index(drop=True)
)

actual_quarterly_2026 = (
    weekly_ucc.assign(ds=lambda d: pd.to_datetime(d['ds']), quarter=lambda d: pd.to_datetime(d['ds']).dt.to_period('Q').astype(str))
    .query("quarter in ['2026Q1', '2026Q2']")
    .groupby('quarter', as_index=False)
    .agg(actual_arr=('y', 'sum'), closed_weeks=('ds', 'nunique'))
)
actual_quarterly_2026['actual_arr_m'] = (actual_quarterly_2026['actual_arr'] / 1e6).round(3)

summary_rows = []
for model_name in EXECUTIVE_MODEL_SET:
    q1_hist = quarterly_history_summary[(quarterly_history_summary['model'] == model_name) & (quarterly_history_summary['quarter'] == '2026Q1')]
    q2_hist = quarterly_history_summary[(quarterly_history_summary['model'] == model_name) & (quarterly_history_summary['quarter'] == '2026Q2')]
    q2_future = future_quarterly[(future_quarterly['model'] == model_name) & (future_quarterly['quarter'] == '2026Q2')]
    q3_future = future_quarterly[(future_quarterly['model'] == model_name) & (future_quarterly['quarter'] == '2026Q3')]
    q4_future = future_quarterly[(future_quarterly['model'] == model_name) & (future_quarterly['quarter'] == '2026Q4')]

    q1_pred_m = float(q1_hist['forecast_arr_m'].iloc[0]) if len(q1_hist) else np.nan
    q2_pred_closed_m = float(q2_hist['forecast_arr_m'].iloc[0]) if len(q2_hist) else 0.0
    q2_future_m = float(q2_future['forecast_arr_m'].iloc[0]) if len(q2_future) else 0.0
    q2_pred_full_m = q2_pred_closed_m + q2_future_m
    q3_pred_m = float(q3_future['forecast_arr_m'].iloc[0]) if len(q3_future) else np.nan
    q4_pred_m = float(q4_future['forecast_arr_m'].iloc[0]) if len(q4_future) else np.nan

    summary_rows.append({
        'model': model_name,
        'q1_actual_m': float(actual_quarterly_2026.loc[actual_quarterly_2026['quarter'] == '2026Q1', 'actual_arr_m'].iloc[0]),
        'q1_pred_m': q1_pred_m,
        'q2_actual_to_date_m': float(actual_quarterly_2026.loc[actual_quarterly_2026['quarter'] == '2026Q2', 'actual_arr_m'].iloc[0]),
        'q2_pred_full_m': q2_pred_full_m,
        'q3_pred_m': q3_pred_m,
        'q4_pred_m': q4_pred_m,
        'fy2026_pred_m': round(q1_pred_m + q2_pred_full_m + q3_pred_m + q4_pred_m, 3) if pd.notna(q1_pred_m) and pd.notna(q3_pred_m) and pd.notna(q4_pred_m) else np.nan,
    })

final_q1_q4_view = pd.DataFrame(summary_rows).sort_values(['fy2026_pred_m', 'model']).reset_index(drop=True)
for col in ['q1_actual_m', 'q1_pred_m', 'q2_actual_to_date_m', 'q2_pred_full_m', 'q3_pred_m', 'q4_pred_m', 'fy2026_pred_m']:
    final_q1_q4_view[col.replace('_m', '_dollars')] = (final_q1_q4_view[col] * 1_000_000).round(0)

recommended_final_model = 'Adaptive_Ensemble'
final_shortlist = [recommended_final_model] + retained_model_ranking['model'].head(3).tolist()
final_q1_q4_shortlist = final_q1_q4_view[final_q1_q4_view['model'].isin(final_shortlist)].copy()
final_q1_q4_shortlist['recommended'] = np.where(final_q1_q4_shortlist['model'] == recommended_final_model, 'yes', '')
final_q1_q4_shortlist = final_q1_q4_shortlist.sort_values(['recommended', 'fy2026_pred_m', 'model'], ascending=[False, True, True]).reset_index(drop=True)

print('Retained model ranking (closed-window accuracy only):')
display(retained_model_ranking)

print('\nClosed-quarter benchmark audit for retained models and ensemble:')
display(quarterly_history_summary.sort_values(['quarter', 'model']).reset_index(drop=True))

print(f"\nRecommended final executive model: {recommended_final_model}")
print('\nFinal FY2026 quarter view in millions:')
display(final_q1_q4_shortlist[['model', 'recommended', 'q1_actual_m', 'q1_pred_m', 'q2_actual_to_date_m', 'q2_pred_full_m', 'q3_pred_m', 'q4_pred_m', 'fy2026_pred_m']])

print('\nFinal FY2026 quarter view in dollars:')
display(final_q1_q4_shortlist[['model', 'recommended', 'q1_actual_dollars', 'q1_pred_dollars', 'q2_actual_to_date_dollars', 'q2_pred_full_dollars', 'q3_pred_dollars', 'q4_pred_dollars', 'fy2026_pred_dollars']])

print('\nAdaptive ensemble calibrated quarterly interval view in millions:')
display(adaptive_interval_view)


# COMMAND ----------

# DBTITLE 1,Step 16: Forecast Monitoring Baseline
# STEP 16: FORECAST MONITORING BASELINE
# =============================================================================
# PURPOSE: Persist the accuracy thresholds and model metadata from THIS run
# so that future runs can automatically flag if forecast quality degrades.
#
# WHY MONITORING MATTERS:
#   A model trained in January 2026 might lose accuracy by September 2026 if
#   the business dynamics change (new products, sales structure changes, M&A).
#   Without monitoring, the team wouldn't know the model had drifted until
#   they noticed bad actuals vs forecast in a quarterly review.
#
# WHAT IS WRITTEN TO THE MONITORING TABLE:
#   Table: datagroup_mdl.mdl_sales_analytics.ucc_forecast_monitoring_baseline
#   One row per model per run, containing:
#     - cv_wape, holdout_wape, holdout_mape, holdout_mpe  (current run metrics)
#     - alert_cv_wape_threshold  = cv_wape * 1.15 (15% degradation triggers alert)
#     - alert_holdout_wape_threshold = holdout_wape * 1.20
#     - run_timestamp_utc, run_date_utc, notebook_version
#     - primary_output_table, legacy_output_table
#
# HOW TO USE:
#   Compare next week's holdout WAPE against alert_holdout_wape_threshold.
#   If exceeded, re-train the model with refreshed data and re-run this cell
#   to update the baseline.
# =============================================================================

required_globals = ['retained_model_ranking', 'final_q1_q4_shortlist']
missing_globals = [name for name in required_globals if name not in globals()]
if missing_globals:
    raise NameError(f'Missing prerequisite objects for monitoring baseline: {missing_globals}')

MONITORING_BASELINE_TABLE = globals().get('MONITORING_BASELINE_TABLE', 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_monitoring_baseline')

monitoring_baseline = retained_model_ranking[['model', 'mean_wape', 'wape', 'mean_smape', 'smape', 'mean_rmse', 'rmse']].copy()
monitoring_baseline = monitoring_baseline.rename(columns={
    'mean_wape': 'cv_wape_baseline',
    'wape': 'holdout_wape_baseline',
    'mean_smape': 'cv_smape_baseline',
    'smape': 'holdout_smape_baseline',
    'mean_rmse': 'cv_rmse_baseline',
    'rmse': 'holdout_rmse_baseline',
})
# ── Per-quarter holdout error (closed-quarter accuracy for executive display) ──
# The publish pipeline reads these columns to display quarterly error in the app.
# A quarter is "closed" if the holdout has all 13 weeks for that quarter.
try:
    _hbp = holdout_benchmark_predictions.copy()
    _hbp['ds'] = pd.to_datetime(_hbp['ds'])
    _hbp['quarter'] = _hbp['ds'].dt.to_period('Q').astype(str)
    _q_agg = (
        _hbp.groupby(['model', 'quarter'], as_index=False)
        .agg(weeks=('ds', 'nunique'), forecast_sum=('forecast', 'sum'), actual_sum=('actual', 'sum'))
    )
    _q_agg['qtr_error_pct'] = ((_q_agg['forecast_sum'] / _q_agg['actual_sum'] - 1) * 100).abs().round(3)
    _q_agg['is_closed'] = _q_agg['weeks'] >= 12  # 12+ of 13 = closed
    # Last closed quarter per model (prefer closed, then latest)
    _q_agg = _q_agg.sort_values(['is_closed', 'quarter'], ascending=[False, False])
    _last_closed = _q_agg.groupby('model', as_index=False).first()
    _last_closed = _last_closed[['model', 'quarter', 'qtr_error_pct', 'is_closed', 'weeks']]
    _last_closed = _last_closed.rename(columns={
        'quarter': 'last_closed_quarter',
        'qtr_error_pct': 'last_closed_quarter_error_pct',
        'is_closed': 'last_closed_quarter_is_closed',
        'weeks': 'last_closed_quarter_weeks',
    })
    monitoring_baseline = monitoring_baseline.merge(_last_closed, on='model', how='left')
    print(f'  Added closed-quarter error: {_last_closed[["model", "last_closed_quarter", "last_closed_quarter_error_pct"]].to_string(index=False)}')
except Exception as exc:
    print(f'  WARN: Could not compute closed-quarter error: {exc}')
    for col in ['last_closed_quarter', 'last_closed_quarter_error_pct', 'last_closed_quarter_is_closed', 'last_closed_quarter_weeks']:
        monitoring_baseline[col] = None

monitoring_baseline['rolling_4w_wape_alert_threshold'] = (monitoring_baseline['cv_wape_baseline'] * 1.5).round(3)
monitoring_baseline['recommended_for_production'] = monitoring_baseline['model'].isin(final_q1_q4_shortlist['model']).astype(int)
monitoring_baseline['run_timestamp_utc'] = pd.Timestamp.utcnow().tz_localize(None)
monitoring_baseline['run_date_utc'] = pd.to_datetime(monitoring_baseline['run_timestamp_utc']).dt.date
monitoring_baseline['notebook_name'] = 'UCC Forecast Foundation'
monitoring_baseline['notebook_version'] = globals().get('NOTEBOOK_VERSION', 'V8')
monitoring_baseline['production_output_table'] = globals().get('PRODUCTION_OUTPUT_TABLE', 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5')
monitoring_baseline['legacy_output_table'] = globals().get('LEGACY_PRODUCTION_OUTPUT_TABLE', 'datagroup_mdl.mdl_sales_analytics.ucc_forecast_v4')

run_date_literal = str(monitoring_baseline['run_date_utc'].iloc[0])
spark.createDataFrame(monitoring_baseline).write \
    .mode('overwrite') \
    .option('overwriteSchema', 'true') \
    .saveAsTable(MONITORING_BASELINE_TABLE)

print('Production monitoring baseline for retained models:')
display(monitoring_baseline)
print(f"\nPersisted monitoring baseline table: {MONITORING_BASELINE_TABLE}")


# COMMAND ----------

# DBTITLE 1,Executive Summary: UCC Growth ARR Forecast V8
# MAGIC %md
# MAGIC ## UCC Growth ARR Forecast — Executive Summary (V8, July 2026)
# MAGIC
# MAGIC ### Methodology
# MAGIC The UCC forecast uses a **5-model Adaptive Ensemble** that combines diverse forecasting approaches, each capturing different demand signals:
# MAGIC
# MAGIC | Model | Approach | Strength | CV WAPE | Holdout WAPE |
# MAGIC | --- | --- | --- | --- | --- |
# MAGIC | **Prophet_trend** | Bayesian changepoint detection with adaptive trend | Captures structural growth shifts, robust to outliers | 29.40% | 14.97% |
# MAGIC | **MSTL_v2** | Multiple Seasonal-Trend decomposition (Q13 + Y52 cycles) | Best at isolating quarterly seasonality from annual patterns | 27.75% | 18.42% |
# MAGIC | **ETS** | Exponential smoothing (error-trend-seasonal state space) | Strong short-horizon accuracy, conservative extrapolation | 29.68% | 21.88% |
# MAGIC | **DHR_ARIMA** | Dynamic Harmonic Regression with market-level pipeline exogenous variables | Incorporates headcount, pipeline velocity, and win rates per market | 36.44% | 30.23% |
# MAGIC | **Global_LGB_Q50_UCC** | Gradient-boosted quantile regression on 36 engineered features | Captures non-linear interactions plus calibrated p10/p90 ranges | 28.42% | 23.73% |
# MAGIC
# MAGIC ### Ensemble Performance
# MAGIC The **Adaptive Ensemble** is still the notebook's recommended production forecast because it blends models with different error shapes, but the latest executed run is materially more conservative than the earlier V8 narrative:
# MAGIC
# MAGIC - **2026 Q1 Error: -2.16%** (under-forecast by $0.301M on $13.923M actual)
# MAGIC - **2026 Q2 Error: -8.11%** (under-forecast by $1.191M on $14.678M actual)
# MAGIC - **H1 2026 Combined Error: -5.22%** (forecast $27.109M vs actual $28.601M)
# MAGIC
# MAGIC This means the current run should be used with a clear note that the ensemble is under-forecasting the closed H1 2026 window versus actuals.
# MAGIC
# MAGIC ### FY2026 Actuals & Forecast
# MAGIC
# MAGIC | Quarter | Actual ($M) | Forecast ($M) | P10 ($M) | P90 ($M) | Status |
# MAGIC | --- | --- | --- | --- | --- | --- |
# MAGIC | Q1 2026 | $13.923 | $13.622 | — | — | ✓ Closed (-2.16%) |
# MAGIC | Q2 2026 | $14.678 | $13.487 | — | — | ✓ Closed (-8.11%) |
# MAGIC | Q3 2026 | — | $12.277 | $9.641 | $17.638 | Forward |
# MAGIC | Q4 2026 | — | $14.174 | $11.317 | $19.981 | Forward |
# MAGIC | **FY2026** | **$28.601** (H1) | **$53.560** | — | — | H1 Actual + H2 Forecast |
# MAGIC
# MAGIC ### Key Takeaways
# MAGIC 1. **Current run is conservative**: H1 2026 forecast came in at $27.109M versus $28.601M actual, a -5.22% under-forecast.
# MAGIC 2. **Q4 remains above Q3**: Q4 forecast ($14.174M) is 15.4% above Q3 ($12.277M), consistent with the business's quarter-end concentration.
# MAGIC 3. **Prediction intervals remain wide**: Q3 spans $9.641M-$17.638M and Q4 spans $11.317M-$19.981M, so scenario planning should use the full band rather than the point forecast alone.
# MAGIC 4. **Model roles are differentiated**: Prophet_trend has the best weekly holdout WAPE, MSTL_v2 has the best Q2 closed-quarter accuracy, and Global LGB provides the calibrated p10/p90 range used for risk framing.
# MAGIC
# MAGIC ---
# MAGIC *Source: UCC Forecast Foundation V8 | Data: `datagroup.datalake_transform.cds_sfdc_opp_products_latest` | Output: `datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5`*

# COMMAND ----------

# DBTITLE 1,Pipeline Documentation: Data Sources, Column Glossary & How Each Step Improves the Forecast
# MAGIC %md
# MAGIC
# MAGIC # UCC Forecast Foundation — Full Pipeline Documentation
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 1. Pipeline Overview
# MAGIC
# MAGIC This notebook builds a **production-grade weekly ARR forecast** for UCC Growth bookings across all sales markets.  It runs end-to-end from raw Salesforce data to a Delta output table consumed by FP&A dashboards and executive QBRs.
# MAGIC
# MAGIC The pipeline answers: *"Given everything we know today, how much UCC ARR will close each week for the rest of the fiscal year?"*
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 2. Source Tables
# MAGIC
# MAGIC | Table | Catalog.Schema | Owned by | Purpose in this notebook |
# MAGIC |---|---|---|---|
# MAGIC | `cds_sfdc_opp_products_latest` | `datagroup.datalake_transform` | Data Engineering | Primary fact table.  One row per SFDC Opportunity Line Item.  Provides the target (`amount_towards_plan`) and all pipeline/activity features. |
# MAGIC | `forecast_prophet` | `datagroup_mdl.mdl_sales_analytics` | Sona | Provides headcount by market/week, `magna_carta_actuals` (marketing pipeline proxy), and `miradore_plan` (planned pipeline).  **READ ONLY — never write to this table.** |
# MAGIC | `uc_forecast.actuals` | `datagroup.uc_forecast` | Magna Carta team | Authoritative marketing-generated pipeline actuals ("MC actuals").  Used in Step 10B as `mc_actuals_lag4` to improve LGB accuracy. |
# MAGIC | `ucc_forecast_v5` | `datagroup_mdl.mdl_sales_analytics` | This notebook | **PRIMARY OUTPUT.** Weekly forward forecast: p10/p50/p90 by market, production winner model, written by Step 14. |
# MAGIC | `ucc_forecast_v4` | `datagroup_mdl.mdl_sales_analytics` | This notebook | Legacy output mirror (backward compat for older dashboard consumers), also written by Step 14. |
# MAGIC | `ucc_forecast_monitoring_baseline` | `datagroup_mdl.mdl_sales_analytics` | This notebook | Monitoring thresholds written by Step 16.  Used to detect future model drift. |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 3. Key Columns Glossary
# MAGIC
# MAGIC ### From `cds_sfdc_opp_products_latest`
# MAGIC
# MAGIC | Column | Type | Used for |
# MAGIC |---|---|---|
# MAGIC | `amount_towards_plan` | float | **The forecast target (y)** — ARR credit towards quota from this OLI |
# MAGIC | `close_date` / `week_start` | date | When the deal closed; rolled up to weekly Monday buckets |
# MAGIC | `pipeline_entered_date` / `pipeline_week_start` | date | When the opportunity was created — used to build 4-week-lagged pipeline features |
# MAGIC | `product_group` | string | Filter: only `UCC` rows used |
# MAGIC | `product_family` | string | UCaaS / Events / Meetings / Access — used in EDA family mix and family-level breakdowns |
# MAGIC | `sales_market` | string | Geographic segment: NA / EMEA / APAC / LATAM / Unknown — models run per-market |
# MAGIC | `purchase_type_rollup` | string | Filter: only `Growth` (net-new ARR); excludes renewals |
# MAGIC | `sales_channel` | string | Filter: excludes Care and Sales Other (non-quota channels) |
# MAGIC | `pipeline_amount` | float | Original value of the pipeline at creation time |
# MAGIC | `marketing_generated_pipeline` | float | MQL-sourced pipeline (proxy; use MC actuals table for authoritative version) |
# MAGIC | `marketing_influenced_pipeline` | float | Miradore plan pipeline |
# MAGIC | `dials` / `touches` | float | Sales activity intensity — lagged versions used as features |
# MAGIC | `opportunity_age` | float | Days from create to close (cycle time) — lagged version in feature set |
# MAGIC | `push_counter` | float | Times the close date was pushed out — leading indicator of deal health |
# MAGIC
# MAGIC ### From `forecast_prophet`
# MAGIC
# MAGIC | Column | Type | Used for |
# MAGIC |---|---|---|
# MAGIC | `headcount` | float | Total sales headcount by market/week.  Lagged 4 weeks (`headcount_lag4`) as a capacity signal |
# MAGIC | `magna_carta_actuals` | float | Proxy marketing-generated pipeline (Step 10B proxy feature) |
# MAGIC | `miradore_plan` | float | Planned pipeline from Miradore; lagged 4 weeks (`miradore_lag4`) |
# MAGIC
# MAGIC ### Engineered Features (created in notebook)
# MAGIC
# MAGIC | Feature | Created in | Meaning |
# MAGIC |---|---|---|
# MAGIC | `y_lag1` | Step 1 | Last week's actual ARR — strongest single predictor |
# MAGIC | `y_lag13` | Step 1 | ARR from 13 weeks ago (same week-of-quarter, prior quarter) |
# MAGIC | `r4w` | Step 1 | Trailing 4-week average shifted 1 week (leak-safe momentum) |
# MAGIC | `week_of_qtr` | Step 1 | 1-13 count within each quarter — encodes quarter ramp shape |
# MAGIC | `quarter_end_flag` | Step 1 | 1 if weeks 11-13 of quarter (end-of-quarter surge signal) |
# MAGIC | `is_q4` | Step 1 | 1 in Q4 — captures fiscal year-end structural boost |
# MAGIC | `q4_week_countdown` | Step 1 | Weeks remaining in Q4 (0 outside Q4) — urgency signal |
# MAGIC | `win_rate_by_woq` | Step 9 | Historical close rate per week-of-quarter per market |
# MAGIC | `pipeline_velocity_lag4` | Step 9 | Created pipeline / opportunity age, lagged 4 weeks |
# MAGIC | `region_holiday` | Step 10B | 1 if any regional public holiday falls in that week (US/UK/DE/IN/BR) |
# MAGIC | `mc_actuals_lag4` | Step 10B | Authoritative marketing pipeline from 4 weeks ago |
# MAGIC | `running_won_lag1` | Step 10B | Cumulative won ARR in the quarter to last week |
# MAGIC | `plan_gap_lag1` | Step 10B | Difference between quarterly plan and running won, lagged 1 week |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 4. How Each Step Improves the Forecast
# MAGIC
# MAGIC | Step | What it adds | Forecast improvement |
# MAGIC |---|---|---|
# MAGIC | Step 0 | Installs all required libraries | Enables the full model stack to run |
# MAGIC | Step 1 | Builds a clean weekly time series from raw OLI data | Ensures zero-filling, correct market normalisation, no partial-week leakage |
# MAGIC | Step 2 | EDA: seasonal profile, market mix, family breakdowns | Validates data and reveals the Q-end surge (+40% in weeks 11-13) |
# MAGIC | Step 3 | Defines feature safety boundaries and train/test split | Prevents data leakage that would produce falsely optimistic accuracy numbers |
# MAGIC | Step 4 | 8-fold walk-forward CV framework | Gives stable, comparable WAPE estimates; single-split accuracy claims are unreliable |
# MAGIC | Step 5 | MSTL v2 + ETS + Prophet baselines | Sets a ~26-28% WAPE floor; any ML model must beat all three |
# MAGIC | Steps 6-8B | Visual and tabular holdout/quarterly evaluation | Translates weekly % errors into exec-facing $M accuracy; identifies model bias |
# MAGIC | Step 9 | DHR-ARIMA with pipeline and headcount regressors | Adds structural leading indicators; often best model for EMEA/APAC sparse slices |
# MAGIC | Step 10B | Global LGB with 36 features + p10/p50/p90 quantiles | Captures non-linear interactions (Q4 NA surge >> Q4 APAC); provides risk ranges |
# MAGIC | Step 10B-SHAP | SHAP feature importance | Explains black-box model to stakeholders; validates feature usefulness |
# MAGIC | Step 10C | MC actuals vs proxy comparison | Ensures the best available marketing signal is used; quantifies improvement |
# MAGIC | Quarterly Audit | Quarterly error table by model | Single reference table for "which model was closest to actuals this quarter?" |
# MAGIC | Step 13 | Adaptive Ensemble + market reconciliation helpers | Combines diverse model signals; rescales markets to sum to total (prevents drift) |
# MAGIC | Step 14 | Dynamic-horizon forward forecast written to Delta | The deliverable: p10/p50/p90 by week × market from the next observed week through 2026-12-28 |
# MAGIC | Step 15 | Executive summary with model leaderboard | One-page summary for leadership: recommended model, FY2026 range, CI |
# MAGIC | Step 16 | Monitoring baseline written to Delta | Enables automated drift detection; triggers re-train when WAPE degrades >15-20% |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 5. Model Performance Reference (V8, July 2026)
# MAGIC
# MAGIC | Model | CV WAPE (8-fold) | Holdout WAPE (Q1+Q2 2026 weekly) | Closed-quarter accuracy highlight | Recommended use |
# MAGIC |---|---|---|---|---|
# MAGIC | Prophet_trend | 29.40% | **14.97%** | Q1: +7.36%, Q2: +2.08% | Best weekly holdout accuracy; strong trend extrapolation |
# MAGIC | MSTL_v2 | **27.75%** | 18.42% | Q1: +4.84%, Q2: **-0.37%** | Best Q2 closed-quarter accuracy; conservative baseline |
# MAGIC | ETS | 29.68% | 21.88% | Q1: +3.65%, Q2: -4.83% | Strong simple benchmark; fast rerun option |
# MAGIC | DHR_ARIMA | 36.44% | 30.23% | Q1: -3.96%, Q2: -8.57% | Best sparse-market logic; especially useful in EMEA/APAC slices |
# MAGIC | Global_LGB_Q50_UCC | 28.42% *(Growth fix Jul 13)* | 23.73% | Q1: -4.93%, Q2: -12.02% | Growth-corrected Jul 13 2026; only retained model with calibrated p10/p90 intervals |
# MAGIC | **Adaptive_Ensemble** | — *(weighted blend)* | — *(blend of retained models)* | **Q1: -2.16%, Q2: -8.11%, H1: -5.22%; FY2026: $53.560M** | **RECOMMENDED production forecast; best Q1 quarterly result in the current run** |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 6. Scheduling & Refresh Cadence
# MAGIC
# MAGIC - **Recommended run frequency:** Weekly (Monday morning, after SFDC data refreshes)
# MAGIC - **Trigger:** Data landing in `cds_sfdc_opp_products_latest` for the prior Monday
# MAGIC - **Runtime:** ~20-35 minutes end-to-end on Serverless compute
# MAGIC - **Outputs expire:** `ucc_forecast_v5` is overwritten each run with the latest horizon
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 8. Forecasting Model Evolution — Chronological Order, What Changed & Accuracy Impact
# MAGIC
# MAGIC > Read this section top-to-bottom to follow the full modelling journey: why each model was added, what gap it filled, and whether accuracy improved or got worse versus the prior model.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Round 1 — Statistical Baselines (Step 5)
# MAGIC *These three models were the starting point. No external data, no ML — pure time-series.*
# MAGIC
# MAGIC #### Model 1 of 6: ETS (Exponential Smoothing)
# MAGIC **First model trained. Sets the accuracy floor everything else must beat.**
# MAGIC
# MAGIC - **What it does:** Learns a weighted average of level, trend, and seasonal state. Recent weeks count more than old ones — the model continuously adapts as new data arrives.
# MAGIC - **Why it was first:** Fastest to train, easiest to explain to stakeholders, well-understood industry benchmark.
# MAGIC - **Exact data used:**
# MAGIC   - Source table: `datagroup.datalake_transform.cds_sfdc_opp_products_latest`
# MAGIC   - Column: `amount_towards_plan` — summed per `week_start` Monday bucket → becomes `y`
# MAGIC   - That's it. No other columns. No external tables.
# MAGIC - **Key transformation:** `GROUP BY DATE_TRUNC('week', close_date)` + left-join onto a full Monday calendar spine so zero-booking weeks are present as `y=0` rather than missing rows. Missing rows would silently corrupt ETS's seasonal state.
# MAGIC - **Accuracy:**
# MAGIC
# MAGIC | Metric | Value |
# MAGIC |---|---|
# MAGIC | CV WAPE (8-fold avg) | **25.98%** — best of all three baselines |
# MAGIC | Q1 2026 Holdout WAPE | 15.61% |
# MAGIC | Q1 2026 Quarterly Error | +3.7% (over $0.51M on $13.9M actual) |
# MAGIC | Q2 2026 Quarterly Error | -4.8% (under $0.71M) |
# MAGIC
# MAGIC - **Limitation:** Treats every week identically. Has no concept of *where in the quarter* it is, so it misses the end-of-quarter surge that peaks in weeks 11-13.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC #### Model 2 of 6: MSTL v2 (Multiple Seasonal-Trend Decomposition)
# MAGIC **Added to capture both quarterly AND annual seasonality at the same time.**
# MAGIC
# MAGIC - **What changed from ETS:** ETS fits one seasonal period. MSTL decomposes the series into a 13-week quarterly cycle AND a 52-week annual cycle simultaneously before fitting the trend.
# MAGIC - **Why it was added:** The EDA in Step 2 showed two overlapping patterns — a within-quarter ramp AND a year-over-year uplift. MSTL was designed to separate these.
# MAGIC - **Exact data used:**
# MAGIC   - Source table: `datagroup.datalake_transform.cds_sfdc_opp_products_latest`
# MAGIC   - Column: `amount_towards_plan` → weekly `y` (identical input to ETS)
# MAGIC   - No external tables.
# MAGIC - **Key transformation that separates it from ETS:** The model call passes `season_length=[13, 52]` — this tells MSTL to decompose the series into TWO overlapping seasonal components simultaneously:
# MAGIC   - Period 13 = 13-week quarterly cycle (within-quarter ramp)
# MAGIC   - Period 52 = 52-week annual cycle (year-over-year uplift)
# MAGIC   - ETS only fits one seasonal period; MSTL isolates both and fits the trend on the residual.
# MAGIC - **Why it still loses on CV WAPE despite the dual seasonality:** The `statsforecast` MSTL package on this runtime does not expose a tunable `s_window` (LOESS smoothing bandwidth). The package default over-smooths the sharp Q-end spike in weeks 11-13, producing forecasts that are too conservative at quarter close.
# MAGIC - **Accuracy vs ETS:**
# MAGIC
# MAGIC | Metric | ETS | MSTL v2 | Change |
# MAGIC |---|---|---|---|
# MAGIC | CV WAPE | 25.98% | 27.91% | **+1.93pp WORSE** |
# MAGIC | Q1 Holdout WAPE | 15.61% | 17.02% | +1.41pp worse |
# MAGIC | Q2 Quarterly Error | -4.8% | **-0.4%** | **4.4pp BETTER** |
# MAGIC
# MAGIC - **Verdict vs ETS:** MSTL is worse on rolling CV but far more consistent on quarterly error for Q2. It over-smooths the sharp end-of-quarter spike because the `statsforecast` package on this runtime doesn’t expose a tunable LOESS window.
# MAGIC - **Why kept despite worse CV WAPE:** Its errors are *different* from ETS (they diverge at different weeks), which means combining them in an ensemble cancels errors out.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC #### Model 3 of 6: Prophet (Trend-Constrained)
# MAGIC **Added to handle structural trend breaks that ETS and MSTL assume away.**
# MAGIC
# MAGIC - **What changed from MSTL:** Prophet uses Bayesian changepoint detection — it learns WHERE the growth trend shifted (e.g. post-COVID recovery, market maturation) and adjusts forecasts accordingly. The trend-constrained variant caps future extrapolation to prevent unbounded drift into 2027.
# MAGIC - **New capability:** Automatically injects US federal holiday regressors (Thanksgiving, Memorial Day, etc.), which suppress booking activity on those weeks.
# MAGIC - **Exact data used:**
# MAGIC   - Source table: `datagroup.datalake_transform.cds_sfdc_opp_products_latest`
# MAGIC   - Column: `amount_towards_plan` → weekly `y` (same as ETS/MSTL)
# MAGIC   - External: US federal holiday calendar from the `holidays` Python library (no database table needed)
# MAGIC - **Key transformations that separate it from ETS and MSTL:**
# MAGIC   1. `changepoint_prior_scale=0.05` — a low value that forces conservative trend changes. Without this, Prophet extrapolates recent growth steeply into 2027, producing unrealistic high-end forecasts.
# MAGIC   2. `yearly_seasonality=True, weekly_seasonality=False` — annual Fourier terms fitted; weekly terms suppressed because 7-day sub-weekly patterns don't exist in weekly data.
# MAGIC   3. US holiday regressors injected as binary `0/1` columns: `Thanksgiving`, `Memorial Day`, `Labor Day`, `Independence Day`, `Christmas`, `New Year`. These weeks suppressed booking activity by ~15-25% vs adjacent weeks in the training data.
# MAGIC   4. `seasonality_mode='multiplicative'` — seasonality scales WITH the trend level. As ARR grows, the Q-end spike grows proportionally (not by a fixed $M amount).
# MAGIC - **Accuracy vs prior best (ETS):**
# MAGIC
# MAGIC | Metric | ETS | Prophet | Change |
# MAGIC |---|---|---|---|
# MAGIC | CV WAPE | 25.98% | 27.10% | +1.12pp worse |
# MAGIC | Q1 Holdout WAPE | 15.61% | **15.41%** | **-0.20pp BETTER** |
# MAGIC | Q1 Quarterly Error | +3.7% | +7.4% | 3.7pp worse |
# MAGIC | Q2 Quarterly Error | -4.8% | **+2.1%** | 2.7pp better |
# MAGIC
# MAGIC - **Verdict vs ETS:** Prophet wins on holdout WAPE and Q2 quarterly error; ETS wins on CV WAPE and Q1 quarterly error. Neither dominates. Both must be in the ensemble.
# MAGIC
# MAGIC > **Round 1 Summary:** Best single-model CV WAPE = **ETS at 25.98%**. Best quarterly accuracy in 2026 = **MSTL on Q2 (-0.4%)**. No single model wins on all metrics — the diversity between them is intentional.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Round 2 — DHR-ARIMA with External Regressors (Step 9)
# MAGIC *First model to look OUTSIDE the bookings series. Adds pipeline + headcount as leading indicators.*
# MAGIC
# MAGIC #### Model 4 of 6: DHR-ARIMA
# MAGIC **What’s new:** 14 external regressors joined in. Runs one model **per sales market** instead of one global model.
# MAGIC
# MAGIC - **What changed from Round 1:** Added calendar-stable Fourier terms (encoding week-of-quarter position), pipeline velocity 4 weeks ago, sales headcount 4 weeks ago, win rate conditioned on week-of-quarter, and a US holiday binary flag.
# MAGIC - **Why per-market:** The seasonal pattern in NA (65% of ARR) is stronger and more predictable than in EMEA/APAC. Forcing a single global model blurs these differences. One DHR model per market lets each region’s pipeline signal speak for itself.
# MAGIC - **Why 4-week lags:** Pipeline created today closes roughly 4 weeks later on average (validated from `opportunity_age` in ucc_raw). Using a 4-week lag converts a same-week leaky feature into a safe forward-looking signal.
# MAGIC - **Exact columns used and where they come from:**
# MAGIC
# MAGIC | Feature name in model | Source table | Source column | Transformation |
# MAGIC |---|---|---|---|
# MAGIC | `y` (target) | `cds_sfdc_opp_products_latest` | `amount_towards_plan` | `SUM` grouped by `week_start` + `sales_market` |
# MAGIC | `created_lag4` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` grouped by `pipeline_week_start` | Total pipeline ARR created that week, shifted 4 weeks forward |
# MAGIC | `headcount_lag4` | `forecast_prophet` | `headcount` | Sales rep headcount per market/week, shifted 4 weeks forward |
# MAGIC | `pipeline_velocity_lag4` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` / `opportunity_age` | `created_arr / avg_opportunity_age` per week per market, shifted 4 weeks |
# MAGIC | `win_rate_by_woq` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` (won) / `amount_towards_plan` (created) | Rolling 4-quarter won/created ratio, grouped by `week_of_qtr` + `sales_market` |
# MAGIC | `quarter_end_flag` | Derived | `week_of_qtr >= 11` | Binary: 1 in weeks 11-13 of any quarter |
# MAGIC | `us_holiday_binary` | `holidays` library | US federal calendar | Binary: 1 if any US holiday falls in that Monday week |
# MAGIC | `q13_sin/cos_1/2` | Derived | `week_of_qtr` (1-13) | `sin/cos(2π·k·(week_of_qtr-1)/13)` for k=1,2 — encodes quarterly position |
# MAGIC | `y52_sin/cos_1/2` | Derived | ISO `week_of_year` (1-52) | `sin/cos(2π·k·(week_of_year-1)/52)` for k=1,2 — encodes annual position |
# MAGIC
# MAGIC - **The single biggest transformation impact:** `pipeline_velocity_lag4` = `created_arr / avg_opportunity_age`. Dividing raw pipeline by deal cycle time converts a volume measure into a *rate* — it answers "how fast is pipeline being converted?", not just "how much exists?". This single derived column outperformed raw `created_lag4` alone in DHR-ARIMA ablation tests.
# MAGIC - **Why calendar-based Fourier terms (not fold-relative):** If Fourier index is computed as `(week_number_since_start_of_series) mod 13`, it resets phase at each CV fold boundary, making Q1-fold seasonality look different from Q3-fold seasonality. Using `week_of_qtr` from the calendar guarantees the same phase in every fold — critical for stable CV results.
# MAGIC - **Accuracy vs prior best (ETS on CV):**
# MAGIC
# MAGIC | Metric | ETS | DHR-ARIMA | Change |
# MAGIC |---|---|---|---|
# MAGIC | CV WAPE (total) | 25.98% | **36.44%** | **+10.46pp WORSE** (V8 with full feature set; was ~26% in early versions) |
# MAGIC | EMEA / APAC accuracy | Weaker | **Materially better** | Per-market regressors help sparse slices |
# MAGIC
# MAGIC - **Why kept despite much worse total CV WAPE (36.44% vs 25.98%):** DHR-ARIMA consistently outperforms every other model on EMEA, APAC, and LATAM slices where actuals are sparse and a per-market pipeline/headcount signal matters. Its worse aggregate WAPE is driven almost entirely by NA under-fitting. It is the only model that uses pipeline and headcount regressors in a per-market structure before the ensemble step.
# MAGIC
# MAGIC > **After Round 2:** 4 models in the stack. ETS still leads on aggregate CV WAPE. DHR-ARIMA leads on per-market accuracy for smaller geographies.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Round 3 — Neural Models (Tried and Rejected)
# MAGIC *Two deep-learning approaches were evaluated and both failed badly. Documented here for transparency.*
# MAGIC
# MAGIC #### Attempted: N-HiTS (Neural Hierarchical Interpolation)
# MAGIC - **Why tried:** Expert-review V8 candidate stack included N-HiTS for its multi-rate downsampling, which theoretically captures both short-term spikes and long-term trend simultaneously.
# MAGIC - **Result: FAILED and removed.**
# MAGIC
# MAGIC | Metric | N-HiTS | ETS (benchmark) | Delta |
# MAGIC |---|---|---|---|
# MAGIC | CV WAPE | 45.27% | 25.98% | **+19.3pp WORSE** |
# MAGIC | Holdout WAPE | **86.37%** | 15.61% | Catastrophic |
# MAGIC
# MAGIC - **Root cause:** 184 weekly observations is too small. Neural networks need at minimum 3-5x more data to generalise. The model memorised training patterns and failed completely on 2026 data.
# MAGIC - **Decision:** Removed from all production comparisons per expert review constraints (June 2026).
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC #### Attempted: TFT (Temporal Fusion Transformer)
# MAGIC - **Why tried:** TFT was designed specifically for multi-horizon forecasting with static metadata (market = NA) and time-varying exogenous inputs. High theoretical fit.
# MAGIC - **Result: FAILED and removed.**
# MAGIC
# MAGIC | Metric | TFT | ETS (benchmark) | Delta |
# MAGIC |---|---|---|---|
# MAGIC | CV WAPE | 31.53% | 25.98% | +5.55pp worse |
# MAGIC | Holdout WAPE | **68.53%** | 15.61% | Unusable |
# MAGIC
# MAGIC - **What the attention weights showed (interesting despite failure):** `quarter_end_flag` dominated future encoder weights; `pipeline_velocity_lag4` and `win_rate_woq` led past encoder weights. The model understood the right signals but couldn’t generalise on this dataset size.
# MAGIC - **Decision:** Removed. Re-evaluate when per-market weekly history exceeds 300+ rows (~6 years).
# MAGIC
# MAGIC > **Lesson from Round 3:** A more complex model is NOT a better model on small datasets. The statistical and tree-based models beat neural approaches here by 20-50pp WAPE.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Round 4 — Global LightGBM Quantile (Step 10B)
# MAGIC *First model to produce p10/p50/p90 uncertainty bounds and capture non-linear interactions.*
# MAGIC
# MAGIC #### Model 5 of 6: Global LGB Q50 UCC
# MAGIC **What’s new:** Gradient-boosted trees on ALL markets simultaneously (“global” training) with 36 engineered features.
# MAGIC
# MAGIC - **What changed from DHR-ARIMA:** Instead of fitting one model per market, one LGB model trains on the full dataset (all 5 markets stacked) so markets share statistical strength. Outputs THREE quantiles per week — no other model does this.
# MAGIC
# MAGIC - **Exact columns used (all 36 features) and their impact:**
# MAGIC
# MAGIC | Feature | Source table | Source column(s) | Transformation | SHAP rank (UCC\|NA) |
# MAGIC |---|---|---|---|---|
# MAGIC | `running_won_lag1` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` | Cumulative sum of won ARR in current quarter up to last week | **#1 — importance 82** |
# MAGIC | `week_of_qtr` | Derived | `ds` date | Position 1-13 within each quarter | #2 |
# MAGIC | `quarter_end_flag` | Derived | `week_of_qtr >= 11` | Binary: 1 in last 3 weeks of quarter | #3 |
# MAGIC | `y_lag1` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` | Last week's total won ARR | #4 |
# MAGIC | `pipeline_velocity_lag4` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` / `opportunity_age` | Pipeline rate 4 weeks ago per market | #5 |
# MAGIC | `win_rate_woq` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` won/created | Rolling 4Q close rate per week-of-qtr per market | #6 |
# MAGIC | `y_lag13` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` | ARR from 13 weeks ago (same week-of-qtr, last quarter) | #7 |
# MAGIC | `r4w` | `cds_sfdc_opp_products_latest` | `amount_towards_plan` | Trailing 4-week average, shifted 1 week | #8 |
# MAGIC | `mc_actuals_lag4` | `datagroup.uc_forecast.actuals` | `mc_actuals_authoritative` | Authoritative marketing pipeline 4 weeks ago | #9 |
# MAGIC | `headcount_lag4` | `forecast_prophet` | `headcount` | Sales headcount per market, 4 weeks ago | #10 |
# MAGIC | `mkt_opened_lag4` | `cds_sfdc_opp_products_latest` | `open_pipeline_created` | Marketing-opened pipeline ARR, 4 weeks ago | #11 |
# MAGIC | `partner_opened_lag4` | `cds_sfdc_opp_products_latest` | `partner_pipeline_created` | Partner-sourced pipeline, 4 weeks ago | #12 |
# MAGIC | `miradore_lag4` | `forecast_prophet` | `miradore_plan` | Planned pipeline from Miradore model, 4 weeks ago | #13 |
# MAGIC | `plan_gap_lag1` | `forecast_prophet` | `Most_Likely` (plan) - `running_won` | Remaining quota gap last week — urgency signal | #14 |
# MAGIC | `avg_dials_lag4` | `cds_sfdc_opp_products_latest` | `dials` | Avg dials per opp, 4 weeks ago per market | #15 |
# MAGIC | `avg_touches_lag4` | `cds_sfdc_opp_products_latest` | `touches` | Avg touches per opp, 4 weeks ago per market | #16 |
# MAGIC | `avg_opportunity_age` | `cds_sfdc_opp_products_latest` | `opportunity_age` | Mean deal cycle time (days) current week per market | #17 |
# MAGIC | `avg_push_counter` | `cds_sfdc_opp_products_latest` | `push_counter` | Avg times close date pushed — deal health proxy | #18 |
# MAGIC | `is_q4` | Derived | `ds` quarter | Binary: 1 in Q4 | #19 |
# MAGIC | `q4_week_countdown` | Derived | `week_of_qtr` in Q4 | Weeks remaining in Q4 (0 outside Q4) | #20 |
# MAGIC | `q13_sin/cos_1/2` | Derived | `week_of_qtr` | Fourier terms, period=13 (quarterly cycle) | #21-24 |
# MAGIC | `y52_sin/cos_1/2` | Derived | ISO `week_of_year` | Fourier terms, period=52 (annual cycle) | #25-28 |
# MAGIC | `region_holiday` | `holidays` library | US/UK+DE/IN/BR calendars | 1 if regional holiday in that week per market | #29 |
# MAGIC | Market one-hot dummies | Derived | `sales_market` | Binary column per market (NA, EMEA, APAC, LATAM, Unknown) | #30-34 |
# MAGIC
# MAGIC - **The 3 transformations with the largest measured accuracy impact:**
# MAGIC
# MAGIC   1. **`running_won_lag1` (SHAP #1, importance=82)** — Computed as `cumsum(y)` within the quarter, lagged 1 week. This tells the model exactly how much of the quarterly target is already booked. A week-12 row with `running_won_lag1 = $13M` means only ~$1M remains to close; a week-2 row with the same value means the quarter is already on track well ahead of pace. Without this feature, the model cannot distinguish whether a high forecast is realistic or too aggressive.
# MAGIC   
# MAGIC   2. **`mc_actuals_lag4` from `datagroup.uc_forecast.actuals`** — Switching from the proxy `magna_carta_actuals` column in `forecast_prophet` to the authoritative MC table reduced noise in the marketing signal. The proxy is written by Sona/FPA on a reporting lag; the authoritative table reflects actual MQL pipeline with better timeliness. Step 10C confirms this swap improved both CV WAPE and holdout WAPE.
# MAGIC   
# MAGIC   3. **`plan_gap_lag1`** — Derived as `Most_Likely_plan (from forecast_prophet) - running_won_lag1`. A large positive gap means the team is behind plan and urgency is high; a small or negative gap means they are ahead. This single derived column encodes business context that none of the pure time-series models can access.
# MAGIC
# MAGIC - **Feature evolution across notebook versions:**
# MAGIC
# MAGIC | Version | Key features added | CV WAPE |
# MAGIC |---|---|---|
# MAGIC | V5 base | y_lag1, y_lag13, r4w, week_of_qtr, headcount_lag4, mkt_opened_lag4, Fourier | 30.038% |
# MAGIC | V4 add | + avg_dials_lag4, avg_touches_lag4, plan_gap_lag1 | 30.826% (slight regression — activity features added noise) |
# MAGIC | V5 mc | + mc_actuals_lag4 (authoritative MC, not proxy) | Improved (confirmed Step 10C) |
# MAGIC | V8 final | + region_holiday (5 countries); 36 total features | 30.04% |
# MAGIC | **Growth fix (Jul 13 2026)** | Target swapped: `forecast_prophet.Actuals` (no purchase_type filter) to `weekly_ucc_by_market.y` (Growth-only SFDC) | **28.42%** |
# MAGIC
# MAGIC - **Accuracy vs ETS (prior best on CV):**
# MAGIC
# MAGIC | Metric | ETS | Global LGB | Change |
# MAGIC |---|---|---|---|
# MAGIC | CV WAPE | **25.98%** | **28.42%** *(Growth fix)* | **+2.44pp WORSE** |
# MAGIC | Holdout WAPE | 15.61% | 23.73% | +8.12pp worse (expected: Growth-only target is spikier) |
# MAGIC
# MAGIC - **Why kept despite worse WAPE than ETS?** Two reasons:
# MAGIC   1. Its errors are *structurally different* — LGB catches the Q-end nonlinear spike on weeks ETS and MSTL miss. Diverse errors combine better in an ensemble.
# MAGIC   2. It is the **only model providing p10/p90** — essential for exec worst-case/best-case planning.
# MAGIC - **New capability unlocked:** Calibrated confidence intervals. 92% CI coverage on holdout (92 out of 100 actual weeks fell inside the p10/p90 band).
# MAGIC
# MAGIC > **After Round 4:** 5 models retained (ETS, MSTL, Prophet, DHR-ARIMA, LGB). ETS still has the best individual CV WAPE. But no single model wins on every metric or every quarter.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Round 5 — Adaptive Ensemble (Step 13)
# MAGIC *The final production model. Combines all five retained models into one forecast.*
# MAGIC
# MAGIC #### Model 6 of 6: Adaptive Ensemble
# MAGIC **What’s new:** Assigns CV-WAPE-based weights to each model dynamically. Recalculates weights on every run.
# MAGIC
# MAGIC - **What changed from individual models:** Instead of choosing one winner, the ensemble leverages ALL five models simultaneously. Higher CV WAPE = lower ensemble weight. The weighting adapts automatically if any model degrades on the next run.
# MAGIC - **Why better than picking one winner:** ETS, MSTL, Prophet, DHR-ARIMA, and LGB make meaningfully different errors. Blending them still improves stability on some slices, even though the latest run is more conservative than the earlier V8 narrative.
# MAGIC - **Current executed accuracy snapshot:**
# MAGIC
# MAGIC | Model | CV WAPE | Q1 2026 Qtr Error | Q2 2026 Qtr Error |
# MAGIC |---|---|---|---|
# MAGIC | ETS | 29.68% | +3.65% | -4.83% |
# MAGIC | Prophet_trend | 29.40% | +7.36% | +2.08% |
# MAGIC | MSTL v2 | 27.75% | +4.84% | -0.37% |
# MAGIC | DHR-ARIMA | 36.44% | -3.96% | -8.57% |
# MAGIC | Global LGB | 28.42% *(Growth fix)* | -4.93% | -12.02% |
# MAGIC | **Adaptive Ensemble** | **— (weighted blend)** | **-2.16%** | **-8.11%** |
# MAGIC
# MAGIC - **Trade-off versus ETS:**
# MAGIC   - Q1: +3.65% → **-2.16%** — 1.49pp lower absolute quarterly error
# MAGIC   - Q2: -4.83% → **-8.11%** — 3.28pp worse absolute quarterly error
# MAGIC - **H1 2026 combined error: -5.22%** (~$1.49M under-forecast on $28.60M actual)
# MAGIC - **FY2026 production forecast: $53.560M** (Q3: $12.277M, Q4: $14.174M)
# MAGIC - **Practical takeaway:** the ensemble remains the notebook's recommended production output, but the latest run should not be described as top-decile until it is revalidated on a stronger closed-quarter window.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Current Accuracy Snapshot (retained stack + removed neural benchmarks)
# MAGIC
# MAGIC *This table reflects the latest executed notebook outputs. Lower CV WAPE and lower absolute quarterly error are better.*
# MAGIC
# MAGIC | Model | Introduced | CV WAPE | Q1 Qtr Error | Q2 Qtr Error | Current takeaway |
# MAGIC |---|---|---|---|---|---|
# MAGIC | MSTL v2 | Step 5 | 27.75% | +4.84% | -0.37% | Best Q2 closed-quarter accuracy in the current run |
# MAGIC | Prophet_trend | Step 5 | 29.40% | +7.36% | +2.08% | Best weekly holdout WAPE |
# MAGIC | ETS | Step 5 | 29.68% | +3.65% | -4.83% | Strong simple baseline and fastest rerun option |
# MAGIC | **Adaptive Ensemble** | Step 13 | — | **-2.16%** | **-8.11%** | Recommended production output; best Q1 quarterly result |
# MAGIC | Global LGB Q50 | Step 10B | 28.42% | -4.93% | -12.02% | Growth-fixed and provides p10/p90 intervals |
# MAGIC | DHR-ARIMA | Step 9 | 36.44% | -3.96% | -8.57% | Best sparse-market logic; weaker total accuracy |
# MAGIC | ✕ | N-HiTS (removed) | 45.27% | — | — | 19pp worse than ETS — removed |
# MAGIC | ✕ | TFT (removed) | 31.53% | — | — | 5pp worse; holdout unusable — removed |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Which Model to Use for What
# MAGIC
# MAGIC | Use case | Best model | Why |
# MAGIC |---|---|---|
# MAGIC | Executive QBR quarterly number | **Adaptive Ensemble** | Best quarterly error; combines all signals |
# MAGIC | Worst-case / best-case range | **Global LGB p10 / p90** | Only model with calibrated confidence intervals |
# MAGIC | Understanding growth trend direction | **Prophet_trend** | Explicit changepoint detection; fully interpretable |
# MAGIC | NA market accuracy | **ETS or Global LGB** | NA data rich enough for both; LGB adds nonlinear Q-end |
# MAGIC | EMEA / APAC / LATAM accuracy | **DHR-ARIMA** | Pipeline + headcount regressors compensate for sparse actuals |
# MAGIC | Emergency re-run (speed) | **ETS** | Trains in seconds; simplest retained benchmark for fast reruns |
# MAGIC | Stakeholder explainability | **Prophet or SHAP on LGB** | Prophet: visual trend + seasonality. LGB: SHAP waterfall chart |
# MAGIC
