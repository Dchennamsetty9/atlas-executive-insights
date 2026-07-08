# Databricks notebook source
# MAGIC %md
# MAGIC # Atlas Combined ARR Writer — UCC + ITSG → arr_forecast_v2
# MAGIC
# MAGIC **Purpose:** Read ITSG V4 ATP-based forecasts from `itsg_forecast_v5` (long format),
# MAGIC pivot to wide format, merge authoritative actuals, and write ITSG rows into
# MAGIC `arr_forecast_v2` alongside existing UCC rows so the Atlas UI can serve both
# MAGIC products from a single table with zero schema changes.
# MAGIC
# MAGIC **Run schedule:** Weekly, after both UCC and ITSG forecast notebooks complete.
# MAGIC (Wire as a Databricks Job with dependency on ITSG + UCC notebooks.)
# MAGIC
# MAGIC **READ-ONLY constraint:** `mdl_sales_analytics.forecast_prophet` is READ ONLY —
# MAGIC this notebook never writes to it.
# MAGIC
# MAGIC **Output tables (append-safe, idempotent on run_date):**
# MAGIC - `datagroup_mdl.mdl_sales_analytics.arr_forecast_v2`   — ITSG rows added
# MAGIC - `datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard` — ITSG MAPE rows

# COMMAND ----------
# MAGIC %md ## Cell 1 — Config

# COMMAND ----------

import datetime
import mlflow
import numpy as np
import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType, DoubleType, StringType, StructField, StructType,
)

# ── Catalog / table references ────────────────────────────────────────────────
CATALOG      = "datagroup_mdl"
SCHEMA       = "mdl_sales_analytics"
OUT_TABLE    = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"
LB_TABLE     = f"{CATALOG}.{SCHEMA}.arr_forecast_v2_leaderboard"

# Source: ITSG V4 ATP-based production output (long format)
ITSG_TABLE   = f"{CATALOG}.{SCHEMA}.itsg_forecast_v5"

# Authoritative actuals — Magna Carta
ACTUALS_TABLE = "datagroup.uc_forecast.actuals"
ACTUALS_PRODUCT = "RSG-IT"   # AUTHORITATIVE_ACTUALS_PRODUCT for ITSG

# Service principal for GRANT
SP_PRINCIPAL = "324a6ec7-e988-42c7-8a7f-55465f5bea37"

# ── Date helpers ──────────────────────────────────────────────────────────────
TODAY        = datetime.date.today()
RUN_DATE     = TODAY
YEAR_END     = datetime.date(TODAY.year, 12, 31)

# Rolling window = 13 weeks from run_date (current quarter)
ROLLING_END  = RUN_DATE + datetime.timedelta(weeks=13)

# ── Model name → wide column mapping ─────────────────────────────────────────
# Source notebook model names → arr_forecast_v2 column names
MODEL_COL_MAP = {
    "ETS":                "arr_ets",
    "Prophet_trend":      "arr_prophet",
    "Global_LGB_Q50_ITSG":"arr_lightgbm",
    "Global_LGB":         "arr_lightgbm",   # fallback if suffix differs
    "MSTL_v2":            "arr_mstl_v2",    # MSTL — now has a proper column
    "DHR-ARIMA":          "arr_dhr_arima",  # DHR-ARIMA — dedicated column (not aliased to arr_chronos)
    "Adaptive_Ensemble":  "__ensemble__",   # handled separately → Most_Likely/P10/P90
}

print(f"[combined_writer] run_date={RUN_DATE} | itsg_src={ITSG_TABLE}")
print(f"[combined_writer] rolling_window_end={ROLLING_END} | year_end={YEAR_END}")

# COMMAND ----------
# MAGIC %md ## Cell 2 — Load itsg_forecast_v5 (latest run_date_utc)

# COMMAND ----------

# Identify the latest run date in itsg_forecast_v5
latest_itsg_run = spark.sql(f"""
    SELECT MAX(run_date_utc) AS latest_run
    FROM {ITSG_TABLE}
""").collect()[0]["latest_run"]

if latest_itsg_run is None:
    dbutils.notebook.exit(f"[combined_writer] ERROR: {ITSG_TABLE} has no rows. Run ITSG V4 notebook first.")

print(f"[combined_writer] ITSG latest run_date_utc = {latest_itsg_run}")

itsg_raw = spark.sql(f"""
    SELECT
        ds,
        model,
        grain_level,
        CASE
            WHEN grain_level = 'total'  THEN 'Total'
            WHEN sales_market IN ('NA','NAMER','US','North America') THEN 'NA'
            WHEN sales_market IN ('EMEA','Europe','EUR')             THEN 'EMEA'
            WHEN sales_market IN ('APAC','Asia Pacific','APJ','AUS','ROW') THEN 'APAC'
            WHEN sales_market IN ('LATAM','Latin America')           THEN 'LATAM'
            ELSE sales_market
        END AS sales_market,
        forecast,
        p10,
        p50,
        p90,
        run_date_utc
    FROM {ITSG_TABLE}
    WHERE run_date_utc = '{latest_itsg_run}'
""")

row_count = itsg_raw.count()
print(f"[combined_writer] Loaded {row_count} rows from itsg_forecast_v5")
print(f"[combined_writer] Models: {[r['model'] for r in itsg_raw.select('model').distinct().collect()]}")
print(f"[combined_writer] Markets: {[r['sales_market'] for r in itsg_raw.select('sales_market').distinct().collect()]}")

itsg_pd = itsg_raw.toPandas()
itsg_pd["ds"] = pd.to_datetime(itsg_pd["ds"]).dt.date

# COMMAND ----------
# MAGIC %md ## Cell 3 — Pivot to wide format matching arr_forecast_v2 schema

# COMMAND ----------

def pivot_itsg_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot itsg_forecast_v5 long rows (one per model) into arr_forecast_v2 wide schema.

    Output columns:
        ds, sales_market,
        Most_Likely, Worst_Case, Best_Case,
        arr_ets, arr_prophet, arr_lightgbm, arr_mstl_v2, arr_dhr_arima
    """
    result_rows = []

    # Group by (ds, sales_market)
    for (ds, mkt), grp in df.groupby(["ds", "sales_market"]):
        row = {"ds": ds, "sales_market": mkt}

        # Ensemble → Most_Likely / Worst_Case / Best_Case
        ens = grp[grp["model"] == "Adaptive_Ensemble"]
        if not ens.empty:
            row["Most_Likely"] = float(ens["p50"].iloc[0])  if pd.notna(ens["p50"].iloc[0])  else float(ens["forecast"].iloc[0])
            row["Worst_Case"]  = float(ens["p10"].iloc[0])  if pd.notna(ens["p10"].iloc[0])  else None
            row["Best_Case"]   = float(ens["p90"].iloc[0])  if pd.notna(ens["p90"].iloc[0])  else None
        else:
            row["Most_Likely"] = None
            row["Worst_Case"]  = None
            row["Best_Case"]   = None

        # Individual models
        for model_name, col in MODEL_COL_MAP.items():
            if col.startswith("__"):
                continue  # handled above (ensemble) or skipped
            match = grp[grp["model"] == model_name]
            if not match.empty:
                row[col] = float(match["forecast"].iloc[0]) if pd.notna(match["forecast"].iloc[0]) else None

        # If ensemble missing but individual models exist, compute simple mean as Most_Likely
        individual_vals = [row.get(c) for c in ["arr_ets","arr_prophet","arr_lightgbm","arr_mstl_v2","arr_dhr_arima"]
                           if row.get(c) is not None]
        if row["Most_Likely"] is None and individual_vals:
            row["Most_Likely"] = float(np.mean(individual_vals))

        result_rows.append(row)

    wide_df = pd.DataFrame(result_rows)

    # Ensure all model columns exist (fill None if a model didn't produce output)
    for col in ["Most_Likely","Worst_Case","Best_Case","arr_ets","arr_prophet","arr_lightgbm","arr_mstl_v2","arr_dhr_arima"]:
        if col not in wide_df.columns:
            wide_df[col] = None

    print(f"[combined_writer] Pivoted to {len(wide_df)} (ds, market) rows")
    return wide_df


wide_pd = pivot_itsg_to_wide(itsg_pd)
wide_pd["product"] = "ITSG"
print(wide_pd[["ds","sales_market","Most_Likely","arr_ets","arr_prophet"]].tail(10).to_string(index=False))

# COMMAND ----------
# MAGIC %md ## Cell 4 — Load authoritative actuals from uc_forecast.actuals

# COMMAND ----------

# Actuals: weekly RSG-IT bookings from Magna Carta (most authoritative source)
try:
    actuals_pd = spark.sql(f"""
        SELECT
            CAST(week_start_date AS DATE) AS ds,
            SUM(arr)                      AS Actuals
        FROM {ACTUALS_TABLE}
        WHERE version        = 'ACTUALS'
          AND product_family = '{ACTUALS_PRODUCT}'
          AND week_start_date >= '2022-01-01'
          AND week_start_date <  current_date()
        GROUP BY 1
        ORDER BY 1
    """).toPandas()
    actuals_pd["ds"] = pd.to_datetime(actuals_pd["ds"]).dt.date
    print(f"[combined_writer] Loaded {len(actuals_pd)} weeks of RSG-IT actuals")
    print(f"[combined_writer] Actuals range: {actuals_pd['ds'].min()} → {actuals_pd['ds'].max()}")
except Exception as e:
    print(f"[combined_writer] WARN: Could not load actuals from {ACTUALS_TABLE}: {e}")
    print("[combined_writer] Continuing with Actuals=NULL for all ITSG rows.")
    actuals_pd = pd.DataFrame(columns=["ds","Actuals"])

# For Total market: these are already global totals
# For per-market: uc_forecast.actuals may have a sales_market column — try to use it
try:
    actuals_by_mkt = spark.sql(f"""
        SELECT
            CAST(week_start_date AS DATE) AS ds,
            CASE
                WHEN sales_market IN ('NA','NAMER','US') THEN 'NA'
                WHEN sales_market IN ('EMEA','Europe')   THEN 'EMEA'
                WHEN sales_market IN ('APAC','AUS','ROW')THEN 'APAC'
                WHEN sales_market IN ('LATAM')           THEN 'LATAM'
                ELSE sales_market
            END                           AS sales_market,
            SUM(arr)                      AS Actuals
        FROM {ACTUALS_TABLE}
        WHERE version        = 'ACTUALS'
          AND product_family = '{ACTUALS_PRODUCT}'
          AND week_start_date >= '2022-01-01'
          AND week_start_date <  current_date()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).toPandas()
    actuals_by_mkt["ds"] = pd.to_datetime(actuals_by_mkt["ds"]).dt.date
    print(f"[combined_writer] By-market actuals: {len(actuals_by_mkt)} rows")
    HAS_MKT_ACTUALS = True
except Exception as e:
    print(f"[combined_writer] WARN: No by-market actuals available ({e})")
    actuals_by_mkt = pd.DataFrame(columns=["ds","sales_market","Actuals"])
    HAS_MKT_ACTUALS = False

# COMMAND ----------
# MAGIC %md ## Cell 5 — Merge actuals and assign forecast_type

# COMMAND ----------

def assign_forecast_type(ds: datetime.date) -> str:
    """
    actuals  — historical weeks before run_date (where Actuals are known)
    rolling  — next 13 weeks from run_date (current quarter outlook)
    roy      — beyond rolling window through year-end (rest-of-year)
    """
    if ds < RUN_DATE:
        return "actuals"
    elif ds <= ROLLING_END:
        return "rolling"
    else:
        return "roy"


def merge_actuals_and_tag(wide: pd.DataFrame,
                           total_actuals: pd.DataFrame,
                           mkt_actuals: pd.DataFrame) -> pd.DataFrame:
    """Merge actuals, tag forecast_type, add run_date, product='ITSG'."""
    rows = []

    # Build lookup dicts for O(1) access
    total_lookup = dict(zip(total_actuals["ds"], total_actuals["Actuals"]))
    mkt_lookup   = {}
    for _, r in mkt_actuals.iterrows():
        mkt_lookup[(r["ds"], r["sales_market"])] = r["Actuals"]

    for _, row in wide.iterrows():
        ds  = row["ds"]
        mkt = row["sales_market"]

        # Choose actuals source
        if mkt == "Total":
            actual = total_lookup.get(ds)
        else:
            actual = mkt_lookup.get((ds, mkt)) if HAS_MKT_ACTUALS else None

        fc_type = assign_forecast_type(ds)

        # For historical rows (actuals): null out forecasts to keep table clean
        # (Actuals row still stores model forecasts for post-hoc accuracy checks)
        rows.append({
            "ds":            ds,
            "product":       "ITSG",
            "sales_market":  mkt,
            "Actuals":       float(actual) if actual is not None else None,
            "Most_Likely":   float(row.get("Most_Likely")) if pd.notna(row.get("Most_Likely")) else None,
            "Worst_Case":    float(row.get("Worst_Case"))  if pd.notna(row.get("Worst_Case"))  else None,
            "Best_Case":     float(row.get("Best_Case"))   if pd.notna(row.get("Best_Case"))   else None,
            "arr_ets":       float(row.get("arr_ets"))       if pd.notna(row.get("arr_ets"))       else None,
            "arr_prophet":   float(row.get("arr_prophet"))   if pd.notna(row.get("arr_prophet"))   else None,
            "arr_lightgbm":  float(row.get("arr_lightgbm"))  if pd.notna(row.get("arr_lightgbm"))  else None,
            "arr_mstl_v2":   float(row.get("arr_mstl_v2"))   if pd.notna(row.get("arr_mstl_v2"))   else None,
            "arr_dhr_arima": float(row.get("arr_dhr_arima")) if pd.notna(row.get("arr_dhr_arima")) else None,
            "mape_ets":      None,   # filled from MLflow in Cell 6
            "mape_prophet":  None,
            "mape_lightgbm": None,
            "mape_mstl_v2":  None,
            "mape_dhr_arima":None,
            "forecast_type": fc_type,
            "run_date":      RUN_DATE,
        })

    return pd.DataFrame(rows)


final_pd = merge_actuals_and_tag(wide_pd, actuals_pd, actuals_by_mkt)

print(f"[combined_writer] Final ITSG rows: {len(final_pd)}")
print(final_pd.groupby(["sales_market","forecast_type"]).size().reset_index(name="rows").to_string(index=False))

# COMMAND ----------
# MAGIC %md ## Cell 6 — Pull MAPE from MLflow (latest ITSG run)

# COMMAND ----------

# Try to read WAPE/MAPE from the most recent MLflow ITSG run.
# Models log metrics like: wape_ets, wape_prophet, wape_lgb_p50, wape_mstl_v2
# These are available if ITSG V4 notebook was run with MLflow tracking.

MLFLOW_EXPERIMENT = "itsg_growth_arr_forecast"

def load_itsg_mape_from_mlflow() -> dict:
    """Return {model_key: mape} or empty dict if MLflow is unavailable."""
    try:
        mlflow.set_tracking_uri("databricks")
        exps = mlflow.search_experiments(filter_string=f"name LIKE '%itsg%arr%'")
        if not exps:
            exps = mlflow.search_experiments(filter_string=f"name LIKE '%itsg%'")
        if not exps:
            print("[combined_writer] WARN: No ITSG MLflow experiment found")
            return {}

        exp_id = exps[0].experiment_id
        runs = mlflow.search_runs(
            experiment_ids=[exp_id],
            filter_string="status = 'FINISHED'",
            order_by=["start_time DESC"],
            max_results=1,
        )
        if runs.empty:
            print("[combined_writer] WARN: No finished MLflow runs found")
            return {}

        metrics = runs.iloc[0].to_dict()
        mape_map = {}

        # Map MLflow metric names → arr_forecast_v2 mape columns
        METRIC_MAP = {
            "wape_ets":          "mape_ets",
            "mape_ets":          "mape_ets",
            "wape_prophet":      "mape_prophet",
            "mape_prophet":      "mape_prophet",
            "wape_lgb_p50":      "mape_lightgbm",
            "wape_lightgbm":     "mape_lightgbm",
            "mape_lightgbm":     "mape_lightgbm",
            "wape_mstl_v2":      "mape_mstl_v2",
            "mape_mstl_v2":      "mape_mstl_v2",
            "wape_dhr_arima":    "mape_dhr_arima",
            "mape_dhr_arima":    "mape_dhr_arima",
        }
        for mlflow_key, col in METRIC_MAP.items():
            full_key = f"metrics.{mlflow_key}"
            if full_key in metrics and pd.notna(metrics[full_key]):
                mape_map[col] = float(metrics[full_key])

        print(f"[combined_writer] MLflow MAPE values: {mape_map}")
        return mape_map
    except Exception as e:
        print(f"[combined_writer] WARN: MLflow unavailable ({e}); MAPE will be NULL")
        return {}


mape_vals = load_itsg_mape_from_mlflow()

# Backfill MAPE into all rows for the given (product, sales_market) — consistent
# with how arr_forecast_v2_main.py attaches holdout sMAPE to every row
if mape_vals:
    for col, val in mape_vals.items():
        final_pd[col] = val
    print(f"[combined_writer] Applied MAPE to {len(final_pd)} rows")
else:
    print("[combined_writer] No MAPE values — mape_* columns will be NULL")

# COMMAND ----------
# MAGIC %md ## Cell 7 — Write ITSG rows to arr_forecast_v2 (idempotent)

# COMMAND ----------

OUTPUT_SCHEMA = StructType([
    StructField("ds",             DateType(),   True),
    StructField("product",        StringType(), True),
    StructField("sales_market",   StringType(), True),
    StructField("Actuals",        DoubleType(), True),
    StructField("Most_Likely",    DoubleType(), True),
    StructField("Worst_Case",     DoubleType(), True),
    StructField("Best_Case",      DoubleType(), True),
    StructField("arr_ets",        DoubleType(), True),
    StructField("arr_prophet",    DoubleType(), True),
    StructField("arr_lightgbm",   DoubleType(), True),
    StructField("arr_mstl_v2",    DoubleType(), True),
    StructField("arr_dhr_arima",  DoubleType(), True),
    StructField("mape_ets",       DoubleType(), True),
    StructField("mape_prophet",   DoubleType(), True),
    StructField("mape_lightgbm",  DoubleType(), True),
    StructField("mape_mstl_v2",   DoubleType(), True),
    StructField("mape_dhr_arima", DoubleType(), True),
    StructField("forecast_type",  StringType(), True),
    StructField("run_date",       DateType(),   True),
])

# Coerce types
numeric_cols = [
    "Actuals","Most_Likely","Worst_Case","Best_Case",
    "arr_ets","arr_prophet","arr_lightgbm","arr_mstl_v2","arr_dhr_arima",
    "mape_ets","mape_prophet","mape_lightgbm","mape_mstl_v2","mape_dhr_arima",
]
for c in numeric_cols:
    final_pd[c] = pd.to_numeric(final_pd[c], errors="coerce")

final_pd["ds"]       = pd.to_datetime(final_pd["ds"]).dt.date
final_pd["run_date"] = pd.to_datetime(final_pd["run_date"]).dt.date

out_sdf = spark.createDataFrame(final_pd, schema=OUTPUT_SCHEMA)

# ── Ensure table exists (arr_forecast_v2_main.py creates it; this is a no-op if so) ──
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {OUT_TABLE} (
        ds            DATE        COMMENT 'Week start (Monday)',
        product       STRING      COMMENT 'Total / UCC / ITSG',
        sales_market  STRING      COMMENT 'Total / NA / EMEA / APAC / LATAM',
        Actuals       DOUBLE      COMMENT 'Blended actuals (null for future weeks)',
        Most_Likely   DOUBLE      COMMENT 'Ensemble median (P50)',
        Worst_Case    DOUBLE      COMMENT 'Ensemble P10 lower bound',
        Best_Case     DOUBLE      COMMENT 'Ensemble P90 upper bound',
        arr_ets       DOUBLE      COMMENT 'ETS point forecast',
        arr_prophet   DOUBLE      COMMENT 'Prophet point forecast',
        arr_lightgbm  DOUBLE      COMMENT 'LightGBM quantile P50 forecast',
        arr_mstl_v2   DOUBLE      COMMENT 'MSTL_v2 point forecast',
        arr_dhr_arima DOUBLE      COMMENT 'DHR-ARIMA point forecast',
        mape_ets      DOUBLE      COMMENT 'Walk-forward WAPE — ETS',
        mape_prophet  DOUBLE      COMMENT 'Walk-forward WAPE — Prophet',
        mape_lightgbm DOUBLE      COMMENT 'Walk-forward WAPE — LightGBM',
        mape_mstl_v2  DOUBLE      COMMENT 'Walk-forward WAPE — MSTL_v2',
        mape_dhr_arima DOUBLE     COMMENT 'Walk-forward WAPE — DHR-ARIMA',
        forecast_type STRING      COMMENT 'actuals | rolling | roy',
        run_date      DATE        COMMENT 'Notebook run date (partition key)'
    )
    USING DELTA
    TBLPROPERTIES (
        'delta.autoOptimize.optimizeWrite' = 'true',
        'delta.autoOptimize.autoCompact'   = 'true'
    )
""")

# Add new columns if table was created before this schema version
for alter_col, alter_comment in [
    ("arr_mstl_v2",   "MSTL_v2 point forecast"),
    ("arr_dhr_arima", "DHR-ARIMA point forecast"),
    ("mape_mstl_v2",  "Walk-forward WAPE - MSTL_v2"),
    ("mape_dhr_arima","Walk-forward WAPE - DHR-ARIMA"),
]:
    try:
        spark.sql(f"ALTER TABLE {OUT_TABLE} ADD COLUMNS ({alter_col} DOUBLE COMMENT '{alter_comment}')")
        print(f"[combined_writer] Added column {alter_col} to {OUT_TABLE}")
    except Exception:
        pass  # Column already exists

# Idempotent: delete ITSG rows for today's run_date, then re-insert
spark.sql(f"""
    DELETE FROM {OUT_TABLE}
    WHERE product = 'ITSG'
      AND run_date = '{RUN_DATE}'
""")

out_sdf.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(OUT_TABLE)
spark.sql(f"OPTIMIZE {OUT_TABLE} ZORDER BY (run_date, product)")

written = spark.sql(f"""
    SELECT product, sales_market, forecast_type, COUNT(*) AS n
    FROM {OUT_TABLE}
    WHERE product = 'ITSG' AND run_date = '{RUN_DATE}'
    GROUP BY 1, 2, 3
    ORDER BY 2, 3
""")
print(f"✅  Written to {OUT_TABLE}")
written.show(30, truncate=False)

# COMMAND ----------
# MAGIC %md ## Cell 8 — Write leaderboard rows

# COMMAND ----------

# Build one leaderboard row per (product, sales_market) for ITSG
lb_rows = []
for mkt in final_pd["sales_market"].unique():
    mape_ets_val       = mape_vals.get("mape_ets")
    mape_prophet_val   = mape_vals.get("mape_prophet")
    mape_lightgbm_val  = mape_vals.get("mape_lightgbm")
    mape_mstl_v2_val   = mape_vals.get("mape_mstl_v2")
    mape_dhr_arima_val = mape_vals.get("mape_dhr_arima")

    candidates = {
        "ETS":       mape_ets_val,
        "Prophet":   mape_prophet_val,
        "LightGBM":  mape_lightgbm_val,
        "MSTL_v2":   mape_mstl_v2_val,
        "DHR_ARIMA": mape_dhr_arima_val,
    }
    valid = {k: v for k, v in candidates.items() if v is not None}
    best_model = min(valid, key=valid.get) if valid else None
    best_mape  = valid[best_model]        if valid else None

    lb_rows.append({
        "product":        "ITSG",
        "sales_market":   mkt,
        "mape_ets":       mape_ets_val,
        "mape_prophet":   mape_prophet_val,
        "mape_lightgbm":  mape_lightgbm_val,
        "mape_mstl_v2":   mape_mstl_v2_val,
        "mape_dhr_arima": mape_dhr_arima_val,
        "best_mape":      best_mape,
        "best_model":     best_model,
        "run_date":       RUN_DATE,
    })

lb_pd = pd.DataFrame(lb_rows)

LB_SCHEMA = StructType([
    StructField("product",        StringType(), True),
    StructField("sales_market",   StringType(), True),
    StructField("mape_ets",       DoubleType(), True),
    StructField("mape_prophet",   DoubleType(), True),
    StructField("mape_lightgbm",  DoubleType(), True),
    StructField("mape_mstl_v2",   DoubleType(), True),
    StructField("mape_dhr_arima", DoubleType(), True),
    StructField("best_mape",      DoubleType(), True),
    StructField("best_model",     StringType(), True),
    StructField("run_date",       DateType(),   True),
])

lb_pd["run_date"] = pd.to_datetime(lb_pd["run_date"]).dt.date
for c in ["mape_ets","mape_prophet","mape_lightgbm","mape_mstl_v2","mape_dhr_arima","best_mape"]:
    lb_pd[c] = pd.to_numeric(lb_pd[c], errors="coerce")

lb_sdf = spark.createDataFrame(lb_pd, schema=LB_SCHEMA)

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {LB_TABLE} (
        product       STRING,
        sales_market  STRING,
        mape_ets      DOUBLE,
        mape_prophet  DOUBLE,
        mape_lightgbm DOUBLE,
        mape_mstl_v2  DOUBLE,
        mape_dhr_arima DOUBLE,
        best_mape     DOUBLE,
        best_model    STRING,
        run_date      DATE
    ) USING DELTA
""")

for alter_col in ["mape_mstl_v2", "mape_dhr_arima"]:
    try:
        spark.sql(f"ALTER TABLE {LB_TABLE} ADD COLUMNS ({alter_col} DOUBLE)")
        print(f"[combined_writer] Added column {alter_col} to {LB_TABLE}")
    except Exception:
        pass  # Column already exists

spark.sql(f"DELETE FROM {LB_TABLE} WHERE product = 'ITSG' AND run_date = '{RUN_DATE}'")
lb_sdf.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(LB_TABLE)

print(f"✅  Leaderboard → {LB_TABLE}")
lb_pd[["product","sales_market","mape_ets","mape_prophet","mape_lightgbm","mape_mstl_v2","mape_dhr_arima","best_model","best_mape"]].to_string(index=False)

# COMMAND ----------
# MAGIC %md ## Cell 9 — GRANT service principal + sanity check

# COMMAND ----------

# Grant the Atlas app service principal read access (no-op if already granted)
for tbl in [OUT_TABLE, LB_TABLE]:
    try:
        spark.sql(f"GRANT SELECT ON TABLE {tbl} TO `{SP_PRINCIPAL}`")
        print(f"✅  GRANT SELECT on {tbl}")
    except Exception as e:
        print(f"[combined_writer] WARN: GRANT failed for {tbl}: {e}")

# Final sanity check: show one rolling week per market for ITSG
sanity = spark.sql(f"""
    SELECT ds, product, sales_market, forecast_type,
           ROUND(Most_Likely,0) AS most_likely, ROUND(Actuals,0) AS actuals,
           run_date
    FROM {OUT_TABLE}
    WHERE product = 'ITSG'
      AND run_date = '{RUN_DATE}'
      AND forecast_type = 'rolling'
    ORDER BY sales_market, ds
    LIMIT 20
""")
print("\n[combined_writer] Sample ITSG rolling rows:")
sanity.show(20, truncate=False)

print(f"""
╔══════════════════════════════════════════════════════════╗
║  atlas_combined_writer.py  COMPLETE                      ║
║  ITSG rows written: product='ITSG', run_date={RUN_DATE}  ║
║  Next: run atlas_ai_insights_writer.py to refresh cache  ║
╚══════════════════════════════════════════════════════════╝
""")
