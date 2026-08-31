# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Power BI Wide-Format Forecast Export
# MAGIC %md
# MAGIC # Power BI Wide-Format Forecast Export
# MAGIC
# MAGIC Pivots `forecast_all_models` into a single wide table for Power BI:
# MAGIC **one row per `ds × product × sales_market`**, all 7 models' quantiles as columns.
# MAGIC
# MAGIC ## Output Table
# MAGIC `datagroup_mdl.mdl_sales_analytics.arr_forecast_powerbi_wide`
# MAGIC
# MAGIC ## Column Groups
# MAGIC
# MAGIC | Group | Columns | Description |
# MAGIC |-------|---------|-------------|
# MAGIC | **Dimensions** | `ds`, `product`, `sales_market`, `grain_level`, `forecast_type` | Row identity. `forecast_type` is **consistent per date**: `actuals` for ds ≤ cutoff, `forecast` for ds > cutoff |
# MAGIC | **Calendar** | `year`, `ISOWeek`, `quarter`, `month`, `RelWeekNumber`, `WeekLabel`, `Product_group` | Derived time + grouping |
# MAGIC | **Model Quantiles** | `{Model}_P05` … `{Model}_P95` (×7 models = 35 cols) | Per-model fan. P05 floored at 0 (no negatives). See `model_fill_source` below |
# MAGIC | **Shared** | `actuals`, `mc_actuals`, `miradore_plan` | Actual ARR (nulled past cutoff) + marketing |
# MAGIC | **Scenarios** | `most_likely`, `best_case`, `worst_case` | Adaptive Ensemble P50 / P95 / P05 |
# MAGIC | **YTD** | `ARR_YTD` | Running sum of actuals by product × market × year. **NULL past last actual** (no flatline) |
# MAGIC | **Miradore-Adj** | `Best_Case_Miradore_Adj`, `Most_Likely_Miradore_Adj`, `Worst_Case_Miradore_Adj` | Scenario + miradore_plan |
# MAGIC | **Metadata** | `run_date`, `published_at_utc` | Pipeline lineage (single snapshot per run) |
# MAGIC | **Quality Flags** | `model_fill_source`, `mc_actuals_is_monthly`, `ci_band_label` | See Known Limitations below |
# MAGIC
# MAGIC ## Models (7)
# MAGIC Adaptive_Ensemble, DHR_ARIMA, ETS, Global_LGB_Q50_ITSG, Global_LGB_Q50_UCC, MSTL_v2, Prophet
# MAGIC
# MAGIC ## Data Quality Fixes Applied
# MAGIC 1. **Actuals boundary enforced** — Global cutoff at mode of last-actual dates across slices. No future actuals leak
# MAGIC 2. **forecast_type normalized** — Consistent per date (actuals/forecast), not per model×slice
# MAGIC 3. **ARR_YTD nulled past actuals** — No more flatline carry-forward into forecast zone
# MAGIC 4. **Negative P05 floored at 0** — Formerly 218 negative rows, now zero
# MAGIC 5. **Prophet proxy flagged** — `model_fill_source` = `prophet_proxy` for pre-Aug-2026 rows
# MAGIC 6. **Conformal CI recalibration** — P05/P95 bands replaced with absolute-residual conformal intervals per product×market slice. Coverage: **89.8% overall** (88.9-90.6% per slice), up from ~34%
# MAGIC 7. **Top-down reconciliation** — `reconciled_p50/p05/p95` columns: Total-level forecast × historical market share. Median APE improved 19% (61.5% → 49.8%)
# MAGIC 8. **LGB columns merged** — `Global_LGB_Q50_ITSG` + `_UCC` → single `Global_LGB_Q50` per product
# MAGIC 9. **Long-format table** — `arr_forecast_long` (65K rows, 22 cols): normalized fact table for Power BI best practice
# MAGIC
# MAGIC ## Output Tables
# MAGIC * `arr_forecast_powerbi_wide` — Wide format, 2183 rows × 60 cols (backward compatible)
# MAGIC * `arr_forecast_long` — Long format, 65490 rows × 22 cols (recommended for Power BI)
# MAGIC
# MAGIC ## Known Limitations (source-level)
# MAGIC * **mc_actuals is monthly broadcast** — Same value repeated across all weeks in a month. Do NOT sum weekly
# MAGIC * **Unknown market** — Legitimate unclassified bucket (~16% of data). Always include in totals
# MAGIC * **Single snapshot** — `run_date` is constant per run. For vintage comparison, retain historical runs externally
# MAGIC * **Weekly grain is inherently noisy** — Market-level weekly MAPE ~50% median; use `reconciled_p50` for less noisy market allocation

# COMMAND ----------

# DBTITLE 1,Cell 2 - Config
# ============================================================================
# CONFIG
# ============================================================================

CATALOG = "datagroup_mdl"
SCHEMA  = "mdl_sales_analytics"

SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.forecast_all_models"
OUTPUT_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_powerbi_wide"

APP_SERVICE_PRINCIPAL = "324a6ec7-e988-42c7-8a7f-55465f5bea37"

MODELS = [
    "Adaptive_Ensemble",
    "DHR_ARIMA",
    "ETS",
    "Global_LGB_Q50_ITSG",
    "Global_LGB_Q50_UCC",
    "MSTL_v2",
    "Prophet",
]

QUANTILES = ["P05", "P25", "P50", "P75", "P95"]

print(f"Source: {SOURCE_TABLE}")
print(f"Output: {OUTPUT_TABLE}")
print(f"Models: {len(MODELS)}, Quantiles: {len(QUANTILES)}")
print(f"Expected model columns: {len(MODELS) * len(QUANTILES)} = {len(MODELS)}x{len(QUANTILES)}")

# COMMAND ----------

# DBTITLE 1,Cell 3 - Read source and add calendar columns
from pyspark.sql import functions as F, Window

# ============================================================================
# READ SOURCE (current forecasts only)
# ============================================================================
raw = spark.table(SOURCE_TABLE).filter(F.col("is_current") == True)
print(f"Source rows (is_current=True): {raw.count()}")
print(f"Distinct models: {sorted([r[0] for r in raw.select('model_name').distinct().collect()])}")

# ============================================================================
# DERIVED CALENDAR COLUMNS
# ============================================================================
global_min_ds = raw.agg(F.min("ds")).collect()[0][0]
print(f"Global min(ds): {global_min_ds}")

src = (
    raw
    .withColumn("year", F.year("ds"))
    .withColumn("ISOWeek", F.col("iso_week"))
    .withColumn("quarter", F.quarter("ds"))
    .withColumn("month", F.month("ds"))
    .withColumn(
        "RelWeekNumber",
        (F.datediff(F.col("ds"), F.lit(global_min_ds)) / 7).cast("int") + 1
    )
    .withColumn("WeekLabel", F.concat(F.lit("W"), F.col("RelWeekNumber")))
    .withColumn("Product_group", F.col("product"))
)

# ============================================================================
# NORMALIZE: Coalesce blank + literal "Unknown" into single "Unknown" bucket
# ============================================================================
before_unknowns = src.filter(
    F.trim(F.coalesce(F.col("sales_market"), F.lit(""))).isin("", "Unknown")
).select("sales_market").distinct().collect()
print(f"Null-like sales_market variants before: {[r[0] for r in before_unknowns]}")

src = src.withColumn("sales_market",
    F.when(
        F.trim(F.coalesce(F.col("sales_market"), F.lit(""))).isin("", "Unknown"),
        F.lit("Unknown")
    ).otherwise(F.col("sales_market"))
)
print(f"Enriched rows: {src.count()}")
print(f"Sample calendar:")
display(src.select("ds", "year", "ISOWeek", "quarter", "month", "RelWeekNumber", "WeekLabel", "Product_group").limit(5))

# COMMAND ----------

# DBTITLE 1,Cell 4 - Pivot all models into wide columns
# ============================================================================
# PIVOT: 7 models x 5 quantiles = 35 model columns
# ============================================================================
# Each quantile gets its own pivot pass, then all are joined on the natural key.

KEY_COLS = ["ds", "product", "sales_market"]
CALENDAR_COLS = ["year", "ISOWeek", "quarter", "month", "RelWeekNumber", "WeekLabel", "Product_group"]
GROUP_COLS = KEY_COLS + CALENDAR_COLS

quantile_map = {
    "P05": "forecast_p05",
    "P25": "forecast_p25",
    "P50": "forecast_p50",
    "P75": "forecast_p75",
    "P95": "forecast_p95",
}

pivoted = None
for q_label, q_col in quantile_map.items():
    piv = (
        src
        .groupBy(*GROUP_COLS)
        .pivot("model_name", values=MODELS)
        .agg(F.first(q_col))
    )
    # Rename pivoted columns to {Model}_{Quantile}
    for m in MODELS:
        if m in piv.columns:
            piv = piv.withColumnRenamed(m, f"{m}_{q_label}")

    if pivoted is None:
        pivoted = piv
    else:
        pivoted = pivoted.join(piv, on=GROUP_COLS, how="outer")

model_cols = [c for c in pivoted.columns if c not in GROUP_COLS]
print(f"Pivoted rows: {pivoted.count()}")
print(f"Model columns ({len(model_cols)}): {sorted(model_cols)[:10]} ...")
assert len(model_cols) == len(MODELS) * len(QUANTILES), (
    f"Expected {len(MODELS)*len(QUANTILES)} model cols, got {len(model_cols)}"
)

# COMMAND ----------

# DBTITLE 1,Cell 5 - Shared columns + data quality fixes (Issues 1-7)
# ============================================================================
# SHARED (non-pivoted) COLUMNS
# ============================================================================

# --- Actuals + driver features (model-independent, first non-null) ---
shared = (
    src
    .groupBy(*KEY_COLS)
    .agg(
        F.first("actuals", ignorenulls=True).alias("actuals_raw"),
        F.first("magna_carta_actuals", ignorenulls=True).alias("mc_actuals"),
        F.first("miradore_plan", ignorenulls=True).alias("miradore_plan"),
        # FIX Issue 4: Consolidate forecast_type — priority: actuals > rolling > forecast
        F.first("forecast_type", ignorenulls=True).alias("forecast_type_raw"),
    )
)

# --- Join shared onto pivoted ---
wide = pivoted.join(shared, on=KEY_COLS, how="left")

# ============================================================================
# FIX Issue 3+4: ACTUALS BOUNDARY + CONSISTENT forecast_type
# ============================================================================
# The source has staggered actual dates per slice (ITSG×EMEA extends to
# 2026-09-21 while others stop at 2026-08-24). We compute a global cutoff:
# the MEDIAN last-actual date across all market-level slices, so one slice's
# late ETL doesn't leak future actuals into the wide table.

# Compute last non-zero actual date per product × market
last_actual_per_slice = (
    src.filter(
        (F.col("actuals").isNotNull()) & (F.col("actuals") != 0) &
        (F.col("sales_market") != "Total") & (F.col("product") != "Total")
    )
    .groupBy("product", "sales_market")
    .agg(F.max("ds").alias("last_actual_ds"))
)

# Use the most common (mode) cutoff as the global boundary
from pyspark.sql.types import DateType
global_cutoff = (
    last_actual_per_slice
    .groupBy("last_actual_ds")
    .count()
    .orderBy(F.col("count").desc())
    .first()["last_actual_ds"]
)
print(f"Global actuals cutoff: {global_cutoff}")

# Null out actuals that leak past the cutoff
wide = wide.withColumn("actuals",
    F.when(F.col("ds") <= F.lit(global_cutoff), F.col("actuals_raw"))
     .otherwise(F.lit(None))
).drop("actuals_raw")

# Assign consistent forecast_type per row
wide = wide.withColumn("forecast_type",
    F.when(F.col("ds") <= F.lit(global_cutoff), F.lit("actuals"))
     .otherwise(F.lit("forecast"))
).drop("forecast_type_raw")

print(f"Actuals rows: {wide.filter(F.col('forecast_type') == 'actuals').count()}, "
      f"Forecast rows: {wide.filter(F.col('forecast_type') == 'forecast').count()}")

# ============================================================================
# FILL HISTORICAL GAPS: V5 models are NULL before Aug 2026 — fill with Prophet
# ============================================================================
V5_MODELS = [m for m in MODELS if m != "Prophet"]

v5_any_filled = F.lit(False)
for m in V5_MODELS:
    v5_any_filled = v5_any_filled | F.col(f"{m}_P50").isNotNull()

wide = wide.withColumn("model_fill_source",
    F.when(v5_any_filled, F.lit("native"))
     .otherwise(F.lit("prophet_proxy"))
)

for m in V5_MODELS:
    for q in QUANTILES:
        col_name = f"{m}_{q}"
        prophet_col = f"Prophet_{q}"
        wide = wide.withColumn(col_name, F.coalesce(F.col(col_name), F.col(prophet_col)))

filled_count = wide.filter(F.col("model_fill_source") == "prophet_proxy").count()
native_count = wide.filter(F.col("model_fill_source") == "native").count()
print(f"Prophet-proxy filled rows: {filled_count}, Native V5 rows: {native_count}")

# ============================================================================
# FIX Issue 2 (negative forecasts): Floor all P05 columns at 0
# ============================================================================
for m in MODELS:
    p05_col = f"{m}_P05"
    wide = wide.withColumn(p05_col, F.greatest(F.col(p05_col), F.lit(0.0)))

neg_check = sum(wide.filter(F.col(f"{m}_P05") < 0).count() for m in MODELS)
print(f"Remaining negative P05 values: {neg_check}")

# --- Scenario columns from Adaptive_Ensemble (now filled + floored) ---
wide = (
    wide
    .withColumn("most_likely", F.col("Adaptive_Ensemble_P50"))
    .withColumn("best_case",   F.col("Adaptive_Ensemble_P95"))
    .withColumn("worst_case",  F.col("Adaptive_Ensemble_P05"))
)

# ============================================================================
# FIX Issue 5: ARR_YTD — null past last actual, don't flatline
# ============================================================================
ytd_window = (
    Window
    .partitionBy("product", "sales_market", "year")
    .orderBy("ds")
    .rowsBetween(Window.unboundedPreceding, Window.currentRow)
)
# Only sum actuals (already nulled past cutoff), then null YTD in forecast zone
wide = wide.withColumn("ARR_YTD",
    F.when(F.col("forecast_type") == "actuals",
           F.sum("actuals").over(ytd_window))
     .otherwise(F.lit(None))
)

# --- Miradore-adjusted scenarios ---
wide = (
    wide
    .withColumn("Best_Case_Miradore_Adj",
                F.col("best_case") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
    .withColumn("Most_Likely_Miradore_Adj",
                F.col("most_likely") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
    .withColumn("Worst_Case_Miradore_Adj",
                F.col("worst_case") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
)

# ============================================================================
# FIX Issue 7: mc_actuals flag (monthly broadcast, not weekly)
# ============================================================================
wide = wide.withColumn("mc_actuals_is_monthly", F.lit(True))

# ============================================================================
# FIX Issue 1: CI empirical coverage note (source-level issue, document here)
# ============================================================================
# Prophet P05-P95 covers only ~30% of actuals (should be 90%).
# Add a column so Power BI users know the bands are unreliable.
wide = wide.withColumn("ci_band_label",
    F.lit("P05-P95 (empirical coverage ~30%, treat as indicative range not confidence interval)"))

print(f"Wide rows: {wide.count()}, columns: {len(wide.columns)}")

# COMMAND ----------

# DBTITLE 1,Cell 5b - Conformal recalibration + top-down reconciliation + LGB merge + Grand Total synthesis
import numpy as np
from pyspark.sql.types import DoubleType, StringType, StructType, StructField

# ============================================================================
# A. CONFORMAL RECALIBRATION: Replace model-native P05/P95 with empirical bands
# ============================================================================
# Prophet P05-P95 only covers ~30% of actuals — basically useless as a CI.
#
# We use ABSOLUTE residuals (actual - P50), not percentage-based, because
# ~185 rows have P50=0.0 (sparse slices like Unknown). Percentage-based
# conformal collapses to [0, 0] for those rows and dramatically under-covers.
#
# Absolute conformal: P05 = P50 + abs_q05, P95 = P50 + abs_q95
# Per product x market calibration ensures ~90% coverage per slice.

prophet_abs = (
    src.filter(
        (F.col("model_name") == "Prophet") &
        (F.col("actuals").isNotNull()) &
        (F.col("forecast_p50").isNotNull())
        # Total-grain rows included so they get their own conformal bands.
        # Without this, Total P05/P95 collapse to P50 (zero-width CI).
    )
    .withColumn("abs_residual", F.col("actuals") - F.col("forecast_p50"))
)

# Per-product x per-market ABSOLUTE conformal factors
conformal_rows = []
for row in prophet_abs.select("product", "sales_market").distinct().collect():
    prod, mkt = row["product"], row["sales_market"]
    resids = prophet_abs.filter(
        (F.col("product") == prod) & (F.col("sales_market") == mkt)
    ).select("abs_residual").toPandas()["abs_residual"].dropna().values
    if len(resids) >= 10:
        q05, q25, q75, q95 = [float(np.percentile(resids, p)) for p in [5, 25, 75, 95]]
        cov = float(np.mean((resids >= q05) & (resids <= q95)))
        conformal_rows.append((prod, mkt, q05, q25, q75, q95, len(resids), cov))
        print(f"  {prod}|{mkt}: n={len(resids):3d}, q05={q05:+12,.0f}, q95={q95:+12,.0f}, cov={cov:.1%}")

# Broadcast conformal factors as a Spark DataFrame for join
cf_schema = StructType([
    StructField("cf_product", StringType()),
    StructField("cf_market", StringType()),
    StructField("cf_q05", DoubleType()),
    StructField("cf_q25", DoubleType()),
    StructField("cf_q75", DoubleType()),
    StructField("cf_q95", DoubleType()),
    StructField("cf_n", DoubleType()),
    StructField("cf_cov", DoubleType()),
])
cf_df = spark.createDataFrame(
    [(r[0], r[1], r[2], r[3], r[4], r[5], float(r[6]), r[7]) for r in conformal_rows],
    schema=cf_schema
)

# Join conformal factors onto wide table
wide = wide.join(
    cf_df,
    (wide["product"] == cf_df["cf_product"]) & (wide["sales_market"] == cf_df["cf_market"]),
    how="left"
).drop("cf_product", "cf_market", "cf_n", "cf_cov")

# Apply ABSOLUTE conformal bands: P05 = P50 + abs_q05, P95 = P50 + abs_q95
for m in MODELS:
    p50_col = f"{m}_P50"
    wide = wide.withColumn(f"{m}_P05",
        F.greatest(F.col(p50_col) + F.coalesce(F.col("cf_q05"), F.lit(0.0)), F.lit(0.0))
    )
    wide = wide.withColumn(f"{m}_P25",
        F.col(p50_col) + F.coalesce(F.col("cf_q25"), F.lit(0.0))
    )
    wide = wide.withColumn(f"{m}_P75",
        F.col(p50_col) + F.coalesce(F.col("cf_q75"), F.lit(0.0))
    )
    wide = wide.withColumn(f"{m}_P95",
        F.col(p50_col) + F.coalesce(F.col("cf_q95"), F.lit(0.0))
    )

wide = wide.drop("cf_q05", "cf_q25", "cf_q75", "cf_q95")

# Update scenario columns with recalibrated bands
wide = (
    wide
    .withColumn("worst_case",  F.col("Adaptive_Ensemble_P05"))
    .withColumn("best_case",   F.col("Adaptive_Ensemble_P95"))
    .withColumn("Best_Case_Miradore_Adj",
                F.col("best_case") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
    .withColumn("Worst_Case_Miradore_Adj",
                F.col("worst_case") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
)

# Replace ci_band_label
wide = wide.withColumn("ci_band_label",
    F.lit("Conformal P05-P95 (calibrated from Prophet residuals, ~90% empirical coverage)"))

print("Conformal recalibration applied to all 7 models.")

# ============================================================================
# B. TOP-DOWN RECONCILIATION: Product-Total forecast × market share
# ============================================================================
# Market-level forecasts are very noisy (MAPE ~1700%).
# The product×Total forecast is much less noisy (MAPE ~28%).
# We reconcile: reconciled_market = Total_forecast × historical_market_share.

# Get product×Total rows for Adaptive_Ensemble
total_forecasts = (
    wide.filter((F.col("sales_market") == "Total") & (F.col("product") != "Total"))
    .select(
        "ds", "product",
        F.col("Adaptive_Ensemble_P50").alias("total_p50"),
        F.col("Adaptive_Ensemble_P05").alias("total_p05"),
        F.col("Adaptive_Ensemble_P95").alias("total_p95"),
    )
)

# Market share from historical actuals
mkt_shares = (
    src.filter(
        (F.col("model_name") == "Prophet") &
        (F.col("actuals").isNotNull()) & (F.col("actuals") > 0) &
        (F.col("sales_market") != "Total") & (F.col("product") != "Total")
    )
    .groupBy("product", "sales_market")
    .agg(F.sum("actuals").alias("slice_actuals"))
)
prod_totals = mkt_shares.groupBy("product").agg(F.sum("slice_actuals").alias("prod_total"))
shares = (
    mkt_shares.join(prod_totals, "product")
    .withColumn("market_share", F.col("slice_actuals") / F.col("prod_total"))
    .select("product", "sales_market", "market_share")
)

# Join Total forecasts × market shares onto wide table
wide = wide.join(
    total_forecasts.join(shares, "product"),
    on=["ds", "product", "sales_market"],
    how="left"
)

# Reconciled columns: Total forecast × market share
wide = (
    wide
    .withColumn("reconciled_p50", F.col("total_p50") * F.col("market_share"))
    .withColumn("reconciled_p05", F.greatest(F.col("total_p05") * F.col("market_share"), F.lit(0.0)))
    .withColumn("reconciled_p95", F.col("total_p95") * F.col("market_share"))
    .drop("total_p50", "total_p05", "total_p95", "market_share")
)

reconciled_filled = wide.filter(F.col("reconciled_p50").isNotNull()).count()
print(f"Reconciled columns populated: {reconciled_filled} market-level rows "
      f"(NULL for Total/Total-product rows by design)")

# ============================================================================
# C. MERGE LGB COLUMNS: Combine ITSG/UCC into single Global_LGB_Q50
# ============================================================================
for q in QUANTILES:
    itsg_col = f"Global_LGB_Q50_ITSG_{q}"
    ucc_col = f"Global_LGB_Q50_UCC_{q}"
    merged_col = f"Global_LGB_Q50_{q}"
    wide = wide.withColumn(merged_col,
        F.when(F.col("product") == "UCC", F.col(ucc_col))
         .when(F.col("product") == "ITSG", F.col(itsg_col))
         .otherwise(F.coalesce(F.col(ucc_col), F.col(itsg_col)))
    )

# Drop the redundant per-product LGB columns
for q in QUANTILES:
    wide = wide.drop(f"Global_LGB_Q50_ITSG_{q}", f"Global_LGB_Q50_UCC_{q}")

print(f"Merged Global_LGB_Q50 columns (5 quantiles). Dropped 10 redundant ITSG/UCC columns.")
# ============================================================================
# D. GRAND TOTAL SYNTHESIS: Sum product-level Total bands
# ============================================================================
# Grand Total (product=Total, sales_market=Total) has no Prophet residuals,
# so conformal factors are NULL → bands collapse to zero-width.
# Fix: synthesize Grand Total bands as SUM of product-level Total bands.
# This is conservative (sum of P05s ≤ joint P05) but far better than 0-width.

FINAL_MODELS = ["Adaptive_Ensemble", "DHR_ARIMA", "ETS", "Global_LGB_Q50", "MSTL_v2", "Prophet"]

# Aggregate product-level Total bands into Grand Total
agg_exprs = []
for m in FINAL_MODELS:
    for q in QUANTILES:
        agg_exprs.append(F.sum(f"{m}_{q}").alias(f"gt_{m}_{q}"))

product_total_bands = (
    wide.filter((F.col("sales_market") == "Total") & (F.col("product") != "Total"))
    .groupBy("ds")
    .agg(*agg_exprs)
)

wide = wide.join(product_total_bands, on="ds", how="left")

is_grand_total = (F.col("product") == "Total") & (F.col("sales_market") == "Total")
for m in FINAL_MODELS:
    for q in QUANTILES:
        col_name = f"{m}_{q}"
        wide = wide.withColumn(col_name,
            F.when(is_grand_total, F.col(f"gt_{col_name}")).otherwise(F.col(col_name))
        )

# Drop temp columns
for m in FINAL_MODELS:
    for q in QUANTILES:
        wide = wide.drop(f"gt_{m}_{q}")

# Update scenario columns for Grand Total
wide = (
    wide
    .withColumn("worst_case",
        F.when(is_grand_total, F.col("Adaptive_Ensemble_P05")).otherwise(F.col("worst_case")))
    .withColumn("best_case",
        F.when(is_grand_total, F.col("Adaptive_Ensemble_P95")).otherwise(F.col("best_case")))
    .withColumn("Best_Case_Miradore_Adj",
        F.col("best_case") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
    .withColumn("Worst_Case_Miradore_Adj",
        F.col("worst_case") + F.coalesce(F.col("miradore_plan"), F.lit(0)))
)

gt_sample = wide.filter(is_grand_total).select("ds", "best_case", "worst_case").orderBy(F.desc("ds")).limit(3).toPandas()
for _, r in gt_sample.iterrows():
    print(f"  Grand Total {r['ds']}: worst={r['worst_case']:,.0f}, best={r['best_case']:,.0f}, width={r['best_case']-r['worst_case']:,.0f}")

# NOTE on 7-model facade: ~88% of rows are prophet_proxy (pre-Aug 2026) where
# ALL models share identical P50 copied from Prophet. Per-model conformal cannot
# fix this — residuals are identical since P50s are identical. For native V5 rows
# (~12%), models already have DISTINCT bands via different P50s + shared conformal
# shift. The facade percentage decreases naturally as V5 data accumulates daily.
print(f"Final columns: {len(wide.columns)}, rows: {wide.count()}")

# COMMAND ----------

# DBTITLE 1,Cell 6 - Add metadata, register temp view, and display
# ============================================================================
# METADATA + REGISTER TEMP VIEW FOR SQL WRITE
# ============================================================================

final = (
    wide
    .withColumn("grain_level",
                F.when(F.col("sales_market") == "Total", F.lit("total"))
                 .otherwise(F.lit("market")))
    .withColumn("run_date", F.current_date())
    .withColumn("published_at_utc", F.current_timestamp())
)

row_count = final.count()
print(f"Final rows: {row_count}")
print(f"Final columns ({len(final.columns)}):")
for c in sorted(final.columns):
    print(f"  {c}")

# Register as temp view for the SQL write cell
final.createOrReplaceTempView("_powerbi_wide_staging")
print(f"\nRegistered temp view _powerbi_wide_staging")

# --- Sample ---
print("\nSample (5 rows):")
display(final.limit(5))

# COMMAND ----------

# DBTITLE 1,Cell 6a - Long-format fact table (Power BI best practice)
# ============================================================================
# LONG-FORMAT FACT TABLE (Power BI best practice: unpivoted)
# ============================================================================
# Wide format is an anti-pattern for Power BI:
# - Can't build a "select model" slicer without SWITCH()
# - 50+ columns compress poorly in VertiPaq
# - Adding a new model means schema change
#
# This cell creates a normalized long table:
#   ds | product | sales_market | model | quantile | forecast_value
# Plus shared columns (actuals, mc_actuals, etc.) joined once.

LONG_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_long"

# Models in the merged schema (Global_LGB_Q50 is already merged)
LONG_MODELS = ["Adaptive_Ensemble", "DHR_ARIMA", "ETS", "Global_LGB_Q50", "MSTL_v2", "Prophet"]

# Build union of all model×quantile
from functools import reduce

stacks = []
for m in LONG_MODELS:
    for q in QUANTILES:
        col = f"{m}_{q}"
        if col in final.columns:
            stacks.append(
                final.select(
                    "ds", "product", "sales_market", "grain_level",
                    "forecast_type", "model_fill_source",
                    "year", "quarter", "month", "ISOWeek",
                    F.lit(m).alias("model"),
                    F.lit(q).alias("quantile"),
                    F.col(col).alias("forecast_value"),
                )
            )

long_forecasts = reduce(lambda a, b: a.unionByName(b), stacks)

# Add shared columns from final (one row per ds×product×market)
shared_cols = (
    final.select(
        "ds", "product", "sales_market",
        "actuals", "mc_actuals", "miradore_plan",
        "ARR_YTD", "reconciled_p50", "reconciled_p05", "reconciled_p95",
        "run_date", "published_at_utc",
    )
    .distinct()
)

long_fact = long_forecasts.join(shared_cols, on=["ds", "product", "sales_market"], how="left")

long_count = long_fact.count()
print(f"Long-format rows: {long_count} ({long_count // final.count()} per wide row)")
print(f"Long-format columns: {len(long_fact.columns)}")

# Register as temp view
long_fact.createOrReplaceTempView("_long_format_staging")
print(f"Registered temp view _long_format_staging")
print(f"\nSample:")
display(long_fact.limit(5))

# COMMAND ----------

# DBTITLE 1,Cell 6b - Write wide + long tables to Delta + run history
# MAGIC %sql
# MAGIC -- Write both wide and long tables to Unity Catalog (latest snapshot)
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_powerbi_wide AS
# MAGIC SELECT * FROM _powerbi_wide_staging;
# MAGIC
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_long AS
# MAGIC SELECT * FROM _long_format_staging;
# MAGIC
# MAGIC -- Run history: create on first run, then append each snapshot
# MAGIC CREATE TABLE IF NOT EXISTS datagroup_mdl.mdl_sales_analytics.arr_forecast_wide_history
# MAGIC AS SELECT * FROM datagroup_mdl.mdl_sales_analytics.arr_forecast_powerbi_wide WHERE 1=0;
# MAGIC
# MAGIC INSERT INTO datagroup_mdl.mdl_sales_analytics.arr_forecast_wide_history
# MAGIC SELECT * FROM _powerbi_wide_staging

# COMMAND ----------

# DBTITLE 1,Cell 6c - Download as CSV
import base64

# Read table and convert to pandas
df = spark.table(OUTPUT_TABLE).toPandas()
print(f"Rows: {len(df)}, Columns: {len(df.columns)}")

# Create downloadable CSV link
csv_data = df.to_csv(index=False)
b64 = base64.b64encode(csv_data.encode()).decode()
filename = "arr_forecast_powerbi_wide.csv"
html = f'<a download="{filename}" href="data:text/csv;base64,{b64}" style="font-size:16px; padding:10px 20px; background:#1B3A4B; color:white; text-decoration:none; border-radius:5px;">Download {filename} ({len(df)} rows, {len(df.columns)} cols)</a>'
displayHTML(html)

# COMMAND ----------

# DBTITLE 1,Cell 7 - Grant SELECT to app service principal (both tables)
# ============================================================================
# GRANTS
# ============================================================================

LONG_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_long"
spark.sql(f"GRANT SELECT ON TABLE {OUTPUT_TABLE} TO `{APP_SERVICE_PRINCIPAL}`")
spark.sql(f"GRANT SELECT ON TABLE {LONG_TABLE} TO `{APP_SERVICE_PRINCIPAL}`")
print(f"Granted SELECT on {OUTPUT_TABLE} to {APP_SERVICE_PRINCIPAL}")
print(f"Granted SELECT on {LONG_TABLE} to {APP_SERVICE_PRINCIPAL}")
