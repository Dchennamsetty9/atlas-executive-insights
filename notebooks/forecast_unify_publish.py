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
        "forecast_type", "forecast_view", "actual", "p10", "p50", "p90", "most_likely",
        "recommended_for_exec", "source_run_ts", "published_at_utc"]
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
# MAGIC ## Cell 5 — Pull actuals (CBE current + arr_forecast_v2 historical)
# MAGIC
# MAGIC Current actuals (2026+) from CBE tables (TRUE Growth ARR from SFDC).
# MAGIC Historical actuals (2022-2025) from `arr_forecast_v2` for UCC + Total only
# MAGIC (ITSG values there are inflated — not Growth ARR). This gives the Multi-Year
# MAGIC seasonality overlay full year-over-year coverage.

# COMMAND ----------

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
            F.lit(None).cast("double").alias("p50"),
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

# ── Historical actuals from arr_forecast_v2 (pre-CBE window) ─────────────────
# The CBE tables start ~2025-12-29. For the Multi-Year seasonality overlay,
# the app needs 2022-2025 actuals. UCC actuals in arr_forecast_v2 are correct
# (Growth ARR). ITSG actuals there are inflated (all revenue, not Growth) so
# we only pull UCC + Total from arr_forecast_v2 for the historical window.

def build_historical_actuals_from_v2(cbe_earliest_ds):
    """Pull UCC + Total historical actuals from arr_forecast_v2 for dates
    BEFORE the CBE window starts. These give the Multi-Year tab full YoY data."""
    ARR_V2 = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"
    try:
        v2 = spark.table(ARR_V2)
    except Exception as exc:
        print(f"  WARN arr_forecast_v2 unavailable: {exc}")
        return None

    mkt = (F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"), F.lit("Total"))
            .when(F.upper(F.trim(F.col("sales_market"))) == "UNKNOWN", F.lit("Unknown"))
            .otherwise(F.trim(F.col("sales_market"))))

    # Only UCC rows (ITSG values are inflated in this table — not Growth ARR).
    # DO NOT include 'Total' — it includes ALL product revenue (not Growth-only).
    # The Total rollup in Cell 6 will compute correct Total = UCC + ITSG.
    out = (v2
        .where(f"forecast_type = 'actuals' AND ds < '{cbe_earliest_ds}'")
        .where("product = 'UCC'")
        .select(
            F.current_date().alias("run_date"),
            F.to_date("ds").alias("ds"),
            F.col("product"),
            mkt.alias("sales_market"),
            F.lit("total").alias("grain_level"),
            F.lit("ACTUAL").alias("model"),
            F.lit("actuals").alias("forecast_type"),
            F.lit("adaptive").alias("forecast_view"),
            F.col("Actuals").cast("double").alias("actual"),
            F.lit(None).cast("double").alias("p10"),
            F.lit(None).cast("double").alias("p50"),
            F.lit(None).cast("double").alias("p90"),
            F.col("Actuals").cast("double").alias("most_likely"),
            F.lit(0).cast("bigint").alias("recommended_for_exec"),
            F.lit(None).cast("timestamp").alias("source_run_ts"),
            F.current_timestamp().alias("published_at_utc"),
        ).select(*BASE)
        .where("actual IS NOT NULL")  # skip nulls
    )
    n = out.count()
    print(f"  Historical actuals from arr_forecast_v2 (pre-CBE): {n} rows")
    return out

# Determine the earliest date in CBE actuals to avoid overlap
cbe_min_ds = "2025-12-29"  # CBE window start (aligned Monday before Jan 1 2026)
if ucc_actuals is not None:
    _cbe_min = ucc_actuals.agg(F.min("ds")).collect()[0][0]
    if _cbe_min:
        cbe_min_ds = str(_cbe_min)

hist_actuals = build_historical_actuals_from_v2(cbe_min_ds)

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
         F.sum("p50").alias("p50"),
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
            tot = df[df["grain_level"].astype(str).str.lower() == "total"].copy()
        else:
            tot = df[(df["grain_level"].astype(str).str.lower() == "market")
                     & (df["sales_market"].astype(str).str.upper() == str(region).upper())].copy()
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
    narrative = (f"{label} {_pl} landing is {_fmt_m(s['most_likely'])} "
                 f"({_fmt_m(s['qtd'])} realized + forecast), "
                 f"ranging {_fmt_m(s['worst'])} to {_fmt_m(s['best'])}{yoy_txt}. "
                 f"Forecast {momentum_desc.get(s['momentum'], 'stable')}.")

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

rows, stats = [], {}
for product in sorted(res["product"].dropna().unique()):
    if product == "Total":
        continue
    s = _stats(res[res["product"] == product])
    if not s:
        continue
    stats[product] = s
    payload = _render(s, product)
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
    payload = _render(agg, "Total portfolio", product_stats=stats)
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
            tot = df[df["grain_level"].astype(str).str.lower() == "total"].copy()
        else:
            tot = df[(df["grain_level"].astype(str).str.lower() == "market")
                     & (df["sales_market"].astype(str).str.upper() == str(region).upper())].copy()
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
    l AS (
        SELECT *, LEAST(
            COALESCE(mape_ensemble, 1e9),
            COALESCE(mape_ets, 1e9), COALESCE(mape_prophet, 1e9),
            COALESCE(mape_lightgbm, 1e9), COALESCE(mape_mstl_v2, 1e9),
            COALESCE(mape_dhr_arima, 1e9)) AS lv
        FROM m
    )
    SELECT product, sales_market, mape_ensemble, mape_ets, mape_prophet, mape_lightgbm,
           mape_mstl_v2, mape_dhr_arima,
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
from pyspark.sql import Window
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

# ─── 2. SENSITIVITY COEFFICIENTS ────────────────────────────────────────────
# Compute elasticity: how much does quarterly ARR change when a driver changes?
# Based on historical quarterly data from kpi_pacing_sfdc.

def build_sensitivity_coefficients():
    """Compute per-driver elasticity from historical pipeline → ARR relationships."""
    qtr_stats = spark.sql("""
        SELECT 
            product_group as product,
            CONCAT('Q', QUARTER(dte)) as fiscal_quarter,
            YEAR(dte) as fiscal_year,
            sales_market,
            SUM(won_amount) as won_arr,
            SUM(opened_amount) as opened_arr,
            SUM(won_opps) as won_deals,
            SUM(opened_opps) as opened_deals,
            ROUND(SUM(won_amount) / NULLIF(SUM(won_opps), 0), 2) as avg_deal_size,
            ROUND(SUM(won_opps) * 100.0 / NULLIF(SUM(opened_opps), 0), 2) as win_rate_pct,
            ROUND(SUM(opened_amount) / NULLIF(SUM(won_amount), 0), 2) as coverage_x
        FROM datagroup_mdl.mdl_sales_analytics.kpi_pacing_sfdc
        WHERE product_grain = 'genus'
          AND product_group IN ('UCC', 'ITSG')
          AND purchase_type IN ('New', 'Add-On')
          AND sales_market IN ('NA', 'EMEA', 'APAC', 'LATAM')
          AND YEAR(dte) BETWEEN 2023 AND 2026
        GROUP BY product_group, QUARTER(dte), YEAR(dte), sales_market
        HAVING SUM(won_amount) > 0 AND SUM(opened_opps) > 10
    """)
    
    # Convert to pandas for regression
    pdf = qtr_stats.toPandas()
    
    results = []
    for product in pdf['product'].unique():
        for market in pdf['sales_market'].unique():
            subset = pdf[(pdf['product'] == product) & (pdf['sales_market'] == market)]
            if len(subset) < 4:
                continue
            
            won_arr = subset['won_arr'].values.astype(float)
            mean_arr = won_arr.mean()
            if mean_arr == 0:
                continue
            
            # Win rate elasticity: % change in ARR per 1pp change in win rate
            wr = subset['win_rate_pct'].values.astype(float)
            if wr.std() > 0 and len(wr) >= 4:
                corr = np.corrcoef(wr, won_arr)[0, 1]
                slope = corr * won_arr.std() / wr.std()  # linear regression slope
                elasticity_wr = (slope / mean_arr) * 100  # % ARR change per 1pp win rate
                results.append({
                    'product': product, 'sales_market': market,
                    'driver': 'win_rate', 'driver_unit': 'percentage_point',
                    'baseline_value': round(float(wr.mean()), 1),
                    'elasticity_pct': round(float(elasticity_wr), 3),
                    'correlation': round(float(corr), 3),
                    'n_observations': int(len(subset)),
                    'description': f'1pp higher win rate -> +{elasticity_wr:.1f}% ARR'
                })
            
            # Deal size elasticity: % change in ARR per 1% change in deal size
            ds_val = subset['avg_deal_size'].values.astype(float)
            if ds_val.std() > 0 and len(ds_val) >= 4:
                corr = np.corrcoef(ds_val, won_arr)[0, 1]
                # Normalize: 1% deal size change
                slope = corr * won_arr.std() / ds_val.std()
                elasticity_ds = (slope * (ds_val.mean() * 0.01)) / mean_arr * 100
                results.append({
                    'product': product, 'sales_market': market,
                    'driver': 'deal_size', 'driver_unit': 'percent_change',
                    'baseline_value': round(float(ds_val.mean()), 0),
                    'elasticity_pct': round(float(elasticity_ds), 3),
                    'correlation': round(float(corr), 3),
                    'n_observations': int(len(subset)),
                    'description': f'1% larger deals -> +{elasticity_ds:.2f}% ARR'
                })
            
            # Coverage elasticity: % change in ARR per 0.1x coverage change
            cov = subset['coverage_x'].values.astype(float)
            if cov.std() > 0 and len(cov) >= 4:
                corr = np.corrcoef(cov, won_arr)[0, 1]
                slope = corr * won_arr.std() / cov.std()
                elasticity_cov = (slope * 0.1) / mean_arr * 100  # per 0.1x coverage
                results.append({
                    'product': product, 'sales_market': market,
                    'driver': 'coverage', 'driver_unit': '0.1x_change',
                    'baseline_value': round(float(cov.mean()), 2),
                    'elasticity_pct': round(float(elasticity_cov), 3),
                    'correlation': round(float(corr), 3),
                    'n_observations': int(len(subset)),
                    'description': f'+0.1x coverage -> {elasticity_cov:+.2f}% ARR'
                })
            
            # Volume (opened deals) elasticity: % ARR per 1% more opened deals
            od = subset['opened_deals'].values.astype(float)
            if od.std() > 0 and len(od) >= 4:
                corr = np.corrcoef(od, won_arr)[0, 1]
                slope = corr * won_arr.std() / od.std()
                elasticity_od = (slope * (od.mean() * 0.01)) / mean_arr * 100
                results.append({
                    'product': product, 'sales_market': market,
                    'driver': 'pipeline_volume', 'driver_unit': 'percent_change',
                    'baseline_value': round(float(od.mean()), 0),
                    'elasticity_pct': round(float(elasticity_od), 3),
                    'correlation': round(float(corr), 3),
                    'n_observations': int(len(subset)),
                    'description': f'1% more opened deals -> +{elasticity_od:.2f}% ARR'
                })
    
    sens_df = spark.createDataFrame(results)
    sens_df = sens_df.withColumn("run_date", F.current_date())
    return sens_df

sensitivity = build_sensitivity_coefficients()
sensitivity.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(SENSITIVITY_TABLE)
print(f"\n2. Wrote {sensitivity.count()} rows to {SENSITIVITY_TABLE}")
sensitivity.where("sales_market = 'NA'").orderBy("product", "driver").show(truncate=False)

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

# DBTITLE 1,Grants and companion views for Power BI
# ══════════════════════════════════════════════════════════════════════════════
# GRANTS + COMPANION VIEWS
# ══════════════════════════════════════════════════════════════════════════════

CATALOG = "datagroup_mdl"
SCHEMA = "mdl_sales_analytics"
ALL_MODELS_TABLE = f"{CATALOG}.{SCHEMA}.forecast_all_models"
APP_SERVICE_PRINCIPAL = "324a6ec7-e988-42c7-8a7f-55465f5bea37"

spark.sql(f"GRANT SELECT ON TABLE {ALL_MODELS_TABLE} TO `{APP_SERVICE_PRINCIPAL}`")
print(f"✓ Granted SELECT on {ALL_MODELS_TABLE} to {APP_SERVICE_PRINCIPAL}")

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
