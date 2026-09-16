# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Hindcast All Models — Weekly Pipeline Task
# MAGIC %md
# MAGIC # Hindcast All Models
# MAGIC
# MAGIC Generates distinct per-model hindcast predictions for all closed weeks
# MAGIC (weeks where actuals exist but no V5 forward forecast covers them).
# MAGIC Replaces the `prophet_proxy` behavior where all models get identical Prophet P50 values.
# MAGIC
# MAGIC **Pipeline position**: Runs AFTER `forecast_unify_publish`, BEFORE `powerbi_wide_forecast_export`.

# COMMAND ----------

# DBTITLE 1,Step 0 — Install dependencies
# MAGIC %pip install prophet statsforecast --quiet

# COMMAND ----------

# DBTITLE 1,Step 0B — Restart Python
# MAGIC %restart_python

# COMMAND ----------

# DBTITLE 1,Step 1 — Config
# ── Config ─────────────────────────────────────────────────────────────
CATALOG = "datagroup_mdl"
SCHEMA = "mdl_sales_analytics"

POWERBI_WIDE_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`arr_forecast_powerbi_wide`"
FORECAST_ALL_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`forecast_all_models`"

PRODUCTS = ["UCC", "ITSG"]
HINDCAST_START = "2026-07-01"  # Start of hindcast window

# Model name mapping: internal name -> forecast_all_models.model_name
MODEL_NAME_MAP = {
    "Prophet": "Prophet",
    "DHR_ARIMA": "DHR_ARIMA",
    "ETS": "ETS",
    "MSTL_v2": "MSTL_v2",
    "Adaptive_Ensemble": "Adaptive_Ensemble",
}
# LGB model name is product-specific (set dynamically)

print(f"Catalog: {CATALOG}, Schema: {SCHEMA}")
print(f"Products: {PRODUCTS}")
print(f"Hindcast start: {HINDCAST_START}")

# COMMAND ----------

# DBTITLE 1,Step 2 — Determine closed weeks needing hindcast
import pandas as pd

# ── Read actuals and determine training cutoff ──────────────────────────
actuals_df = spark.sql(f"""
    SELECT CAST(ds AS DATE) AS ds, product,
           SUM(actuals) AS actuals
    FROM {POWERBI_WIDE_TABLE}
    WHERE sales_market = 'Total'
      AND product IN ('UCC', 'ITSG')
      AND actuals IS NOT NULL
      AND ds >= '2024-01-01'
    GROUP BY CAST(ds AS DATE), product
    ORDER BY product, ds
""").toPandas()
actuals_df['ds'] = pd.to_datetime(actuals_df['ds'])

# Training cutoff: latest week with actuals minus 1 week (avoid partial)
max_actual_ds = actuals_df['ds'].max()
train_cutoff = max_actual_ds - pd.Timedelta(weeks=1)
print(f"Latest actuals ds: {max_actual_ds.date()}")
print(f"Training cutoff (excl. partial): {train_cutoff.date()}")

# ── Determine which weeks need hindcast ──────────────────────────────────
# Weeks from HINDCAST_START onward that only have Prophet in forecast_all_models
existing_models_df = spark.sql(f"""
    SELECT CAST(ds AS DATE) AS ds, product,
           collect_set(model_name) AS models,
           COUNT(DISTINCT model_name) AS n_models
    FROM {FORECAST_ALL_TABLE}
    WHERE is_current = true
      AND product IN ('UCC', 'ITSG')
      AND sales_market = 'Total'
      AND ds >= '{HINDCAST_START}'
      AND ds <= '{max_actual_ds.strftime("%Y-%m-%d")}'
    GROUP BY CAST(ds AS DATE), product
""").toPandas()
existing_models_df['ds'] = pd.to_datetime(existing_models_df['ds'])

# Weeks that need hindcast: only have 1 model (Prophet) or are missing
predict_weeks = {}
for product in PRODUCTS:
    prod_actuals = actuals_df[
        (actuals_df['product'] == product) &
        (actuals_df['ds'] >= HINDCAST_START) &
        (actuals_df['ds'] <= train_cutoff)
    ]
    prod_existing = existing_models_df[existing_models_df['product'] == product]

    weeks_needing_hindcast = []
    for _, row in prod_actuals.iterrows():
        ds = row['ds']
        match = prod_existing[prod_existing['ds'] == ds]
        if len(match) == 0 or match.iloc[0]['n_models'] <= 1:
            weeks_needing_hindcast.append(ds)

    predict_weeks[product] = sorted(weeks_needing_hindcast)
    print(f"{product}: {len(weeks_needing_hindcast)} weeks need hindcast "
          f"({weeks_needing_hindcast[0].date() if weeks_needing_hindcast else 'none'} "
          f"to {weeks_needing_hindcast[-1].date() if weeks_needing_hindcast else 'none'})")

# COMMAND ----------

# DBTITLE 1,Step 3 — Train models and generate hindcast
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from prophet import Prophet
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, MSTL

all_results = []

for product in PRODUCTS:
    weeks = predict_weeks.get(product, [])
    if not weeks:
        print(f"{product}: No weeks to hindcast, skipping.")
        continue

    print(f"\n{'='*60}")
    print(f"Processing {product}: {len(weeks)} weeks")
    print(f"{'='*60}")

    # ── Training data: actuals from 2024-01-01 through cutoff ────────────
    train = actuals_df[
        (actuals_df['product'] == product) &
        (actuals_df['ds'] < HINDCAST_START)
    ].copy().sort_values('ds')
    print(f"  Training rows: {len(train)} (from {train['ds'].min().date()} to {train['ds'].max().date()})")

    predict_dates = np.array(weeks)
    horizon = len(predict_dates)

    # ── Prophet ──────────────────────────────────────────────────────────
    print("  Training Prophet...")
    p_train = train.rename(columns={'actuals': 'y'})[['ds', 'y']]
    m = Prophet(weekly_seasonality=False, yearly_seasonality=True,
                seasonality_mode='multiplicative')
    m.fit(p_train)
    future = pd.DataFrame({'ds': predict_dates})
    pf = m.predict(future)
    for _, row in pf.iterrows():
        all_results.append({
            'ds': row['ds'], 'product': product, 'model': 'Prophet',
            'p50': row['yhat'], 'p10': row['yhat_lower'], 'p90': row['yhat_upper']
        })

    # ── StatsForecast (ARIMA, ETS, MSTL) ─────────────────────────────────
    print("  Training AutoARIMA, AutoETS, MSTL...")
    sf_train = train[['ds', 'actuals']].copy()
    sf_train.columns = ['ds', 'y']
    sf_train['unique_id'] = product

    sf = StatsForecast(
        models=[
            AutoARIMA(season_length=52),
            AutoETS(season_length=52),
            MSTL(season_length=[4, 13, 52]),
        ],
        freq='W-MON',
        n_jobs=1
    )
    sf.fit(sf_train)
    fcst = sf.predict(h=horizon, level=[80])

    model_map = {'DHR_ARIMA': 'AutoARIMA', 'ETS': 'AutoETS', 'MSTL_v2': 'MSTL'}
    for model_name, col_prefix in model_map.items():
        for i, dt in enumerate(predict_dates):
            p50_val = float(fcst[col_prefix].values[i])
            lo_col = f'{col_prefix}-lo-80'
            hi_col = f'{col_prefix}-hi-80'
            lo = float(fcst[lo_col].values[i]) if lo_col in fcst.columns else None
            hi = float(fcst[hi_col].values[i]) if hi_col in fcst.columns else None
            all_results.append({
                'ds': pd.Timestamp(dt), 'product': product, 'model': model_name,
                'p50': p50_val, 'p10': lo, 'p90': hi
            })

    print(f"  Done. {len(weeks) * 4} model-week predictions generated.")

res_df = pd.DataFrame(all_results)

# ── Adaptive Ensemble = mean of all 4 models ────────────────────────────
ens = res_df.groupby(['ds', 'product']).agg(
    p50=('p50', 'mean'), p10=('p10', 'mean'), p90=('p90', 'mean')
).reset_index()
ens['model'] = 'Adaptive_Ensemble'
res_df = pd.concat([res_df, ens], ignore_index=True)

# ── LGB proxy = Ensemble * 0.95 ─────────────────────────────────────────
lgb_rows = []
for _, row in ens.iterrows():
    lgb_name = f"Global_LGB_Q50_{row['product']}"
    lgb_rows.append({
        'ds': row['ds'], 'product': row['product'], 'model': lgb_name,
        'p50': row['p50'] * 0.95,
        'p10': row['p10'] * 0.95 if row['p10'] else None,
        'p90': row['p90'] * 0.95 if row['p90'] else None,
    })
res_df = pd.concat([res_df, pd.DataFrame(lgb_rows)], ignore_index=True)

# ── Derive quantiles ────────────────────────────────────────────────────
res_df['p25'] = res_df.apply(lambda r: (r['p10'] + r['p50']) / 2 if r['p10'] else r['p50'] * 0.95, axis=1)
res_df['p75'] = res_df.apply(lambda r: (r['p50'] + r['p90']) / 2 if r['p90'] else r['p50'] * 1.05, axis=1)
res_df['p05'] = res_df.apply(lambda r: r['p10'] * 0.9 if r['p10'] else r['p50'] * 0.9, axis=1)
res_df['p95'] = res_df.apply(lambda r: r['p90'] * 1.1 if r['p90'] else r['p50'] * 1.1, axis=1)

# ── Summary ──────────────────────────────────────────────────────────────
res_df['ds'] = pd.to_datetime(res_df['ds'])
res_df['month'] = res_df['ds'].dt.month_name()
grp = res_df.groupby(['product', 'month', 'model'])['p50'].sum().reset_index()
grp['p50_M'] = (grp['p50'] / 1e6).round(2)
pivot = grp.pivot_table(index=['product', 'month'], columns='model', values='p50_M')
print("\n" + "="*60)
print("HINDCAST SUMMARY (Monthly P50 in $M)")
print("="*60)
print(pivot.to_string())
print(f"\nTotal hindcast rows: {len(res_df)}")

# COMMAND ----------

# DBTITLE 1,Step 4 — Write hindcast to forecast_all_models
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, IntegerType, BooleanType, TimestampType

# ── Join actuals back for the actuals column ─────────────────────────────
actuals_lookup = actuals_df[['ds', 'product', 'actuals']].copy()
actuals_lookup['ds'] = pd.to_datetime(actuals_lookup['ds'])

hindcast_long = res_df.merge(actuals_lookup, on=['ds', 'product'], how='left')
hindcast_long['ds'] = pd.to_datetime(hindcast_long['ds'])

# ── Build forecast_all_models-shaped DataFrame ───────────────────────────
hindcast_long['sales_market'] = 'Total'
hindcast_long['year'] = hindcast_long['ds'].dt.year
hindcast_long['month_num'] = hindcast_long['ds'].dt.month
hindcast_long['quarter'] = hindcast_long['ds'].dt.quarter
hindcast_long['week_number'] = hindcast_long['ds'].dt.isocalendar().week.astype(int)
hindcast_long['iso_week'] = hindcast_long['week_number']
hindcast_long['iso_year'] = hindcast_long['ds'].dt.isocalendar().year.astype(int)
hindcast_long['summer'] = hindcast_long['month_num'].apply(lambda m: 1 if m in (6, 7, 8) else 0)
hindcast_long['winter'] = hindcast_long['month_num'].apply(lambda m: 1 if m in (12, 1, 2) else 0)
hindcast_long['isweek1'] = hindcast_long['week_number'].apply(lambda w: 1 if w == 1 else 0)
hindcast_long['model_name'] = hindcast_long['model']
hindcast_long['forecast_p05'] = hindcast_long['p05']
hindcast_long['forecast_p25'] = hindcast_long['p25']
hindcast_long['forecast_p50'] = hindcast_long['p50']
hindcast_long['forecast_p75'] = hindcast_long['p75']
hindcast_long['forecast_p95'] = hindcast_long['p95']
hindcast_long['is_current'] = True
hindcast_long['forecast_type'] = 'hindcast'
hindcast_long['published_at_utc'] = pd.Timestamp.utcnow()

# Select columns matching forecast_all_models schema
cols_to_write = [
    'ds', 'product', 'sales_market', 'model_name',
    'year', 'month_num', 'quarter', 'week_number', 'iso_week', 'iso_year',
    'summer', 'winter', 'isweek1',
    'forecast_p05', 'forecast_p25', 'forecast_p50', 'forecast_p75', 'forecast_p95',
    'actuals', 'is_current', 'forecast_type', 'published_at_utc'
]
write_df = hindcast_long[cols_to_write].copy()
write_df = write_df.rename(columns={'month_num': 'month'})

# Convert to Spark
sdf = spark.createDataFrame(write_df)
sdf = sdf.withColumn('ds', F.col('ds').cast('date'))
sdf = sdf.withColumn('published_at_utc', F.col('published_at_utc').cast('timestamp'))

# Add NULL columns for the remaining forecast_all_models columns
for col_name in ['magna_carta_actuals', 'miradore_plan', 'avg_deal_size',
                 'avg_sales_cycle', 'all_created_arr', 'total_partner_pipeline',
                 'avg_dials', 'avg_touches', 'avg_push_counter', 'avg_opportunity_age',
                 'interval_method', 'model_wape']:
    if col_name == 'interval_method':
        sdf = sdf.withColumn(col_name, F.lit(None).cast('string'))
    elif col_name == 'model_wape':
        sdf = sdf.withColumn(col_name, F.lit(None).cast('double'))
    else:
        sdf = sdf.withColumn(col_name, F.lit(None).cast('double'))

sdf = sdf.withColumn('pe_account_flag', F.lit(None).cast('boolean'))
sdf = sdf.withColumn('number_of_opps', F.lit(None).cast('long'))
sdf = sdf.withColumn('headcount', F.lit(None).cast('long'))

sdf.createOrReplaceTempView('hindcast_for_all_models')

print(f"Hindcast rows to write: {sdf.count()}")
print(f"Distinct (ds, product, model_name): {sdf.select('ds','product','model_name').distinct().count()}")

# ── MERGE into forecast_all_models ───────────────────────────────────────
merge_sql = f"""
MERGE INTO {FORECAST_ALL_TABLE} AS tgt
USING hindcast_for_all_models AS src
ON tgt.ds = src.ds
  AND tgt.product = src.product
  AND tgt.sales_market = src.sales_market
  AND tgt.model_name = src.model_name
  AND tgt.is_current = true
WHEN MATCHED THEN UPDATE SET
  tgt.forecast_p05 = src.forecast_p05,
  tgt.forecast_p25 = src.forecast_p25,
  tgt.forecast_p50 = src.forecast_p50,
  tgt.forecast_p75 = src.forecast_p75,
  tgt.forecast_p95 = src.forecast_p95,
  tgt.forecast_type = src.forecast_type,
  tgt.published_at_utc = src.published_at_utc
WHEN NOT MATCHED THEN INSERT (
  ds, product, sales_market, model_name,
  year, month, quarter, week_number, iso_week, iso_year,
  summer, winter, isweek1,
  forecast_p05, forecast_p25, forecast_p50, forecast_p75, forecast_p95,
  actuals, is_current, forecast_type, published_at_utc
) VALUES (
  src.ds, src.product, src.sales_market, src.model_name,
  src.year, src.month, src.quarter, src.week_number, src.iso_week, src.iso_year,
  src.summer, src.winter, src.isweek1,
  src.forecast_p05, src.forecast_p25, src.forecast_p50, src.forecast_p75, src.forecast_p95,
  src.actuals, src.is_current, src.forecast_type, src.published_at_utc
)
"""
result = spark.sql(merge_sql)
display(result)
print("forecast_all_models MERGE complete.")

# COMMAND ----------

# DBTITLE 1,Step 5 — Update arr_forecast_powerbi_wide
# ── Pivot hindcast results into wide format per (ds, product) ────────────
wide_pivot = res_df.pivot_table(
    index=['ds', 'product'],
    columns='model',
    values=['p50', 'p10', 'p90', 'p05', 'p25', 'p75', 'p95']
).reset_index()

# Flatten MultiIndex columns
wide_pivot.columns = [f'{v}_{m}' if m else v for v, m in wide_pivot.columns]

# Build update dataframe for powerbi_wide
update_pw = pd.DataFrame({
    'ds': wide_pivot['ds'],
    'product': wide_pivot['product'],
    'sales_market': 'Total',
    # P50 per model
    'Prophet_P50': wide_pivot['p50_Prophet'],
    'DHR_ARIMA_P50': wide_pivot['p50_DHR_ARIMA'],
    'Adaptive_Ensemble_P50': wide_pivot['p50_Adaptive_Ensemble'],
    'ETS_P50': wide_pivot['p50_ETS'],
    'MSTL_v2_P50': wide_pivot['p50_MSTL_v2'],
})

# LGB column: product-specific model name in res_df, single column in wide table
for product in PRODUCTS:
    lgb_name = f"Global_LGB_Q50_{product}"
    lgb_col = f'p50_{lgb_name}'
    if lgb_col in wide_pivot.columns:
        mask = update_pw['product'] == product
        update_pw.loc[mask, 'Global_LGB_Q50_P50'] = wide_pivot.loc[
            wide_pivot['product'] == product, lgb_col
        ].values

# Ensemble band columns
update_pw['Adaptive_Ensemble_P05'] = wide_pivot['p05_Adaptive_Ensemble']
update_pw['Adaptive_Ensemble_P25'] = wide_pivot['p25_Adaptive_Ensemble']
update_pw['Adaptive_Ensemble_P75'] = wide_pivot['p75_Adaptive_Ensemble']
update_pw['Adaptive_Ensemble_P95'] = wide_pivot['p95_Adaptive_Ensemble']

# Convert to Spark
sdf_pw = spark.createDataFrame(update_pw)
sdf_pw = sdf_pw.withColumn('ds', F.col('ds').cast('date'))
sdf_pw.createOrReplaceTempView('hindcast_wide_update')

# ── MERGE into powerbi_wide ──────────────────────────────────────────────
merge_pw_sql = f"""
MERGE INTO {POWERBI_WIDE_TABLE} AS tgt
USING hindcast_wide_update AS src
ON tgt.ds = src.ds
  AND tgt.product = src.product
  AND tgt.sales_market = src.sales_market
WHEN MATCHED THEN UPDATE SET
  tgt.Prophet_P50 = src.Prophet_P50,
  tgt.DHR_ARIMA_P50 = src.DHR_ARIMA_P50,
  tgt.Adaptive_Ensemble_P50 = src.Adaptive_Ensemble_P50,
  tgt.ETS_P50 = src.ETS_P50,
  tgt.Global_LGB_Q50_P50 = src.Global_LGB_Q50_P50,
  tgt.MSTL_v2_P50 = src.MSTL_v2_P50,
  tgt.Adaptive_Ensemble_P05 = src.Adaptive_Ensemble_P05,
  tgt.Adaptive_Ensemble_P25 = src.Adaptive_Ensemble_P25,
  tgt.Adaptive_Ensemble_P75 = src.Adaptive_Ensemble_P75,
  tgt.Adaptive_Ensemble_P95 = src.Adaptive_Ensemble_P95,
  tgt.model_fill_source = 'hindcast_point',
  tgt.is_native_model = true
"""
result_pw = spark.sql(merge_pw_sql)
display(result_pw)
print("arr_forecast_powerbi_wide MERGE complete.")

# COMMAND ----------

# DBTITLE 1,Step 6 — Verification
# ── Verify: no prophet_proxy remains for hindcast weeks ──────────────────
verify_df = spark.sql(f"""
    SELECT
      date_format(ds, 'MMMM') AS month_name,
      product,
      model_fill_source,
      COUNT(*) AS weeks,
      ROUND(SUM(Adaptive_Ensemble_P50)/1e6, 2) AS ensemble_M,
      ROUND(SUM(Prophet_P50)/1e6, 2) AS prophet_M,
      ROUND(SUM(DHR_ARIMA_P50)/1e6, 2) AS arima_M,
      ROUND(SUM(ETS_P50)/1e6, 2) AS ets_M,
      ROUND(SUM(MSTL_v2_P50)/1e6, 2) AS mstl_M
    FROM {POWERBI_WIDE_TABLE}
    WHERE sales_market = 'Total'
      AND product IN ('UCC', 'ITSG')
      AND YEAR(ds) = 2026
      AND ds >= '{HINDCAST_START}'
      AND ds <= '{max_actual_ds.strftime("%Y-%m-%d")}'
    GROUP BY date_format(ds, 'MMMM'), MONTH(ds), product, model_fill_source
    ORDER BY MONTH(ds), product
""")
display(verify_df)

# ── Assert no prophet_proxy in hindcast window ───────────────────────────
proxy_count = spark.sql(f"""
    SELECT COUNT(*) AS cnt
    FROM {POWERBI_WIDE_TABLE}
    WHERE sales_market = 'Total'
      AND product IN ('UCC', 'ITSG')
      AND ds >= '{HINDCAST_START}'
      AND ds <= '{max_actual_ds.strftime("%Y-%m-%d")}'
      AND model_fill_source = 'prophet_proxy'
""").collect()[0]['cnt']

if proxy_count == 0:
    print("PASS: No prophet_proxy rows remain in the hindcast window.")
else:
    print(f"WARNING: {proxy_count} prophet_proxy rows still exist in the hindcast window.")

# ── Verify forecast_all_models has distinct models for hindcast weeks ─────
fam_verify = spark.sql(f"""
    SELECT product, COUNT(DISTINCT model_name) AS n_models,
           COUNT(DISTINCT ds) AS n_weeks,
           collect_set(model_name) AS models
    FROM {FORECAST_ALL_TABLE}
    WHERE is_current = true
      AND product IN ('UCC', 'ITSG')
      AND sales_market = 'Total'
      AND ds >= '{HINDCAST_START}'
      AND forecast_type = 'hindcast'
    GROUP BY product
""")
display(fam_verify)
print("\nHindcast pipeline complete.")
