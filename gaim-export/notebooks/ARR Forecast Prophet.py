# Databricks notebook source
# MAGIC %md
# MAGIC # ARR Forecast — Prophet Model on Databricks
# MAGIC
# MAGIC Runs Meta's Prophet time series model **directly on the Databricks cluster** where Won ARR data lives.
# MAGIC Matches the methodology from the ARR Forecast Power BI dashboard (PPT reference):
# MAGIC - **Data source**: `federated.sales.metis_won_opps_fact` (Won ARR by Geo × Product)
# MAGIC - **Segmentation**: NA / EMEA / LATAM / APAC × ITSG / UCC + Total
# MAGIC - **Scenarios**: Worst Case (`yhat_lower`) · Most Likely (`yhat`) · Best Case (`yhat_upper`)
# MAGIC - **Confidence interval**: 80% (matches Power BI dashboard)
# MAGIC - **Output**: Results written to `datagroup_mdl.mdl_sales_analytics.arr_forecast_prophet`
# MAGIC - **App connection**: FastAPI backend reads from the Delta output table via SQL
# MAGIC
# MAGIC **Run schedule**: Daily via Databricks Workflow (or on-demand before dashboard refresh)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1 — Install and Import Required Libraries

# COMMAND ----------

# Install Prophet and plotting support on the cluster
# Run once per cluster; subsequent runs use the cached install
%pip install prophet==1.1.5 --quiet

# Standard imports
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib
matplotlib.use("Agg")          # non-interactive backend for cluster notebooks
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Prophet
from prophet import Prophet

# PySpark (already available on Databricks)
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, DateType, TimestampType, BooleanType
)

# MLflow for model registry
import mlflow
import mlflow.prophet

spark = SparkSession.builder.getOrCreate()
print(f"Spark version: {spark.version}")
print(f"Prophet imported OK")
print(f"MLflow version: {mlflow.__version__}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2 — Configuration
# MAGIC
# MAGIC Edit these parameters to control data source, output table, and forecast horizon.

# COMMAND ----------

# ── Data source ──────────────────────────────────────────────────────────────
SOURCE_TABLE   = "federated.sales.metis_won_opps_fact"
HISTORY_START  = "2022-01-01"   # use data from this date forward for training

# ── Output ───────────────────────────────────────────────────────────────────
OUTPUT_CATALOG = "datagroup_mdl"
OUTPUT_SCHEMA  = "mdl_sales_analytics"
OUTPUT_TABLE   = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_forecast_prophet"

# ── Forecast horizon ─────────────────────────────────────────────────────────
FORECAST_WEEKS = 52          # how many weeks ahead to forecast (1 year)
FREQ           = "W-MON"     # weekly, week starts Monday (ISO standard)

# ── Prophet hyperparameters (matching ARR Forecast Power BI config) ───────────
INTERVAL_WIDTH         = 0.80   # 80% CI → Best Case / Worst Case bands
CHANGEPOINT_PRIOR      = 0.05   # flexibility of trend; lower = smoother
SEASONALITY_MODE       = "multiplicative"   # multiplicative fits ARR growth better

# ── Segmentation dimensions ──────────────────────────────────────────────────
GEO_VALUES     = ["APAC", "EMEA", "LATAM", "NA", "UNKNOWN", "Total"]
PRODUCT_VALUES = ["ITSG", "UCC", "Total"]

RUN_DATE = datetime.now().strftime("%Y-%m-%d")
print(f"Config loaded. Run date: {RUN_DATE}")
print(f"Output table: {OUTPUT_TABLE}")
print(f"Forecast: {FORECAST_WEEKS} weeks ahead from {RUN_DATE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3 — Connect to Databricks and Load Won ARR Data
# MAGIC
# MAGIC Reads `federated.sales.metis_won_opps_fact` — the latest snapshot of all closed-won opportunities.
# MAGIC Uses `data_date = MAX(data_date)` to get the most current snapshot without duplicates.

# COMMAND ----------

# Load Won ARR from the federated Metis table
# Uses the latest data_date snapshot to avoid double-counting
sql = f"""
SELECT
    close_date,
    COALESCE(UPPER(TRIM(sales_market)), 'UNKNOWN')  AS geo,
    COALESCE(UPPER(TRIM(product_group)), 'UNKNOWN') AS product_group,
    SUM(amount_towards_plan)                         AS won_arr
FROM {SOURCE_TABLE}
WHERE
    data_date = (SELECT MAX(data_date) FROM {SOURCE_TABLE})
    AND close_date >= '{HISTORY_START}'
    AND close_date <= CURRENT_DATE()
    AND amount_towards_plan IS NOT NULL
    AND amount_towards_plan > 0
GROUP BY
    close_date,
    COALESCE(UPPER(TRIM(sales_market)), 'UNKNOWN'),
    COALESCE(UPPER(TRIM(product_group)), 'UNKNOWN')
ORDER BY close_date
"""

sdf_raw = spark.sql(sql)
print(f"Rows loaded: {sdf_raw.count():,}")
print(f"Date range:")
sdf_raw.selectExpr("MIN(close_date) AS min_date", "MAX(close_date) AS max_date").show()
print("Geo values:")
sdf_raw.groupBy("geo").agg(F.sum("won_arr").alias("total_arr")).orderBy("geo").show()
print("Product values:")
sdf_raw.groupBy("product_group").agg(F.sum("won_arr").alias("total_arr")).orderBy("product_group").show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4 — Prepare Data for Prophet
# MAGIC
# MAGIC Aggregates daily close_date data to **weekly** (ISO Monday-aligned) buckets.
# MAGIC Adds the seasonality feature columns used by the Power BI model: `summer`, `winter`, `isweek1`.

# COMMAND ----------

def prepare_prophet_df(pdf: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a filtered pandas DataFrame to Prophet format.
    - Renames close_date → ds, won_arr → y
    - Aggregates to ISO-week (Monday-start)
    - Adds seasonality regressors matching ARR Forecast Power BI model:
        summer   = June / July / August
        winter   = December / January / February
        isweek1  = first 7 days of the month
    - Fills missing weeks with 0 (no deals closed that week)
    """
    df = pdf.copy()
    df["ds"] = pd.to_datetime(df["close_date"])
    df["y"]  = df["won_arr"].astype(float)

    # Aggregate to weekly buckets (ISO Monday start)
    df["week_start"] = df["ds"].dt.to_period(FREQ).apply(lambda p: p.start_time)
    weekly = (
        df.groupby("week_start", as_index=False)["y"]
        .sum()
        .rename(columns={"week_start": "ds"})
    )

    # Fill the full calendar range so Prophet sees a complete weekly series
    full_range = pd.date_range(
        start=weekly["ds"].min(),
        end=weekly["ds"].max(),
        freq=FREQ,
    )
    weekly = weekly.set_index("ds").reindex(full_range, fill_value=0).reset_index()
    weekly.columns = ["ds", "y"]
    weekly["ds"] = pd.to_datetime(weekly["ds"])

    # Seasonality regressors (matching PPT feature engineering)
    weekly["summer"]  = weekly["ds"].dt.month.isin([6, 7, 8]).astype(int)
    weekly["winter"]  = weekly["ds"].dt.month.isin([12, 1, 2]).astype(int)
    weekly["isweek1"] = (weekly["ds"].dt.day <= 7).astype(int)

    return weekly.sort_values("ds").reset_index(drop=True)


# Convert to pandas and build a "Total" aggregate in addition to segments
df_raw = sdf_raw.toPandas()
df_raw["close_date"] = pd.to_datetime(df_raw["close_date"])

# Build total series
df_total = df_raw.groupby("close_date", as_index=False)["won_arr"].sum()
df_total["geo"] = "Total"
df_total["product_group"] = "Total"

df_all = pd.concat([df_raw, df_total], ignore_index=True)

# Preview the Total series prepared for Prophet
sample = prepare_prophet_df(df_total)
print(f"Total series: {len(sample)} weekly points  ({sample['ds'].min().date()} → {sample['ds'].max().date()})")
print(f"Average weekly Won ARR (Total): ${sample['y'].mean():,.0f}")
print(f"\nFirst 5 rows:")
print(sample.head())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5 — Build and Train Prophet Model
# MAGIC
# MAGIC Instantiates one Prophet model per segment (Geo × Product combination).
# MAGIC Configuration exactly matches the ARR Forecast Power BI dashboard methodology.

# COMMAND ----------

def build_and_train_prophet(weekly_df: pd.DataFrame, segment_label: str) -> tuple:
    """
    Build and fit a Prophet model for one Geo×Product segment.

    Returns: (fitted_model, forecast_df, mape_pct)
    """
    if len(weekly_df) < 26:
        print(f"  [SKIP] {segment_label}: only {len(weekly_df)} weeks — need at least 26")
        return None, None, None

    # ── Prophet config matching ARR Forecast Power BI ─────────────────────────
    model = Prophet(
        interval_width         = INTERVAL_WIDTH,       # 0.80 → Best/Worst case bands
        changepoint_prior_scale= CHANGEPOINT_PRIOR,    # 0.05 → smooth trend
        seasonality_mode       = SEASONALITY_MODE,     # multiplicative
        yearly_seasonality     = True,
        weekly_seasonality     = True,
        daily_seasonality      = False,                # weekly data — no daily pattern
    )

    # Custom seasonality regressors (PPT Feature Engineering step)
    model.add_regressor("summer")
    model.add_regressor("winter")
    model.add_regressor("isweek1")

    # Fit on the full history
    model.fit(weekly_df[["ds", "y", "summer", "winter", "isweek1"]])

    # ── Accuracy on held-out last 8 weeks ─────────────────────────────────────
    train_df  = weekly_df.iloc[:-8]
    test_df   = weekly_df.iloc[-8:]
    eval_model = Prophet(
        interval_width=INTERVAL_WIDTH,
        changepoint_prior_scale=CHANGEPOINT_PRIOR,
        seasonality_mode=SEASONALITY_MODE,
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
    )
    eval_model.add_regressor("summer")
    eval_model.add_regressor("winter")
    eval_model.add_regressor("isweek1")
    eval_model.fit(train_df[["ds", "y", "summer", "winter", "isweek1"]])

    test_pred = eval_model.predict(test_df[["ds", "summer", "winter", "isweek1"]])
    actuals   = test_df["y"].values
    preds     = test_pred["yhat"].values
    mape = float(np.mean(np.abs((actuals - preds) / np.where(actuals == 0, 1, actuals)))) * 100

    # ── Generate forecast ─────────────────────────────────────────────────────
    future = model.make_future_dataframe(periods=FORECAST_WEEKS, freq=FREQ)
    future["summer"]  = future["ds"].dt.month.isin([6, 7, 8]).astype(int)
    future["winter"]  = future["ds"].dt.month.isin([12, 1, 2]).astype(int)
    future["isweek1"] = (future["ds"].dt.day <= 7).astype(int)

    forecast_df = model.predict(future)

    print(f"  [OK] {segment_label:<22}  weeks={len(weekly_df)}  MAPE={mape:.1f}%")
    return model, forecast_df, mape


# ── Train all segments ─────────────────────────────────────────────────────────
all_results = {}   # key: (geo, product_group)  → (model, forecast_df, mape)

segments = df_all.groupby(["geo", "product_group"])

print(f"Training {segments.ngroups} segments...\n")

for (geo, product), group_df in segments:
    label = f"{geo}/{product}"
    weekly = prepare_prophet_df(group_df)
    model, fc_df, mape = build_and_train_prophet(weekly, label)
    if model is not None:
        all_results[(geo, product)] = {"model": model, "forecast": fc_df, "mape": mape, "history": weekly}

print(f"\n✓ Trained {len(all_results)} segments successfully")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6 — Generate & Review Forecast Results
# MAGIC
# MAGIC Assembles all segment forecasts into a single flat DataFrame with columns matching the Power BI dashboard output format.

# COMMAND ----------

rows = []
history_cutoff = pd.Timestamp(RUN_DATE)

for (geo, product), result in all_results.items():
    fc_df   = result["forecast"]
    history = result["history"]
    mape    = result["mape"]

    # Build a lookup for actual values (historical weeks)
    actual_map = dict(zip(history["ds"], history["y"]))

    for _, row in fc_df.iterrows():
        week_date     = row["ds"]
        is_historical = bool(week_date <= history_cutoff)
        actual_val    = actual_map.get(week_date, None)

        rows.append({
            "run_date"      : RUN_DATE,
            "geo"           : geo,
            "product_group" : product,
            "forecast_date" : week_date.date(),
            "most_likely"   : max(0.0, round(float(row["yhat"]),       2)),
            "worst_case"    : max(0.0, round(float(row["yhat_lower"]), 2)),
            "best_case"     : max(0.0, round(float(row["yhat_upper"]), 2)),
            "actual"        : round(float(actual_val), 2) if actual_val is not None else None,
            "is_historical" : is_historical,
            "model_mape"    : round(mape, 2),
        })

df_output = pd.DataFrame(rows)
print(f"Total output rows: {len(df_output):,}")
print(f"  Historical rows : {df_output['is_historical'].sum():,}")
print(f"  Forecast rows   : {(~df_output['is_historical']).sum():,}")

# COMMAND ----------

# Fix the preview — simpler display without the pipe operator
sample_view = (
    df_output
    .query("geo == 'Total' and product_group == 'Total' and is_historical == False")
    [["forecast_date", "worst_case", "most_likely", "best_case"]]
    .head(8)
)
print("Total segment — next 8 forecast weeks:")
print(sample_view.to_string(index=False))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 7 — Visualize Forecast Results
# MAGIC
# MAGIC Plots the Total segment: actual history + 3 scenario bands (Worst / Most Likely / Best Case).
# MAGIC Matches the "Actual Won ARR vs Predicted" chart from the Power BI dashboard.

# COMMAND ----------

def plot_forecast(geo: str, product: str, lookback_weeks: int = 52):
    """
    Plot actuals + 3 scenario bands for a given Geo × Product segment.
    Matches the 'Actual Won ARR vs Predicted' Power BI chart style.
    """
    df_seg = df_output.query(f"geo == '{geo}' and product_group == '{product}'").copy()
    df_seg["forecast_date"] = pd.to_datetime(df_seg["forecast_date"])
    df_seg = df_seg.sort_values("forecast_date")

    hist = df_seg[df_seg["is_historical"]]
    fcast = df_seg[~df_seg["is_historical"]]

    # Show only recent history for readability
    cutoff = df_seg["forecast_date"].max() - pd.Timedelta(weeks=lookback_weeks)
    hist = hist[hist["forecast_date"] >= cutoff]

    fig, axes = plt.subplots(2, 1, figsize=(14, 9))
    fig.suptitle(f"Won ARR Forecast — {geo} / {product}", fontsize=14, fontweight="bold")

    # ── Top: Weekly view ──────────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(hist["forecast_date"], hist["actual"], color="#FFA500", linewidth=1.8,
            label="Actuals", zorder=5)
    ax.plot(fcast["forecast_date"], fcast["most_likely"], color="#FFA500",
            linewidth=1.5, linestyle="--", label="Most Likely")
    ax.fill_between(fcast["forecast_date"],
                    fcast["worst_case"], fcast["best_case"],
                    alpha=0.25, color="#888888", label="Worst–Best band")
    ax.plot(fcast["forecast_date"], fcast["worst_case"],
            color="white", linewidth=0.8, linestyle=":")
    ax.plot(fcast["forecast_date"], fcast["best_case"],
            color="white", linewidth=0.8, linestyle=":")
    ax.axvline(pd.Timestamp(RUN_DATE), color="red", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.set_title("Weekly Forecast vs Actuals", fontsize=10)
    ax.set_ylabel("Won ARR ($)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M"))
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_facecolor("#1a1a1a")
    fig.patch.set_facecolor("#1a1a1a")
    ax.tick_params(colors="white")
    ax.yaxis.label.set_color("white")
    ax.title.set_color("white")

    # ── Bottom: Running totals ────────────────────────────────────────────────
    ax2 = axes[1]
    df_all_seg = pd.concat([
        hist[["forecast_date", "actual", "most_likely", "worst_case", "best_case"]],
        fcast[["forecast_date", "actual", "most_likely", "worst_case", "best_case"]],
    ]).sort_values("forecast_date")

    df_all_seg["cum_actual"]      = df_all_seg["actual"].fillna(0).cumsum()
    df_all_seg["cum_most_likely"] = df_all_seg["most_likely"].cumsum()
    df_all_seg["cum_worst"]       = df_all_seg["worst_case"].cumsum()
    df_all_seg["cum_best"]        = df_all_seg["best_case"].cumsum()

    ax2.plot(df_all_seg["forecast_date"], df_all_seg["cum_actual"],
             color="#FFA500", linewidth=1.8, label="Running Actuals")
    ax2.plot(df_all_seg["forecast_date"], df_all_seg["cum_most_likely"],
             color="#FFA500", linewidth=1.2, linestyle="--", label="Running Most Likely")
    ax2.fill_between(df_all_seg["forecast_date"],
                     df_all_seg["cum_worst"], df_all_seg["cum_best"],
                     alpha=0.2, color="#888888")
    ax2.axvline(pd.Timestamp(RUN_DATE), color="red", linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.set_title("Running Totals", fontsize=10)
    ax2.set_ylabel("Cumulative Won ARR ($)")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x/1e6:.0f}M"))
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_facecolor("#1a1a1a")
    ax2.tick_params(colors="white")
    ax2.yaxis.label.set_color("white")
    ax2.title.set_color("white")

    plt.tight_layout()
    plt.show()
    mape_val = df_output.query(
        f"geo == '{geo}' and product_group == '{product}'"
    )["model_mape"].iloc[0]
    print(f"Model MAPE (8-week holdout): {mape_val:.1f}%")


# Plot Total and key segments
plot_forecast("Total", "Total")
plot_forecast("NA",   "Total")
plot_forecast("EMEA", "Total")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 8 — Save Results to App Forecast Delta Tables
# MAGIC
# MAGIC Writes three app-facing snapshot tables in `datagroup_mdl.mdl_sales_analytics`:
# MAGIC
# MAGIC - `arr_forecast_output` — historical + forecast points by segment
# MAGIC - `arr_forecast_insights` — run-level narrative and guidance
# MAGIC - `arr_model_leaderboard` — model quality metrics for readiness checks
# MAGIC
# MAGIC Write pattern is append-only snapshots with **run_date-level idempotency**:
# MAGIC - delete only the current `run_date` slice
# MAGIC - append fresh rows for this run
# MAGIC - preserve all historical runs

# COMMAND ----------

from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, BooleanType
)
from pyspark.sql import functions as F
import numpy as np

# ── App tables ───────────────────────────────────────────────────────────────
FORECAST_OUTPUT_TABLE      = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_forecast_output"
FORECAST_INSIGHTS_TABLE    = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_forecast_insights"
FORECAST_LEADERBOARD_TABLE = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_model_leaderboard"

# ── Prepare forecast output snapshot (Prophet / won_pipeline) ───────────────
df_to_write = df_output.copy()
df_to_write["forecast_date"] = df_to_write["forecast_date"].astype(str)
df_to_write["actual"] = df_to_write["actual"].where(df_to_write["actual"].notna(), other=None)
df_to_write["metric"] = "won_pipeline"
df_to_write["model_name"] = "prophet"

output_schema = StructType([
    StructField("run_date",       StringType(),  False),
    StructField("metric",         StringType(),  False),
    StructField("model_name",     StringType(),  False),
    StructField("geo",            StringType(),  False),
    StructField("product_group",  StringType(),  False),
    StructField("forecast_date",  StringType(),  False),
    StructField("most_likely",    DoubleType(),  True),
    StructField("worst_case",     DoubleType(),  True),
    StructField("best_case",      DoubleType(),  True),
    StructField("actual",         DoubleType(),  True),
    StructField("is_historical",  BooleanType(), False),
    StructField("model_mape",     DoubleType(),  True),
])

sdf_output = spark.createDataFrame(df_to_write, schema=output_schema)
sdf_output = sdf_output.withColumn("created_at", F.current_timestamp())

# ── Build run-level insights snapshot ────────────────────────────────────────
hist_pdf = df_to_write[df_to_write["is_historical"]].copy()
if len(hist_pdf) > 1:
    hist_pdf = hist_pdf.sort_values("forecast_date")
    actual_non_null = hist_pdf["actual"].dropna()
    start_actual = float(actual_non_null.iloc[0]) if actual_non_null.shape[0] else 0.0
    end_actual = float(actual_non_null.iloc[-1]) if actual_non_null.shape[0] else 0.0
    growth_rate = ((end_actual - start_actual) / start_actual) if start_actual else 0.0
else:
    growth_rate = 0.0

if growth_rate > 0.05:
    trend_status = "accelerating"
elif growth_rate < -0.02:
    trend_status = "decelerating"
else:
    trend_status = "stable"

mape_non_null = df_to_write["model_mape"].dropna()
model_mape = float(mape_non_null.mean()) if mape_non_null.shape[0] else 0.0

hist_eval = hist_pdf.dropna(subset=["actual", "most_likely"]) if "most_likely" in hist_pdf.columns else hist_pdf.iloc[0:0]
if len(hist_eval) > 0:
    rmse = float(np.sqrt(np.mean((hist_eval["actual"] - hist_eval["most_likely"]) ** 2)))
else:
    rmse = 0.0

if model_mape <= 10:
    risk_level = "low"
elif model_mape <= 20:
    risk_level = "moderate"
else:
    risk_level = "high"

if risk_level == "low":
    model_confidence = 0.92
elif risk_level == "moderate":
    model_confidence = 0.84
else:
    model_confidence = 0.72

description = (
    f"Prophet forecast for won_pipeline is {trend_status}. "
    f"Model MAPE is {model_mape:.1f}% with RMSE {rmse:,.0f}."
)

insights_rows = [{
    "run_date": RUN_DATE,
    "metric": "won_pipeline",
    "model_name": "prophet",
    "description": description,
    "trend_status": trend_status,
    "risk_level": risk_level,
    "model_confidence": float(model_confidence),
    "key_drivers": "historical trend; seasonality; recent close pattern",
    "executive_actions": "review top at-risk deals; validate commit dates; keep coverage >3x",
    "downside_risks": "large-deal slippage; conversion softness; seasonality miss",
    "upside_opportunities": "conversion lift; faster cycle times; upside deal acceleration",
}]

insights_schema = StructType([
    StructField("run_date",             StringType(), False),
    StructField("metric",               StringType(), False),
    StructField("model_name",           StringType(), False),
    StructField("description",          StringType(), True),
    StructField("trend_status",         StringType(), True),
    StructField("risk_level",           StringType(), True),
    StructField("model_confidence",     DoubleType(), True),
    StructField("key_drivers",          StringType(), True),
    StructField("executive_actions",    StringType(), True),
    StructField("downside_risks",       StringType(), True),
    StructField("upside_opportunities", StringType(), True),
])

sdf_insights = spark.createDataFrame(insights_rows, schema=insights_schema)
sdf_insights = sdf_insights.withColumn("created_at", F.current_timestamp())

# ── Build model leaderboard snapshot ─────────────────────────────────────────
leaderboard_rows = [{
    "run_date": RUN_DATE,
    "metric": "won_pipeline",
    "model_name": "prophet",
    "mape": float(model_mape),
    "rmse": float(rmse),
}]

leaderboard_schema = StructType([
    StructField("run_date",   StringType(), False),
    StructField("metric",     StringType(), False),
    StructField("model_name", StringType(), False),
    StructField("mape",       DoubleType(), True),
    StructField("rmse",       DoubleType(), True),
])

sdf_leaderboard = spark.createDataFrame(leaderboard_rows, schema=leaderboard_schema)
sdf_leaderboard = sdf_leaderboard.withColumn("created_at", F.current_timestamp())

# ── Ensure database exists ───────────────────────────────────────────────────
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {OUTPUT_CATALOG}.{OUTPUT_SCHEMA}")

def upsert_run_snapshot(table_name: str, sdf):
    """Idempotent per run_date: delete run slice, then append new snapshot."""
    if not spark.catalog.tableExists(table_name):
        (
            sdf.limit(0)
            .write
            .format("delta")
            .mode("overwrite")
            .saveAsTable(table_name)
        )
    spark.sql(f"DELETE FROM {table_name} WHERE run_date = '{RUN_DATE}'")
    (
        sdf
        .write
        .format("delta")
        .mode("append")
        .saveAsTable(table_name)
    )

upsert_run_snapshot(FORECAST_OUTPUT_TABLE, sdf_output)
upsert_run_snapshot(FORECAST_INSIGHTS_TABLE, sdf_insights)
upsert_run_snapshot(FORECAST_LEADERBOARD_TABLE, sdf_leaderboard)

# ── Validation ────────────────────────────────────────────────────────────────
out_count = spark.table(FORECAST_OUTPUT_TABLE).filter(F.col("run_date") == RUN_DATE).count()
ins_count = spark.table(FORECAST_INSIGHTS_TABLE).filter(F.col("run_date") == RUN_DATE).count()
lb_count  = spark.table(FORECAST_LEADERBOARD_TABLE).filter(F.col("run_date") == RUN_DATE).count()

print(f"✓ Written {out_count:,} rows to {FORECAST_OUTPUT_TABLE} (run_date={RUN_DATE})")
print(f"✓ Written {ins_count:,} rows to {FORECAST_INSIGHTS_TABLE} (run_date={RUN_DATE})")
print(f"✓ Written {lb_count:,} rows to {FORECAST_LEADERBOARD_TABLE} (run_date={RUN_DATE})")

spark.sql(f"""
    SELECT model_name, metric, COUNT(*) AS rows, ROUND(AVG(mape), 2) AS avg_mape
    FROM {FORECAST_LEADERBOARD_TABLE}
    WHERE run_date = '{RUN_DATE}'
    GROUP BY model_name, metric
    ORDER BY model_name, metric
""").show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 9 — Register Model to MLflow
# MAGIC
# MAGIC Logs the Total segment Prophet model to the Databricks MLflow Model Registry.
# MAGIC The FastAPI app (or a Databricks App) can then call the model endpoint via REST instead of querying the Delta table.

# COMMAND ----------

MLFLOW_EXPERIMENT = "/Users/gaim-team/arr-forecast-prophet"
REGISTERED_MODEL  = "arr_forecast_prophet_total"

mlflow.set_experiment(MLFLOW_EXPERIMENT)

total_result = all_results.get(("Total", "Total"))
if total_result is None:
    print("Total segment model not found — skipping MLflow registration")
else:
    total_model = total_result["model"]
    total_mape  = total_result["mape"]
    total_weeks = len(total_result["history"])

    with mlflow.start_run(run_name=f"arr_forecast_prophet_{RUN_DATE}") as run:
        # Log parameters matching Power BI config
        mlflow.log_params({
            "forecast_weeks"        : FORECAST_WEEKS,
            "interval_width"        : INTERVAL_WIDTH,
            "changepoint_prior_scale": CHANGEPOINT_PRIOR,
            "seasonality_mode"      : SEASONALITY_MODE,
            "frequency"             : FREQ,
            "training_weeks"        : total_weeks,
        })

        # Log accuracy metrics
        mlflow.log_metrics({
            "total_mape_pct" : round(total_mape, 2),
            "segments_trained": len(all_results),
        })

        # Log the Prophet model itself
        mlflow.prophet.log_model(
            pr_model=total_model,
            artifact_path="prophet_model",
            registered_model_name=REGISTERED_MODEL,
        )

        run_id = run.info.run_id
        print(f"✓ MLflow run logged:  {run_id}")
        print(f"  Experiment : {MLFLOW_EXPERIMENT}")
        print(f"  Model      : {REGISTERED_MODEL}")
        print(f"  Total MAPE : {total_mape:.1f}%")
        print(f"  Run date   : {RUN_DATE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 10 — Connect to the FastAPI / Databricks App
# MAGIC
# MAGIC ### Architecture
# MAGIC
# MAGIC ```
# MAGIC Databricks Cluster (this notebook)
# MAGIC   └─ runs Prophet per-segment
# MAGIC   └─ writes → datagroup_mdl.mdl_sales_analytics.arr_forecast_prophet (Delta)
# MAGIC
# MAGIC FastAPI backend (atlas-executive-insights)
# MAGIC   └─ GET /api/arr/forecast
# MAGIC   └─ reads ← arr_forecast_prophet (latest run_date)
# MAGIC   └─ returns JSON to frontend
# MAGIC ```
# MAGIC
# MAGIC ### Option A — FastAPI reads from Delta table (recommended)
# MAGIC
# MAGIC Update `backend/routes/arr.py` (or `main.py`) to query the pre-computed table.
# MAGIC No model runs in the app. Response time drops from ~30s (Prophet fit) to <1s (SQL read).
# MAGIC
# MAGIC ### Option B — Databricks Apps host the notebook directly
# MAGIC
# MAGIC Wrap this notebook as a Databricks App using the Databricks Apps service.
# MAGIC The app surfaces a REST endpoint automatically; the FastAPI backend calls that endpoint.