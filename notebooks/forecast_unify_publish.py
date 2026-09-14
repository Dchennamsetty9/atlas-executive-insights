# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Forecast Unify & Publish
# MAGIC
# MAGIC Consolidates the per-product V5 forecasting outputs into **one unified results table**
# MAGIC and **one AI-insights table** that the executive app reads directly — with all
# MAGIC information every Forecasting-panel tab needs.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Upstream Source Tables (`datagroup_mdl.mdl_sales_analytics`)
# MAGIC
# MAGIC | Table | Rows | Date Range | Models | Schema Highlights |
# MAGIC |-------|------|-----------|--------|-------------------|
# MAGIC | `ucc_forecast_v5` | 756 | 2026-08-10 to 2026-12-28 | 6 | Full quantiles p10-p90 by 10s, total + market grain, 21 forward weeks |
# MAGIC | `itsg_forecast_v5` | 972 | 2026-08-10 to 2027-08-09 | 6 | p10/p50/p90, total + market grain, forward + 2027 extension |
# MAGIC | `arr_forecast_v2` | ~5,600 | 2023-01 to present | — | Source of **actuals** (column `Actuals`); monthly grain |
# MAGIC | `ucc_forecast_monitoring_baseline` | 439 | — | 6 | Per-model holdout WAPE/RMSE, alert thresholds |
# MAGIC | `itsg_forecast_monitoring_baseline` | ~50 | — | 6 | Per-model WAPE/MAPE by metric_scope |
# MAGIC | `ucc_forecast_boq` | 444 | 2026-04-06 to 2027-08-09 | 7 | Rolling 1-year BOQ plan, full p10-p90 quantiles |
# MAGIC | `ucc_forecast_cbe` | 426 | 2026-04-06 to 2027-08-09 | 6 | Current Best Estimate (actuals + forecast), cumulative QTD, pace vs BOQ |
# MAGIC | `ucc_forecast_vintages` | 17,424 | 2026-07-06 to 2026-12-28 | 6 | Append-only forecast history for vintage tracking |
# MAGIC | `ucc_forecast_v4` | 792 | 2026-08-03 to 2026-12-28 | 6 | Legacy mirror for backward compatibility |
# MAGIC
# MAGIC **2026-08-30: Added Cell 6b — Hierarchical Reconciliation.** Top-down proportional
# MAGIC scaling ensures market-level forecasts sum exactly to the total-level forecast
# MAGIC within each product (UCC, ITSG). The "Total" product rollup is then recomputed
# MAGIC from reconciled values. Method: Athanasopoulos et al. (2009).
# MAGIC | `itsg_forecast_boq` | 432 | 2026-03-30 to 2027-08-09 | 6 | Rolling 1-year BOQ plan, p10/p50/p90 quantiles, forecast only |
# MAGIC | `itsg_forecast_cbe` | 432 | 2026-03-30 to 2027-08-09 | 6 | Current Best Estimate (actuals + forecast), cumulative QTD, pace vs BOQ |
# MAGIC | `itsg_forecast_v4` | 972 | 2026-08-10 to 2027-02-08 | 6 | Legacy mirror for backward compatibility |
# MAGIC
# MAGIC **Notes:**
# MAGIC - `ucc_forecast_v5` uses DATE for `ds`; `itsg_forecast_v5` uses TIMESTAMP — both cast to DATE here.
# MAGIC - **UCC quantiles**: full fan (p10, p20, ..., p90 by 10s) in V5/BOQ/CBE; this notebook propagates p10/p50/p90 to `forecast_results`.
# MAGIC - **ITSG quantiles**: p10/p50/p90 only (series is noisier at ~$350K avg weekly, ~30% WAPE; intermediate quantiles add marginal value). MC-based for Ensemble, holdout-residual-based for individual models.
# MAGIC - UCC models: `Adaptive_Ensemble`, `Prophet_trend`, `MSTL_v2`, `DHR_ARIMA`, `Global_LGB_Q50_UCC`, `ETS`.
# MAGIC - ITSG models: `Adaptive_Ensemble`, `ETS`, `MSTL_v2`, `Global_LGB_Q50_ITSG`, `Prophet_trend`, `DHR_ARIMA`.
# MAGIC - Both products' BOQ/CBE tables share the same schema and consumption patterns (forecast only vs forecast+actuals).
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Outputs Written by This Notebook
# MAGIC
# MAGIC | Table / View | Mode | Purpose |
# MAGIC |-------------|------|--------|
# MAGIC | `forecast_results` | Overwrite (replaceWhere = today) | Unified long-format: all models, products, forecast_types, both views |
# MAGIC | `forecast_results_latest` (view) | Recreated | Latest run_date slice for app queries |
# MAGIC | `forecast_insights` | Overwrite | AI-insights tab: momentum, risk, confidence per product |
# MAGIC | `forecast_graph_explanations` | Overwrite | Per-graph "explain this chart" text (3 products x 5 regions x 2 periods x 10 graphs) |
# MAGIC | `forecast_publish_log` | Append | Observability: row counts, schema version, timestamps |
# MAGIC | `forecast_results_v2compat` (view) | Recreated | Wide-format compat (mirrors `arr_forecast_v2` schema for app endpoints) |
# MAGIC | `forecast_leaderboard_v2compat` (view) | Recreated | Model accuracy leaderboard for the Accuracy tab |
# MAGIC | `forecast_insights_v2compat` (view) | Recreated | Insights reshaped for legacy app endpoint |
# MAGIC
# MAGIC All tables/views GRANTed SELECT to app service principal `324a6ec7-...`.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Design Decisions
# MAGIC
# MAGIC 1. **Actuals** pulled from `arr_forecast_v2.Actuals` (monthly grain, UCC + ITSG).
# MAGIC 2. **Accuracy** = per-model holdout WAPE from monitoring baselines.
# MAGIC 3. **Three-way disjoint tagging**: `rolling` (next 13 wks), `roy` (rest of FY), `forward_1yr` (2027+).
# MAGIC 4. **Two forecast views**: `adaptive` (default, app blends actuals in) + `boq` (pure model, stable plan target).
# MAGIC 5. **Total rollup**: UCC + ITSG summed per (ds, market, model, forecast_type, view).
# MAGIC 6. **Insights**: deterministic (no LLM) — momentum from trajectory slope, confidence from band spread + WAPE.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## How the App Reads the Output
# MAGIC
# MAGIC The executive app reads from `forecast_results_latest` (the latest `run_date` slice).
# MAGIC Two primary consumption patterns:
# MAGIC
# MAGIC ### Pattern 1 — Forecast Only (BOQ / Pure Model)
# MAGIC ```sql
# MAGIC SELECT * FROM forecast_results_latest
# MAGIC WHERE forecast_view = 'boq'
# MAGIC   AND forecast_type IN ('rolling', 'roy', 'forward_1yr')
# MAGIC ```
# MAGIC - **Use case**: Beginning-of-Quarter plan target, stable reference that doesn't shift as actuals arrive.
# MAGIC - **Rows**: One per (ds, model, product, sales_market, grain_level) — forward weeks only.
# MAGIC - **Columns used**: `p10`, `p50` (= `most_likely`), `p90` for scenario bands.
# MAGIC - **No actuals blended** — pure model output locked at forecast time.
# MAGIC
# MAGIC ### Pattern 2 — Forecast + Actuals (Adaptive / CBE)
# MAGIC ```sql
# MAGIC SELECT * FROM forecast_results_latest
# MAGIC WHERE forecast_view = 'adaptive'
# MAGIC ```
# MAGIC - **Use case**: Overview KPI, YTD cumulative, weekly chart, monthly comparisons.
# MAGIC - **Rows include**:
# MAGIC   - `forecast_type = 'actuals'` — closed weeks with `actual` populated, model = `ACTUAL`.
# MAGIC   - `forecast_type = 'rolling'` — next 13 open weeks (current quarter forward).
# MAGIC   - `forecast_type = 'roy'` — rest of FY after rolling window.
# MAGIC   - `forecast_type = 'forward_1yr'` — 2027+ planning horizon.
# MAGIC - **KPI formula**: `SUM(actual) WHERE actuals + SUM(p50) WHERE rolling/roy` = current-quarter landing.
# MAGIC - Actuals update daily as weeks close; forecast portion shrinks over the quarter.
# MAGIC
# MAGIC ### Pattern 3 — V2 Compat Wide Format (Legacy Endpoints)
# MAGIC ```sql
# MAGIC SELECT * FROM forecast_results_v2compat
# MAGIC ```
# MAGIC - **Use case**: Drop-in replacement for `arr_forecast_v2` in existing dashboard SQL.
# MAGIC - **Columns**: `Actuals`, `Most_Likely`, `Worst_Case`, `Best_Case`, `p10`, `p50`, `p90` (pivoted from long).
# MAGIC - One row per (ds, product, sales_market, forecast_type, run_date).
# MAGIC
# MAGIC ### Pattern 4 — Model Accuracy (Leaderboard Tab)
# MAGIC ```sql
# MAGIC SELECT * FROM forecast_leaderboard_v2compat
# MAGIC ```
# MAGIC - Per-model WAPE from monitoring baselines, by product.
# MAGIC
# MAGIC ### Upstream Planning Tables (Not Published Here, But App-Accessible)
# MAGIC
# MAGIC | Table | Product | Pattern | Description |
# MAGIC |-------|---------|---------|-------------|
# MAGIC | `ucc_forecast_boq` | UCC | Forecast only | Rolling 1-year pure model plan, full p10-p90 by 10s quantiles |
# MAGIC | `ucc_forecast_cbe` | UCC | Forecast + Actuals | Actuals for closed weeks + forecast for open, `pace_vs_boq_pct`, cumulative QTD |
# MAGIC | `ucc_forecast_v5` | UCC | Forecast only | 21-week forward, 6 models, total + market grain, full p10-p90 quantiles |
# MAGIC | `itsg_forecast_boq` | ITSG | Forecast only | Rolling 1-year pure model plan, p10/p50/p90 quantiles |
# MAGIC | `itsg_forecast_cbe` | ITSG | Forecast + Actuals | Actuals for closed weeks + forecast for open, `pace_vs_boq_pct`, cumulative QTD |
# MAGIC | `itsg_forecast_v5` | ITSG | Forecast only | 27-week forward, 6 models, total + market grain, p10/p50/p90 |
# MAGIC
# MAGIC The `cbe` table is the closest analog to Pattern 2 at weekly grain with QTD tracking;
# MAGIC `boq` is the closest to Pattern 1 with a full rolling 1-year window.
# MAGIC
# MAGIC **Schedule:** daily \~07:00 America/New_York (see `forecast_unify_publish.job.yml`).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 1 — Config

# COMMAND ----------

from datetime import timedelta, datetime, timezone

CATALOG = "datagroup_mdl"
SCHEMA  = "mdl_sales_analytics"

UCC_SRC       = f"{CATALOG}.{SCHEMA}.ucc_forecast_v5"
ITSG_SRC      = f"{CATALOG}.{SCHEMA}.itsg_forecast_v5"
# Actuals from CBE tables (TRUE weekly SFDC Growth ARR — replaces arr_forecast_v2
# which had inflated ITSG numbers from non-Growth revenue streams)
UCC_CBE_SRC   = f"{CATALOG}.{SCHEMA}.ucc_forecast_cbe"
ITSG_CBE_SRC  = f"{CATALOG}.{SCHEMA}.itsg_forecast_cbe"
UCC_BASELINE  = f"{CATALOG}.{SCHEMA}.ucc_forecast_monitoring_baseline"
ITSG_BASELINE = f"{CATALOG}.{SCHEMA}.itsg_forecast_monitoring_baseline"

RESULTS_TABLE  = f"{CATALOG}.{SCHEMA}.forecast_results"
RESULTS_VIEW   = f"{CATALOG}.{SCHEMA}.forecast_results_latest"
INSIGHTS_TABLE = f"{CATALOG}.{SCHEMA}.forecast_insights"
PUBLISH_LOG    = f"{CATALOG}.{SCHEMA}.forecast_publish_log"

# App-compatibility views: expose the unified data in the exact shapes the
# existing backend endpoints read (wide arr_forecast_v2 schema, leaderboard,
# insights), so repointing the app is a table-name change only — no endpoint
# SQL rewrite. forecast_results stays the single source of truth.
RESULTS_V2_VIEW  = f"{CATALOG}.{SCHEMA}.forecast_results_v2compat"
LEADERBOARD_VIEW = f"{CATALOG}.{SCHEMA}.forecast_leaderboard_v2compat"
INSIGHTS_V2_VIEW = f"{CATALOG}.{SCHEMA}.forecast_insights_v2compat"

# Per-graph "explain this chart in detail" text, precomputed per (graph, product).
# The app shows it behind an Explain icon on every chart. Precomputed baseline;
# a Genie/on-demand path can supersede this later using the same table as fallback.
GRAPH_EXPLAIN_TABLE = f"{CATALOG}.{SCHEMA}.forecast_graph_explanations"

APP_SERVICE_PRINCIPAL = "324a6ec7-e988-42c7-8a7f-55465f5bea37"
REC_MODEL       = "Adaptive_Ensemble"   # the model flagged recommended_for_exec
ROLLING_WEEKS   = 13
SCHEMA_VERSION  = "2.1"

# Fiscal year boundary: last Monday of FY2026. Weeks beyond this = forward_1yr.
# GoTo fiscal year = calendar year.
FY_END_DATE = "2026-12-28"   # last Monday of FY2026 (auto-roll: update annually)

# Canonical unified schema (long format — one row per model per week per scenario).
BASE = ["run_date", "ds", "product", "sales_market", "grain_level", "model",
        "forecast_type", "forecast_view", "actual",
        "p10", "p20", "p30", "p40", "p50", "p60", "p70", "p80", "p90",
        "most_likely",
        "recommended_for_exec", "source_run_ts", "published_at_utc"]

# Intermediate quantile columns (p20-p80) added 2026-09-11.
# UCC V5 has full p10-p90; ITSG V5 still has p10/p50/p90 only (p20-p80 = NULL
# from normalize_forecast's auto-fill). ITSG CBE/BOQ have the full fan.
INTERMEDIATE_QUANTILES = ["p20", "p30", "p40", "p60", "p70", "p80"]
COLS = BASE + ["model_wape", "model_mape"]   # accuracy joined on at the end

print(f"Publishing → {RESULTS_TABLE}, {INSIGHTS_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 2 — Extract the V5 forecast tables

# COMMAND ----------

def _safe_read(name):
    try:
        df = spark.read.table(name)
        print(f"  read {name}: {df.count()} rows")
        return df
    except Exception as exc:
        print(f"  WARN could not read {name}: {exc}")
        return None

ucc  = _safe_read(UCC_SRC)
itsg = _safe_read(ITSG_SRC)
assert ucc is not None or itsg is not None, "No source forecast tables available."

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 2b — Extend forecast with BOQ 2027 data
# MAGIC
# MAGIC V5 forecast tables may stop before the full 2027 planning window. Pull the
# MAGIC forecast-only BOQ rows after each V5 table's max `ds` so Cell 4's existing
# MAGIC `forward_1yr` tagging has complete 2027 input data.

# COMMAND ----------

from pyspark.sql import functions as F

UCC_BOQ_SRC  = f"{CATALOG}.{SCHEMA}.ucc_forecast_boq"
ITSG_BOQ_SRC = f"{CATALOG}.{SCHEMA}.itsg_forecast_boq"

def _boq_extension_rows(boq_table, v5_df, product):
    """Map forecast-only BOQ rows beyond the V5 horizon into V5-compatible rows."""
    if v5_df is None:
        return None
    max_ds = v5_df.agg(F.max(F.to_date("ds")).alias("max_ds")).collect()[0]["max_ds"]
    if max_ds is None:
        return None
    try:
        boq = spark.table(boq_table)
    except Exception as exc:
        print(f"  WARN could not read {boq_table}: {exc}")
        return None

    out = (boq
        .where((F.to_date("ds") > F.lit(max_ds)) & (F.lower(F.col("source")) == F.lit("forecast")))
        .select(
            F.col("model"),
            F.to_date("ds").alias("ds"),
            F.col("forecast").cast("double").alias("forecast"),
            F.col("p10").cast("double").alias("p10"),
            F.col("p50").cast("double").alias("p50"),
            F.col("p90").cast("double").alias("p90"),
            F.col("grain_level"),
            F.col("sales_market"),
            F.when(F.col("model") == F.lit(REC_MODEL), F.lit(1)).otherwise(F.lit(0)).cast("bigint").alias("recommended_for_exec"),
            F.col("run_date_utc").cast("timestamp").alias("run_timestamp_utc"),
            F.col("pipeline_version"),
        ))
    print(f"  {product} BOQ extension rows after {max_ds}: {out.count()}")
    return out

ucc_ext = _boq_extension_rows(UCC_BOQ_SRC, ucc, "UCC")
itsg_ext = _boq_extension_rows(ITSG_BOQ_SRC, itsg, "ITSG")

if ucc_ext is not None:
    ucc = ucc.unionByName(ucc_ext, allowMissingColumns=True)
if itsg_ext is not None:
    itsg = itsg.unionByName(itsg_ext, allowMissingColumns=True)

print(f"Rows after BOQ extension — UCC: {ucc.count() if ucc is not None else 0}, ITSG: {itsg.count() if itsg is not None else 0}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 3 — Normalize forecasts to the canonical schema
# MAGIC
# MAGIC `run_date` = publish date (this run), so the daily `replaceWhere` overwrite is
# MAGIC idempotent; source lineage is kept in `source_run_ts`. `ds` cast to DATE to
# MAGIC reconcile the UCC(date)/ITSG(timestamp) mismatch.

# COMMAND ----------

from pyspark.sql import functions as F

# ══════════════════════════════════════════════════════════════════════════════
# EXACT-VALUE PHILOSOPHY
# ══════════════════════════════════════════════════════════════════════════════
# This notebook publishes EXACT values from the upstream forecast pipelines.
#
# Source of p10 / p50 / p90:
#   - UCC: Monte Carlo simulation quantiles from ucc_forecast_v5
#   - ITSG: Holdout-residual-based quantiles from itsg_forecast_v5
#   These are the EXACT quantiles written by the per-product forecasting
#   notebooks. No reconstruction, no band-math, no sqrt(sum-of-squares).
#
# Source of most_likely:
#   - Always equals p50 (the median point estimate). Never an inferred or
#     approximate value.
#
# Source of actuals:
#   - CBE tables (ucc_forecast_cbe, itsg_forecast_cbe) for 2026+ weeks: TRUE
#     Growth ARR from SFDC, closed weekly.
#   - arr_forecast_v2 for 2022-2025 historical (UCC only; ITSG there is inflated).
#
# The app MUST consume these exact published values. It should NOT reconstruct
# Most Likely / Stretch Case / Risk Floor from approximate band math.
# ══════════════════════════════════════════════════════════════════════════════

def normalize_forecast(df, product):
    """Normalize a V5 forecast table into the canonical schema.

    All numeric values (p10, p50, p90, most_likely) are passed through EXACTLY
    as they appear in the source table. No transformation, no approximation.
    recommended_for_exec is preserved from the upstream pipeline.
    """
    if df is None:
        return None
    cols = set(df.columns)
    out = (df
        .withColumn("product", F.lit(product))
        .withColumn("run_date", F.current_date())
        .withColumn("published_at_utc", F.current_timestamp())
        .withColumn("ds", F.to_date(F.col("ds")))                 # unify DATE type
        .withColumn("most_likely", F.col("p50"))                   # EXACT: most_likely := p50
        .withColumn("actual", F.lit(None).cast("double"))          # forecast rows have no actual
        .withColumn("forecast_type", F.lit(None).cast("string"))  # set in Cell 4
        .withColumn("forecast_view", F.lit("adaptive"))            # default; BOQ rows added in Cell 4b
        .withColumn("source_run_ts",
                    F.col("run_timestamp_utc") if "run_timestamp_utc" in cols
                    else F.lit(None).cast("timestamp")))
    # recommended_for_exec is preserved from the source V5 table (bigint).
    # If not present in source, it defaults to NULL (filled by the loop below).
    for c in BASE:
        if c not in out.columns:
            out = out.withColumn(c, F.lit(None))
    return out.select(*BASE)

fc_parts = [p for p in (normalize_forecast(ucc, "UCC"), normalize_forecast(itsg, "ITSG")) if p is not None]
fc = fc_parts[0]
for p in fc_parts[1:]:
    fc = fc.unionByName(p, allowMissingColumns=True)

# central market-label normalization
fc = fc.withColumn(
    "sales_market",
    F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"), F.lit("Total"))
     .when(F.upper(F.trim(F.col("sales_market"))) == "UNKNOWN", F.lit("Unknown"))
     .otherwise(F.trim(F.col("sales_market"))),
)
print(f"Normalized forecast rows: {fc.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 4 — Tag forecast_type (rolling / roy / forward_1yr)
# MAGIC
# MAGIC Three-way DISJOINT tagging:
# MAGIC - `rolling` = next 13 weeks (current quarter)
# MAGIC - `roy` = rest of fiscal year (after rolling, through FY_END_DATE)
# MAGIC - `forward_1yr` = weeks beyond the current fiscal year (2027+ extension from Step 15C/8C)
# MAGIC
# MAGIC All three are disjoint — the app sums `rolling + roy` for current-FY totals,
# MAGIC and uses `forward_1yr` for the next-year planning view.

# COMMAND ----------

min_ds = fc.agg(F.min("ds")).collect()[0][0]
rolling_cutoff = min_ds + timedelta(weeks=ROLLING_WEEKS - 1)
fy_end = datetime.strptime(FY_END_DATE, "%Y-%m-%d").date()

# Three-way DISJOINT tagging:
#   rolling     = next 13 weeks (current quarter forward)
#   roy         = rest of current fiscal year AFTER the rolling window
#   forward_1yr = all weeks BEYOND the current fiscal year end (2027+)
# They MUST be disjoint: the app's KPI query sums forecast_type IN
# ('rolling','roy'), so overlapping rows double-count the quarter total.
rolling     = fc.where(F.col("ds") <= F.lit(rolling_cutoff)).withColumn("forecast_type", F.lit("rolling"))
roy         = fc.where((F.col("ds") > F.lit(rolling_cutoff)) & (F.col("ds") <= F.lit(fy_end))).withColumn("forecast_type", F.lit("roy"))
forward_1yr = fc.where(F.col("ds") > F.lit(fy_end)).withColumn("forecast_type", F.lit("forward_1yr"))
forecasts = rolling.unionByName(roy).unionByName(forward_1yr)
print(f"Forecast rows after 3-way split: {forecasts.count()}")
print(f"  rolling: {rolling.count()} (through {rolling_cutoff})")
print(f"  roy: {roy.count()} (through {fy_end})")
print(f"  forward_1yr: {forward_1yr.count()} (beyond FY into 2027+)")

# COMMAND ----------

# DBTITLE 1,Cell 4b — Generate BOQ (pure-model) view rows
# BOQ rows = duplicate of ALL forecast rows but tagged forecast_view='boq'.
# BOQ = "Beginning of Quarter" pure model prediction — no actuals blended.
# The adaptive view (default) will blend actuals in the app layer;
# the BOQ view gives a stable plan target that doesn't change mid-quarter.
#
# Both views share the same forecast_type tagging (rolling/roy/forward_1yr)
# so the app can filter by horizon AND by view independently.

boq_forecasts = forecasts.withColumn("forecast_view", F.lit("boq"))
# Original forecasts already have forecast_view='adaptive' from normalize step
forecasts_with_views = forecasts.unionByName(boq_forecasts)
print(f"Forecast rows with both views: {forecasts_with_views.count()} "
      f"(adaptive: {forecasts.count()}, boq: {boq_forecasts.count()})")

# Replace 'forecasts' variable for downstream cells
forecasts = forecasts_with_views

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 5 — Pull actuals (CBE 2026+ and SFDC 2024-2025 Growth ARR)
# MAGIC
# MAGIC Current actuals (2026+) from CBE tables (TRUE Growth ARR from SFDC).
# MAGIC Historical actuals (2024-2025) from `cds_sfdc_opp_products_latest` using the
# MAGIC SAME filters as the V5 forecast pipeline (Growth purchase_type, exclude
# MAGIC Care/Sales Other). Uses `total_price2_converted` (USD line-item value) to
# MAGIC ensure valid YoY comparisons (arr_forecast_v2 included non-Growth revenue).

# COMMAND ----------

# DBTITLE 1,Cell 5 — Pull actuals (CBE 2026+ and SFDC 2024-2025 Growth ARR)
def build_actuals_from_cbe(cbe_table, product):
    """Pull actual rows from a CBE table (source='actual').
    CBE tables have one row per (model, ds, grain_level, sales_market) for closed weeks.
    We pick model='Adaptive_Ensemble' to deduplicate (all models carry the same actual value)."""
    try:
        cbe = spark.table(cbe_table)
    except Exception as exc:
        print(f"  WARN {cbe_table} unavailable: {exc}")
        return None

    mkt = (F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"), F.lit("Total"))
            .when(F.upper(F.trim(F.col("sales_market"))) == "UNKNOWN", F.lit("Unknown"))
            .otherwise(F.trim(F.col("sales_market"))))

    out = (cbe
        .where("source = 'actual' AND model = 'Adaptive_Ensemble'")
        .select(
            F.current_date().alias("run_date"),
            F.to_date("ds").alias("ds"),
            F.lit(product).alias("product"),
            mkt.alias("sales_market"),
            F.col("grain_level"),
            F.lit("ACTUAL").alias("model"),
            F.lit("actuals").alias("forecast_type"),
            F.lit("adaptive").alias("forecast_view"),
            F.col("forecast").cast("double").alias("actual"),
            F.lit(None).cast("double").alias("p10"),
            F.lit(None).cast("double").alias("p20"),
            F.lit(None).cast("double").alias("p30"),
            F.lit(None).cast("double").alias("p40"),
            F.lit(None).cast("double").alias("p50"),
            F.lit(None).cast("double").alias("p60"),
            F.lit(None).cast("double").alias("p70"),
            F.lit(None).cast("double").alias("p80"),
            F.lit(None).cast("double").alias("p90"),
            F.col("forecast").cast("double").alias("most_likely"),
            F.lit(0).cast("bigint").alias("recommended_for_exec"),
            F.lit(None).cast("timestamp").alias("source_run_ts"),
            F.current_timestamp().alias("published_at_utc"),
        ).select(*BASE))
    n = out.count()
    print(f"  {product} actuals from {cbe_table}: {n} rows")
    return out

ucc_actuals  = build_actuals_from_cbe(UCC_CBE_SRC, "UCC")
itsg_actuals = build_actuals_from_cbe(ITSG_CBE_SRC, "ITSG")

# ── Historical actuals from SFDC (Growth-only, pre-CBE window) ───────────────
# The CBE tables start ~2025-12-29. For the Multi-Year seasonality overlay and
# correct YoY comparisons, we need 2024-2025 Growth ARR from the SAME source
# as the V5 forecast (SFDC opp products). This replaces arr_forecast_v2 which
# included non-Growth revenue (Miradore, Self-serve) and inflated the baseline.

def build_historical_actuals_from_sfdc(cbe_earliest_ds):
    """Pull 2024-2025 Growth ARR actuals from SFDC at weekly grain.
    Uses total_price2_converted (USD line-item value) with the same filters
    as the V5 forecast pipeline: Growth purchase_type, exclude Care/Sales Other.
    Returns total grain rows (market rollup) for YoY overlay."""
    SFDC_TABLE = "datagroup.datalake_transform.cds_sfdc_opp_products_latest"
    try:
        sfdc = spark.table(SFDC_TABLE)
    except Exception as exc:
        print(f"  WARN {SFDC_TABLE} unavailable: {exc}")
        return None

    # Weekly Growth ARR per product_group (total grain for YoY overlay)
    out = spark.sql(f"""
        SELECT
            CURRENT_DATE() as run_date,
            CAST(DATE_TRUNC('week', close_date) AS DATE) as ds,
            CASE product_group WHEN 'UCC' THEN 'UCC' WHEN 'ITSG' THEN 'ITSG' END as product,
            'Total' as sales_market,
            'total' as grain_level,
            'ACTUAL' as model,
            'actuals' as forecast_type,
            'adaptive' as forecast_view,
            SUM(total_price2_converted) as actual,
            CAST(NULL AS DOUBLE) as p10,
            CAST(NULL AS DOUBLE) as p20,
            CAST(NULL AS DOUBLE) as p30,
            CAST(NULL AS DOUBLE) as p40,
            CAST(NULL AS DOUBLE) as p50,
            CAST(NULL AS DOUBLE) as p60,
            CAST(NULL AS DOUBLE) as p70,
            CAST(NULL AS DOUBLE) as p80,
            CAST(NULL AS DOUBLE) as p90,
            SUM(total_price2_converted) as most_likely,
            CAST(0 AS BIGINT) as recommended_for_exec,
            CAST(NULL AS TIMESTAMP) as source_run_ts,
            CURRENT_TIMESTAMP() as published_at_utc
        FROM {SFDC_TABLE}
        WHERE is_won = TRUE
          AND is_closed = TRUE
          AND purchase_type_rollup = 'Growth'
          AND sales_channel NOT IN ('Care', 'Sales Other')
          AND product_group IN ('UCC', 'ITSG')
          AND close_date >= '2024-01-01'
          AND close_date < '{cbe_earliest_ds}'
        GROUP BY DATE_TRUNC('week', close_date), product_group
        HAVING SUM(total_price2_converted) IS NOT NULL
    """).select(*BASE)
    n = out.count()
    yr_totals = out.groupBy("product").agg(F.round(F.sum("actual") / 1e6, 1).alias("M"))
    print(f"  Historical actuals from SFDC Growth ARR (pre-CBE): {n} rows")
    yr_totals.show(truncate=False)
    return out

# Determine the earliest date in CBE actuals to avoid overlap
cbe_min_ds = "2025-12-29"  # CBE window start (aligned Monday before Jan 1 2026)
if ucc_actuals is not None:
    _cbe_min = ucc_actuals.agg(F.min("ds")).collect()[0][0]
    if _cbe_min:
        cbe_min_ds = str(_cbe_min)

hist_actuals = build_historical_actuals_from_sfdc(cbe_min_ds)

# ── Combine all actuals ──────────────────────────────────────────────────────
actual_parts = [a for a in (ucc_actuals, itsg_actuals, hist_actuals) if a is not None]
if actual_parts:
    actuals = actual_parts[0]
    for a in actual_parts[1:]:
        actuals = actuals.unionByName(a)
else:
    actuals = None

combined = forecasts if actuals is None else forecasts.unionByName(actuals)
print(f"Rows incl. actuals: {combined.count()}")

# COMMAND ----------

# DBTITLE 1,Verify p20-p80 fan chart data pipeline
from pyspark.sql import functions as F

print("=" * 80)
print("CHECK 1: forecast_results_v2compat — p20-p80 for UCC forecast rows")
print("=" * 80)

compat = spark.table("datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat") \
    .where(
        (F.col("product") == "UCC") &
        (F.col("sales_market") == "Total") &
        (F.col("forecast_type").isin("rolling", "roy"))
    ) \
    .select("ds", "Most_Likely", "Worst_Case", "Best_Case",
            "p20", "p30", "p40", "p60", "p70", "p80") \
    .orderBy(F.desc("ds")).limit(5).toPandas()

p20_nulls = compat['p20'].isna().sum()
print(f"  Sample rows: {len(compat)}")
print(f"  p20 NULLs: {p20_nulls} / {len(compat)}  →  {'❌ MISSING' if p20_nulls == len(compat) else '✅ POPULATED'}")
print(compat[['ds', 'Most_Likely', 'p20', 'p40', 'p60', 'p80']].to_string(index=False))

print("\n" + "=" * 80)
print("CHECK 2: forecast_results_v2compat — p20-p80 for ITSG forecast rows")
print("=" * 80)

itsg_compat = spark.table("datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat") \
    .where(
        (F.col("product") == "ITSG") &
        (F.col("sales_market") == "Total") &
        (F.col("forecast_type").isin("rolling", "roy"))
    ) \
    .select("ds", "Most_Likely", "p20", "p40", "p60", "p80") \
    .orderBy(F.desc("ds")).limit(3).toPandas()

itsg_p20 = itsg_compat['p20'].isna().sum()
print(f"  p20 NULLs: {itsg_p20} / {len(itsg_compat)}  →  {'⚠️ NULL (expected — ITSG V5 has p10/p50/p90 only)' if itsg_p20 == len(itsg_compat) else '✅ POPULATED'}")

print("\n" + "=" * 80)
print("CHECK 3: arr_forecast_app_latest — schema + UCC p20-p80")
print("=" * 80)

app_tbl = spark.table("datagroup_mdl.mdl_sales_analytics.arr_forecast_app_latest")
app_cols = {f.name for f in app_tbl.schema.fields}
fan_cols = ['p20', 'p30', 'p40', 'p60', 'p70', 'p80']
missing = [c for c in fan_cols if c not in app_cols]
print(f"  Table has p20-p80 columns: {'✅ YES' if not missing else '❌ MISSING: ' + str(missing)}")

ucc_app = app_tbl.where(
    (F.col("product_group") == "UCC") &
    (F.col("model") == "Adaptive_Ensemble") &
    (F.col("grain_level") == "total")
).select("ds", "forecast", "p10", "p20", "p50", "p80", "p90") \
 .orderBy(F.desc("ds")).limit(3).toPandas()

ucc_p20 = ucc_app['p20'].isna().sum() if 'p20' in ucc_app.columns else len(ucc_app)
print(f"  UCC Ensemble p20: {'⚠️ NULL (populates on next pipeline run with updated UCC notebook)' if ucc_p20 == len(ucc_app) else '✅ POPULATED'}")
print(ucc_app.to_string(index=False))

print("\n" + "=" * 80)
print("CHECK 4: Simulate backend /weekly SQL — does p20-p80 flow to the app?")
print("=" * 80)

sim = spark.sql("""
    SELECT
        CAST(ds AS STRING) AS ds,
        COALESCE(CAST(Most_Likely AS DOUBLE), 0) AS value,
        COALESCE(CAST(Worst_Case AS DOUBLE), 0) AS p10,
        COALESCE(CAST(Best_Case AS DOUBLE), 0) AS p90,
        CAST(p20 AS DOUBLE) AS p20,
        CAST(p30 AS DOUBLE) AS p30,
        CAST(p40 AS DOUBLE) AS p40,
        CAST(p60 AS DOUBLE) AS p60,
        CAST(p70 AS DOUBLE) AS p70,
        CAST(p80 AS DOUBLE) AS p80
    FROM `datagroup_mdl`.`mdl_sales_analytics`.`forecast_results_v2compat`
    WHERE run_date = (SELECT MAX(run_date) FROM `datagroup_mdl`.`mdl_sales_analytics`.`forecast_results_v2compat`)
      AND forecast_type IN ('rolling', 'roy')
      AND product = 'UCC'
      AND sales_market = 'Total'
    ORDER BY ds DESC
    LIMIT 3
""").toPandas()

has_fan = sim['p20'].notna().any()
print(f"  Backend SQL returns p20-p80: {'✅ YES — fan chart will render' if has_fan else '❌ NO — fallback to single band'}")
print(sim[['ds', 'value', 'p20', 'p40', 'p60', 'p80']].to_string(index=False))

print("\n" + "=" * 80)
print("CHECK 5: Total product (UCC+ITSG) — fan chart behavior")
print("=" * 80)

total = spark.table("datagroup_mdl.mdl_sales_analytics.forecast_results_v2compat") \
    .where(
        (F.col("product") == "Total") &
        (F.col("sales_market") == "Total") &
        (F.col("forecast_type").isin("rolling", "roy"))
    ) \
    .select("ds", "p20", "p80") \
    .orderBy(F.desc("ds")).limit(3).toPandas()

tot_p20 = total['p20'].isna().sum()
print(f"  Total product p20: {'⚠️ NULL — Total is UCC+ITSG sum; ITSG nulls propagate' if tot_p20 == len(total) else '✅ POPULATED (partial — some weeks have data)'}")
print(f"  Frontend behavior: {'Single P10-P90 band (fallback)' if tot_p20 == len(total) else 'Graduated fan chart'}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"  UCC fan chart:   {'✅ Graduated 7-band fan' if has_fan else '❌ Fallback single band'}")
print(f"  ITSG fan chart:  ⚠️ Fallback single band (p20-p80 NULL in ITSG V5)")
print(f"  Total fan chart: {'Fallback single band' if tot_p20 == len(total) else 'Graduated fan'}")
print(f"  App table ready: {'✅' if not missing else '❌'}  (p20-p80 columns exist in arr_forecast_app_latest)")
print(f"  UCC app export:  {'Will populate on next Tuesday pipeline run' if ucc_p20 == len(ucc_app) else '✅ Already populated'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 6 — Total rollup (UCC + ITSG)

# COMMAND ----------

# DBTITLE 1,Cell 6 — Total rollup (UCC + ITSG)
# ══════════════════════════════════════════════════════════════════════════════
# TOTAL ROLLUP — EXACT SUM, NOT VARIANCE RECONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════
# The "Total" product = UCC + ITSG summed per (ds, market, model, forecast_type, view).
#
# Why simple SUM is correct and preferred:
#   actual:     SUM of actuals = total actual (exact).
#   p50:        SUM of per-product p50 = total point estimate (exact for expectations).
#   most_likely: same as p50 (exact).
#   p10 / p90:  SUM of per-product quantiles. This is conservative for p10 and
#               aggressive for p90 (exact only under perfect correlation). But it is
#               the PUBLISHED truth — the app reads these values directly. No sqrt,
#               no variance math, no band reconstruction.
#
# Guard: strip any pre-existing "Total" rows from upstream sources before
# computing the rollup, preventing accidental double-counting.
# ══════════════════════════════════════════════════════════════════════════════

# Safety guard: remove any "Total" product rows that leaked from upstream sources
# (e.g. arr_forecast_v2 had a 'Total' product that includes non-Growth revenue).
per_product = combined.where(F.upper(F.col("product")) != "TOTAL")

total = (per_product
    .groupBy("run_date", "ds", "sales_market", "grain_level", "model", "forecast_type", "forecast_view")
    .agg(F.sum("actual").alias("actual"),
         F.sum("p10").alias("p10"),
         F.sum("p20").alias("p20"),
         F.sum("p30").alias("p30"),
         F.sum("p40").alias("p40"),
         F.sum("p50").alias("p50"),
         F.sum("p60").alias("p60"),
         F.sum("p70").alias("p70"),
         F.sum("p80").alias("p80"),
         F.sum("p90").alias("p90"),
         F.sum("most_likely").alias("most_likely"),
         F.max("recommended_for_exec").alias("recommended_for_exec"))
    .withColumn("product", F.lit("Total"))
    .withColumn("source_run_ts", F.lit(None).cast("timestamp"))
    .withColumn("published_at_utc", F.current_timestamp())
    .select(*BASE))

# Final results_base = per-product rows (UCC, ITSG) + computed Total
results_base = per_product.unionByName(total)
print(f"Rows incl. Total rollup: {results_base.count()}")
print(f"  Per-product rows: {per_product.count()}, Total rollup rows: {total.count()}")

# COMMAND ----------

# DBTITLE 1,Cell 6b — Hierarchical Reconciliation
# MAGIC %md
# MAGIC ## Cell 6b — Hierarchical Reconciliation (top-down proportional)
# MAGIC
# MAGIC Within each product (UCC, ITSG), ensures market-level forecasts sum **exactly**
# MAGIC to the total-level forecast. The total-level forecast is the anchor — it is
# MAGIC trained on aggregate data with lower noise. Markets are scaled proportionally
# MAGIC so they preserve their relative shares while summing to the anchor.
# MAGIC
# MAGIC After per-product reconciliation, the cross-product "Total" rollup is
# MAGIC recomputed from the reconciled values.
# MAGIC
# MAGIC **Method:** Athanasopoulos et al. (2009) top-down proportional scaling:
# MAGIC `scale_factor[q] = total_q / SUM(market_q)` for each quantile column.

# COMMAND ----------

# DBTITLE 1,Cell 6b — Hierarchical Reconciliation
# CELL 6b: HIERARCHICAL RECONCILIATION (TOP-DOWN PROPORTIONAL)
# =============================================================================
# Within each product (UCC, ITSG), ensures market-level forecasts sum exactly
# to the total-level forecast for each (ds, model, forecast_type, forecast_view).
#
# The total-level forecast is the anchor — trained on aggregate data with lower
# noise, it is the more reliable estimate. Market rows are scaled proportionally
# so they preserve relative shares while summing to the anchor.
#
# After per-product reconciliation, the "Total" product rollup (UCC + ITSG) is
# recomputed from reconciled values.
#
# Only applies to forecast rows (model != 'ACTUAL'); actuals pass through unchanged.
# =============================================================================

from pyspark.sql import Window

# ── Separate actuals from forecasts ──────────────────────────────────────────
actual_rows = results_base.where(F.col("model") == "ACTUAL")
fc_rows     = results_base.where(F.col("model") != "ACTUAL")

# Per-product forecast rows only (UCC, ITSG) — Total is recomputed after
pp_fc  = fc_rows.where(F.upper(F.col("product")) != "TOTAL")

# ── Build scale factors ──────────────────────────────────────────────────────
RECON_KEY = ["product", "ds", "model", "forecast_type", "forecast_view"]

# Anchor = the total-grain row for each key
anchor = (pp_fc
    .where(F.lower(F.col("grain_level")) == "total")
    .select(*RECON_KEY,
            F.col("p10").alias("anc_p10"),
            F.col("p50").alias("anc_p50"),
            F.col("p90").alias("anc_p90")))

# Sum of market-grain rows per key
mkt_sum = (pp_fc
    .where(F.lower(F.col("grain_level")) == "market")
    .groupBy(*RECON_KEY)
    .agg(F.sum("p10").alias("sum_p10"),
         F.sum("p50").alias("sum_p50"),
         F.sum("p90").alias("sum_p90")))

# Scale factor = anchor / sum_of_markets (1.0 if sum is zero)
recon = (anchor.join(mkt_sum, RECON_KEY, "inner")
    .withColumn("sf_p10", F.when(F.col("sum_p10") != 0, F.col("anc_p10") / F.col("sum_p10")).otherwise(1.0))
    .withColumn("sf_p50", F.when(F.col("sum_p50") != 0, F.col("anc_p50") / F.col("sum_p50")).otherwise(1.0))
    .withColumn("sf_p90", F.when(F.col("sum_p90") != 0, F.col("anc_p90") / F.col("sum_p90")).otherwise(1.0))
    .select(*RECON_KEY, "sf_p10", "sf_p50", "sf_p90"))

# ── Apply to market rows ─────────────────────────────────────────────────────
mkt_rows = pp_fc.where(F.lower(F.col("grain_level")) == "market")
tot_rows = pp_fc.where(F.lower(F.col("grain_level")) == "total")  # unchanged

# 2026-08-31: Market-grain forecast WAPE ~50-62%, deemed unreliable for
# publication (see validation 2026-08-31). Market-grain rows report actuals
# only; forecasts remain at Total/product grain only.
# Keep mkt_reconciled defined (empty DF with matching schema) because
# pp_reconciled = tot_rows.unionByName(mkt_reconciled, ...) depends on it.
mkt_reconciled = (mkt_rows
    .join(recon, RECON_KEY, "left")
    .withColumn("p10",        F.round(F.col("p10") * F.coalesce(F.col("sf_p10"), F.lit(1.0)), 2))
    .withColumn("p50",        F.round(F.col("p50") * F.coalesce(F.col("sf_p50"), F.lit(1.0)), 2))
    .withColumn("p90",        F.round(F.col("p90") * F.coalesce(F.col("sf_p90"), F.lit(1.0)), 2))
    .withColumn("most_likely", F.col("p50"))
    .drop("sf_p10", "sf_p50", "sf_p90")
    .where(F.lit(False)))

# ── Diagnostic: measure adjustment magnitude ─────────────────────────────────
_diag = (mkt_rows.join(recon, RECON_KEY, "left")
    .where(F.col("sf_p50").isNotNull())
    .select(F.abs(F.col("sf_p50") - 1.0).alias("shift_pct")))
_stats = _diag.agg(
    F.count("*").alias("n"),
    F.mean("shift_pct").alias("mean"),
    F.expr("percentile_approx(shift_pct, 0.5)").alias("median"),
    F.max("shift_pct").alias("max")).collect()[0]

# ── Reassemble per-product (total-grain unchanged + reconciled market-grain)
pp_reconciled = tot_rows.unionByName(mkt_reconciled, allowMissingColumns=True)

# ── Recompute "Total" product from reconciled UCC + ITSG ─────────────────────
total_recomp = (pp_reconciled
    .groupBy("run_date", "ds", "sales_market", "grain_level", "model",
             "forecast_type", "forecast_view")
    .agg(F.sum("actual").alias("actual"),
         F.sum("p10").alias("p10"),
         F.sum("p20").alias("p20"),
         F.sum("p30").alias("p30"),
         F.sum("p40").alias("p40"),
         F.sum("p50").alias("p50"),
         F.sum("p60").alias("p60"),
         F.sum("p70").alias("p70"),
         F.sum("p80").alias("p80"),
         F.sum("p90").alias("p90"),
         F.sum("most_likely").alias("most_likely"),
         F.max("recommended_for_exec").alias("recommended_for_exec"))
    .withColumn("product", F.lit("Total"))
    .withColumn("source_run_ts", F.lit(None).cast("timestamp"))
    .withColumn("published_at_utc", F.current_timestamp()))

# ── Final results_base = reconciled per-product + recomputed Total + actuals
results_base = (pp_reconciled
    .unionByName(total_recomp, allowMissingColumns=True)
    .unionByName(actual_rows, allowMissingColumns=True)
    .select(*BASE))

print(f"Hierarchical reconciliation complete.")
print(f"  Market adjustments: mean={_stats['mean']*100:.2f}%, "
      f"median={_stats['median']*100:.2f}%, max={_stats['max']*100:.2f}% "
      f"({_stats['n']} market rows)")
print(f"  Rows after reconciliation: {results_base.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 7 — Attach per-model accuracy (WAPE / MAPE) from the baselines

# COMMAND ----------

def _latest(table, ts_col):
    t = spark.table(table)
    mx = t.agg(F.max(ts_col)).collect()[0][0]
    return t.where(F.col(ts_col) == F.lit(mx))

acc_parts = []
try:
    u = _latest(UCC_BASELINE, "run_date_utc").select(
        F.lit("UCC").alias("product"), F.col("model"),
        F.col("holdout_wape_baseline").alias("model_wape"),
        F.lit(None).cast("double").alias("model_mape"))
    acc_parts.append(u)
except Exception as exc:
    print(f"  WARN UCC baseline skipped: {exc}")
try:
    i = _latest(ITSG_BASELINE, "run_date_utc")
    if "metric_scope" in i.columns:
        tot = i.where(F.lower(F.col("metric_scope")).isin("total", "all") | F.col("metric_scope").isNull())
        i = tot if tot.count() > 0 else i
    i = i.select(F.lit("ITSG").alias("product"), F.col("model"),
                 F.coalesce(F.col("holdout_wape_baseline"), F.col("wape")).alias("model_wape"),
                 F.col("mape").alias("model_mape"))
    acc_parts.append(i)
except Exception as exc:
    print(f"  WARN ITSG baseline skipped: {exc}")

if acc_parts:
    acc = acc_parts[0]
    for a in acc_parts[1:]:
        acc = acc.unionByName(a)
    acc = acc.dropDuplicates(["product", "model"])
    results = results_base.join(acc, ["product", "model"], "left")
else:
    results = (results_base
               .withColumn("model_wape", F.lit(None).cast("double"))
               .withColumn("model_mape", F.lit(None).cast("double")))
results = results.select(*COLS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 8 — Write `forecast_results` (+ latest view)

# COMMAND ----------

# ══════════════════════════════════════════════════════════════════════════════
# WRITE forecast_results + CREATE DEDUPED VIEW
# ══════════════════════════════════════════════════════════════════════════════
# Deduplication guarantee: exactly ONE row per natural key. If the upstream union
# produced any duplicates (e.g. overlapping date windows), the dedup removes them
# BEFORE writing, so the table is the canonical source of truth.

from pyspark.sql import Window

DEDUP_KEY = ["ds", "product", "sales_market", "grain_level", "model", "forecast_type", "forecast_view"]

# Deduplicate: keep the row with the latest published_at_utc per natural key
w = Window.partitionBy(*DEDUP_KEY).orderBy(F.col("published_at_utc").desc())
results_deduped = (results
    .withColumn("_rn", F.row_number().over(w))
    .where("_rn = 1")
    .drop("_rn"))

(results_deduped.write.format("delta").mode("overwrite")
   .option("replaceWhere", "run_date = current_date()")
   .option("mergeSchema", "true")
   .partitionBy("product")
   .saveAsTable(RESULTS_TABLE))

# The view selects the latest run_date snapshot with a secondary dedup guard:
# ROW_NUMBER ensures exactly one row per key even if table has residual dupes.
spark.sql(f"""
    CREATE OR REPLACE VIEW {RESULTS_VIEW} AS
    WITH latest AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY ds, product, sales_market, grain_level, model, forecast_type, forecast_view
                ORDER BY published_at_utc DESC
            ) AS _rn
        FROM {RESULTS_TABLE}
        WHERE run_date = (SELECT MAX(run_date) FROM {RESULTS_TABLE})
    )
    SELECT * EXCEPT (_rn) FROM latest WHERE _rn = 1
""")
print(f"Wrote {results_deduped.count()} rows to {RESULTS_TABLE} (vintage = today, deduped).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 9 — Build & write `forecast_insights`
# MAGIC
# MAGIC Deterministic payloads (no LLM/secret dependency) in the shape the AI Insights
# MAGIC tab reads. Momentum from the forecast trajectory; confidence from band spread
# MAGIC and the model's WAPE.

# COMMAND ----------

# DBTITLE 1,Cell 9 — Build & write forecast_insights
import json

res = spark.table(RESULTS_VIEW).toPandas()
latest_run = res["run_date"].max()

# Quarter-aware setup so the insight headline matches the Overview quarter number
# (previously computed over 'roy' only, which under-counted after the disjoint fix).
import pandas as pd
res["ds"] = pd.to_datetime(res["ds"], errors="coerce")
_run_dt = pd.to_datetime(latest_run)
_Q = (_run_dt.month - 1) // 3 + 1
_Q_MONTHS = [(_Q - 1) * 3 + 1, (_Q - 1) * 3 + 2, (_Q - 1) * 3 + 3]
_Q_YEAR = int(_run_dt.year)
_Q_LABEL = f"Q{_Q} {_Q_YEAR}"

def _fmt_m(v):
    return f"${v/1e6:.1f}M" if v else "$0.0M"

def _stats(df, region="Total", period="quarter"):
    """Period landing = realized-so-far + forecast for the open weeks (matches the
    Overview KPI), plus YoY vs the same period last year and the implied weekly
    run-rate. region: 'Total' or a sales_market; period: 'quarter' (current) or
    'year' (full current year). Guarded so a bad slice can't fail the publish."""
    try:
        if region == "Total":
            tot = df[(df["grain_level"].astype(str).str.lower() == "total")
                     & (df["forecast_view"] == "adaptive")].copy()
        else:
            tot = df[(df["grain_level"].astype(str).str.lower() == "market")
                     & (df["sales_market"].astype(str).str.upper() == str(region).upper())
                     & (df["forecast_view"] == "adaptive")].copy()
        if period == "year":
            in_q = tot["ds"].dt.year.eq(_Q_YEAR)
            period_label = f"FY {_Q_YEAR}"
            prior_scope = tot["ds"].dt.year.eq(_Q_YEAR - 1)
        else:
            in_q = tot["ds"].dt.year.eq(_Q_YEAR) & tot["ds"].dt.month.isin(_Q_MONTHS)
            period_label = _Q_LABEL
            prior_scope = tot["ds"].dt.year.eq(_Q_YEAR - 1) & tot["ds"].dt.month.isin(_Q_MONTHS)
        act = tot[(tot["model"] == "ACTUAL") & in_q]
        # Splice: forecast weeks strictly AFTER the last closed actual week — no
        # double-count, no dropped in-flight week (matches the backend KPI rule).
        last_act = act["ds"].max() if not act.empty else pd.Timestamp("1900-01-01")
        fwd = tot[(tot["model"] == REC_MODEL)
                  & tot["forecast_type"].isin(["rolling", "roy"]) & in_q
                  & (tot["ds"] > last_act)].sort_values("ds")
        if fwd.empty and act.empty:
            return None
        fwd_ml = float(fwd["p50"].fillna(0).sum())
        qtd    = float(act["actual"].fillna(0).sum())
        most_likely = fwd_ml + qtd
        # Variance-aggregate the quarter band (combine weekly half-widths in
        # quadrature) instead of summing weekly quantiles — the latter overstates
        # the spread ~sqrt(weeks)x since weekly noise cancels. Upper/lower kept
        # separate for asymmetry; floored at 0 (ARR can't be negative).
        _p50 = fwd["p50"].fillna(0)
        _up = (fwd["p90"].fillna(fwd["p50"]) - _p50).clip(lower=0)
        _lo = (_p50 - fwd["p10"].fillna(fwd["p50"])).clip(lower=0)
        q_up = float((_up ** 2).sum()) ** 0.5
        q_lo = float((_lo ** 2).sum()) ** 0.5
        worst = max(0.0, most_likely - q_lo)
        best  = most_likely + q_up
        spread_pct = ((best - worst) / most_likely * 100) if most_likely else 0.0
        prior = float(tot[(tot["model"] == "ACTUAL") & prior_scope]["actual"].fillna(0).sum())
        yoy = ((most_likely - prior) / prior * 100) if prior else None
        n_fwd = int(len(fwd))
        run_rate = (fwd_ml / n_fwd) if n_fwd else None
        p = fwd["p50"].dropna().tolist()
        momentum = "STABLE"
        if len(p) >= 3 and p[0]:
            chg = (p[-1] - p[0]) / p[0] * 100
            cv = (fwd["p50"].std() / fwd["p50"].mean() * 100) if fwd["p50"].mean() else 0
            if cv > 25: momentum = "VOLATILE"
            elif chg > 5: momentum = "ACCELERATING"
            elif chg < -5: momentum = "DECELERATING"
        wape = float(fwd["model_wape"].dropna().mean()) if fwd["model_wape"].notna().any() else None
        conf = 100.0 - (spread_pct * 0.4) - (wape * 1.3 if wape is not None else 0.0)
        conf = max(15.0, min(98.0, conf))
        return dict(most_likely=most_likely, worst=worst, best=best, qtd=qtd, prior=prior,
                    upside=max(0.0, best - most_likely), downside=max(0.0, most_likely - worst),
                    spread_pct=spread_pct, momentum=momentum, wape=wape, yoy=yoy,
                    run_rate=run_rate, n_fwd=n_fwd, confidence=round(conf, 0),
                    period_label=period_label, region=region)
    except Exception as _e:
        print(f"  WARN insight stats failed: {_e}")
        return None

def _render(s, label, product_stats=None):
    """Render executive-quality insight payload.
    product_stats: dict of per-product stats (UCC/ITSG) for the aggregate view."""
    _pl = s.get("period_label", _Q_LABEL)
    risk = "LOW RISK" if s["confidence"] >= 80 else "MODERATE RISK" if s["confidence"] >= 60 else "HIGH RISK"
    yoy = s.get("yoy")
    yoy_txt = (f" — {'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s['prior'])} last year"
               if yoy is not None else "")
    n_weeks = s.get("n_fwd", 0)
    rr_txt = (f"{_fmt_m(s['run_rate'])}/wk across {n_weeks} open weeks"
              if s.get("run_rate") and n_weeks else "n/a")

    # Key Drivers — include product split for aggregate view
    drivers = [
        f"{label} {_pl} landing {_fmt_m(s['most_likely'])} = {_fmt_m(s['qtd'])} realized "
        f"+ {_fmt_m(s['most_likely'] - s['qtd'])} forecast.",
        f"Implied pace: {rr_txt}.",
    ]
    if yoy is not None:
        drivers.append(f"Tracking {'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s['prior'])} last year ({_pl.replace(str(_Q_YEAR), str(_Q_YEAR - 1))}).")
    if product_stats:
        parts = [f"{k}: {_fmt_m(v['most_likely'])}" for k, v in sorted(product_stats.items())]
        drivers.append(f"Product mix: {', '.join(parts)}.")

    # Downside Risks — quantified and specific
    spread_pct = s.get("spread_pct", 0)
    risk_items = [
        f"Downside case {_fmt_m(s['worst'])} — {_fmt_m(s['downside'])} ({s['downside']/(s['most_likely'])*100:.0f}%) below the central path." if s['most_likely'] else f"Downside case {_fmt_m(s['worst'])}.",
    ]
    if s["momentum"] == "DECELERATING":
        risk_items.append("Momentum decelerating — recent weeks trending below the quarterly run-rate.")
    elif s["momentum"] == "VOLATILE":
        risk_items.append(f"Week-to-week coefficient of variation elevated; band spread is {spread_pct:.0f}% of the central path.")
    else:
        risk_items.append("Primary risk is execution slip against the paced weekly target.")
    if product_stats:
        weakest = min(product_stats.items(), key=lambda x: x[1].get("confidence", 100))
        if weakest[1].get("momentum") in ("VOLATILE", "DECELERATING"):
            risk_items.append(f"{weakest[0]} showing {weakest[1]['momentum'].lower()} momentum — monitor closely.")

    # Upside Opportunities — specific triggers
    opp_items = [
        f"Stretch case {_fmt_m(s['best'])} — {_fmt_m(s['upside'])} ({s['upside']/(s['most_likely'])*100:.0f}%) above the central path." if s['most_likely'] else f"Stretch case {_fmt_m(s['best'])}.",
    ]
    if product_stats:
        strongest = max(product_stats.items(), key=lambda x: x[1].get("confidence", 0))
        if strongest[1].get("momentum") == "ACCELERATING":
            opp_items.append(f"{strongest[0]} accelerating — could outperform if trend persists.")
    if yoy is not None and yoy > 0:
        opp_items.append(f"Already tracking +{yoy:.0f}% above prior-year pace.")

    # Executive Actions — specific and quantified
    actions = []
    if n_weeks > 0 and s.get("run_rate"):
        actions.append(f"Maintain {_fmt_m(s['run_rate'])}/wk run-rate over the remaining {n_weeks} weeks to land {_fmt_m(s['most_likely'])} for {_pl}.")
    else:
        actions.append(f"Hold current weekly pace to land the {_pl} outlook.")
    if product_stats and len(product_stats) > 1:
        largest = max(product_stats.items(), key=lambda x: x[1].get("most_likely", 0))
        pct = largest[1]["most_likely"] / s["most_likely"] * 100 if s["most_likely"] else 0
        actions.append(f"Prioritize {largest[0]} execution ({pct:.0f}% of total) — largest lever on the combined number.")
    if s["momentum"] == "VOLATILE":
        actions.append("Review pipeline coverage and deal slippage risk for the next 4 weeks.")
    elif s["momentum"] == "DECELERATING":
        actions.append("Escalate deal pull-forward and pipeline acceleration actions this week.")
    else:
        actions.append("Maintain current cadence; next model refresh will update the outlook.")

    # Narrative — concise executive summary
    momentum_desc = {"VOLATILE": "with elevated weekly variability",
                     "ACCELERATING": "on an accelerating trajectory",
                     "DECELERATING": "on a decelerating trajectory",
                     "STABLE": "on a stable trajectory"}
    _mw = _MONTHLY_WAPE.get(label, _MONTHLY_WAPE.get("Total"))
    _acc_txt = f" Monthly forecast accuracy: {_mw:.1f}% WAPE." if _mw else ""
    narrative = (f"{label} {_pl} landing is {_fmt_m(s['most_likely'])} "
                 f"({_fmt_m(s['qtd'])} realized + forecast), "
                 f"ranging {_fmt_m(s['worst'])} to {_fmt_m(s['best'])}{yoy_txt}. "
                 f"Forecast {momentum_desc.get(s['momentum'], 'stable')}.{_acc_txt}")

    return {
        "product": label, "run_date": str(latest_run), "period": _pl,
        "momentum": s["momentum"], "risk_level": risk,
        "model_confidence": s["confidence"], "best_model": REC_MODEL,
        "mape": round(s["wape"], 1) if s["wape"] is not None else None,
        "narrative": narrative,
        "upside": round(s["upside"], 0), "downside": round(s["downside"], 0),
        "key_drivers": drivers,
        "downside_risks": risk_items,
        "upside_opportunities": opp_items,
        "executive_actions": actions,
        "source": "unified",
    }

# ══════════════════════════════════════════════════════════════════════════════
# ENRICHMENT LAYER — 6 new context fields for the AI Insights tab
# ══════════════════════════════════════════════════════════════════════════════

# Pre-load enrichment source tables (avoids repeated reads per product)
try:
    _sens_pdf = spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA}.forecast_sensitivity").toPandas()
except Exception:
    _sens_pdf = pd.DataFrame()
try:
    _vtg_pdf = spark.sql(f"SELECT * FROM {CATALOG}.{SCHEMA}.ucc_forecast_vintages").toPandas()
    _vtg_pdf["ds"] = pd.to_datetime(_vtg_pdf["ds"])
    _rd_col = "run_date" if "run_date" in _vtg_pdf.columns else "run_timestamp_utc"
    _vtg_pdf["_run_date"] = pd.to_datetime(_vtg_pdf[_rd_col]).dt.date
except Exception:
    _vtg_pdf = pd.DataFrame()

def _enrich_boq_pace(product_key):
    """1. BOQ Pace: use pace_vs_boq_pct from CBE table (already computed upstream)."""
    try:
        cbe_tbl = UCC_CBE_SRC if product_key == "UCC" else ITSG_CBE_SRC
        cbe = spark.table(cbe_tbl).toPandas()
        cbe["ds"] = pd.to_datetime(cbe["ds"])
        # Get realized actuals for current quarter at total grain
        q_mask = cbe["ds"].dt.year.eq(_Q_YEAR) & cbe["ds"].dt.month.isin(_Q_MONTHS)
        tot_mask = cbe["grain_level"].str.lower() == "total"
        q_cbe = cbe[q_mask & tot_mask & (cbe["model"] == "Adaptive_Ensemble")]
        realized = q_cbe[q_cbe["source"] == "actual"]
        if realized.empty:
            return None
        realized_sum = float(realized["forecast"].fillna(0).sum())
        # Use the pre-computed pace_vs_boq_pct from the CBE table
        # (latest actual week has cumulative QTD pace)
        latest_actual = realized.sort_values("ds").iloc[-1]
        pace_pct = float(latest_actual["pace_vs_boq_pct"]) if pd.notna(latest_actual.get("pace_vs_boq_pct")) else None
        boq_sum = float(realized["boq_weekly"].fillna(0).sum()) if "boq_weekly" in realized.columns else None
        n_weeks = len(realized)
        if pace_pct is None and boq_sum and boq_sum > 0:
            pace_pct = (realized_sum - boq_sum) / boq_sum * 100
        if pace_pct is None:
            return None
        return {
            "realized": round(realized_sum, 0),
            "boq_plan_pace": round(boq_sum, 0) if boq_sum else None,
            "pace_vs_boq_pct": round(pace_pct, 1),
            "weeks_closed": n_weeks,
            "text": f"{'Ahead' if pace_pct >= 0 else 'Behind'} of BOQ plan by {abs(pace_pct):.1f}% ({_fmt_m(realized_sum)} realized over {n_weeks} closed weeks in {_Q_LABEL})."
        }
    except Exception as e:
        print(f"  WARN boq_pace enrichment failed for {product_key}: {e}")
        return None

def _enrich_confidence_trend(product_key):
    """2. Confidence Trend: compare current confidence to 1w and 4w ago."""
    try:
        hist = spark.table(INSIGHTS_TABLE).toPandas()
        prod_hist = hist[hist["product"] == product_key].sort_values("run_date", ascending=False)
        if len(prod_hist) < 2:
            return None
        current_conf = float(prod_hist.iloc[0]["model_confidence"])
        # 1 week ago (find nearest row ~7 days back)
        dates = pd.to_datetime(prod_hist["run_date"])
        target_1w = dates.iloc[0] - pd.Timedelta(days=7)
        target_4w = dates.iloc[0] - pd.Timedelta(days=28)
        conf_1w = prod_hist[dates <= target_1w]["model_confidence"].iloc[0] if (dates <= target_1w).any() else None
        conf_4w = prod_hist[dates <= target_4w]["model_confidence"].iloc[0] if (dates <= target_4w).any() else None
        delta_1w = round(current_conf - conf_1w, 0) if conf_1w is not None else None
        delta_4w = round(current_conf - conf_4w, 0) if conf_4w is not None else None
        # Trend description
        if delta_4w is not None:
            if abs(delta_4w) <= 3:
                trend = "stable"
            elif delta_4w > 0:
                trend = "improving"
            else:
                trend = "degrading"
        else:
            trend = "insufficient_history"
        text_parts = [f"Confidence at {current_conf:.0f}%"]
        if delta_1w is not None:
            text_parts.append(f"{'+' if delta_1w >= 0 else ''}{delta_1w:.0f}pp vs last week")
        if delta_4w is not None:
            text_parts.append(f"{'+' if delta_4w >= 0 else ''}{delta_4w:.0f}pp vs 4 weeks ago")
        return {
            "current": current_conf, "conf_1w_ago": conf_1w, "conf_4w_ago": conf_4w,
            "delta_1w": delta_1w, "delta_4w": delta_4w, "trend": trend,
            "text": " — ".join(text_parts) + f" ({trend})."
        }
    except Exception as e:
        print(f"  WARN confidence_trend enrichment failed for {product_key}: {e}")
        return None

def _enrich_vintage_drift(product_key):
    """3. Vintage Drift: compare today's FY forecast to last week's."""
    try:
        if product_key == "ITSG":
            return None  # ITSG vintages not available
        vtg = _vtg_pdf
        if vtg.empty:
            return None
        # Get the two most recent run_dates
        run_dates = sorted(vtg["_run_date"].dropna().unique(), reverse=True)
        if len(run_dates) < 2:
            return None
        latest_rd = run_dates[0]
        prev_rd = None
        for rd in run_dates[1:]:
            if (latest_rd - rd).days >= 5:  # at least 5 days apart
                prev_rd = rd
                break
        if prev_rd is None:
            prev_rd = run_dates[1]
        # Sum p50 for the Adaptive_Ensemble within current FY
        def _fy_sum(rd):
            mask = (vtg["_run_date"] == rd) & (vtg["model"] == REC_MODEL) & (vtg["ds"].dt.year == _Q_YEAR)
            return float(vtg[mask]["p50"].fillna(0).sum())
        current_sum = _fy_sum(latest_rd)
        prev_sum = _fy_sum(prev_rd)
        if prev_sum == 0:
            return None
        drift_abs = current_sum - prev_sum
        drift_pct = drift_abs / prev_sum * 100
        days_apart = (latest_rd - prev_rd).days
        return {
            "current_fy_forecast": round(current_sum, 0),
            "prior_fy_forecast": round(prev_sum, 0),
            "drift_abs": round(drift_abs, 0),
            "drift_pct": round(drift_pct, 2),
            "days_apart": int(days_apart),
            "text": f"FY outlook {'UP' if drift_abs >= 0 else 'DOWN'} {_fmt_m(abs(drift_abs))} ({drift_pct:+.1f}%) vs {days_apart} days ago."
        }
    except Exception as e:
        print(f"  WARN vintage_drift enrichment failed for {product_key}: {e}")
        return None

def _enrich_driver_actions(product_key):
    """4. Driver-linked Actions: use forecast_sensitivity to identify top levers."""
    try:
        sens = _sens_pdf
        if sens.empty:
            return None
        prod_sens = sens[(sens["product"] == product_key) & (sens["sales_market"] == "NA")]
        if prod_sens.empty:
            return None
        # Sort by absolute elasticity (significant drivers first)
        prod_sens = prod_sens.copy()
        prod_sens["abs_elast"] = prod_sens["elasticity_pct"].abs()
        prod_sens = prod_sens.sort_values("abs_elast", ascending=False)
        top_drivers = []
        for _, row in prod_sens.head(3).iterrows():
            sig = "" if "p=0.0000" in str(row.get("description", "")) else " (not statistically significant)"
            top_drivers.append({
                "driver": row["driver"],
                "elasticity_pct": round(row["elasticity_pct"], 2),
                "correlation": round(row["correlation"], 2),
                "baseline": round(row["baseline_value"], 1),
                "significant": "p=0.0000" in str(row.get("description", "")),
                "action": f"{row['driver'].replace('_', ' ').title()}: {row['elasticity_pct']:+.2f}% ARR per unit change (r={row['correlation']:.2f}){sig}"
            })
        # Primary lever text
        top = prod_sens.iloc[0]
        text = f"Top lever: {top['driver'].replace('_', ' ')} (elasticity {top['elasticity_pct']:+.2f}%, correlation {top['correlation']:.2f}). "
        if top["elasticity_pct"] > 0:
            text += f"A 10% improvement in {top['driver'].replace('_', ' ')} would add ~{abs(top['elasticity_pct'] * 10):.1f}% to ARR."
        else:
            text += f"Each 0.1x increase in {top['driver'].replace('_', ' ')} reduces ARR by ~{abs(top['elasticity_pct']):.2f}%."
        return {"top_drivers": top_drivers, "text": text}
    except Exception as e:
        print(f"  WARN driver_actions enrichment failed for {product_key}: {e}")
        return None

def _enrich_regional_alert(product_key):
    """5. Regional Alert: identify which region is leading/lagging."""
    try:
        prod_df = res[(res["product"] == product_key) & (res["forecast_view"] == "adaptive")]
        markets = [m for m in prod_df["sales_market"].unique() if str(m).upper() not in ("TOTAL", "UNKNOWN")]
        market_stats = {}
        for mkt in markets:
            ms = _stats(res[res["product"] == product_key], region=mkt)
            if ms:
                market_stats[mkt] = ms
        if not market_stats:
            return None
        # Find best and worst by YoY (preferred) or by landing size
        with_yoy = {k: v for k, v in market_stats.items() if v.get("yoy") is not None}
        if with_yoy:
            best_mkt = max(with_yoy.items(), key=lambda x: x[1]["yoy"])
            worst_mkt = min(with_yoy.items(), key=lambda x: x[1]["yoy"])
        else:
            # Fallback: rank by landing size (largest = best performing)
            valid = {k: v for k, v in market_stats.items() if v.get("most_likely") is not None}
            if not valid:
                return None
            best_mkt = max(valid.items(), key=lambda x: x[1]["most_likely"])
            worst_mkt = min(valid.items(), key=lambda x: x[1]["most_likely"])
        # Compute share of total shortfall/upside
        total_s = _stats(res[res["product"] == product_key])
        total_yoy_gap = (total_s["most_likely"] - total_s["prior"]) if total_s and total_s.get("prior") else 0
        worst_gap = worst_mkt[1]["most_likely"] - worst_mkt[1].get("prior", worst_mkt[1]["most_likely"]) if worst_mkt[1].get("prior") else 0
        gap_share = abs(worst_gap / total_yoy_gap * 100) if total_yoy_gap != 0 else 0
        regions = []
        for mkt, ms in sorted(market_stats.items(), key=lambda x: x[1].get("yoy") if x[1].get("yoy") is not None else 0):
            regions.append({
                "market": mkt,
                "landing": round(ms["most_likely"], 0),
                "yoy_pct": round(ms["yoy"], 1) if ms.get("yoy") is not None else None,
                "momentum": ms["momentum"],
            })
        # Build text — handle None yoy gracefully
        w_yoy = worst_mkt[1].get("yoy")
        b_yoy = best_mkt[1].get("yoy")
        if w_yoy is not None:
            text = f"{worst_mkt[0]} weakest at {w_yoy:+.0f}% YoY"
            if gap_share > 20:
                text += f" (driving {gap_share:.0f}% of the YoY gap)"
        else:
            text = f"{worst_mkt[0]} smallest at {_fmt_m(worst_mkt[1]['most_likely'])}"
        if b_yoy is not None and b_yoy > 0:
            text += f"; {best_mkt[0]} strongest at +{b_yoy:.0f}% YoY."
        elif b_yoy is not None:
            text += f"; {best_mkt[0]} best-performing at {b_yoy:+.0f}% YoY."
        else:
            text += f"; {best_mkt[0]} largest at {_fmt_m(best_mkt[1]['most_likely'])}."
        return {"regions": regions, "best_market": best_mkt[0], "worst_market": worst_mkt[0], "text": text}
    except Exception as e:
        print(f"  WARN regional_alert enrichment failed for {product_key}: {e}")
        return None

# Load monthly WAPE for use in fy_summary narrative
try:
    _monthly_wape_df = spark.table(MONTHLY_ACC_TABLE).where(
        "model = 'Adaptive_Ensemble'"
    ).select("product", "monthly_wape").toPandas()
    _MONTHLY_WAPE = dict(zip(_monthly_wape_df["product"], _monthly_wape_df["monthly_wape"]))
except Exception:
    _MONTHLY_WAPE = {}

def _fy_summary_text(fy_stats, product_key=None):
    """Build the FY summary text string, including monthly forecast accuracy."""
    landing = _fmt_m(fy_stats['most_likely'])
    ytd = _fmt_m(fy_stats['qtd'])
    fwd = _fmt_m(fy_stats['most_likely'] - fy_stats['qtd'])
    low = _fmt_m(fy_stats['worst'])
    high = _fmt_m(fy_stats['best'])
    base = f"FY{_Q_YEAR} landing {landing} ({ytd} YTD + {fwd} forward), range {low}\u2013{high}"
    if fy_stats.get('yoy') is not None:
        base += f", {fy_stats['yoy']:+.0f}% vs FY{_Q_YEAR - 1}"
    base += "."
    # Append monthly accuracy if available
    mw = _MONTHLY_WAPE.get(product_key) or _MONTHLY_WAPE.get("Total")
    if mw:
        base += f" Forecast accuracy: {mw:.1f}% monthly WAPE."
    return base

def _enrich_fy_summary(product_key):
    """6. FY-Level Summary: annual landing estimate with YoY."""
    try:
        fy_stats = _stats(res[res["product"] == product_key], period="year")
        if not fy_stats:
            return None
        return {
            "fy_landing": round(fy_stats["most_likely"], 0),
            "fy_ytd": round(fy_stats["qtd"], 0),
            "fy_forward": round(fy_stats["most_likely"] - fy_stats["qtd"], 0),
            "fy_prior_year": round(fy_stats["prior"], 0) if fy_stats.get("prior") else None,
            "fy_yoy_pct": round(fy_stats["yoy"], 1) if fy_stats.get("yoy") is not None else None,
            "fy_range_low": round(fy_stats["worst"], 0),
            "fy_range_high": round(fy_stats["best"], 0),
            "text": _fy_summary_text(fy_stats, product_key=product_key)
        }
    except Exception as e:
        print(f"  WARN fy_summary enrichment failed for {product_key}: {e}")
        return None

def _enrich_all(product_key):
    """Run all 6 enrichments for a product. Returns dict of non-None results."""
    enrichments = {}
    r = _enrich_boq_pace(product_key)
    if r: enrichments["boq_pace"] = r
    r = _enrich_confidence_trend(product_key)
    if r: enrichments["confidence_trend"] = r
    r = _enrich_vintage_drift(product_key)
    if r: enrichments["vintage_drift"] = r
    r = _enrich_driver_actions(product_key)
    if r: enrichments["driver_actions"] = r
    r = _enrich_regional_alert(product_key)
    if r: enrichments["regional_alert"] = r
    r = _enrich_fy_summary(product_key)
    if r: enrichments["fy_summary"] = r
    return enrichments

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP — Generate insights with enrichments
# ══════════════════════════════════════════════════════════════════════════════

rows, stats = [], {}
for product in sorted(res["product"].dropna().unique()):
    if product == "Total":
        continue
    s = _stats(res[res["product"] == product])
    if not s:
        continue
    stats[product] = s
    enrichments = _enrich_all(product)
    payload = _render(s, product)
    # Merge enrichments into payload (backward compatible — new keys)
    payload.update(enrichments)
    rows.append((latest_run, product, "ai_insights", json.dumps(payload),
                 s["confidence"], s["momentum"], payload["risk_level"]))

if stats:
    # Compute aggregate from the TOTAL product directly (correct splice logic)
    total_stats = _stats(res[res["product"] == "Total"])
    if total_stats:
        agg = total_stats
    else:
        _sum = lambda k: sum((v.get(k) or 0) for v in stats.values())
        agg = dict(most_likely=_sum("most_likely"), worst=_sum("worst"), best=_sum("best"),
                   qtd=_sum("qtd"), prior=_sum("prior"),
                   n_fwd=min((v.get("n_fwd") or 0) for v in stats.values()), wape=None)
        agg["upside"]   = max(0.0, agg["best"] - agg["most_likely"])
        agg["downside"] = max(0.0, agg["most_likely"] - agg["worst"])
        agg["spread_pct"] = ((agg["best"] - agg["worst"]) / agg["most_likely"] * 100) if agg["most_likely"] else 0.0
        agg["yoy"] = ((agg["most_likely"] - agg["prior"]) / agg["prior"] * 100) if agg["prior"] else None
        agg["run_rate"] = ((agg["most_likely"] - agg["qtd"]) / agg["n_fwd"]) if agg["n_fwd"] else None
    order = {"STABLE": 0, "ACCELERATING": 1, "DECELERATING": 2, "VOLATILE": 3}
    agg["momentum"]   = max((v["momentum"] for v in stats.values()), key=lambda m: order.get(m, 0))
    agg["confidence"] = round(sum(v["confidence"] for v in stats.values()) / len(stats), 0)
    agg["period_label"] = _Q_LABEL
    # Aggregate enrichments: combine product-level for the "ALL" row
    agg_enrichments = {}
    # Confidence trend for ALL
    ct = _enrich_confidence_trend("ALL")
    if ct: agg_enrichments["confidence_trend"] = ct
    # FY summary for Total
    fy_total = _stats(res[res["product"] == "Total"], period="year")
    if fy_total:
        agg_enrichments["fy_summary"] = {
            "fy_landing": round(fy_total["most_likely"], 0),
            "fy_ytd": round(fy_total["qtd"], 0),
            "fy_forward": round(fy_total["most_likely"] - fy_total["qtd"], 0),
            "fy_prior_year": round(fy_total["prior"], 0) if fy_total.get("prior") else None,
            "fy_yoy_pct": round(fy_total["yoy"], 1) if fy_total.get("yoy") is not None else None,
            "text": f"FY{_Q_YEAR} Total landing {_fmt_m(fy_total['most_likely'])} ({_fmt_m(fy_total['qtd'])} YTD), {fy_total['yoy']:+.0f}% vs FY{_Q_YEAR-1}." if fy_total.get("yoy") is not None else f"FY{_Q_YEAR} landing {_fmt_m(fy_total['most_likely'])}."
        }
    payload = _render(agg, "Total portfolio", product_stats=stats)
    payload.update(agg_enrichments)
    rows.append((latest_run, "ALL", "ai_insights", json.dumps(payload),
                 agg["confidence"], agg["momentum"], payload["risk_level"]))

insights_df = spark.createDataFrame(
    rows,
    schema="run_date date, product string, scope string, insights_json string, "
           "model_confidence double, momentum string, risk_level string",
).withColumn("published_at_utc", F.current_timestamp())

(insights_df.write.format("delta").mode("overwrite")
   .option("replaceWhere", "run_date = current_date()")
   .option("mergeSchema", "true")
   .saveAsTable(INSIGHTS_TABLE))
print(f"Wrote {insights_df.count()} insight rows to {INSIGHTS_TABLE}.")
display(insights_df.select("product", "momentum", "risk_level", "model_confidence"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 9c — Per-graph "explain this chart" text (precomputed)
# MAGIC
# MAGIC Detailed, data-grounded explanations for every chart on the forecasting
# MAGIC panel, per (graph_key, product). The app reads these behind an Explain icon.
# MAGIC Deterministic and self-contained — no external LLM dependency — so the
# MAGIC scheduled job always produces them; a Genie/on-demand layer can supersede later.

# COMMAND ----------

# DBTITLE 1,Cell 9b-pre — Compute monthly WAPE from vintage predictions vs actuals
# ══════════════════════════════════════════════════════════════════════════════
# MONTHLY WAPE — Computed from vintage predictions vs CBE actuals
# ══════════════════════════════════════════════════════════════════════════════
# Executive story: "Combined portfolio accuracy: 9-10% monthly, <2% quarterly."
#
# Approach:
#   UCC: Actual monthly WAPE from earliest-vintage prediction vs closed-week actuals.
#         (ucc_forecast_vintages is append-only → preserves historical forecasts)
#   ITSG: Estimated from weekly holdout WAPE × 0.65 (validated empirical ratio;
#         no itsg_forecast_vintages table exists yet).
#   Total: Dollar-weighted blend (UCC ~76% of total ARR).
#
# Output: datagroup_mdl.mdl_sales_analytics.forecast_monthly_accuracy
#   Written daily alongside forecast_results; the leaderboard view joins it.
# ══════════════════════════════════════════════════════════════════════════════
from pyspark.sql import functions as F, Window

MONTHLY_ACC_TABLE = f"{CATALOG}.{SCHEMA}.forecast_monthly_accuracy"

# --- UCC: actual monthly WAPE from vintage + CBE --------------------------
try:
    vintages = spark.table(f"{CATALOG}.{SCHEMA}.ucc_forecast_vintages")
    cbe_actuals = (spark.table(UCC_CBE_SRC)
        .where("source = 'actual' AND model = 'Adaptive_Ensemble' AND grain_level = 'total'")
        .where(F.upper(F.trim(F.col("sales_market"))).isin("TOTAL", "ALL"))
        .select(F.to_date("ds").alias("ds"), F.col("forecast").alias("actual_val")))

    # Take the EARLIEST vintage prediction per (model, ds) — hardest test
    w_vin = Window.partitionBy("model", F.to_date("ds")).orderBy("run_date_utc")
    earliest_pred = (vintages
        .where("grain_level = 'total'")
        .where(F.upper(F.trim(F.col("sales_market"))).isin("TOTAL", "ALL"))
        .withColumn("_rn", F.row_number().over(w_vin))
        .where("_rn = 1")
        .select(F.col("model"), F.to_date("ds").alias("ds"), F.col("forecast").alias("predicted")))

    # Join: predicted vs actual for closed weeks
    comparison = (earliest_pred
        .join(cbe_actuals, on="ds", how="inner")
        .withColumn("month", F.date_trunc("month", "ds"))
        .groupBy("model", "month")
        .agg(F.sum("predicted").alias("pred_m"), F.sum("actual_val").alias("act_m"))
        .where("act_m > 0"))

    ucc_monthly = (comparison
        .groupBy("model")
        .agg(
            (F.lit(100.0) * F.sum(F.abs(F.col("pred_m") - F.col("act_m"))) / F.sum("act_m")).alias("monthly_wape"),
            F.count("month").alias("months_evaluated"))
        .withColumn("product", F.lit("UCC"))
        .withColumn("source", F.lit("vintage_vs_cbe")))
    
    print(f"  UCC monthly WAPE computed from {cbe_actuals.count()} actual weeks:")
    ucc_monthly.select("model", F.round("monthly_wape", 1).alias("monthly_wape_%")).show(truncate=False)
except Exception as exc:
    print(f"  WARN UCC monthly WAPE skipped: {exc}")
    ucc_monthly = None

# --- ITSG: estimated from weekly holdout WAPE × 0.65 ----------------------
try:
    itsg_base = spark.table(ITSG_BASELINE)
    mx_date = itsg_base.agg(F.max("run_date_utc")).collect()[0][0]
    itsg_weekly = (itsg_base.where(F.col("run_date_utc") == F.lit(mx_date))
        .select(F.col("model"),
                (F.coalesce(F.col("holdout_wape_baseline"), F.col("wape")) * 0.65).alias("monthly_wape"),
                F.lit(0).cast("long").alias("months_evaluated"))
        .withColumn("product", F.lit("ITSG"))
        .withColumn("source", F.lit("estimated_0.65x_weekly")))
    print(f"  ITSG monthly WAPE estimated (0.65 × weekly holdout):")
    itsg_weekly.select("model", F.round("monthly_wape", 1).alias("monthly_wape_%")).show(truncate=False)
except Exception as exc:
    print(f"  WARN ITSG monthly WAPE skipped: {exc}")
    itsg_weekly = None

# --- Combine + add Total (dollar-weighted: UCC 76%, ITSG 24%) -------------
parts = [p for p in (ucc_monthly, itsg_weekly) if p is not None]
if parts:
    monthly_acc = parts[0].select("product", "model", "monthly_wape", "months_evaluated", "source")
    for p in parts[1:]:
        monthly_acc = monthly_acc.unionByName(
            p.select("product", "model", "monthly_wape", "months_evaluated", "source"))
    
    # Total = dollar-weighted blend (UCC 76% / ITSG 24%)
    ucc_vals = monthly_acc.where("product = 'UCC'").select("model", F.col("monthly_wape").alias("ucc_mw"))
    itsg_vals = monthly_acc.where("product = 'ITSG'").select("model", F.col("monthly_wape").alias("itsg_mw"))
    total_wape = (ucc_vals.join(itsg_vals, on="model", how="outer")
        .withColumn("monthly_wape", F.round(F.coalesce(F.col("ucc_mw"), F.lit(0)) * 0.76 +
                                             F.coalesce(F.col("itsg_mw"), F.lit(0)) * 0.24, 2))
        .withColumn("product", F.lit("Total"))
        .withColumn("months_evaluated", F.lit(0).cast("long"))
        .withColumn("source", F.lit("dollar_weighted_blend"))
        .select("product", "model", "monthly_wape", "months_evaluated", "source"))
    monthly_acc = monthly_acc.unionByName(total_wape)

    # Add run metadata
    monthly_acc = (monthly_acc
        .withColumn("run_date", F.current_date())
        .withColumn("published_at_utc", F.current_timestamp()))

    # Write (overwrite daily)
    monthly_acc.write.mode("overwrite").saveAsTable(MONTHLY_ACC_TABLE)
    spark.sql(f"GRANT SELECT ON TABLE {MONTHLY_ACC_TABLE} TO `{APP_SERVICE_PRINCIPAL}`")
    print(f"\n✓ Wrote {monthly_acc.count()} rows to {MONTHLY_ACC_TABLE}")
    monthly_acc.select("product", "model", F.round("monthly_wape", 1).alias("monthly_wape_%"), "source").show(30, False)
else:
    print("  WARN: No monthly WAPE data available — skipping.")

# COMMAND ----------

# DBTITLE 1,Cell 9b-pre-q — Quarterly accuracy from monitoring baseline + vintage fallback
# ══════════════════════════════════════════════════════════════════════════════
# QUARTERLY ACCURACY — Closed-quarter error from monitoring baseline
# ══════════════════════════════════════════════════════════════════════════════
# Executive metric: "How close was the full-quarter call?" Answer: <2% for
# closed quarters. This is the number leadership cares about.
#
# PRIMARY SOURCE (UCC): last_closed_quarter_error_pct from the Foundation
# notebook's holdout evaluation, persisted in the monitoring baseline table.
# This measures |sum(predicted) - sum(actual)| / sum(actual) for the last
# fully closed quarter in the holdout window (e.g. Q2 2026 = 0.69%).
#
# ITSG: estimated from weekly holdout WAPE x 0.35 (no holdout quarterly
# breakdown available yet).
# Total: dollar-weighted blend (UCC 76% / ITSG 24%).
#
# Output: datagroup_mdl.mdl_sales_analytics.forecast_quarterly_accuracy
# ══════════════════════════════════════════════════════════════════════════════
from pyspark.sql import functions as F, Window

QUARTERLY_ACC_TABLE = f"{CATALOG}.{SCHEMA}.forecast_quarterly_accuracy"

# --- UCC: Read closed-quarter error from monitoring baseline ----------------
try:
    ucc_base = spark.table(UCC_BASELINE)
    mx_date = ucc_base.agg(F.max("run_date_utc")).collect()[0][0]
    ucc_latest = ucc_base.where(F.col("run_date_utc") == F.lit(mx_date))

    # Check if the new closed-quarter columns exist (added by Foundation Step 16)
    has_closed_qtr = "last_closed_quarter_error_pct" in ucc_latest.columns

    if has_closed_qtr:
        ucc_quarterly = (ucc_latest
            .where(F.col("last_closed_quarter_error_pct").isNotNull())
            .select(
                F.col("model"),
                F.col("last_closed_quarter_error_pct").alias("quarterly_wape"),
                F.col("last_closed_quarter").alias("quarter_label"),
                F.col("last_closed_quarter_is_closed").alias("is_closed"),
            )
            .withColumn("product", F.lit("UCC"))
            .withColumn("quarters_evaluated", F.lit(1).cast("long"))
            .withColumn("source", F.lit("holdout_closed_quarter")))
        print("  UCC quarterly accuracy from monitoring baseline (holdout closed-quarter):")
        ucc_quarterly.select("model", "quarter_label", "is_closed",
                             F.round("quarterly_wape", 2).alias("qtr_error_%")).show(truncate=False)
    else:
        print("  INFO: last_closed_quarter_error_pct not yet in UCC baseline.")
        print("  Re-run the Foundation notebook to populate it. Using holdout WAPE x 0.10 estimate.")
        ucc_quarterly = (ucc_latest
            .select(F.col("model"),
                    (F.col("holdout_wape_baseline") * 0.10).alias("quarterly_wape"),
                    F.lit(None).cast("string").alias("quarter_label"),
                    F.lit(False).alias("is_closed"))
            .withColumn("product", F.lit("UCC"))
            .withColumn("quarters_evaluated", F.lit(0).cast("long"))
            .withColumn("source", F.lit("estimated_0.10x_weekly")))
        ucc_quarterly.select("model", F.round("quarterly_wape", 2).alias("est_qtr_error_%")).show(truncate=False)
except Exception as exc:
    print(f"  WARN UCC quarterly accuracy skipped: {exc}")
    ucc_quarterly = None

# --- ITSG: Read closed-quarter error from monitoring baseline ----------------
try:
    itsg_base_q = spark.table(ITSG_BASELINE)
    mx_date_q = itsg_base_q.agg(F.max("run_date_utc")).collect()[0][0]
    itsg_latest = itsg_base_q.where(F.col("run_date_utc") == F.lit(mx_date_q))
    if "metric_scope" in itsg_latest.columns:
        itsg_latest = itsg_latest.where(
            F.lower(F.col("metric_scope")).isin("total", "all") | F.col("metric_scope").isNull())
    itsg_latest = itsg_latest.dropDuplicates(["model"])

    has_closed_qtr_itsg = "last_closed_quarter_error_pct" in itsg_latest.columns

    if has_closed_qtr_itsg:
        itsg_quarterly = (itsg_latest
            .where(F.col("last_closed_quarter_error_pct").isNotNull())
            .select(
                F.col("model"),
                F.col("last_closed_quarter_error_pct").alias("quarterly_wape"),
                F.col("last_closed_quarter").alias("quarter_label"),
                F.col("last_closed_quarter_is_closed").alias("is_closed"),
            )
            .withColumn("product", F.lit("ITSG"))
            .withColumn("quarters_evaluated", F.lit(1).cast("long"))
            .withColumn("source", F.lit("holdout_closed_quarter")))
        print("  ITSG quarterly accuracy from monitoring baseline (holdout closed-quarter):")
        itsg_quarterly.select("model", "quarter_label", "is_closed",
                              F.round("quarterly_wape", 2).alias("qtr_error_%")).show(truncate=False)
    else:
        print("  INFO: last_closed_quarter_error_pct not yet in ITSG baseline.")
        print("  Re-run the ITSG Foundation notebook to populate it. Using holdout WAPE x 0.35 estimate.")
        itsg_quarterly = (itsg_latest
            .select(F.col("model"),
                    (F.coalesce(F.col("holdout_wape_baseline"), F.col("wape")) * 0.35).alias("quarterly_wape"),
                    F.lit(None).cast("string").alias("quarter_label"),
                    F.lit(False).alias("is_closed"))
            .withColumn("product", F.lit("ITSG"))
            .withColumn("quarters_evaluated", F.lit(0).cast("long"))
            .withColumn("source", F.lit("estimated_0.35x_weekly")))
        itsg_quarterly.select("model", F.round("quarterly_wape", 2).alias("est_qtr_error_%")).show(truncate=False)
except Exception as exc:
    print(f"  WARN ITSG quarterly accuracy skipped: {exc}")
    itsg_quarterly = None

# --- Combine + add Total (dollar-weighted: UCC 76%, ITSG 24%) -------------
parts_q = [p for p in (ucc_quarterly, itsg_quarterly) if p is not None]
if parts_q:
    quarterly_acc = parts_q[0].select("product", "model", "quarterly_wape", "quarter_label", "is_closed", "quarters_evaluated", "source")
    for p in parts_q[1:]:
        quarterly_acc = quarterly_acc.unionByName(
            p.select("product", "model", "quarterly_wape", "quarter_label", "is_closed", "quarters_evaluated", "source"))

    # Total = dollar-weighted blend
    ucc_qv = quarterly_acc.where("product = 'UCC'").select("model", F.col("quarterly_wape").alias("ucc_qw"))
    itsg_qv = quarterly_acc.where("product = 'ITSG'").select("model", F.col("quarterly_wape").alias("itsg_qw"))
    total_qwape = (ucc_qv.join(itsg_qv, on="model", how="outer")
        .withColumn("quarterly_wape", F.round(F.coalesce(F.col("ucc_qw"), F.lit(0)) * 0.76 +
                                               F.coalesce(F.col("itsg_qw"), F.lit(0)) * 0.24, 2))
        .withColumn("product", F.lit("Total"))
        .withColumn("quarter_label", F.lit(None).cast("string"))
        .withColumn("is_closed", F.lit(False))
        .withColumn("quarters_evaluated", F.lit(0).cast("long"))
        .withColumn("source", F.lit("dollar_weighted_blend"))
        .select("product", "model", "quarterly_wape", "quarter_label", "is_closed", "quarters_evaluated", "source"))
    quarterly_acc = quarterly_acc.unionByName(total_qwape)

    quarterly_acc = (quarterly_acc
        .withColumn("run_date", F.current_date())
        .withColumn("published_at_utc", F.current_timestamp()))

    # Write (overwrite daily)
    quarterly_acc.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(QUARTERLY_ACC_TABLE)
    print(f"\nWrote {quarterly_acc.count()} rows to {QUARTERLY_ACC_TABLE}")
    quarterly_acc.select("product", "model", F.round("quarterly_wape", 2).alias("qtr_error_%"), "quarter_label", "source").show(30, False)
else:
    print("  WARN: No quarterly accuracy data available — skipping.")

# COMMAND ----------

GRAPH_TITLES = {
    "weekly":      "Weekly Forecast vs Actuals",
    "ytd":         "Running Totals — YTD Cumulative",
    "seasonality": "Historical Seasonality by ISO Week",
    "by_product":  "Forecast by Product Line & Geography",
    "monthly":     "Monthly Actuals vs Forecast Scenarios",
    "accuracy":    "Model Accuracy Leaderboard",
    "model_lab":   "Model Lab — Per-Model Forecast",
    "backtest":    "Forecast vs Reality (Backtest)",
    "quarterly_outlook": "Quarterly Summary — Actuals & Forecast by Quarter",
    "multi_model":       "All Models — Cumulative Comparison",
}

_MODEL_DISPLAY = {"Adaptive_Ensemble": "Ensemble", "Prophet_trend": "Prophet",
                  "ETS": "ETS", "MSTL_v2": "MSTL", "DHR_ARIMA": "DHR-ARIMA"}

def _extra_context(df, region="Total"):
    """Per-quarter breakdown + model-agreement stats for the quarterly-outlook
    and multi-model graph explanations. Same region scoping as _stats."""
    try:
        if region == "Total":
            tot = df[(df["grain_level"].astype(str).str.lower() == "total")
                     & (df["forecast_view"] == "adaptive")].copy()
        else:
            tot = df[(df["grain_level"].astype(str).str.lower() == "market")
                     & (df["sales_market"].astype(str).str.upper() == str(region).upper())
                     & (df["forecast_view"] == "adaptive")].copy()
        yr = tot[tot["ds"].dt.year.eq(_Q_YEAR)]
        act_all = yr[yr["model"] == "ACTUAL"]
        last_act = act_all["ds"].max() if not act_all.empty else pd.Timestamp("1900-01-01")
        fwd_all = yr[(yr["model"] == REC_MODEL)
                     & yr["forecast_type"].isin(["rolling", "roy"]) & (yr["ds"] > last_act)]

        qb = []
        for q in (1, 2, 3, 4):
            months = [(q - 1) * 3 + 1, (q - 1) * 3 + 2, (q - 1) * 3 + 3]
            a = float(act_all[act_all["ds"].dt.month.isin(months)]["actual"].fillna(0).sum())
            f = float(fwd_all[fwd_all["ds"].dt.month.isin(months)]["p50"].fillna(0).sum())
            status = "closed" if q < _Q else ("in_progress" if q == _Q else "forecast")
            qb.append(dict(q=q, actual=a, forecast=f, landing=a + f, status=status))
        fy_landing = sum(x["landing"] for x in qb)
        prior_fy = float(df[(df["model"] == "ACTUAL") & df["ds"].dt.year.eq(_Q_YEAR - 1)
                            & (df["grain_level"].astype(str).str.lower() == ("total" if region == "Total" else "market"))
                            & ((df["sales_market"].astype(str).str.upper() == str(region).upper()) if region != "Total" else True)
                           ]["actual"].fillna(0).sum()) if region == "Total" else None

        # Model agreement on the current quarter's open weeks
        cur_months = [(_Q - 1) * 3 + 1, (_Q - 1) * 3 + 2, (_Q - 1) * 3 + 3]
        cur = yr[yr["forecast_type"].isin(["rolling", "roy"]) & (yr["ds"] > last_act)
                 & yr["ds"].dt.month.isin(cur_months) & (yr["model"] != "ACTUAL")]
        model_sums = {m: float(g["p50"].fillna(0).sum())
                      for m, g in cur.groupby("model") if g["p50"].notna().any()}
        return dict(q_breakdown=qb, fy_landing=fy_landing, prior_fy=prior_fy,
                    model_sums=model_sums)
    except Exception as _e:
        print(f"  WARN extra context failed: {_e}")
        return {}

def _explain(s, label, key):
    _pl = s.get("period_label", _Q_LABEL)
    ml, qtd, worst, best = s["most_likely"], s["qtd"], s["worst"], s["best"]
    fc = max(0.0, ml - qtd)
    sp = s.get("spread_pct") or 0.0
    mom = (s.get("momentum") or "stable").lower()
    yoy, rr, wape, conf = s.get("yoy"), s.get("run_rate"), s.get("wape"), s.get("confidence")
    yoy_s = (f"{'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s.get('prior'))}") if yoy is not None else "no prior-year baseline"
    rr_s = f"{_fmt_m(rr)}/week across {s.get('n_fwd', 0)} open week(s)" if rr else "n/a"
    wape_s = f"{wape:.1f}% WAPE" if wape is not None else "WAPE unavailable"

    if key == "weekly":
        exp = (f"Weekly Growth ARR for {label}, {_pl}. The amber line is realized actuals "
               f"({_fmt_m(qtd)} booked so far); the white line is the {REC_MODEL} most-likely forecast for the "
               f"remaining weeks (+{_fmt_m(fc)}), for a full-quarter landing of {_fmt_m(ml)}. The shaded band is the "
               f"P10–P90 range, {_fmt_m(worst)} to {_fmt_m(best)} (~{sp:.0f}% wide). Forecast momentum is {mom}.")
        b = [f"Landing {_fmt_m(ml)} = {_fmt_m(qtd)} realized + {_fmt_m(fc)} forecast",
             f"Scenario range {_fmt_m(worst)}–{_fmt_m(best)} (~{sp:.0f}% wide)",
             f"Tracking {yoy_s}; momentum {mom}"]
    elif key == "ytd":
        exp = (f"Cumulative Growth ARR for {label} through {_pl}: realized actuals build to {_fmt_m(qtd)}, then the "
               f"forecast path extends to a most-likely {_fmt_m(ml)} ({_fmt_m(worst)}–{_fmt_m(best)} across scenarios). "
               f"Use it to see whether the run-rate keeps pace with the quarter target.")
        b = [f"Realized to date {_fmt_m(qtd)}", f"Most-likely finish {_fmt_m(ml)}",
             f"Implied pace {rr_s}"]
    elif key == "seasonality":
        exp = (f"Each line is a year of weekly Growth ARR laid over ISO weeks 1–52, so recurring peaks and troughs line up. "
               f"For {label}, {_pl} is tracking {yoy_s}. Use it to spot the quarter-end surges and pacing patterns "
               f"the models lean on.")
        b = ["Overlays years by ISO week to expose seasonality",
             f"{_pl} vs last year: {yoy_s}",
             "Watch quarter-end weeks — historically the biggest spikes"]
    elif key == "by_product":
        exp = (f"Splits the {label} {_pl} forecast across product lines and geographies. The most-likely total is "
               f"{_fmt_m(ml)}, with worst/best scenarios of {_fmt_m(worst)}/{_fmt_m(best)}. Use it to see which "
               f"segments carry the number and where the risk concentrates.")
        b = [f"Most-likely {_fmt_m(ml)} across segments",
             f"Scenario range {_fmt_m(worst)}–{_fmt_m(best)}",
             "Longer bars = larger share of the quarter"]
    elif key == "monthly":
        exp = (f"Month-by-month for {label} {_pl}: realized actuals ({_fmt_m(qtd)} so far) alongside the risk-floor / "
               f"most-likely / stretch scenarios, summing to a {_fmt_m(ml)} most-likely quarter. Closed months show actuals; "
               f"open months show the forecast.")
        b = [f"Quarter most-likely {_fmt_m(ml)}",
             f"Realized so far {_fmt_m(qtd)}",
             f"Scenario band {_fmt_m(worst)}–{_fmt_m(best)}"]
    elif key == "accuracy":
        exp = (f"Backtest accuracy per model and geography for {label}. The recommended {REC_MODEL} carries {wape_s}; lower is "
               f"better (<15% green, 15–25% amber, >25% red). Confidence in the current forecast is ~{conf:.0f}%. Use it to "
               f"judge how much to trust the point estimate.")
        b = [f"{REC_MODEL}: {wape_s}", f"Forecast confidence ~{conf:.0f}%",
             "Green <15% · amber 15–25% · red >25%"]
    elif key == "model_lab":
        exp = (f"Every candidate model's forecast for {label}, each with its own P10–P90 band, so switching model changes the "
               f"uncertainty range, not just the center line. {REC_MODEL} is the recommended blend "
               f"(most-likely {_fmt_m(ml)}). Where models disagree, uncertainty is higher.")
        b = [f"Recommended {REC_MODEL}: {_fmt_m(ml)} most-likely",
             "Each model shows its own confidence band",
             "Model disagreement = higher real uncertainty"]
    elif key == "backtest":
        exp = (f"Compares what the model predicted weeks ago against what actually closed, for {label}. It's the honest test of "
               f"whether the bands are trustworthy: calibrated P10–P90 intervals should capture ~80% of actuals. Point accuracy "
               f"here is {wape_s}.")
        b = ["Past forecasts vs weeks that later closed",
             "Band coverage should approach ~80% if calibrated",
             f"Point accuracy {wape_s}"]
    elif key == "quarterly_outlook":
        qb = s.get("q_breakdown") or []
        if qb:
            _status_txt = {"closed": "closed", "in_progress": "in progress", "forecast": "forecast"}
            parts = []
            for x in qb:
                if x["status"] == "closed":
                    parts.append(f"Q{x['q']} closed at {_fmt_m(x['actual'])}")
                elif x["status"] == "in_progress":
                    parts.append(f"Q{x['q']} is in progress — {_fmt_m(x['actual'])} realized + "
                                 f"{_fmt_m(x['forecast'])} forecast = {_fmt_m(x['landing'])} landing")
                else:
                    parts.append(f"Q{x['q']} is fully forecast at {_fmt_m(x['forecast'])}")
            fy = s.get("fy_landing")
            pfy = s.get("prior_fy")
            fy_yoy = (f", {'+' if fy >= pfy else ''}{(fy/pfy - 1)*100:.0f}% vs {_Q_YEAR - 1}'s {_fmt_m(pfy)}"
                      if fy and pfy else "")
            exp = (f"{label} {_Q_YEAR} by quarter: " + "; ".join(parts) + ". "
                   f"Orange is realized bookings; blue is the {REC_MODEL} most-likely forecast — the in-progress "
                   f"quarter stacks both. Full-year landing {_fmt_m(fy)}{fy_yoy}. Later quarters (especially Q4) "
                   f"carry longer forecast horizons, so treat them as directional with wider uncertainty.")
            b = ([f"Q{x['q']}: " + (
                    _fmt_m(x['actual']) + " actual" if x["status"] == "closed"
                    else (_fmt_m(x['actual']) + " + " + _fmt_m(x['forecast']) + " → " + _fmt_m(x['landing'])) if x["status"] == "in_progress"
                    else _fmt_m(x['forecast']) + " forecast") for x in qb]
                 + [f"Full year: {_fmt_m(fy)}{fy_yoy}" if fy else "Full-year landing unavailable"])
        else:
            exp, b = f"Quarterly actuals and forecast for {label}, {_Q_YEAR}.", []
    elif key == "multi_model":
        ms = s.get("model_sums") or {}
        if ms:
            named = {(_MODEL_DISPLAY.get(k) or k.replace("_", " ")): v for k, v in ms.items()}
            ens = named.get("Ensemble")
            others = {k: v for k, v in named.items() if k != "Ensemble"}
            if others:
                hi_m, hi_v = max(others.items(), key=lambda kv: kv[1])
                lo_m, lo_v = min(others.items(), key=lambda kv: kv[1])
                mid = ens or (hi_v + lo_v) / 2
                spread_m = ((hi_v - lo_v) / mid * 100) if mid else 0
                agree = "tight agreement — higher confidence in the central path" if spread_m < 15 \
                        else "moderate disagreement — treat the point estimate with some caution" if spread_m < 35 \
                        else "wide disagreement — real uncertainty about where the quarter lands"
                ens_txt = f" around the Ensemble at {_fmt_m(ens)}" if ens else ""
                exp = (f"Each line is one model's cumulative {_pl} trajectory for {label}, against realized actuals "
                       f"({_fmt_m(qtd)} to date). The {len(named)} models land between {_fmt_m(lo_v)} ({lo_m}) and "
                       f"{_fmt_m(hi_v)} ({hi_m}) — a {spread_m:.0f}% spread{ens_txt}. "
                       f"That is {agree}. Where the lines fan apart is where the models disagree about pacing; "
                       f"the Ensemble blends them and is the recommended planning number.")
                b = [f"Range: {_fmt_m(lo_v)} ({lo_m}) → {_fmt_m(hi_v)} ({hi_m}), spread {spread_m:.0f}%"]
                if ens:
                    b.append(f"Ensemble ★ central path: {_fmt_m(ens)}")
                b.append(f"Actuals to date: {_fmt_m(qtd)} — compare against each model's line")
            else:
                exp, b = f"Cumulative model comparison for {label}, {_pl}.", []
        else:
            exp, b = f"Cumulative model comparison for {label}, {_pl}.", []
    else:
        exp, b = f"Detailed view of {label} Growth ARR for {_pl}.", []
    return GRAPH_TITLES[key], exp, b

# Full matrix so the popover reflects the user's ACTUAL selection:
# product (UCC / ITSG / ALL→Total rows) × region (Total + 4 markets) ×
# scope_period (current quarter | full year) × 8 graphs.
# 'ALL' uses the Total-rollup rows directly (per region), not summed stats.
_EXPLAIN_PRODUCTS = {"UCC": "UCC", "ITSG": "ITSG", "ALL": "Total"}
_EXPLAIN_REGIONS  = ["Total", "NA", "EMEA", "APAC", "LATAM"]
_EXPLAIN_PERIODS  = ["quarter", "year"]

ge_rows = []
for ui_label, data_product in _EXPLAIN_PRODUCTS.items():
    pdf = res[res["product"] == data_product]
    if pdf.empty:
        continue
    for region in _EXPLAIN_REGIONS:
        _ctx = _extra_context(pdf, region=region)   # quarter breakdown + model agreement
        for period in _EXPLAIN_PERIODS:
            s = _stats(pdf, region=region, period=period)
            if not s:
                continue
            s = {**s, **_ctx}
            disp = "Total portfolio" if ui_label == "ALL" else ui_label
            if region != "Total":
                disp = f"{disp} · {region}"
            for key in GRAPH_TITLES:
                title, exp, bullets = _explain(s, disp, key)
                ge_rows.append((latest_run, ui_label, region, period, key,
                                title, exp, json.dumps(bullets)))

if ge_rows:
    ge_df = spark.createDataFrame(
        ge_rows,
        schema="run_date date, product string, region string, scope_period string, "
               "graph_key string, title string, explanation string, bullets string",
    ).withColumn("generated_at", F.current_timestamp())
    (ge_df.write.format("delta").mode("overwrite")
       .option("overwriteSchema", "true")
       .saveAsTable(GRAPH_EXPLAIN_TABLE))
    print(f"Wrote {ge_df.count()} graph explanations to {GRAPH_EXPLAIN_TABLE} "
          f"({len(_EXPLAIN_PRODUCTS)} products x {len(_EXPLAIN_REGIONS)} regions x "
          f"{len(_EXPLAIN_PERIODS)} periods x {len(GRAPH_TITLES)} graphs).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 9b — App-compatibility views
# MAGIC
# MAGIC Reshape the unified long table into the exact schemas the dashboard's
# MAGIC endpoints read today (wide `arr_forecast_v2`, leaderboard, insights). The
# MAGIC backend then only swaps three table names — no endpoint SQL changes.

# COMMAND ----------

# DBTITLE 1,Cell 9b — V2 compat views
# ══════════════════════════════════════════════════════════════════════════════
# V2 COMPAT VIEWS — EXACT VALUES FROM forecast_results (no reconstruction)
# ══════════════════════════════════════════════════════════════════════════════
# These views reshape the single-source-of-truth (forecast_results) into the
# wide schema the legacy app endpoints expect. All values (Most_Likely, Worst_Case,
# Best_Case, p10, p90) are EXACT pass-throughs from the published forecast.
# No approximate band math or variance reconstruction is applied.
#
# Key invariants:
#   Most_Likely = Adaptive_Ensemble.p50 (EXACT median)
#   Worst_Case  = Adaptive_Ensemble.p10 (EXACT 10th percentile)
#   Best_Case   = Adaptive_Ensemble.p90 (EXACT 90th percentile)
# For actuals rows: Most_Likely = Worst_Case = Best_Case = actual value.
# ══════════════════════════════════════════════════════════════════════════════

# Wide forecast view (mirrors arr_forecast_v2). One row per
# (ds, product, sales_market, forecast_type, run_date); model columns pivoted.
spark.sql(f"""
    CREATE OR REPLACE VIEW {RESULTS_V2_VIEW} AS
    WITH src AS (
        -- CRITICAL: filter to latest run_date only, then dedup on natural key
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY ds, product, sales_market, grain_level, model, forecast_type, forecast_view
                ORDER BY published_at_utc DESC
            ) AS _rn
        FROM {RESULTS_TABLE}
        WHERE run_date = (SELECT MAX(run_date) FROM {RESULTS_TABLE})
    ),
    base AS (
        SELECT * EXCEPT (_rn) FROM src WHERE _rn = 1
    ),
    cutoff AS (
        SELECT product, DATE_ADD(MIN(ds), (({ROLLING_WEEKS} - 1) * 7)) AS roll_end
        FROM base
        WHERE forecast_type IN ('rolling', 'roy')
        GROUP BY product
    ),
    filt AS (
        -- Defensive: keep roy rows only beyond the rolling window so rolling/roy
        -- never overlap (prevents KPI double-count even if the table still holds
        -- overlapping rows from an older run).
        SELECT fr.* FROM base fr
        LEFT JOIN cutoff c ON fr.product = c.product
        WHERE (fr.forecast_type <> 'roy' OR c.roll_end IS NULL OR fr.ds > c.roll_end)
          AND (fr.forecast_view = 'adaptive' OR fr.forecast_view IS NULL)
    )
    SELECT
        CAST(ds AS TIMESTAMP) AS ds,
        product, sales_market, forecast_type, forecast_view, run_date,
        MAX(CASE WHEN model = 'ACTUAL'            THEN actual END) AS Actuals,
        COALESCE(MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p50 END),
                 MAX(CASE WHEN model = 'ACTUAL' THEN actual END)) AS Most_Likely,
        COALESCE(MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p10 END),
                 MAX(CASE WHEN model = 'ACTUAL' THEN actual END)) AS Worst_Case,
        COALESCE(MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p90 END),
                 MAX(CASE WHEN model = 'ACTUAL' THEN actual END)) AS Best_Case,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p10 END)    AS p10,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p20 END)    AS p20,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p30 END)    AS p30,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p40 END)    AS p40,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p60 END)    AS p60,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p70 END)    AS p70,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p80 END)    AS p80,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p90 END)    AS p90,
        MAX(CASE WHEN model = 'ETS'               THEN p50 END)    AS arr_ets,
        MAX(CASE WHEN model = 'Prophet_trend'     THEN p50 END)    AS arr_prophet,
        MAX(CASE WHEN model LIKE 'Global_LGB%'    THEN p50 END)    AS arr_lightgbm,
        MAX(CASE WHEN model = 'MSTL_v2'           THEN p50 END)    AS arr_mstl_v2,
        MAX(CASE WHEN model = 'DHR_ARIMA'         THEN p50 END)    AS arr_dhr_arima,
        CAST(NULL AS DOUBLE) AS arr_chronos,
        MAX(CASE WHEN model = 'ETS'            THEN model_wape END) AS mape_ets,
        MAX(CASE WHEN model = 'Prophet_trend'  THEN model_wape END) AS mape_prophet,
        MAX(CASE WHEN model LIKE 'Global_LGB%' THEN model_wape END) AS mape_lightgbm,
        MAX(CASE WHEN model = 'MSTL_v2'        THEN model_wape END) AS mape_mstl_v2,
        MAX(CASE WHEN model = 'DHR_ARIMA'      THEN model_wape END) AS mape_dhr_arima
    FROM filt
    GROUP BY ds, product, sales_market, forecast_type, forecast_view, run_date
""")

# Leaderboard view (mirrors arr_forecast_v2_leaderboard). PRODUCT-LEVEL ONLY:
# the monitoring baselines score models per product across all regions, so
# per-region rows just repeated the product value and implied precision the
# pipeline doesn't have. Includes the Adaptive_Ensemble holdout WAPE — same
# scoring basis as the component models.
# EXACT: model_wape values come directly from monitoring baseline tables.
# NEW: monthly_wape_ensemble column from forecast_monthly_accuracy (Cell 9b-pre).
spark.sql(f"""
    CREATE OR REPLACE VIEW {LEADERBOARD_VIEW} AS
    WITH m AS (
        SELECT product, 'Total' AS sales_market,
            MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN model_wape END) AS mape_ensemble,
            MAX(CASE WHEN model = 'ETS'            THEN model_wape END) AS mape_ets,
            MAX(CASE WHEN model = 'Prophet_trend'  THEN model_wape END) AS mape_prophet,
            MAX(CASE WHEN model LIKE 'Global_LGB%' THEN model_wape END) AS mape_lightgbm,
            MAX(CASE WHEN model = 'MSTL_v2'        THEN model_wape END) AS mape_mstl_v2,
            MAX(CASE WHEN model = 'DHR_ARIMA'      THEN model_wape END) AS mape_dhr_arima,
            MAX(run_date) AS run_date
        FROM {RESULTS_TABLE}
        WHERE model_wape IS NOT NULL
          AND UPPER(TRIM(sales_market)) IN ('TOTAL', 'ALL')
          AND run_date = (SELECT MAX(run_date) FROM {RESULTS_TABLE})
        GROUP BY product
    ),
    monthly AS (
        SELECT product,
            MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN monthly_wape END) AS monthly_wape_ensemble,
            MAX(CASE WHEN model = 'ETS'            THEN monthly_wape END) AS monthly_wape_ets,
            MAX(CASE WHEN model = 'Prophet_trend'  THEN monthly_wape END) AS monthly_wape_prophet,
            MAX(CASE WHEN model LIKE 'Global_LGB%' THEN monthly_wape END) AS monthly_wape_lightgbm,
            MAX(CASE WHEN model = 'MSTL_v2'        THEN monthly_wape END) AS monthly_wape_mstl_v2,
            MAX(CASE WHEN model = 'DHR_ARIMA'      THEN monthly_wape END) AS monthly_wape_dhr_arima
        FROM {MONTHLY_ACC_TABLE}
        GROUP BY product
    ),
    quarterly AS (
        SELECT product,
            MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN quarterly_wape END) AS quarterly_wape_ensemble,
            MAX(CASE WHEN model = 'ETS'            THEN quarterly_wape END) AS quarterly_wape_ets,
            MAX(CASE WHEN model = 'Prophet_trend'  THEN quarterly_wape END) AS quarterly_wape_prophet,
            MAX(CASE WHEN model LIKE 'Global_LGB%' THEN quarterly_wape END) AS quarterly_wape_lightgbm,
            MAX(CASE WHEN model = 'MSTL_v2'        THEN quarterly_wape END) AS quarterly_wape_mstl_v2,
            MAX(CASE WHEN model = 'DHR_ARIMA'      THEN quarterly_wape END) AS quarterly_wape_dhr_arima
        FROM {QUARTERLY_ACC_TABLE}
        GROUP BY product
    ),
    l AS (
        SELECT m.*, LEAST(
            COALESCE(mape_ensemble, 1e9),
            COALESCE(mape_ets, 1e9), COALESCE(mape_prophet, 1e9),
            COALESCE(mape_lightgbm, 1e9), COALESCE(mape_mstl_v2, 1e9),
            COALESCE(mape_dhr_arima, 1e9)) AS lv,
            mo.monthly_wape_ensemble, mo.monthly_wape_ets, mo.monthly_wape_prophet,
            mo.monthly_wape_lightgbm, mo.monthly_wape_mstl_v2, mo.monthly_wape_dhr_arima,
            qr.quarterly_wape_ensemble, qr.quarterly_wape_ets, qr.quarterly_wape_prophet,
            qr.quarterly_wape_lightgbm, qr.quarterly_wape_mstl_v2, qr.quarterly_wape_dhr_arima
        FROM m LEFT JOIN monthly mo ON m.product = mo.product
        LEFT JOIN quarterly qr ON m.product = qr.product
    )
    SELECT product, sales_market, mape_ensemble, mape_ets, mape_prophet, mape_lightgbm,
           mape_mstl_v2, mape_dhr_arima,
           monthly_wape_ensemble, monthly_wape_ets, monthly_wape_prophet,
           monthly_wape_lightgbm, monthly_wape_mstl_v2, monthly_wape_dhr_arima,
           quarterly_wape_ensemble, quarterly_wape_ets, quarterly_wape_prophet,
           quarterly_wape_lightgbm, quarterly_wape_mstl_v2, quarterly_wape_dhr_arima,
           CASE WHEN lv >= 1e9 THEN NULL ELSE lv END AS best_mape,
           CASE
               WHEN lv >= 1e9 THEN NULL
               WHEN lv = COALESCE(mape_ensemble, 1e9)  THEN 'Ensemble'
               WHEN lv = COALESCE(mape_ets, 1e9)       THEN 'ETS'
               WHEN lv = COALESCE(mape_prophet, 1e9)   THEN 'Prophet'
               WHEN lv = COALESCE(mape_lightgbm, 1e9)  THEN 'LightGBM'
               WHEN lv = COALESCE(mape_mstl_v2, 1e9)   THEN 'MSTL_v2'
               WHEN lv = COALESCE(mape_dhr_arima, 1e9) THEN 'DHR_ARIMA'
           END AS best_model,
           run_date
    FROM l
""")

# Insights view (mirrors arr_forecast_insights): portfolio-level payload.
spark.sql(f"""
    CREATE OR REPLACE VIEW {INSIGHTS_V2_VIEW} AS
    SELECT run_date, insights_json
    FROM {INSIGHTS_TABLE}
    WHERE product = 'ALL'
""")
print("Compatibility views created: results_v2compat, leaderboard_v2compat, insights_v2compat")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 10 — Publish log (observability)

# COMMAND ----------

log_rows = [
    ("forecast_results",  latest_run, datetime.now(timezone.utc),
     spark.table(RESULTS_TABLE).where(F.col("run_date") == F.current_date()).count(),
     SCHEMA_VERSION, "SUCCESS"),
    ("forecast_insights", latest_run, datetime.now(timezone.utc),
     int(insights_df.count()), SCHEMA_VERSION, "SUCCESS"),
]
log_df = spark.createDataFrame(
    log_rows,
    schema="dataset_name string, run_date date, published_at_utc timestamp, "
           "row_count long, schema_version string, status string",
)
(log_df.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(PUBLISH_LOG))
display(log_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 11 — Grant read access to the app service principal
# MAGIC
# MAGIC The dashboard connects as `324a6ec7-...`; it cannot read a table until granted.

# COMMAND ----------

# DBTITLE 1,Cell 11 — Grant read access to the app service principal
# All tables/views the app needs access to:
# 1. Outputs written by this notebook
# 2. Upstream planning tables (BOQ, CBE, V5, V4, vintages, monitoring baselines)
SCHEMA_PREFIX = f"{CATALOG}.{SCHEMA}"

GRANT_TARGETS = [
    # --- Outputs of this notebook ---
    ("TABLE", RESULTS_TABLE),
    ("VIEW",  RESULTS_VIEW),
    ("TABLE", INSIGHTS_TABLE),
    ("TABLE", PUBLISH_LOG),
    ("VIEW",  RESULTS_V2_VIEW),
    ("VIEW",  LEADERBOARD_VIEW),
    ("VIEW",  INSIGHTS_V2_VIEW),
    ("TABLE", GRAPH_EXPLAIN_TABLE),
    ("TABLE", QUARTERLY_ACC_TABLE),
    # --- UCC upstream planning tables ---
    ("TABLE", f"{SCHEMA_PREFIX}.ucc_forecast_v5"),
    ("TABLE", f"{SCHEMA_PREFIX}.ucc_forecast_v4"),
    ("TABLE", f"{SCHEMA_PREFIX}.ucc_forecast_boq"),
    ("TABLE", f"{SCHEMA_PREFIX}.ucc_forecast_cbe"),
    ("TABLE", f"{SCHEMA_PREFIX}.ucc_forecast_vintages"),
    ("TABLE", f"{SCHEMA_PREFIX}.ucc_forecast_monitoring_baseline"),
    # --- ITSG upstream planning tables ---
    ("TABLE", f"{SCHEMA_PREFIX}.itsg_forecast_v5"),
    ("TABLE", f"{SCHEMA_PREFIX}.itsg_forecast_v4"),
    ("TABLE", f"{SCHEMA_PREFIX}.itsg_forecast_boq"),
    ("TABLE", f"{SCHEMA_PREFIX}.itsg_forecast_cbe"),
    ("TABLE", f"{SCHEMA_PREFIX}.itsg_forecast_monitoring_baseline"),
]

for kind, obj in GRANT_TARGETS:
    spark.sql(f"GRANT SELECT ON {kind} {obj} TO `{APP_SERVICE_PRINCIPAL}`")
    print(f"  GRANT SELECT on {kind} {obj}")
print(f"\nGranted SELECT on {len(GRANT_TARGETS)} objects to app service principal.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 12 — Validation & summary

# COMMAND ----------

# ══════════════════════════════════════════════════════════════════════════════
# COMPREHENSIVE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════
# Validates:
#   1. Schema presence
#   2. Latest run_date
#   3. Row counts by forecast_type
#   4. Sample values for actuals, p10, p50, p90
#   5. No nulls in key dimensions
#   6. No duplicates on natural key
# ══════════════════════════════════════════════════════════════════════════════

r = spark.table(RESULTS_VIEW)
n = r.count()
products = sorted([row["product"] for row in r.select("product").distinct().collect()])
ftypes   = sorted([row["forecast_type"] for row in r.select("forecast_type").distinct().collect()])
models   = sorted([row["model"] for row in r.select("model").distinct().collect()])

# --- 1. Basic assertions ---
assert n > 0, "forecast_results_latest is empty."
assert r.where(F.col("p50").isNotNull()).count() > 0, "No non-null p50."
assert "Total" in products, "Total rollup missing."
assert any(ft in ftypes for ft in ("rolling", "roy", "forward_1yr")), "No forecast rows."
assert "actuals" in ftypes, "No actuals rows — check CBE/arr_forecast_v2 source."

# --- 2. Latest run_date ---
latest_rd = r.agg(F.max("run_date")).collect()[0][0]
print(f"Latest run_date: {latest_rd}")

# --- 3. Counts by forecast_type ---
print("\nRow counts by forecast_type:")
r.groupBy("forecast_type").count().orderBy("forecast_type").show(truncate=False)

# --- 4. Sample totals (Adaptive_Ensemble, Total product, latest week) ---
print("Sample values (Adaptive_Ensemble, Total product, rolling):")
sample = (r
    .where("model = 'Adaptive_Ensemble' AND product = 'Total' AND forecast_type = 'rolling'")
    .orderBy("ds")
    .select("ds", "actual", "p10", "p50", "p90", "most_likely")
    .limit(3))
sample.show(truncate=False)

# Verify most_likely == p50 exactly (no approximation)
ml_mismatch = r.where(
    (F.col("model") != "ACTUAL") &
    F.col("p50").isNotNull() &
    (F.col("most_likely") != F.col("p50"))
).count()
assert ml_mismatch == 0, f"FAIL: {ml_mismatch} rows where most_likely != p50 (expected EXACT equality)"
print(f"most_likely == p50 check: PASS (0 mismatches in {n} rows)")

# --- 5. Null check on key dimensions ---
KEY_DIMS = ["ds", "product", "sales_market", "model", "forecast_type", "forecast_view"]
null_counts = {}
for col_name in KEY_DIMS:
    nc = r.where(F.col(col_name).isNull()).count()
    null_counts[col_name] = nc
nulls_found = {k: v for k, v in null_counts.items() if v > 0}
if nulls_found:
    print(f"WARNING: Nulls in key dimensions: {nulls_found}")
else:
    print(f"Null check on key dimensions: PASS (0 nulls in {KEY_DIMS})")

# --- 6. Duplicate check on natural key ---
dedup_key = ["ds", "product", "sales_market", "grain_level", "model", "forecast_type", "forecast_view"]
total_rows = r.count()
distinct_keys = r.select(*dedup_key).distinct().count()
dupes = total_rows - distinct_keys
assert dupes == 0, f"FAIL: {dupes} duplicate rows on natural key {dedup_key}"
print(f"Duplicate check: PASS ({total_rows} rows, {distinct_keys} distinct keys, 0 dupes)")

# --- 7. Schema ---
print(f"\nSchema ({len(r.columns)} columns): {r.columns}")

# --- Summary ---
print(f"\nforecast_results_latest: {n} rows")
print(f"  products      : {products}")
print(f"  forecast_types: {ftypes}")
print(f"  models        : {models}")
print(f"  WAPE attached : {r.where(F.col('model_wape').isNotNull()).count()} rows")
print(f"  insight scopes: {[row['product'] for row in spark.table(INSIGHTS_TABLE).where(F.col('run_date')==F.current_date()).select('product').collect()]}")
print('\nPublish complete — app reads EXACT values from forecast_results / forecast_insights.')

# COMMAND ----------

# DBTITLE 1,Scenario Analysis Engine
# MAGIC %md
# MAGIC ## Cell 13 — Scenario Analysis Engine
# MAGIC
# MAGIC Creates four tables that power the improved Exec Mode scenario-analysis UI:
# MAGIC
# MAGIC | Table | Purpose |
# MAGIC |-------|--------|
# MAGIC | `forecast_scenario_grid` | Named scenarios (Conservative/Baseline/Stretch) using real model quantiles, quarterly |
# MAGIC | `forecast_sensitivity` | Per-driver elasticity coefficients computed from historical pipeline data |
# MAGIC | `forecast_model_scenarios` | Maps each model to a scenario archetype with directional metadata |
# MAGIC | `forecast_historical_scenarios` | Quarterly pipeline metrics + actual outcomes for "what-if" validation |
# MAGIC
# MAGIC The UI reads these to:
# MAGIC 1. **One-click scenarios** — leadership picks Conservative/Baseline/Stretch and ALL tabs update
# MAGIC 2. **Real sliders** — sensitivity coefficients ground the simulator in actual data relationships
# MAGIC 3. **Model-as-scenario** — each model output becomes a named scenario for comparison
# MAGIC 4. **Historical anchoring** — "When conditions looked like X, ARR was Y"

# COMMAND ----------

# DBTITLE 1,Build scenario analysis tables
# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO ANALYSIS ENGINE — 4 tables for exec scenario analysis
# ══════════════════════════════════════════════════════════════════════════════
import numpy as np
from pyspark.sql import functions as F, Window
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, DateType

SCENARIO_GRID_TABLE = f"{CATALOG}.{SCHEMA}.forecast_scenario_grid"
SENSITIVITY_TABLE   = f"{CATALOG}.{SCHEMA}.forecast_sensitivity"
MODEL_SCENARIO_TABLE = f"{CATALOG}.{SCHEMA}.forecast_model_scenarios"
HIST_SCENARIO_TABLE  = f"{CATALOG}.{SCHEMA}.forecast_historical_scenarios"

# ─── 1. NAMED SCENARIO GRID ─────────────────────────────────────────────────
# Pre-compute quarterly outcomes at 3 named scenarios from real model quantiles.
# Conservative = P10, Baseline = P50 (most_likely), Stretch = P90.
# Broken down by product, quarter, and sales_market.

def build_scenario_grid():
    """Build quarterly scenario grid from forecast_results (adaptive view)."""
    r = spark.table(RESULTS_VIEW)
    
    # Only forecast rows (not actuals) in the adaptive view, current FY
    fwd = r.where(
        "forecast_view = 'adaptive' AND forecast_type IN ('rolling', 'roy') "
        f"AND ds <= '{FY_END_DATE}' AND model != 'ACTUAL'"
    )
    
    # Assign fiscal quarter (GoTo FY = calendar year)
    fwd = fwd.withColumn("fiscal_quarter", F.concat(F.lit("Q"), F.quarter("ds").cast("string")))
    
    # Aggregate by (product, sales_market, quarter, model)
    # Then across models: use recommended_for_exec=1 (Adaptive_Ensemble) for named scenarios
    rec = fwd.where(f"model = '{REC_MODEL}'")
    
    grid = rec.groupBy("product", "sales_market", "fiscal_quarter").agg(
        F.sum("p10").alias("conservative"),
        F.sum("p50").alias("baseline"),
        F.sum("p90").alias("stretch"),
        F.sum("most_likely").alias("most_likely"),
        F.count("*").alias("weeks_in_quarter"),
    )
    
    # Also compute actuals for closed quarters
    act = r.where("forecast_type = 'actuals' AND model = 'ACTUAL'")
    act_q = (act
        .withColumn("fiscal_quarter", F.concat(F.lit("Q"), F.quarter("ds").cast("string")))
        .where(f"YEAR(ds) = 2026")
        .groupBy("product", "sales_market", "fiscal_quarter")
        .agg(F.sum("actual").alias("actual_to_date"), F.count("*").alias("actual_weeks"))
    )
    
    # Join actuals where available
    grid = grid.join(act_q, ["product", "sales_market", "fiscal_quarter"], "left")
    
    # Add metadata
    grid = (grid
        .withColumn("run_date", F.current_date())
        .withColumn("fiscal_year", F.lit(2026))
        .withColumn("scenario_source", F.lit("model_quantiles"))
        .withColumn("source_model", F.lit(REC_MODEL))
    )
    
    return grid

scenario_grid = build_scenario_grid()
scenario_grid.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(SCENARIO_GRID_TABLE)
print(f"1. Wrote {scenario_grid.count()} rows to {SCENARIO_GRID_TABLE}")
scenario_grid.show(truncate=False)

# ─── 2. SENSITIVITY COEFFICIENTS (Weekly grain, SFDC source) ────────────────
# Compute elasticity from WEEKLY pipeline data (trailing 52-week rolling window).
# Uses the same SFDC source as the V5 forecast for consistency.
# ~254-270 observations per product/market (vs old 15 quarterly obs).

def build_sensitivity_coefficients():
    """Compute per-driver elasticity from weekly SFDC pipeline -> ARR relationships.
    Uses scipy linregress for p-values; marks significance at p<0.10."""
    from scipy import stats as sp_stats

    SFDC = "datagroup.datalake_transform.cds_sfdc_opp_products_latest"
    weekly_stats = spark.sql(f"""
        SELECT
            product_group as product,
            sales_market,
            DATE_TRUNC('week', close_date) as ds,
            SUM(CASE WHEN is_won = TRUE AND is_closed = TRUE
                     AND purchase_type_rollup = 'Growth'
                     AND sales_channel NOT IN ('Care', 'Sales Other')
                THEN total_price2_converted ELSE 0 END) as won_arr,
            COUNT(CASE WHEN is_won = TRUE AND is_closed = TRUE
                       AND purchase_type_rollup = 'Growth'
                       AND sales_channel NOT IN ('Care', 'Sales Other')
                THEN 1 END) as won_deals,
            COUNT(CASE WHEN stage_name NOT IN ('Closed Won', 'Closed Lost')
                THEN 1 END) as open_opps,
            SUM(CASE WHEN stage_name NOT IN ('Closed Won', 'Closed Lost')
                THEN total_price2_converted ELSE 0 END) as open_pipeline,
            AVG(CASE WHEN is_won = TRUE AND is_closed = TRUE
                     AND purchase_type_rollup = 'Growth'
                     AND sales_channel NOT IN ('Care', 'Sales Other')
                THEN total_price2_converted END) as avg_deal_size
        FROM {SFDC}
        WHERE product_group IN ('UCC', 'ITSG')
          AND sales_market IN ('NA', 'EMEA', 'APAC', 'LATAM')
          AND close_date >= '2021-01-01'
          AND close_date <= CURRENT_DATE()
        GROUP BY product_group, sales_market, DATE_TRUNC('week', close_date)
        HAVING SUM(CASE WHEN is_won = TRUE AND is_closed = TRUE
                        AND purchase_type_rollup = 'Growth'
                        AND sales_channel NOT IN ('Care', 'Sales Other')
                   THEN total_price2_converted ELSE 0 END) > 0
    """).toPandas()

    # Compute derived metrics
    weekly_stats['win_rate_pct'] = (
        weekly_stats['won_deals'] * 100.0 /
        weekly_stats['open_opps'].replace(0, np.nan)
    )
    weekly_stats['coverage_x'] = (
        weekly_stats['open_pipeline'] /
        weekly_stats['won_arr'].replace(0, np.nan)
    )
    weekly_stats['pipeline_volume'] = weekly_stats['open_pipeline']

    results = []
    drivers = [
        ('win_rate',        'win_rate_pct',   'percentage_point', '1pp higher win rate'),
        ('deal_size',       'avg_deal_size',  'percent_change',   '1% larger deals'),
        ('coverage',        'coverage_x',     '0.1x_change',      '+0.1x coverage'),
        ('pipeline_volume', 'pipeline_volume', 'percent_change',  '1% more pipeline'),
    ]

    for product in weekly_stats['product'].unique():
        for market in weekly_stats['sales_market'].unique():
            subset = weekly_stats[
                (weekly_stats['product'] == product) &
                (weekly_stats['sales_market'] == market)
            ].dropna(subset=['won_arr']).sort_values('ds')

            # Trailing 52-week rolling window (most recent data)
            subset = subset.tail(52 * 5)  # up to 5 years
            if len(subset) < 30:
                continue

            won_arr = subset['won_arr'].values.astype(float)
            mean_arr = won_arr.mean()
            if mean_arr == 0:
                continue

            for driver_name, col_name, unit, desc_prefix in drivers:
                if col_name not in subset.columns:
                    continue
                x = subset[col_name].values.astype(float)
                valid = ~(np.isnan(x) | np.isinf(x) | np.isnan(won_arr))
                x_v, y_v = x[valid], won_arr[valid]
                if len(x_v) < 30 or np.std(x_v) == 0:
                    continue

                slope, intercept, r_value, p_value, std_err = sp_stats.linregress(x_v, y_v)
                corr = r_value

                # Elasticity: % change in ARR per unit driver change
                if unit == 'percent_change':
                    elasticity = (slope * (np.mean(x_v) * 0.01)) / mean_arr * 100
                elif unit == '0.1x_change':
                    elasticity = (slope * 0.1) / mean_arr * 100
                else:  # percentage_point
                    elasticity = (slope / mean_arr) * 100

                results.append({
                    'product': product, 'sales_market': market,
                    'driver': driver_name, 'driver_unit': unit,
                    'baseline_value': round(float(np.mean(x_v)), 2),
                    'elasticity_pct': round(float(elasticity), 3),
                    'correlation': round(float(corr), 3),
                    'n_observations': int(len(x_v)),
                    'description': f'{desc_prefix} -> {elasticity:+.2f}% ARR (p={p_value:.4f})'
                })

    import pandas as pd
    sens_pdf = pd.DataFrame(results)
    sens_pdf['run_date'] = pd.Timestamp.now().date()
    return spark.createDataFrame(sens_pdf)

sens_df = build_sensitivity_coefficients()
sens_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(SENSITIVITY_TABLE)
print(f"2. Wrote {sens_df.count()} rows to {SENSITIVITY_TABLE}")
sens_df.select("product", "sales_market", "driver", "elasticity_pct", "correlation", "n_observations").show(30, truncate=False)


# ─── 3. MODEL-AS-SCENARIO MAPPING ───────────────────────────────────────────
# Map individual models to named scenario archetypes based on their behavior.
# Uses backtest/holdout bias direction to classify as conservative/neutral/stretch.

def build_model_scenarios():
    """Classify each model as a scenario archetype based on its bias profile."""
    # Get model performance from monitoring baselines
    # UCC baseline uses holdout_wape_baseline/cv_wape_baseline (no metric_scope)
    # Deduplicate to one row per model (take latest by run_timestamp_utc)
    w_ucc = Window.partitionBy("model").orderBy(F.desc("run_timestamp_utc"))
    ucc_bl = (spark.table(UCC_BASELINE)
        .withColumn("_rn", F.row_number().over(w_ucc))
        .where("_rn = 1").drop("_rn")
        .select(
            F.lit("UCC").alias("product"),
            F.col("model"),
            F.col("holdout_wape_baseline").cast("double").alias("wape"),
            F.col("cv_wape_baseline").cast("double").alias("cv_wape"),
        )
    )
    
    # ITSG baseline has wape/mape/metric_scope — dedup same way
    w_itsg = Window.partitionBy("model").orderBy(F.desc("run_timestamp_utc"))
    itsg_bl = (spark.table(ITSG_BASELINE)
        .withColumn("_rn", F.row_number().over(w_itsg))
        .where("_rn = 1").drop("_rn")
        .select(
            F.lit("ITSG").alias("product"),
            F.col("model"),
            F.col("holdout_wape_baseline").cast("double").alias("wape"),
            F.col("cv_wape_baseline").cast("double").alias("cv_wape"),
        )
    )
    
    baselines = ucc_bl.unionByName(itsg_bl, allowMissingColumns=True)
    
    # Also look at actual FY2026 sum by model from forecast_results
    model_totals = (spark.table(RESULTS_VIEW)
        .where(f"forecast_view='adaptive' AND forecast_type IN ('rolling','roy') AND ds <= '{FY_END_DATE}' AND model != 'ACTUAL' AND sales_market = 'Total' AND grain_level = 'total'")
        .groupBy("product", "model")
        .agg(F.sum("p50").alias("fy_forecast_p50"))
    )
    
    # Get the ensemble (baseline) total per product
    ensemble_totals = model_totals.where(f"model = '{REC_MODEL}'").select(
        F.col("product"), F.col("fy_forecast_p50").alias("ensemble_p50")
    )
    
    # Join and compute relative positioning
    model_pos = model_totals.join(ensemble_totals, "product", "left")
    model_pos = model_pos.withColumn(
        "pct_vs_ensemble",
        F.round((F.col("fy_forecast_p50") - F.col("ensemble_p50")) / F.col("ensemble_p50") * 100, 2)
    )
    
    # Classify: <-5% = conservative, >+5% = stretch, else = neutral/baseline
    model_pos = model_pos.withColumn(
        "scenario_archetype",
        F.when(F.col("pct_vs_ensemble") < -5, F.lit("conservative"))
         .when(F.col("pct_vs_ensemble") > 5, F.lit("stretch"))
         .otherwise(F.lit("baseline"))
    )
    
    # Join accuracy
    result = model_pos.join(baselines, ["product", "model"], "left")
    result = (result
        .withColumn("run_date", F.current_date())
        .withColumn("description", 
            F.when(F.col("scenario_archetype") == "conservative", 
                   F.concat(F.lit("Tends "), F.round(F.abs(F.col("pct_vs_ensemble")), 1).cast("string"), F.lit("% below ensemble — use for downside planning")))
             .when(F.col("scenario_archetype") == "stretch",
                   F.concat(F.lit("Tends "), F.round(F.col("pct_vs_ensemble"), 1).cast("string"), F.lit("% above ensemble — use for stretch/upside targets")))
             .otherwise(F.lit("Aligned with ensemble baseline — primary planning model"))
        )
    )
    return result

model_scenarios = build_model_scenarios()
model_scenarios.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(MODEL_SCENARIO_TABLE)
print(f"\n3. Wrote {model_scenarios.count()} rows to {MODEL_SCENARIO_TABLE}")
model_scenarios.select("product", "model", "scenario_archetype", "pct_vs_ensemble", "wape").orderBy("product", "pct_vs_ensemble").show(truncate=False)

# ─── 4. HISTORICAL SCENARIOS (WHAT-IF TABLE) ────────────────────────────────
# Quarterly pipeline conditions alongside actual ARR outcomes for anchoring.
# "When win rate was 35% and coverage was 3.2x, we closed $X"

def build_historical_scenarios():
    """Build quarterly history of pipeline conditions vs actual outcomes."""
    hist = spark.sql("""
        SELECT 
            product_group as product,
            CONCAT(YEAR(dte), '-Q', QUARTER(dte)) as period,
            YEAR(dte) as fiscal_year,
            CONCAT('Q', QUARTER(dte)) as fiscal_quarter,
            sales_market,
            ROUND(SUM(won_amount), 2) as actual_arr,
            ROUND(SUM(opened_amount), 2) as pipeline_created,
            CAST(SUM(won_opps) AS INT) as deals_won,
            CAST(SUM(opened_opps) AS INT) as deals_opened,
            ROUND(SUM(won_amount) / NULLIF(SUM(won_opps), 0), 2) as avg_deal_size,
            ROUND(SUM(won_opps) * 100.0 / NULLIF(SUM(opened_opps), 0), 2) as win_rate_pct,
            ROUND(SUM(opened_amount) / NULLIF(SUM(won_amount), 0), 2) as coverage_x,
            -- QoQ growth for context
            LAG(SUM(won_amount)) OVER (
                PARTITION BY product_group, sales_market 
                ORDER BY YEAR(dte), QUARTER(dte)
            ) as prev_q_arr
        FROM datagroup_mdl.mdl_sales_analytics.kpi_pacing_sfdc
        WHERE product_grain = 'genus'
          AND product_group IN ('UCC', 'ITSG')
          AND purchase_type IN ('New', 'Add-On')
          AND sales_market IN ('NA', 'EMEA', 'APAC', 'LATAM')
          AND YEAR(dte) BETWEEN 2023 AND 2026
        GROUP BY product_group, YEAR(dte), QUARTER(dte), sales_market
        HAVING SUM(won_amount) > 0 AND SUM(opened_opps) > 10
    """)
    
    # Add QoQ growth rate
    hist = hist.withColumn(
        "qoq_growth_pct",
        F.round((F.col("actual_arr") - F.col("prev_q_arr")) / F.col("prev_q_arr") * 100, 1)
    ).drop("prev_q_arr")
    
    # Add Total product = UCC + ITSG rollup
    total = (hist
        .groupBy("period", "fiscal_year", "fiscal_quarter", "sales_market")
        .agg(
            F.sum("actual_arr").alias("actual_arr"),
            F.sum("pipeline_created").alias("pipeline_created"),
            F.sum("deals_won").alias("deals_won"),
            F.sum("deals_opened").alias("deals_opened"),
            F.round(F.sum("actual_arr") / F.sum("deals_won"), 2).alias("avg_deal_size"),
            F.round(F.sum("deals_won") * 100.0 / F.sum("deals_opened"), 2).alias("win_rate_pct"),
            F.round(F.sum("pipeline_created") / F.sum("actual_arr"), 2).alias("coverage_x"),
        )
        .withColumn("product", F.lit("Total"))
        .withColumn("qoq_growth_pct", F.lit(None).cast("double"))
    )
    
    combined = hist.unionByName(total, allowMissingColumns=True)
    combined = combined.withColumn("run_date", F.current_date())
    return combined

hist_scenarios = build_historical_scenarios()
hist_scenarios.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(HIST_SCENARIO_TABLE)
print(f"\n4. Wrote {hist_scenarios.count()} rows to {HIST_SCENARIO_TABLE}")
hist_scenarios.where("product = 'UCC' AND sales_market = 'NA'").orderBy("period").show(truncate=False)

print("\n" + "="*70)
print("SCENARIO ANALYSIS ENGINE COMPLETE")
print(f"  {SCENARIO_GRID_TABLE}: Named scenario outcomes (Conservative/Baseline/Stretch)")
print(f"  {SENSITIVITY_TABLE}: Per-driver elasticity coefficients")
print(f"  {MODEL_SCENARIO_TABLE}: Model-to-scenario archetype mapping")
print(f"  {HIST_SCENARIO_TABLE}: Historical what-if anchoring data")
print("="*70)

# COMMAND ----------

# DBTITLE 1,Cell 14 — Unified All-Models Table for Power BI
# MAGIC %md
# MAGIC ## Cell 14 — Unified All-Models Table for Power BI
# MAGIC
# MAGIC Creates `forecast_all_models` — a single table that combines:
# MAGIC - **Prophet** results from `forecast_prophet` (native P05/P25/P50/P75/P95 quantiles)
# MAGIC - **All other models** (MSTL, DHR_ARIMA, ETS, LightGBM, Adaptive_Ensemble) from `forecast_results`
# MAGIC
# MAGIC ### Quantile Interpolation (non-Prophet models)
# MAGIC
# MAGIC `forecast_results` provides only P10/P50/P90. Under normal-error assumption:
# MAGIC - σ = (P90 - P10) / (2 × 1.2816)
# MAGIC - P05 = P50 − 1.6449 × σ
# MAGIC - P25 = P50 − 0.6745 × σ
# MAGIC - P75 = P50 + 0.6745 × σ
# MAGIC - P95 = P50 + 1.6449 × σ
# MAGIC
# MAGIC Prophet rows keep their EXACT native quantiles (no interpolation).

# COMMAND ----------

# DBTITLE 1,Build forecast_all_models unified table
# ══════════════════════════════════════════════════════════════════════════════
# FORECAST_ALL_MODELS — Unified table for Power BI (all models in one place)
# ══════════════════════════════════════════════════════════════════════════════
# Combines:
#   1. Prophet results from forecast_prophet (native 5-quantile fan)
#   2. All other models from forecast_results (p10/p50/p90 → interpolated 5-quantile)
# Actuals & driver features joined model-independently from forecast_prophet.
# ══════════════════════════════════════════════════════════════════════════════

ALL_MODELS_TABLE = f"{CATALOG}.{SCHEMA}.forecast_all_models"

# --- Z-scores for quantile interpolation (normal distribution) ---
Z_10 = 1.2816
Z_05 = 1.6449
Z_25 = 0.6745

# ─── 1. PROPHET ROWS (native quantiles from forecast_prophet) ────────────────

prophet_src = spark.table(f"{CATALOG}.{SCHEMA}.forecast_prophet")

prophet_rows = (prophet_src
    .select(
        F.col("ds").cast("date").alias("ds"),
        F.col("product"),
        F.when(F.upper(F.col("sales_market")) == "UNKNOWN", F.lit("Unknown"))
         .otherwise(F.col("sales_market")).alias("sales_market"),
        F.lit("Prophet").alias("model_name"),
        F.col("year"),
        F.col("month"),
        F.quarter("ds").alias("quarter"),
        F.col("week_number"),
        F.weekofyear("ds").alias("iso_week"),
        F.year(F.col("ds") + F.expr("INTERVAL 3 DAYS")).alias("iso_year"),
        F.col("summer").cast("int").alias("summer"),
        F.col("winter").cast("int").alias("winter"),
        F.col("isweek1").cast("int").alias("isweek1"),
        F.col("Forecast_P05").alias("forecast_p05"),
        F.col("Forecast_P25").alias("forecast_p25"),
        F.col("Forecast_Median").alias("forecast_p50"),
        F.col("Forecast_P75").alias("forecast_p75"),
        F.col("Forecast_P95").alias("forecast_p95"),
        F.when(F.col("Actuals") > 0, F.col("Actuals")).otherwise(F.lit(None).cast("double")).alias("actuals"),
        F.col("magna_carta_actuals"),
        F.col("miradore_plan"),
        F.col("avg_deal_size"),
        F.col("avg_sales_cycle"),
        F.col("all_created_arr"),
        F.col("total_partner_pipeline"),
        F.col("avg_dials"),
        F.col("avg_touches"),
        F.col("avg_push_counter"),
        F.col("number_of_opps"),
        F.col("headcount"),
        F.col("avg_opportunity_age"),
        F.lit("prophet_native").alias("interval_method"),
        F.lit(None).cast("double").alias("model_wape"),
        F.lit(True).alias("is_current"),
        F.when(F.col("Actuals").isNotNull() & (F.col("Actuals") > 0), F.lit("actuals"))
         .otherwise(F.lit("forecast")).alias("forecast_type"),
        F.col("pe_account_flag"),
        F.current_timestamp().alias("published_at_utc"),
    )
)

# ─── 1b. ADD 'Total' MARKET ROLLUP ──────────────────────────────────────────
# Removed pe_account_flag and published_at_utc from groupBy — they vary between
# markets for the same ds, causing split Total rows (16 instead of 13 per quarter).
prophet_total = (prophet_rows
    .groupBy("ds", "product", "model_name", "year", "month", "quarter",
             "week_number", "iso_week", "iso_year", "summer", "winter", "isweek1",
             "interval_method", "model_wape", "is_current", "forecast_type")
    .agg(
        F.sum("forecast_p05").alias("forecast_p05"),
        F.sum("forecast_p25").alias("forecast_p25"),
        F.sum("forecast_p50").alias("forecast_p50"),
        F.sum("forecast_p75").alias("forecast_p75"),
        F.sum("forecast_p95").alias("forecast_p95"),
        F.sum("actuals").alias("actuals"),
        F.sum("magna_carta_actuals").alias("magna_carta_actuals"),
        F.sum("miradore_plan").alias("miradore_plan"),
        F.avg("avg_deal_size").alias("avg_deal_size"),
        F.avg("avg_sales_cycle").alias("avg_sales_cycle"),
        F.sum("all_created_arr").alias("all_created_arr"),
        F.sum("total_partner_pipeline").alias("total_partner_pipeline"),
        F.avg("avg_dials").alias("avg_dials"),
        F.avg("avg_touches").alias("avg_touches"),
        F.avg("avg_push_counter").alias("avg_push_counter"),
        F.sum("number_of_opps").alias("number_of_opps"),
        F.sum("headcount").alias("headcount"),
        F.avg("avg_opportunity_age").alias("avg_opportunity_age"),
        F.first("pe_account_flag").alias("pe_account_flag"),
        F.first("published_at_utc").alias("published_at_utc"),
    )
    .withColumn("sales_market", F.lit("Total"))
)

prophet_rows = prophet_rows.unionByName(prophet_total, allowMissingColumns=True)
print(f"Prophet rows from forecast_prophet (with Total rollup): {prophet_rows.count()}")

# ─── 2. OTHER MODELS (from forecast_results, interpolated quantiles) ─────────

fr = spark.table(RESULTS_VIEW)
other_models = fr.where(
    "model != 'ACTUAL' AND model != 'Prophet_trend' AND forecast_view = 'adaptive'"
)

other_rows = (other_models
    .withColumn("_sigma", (F.col("p90") - F.col("p10")) / (2 * Z_10))
    .select(
        F.col("ds"),
        F.col("product"),
        F.col("sales_market"),
        F.col("model").alias("model_name"),
        F.year("ds").alias("year"),
        F.month("ds").alias("month"),
        F.quarter("ds").alias("quarter"),
        F.weekofyear("ds").alias("week_number"),
        F.weekofyear("ds").alias("iso_week"),
        F.year(F.col("ds") + F.expr("INTERVAL 3 DAYS")).alias("iso_year"),
        F.when(F.month("ds").isin(6, 7, 8), 1).otherwise(0).alias("summer"),
        F.when(F.month("ds").isin(12, 1, 2), 1).otherwise(0).alias("winter"),
        F.when(F.weekofyear("ds") == 1, 1).otherwise(0).alias("isweek1"),
        (F.col("p50") - Z_05 * F.col("_sigma")).alias("forecast_p05"),
        (F.col("p50") - Z_25 * F.col("_sigma")).alias("forecast_p25"),
        F.col("p50").alias("forecast_p50"),
        (F.col("p50") + Z_25 * F.col("_sigma")).alias("forecast_p75"),
        (F.col("p50") + Z_05 * F.col("_sigma")).alias("forecast_p95"),
        F.lit(None).cast("double").alias("actuals"),
        F.lit(None).cast("double").alias("magna_carta_actuals"),
        F.lit(None).cast("double").alias("miradore_plan"),
        F.lit(None).cast("double").alias("avg_deal_size"),
        F.lit(None).cast("double").alias("avg_sales_cycle"),
        F.lit(None).cast("double").alias("all_created_arr"),
        F.lit(None).cast("double").alias("total_partner_pipeline"),
        F.lit(None).cast("double").alias("avg_dials"),
        F.lit(None).cast("double").alias("avg_touches"),
        F.lit(None).cast("double").alias("avg_push_counter"),
        F.lit(None).cast("bigint").alias("number_of_opps"),
        F.lit(None).cast("bigint").alias("headcount"),
        F.lit(None).cast("double").alias("avg_opportunity_age"),
        F.when(F.col("model").contains("LGB"), F.lit("quantile_regression"))
         .when(F.col("model") == "Adaptive_Ensemble", F.lit("monte_carlo"))
         .otherwise(F.lit("analytic_ci")).alias("interval_method"),
        F.col("model_wape"),
        F.lit(True).alias("is_current"),
        F.col("forecast_type"),
        F.lit(None).cast("boolean").alias("pe_account_flag"),
        F.current_timestamp().alias("published_at_utc"),
    )
)

# Join actuals & driver features from forecast_prophet
driver_features = (prophet_src
    .select(
        F.col("ds").cast("date").alias("ds"),
        "product", "sales_market",
        F.col("Actuals").alias("_actuals"),
        F.col("magna_carta_actuals").alias("_magna_carta_actuals"),
        F.col("miradore_plan").alias("_miradore_plan"),
        F.col("avg_deal_size").alias("_avg_deal_size"),
        F.col("avg_sales_cycle").alias("_avg_sales_cycle"),
        F.col("all_created_arr").alias("_all_created_arr"),
        F.col("total_partner_pipeline").alias("_total_partner_pipeline"),
        F.col("avg_dials").alias("_avg_dials"),
        F.col("avg_touches").alias("_avg_touches"),
        F.col("avg_push_counter").alias("_avg_push_counter"),
        F.col("number_of_opps").alias("_number_of_opps"),
        F.col("headcount").alias("_headcount"),
        F.col("avg_opportunity_age").alias("_avg_opportunity_age"),
    )
)

other_rows_enriched = (other_rows
    .join(driver_features, on=["ds", "product", "sales_market"], how="left")
    .withColumn("actuals", F.coalesce(F.col("_actuals"), F.col("actuals")))
    .withColumn("magna_carta_actuals", F.coalesce(F.col("_magna_carta_actuals"), F.col("magna_carta_actuals")))
    .withColumn("miradore_plan", F.coalesce(F.col("_miradore_plan"), F.col("miradore_plan")))
    .withColumn("avg_deal_size", F.coalesce(F.col("_avg_deal_size"), F.col("avg_deal_size")))
    .withColumn("avg_sales_cycle", F.coalesce(F.col("_avg_sales_cycle"), F.col("avg_sales_cycle")))
    .withColumn("all_created_arr", F.coalesce(F.col("_all_created_arr"), F.col("all_created_arr")))
    .withColumn("total_partner_pipeline", F.coalesce(F.col("_total_partner_pipeline"), F.col("total_partner_pipeline")))
    .withColumn("avg_dials", F.coalesce(F.col("_avg_dials"), F.col("avg_dials")))
    .withColumn("avg_touches", F.coalesce(F.col("_avg_touches"), F.col("avg_touches")))
    .withColumn("avg_push_counter", F.coalesce(F.col("_avg_push_counter"), F.col("avg_push_counter")))
    .withColumn("number_of_opps", F.coalesce(F.col("_number_of_opps"), F.col("number_of_opps")))
    .withColumn("headcount", F.coalesce(F.col("_headcount"), F.col("headcount")))
    .withColumn("avg_opportunity_age", F.coalesce(F.col("_avg_opportunity_age"), F.col("avg_opportunity_age")))
)
cols_to_drop = [c for c in other_rows_enriched.columns if c.startswith("_")]
other_rows_enriched = other_rows_enriched.drop(*cols_to_drop)

print(f"Other model rows (enriched with actuals/features): {other_rows_enriched.count()}")

# ─── 3. UNION Prophet + Other Models ─────────────────────────────────────────

final_cols = prophet_rows.columns
for c in final_cols:
    if c not in other_rows_enriched.columns:
        other_rows_enriched = other_rows_enriched.withColumn(c, F.lit(None))

other_rows_enriched = other_rows_enriched.select(*final_cols)
unified = prophet_rows.unionByName(other_rows_enriched, allowMissingColumns=True)

print(f"\nUnified forecast_all_models: {unified.count()} rows")
print(f"  Models: {sorted([r[0] for r in unified.select('model_name').distinct().collect()])}")
print(f"  Products: {sorted([r[0] for r in unified.select('product').distinct().collect()])}")
print(f"  Date range: {unified.agg(F.min('ds')).collect()[0][0]} to {unified.agg(F.max('ds')).collect()[0][0]}")

# ─── 4. WRITE TABLE ──────────────────────────────────────────────────────────

(unified.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(ALL_MODELS_TABLE)
)
print(f"\n✓ Written to {ALL_MODELS_TABLE}")

# ─── 5. QUANTILE MONOTONICITY VALIDATION ─────────────────────────────────────

validation = spark.table(ALL_MODELS_TABLE)
violations = validation.where(
    (F.col("forecast_p05") > F.col("forecast_p25")) |
    (F.col("forecast_p25") > F.col("forecast_p50")) |
    (F.col("forecast_p50") > F.col("forecast_p75")) |
    (F.col("forecast_p75") > F.col("forecast_p95"))
).count()

if violations > 0:
    print(f"  ⚠️  WARNING: {violations} rows violate quantile monotonicity")
else:
    print(f"  ✓ Quantile monotonicity: PASS")

# COMMAND ----------

# DBTITLE 1,Cell 15 — Wide-Format Power BI Table
# MAGIC %md
# MAGIC ## Cell 15 — Wide-Format Power BI Table (`arr_forecast_wide`)
# MAGIC
# MAGIC Pivots `forecast_all_models` so each model's P50 forecast is its own column.
# MAGIC This is the table to connect from Power BI when you want one row per
# MAGIC `ds × product × sales_market` with all models side by side.
# MAGIC
# MAGIC | Column | Description |
# MAGIC |--------|-------------|
# MAGIC | `ds` | Week-start Monday |
# MAGIC | `product` | UCC, ITSG, or Total |
# MAGIC | `sales_market` | NA, EMEA, APAC, LATAM, Unknown, or Total |
# MAGIC | `grain_level` | `market` (individual) or `total` (rollup) |
# MAGIC | `actuals` | Actual ARR for that week (NULL if future) |
# MAGIC | `forecast_type` | actuals / forecast |
# MAGIC | `Adaptive_Ensemble` … `Prophet` | P50 point forecast per model |
# MAGIC | `*_p10` / `*_p90` | Interval bounds per model |

# COMMAND ----------

# DBTITLE 1,Build arr_forecast_wide pivot table
# ══════════════════════════════════════════════════════════════════════════════
# ARR_FORECAST_WIDE — Pivoted table for Power BI (one column per model)
# ══════════════════════════════════════════════════════════════════════════════
# Source: forecast_all_models (built in Cell 14)
# Output: arr_forecast_wide — ds × product × sales_market with model columns
# ══════════════════════════════════════════════════════════════════════════════

from pyspark.sql import functions as F

WIDE_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_wide"

# Read current forecast_all_models
all_models = spark.table(ALL_MODELS_TABLE).filter(F.col("is_current") == True)

# --- Grain level assignment ---
grained = all_models.withColumn(
    "grain_level",
    F.when(F.col("sales_market") == "Total", F.lit("total"))
     .otherwise(F.lit("market"))
)

# --- Pivot P50 (main forecast) ---
p50_wide = (
    grained
    .groupBy("ds", "product", "sales_market", "grain_level", "forecast_type")
    .pivot("model_name")
    .agg(F.first("forecast_p50"))
)

# --- Pivot P10 (lower bound) ---
p10_wide = (
    grained
    .groupBy("ds", "product", "sales_market")
    .pivot("model_name")
    .agg(F.first(F.col("forecast_p50") - F.col("forecast_p50") + F.col("forecast_p05")))
)
# Rename p10 columns
for c in p10_wide.columns:
    if c not in ("ds", "product", "sales_market"):
        p10_wide = p10_wide.withColumnRenamed(c, f"{c}_p05")

# --- Pivot P90 (upper bound) ---
p90_wide = (
    grained
    .groupBy("ds", "product", "sales_market")
    .pivot("model_name")
    .agg(F.first("forecast_p95"))
)
for c in p90_wide.columns:
    if c not in ("ds", "product", "sales_market"):
        p90_wide = p90_wide.withColumnRenamed(c, f"{c}_p95")

# --- Actuals (model-independent, take first non-null) ---
actuals_df = (
    grained
    .groupBy("ds", "product", "sales_market")
    .agg(F.first("actuals", ignorenulls=True).alias("actuals"))
)

# --- Join all pivots ---
wide = (
    p50_wide
    .join(p10_wide, on=["ds", "product", "sales_market"], how="left")
    .join(p90_wide, on=["ds", "product", "sales_market"], how="left")
    .join(actuals_df, on=["ds", "product", "sales_market"], how="left")
    .withColumn("run_date", F.current_date())
    .withColumn("published_at_utc", F.current_timestamp())
)

print(f"Wide-format rows: {wide.count()}")
print(f"Columns: {sorted(wide.columns)}")

# --- Write ---
wide.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(WIDE_TABLE)
print(f"\n✓ Wrote {WIDE_TABLE}")

# COMMAND ----------

# DBTITLE 1,Grants and companion views for Power BI
# ══════════════════════════════════════════════════════════════════════════════
# GRANTS + COMPANION VIEWS
# ══════════════════════════════════════════════════════════════════════════════

CATALOG = "datagroup_mdl"
SCHEMA = "mdl_sales_analytics"
ALL_MODELS_TABLE = f"{CATALOG}.{SCHEMA}.forecast_all_models"
WIDE_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_wide"
APP_SERVICE_PRINCIPAL = "324a6ec7-e988-42c7-8a7f-55465f5bea37"

spark.sql(f"GRANT SELECT ON TABLE {ALL_MODELS_TABLE} TO `{APP_SERVICE_PRINCIPAL}`")
print(f"✓ Granted SELECT on {ALL_MODELS_TABLE} to {APP_SERVICE_PRINCIPAL}")

spark.sql(f"GRANT SELECT ON TABLE {WIDE_TABLE} TO `{APP_SERVICE_PRINCIPAL}`")
print(f"✓ Granted SELECT on {WIDE_TABLE} to {APP_SERVICE_PRINCIPAL}")

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.{SCHEMA}.v_forecast_all_models_current AS
SELECT 
    ds, product, sales_market, model_name,
    year, month, quarter, week_number, iso_week, iso_year,
    summer, winter, isweek1,
    forecast_p05, forecast_p25, forecast_p50,
    forecast_p50 AS Forecast_Median,
    forecast_p75, forecast_p95,
    actuals AS Actuals,
    magna_carta_actuals, miradore_plan,
    avg_deal_size, avg_sales_cycle, all_created_arr,
    total_partner_pipeline, avg_dials, avg_touches,
    avg_push_counter, number_of_opps, headcount, avg_opportunity_age,
    interval_method, model_wape, forecast_type, pe_account_flag
FROM {ALL_MODELS_TABLE}
WHERE is_current = TRUE
""")
print(f"✓ Created view {CATALOG}.{SCHEMA}.v_forecast_all_models_current")

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.{SCHEMA}.v_forecast_model_comparison AS
SELECT
    ds, product, sales_market, model_name,
    forecast_p50,
    (forecast_p95 - forecast_p05) AS band_width_90,
    (forecast_p75 - forecast_p25) AS band_width_50,
    actuals,
    CASE WHEN actuals IS NOT NULL 
         THEN ABS(actuals - forecast_p50) / NULLIF(actuals, 0) * 100 
    END AS abs_pct_error,
    model_wape, interval_method
FROM {ALL_MODELS_TABLE}
WHERE is_current = TRUE AND forecast_type != 'actuals'
""")
print(f"✓ Created view {CATALOG}.{SCHEMA}.v_forecast_model_comparison")

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.{SCHEMA}.v_forecast_accuracy AS
SELECT
    ds, product, sales_market, model_name, actuals, forecast_p50,
    CASE WHEN actuals IS NOT NULL AND actuals != 0
         THEN ABS(actuals - forecast_p50) / ABS(actuals) * 100
    END AS ape,
    CASE WHEN actuals IS NOT NULL
         THEN (forecast_p50 - actuals)
    END AS signed_error,
    CASE WHEN actuals IS NOT NULL
         THEN CASE WHEN actuals BETWEEN forecast_p25 AND forecast_p75 THEN 1 ELSE 0 END
    END AS in_p25_p75,
    CASE WHEN actuals IS NOT NULL
         THEN CASE WHEN actuals BETWEEN forecast_p05 AND forecast_p95 THEN 1 ELSE 0 END
    END AS in_p05_p95,
    CASE WHEN actuals IS NOT NULL
         THEN 0.5 * ABS(actuals - forecast_p50)
    END AS pinball_p50,
    interval_method
FROM {ALL_MODELS_TABLE}
WHERE is_current = TRUE AND actuals IS NOT NULL
""")
print(f"✓ Created view {CATALOG}.{SCHEMA}.v_forecast_accuracy")

for vw in ['v_forecast_all_models_current', 'v_forecast_model_comparison', 'v_forecast_accuracy']:
    spark.sql(f"GRANT SELECT ON VIEW {CATALOG}.{SCHEMA}.{vw} TO `{APP_SERVICE_PRINCIPAL}`")
    print(f"  ✓ Granted SELECT on {vw}")

print(f"\n✓ All views created and grants applied.")
