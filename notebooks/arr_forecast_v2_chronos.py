# Databricks notebook source
# MAGIC %md
# MAGIC # ⚠️ DEPRECATED — ARR Forecast v2 — Chronos (Companion Notebook)
# MAGIC
# MAGIC **STATUS: RETIRED as of July 2026**
# MAGIC
# MAGIC Chronos/MSTL_v2 has been removed from the model ensemble for both UCC and ITSG.
# MAGIC
# MAGIC **Replacement:**
# MAGIC - **ITSG**: DHR-ARIMA (already computed in `itsg_forecast_v5`) now fills the `arr_chronos` column via `atlas_combined_writer.py`
# MAGIC - **UCC**: `arr_chronos` column left NULL — 3-model ensemble (ETS + Prophet + LightGBM) is sufficient
# MAGIC
# MAGIC **Do NOT run this notebook.** It is kept for historical reference only.
# MAGIC Remove it from any Databricks Job schedules.
# MAGIC
# MAGIC **Run AFTER**: arr_forecast_v2_main.py (historical reference)
# MAGIC
# MAGIC This notebook:
# MAGIC 1. Loads the same blended monthly actuals used by the main notebook
# MAGIC 2. Runs **Chronos-T5-Small** (50 quantile samples) on each (product, geo) slice
# MAGIC 3. MERGEs `arr_chronos` into existing rows of `arr_forecast_v2`
# MAGIC 4. Recomputes `Most_Likely`, `Worst_Case`, `Best_Case` including Chronos in the
# MAGIC    inverse-sMAPE weighted ensemble (weights carried from main notebook leaderboard)
# MAGIC 5. Updates `mape_chronos` in the leaderboard table
# MAGIC
# MAGIC **Output table**: datagroup_mdl.mdl_sales_analytics.arr_forecast_v2  (MERGE, not overwrite)

# COMMAND ----------
# MAGIC %pip install chronos-forecasting transformers torch --quiet

# COMMAND ----------
import warnings, logging, datetime, math
warnings.filterwarnings("ignore")
logging.getLogger("transformers").setLevel(logging.ERROR)

import numpy as np
import pandas as pd
import torch
from chronos import ChronosPipeline
from pyspark.sql import functions as F
from pyspark.sql.types import *

# ── Config (must match main notebook) ─────────────────────────────────────────
CATALOG   = "datagroup_mdl"
SCHEMA    = "mdl_sales_analytics"
OUT_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"
LB_TABLE  = f"{CATALOG}.{SCHEMA}.arr_forecast_v2_leaderboard"

SFDC_TABLE = "datalake_transform.cds_sfdc_opp_products_latest"
MC_TABLE   = f"{CATALOG}.{SCHEMA}.mc_actuals"

TODAY           = datetime.date.today()
RUN_DATE        = TODAY
CUR_MONTH_START = TODAY.replace(day=1)
TRAIN_FROM      = "2022-01-01"

ROLLING_MONTHS = 3
ROY_MONTHS     = max(
    round((datetime.date(TODAY.year, 12, 31) - CUR_MONTH_START).days / 30.44), 1
)
HOLDOUT_MONTHS = 3
MIN_HISTORY    = 18

PRODUCT_MAP = {
    "GoTo Connect": "UCC",
    "GoTo Engage":  "UCC",
    "GoTo Resolve": "ITSG",
    "GoTo Central": "ITSG",
    "Rescue":       "ITSG",
}

GEO_NORM = {
    "NA":"NA","US":"NA","North America":"NA","NAMER":"NA","AMER":"NA",
    "EMEA":"EMEA","Europe":"EMEA","EUR":"EMEA",
    "APAC":"APAC","Asia Pacific":"APAC","APJ":"APAC","AUS":"APAC","ROW":"APAC",
    "LATAM":"LATAM","Latin America":"LATAM",
}

SLICES = [
    ("Total","Total"),
    ("UCC",  "Total"), ("ITSG","Total"),
    ("Total","NA"),    ("Total","EMEA"), ("Total","APAC"), ("Total","LATAM"),
    ("UCC",  "NA"),    ("UCC", "EMEA"),
    ("ITSG", "NA"),    ("ITSG","EMEA"),
]

print(f"Run: {RUN_DATE} | Rolling: {ROLLING_MONTHS}m | RoY: {ROY_MONTHS}m")

# COMMAND ----------
# MAGIC %md ## 1 — Load Chronos Pipeline

# COMMAND ----------
# Chronos-T5-Small: ~250 MB, ~700 ms/series on CPU (fastest Chronos model)
print("Loading Chronos-T5-Small ...")
pipeline = ChronosPipeline.from_pretrained(
    "amazon/chronos-t5-small",
    device_map="cpu",          # CPU on m5d.xlarge — avoids GPU licensing issues
    torch_dtype=torch.float32,
    cache_dir="/dbfs/tmp/hf_cache",
)
print("Chronos loaded ✅")

# COMMAND ----------
# MAGIC %md ## 2 — Rebuild Blended Monthly Actuals (same as main notebook)

# COMMAND ----------
prod_case = "CASE " + " ".join(
    f"WHEN product_genus='{k}' THEN '{v}'" for k,v in PRODUCT_MAP.items()
) + " ELSE 'Other' END"

geo_case = "CASE " + " ".join(
    f"WHEN sales_market='{k}' THEN '{v}'" for k,v in GEO_NORM.items()
) + " ELSE 'Other' END"

sfdc_raw = spark.sql(f"""
    SELECT
        date_trunc('month', close_date)  AS month_start,
        {prod_case}                      AS product_group,
        {geo_case}                       AS geo,
        SUM(COALESCE(arr, 0))            AS arr_sfdc
    FROM {SFDC_TABLE}
    WHERE is_won        = 'True'
      AND purchase_type = 'Growth'
      AND close_date   >= '{TRAIN_FROM}'
      AND close_date   <  current_date()
      AND COALESCE(arr, 0) > 0
    GROUP BY 1, 2, 3
""").filter(
    F.col("product_group").isin("UCC","ITSG") &
    F.col("geo").isin("NA","EMEA","APAC","LATAM")
)

sfdc_tot_p = sfdc_raw.groupBy("month_start","geo").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("product_group",F.lit("Total"))
sfdc_tot_g = sfdc_raw.groupBy("month_start","product_group").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("geo",F.lit("Total"))
sfdc_tot   = sfdc_raw.groupBy("month_start").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("product_group",F.lit("Total")).withColumn("geo",F.lit("Total"))
sfdc_all   = sfdc_raw.union(sfdc_tot_p).union(sfdc_tot_g).union(sfdc_tot)

geo_case_mc = "CASE " + " ".join(
    f"WHEN `Sales Market`='{k}' THEN '{v}'" for k,v in GEO_NORM.items()
) + " ELSE 'Other' END"

try:
    mc_raw = spark.sql(f"""
        SELECT
            date_trunc('month', `Month of Data Month`)                          AS month_start,
            CASE WHEN `Business Unit`='UCC'  THEN 'UCC'
                 WHEN `Business Unit`='ITSG' THEN 'ITSG'
                 ELSE 'Other' END                                               AS product_group,
            {geo_case_mc}                                                       AS geo,
            SUM(CAST(`Reported Bookings Total In USD Order Month Rate` AS DOUBLE)) AS arr_mc
        FROM {MC_TABLE}
        WHERE `Version`       = 'Actuals'
          AND `Purchase Type` = 'Growth'
          AND `Month of Data Month` <  '{CUR_MONTH_START}'
          AND `Month of Data Month` >= '{TRAIN_FROM}'
        GROUP BY 1, 2, 3
    """).filter(
        F.col("product_group").isin("UCC","ITSG") &
        F.col("geo").isin("NA","EMEA","APAC","LATAM")
    )
    mc_tot_p = mc_raw.groupBy("month_start","geo").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("product_group",F.lit("Total"))
    mc_tot_g = mc_raw.groupBy("month_start","product_group").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("geo",F.lit("Total"))
    mc_tot   = mc_raw.groupBy("month_start").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("product_group",F.lit("Total")).withColumn("geo",F.lit("Total"))
    mc_all   = mc_raw.union(mc_tot_p).union(mc_tot_g).union(mc_tot)
    HAS_MC   = True
except Exception as e:
    print(f"MC actuals unavailable ({e})")
    mc_all = spark.createDataFrame([], sfdc_all.schema)
    HAS_MC = False

blended_sdf = (
    sfdc_all
    .join(mc_all.withColumnRenamed("arr_mc","arr_mc_month"),
          ["month_start","product_group","geo"], "left")
    .withColumn("arr_actuals",
        F.when(
            (F.col("month_start") < F.lit(CUR_MONTH_START)) &
            F.col("arr_mc_month").isNotNull() & (F.col("arr_mc_month") > 0),
            F.col("arr_mc_month")
        ).otherwise(F.col("arr_sfdc"))
    )
    .select("month_start","product_group","geo","arr_actuals")
)

blended_pd = blended_sdf.toPandas()
blended_pd["month_start"] = pd.to_datetime(blended_pd["month_start"])
blended_pd["arr_actuals"] = pd.to_numeric(blended_pd["arr_actuals"], errors="coerce").fillna(0)
print(f"Blended rows: {len(blended_pd)}")

# COMMAND ----------
# MAGIC %md ## 3 — Weekly Distribution Pattern (same as main notebook)

# COMMAND ----------
sfdc_weekly_raw = spark.sql(f"""
    SELECT
        date_trunc('week',  close_date) AS week_start,
        date_trunc('month', close_date) AS month_start,
        SUM(COALESCE(arr,0))            AS arr_sfdc
    FROM {SFDC_TABLE}
    WHERE is_won        = 'True'
      AND purchase_type = 'Growth'
      AND close_date   >= '2023-01-01'
      AND close_date   <  current_date()
      AND COALESCE(arr, 0) > 0
    GROUP BY 1, 2
""").toPandas()
sfdc_weekly_raw["week_start"]  = pd.to_datetime(sfdc_weekly_raw["week_start"])
sfdc_weekly_raw["month_start"] = pd.to_datetime(sfdc_weekly_raw["month_start"])

monthly_totals  = sfdc_weekly_raw.groupby("month_start")["arr_sfdc"].sum().reset_index(name="arr_month")
sfdc_weekly_raw = sfdc_weekly_raw.merge(monthly_totals, on="month_start")
sfdc_weekly_raw["share"] = sfdc_weekly_raw["arr_sfdc"] / sfdc_weekly_raw["arr_month"].replace(0, np.nan)
sfdc_weekly_raw["week_of_month"] = (
    (sfdc_weekly_raw["week_start"] - sfdc_weekly_raw["month_start"]).dt.days // 7
).clip(0, 4)

avg_weekly_share = (
    sfdc_weekly_raw.groupby("week_of_month")["share"]
    .mean()
    .reindex([0,1,2,3,4], fill_value=0)
)
avg_weekly_share = avg_weekly_share / avg_weekly_share.sum()


def monthly_to_weekly(month_start: pd.Timestamp, monthly_value: float) -> list:
    ms      = pd.Timestamp(month_start)
    me      = ms + pd.offsets.MonthEnd(0)
    mondays = pd.date_range(
        start=ms - pd.Timedelta(days=ms.weekday()),
        end=me + pd.Timedelta(days=6),
        freq="W-MON"
    )
    mondays_in_month = [d for d in mondays if d.month == ms.month]
    if not mondays_in_month:
        return [{"ds": ms, "value": monthly_value}]
    n = len(mondays_in_month)
    shares = avg_weekly_share.iloc[:n].values
    if shares.sum() > 0:
        shares = shares / shares.sum()
    else:
        shares = np.ones(n) / n
    return [{"ds": d, "value": monthly_value * s}
            for d, s in zip(mondays_in_month, shares)]

# COMMAND ----------
# MAGIC %md ## 4 — Chronos Forecast Function

# COMMAND ----------
def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2.0
    mask  = denom > 0
    if mask.sum() == 0:
        return 999.0
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


def forecast_chronos_monthly(y: np.ndarray, h: int,
                              n_samples: int = 50) -> tuple:
    """
    Run Chronos-T5-Small on a monthly series.
    Returns (fc, lo, hi) in original scale.

    - Input is log1p-transformed to suppress spikes (matches main notebook behaviour)
    - P10/P90 quantiles from 50 posterior samples form the confidence band
    """
    y_log = np.log1p(np.maximum(y, 0))
    ctx   = torch.tensor(y_log.reshape(1, -1), dtype=torch.float32)

    quantiles, mean = pipeline.predict_quantiles(
        context=ctx,
        prediction_length=h,
        quantile_levels=[0.10, 0.50, 0.90],
        num_samples=n_samples,
    )
    # quantiles shape: (batch=1, h, 3) — [P10, P50, P90]
    q = quantiles[0].numpy()        # (h, 3)
    fc_log  = q[:, 1]               # median
    lo_log  = q[:, 0]               # P10
    hi_log  = q[:, 2]               # P90

    return (np.maximum(np.expm1(fc_log), 0),
            np.maximum(np.expm1(lo_log), 0),
            np.maximum(np.expm1(hi_log), 0))


def holdout_smape_chronos(y: np.ndarray, h: int = HOLDOUT_MONTHS) -> float:
    if len(y) < h + MIN_HISTORY:
        return 999.0
    y_tr, y_te = y[:-h], y[-h:]
    try:
        fc, _, _ = forecast_chronos_monthly(y_tr, h)
        return smape(y_te, fc[:h])
    except Exception as e:
        print(f"    Chronos holdout error: {e}")
        return 999.0

# COMMAND ----------
# MAGIC %md ## 5 — Load Existing sMAPE Weights from Leaderboard

# COMMAND ----------
try:
    lb_pd = spark.sql(f"""
        SELECT product, sales_market, mape_ets, mape_prophet, mape_lightgbm
        FROM {LB_TABLE}
        WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
    """).toPandas()
    print(f"Loaded leaderboard: {len(lb_pd)} rows")
    HAS_LB = True
except Exception as e:
    print(f"Leaderboard not available ({e})")
    lb_pd  = pd.DataFrame()
    HAS_LB = False


def get_prior_mapes(product_group: str, geo: str) -> dict:
    """Get 3-model sMAPE values from the main notebook leaderboard."""
    if not HAS_LB:
        return {"mape_ets": 20.0, "mape_prophet": 20.0, "mape_lightgbm": 20.0}
    row = lb_pd[
        (lb_pd["product"] == product_group) & (lb_pd["sales_market"] == geo)
    ]
    if row.empty:
        return {"mape_ets": 20.0, "mape_prophet": 20.0, "mape_lightgbm": 20.0}
    r = row.iloc[0]
    return {
        "mape_ets":       float(r.get("mape_ets",       20.0) or 20.0),
        "mape_prophet":   float(r.get("mape_prophet",   20.0) or 20.0),
        "mape_lightgbm":  float(r.get("mape_lightgbm",  20.0) or 20.0),
    }

# COMMAND ----------
# MAGIC %md ## 6 — Main Chronos Loop

# COMMAND ----------
merge_rows = []   # rows to MERGE into arr_forecast_v2

for product_group, geo in SLICES:
    print(f"\n{'='*55}")
    print(f"  product={product_group}  geo={geo}")
    print(f"{'='*55}")

    mask = ((blended_pd["product_group"] == product_group) &
            (blended_pd["geo"]           == geo))
    df_s = (blended_pd[mask]
            .sort_values("month_start")
            .reset_index(drop=True))

    if len(df_s) < MIN_HISTORY:
        print(f"  Insufficient history ({len(df_s)} months) — skip")
        continue

    y     = df_s["arr_actuals"].values.astype(float)
    dates = pd.DatetimeIndex(df_s["month_start"])

    # IQR fence (5×)
    q1, q3 = np.percentile(y, 25), np.percentile(y, 75)
    y_c     = np.clip(y, 0, q3 + 5*(q3-q1))

    sm_ch = holdout_smape_chronos(y_c)
    print(f"  Chronos holdout sMAPE: {sm_ch:.1f}%")

    prior_mapes = get_prior_mapes(product_group, geo)

    def iw(s): return 1.0 / max(s, 0.1)
    sm_ets = prior_mapes["mape_ets"]
    sm_ph  = prior_mapes["mape_prophet"]
    sm_lgb = prior_mapes["mape_lightgbm"]

    tw = iw(sm_ets) + iw(sm_ph) + iw(sm_lgb) + iw(sm_ch)
    we, wp, wl, wc = (iw(sm_ets)/tw, iw(sm_ph)/tw,
                      iw(sm_lgb)/tw, iw(sm_ch)/tw)
    print(f"  5-model weights → ETS:{we:.2f} Prophet:{wp:.2f} LGB:{wl:.2f} Chronos:{wc:.2f}")

    for fc_type, horizon in [("rolling", ROLLING_MONTHS), ("roy", ROY_MONTHS)]:
        print(f"  ── {fc_type} ({horizon}m)")
        try:
            fc_ch, lo_ch, hi_ch = forecast_chronos_monthly(y_c, horizon)
        except Exception as e:
            print(f"    Chronos forecast error: {e}")
            continue

        last_month   = dates[-1]
        future_months = pd.date_range(
            last_month + pd.offsets.MonthBegin(1), periods=horizon, freq="MS"
        )

        for i, m in enumerate(future_months):
            weekly_ch = monthly_to_weekly(m, float(fc_ch[i]))

            for j, wk in enumerate(weekly_ch):
                ds_date = wk["ds"].date() if hasattr(wk["ds"], "date") else wk["ds"]
                merge_rows.append({
                    "ds":            ds_date,
                    "product":       product_group,
                    "sales_market":  geo,
                    "arr_chronos":   wk["value"],
                    "mape_chronos":  sm_ch,
                    # 5-model recomputed ensemble
                    # We store weights in extra cols for MERGE to rebuild Most_Likely
                    "w_ets":   we,
                    "w_ph":    wp,
                    "w_lgb":   wl,
                    "w_ch":    wc,
                    "lo_ch":   monthly_to_weekly(m, float(lo_ch[i]))[j]["value"]
                               if j < len(monthly_to_weekly(m, float(lo_ch[i]))) else wk["value"] * 0.88,
                    "hi_ch":   monthly_to_weekly(m, float(hi_ch[i]))[j]["value"]
                               if j < len(monthly_to_weekly(m, float(hi_ch[i]))) else wk["value"] * 1.12,
                    "forecast_type": fc_type,
                    "run_date":      RUN_DATE,
                })

print(f"\nChronos forecast rows: {len(merge_rows)}")

# COMMAND ----------
# MAGIC %md ## 7 — MERGE arr_chronos + Recompute Ensemble

# COMMAND ----------
if not merge_rows:
    print("No Chronos rows to merge — exiting.")
    dbutils.notebook.exit("No rows")

merge_pd = pd.DataFrame(merge_rows)
merge_pd["ds"]       = pd.to_datetime(merge_pd["ds"]).dt.date
merge_pd["run_date"] = pd.to_datetime(merge_pd["run_date"]).dt.date

MERGE_SCHEMA = StructType([
    StructField("ds",            DateType(),   True),
    StructField("product",       StringType(), True),
    StructField("sales_market",  StringType(), True),
    StructField("arr_chronos",   DoubleType(), True),
    StructField("mape_chronos",  DoubleType(), True),
    StructField("w_ets",         DoubleType(), True),
    StructField("w_ph",          DoubleType(), True),
    StructField("w_lgb",         DoubleType(), True),
    StructField("w_ch",          DoubleType(), True),
    StructField("lo_ch",         DoubleType(), True),
    StructField("hi_ch",         DoubleType(), True),
    StructField("forecast_type", StringType(), True),
    StructField("run_date",      DateType(),   True),
])

merge_sdf = spark.createDataFrame(merge_pd, schema=MERGE_SCHEMA)
merge_sdf.createOrReplaceTempView("chronos_updates")

# MERGE into main table:
#   - Set arr_chronos
#   - Recompute Most_Likely = weighted combo of all 5 individual model columns
#     (arr_ets, arr_prophet, arr_lightgbm are already there from main notebook run)
#   - Recompute Worst_Case / Best_Case using Chronos CI
spark.sql(f"""
MERGE INTO {OUT_TABLE} AS tgt
USING chronos_updates AS src
  ON  tgt.ds            = src.ds
  AND tgt.product       = src.product
  AND tgt.sales_market  = src.sales_market
  AND tgt.forecast_type = src.forecast_type
  AND tgt.run_date      = src.run_date
WHEN MATCHED THEN UPDATE SET
  tgt.arr_chronos  = src.arr_chronos,
  tgt.mape_chronos = src.mape_chronos,
  -- 5-model ensemble (inverse-sMAPE weighted, all four known columns)
  tgt.Most_Likely  = (
    COALESCE(tgt.arr_ets,      0) * src.w_ets  +
    COALESCE(tgt.arr_prophet,  0) * src.w_ph   +
    COALESCE(tgt.arr_lightgbm, 0) * src.w_lgb  +
    src.arr_chronos                * src.w_ch
  ),
  tgt.Worst_Case   = LEAST(
    (
      COALESCE(tgt.arr_ets,      0) * src.w_ets  +
      COALESCE(tgt.arr_prophet,  0) * src.w_ph   +
      COALESCE(tgt.arr_lightgbm, 0) * src.w_lgb  +
      src.lo_ch                      * src.w_ch
    ),
    tgt.Most_Likely * 0.88
  ),
  tgt.Best_Case    = GREATEST(
    (
      COALESCE(tgt.arr_ets,      0) * src.w_ets  +
      COALESCE(tgt.arr_prophet,  0) * src.w_ph   +
      COALESCE(tgt.arr_lightgbm, 0) * src.w_lgb  +
      src.hi_ch                      * src.w_ch
    ),
    tgt.Most_Likely * 1.12
  )
""")

print(f"✅  MERGE complete → {OUT_TABLE}")

# COMMAND ----------
# MAGIC %md ## 8 — Update Leaderboard with Chronos sMAPE

# COMMAND ----------
lb_update_rows = []
for product_group, geo in SLICES:
    mask = ((blended_pd["product_group"] == product_group) &
            (blended_pd["geo"]           == geo))
    df_s = blended_pd[mask]
    if len(df_s) < MIN_HISTORY:
        continue
    y  = df_s["arr_actuals"].values.astype(float)
    q1, q3 = np.percentile(y, 25), np.percentile(y, 75)
    y_c = np.clip(y, 0, q3 + 5*(q3-q1))
    sm_ch = holdout_smape_chronos(y_c)
    lb_update_rows.append({
        "product":       product_group,
        "sales_market":  geo,
        "mape_chronos":  sm_ch,
        "run_date":      RUN_DATE,
    })

lb_update_pd = pd.DataFrame(lb_update_rows)
lb_update_pd["run_date"] = pd.to_datetime(lb_update_pd["run_date"]).dt.date

lb_upd_sdf = spark.createDataFrame(lb_update_pd)
lb_upd_sdf.createOrReplaceTempView("lb_chronos_updates")

spark.sql(f"""
MERGE INTO {LB_TABLE} AS tgt
USING lb_chronos_updates AS src
  ON  tgt.product       = src.product
  AND tgt.sales_market  = src.sales_market
  AND tgt.run_date      = src.run_date
WHEN MATCHED THEN UPDATE SET
  tgt.mape_chronos = src.mape_chronos,
  tgt.best_mape    = LEAST(
    COALESCE(tgt.mape_ets,       999),
    COALESCE(tgt.mape_prophet,   999),
    COALESCE(tgt.mape_lightgbm,  999),
    src.mape_chronos
  ),
  tgt.best_model   = CASE
    WHEN src.mape_chronos <= COALESCE(tgt.mape_ets,      999)
     AND src.mape_chronos <= COALESCE(tgt.mape_prophet,  999)
     AND src.mape_chronos <= COALESCE(tgt.mape_lightgbm, 999)
    THEN 'Chronos'
    ELSE tgt.best_model
  END
""")

print(f"✅  Leaderboard updated → {LB_TABLE}")

# COMMAND ----------
# MAGIC %md ## 9 — Final sMAPE Summary

# COMMAND ----------
summary = spark.sql(f"""
    SELECT product, sales_market,
           ROUND(mape_ets,      1) AS sMAPE_ETS,
           ROUND(mape_prophet,  1) AS sMAPE_Prophet,
           ROUND(mape_lightgbm, 1) AS sMAPE_LightGBM,
           ROUND(mape_chronos,  1) AS sMAPE_Chronos,
           ROUND(best_mape,     1) AS best_sMAPE,
           best_model
    FROM {LB_TABLE}
    WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
    ORDER BY best_mape
""")

summary.show(50, truncate=False)

# Check target
worst = summary.agg(F.max("best_mape")).collect()[0][0]
if worst is not None and worst < 15.0:
    print(f"🎯  Target achieved: all slices best sMAPE < 15% (worst = {worst:.1f}%)")
else:
    print(f"⚠️  Some slices above 15% sMAPE target (worst = {worst:.1f}%)")
    print("Investigate slices with low volume (LATAM / APAC sub-segments).")

print("""
DONE. The atlas-executive-insights app ForecastingPanel reads:
  datagroup_mdl.mdl_sales_analytics.arr_forecast_v2

All 5 model columns (arr_ets, arr_prophet, arr_lightgbm, arr_chronos, Most_Likely)
are now populated for every forecast row.

GRANT statements (run once in SQL if not yet done):
  GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
    TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
  GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard
    TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
""")
