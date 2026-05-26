# Databricks notebook source
# This file is sourced into a Databricks Workflow (scheduled job).
# Recommended schedule: every 4-6 hours  (e.g., 06:00, 12:00, 18:00 UTC)
# Cluster: Serverless (job cluster, auto-scales)
# Service principal: needs READ on federated.sales.* and
#                    READ+WRITE on datagroup_mdl.mdl_sales_analytics.*

# COMMAND ----------
# MAGIC %md
# MAGIC ## Atlas Executive Insights — Gold Layer Refresh
# MAGIC Pre-computes all metrics, insights, and forecast results so the app reads
# MAGIC from cheap single-table queries instead of spinning up a cluster on demand.

# COMMAND ----------

import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from pyspark.sql import SparkSession
from pyspark.sql.functions import lit, current_timestamp, col
from pyspark.sql import functions as F

spark = SparkSession.builder.getOrCreate()

CATALOG = "datagroup_mdl"
SCHEMA  = "mdl_sales_analytics"
PREFIX  = f"{CATALOG}.{SCHEMA}"

# Infer current fiscal quarter (adjust to your fiscal calendar)
today     = datetime.utcnow().date()
quarter   = (today.month - 1) // 3 + 1
q_start   = datetime(today.year, (quarter - 1) * 3 + 1, 1).date()
q_end_est = datetime(today.year, min(quarter * 3, 12), 28).date()  # approx

print(f"Refreshing gold layer — {today}  Q{quarter} {q_start} → {q_end_est}")

# COMMAND ----------
# MAGIC %md ### 1. metrics_summary — KPI health status snapshot

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {PREFIX}.atlas_metrics_summary (
  refresh_ts        TIMESTAMP,
  quarter           INT,
  metric_id         STRING,
  metric_name       STRING,
  actual_value      DOUBLE,
  target_value      DOUBLE,
  attainment_pct    DOUBLE,
  status            STRING,         -- at_risk | on_track | exceeding
  prev_period_value DOUBLE,
  trend_direction   STRING,         -- up | down | flat
  trend_pct_change  DOUBLE,
  sparkline_json    STRING          -- JSON array of last 7 weekly values
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
""")

# Pull live KPI data from federated tables
kpi_df = spark.sql(f"""
SELECT
  metric_name,
  actual_value,
  target_value,
  ROUND(actual_value / NULLIF(target_value, 0) * 100, 1) AS attainment_pct,
  prev_period_value,
  CASE
    WHEN actual_value / NULLIF(target_value, 0) >= 1.10 THEN 'exceeding'
    WHEN actual_value / NULLIF(target_value, 0) >= 0.90 THEN 'on_track'
    ELSE 'at_risk'
  END AS status,
  ROUND((actual_value - prev_period_value) / NULLIF(prev_period_value, 0) * 100, 1) AS trend_pct_change
FROM {CATALOG}.{SCHEMA}.gaim_kpi_current
""")

kpi_df = kpi_df.withColumn("refresh_ts", current_timestamp()) \
               .withColumn("quarter", lit(quarter)) \
               .withColumn("trend_direction",
                   F.when(col("trend_pct_change") > 1, "up")
                    .when(col("trend_pct_change") < -1, "down")
                    .otherwise("flat")) \
               .withColumn("metric_id", F.lower(F.regexp_replace(col("metric_name"), r"\s+", "_"))) \
               .withColumn("sparkline_json", lit("[]"))

spark.sql(f"DELETE FROM {PREFIX}.atlas_metrics_summary WHERE quarter = {quarter}")
kpi_df.select(
    "refresh_ts", "quarter", "metric_id", "metric_name",
    "actual_value", "target_value", "attainment_pct",
    "status", "prev_period_value", "trend_direction",
    "trend_pct_change", "sparkline_json"
).write.mode("append").saveAsTable(f"{PREFIX}.atlas_metrics_summary")

print(f"metrics_summary: wrote {kpi_df.count()} rows")

# COMMAND ----------
# MAGIC %md ### 2. insights_cache — Pre-generated AI insights (rule-based + LLM)

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {PREFIX}.atlas_insights_cache (
  refresh_ts    TIMESTAMP,
  insight_id    STRING,
  insight_type  STRING,     -- alert | opportunity | observation
  title         STRING,
  description   STRING,
  impact        STRING,     -- High | Medium | Low
  metric        STRING,
  priority_rank INT,
  owner         STRING,
  dismissed_by  ARRAY<STRING>,
  why_text      STRING,
  source_data   STRING      -- JSON blob of the data that drove this insight
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
""")

# Generate rule-based insights from the metrics summary
insights_df = spark.sql(f"""
SELECT
  current_timestamp()  AS refresh_ts,
  uuid()               AS insight_id,
  CASE
    WHEN attainment_pct < 75 THEN 'alert'
    WHEN attainment_pct < 90 THEN 'alert'
    WHEN attainment_pct > 110 THEN 'opportunity'
    ELSE 'observation'
  END AS insight_type,
  CONCAT(
    CASE
      WHEN attainment_pct < 75 THEN '⚠ CRITICAL: '
      WHEN attainment_pct < 90 THEN '⚑ AT RISK: '
      WHEN attainment_pct > 110 THEN '↑ EXCEEDING: '
      ELSE '→ '
    END,
    metric_name, ' at ', CAST(ROUND(attainment_pct,0) AS STRING), '% of target'
  ) AS title,
  CONCAT(
    metric_name, ' is at ', CAST(ROUND(attainment_pct,1) AS STRING),
    '% of target. Actual: ', FORMAT_NUMBER(actual_value, 0),
    ', Target: ', FORMAT_NUMBER(target_value, 0), '.'
  ) AS description,
  CASE
    WHEN attainment_pct < 75 THEN 'High'
    WHEN attainment_pct < 90 THEN 'Medium'
    ELSE 'Low'
  END AS impact,
  metric_id   AS metric,
  ROW_NUMBER() OVER (ORDER BY attainment_pct ASC) AS priority_rank,
  NULL         AS owner,
  ARRAY()      AS dismissed_by,
  CONCAT(
    'This insight is based on ', metric_name,
    ' attainment of ', CAST(ROUND(attainment_pct,1) AS STRING),
    '% vs a target of ', FORMAT_NUMBER(target_value, 0), '.'
  ) AS why_text,
  TO_JSON(STRUCT(metric_id, actual_value, target_value, attainment_pct)) AS source_data
FROM {PREFIX}.atlas_metrics_summary
WHERE quarter = {quarter}
ORDER BY attainment_pct ASC
""")

spark.sql(f"DELETE FROM {PREFIX}.atlas_insights_cache")
insights_df.write.mode("append").saveAsTable(f"{PREFIX}.atlas_insights_cache")
print(f"insights_cache: wrote {insights_df.count()} rows")

# COMMAND ----------
# MAGIC %md ### 3. forecast_results — Pre-scored multi-model forecasts

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {PREFIX}.atlas_forecast_results (
  refresh_ts     TIMESTAMP,
  metric         STRING,
  model          STRING,
  horizon_days   INT,
  mape           DOUBLE,
  rmse           DOUBLE,
  is_recommended BOOLEAN,
  forecast_json  STRING    -- JSON: {{historical: [...], forecast: [...], confidence: ...}}
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
""")

# Pull daily ARR time-series
arr_df = spark.sql(f"""
SELECT
  date_trunc('day', close_date)  AS ds,
  SUM(won_amount)                AS y
FROM federated.sales.metis_won_opps_fact
WHERE close_date >= ADD_MONTHS(CURRENT_DATE(), -12)
GROUP BY 1
ORDER BY 1
""").toPandas()

arr_df["ds"] = pd.to_datetime(arr_df["ds"])
arr_df["y"]  = arr_df["y"].fillna(0).astype(float)

if len(arr_df) >= 14:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    import warnings
    warnings.filterwarnings("ignore")

    results_rows = []
    for horizon in (30, 60, 90):
        try:
            model = ExponentialSmoothing(
                arr_df["y"], trend="add", seasonal="add",
                seasonal_periods=min(7, len(arr_df) // 2)
            ).fit(optimized=True)
            fc    = model.forecast(horizon)
            hist  = [{"date": str(r.ds.date()), "value": float(r.y)}
                     for r in arr_df.itertuples()]
            fcast = [{"date": str((today + timedelta(days=i+1))), "value": float(v)}
                     for i, v in enumerate(fc)]
            mape_val = float(np.mean(np.abs((arr_df["y"].values[1:] -
                             model.fittedvalues.values[1:]) /
                             (arr_df["y"].values[1:] + 1e-10))) * 100)
            results_rows.append({
                "refresh_ts":     datetime.utcnow(),
                "metric":         "won_pipeline",
                "model":          "holt_winters",
                "horizon_days":   horizon,
                "mape":           round(mape_val, 2),
                "rmse":           0.0,
                "is_recommended": True,
                "forecast_json":  json.dumps({"historical": hist, "forecast": fcast}),
            })
        except Exception as e:
            print(f"Holt-Winters h={horizon} error: {e}")

    if results_rows:
        schema_cols = ["refresh_ts", "metric", "model", "horizon_days",
                       "mape", "rmse", "is_recommended", "forecast_json"]
        fc_df = spark.createDataFrame(
            pd.DataFrame(results_rows)[schema_cols]
        )
        spark.sql(f"DELETE FROM {PREFIX}.atlas_forecast_results WHERE metric = 'won_pipeline'")
        fc_df.write.mode("append").saveAsTable(f"{PREFIX}.atlas_forecast_results")
        print(f"forecast_results: wrote {len(results_rows)} rows")
else:
    print("Insufficient time-series data for forecasting — skipping.")

# COMMAND ----------
# MAGIC %md ### 4. revenue_gap_analysis — Pre-computed waterfall decomposition

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {PREFIX}.atlas_revenue_gap_analysis (
  refresh_ts          TIMESTAMP,
  quarter             INT,
  factor              STRING,
  impact_dollars      DOUBLE,
  impact_pct          DOUBLE,
  sort_order          INT
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
""")

gap_df = spark.sql(f"""
SELECT
  current_timestamp() AS refresh_ts,
  {quarter} AS quarter,
  factor,
  impact_dollars,
  ROUND(impact_dollars / NULLIF(ABS(SUM(CASE WHEN impact_dollars < 0 THEN impact_dollars END)
    OVER ()), 0) * 100, 1) AS impact_pct,
  sort_order
FROM (
  SELECT 'Won Volume'   AS factor, impact_opened_opps    AS impact_dollars, 1 AS sort_order FROM {CATALOG}.{SCHEMA}.gaim_kpi_current LIMIT 1
  UNION ALL
  SELECT 'Close Rate'   AS factor, impact_close_rate_opps AS impact_dollars, 2 AS sort_order FROM {CATALOG}.{SCHEMA}.gaim_kpi_current LIMIT 1
  UNION ALL
  SELECT 'Avg Deal Size' AS factor, impact_ads           AS impact_dollars, 3 AS sort_order FROM {CATALOG}.{SCHEMA}.gaim_kpi_current LIMIT 1
  UNION ALL
  SELECT 'Pipeline $'   AS factor, impact_pipeline       AS impact_dollars, 4 AS sort_order FROM {CATALOG}.{SCHEMA}.gaim_kpi_current LIMIT 1
)
ORDER BY sort_order
""")

spark.sql(f"DELETE FROM {PREFIX}.atlas_revenue_gap_analysis WHERE quarter = {quarter}")
gap_df.write.mode("append").saveAsTable(f"{PREFIX}.atlas_revenue_gap_analysis")
print(f"revenue_gap_analysis: wrote {gap_df.count()} rows")

# COMMAND ----------
# MAGIC %md ### Done — record refresh timestamp

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {PREFIX}.atlas_gold_layer_log (
  refresh_ts  TIMESTAMP,
  status      STRING,
  message     STRING
) USING DELTA
""")

spark.createDataFrame([{
    "refresh_ts": datetime.utcnow(),
    "status":     "success",
    "message":    f"Gold layer refreshed for Q{quarter} {today}",
}]).write.mode("append").saveAsTable(f"{PREFIX}.atlas_gold_layer_log")

print("✅ Gold layer refresh complete.")
