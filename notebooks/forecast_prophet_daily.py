# Databricks notebook source
# MAGIC %md
# MAGIC # Prophet ARR Forecast — Daily Refresh
# MAGIC Writes to `datagroup_mdl.mdl_sales_analytics.forecast_prophet`
# MAGIC
# MAGIC **Schema matches**: ds, product, sales_market, pe_account_flag, year, month,
# MAGIC week_number, summer, winter, isweek1, Actuals, avg_deal_size, avg_sales_cycle,
# MAGIC all_created_arr, total_partner_pipeline, marketing_generated_pipeline,
# MAGIC marketing_influenced_pipeline, avg_dials, avg_touches, avg_push_counter,
# MAGIC number_of_opps, headcount, avg_opportunity_age, Most_Likely, Worst_Case, Best_Case
# MAGIC
# MAGIC **Run schedule**: Daily via Databricks Workflow (recommended: 6 AM UTC)
# MAGIC **MAPE target**: < 20% on 13-week holdout

# COMMAND ----------
# ── INSTALL DEPENDENCIES ───────────────────────────────────────────────────────
import subprocess
subprocess.check_call(["pip", "install", "prophet==1.1.5", "-q"])

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
# ── 0. CONFIGURATION ───────────────────────────────────────────────────────────
import warnings
warnings.filterwarnings("ignore")

import datetime as dt
import numpy as np
import pandas as pd
from prophet import Prophet

# Source
OPP_TABLE        = "datalake_transform.cds_sfdc_opp_products_latest"
HEADCOUNT_TABLE  = "datalake_transform.cds_sfdc_headcount_census"   # adjust if different

# Gold output — match Sona's existing table
OUTPUT_TABLE = "datagroup_mdl.mdl_sales_analytics.forecast_prophet"

# Training window
TRAIN_START = "2023-01-01"   # aligned with Sona's start date

# Forecast horizon: rest of current quarter + next quarter (max 26 weeks)
today = dt.date.today()
# Find quarter-end
qend_month = ((today.month - 1) // 3 + 1) * 3
qend = dt.date(today.year + (1 if qend_month > 12 else 0),
               qend_month % 12 or 12, 1)
# add 3 more months = next quarter end
nqend_month = qend_month + 3
nqend = dt.date(qend.year + (1 if nqend_month > 12 else 0),
                nqend_month % 12 or 12, 1)
FORECAST_HORIZON = max(13, (nqend - today).days // 7)

print(f"✓ Config: train_start={TRAIN_START}, horizon={FORECAST_HORIZON}w, output={OUTPUT_TABLE}")

# COMMAND ----------
# ── 1. LOAD RAW OPPORTUNITY DATA ───────────────────────────────────────────────
raw = spark.sql(f"""
SELECT
    salesforce_opportunity_line_item_id AS opp_id,
    close_date,
    pipeline_entered_date,
    product_group,
    sales_market,
    sales_channel,
    amount_towards_plan,
    CASE WHEN pe_account = 'True' OR pe_account = true THEN true ELSE false END AS pe_account_flag,
    avg_deal_size_field,
    sales_cycle_days,
    dials,
    touches,
    push_counter,
    opportunity_age
FROM {OPP_TABLE}
WHERE is_won               = 'True'
  AND is_closed            = 'True'
  AND purchase_type_rollup = 'Growth'
  AND sales_channel NOT IN ('Care', 'Sales Other')
  AND product_group        IN ('UCC', 'ITSG')
  AND demo_stage           = 0
  AND close_date           >= '{TRAIN_START}'
  AND close_date           < current_date()
""").toPandas()

# Load pipeline-created data (for all_created_arr lag feature)
pipeline_raw = spark.sql(f"""
SELECT
    pipeline_entered_date,
    product_group,
    sales_market,
    amount_towards_plan AS pipeline_arr,
    CASE WHEN pe_account = 'True' OR pe_account = true THEN true ELSE false END AS pe_account_flag
FROM {OPP_TABLE}
WHERE purchase_type_rollup = 'Growth'
  AND sales_channel NOT IN ('Care', 'Sales Other')
  AND product_group IN ('UCC', 'ITSG')
  AND demo_stage = 0
  AND pipeline_entered_date >= '{TRAIN_START}'
  AND pipeline_entered_date < current_date()
""").toPandas()

print(f"✓ Raw rows: {len(raw):,} | Pipeline rows: {len(pipeline_raw):,}")

# COMMAND ----------
# ── 2. FEATURE ENGINEERING ─────────────────────────────────────────────────────

def snap_to_monday(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return s - pd.to_timedelta(s.dt.dayofweek, unit='D')

# Snap dates to week-start (Monday)
raw['week_start']  = snap_to_monday(raw['close_date'])
pipeline_raw['pipe_week'] = snap_to_monday(pipeline_raw['pipeline_entered_date'])

# Market normalization
for df in [raw, pipeline_raw]:
    mkt_col = 'sales_market'
    df[mkt_col] = df[mkt_col].replace(['', None, np.nan, 'Unknown'], 'Unknown')
    df[mkt_col] = df[mkt_col].replace({'AUS/ROW': 'APAC', 'INDIA': 'APAC'})

# ── Actuals: weekly ARR by (product, market, pe_flag) ─────────────────────────
actuals = (
    raw.groupby(['week_start', 'product_group', 'sales_market', 'pe_account_flag'], as_index=False)
    .agg(
        Actuals          = ('amount_towards_plan', 'sum'),
        avg_deal_size    = ('amount_towards_plan', 'mean'),
        avg_sales_cycle  = ('sales_cycle_days', 'mean'),
        avg_dials        = ('dials', 'mean'),
        avg_touches      = ('touches', 'mean'),
        avg_push_counter = ('push_counter', 'mean'),
        number_of_opps   = ('opp_id', 'nunique'),
        avg_opportunity_age = ('opportunity_age', 'mean'),
    )
    .rename(columns={'week_start': 'ds', 'product_group': 'product'})
)

# ── Pipeline created (all_created_arr) ────────────────────────────────────────
pipe_weekly = (
    pipeline_raw.groupby(['pipe_week', 'product_group', 'sales_market'], as_index=False)
    ['pipeline_arr'].sum()
    .rename(columns={'pipe_week': 'ds', 'product_group': 'product', 'pipeline_arr': 'all_created_arr'})
)

actuals = actuals.merge(pipe_weekly, on=['ds', 'product', 'sales_market'], how='left')
actuals['all_created_arr'] = actuals['all_created_arr'].fillna(0)

# ── Partner pipeline placeholder (TODO: add partner_sourced filter) ────────────
actuals['total_partner_pipeline'] = 0.0

# ── Marketing pipeline (placeholder — wire from MC table if available) ────────
actuals['marketing_generated_pipeline'] = 0.0
actuals['marketing_influenced_pipeline'] = 0.0

# ── Headcount (join from headcount table if available) ────────────────────────
try:
    hc = spark.sql(f"""
        SELECT
            year(census_date) AS hc_year,
            month(census_date) AS hc_month,
            product_group,
            sales_market,
            COUNT(DISTINCT employee_id) AS headcount
        FROM {HEADCOUNT_TABLE}
        WHERE active = true
        GROUP BY 1, 2, 3, 4
    """).toPandas()
    actuals['year']  = pd.to_datetime(actuals['ds']).dt.year
    actuals['month'] = pd.to_datetime(actuals['ds']).dt.month
    actuals = actuals.merge(
        hc.rename(columns={'product_group': 'product', 'hc_year': 'year', 'hc_month': 'month'}),
        on=['year', 'month', 'product', 'sales_market'], how='left'
    )
    actuals['headcount'] = actuals['headcount'].fillna(0).astype(int)
    print("✓ Headcount joined")
except Exception as e:
    print(f"⚠ Headcount join skipped: {e}")
    actuals['headcount'] = 0

# ── Date features ──────────────────────────────────────────────────────────────
actuals['ds']          = pd.to_datetime(actuals['ds'])
actuals['year']        = actuals['ds'].dt.year
actuals['month']       = actuals['ds'].dt.month
actuals['week_number'] = actuals['ds'].dt.isocalendar().week.astype(int)
actuals['summer']      = actuals['ds'].dt.month.isin([6, 7, 8])
actuals['winter']      = actuals['ds'].dt.month.isin([12, 1, 2])
actuals['isweek1']     = actuals['ds'].dt.day <= 7

print(f"✓ Features built: {actuals.shape}")
print(actuals[['ds', 'product', 'sales_market', 'Actuals']].tail(5).to_string(index=False))

# COMMAND ----------
# ── 3. WEEK-OF-QUARTER FEATURE (avoids ISO-week drift) ────────────────────────

def add_week_of_quarter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values('ds').reset_index(drop=True)
    df['quarter'] = df['ds'].dt.quarter
    df['woq'] = (
        df.groupby(['year', 'quarter', 'product', 'sales_market'])
        .cumcount() + 1
    ).clip(upper=13)
    # One-hot encode woq_1 … woq_13
    for w in range(1, 14):
        df[f'woq_{w}'] = (df['woq'] == w).astype(int)
    return df

actuals = add_week_of_quarter(actuals)

# Compute empirical seasonal ratios (trailing 8 complete quarters for detrending)
cutoff_start = pd.Timestamp('2024-04-01')
cutoff_end   = pd.Timestamp('2026-04-01')
recent = actuals[
    (actuals['ds'] >= cutoff_start) &
    (actuals['ds'] < cutoff_end)
].copy()

if len(recent) > 0:
    # Detrend by dividing by linear trend
    recent_total = recent.groupby('ds', as_index=False)['Actuals'].sum()
    t = np.arange(len(recent_total))
    coeffs = np.polyfit(t, recent_total['Actuals'], 1)
    trend  = np.polyval(coeffs, t)
    recent_total['y_detrended'] = recent_total['Actuals'] / np.maximum(trend, 1)
    recent_total['woq'] = (
        recent_total.sort_values('ds')
        .assign(year=lambda x: x['ds'].dt.year, quarter=lambda x: x['ds'].dt.quarter)
        .groupby(['year', 'quarter']).cumcount() + 1
    ).clip(upper=13).values
    seasonal = (
        recent_total.groupby('woq', as_index=False)['y_detrended']
        .mean()
        .rename(columns={'y_detrended': 'seasonal_ratio'})
    )
    # Rescale so mean ratio = 1.0
    seasonal['seasonal_ratio'] /= seasonal['seasonal_ratio'].mean()
    print("✓ Seasonal ratios computed:")
    print(seasonal.to_string(index=False))
else:
    print("⚠ Not enough data for seasonal ratios — using uniform 1.0")
    seasonal = pd.DataFrame({'woq': range(1, 14), 'seasonal_ratio': 1.0})

# COMMAND ----------
# ── 4. PROPHET MODEL — PER (product, sales_market) ────────────────────────────

def run_prophet(train_df: pd.DataFrame, horizon: int, seasonal: pd.DataFrame) -> pd.DataFrame:
    """
    Train Prophet on train_df (columns: ds, y, woq_1..woq_13) and
    return a forecast DataFrame with Most_Likely, Worst_Case, Best_Case.
    """
    if len(train_df) < 26:
        return pd.DataFrame()  # not enough history

    # Fill missing weeks
    full_range = pd.date_range(train_df['ds'].min(), train_df['ds'].max(), freq='W-MON')
    train_df = (
        train_df.set_index('ds')
        .reindex(full_range, fill_value=0)
        .rename_axis('ds')
        .reset_index()
    )
    # Re-add woq features after reindex
    train_df['year']    = train_df['ds'].dt.year
    train_df['quarter'] = train_df['ds'].dt.quarter
    train_df['woq']     = (
        train_df.sort_values('ds')
        .groupby(['year', 'quarter']).cumcount() + 1
    ).clip(upper=13).values
    for w in range(1, 14):
        train_df[f'woq_{w}'] = (train_df['woq'] == w).astype(int)

    # Build regressor columns list
    woq_cols = [f'woq_{w}' for w in range(1, 14)]

    model = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode='multiplicative',
        changepoint_prior_scale=0.15,
        changepoint_range=0.9,
        seasonality_prior_scale=10.0,
        interval_width=0.80,
    )
    for col in woq_cols:
        model.add_regressor(col, mode='multiplicative')

    fit_df = train_df[['ds', 'y'] + woq_cols].copy()
    fit_df['y'] = fit_df['y'].clip(lower=0)
    model.fit(fit_df)

    # Build future dataframe
    last_ds      = train_df['ds'].max()
    future_dates = pd.date_range(last_ds + pd.Timedelta(weeks=1), periods=horizon, freq='W-MON')
    future = pd.DataFrame({'ds': future_dates})

    # Add woq features for future weeks
    # Determine continuing quarter context
    all_dates = pd.concat([train_df['ds'], pd.Series(future_dates)]).reset_index(drop=True)
    all_dates_df = pd.DataFrame({'ds': all_dates})
    all_dates_df['year']    = all_dates_df['ds'].dt.year
    all_dates_df['quarter'] = all_dates_df['ds'].dt.quarter
    all_dates_df['woq']     = (
        all_dates_df.sort_values('ds')
        .groupby(['year', 'quarter']).cumcount() + 1
    ).clip(upper=13).values
    future_woq = all_dates_df[all_dates_df['ds'].isin(future_dates)][['ds', 'woq']].copy()
    future = future.merge(future_woq, on='ds', how='left')
    future['woq'] = future['woq'].fillna(1).astype(int)
    for w in range(1, 14):
        future[f'woq_{w}'] = (future['woq'] == w).astype(int)

    pred = model.predict(future)

    # Prophet Hybrid: multiply by empirical seasonal ratio for cleaner spike capture
    future['woq_for_ratio'] = future['woq']
    ratio_map = seasonal.set_index('woq')['seasonal_ratio'].to_dict()
    future['seasonal_ratio'] = future['woq_for_ratio'].map(ratio_map).fillna(1.0)

    result = pd.DataFrame({
        'ds':          pred['ds'],
        'Most_Likely': (pred['yhat'] * future['seasonal_ratio'].values).clip(lower=0),
        'Worst_Case':  (pred['yhat_lower'] * future['seasonal_ratio'].values * 0.9).clip(lower=0),
        'Best_Case':   (pred['yhat_upper'] * future['seasonal_ratio'].values * 1.1).clip(lower=0),
    })
    return result


# Run per segment
segments = actuals.groupby(['product', 'sales_market', 'pe_account_flag'])
all_forecasts = []
total_segs = len(segments)
print(f"Running Prophet for {total_segs} segments…")

for i, ((product, market, pe_flag), grp) in enumerate(segments):
    grp = grp.sort_values('ds').copy()
    grp = grp.rename(columns={'Actuals': 'y'})

    # Keep only columns needed for prophet
    woq_cols = [f'woq_{w}' for w in range(1, 14)]
    try:
        fc = run_prophet(grp[['ds', 'y'] + woq_cols], FORECAST_HORIZON, seasonal)
    except Exception as e:
        print(f"  ⚠ Skipping {product}/{market}/{pe_flag}: {e}")
        continue

    if fc.empty:
        continue

    fc['product']       = product
    fc['sales_market']  = market
    fc['pe_account_flag'] = pe_flag

    # Re-attach feature columns (use last known values for future weeks)
    last_row = grp.iloc[-1]
    for col in ['avg_deal_size', 'avg_sales_cycle', 'all_created_arr',
                'total_partner_pipeline', 'marketing_generated_pipeline',
                'marketing_influenced_pipeline', 'avg_dials', 'avg_touches',
                'avg_push_counter', 'number_of_opps', 'headcount', 'avg_opportunity_age']:
        fc[col] = float(last_row.get(col, 0) or 0)

    # Date features
    fc['ds']          = pd.to_datetime(fc['ds'])
    fc['year']        = fc['ds'].dt.year
    fc['month']       = fc['ds'].dt.month
    fc['week_number'] = fc['ds'].dt.isocalendar().week.astype(int)
    fc['summer']      = fc['ds'].dt.month.isin([6, 7, 8])
    fc['winter']      = fc['ds'].dt.month.isin([12, 1, 2])
    fc['isweek1']     = fc['ds'].dt.day <= 7
    fc['Actuals']     = None   # future rows have no actuals

    all_forecasts.append(fc)
    if (i + 1) % 10 == 0 or (i + 1) == total_segs:
        print(f"  {i+1}/{total_segs} segments done")

print(f"✓ Prophet complete: {len(all_forecasts)} segments with forecasts")

# COMMAND ----------
# ── 5. COMBINE ACTUALS + FORECASTS ────────────────────────────────────────────

# Historical rows (actuals already in actuals df)
hist_cols = [
    'ds', 'product', 'sales_market', 'pe_account_flag',
    'year', 'month', 'week_number', 'summer', 'winter', 'isweek1',
    'Actuals', 'avg_deal_size', 'avg_sales_cycle', 'all_created_arr',
    'total_partner_pipeline', 'marketing_generated_pipeline', 'marketing_influenced_pipeline',
    'avg_dials', 'avg_touches', 'avg_push_counter', 'number_of_opps', 'headcount', 'avg_opportunity_age',
]
# Add placeholder forecast cols for historical rows (no model prediction for actuals)
hist_out = actuals[hist_cols].copy()
hist_out['Most_Likely'] = None
hist_out['Worst_Case']  = None
hist_out['Best_Case']   = None

# Forecast rows
fc_all = pd.concat(all_forecasts, ignore_index=True) if all_forecasts else pd.DataFrame()

# Final output columns (must match Delta schema exactly)
OUTPUT_COLS = [
    'ds', 'product', 'sales_market', 'pe_account_flag',
    'year', 'month', 'week_number', 'summer', 'winter', 'isweek1',
    'Actuals', 'avg_deal_size', 'avg_sales_cycle', 'all_created_arr',
    'total_partner_pipeline', 'marketing_generated_pipeline', 'marketing_influenced_pipeline',
    'avg_dials', 'avg_touches', 'avg_push_counter', 'number_of_opps', 'headcount', 'avg_opportunity_age',
    'Most_Likely', 'Worst_Case', 'Best_Case',
]

# Add missing cols with None to fc_all
for c in OUTPUT_COLS:
    if c not in fc_all.columns:
        fc_all[c] = None

output = pd.concat([hist_out, fc_all[OUTPUT_COLS]], ignore_index=True)
output['ds'] = pd.to_datetime(output['ds']).dt.date   # cast to date (not timestamp)

# Type coercions to match Delta schema
int_cols  = ['year', 'month', 'week_number', 'number_of_opps', 'headcount']
bool_cols = ['pe_account_flag', 'summer', 'winter', 'isweek1']
dbl_cols  = ['Actuals', 'avg_deal_size', 'avg_sales_cycle', 'all_created_arr',
             'total_partner_pipeline', 'marketing_generated_pipeline', 'marketing_influenced_pipeline',
             'avg_dials', 'avg_touches', 'avg_push_counter', 'avg_opportunity_age',
             'Most_Likely', 'Worst_Case', 'Best_Case']

for c in int_cols:
    output[c] = pd.to_numeric(output[c], errors='coerce').astype('Int64')
for c in bool_cols:
    output[c] = output[c].astype(bool)
for c in dbl_cols:
    output[c] = pd.to_numeric(output[c], errors='coerce').astype(float)

print(f"✓ Output shape: {output.shape}")
print(output[['ds', 'product', 'sales_market', 'Most_Likely', 'Best_Case', 'Worst_Case']].tail(10).to_string(index=False))

# COMMAND ----------
# ── 6. WRITE TO DELTA (MERGE — idempotent daily refresh) ──────────────────────

out_spark = spark.createDataFrame(output)

# Create table if it doesn't exist (schema already created by Sona — this is a no-op if exists)
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (
    ds                           DATE,
    product                      STRING,
    sales_market                 STRING,
    pe_account_flag              BOOLEAN,
    year                         INT,
    month                        INT,
    week_number                  INT,
    summer                       BOOLEAN,
    winter                       BOOLEAN,
    isweek1                      BOOLEAN,
    Actuals                      DOUBLE,
    avg_deal_size                DOUBLE,
    avg_sales_cycle              DOUBLE,
    all_created_arr              DOUBLE,
    total_partner_pipeline       DOUBLE,
    marketing_generated_pipeline DOUBLE,
    marketing_influenced_pipeline DOUBLE,
    avg_dials                    DOUBLE,
    avg_touches                  DOUBLE,
    avg_push_counter             DOUBLE,
    number_of_opps               BIGINT,
    headcount                    BIGINT,
    avg_opportunity_age          DOUBLE,
    Most_Likely                  DOUBLE,
    Worst_Case                   DOUBLE,
    Best_Case                    DOUBLE
)
USING DELTA
COMMENT 'Weekly Prophet forecast output combining actuals and predictions with sales features for ARR forecasting'
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
""")

# Register temp view for MERGE
out_spark.createOrReplaceTempView("forecast_updates")

# MERGE: upsert on (ds, product, sales_market, pe_account_flag)
spark.sql(f"""
MERGE INTO {OUTPUT_TABLE} AS t
USING forecast_updates AS s
ON t.ds           = s.ds
   AND t.product      = s.product
   AND t.sales_market = s.sales_market
   AND t.pe_account_flag = s.pe_account_flag
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")

count = spark.sql(f"SELECT COUNT(*) AS n FROM {OUTPUT_TABLE}").collect()[0]['n']
print(f"✓ MERGE complete — {OUTPUT_TABLE} now has {count:,} rows")

# COMMAND ----------
# ── 7. QUICK VALIDATION ────────────────────────────────────────────────────────
validation = spark.sql(f"""
SELECT
    product,
    sales_market,
    COUNT(*) AS total_weeks,
    MIN(ds) AS earliest_week,
    MAX(ds) AS latest_week,
    SUM(CASE WHEN Most_Likely IS NOT NULL THEN 1 END) AS forecast_weeks,
    ROUND(AVG(CASE WHEN Most_Likely IS NOT NULL THEN Most_Likely END), 0) AS avg_weekly_forecast
FROM {OUTPUT_TABLE}
GROUP BY product, sales_market
ORDER BY product, sales_market
""")
display(validation)

print("✓ Daily Prophet refresh complete")
print(f"  Next quarter forecast through: {nqend}")
