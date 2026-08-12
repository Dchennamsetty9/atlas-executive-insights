# Databricks notebook source
# GAIM / Atlas — Unified ARR Forecast (arr_forecast_all_models)
# =============================================================================
# Combines model results into ONE long-format table:
#
#   SOURCE 1  datagroup_mdl.mdl_sales_analytics.forecast_results
#             (output of forecast_unify_publish — UCC/ITSG V5 models, already
#             canonical long format: model, p10/p50/p90, actuals, model_wape, etc.)
#
#   SOURCE 2  datagroup_mdl.mdl_sales_analytics.forecast_prophet  (Sona — Prophet)
#             single-model wide table; normalized to the same schema here and
#             added as model = 'prophet_production'.
#             Wrapped in try/except — runs today before Sona's grant lands.
#
#   OUTPUT    datagroup_mdl.mdl_sales_analytics.arr_forecast_all_models
#             Identical schema to forecast_results + model_wape/model_mape.
#             One row per (ds, product, sales_market, model, forecast_type).
#
# Schedule: run AFTER forecast_unify_publish + Sona's prophet refresh.
# =============================================================================

# COMMAND ----------
# MAGIC %md ## Cell 1 — Config

# COMMAND ----------

from datetime import date
from pyspark.sql import functions as F

CATALOG        = "datagroup_mdl"
SCHEMA         = "mdl_sales_analytics"
RESULTS_TABLE  = f"{CATALOG}.{SCHEMA}.forecast_results"   # output of forecast_unify_publish
PROPHET_TABLE  = f"{CATALOG}.{SCHEMA}.forecast_prophet"   # Sona's production Prophet
OUTPUT_TABLE   = f"{CATALOG}.{SCHEMA}.arr_forecast_all_models"
APP_SP         = "324a6ec7-e988-42c7-8a7f-55465f5bea37"   # Atlas app service principal

# Canonical column order (matches forecast_results schema)
COLS = ["run_date", "ds", "product", "sales_market", "grain_level", "model",
        "forecast_type", "actual", "p10", "p50", "p90", "most_likely",
        "recommended_for_exec", "source_run_ts", "published_at_utc",
        "model_wape", "model_mape"]

RUN_DATE = date.today().isoformat()
print(f"[unified] {RUN_DATE} -> {OUTPUT_TABLE}")

# COMMAND ----------
# MAGIC %md ## Cell 2 — Read latest run from forecast_results (UCC + ITSG models)
# MAGIC This is the already-canonical long-format output of forecast_unify_publish.
# MAGIC We take only the latest run_date to avoid duplicating historical vintages.

# COMMAND ----------

results = spark.table(RESULTS_TABLE)
latest_run = results.agg(F.max("run_date")).collect()[0][0]
main_models = results.where(F.col("run_date") == F.lit(latest_run))

# Ensure all output columns exist (guard against schema drift)
for c in COLS:
    if c not in main_models.columns:
        main_models = main_models.withColumn(c, F.lit(None))
main_models = main_models.select(*COLS)

row_count = main_models.count()
model_list = [r["model"] for r in main_models.select("model").distinct().collect()]
print(f"[unified] forecast_results ({latest_run}) -> {row_count} rows, models: {sorted(model_list)}")

# COMMAND ----------
# MAGIC %md ## Cell 3 — Sona's Prophet (read-only, wrapped for pre-grant runs)
# MAGIC Normalized to the same canonical schema. forecast_type derived from whether
# MAGIC Actuals is populated; Worst_Case → p10, Best_Case → p90 (closest equivalents).

# COMMAND ----------

try:
    raw_prophet = spark.table(PROPHET_TABLE)
    last_actual_ds = raw_prophet.where(F.col("Actuals").isNotNull()) \
                                .agg(F.max("ds")).collect()[0][0]

    prophet_rows = (raw_prophet
        .withColumn("ds",          F.to_date(F.col("ds")))
        .withColumn("forecast_type",
            F.when((F.col("Actuals").isNotNull()) & (F.col("ds") <= F.lit(last_actual_ds)),
                   F.lit("actuals"))
             .otherwise(F.lit("rolling")))
        .withColumn("model",        F.lit("prophet_production"))
        .withColumn("actual",       F.col("Actuals").cast("double"))
        .withColumn("p50",          F.col("Most_Likely").cast("double"))
        .withColumn("most_likely",  F.col("Most_Likely").cast("double"))
        .withColumn("p10",          F.col("Worst_Case").cast("double"))   # closest equivalent
        .withColumn("p90",          F.col("Best_Case").cast("double"))    # closest equivalent
        .withColumn("run_date",     F.lit(RUN_DATE).cast("date"))
        .withColumn("published_at_utc", F.current_timestamp())
        .withColumn("source_run_ts",    F.lit(None).cast("timestamp"))
        .withColumn("recommended_for_exec", F.lit(0).cast("bigint"))
        .withColumn("model_wape",   F.lit(None).cast("double"))
        .withColumn("model_mape",   F.lit(None).cast("double"))
        .withColumn("grain_level",
            F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"),
                   F.lit("total"))
             .otherwise(F.lit("market")))
        .withColumn("sales_market",
            F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"),
                   F.lit("Total"))
             .otherwise(F.trim(F.col("sales_market"))))
        .select(*COLS)
    )

    n_prophet = prophet_rows.count()
    print(f"[unified] forecast_prophet -> {n_prophet} rows (prophet_production)")
except Exception as exc:
    print(f"[unified] WARN forecast_prophet not readable yet ({exc}). "
          f"Building with forecast_results models only. Re-run after Sona grants SELECT.")
    prophet_rows = None

# COMMAND ----------
# MAGIC %md ## Cell 4 — Union + write arr_forecast_all_models

# COMMAND ----------

unified = main_models if prophet_rows is None else main_models.unionByName(prophet_rows)

(unified.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"run_date = '{RUN_DATE}'")
        .option("mergeSchema", "true")
        .partitionBy("product")
        .saveAsTable(OUTPUT_TABLE))

spark.sql(f"""
    ALTER TABLE {OUTPUT_TABLE} SET TBLPROPERTIES (
        'comment' = 'Unified ARR forecast — UCC/ITSG V5 models from forecast_results + '
                    'Sona production Prophet. One row per ds/product/market/model/forecast_type.'
    )
""")

total = unified.count()
models = [r["model"] for r in unified.select("model").distinct().collect()]
print(f"[unified] wrote {total} rows -> {OUTPUT_TABLE}")
print(f"[unified] models present: {sorted(models)}")

# COMMAND ----------
# MAGIC %md ## Cell 5 — Grant the Atlas app service principal read access

# COMMAND ----------

try:
    spark.sql(f"GRANT SELECT ON TABLE {OUTPUT_TABLE} TO `{APP_SP}`")
    print(f"[unified] granted SELECT on {OUTPUT_TABLE} to app SP")
except Exception as exc:
    print(f"[unified] WARN could not grant to app SP ({exc}); grant manually if needed")

# COMMAND ----------
# MAGIC %md ## Cell 6 — Sanity preview

# COMMAND ----------

display(spark.sql(f"""
    SELECT model, forecast_type, product, COUNT(*) AS rows,
           MIN(ds) AS first_week, MAX(ds) AS last_week,
           ROUND(AVG(model_wape) * 100, 1) AS avg_wape_pct
    FROM {OUTPUT_TABLE}
    WHERE run_date = '{RUN_DATE}'
    GROUP BY model, forecast_type, product
    ORDER BY product, model, forecast_type
"""))

print(f"\n[unified] DONE {RUN_DATE}. Table: {OUTPUT_TABLE}")
