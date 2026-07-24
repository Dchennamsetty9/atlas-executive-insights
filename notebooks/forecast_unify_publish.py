# Databricks notebook source
# MAGIC %md
# MAGIC # Forecast Unify & Publish
# MAGIC
# MAGIC Consolidates the per-product V5 forecasting outputs into **one results table**
# MAGIC and **one AI-insights table** that the executive app reads directly — with all
# MAGIC information every Forecasting-panel tab needs.
# MAGIC
# MAGIC **Sources (verified via Unity Catalog):**
# MAGIC - `ucc_forecast_v5`, `itsg_forecast_v5` — per-model forward forecast (p10/p50/p90).
# MAGIC   Note: `ucc.ds` is DATE, `itsg.ds` is TIMESTAMP → both cast to DATE.
# MAGIC - `arr_forecast_v2` — source of **actuals** (Overview/YTD/Monthly/Multi-Year tabs).
# MAGIC - `ucc_forecast_monitoring_baseline` / `itsg_forecast_monitoring_baseline` —
# MAGIC   per-model **WAPE/MAPE** (Accuracy tab).
# MAGIC
# MAGIC **Design decisions (confirmed with Dileep):**
# MAGIC 1. Actuals pulled from `arr_forecast_v2.Actuals`.
# MAGIC 2. Accuracy = per-model WAPE (relabelled from MAPE in the UI).
# MAGIC 3. Forward rows tagged both `rolling` (next 13 wks) and `roy` (rest of year).
# MAGIC 4. `Total` = UCC + ITSG, summed in this notebook.
# MAGIC
# MAGIC **Outputs:** `forecast_results` (+ `forecast_results_latest` view),
# MAGIC `forecast_insights`, `forecast_publish_log`. GRANTed to the app service principal.
# MAGIC
# MAGIC **Schedule:** daily ~07:00 America/New_York (see `forecast_unify_daily` in `databricks.yml`).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 1 — Config

# COMMAND ----------

from datetime import timedelta, datetime, timezone

CATALOG = "datagroup_mdl"
SCHEMA  = "mdl_sales_analytics"

UCC_SRC       = f"{CATALOG}.{SCHEMA}.ucc_forecast_v5"
ITSG_SRC      = f"{CATALOG}.{SCHEMA}.itsg_forecast_v5"
ACTUALS_SRC   = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"          # source of Actuals
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

APP_SERVICE_PRINCIPAL = "324a6ec7-e988-42c7-8a7f-55465f5bea37"
REC_MODEL       = "Adaptive_Ensemble"   # the model flagged recommended_for_exec
ROLLING_WEEKS   = 13
SCHEMA_VERSION  = "2.0"

# Canonical unified schema (long format — one row per model per week per scenario).
BASE = ["run_date", "ds", "product", "sales_market", "grain_level", "model",
        "forecast_type", "actual", "p10", "p50", "p90", "most_likely",
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
# MAGIC ## Cell 3 — Normalize forecasts to the canonical schema
# MAGIC
# MAGIC `run_date` = publish date (this run), so the daily `replaceWhere` overwrite is
# MAGIC idempotent; source lineage is kept in `source_run_ts`. `ds` cast to DATE to
# MAGIC reconcile the UCC(date)/ITSG(timestamp) mismatch.

# COMMAND ----------

from pyspark.sql import functions as F

def normalize_forecast(df, product):
    if df is None:
        return None
    cols = set(df.columns)
    out = (df
        .withColumn("product", F.lit(product))
        .withColumn("run_date", F.current_date())
        .withColumn("published_at_utc", F.current_timestamp())
        .withColumn("ds", F.to_date(F.col("ds")))                 # unify DATE type
        .withColumn("most_likely", F.col("p50"))
        .withColumn("actual", F.lit(None).cast("double"))
        .withColumn("forecast_type", F.lit(None).cast("string"))  # set in Cell 4
        .withColumn("source_run_ts",
                    F.col("run_timestamp_utc") if "run_timestamp_utc" in cols
                    else F.lit(None).cast("timestamp")))
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
# MAGIC ## Cell 4 — Tag forecast_type (rolling = next 13 wks, roy = rest of year)
# MAGIC
# MAGIC Forward weeks are emitted twice so both panel views work: every forward week
# MAGIC as `roy`, and the first 13 weeks additionally as `rolling`.

# COMMAND ----------

min_ds = fc.agg(F.min("ds")).collect()[0][0]
rolling_cutoff = min_ds + timedelta(weeks=ROLLING_WEEKS - 1)

rolling = fc.where(F.col("ds") <= F.lit(rolling_cutoff)).withColumn("forecast_type", F.lit("rolling"))
roy     = fc.withColumn("forecast_type", F.lit("roy"))
forecasts = rolling.unionByName(roy)
print(f"Forecast rows after rolling/roy split: {forecasts.count()} (cutoff {rolling_cutoff})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 5 — Pull actuals from `arr_forecast_v2`

# COMMAND ----------

def build_actuals():
    try:
        av2 = spark.table(ACTUALS_SRC)
    except Exception as exc:
        print(f"  WARN actuals source unavailable: {exc}")
        return None
    grain = (F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"), F.lit("total"))
              .otherwise(F.lit("market")))
    mkt = (F.when(F.upper(F.trim(F.col("sales_market"))).isin("ALL", "TOTAL"), F.lit("Total"))
            .when(F.upper(F.trim(F.col("sales_market"))) == "UNKNOWN", F.lit("Unknown"))
            .otherwise(F.trim(F.col("sales_market"))))
    return (av2
        .where("forecast_type = 'actuals' AND Actuals IS NOT NULL AND product IN ('UCC','ITSG')")
        .select(
            F.current_date().alias("run_date"),
            F.to_date("ds").alias("ds"),
            F.col("product"),
            mkt.alias("sales_market"),
            grain.alias("grain_level"),
            F.lit("ACTUAL").alias("model"),
            F.lit("actuals").alias("forecast_type"),
            F.col("Actuals").cast("double").alias("actual"),
            F.lit(None).cast("double").alias("p10"),
            F.lit(None).cast("double").alias("p50"),
            F.lit(None).cast("double").alias("p90"),
            F.col("Actuals").cast("double").alias("most_likely"),
            F.lit(0).cast("bigint").alias("recommended_for_exec"),
            F.lit(None).cast("timestamp").alias("source_run_ts"),
            F.current_timestamp().alias("published_at_utc"),
        ).select(*BASE))

actuals = build_actuals()
combined = forecasts if actuals is None else forecasts.unionByName(actuals)
print(f"Rows incl. actuals: {combined.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 6 — Total rollup (UCC + ITSG)

# COMMAND ----------

total = (combined
    .groupBy("run_date", "ds", "sales_market", "grain_level", "model", "forecast_type")
    .agg(F.sum("actual").alias("actual"),
         F.sum("p10").alias("p10"), F.sum("p50").alias("p50"), F.sum("p90").alias("p90"),
         F.sum("most_likely").alias("most_likely"),
         F.max("recommended_for_exec").alias("recommended_for_exec"))
    .withColumn("product", F.lit("Total"))
    .withColumn("source_run_ts", F.lit(None).cast("timestamp"))
    .withColumn("published_at_utc", F.current_timestamp())
    .select(*BASE))

results_base = combined.unionByName(total)
print(f"Rows incl. Total rollup: {results_base.count()}")

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
        tot = i.where(F.lower(F.col("metric_scope")) == "total")
        i = tot if tot.count() > 0 else i
    i = i.select(F.lit("ITSG").alias("product"), F.col("model"),
                 F.col("wape").alias("model_wape"), F.col("mape").alias("model_mape"))
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

(results.write.format("delta").mode("overwrite")
   .option("replaceWhere", "run_date = current_date()")
   .option("mergeSchema", "true")
   .partitionBy("product")
   .saveAsTable(RESULTS_TABLE))

spark.sql(f"""
    CREATE OR REPLACE VIEW {RESULTS_VIEW} AS
    SELECT * FROM {RESULTS_TABLE}
    WHERE run_date = (SELECT MAX(run_date) FROM {RESULTS_TABLE})
""")
print(f"Wrote {results.count()} rows to {RESULTS_TABLE} (vintage = today).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 9 — Build & write `forecast_insights`
# MAGIC
# MAGIC Deterministic payloads (no LLM/secret dependency) in the shape the AI Insights
# MAGIC tab reads. Momentum from the forecast trajectory; confidence from band spread
# MAGIC and the model's WAPE.

# COMMAND ----------

import json

res = spark.table(RESULTS_VIEW).toPandas()
latest_run = res["run_date"].max()

def _fmt_m(v):
    return f"${v/1e6:.1f}M" if v else "$0.0M"

def _stats(df):
    tot = df[(df["grain_level"].astype(str).str.lower() == "total") &
             (df["forecast_type"] == "roy")]
    rec = tot[tot["model"] == REC_MODEL]
    if rec.empty:
        rec = tot[tot["recommended_for_exec"] == 1]
    rec = rec.sort_values("ds")
    if rec.empty or rec["p50"].dropna().empty:
        return None
    most_likely = float(rec["p50"].fillna(0).sum())
    worst = float(rec["p10"].fillna(rec["p50"]).sum())
    best  = float(rec["p90"].fillna(rec["p50"]).sum())
    spread_pct = ((best - worst) / most_likely * 100) if most_likely else 0.0
    p = rec["p50"].dropna().tolist()
    momentum = "STABLE"
    if len(p) >= 3 and p[0]:
        chg = (p[-1] - p[0]) / p[0] * 100
        cv = (rec["p50"].std() / rec["p50"].mean() * 100) if rec["p50"].mean() else 0
        if cv > 25: momentum = "VOLATILE"
        elif chg > 5: momentum = "ACCELERATING"
        elif chg < -5: momentum = "DECELERATING"
    wape = float(rec["model_wape"].dropna().mean()) if rec["model_wape"].notna().any() else None
    conf = 100.0 - (spread_pct * 0.4) - (wape * 1.3 if wape is not None else 0.0)
    conf = max(15.0, min(98.0, conf))
    return dict(most_likely=most_likely, worst=worst, best=best,
                upside=max(0.0, best - most_likely), downside=max(0.0, most_likely - worst),
                spread_pct=spread_pct, momentum=momentum, wape=wape, confidence=round(conf, 0))

def _render(s, label):
    risk = "LOW RISK" if s["confidence"] >= 80 else "MODERATE RISK" if s["confidence"] >= 60 else "HIGH RISK"
    return {
        "product": label, "run_date": str(latest_run),
        "momentum": s["momentum"], "risk_level": risk,
        "model_confidence": s["confidence"], "best_model": REC_MODEL,
        "mape": round(s["wape"], 1) if s["wape"] is not None else None,
        "narrative": (f"{label} rest-of-year outlook is {_fmt_m(s['most_likely'])}, ranging "
                      f"{_fmt_m(s['worst'])} to {_fmt_m(s['best'])} ({s['spread_pct']:.0f}% spread). "
                      f"Forecast momentum is {s['momentum'].lower()}."),
        "upside": round(s["upside"], 0), "downside": round(s["downside"], 0),
        "key_drivers": [
            f"Recommended model ({REC_MODEL}) projects {_fmt_m(s['most_likely'])} most-likely.",
            f"Scenario band is {s['spread_pct']:.0f}% of the central forecast.",
        ],
        "downside_risks": [
            f"Downside case sits {_fmt_m(s['downside'])} below plan ({_fmt_m(s['worst'])}).",
            "Momentum decelerating — watch weekly pacing." if s["momentum"] == "DECELERATING"
                else "Elevated forecast volatility." if s["momentum"] == "VOLATILE"
                else "Primary risk is execution against the central path.",
        ],
        "upside_opportunities": [f"Upside case adds {_fmt_m(s['upside'])} over plan ({_fmt_m(s['best'])})."],
        "executive_actions": [
            "Protect the most-likely path; focus on the largest at-risk product/region slices.",
            "Revisit if the next run moves the central forecast materially.",
        ],
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
    agg = dict(most_likely=sum(v["most_likely"] for v in stats.values()),
               worst=sum(v["worst"] for v in stats.values()),
               best=sum(v["best"] for v in stats.values()), wape=None)
    agg["upside"]   = max(0.0, agg["best"] - agg["most_likely"])
    agg["downside"] = max(0.0, agg["most_likely"] - agg["worst"])
    agg["spread_pct"] = ((agg["best"] - agg["worst"]) / agg["most_likely"] * 100) if agg["most_likely"] else 0.0
    order = {"STABLE": 0, "ACCELERATING": 1, "DECELERATING": 2, "VOLATILE": 3}
    agg["momentum"]   = max((v["momentum"] for v in stats.values()), key=lambda m: order[m])
    agg["confidence"] = round(sum(v["confidence"] for v in stats.values()) / len(stats), 0)
    payload = _render(agg, "Total portfolio")
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
# MAGIC ## Cell 9b — App-compatibility views
# MAGIC
# MAGIC Reshape the unified long table into the exact schemas the dashboard's
# MAGIC endpoints read today (wide `arr_forecast_v2`, leaderboard, insights). The
# MAGIC backend then only swaps three table names — no endpoint SQL changes.

# COMMAND ----------

# Wide forecast view (mirrors arr_forecast_v2). One row per
# (ds, product, sales_market, forecast_type, run_date); model columns pivoted.
spark.sql(f"""
    CREATE OR REPLACE VIEW {RESULTS_V2_VIEW} AS
    SELECT
        CAST(ds AS TIMESTAMP) AS ds,
        product, sales_market, forecast_type, run_date,
        MAX(CASE WHEN model = 'ACTUAL'            THEN actual END) AS Actuals,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p50 END)    AS Most_Likely,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p10 END)    AS Worst_Case,
        MAX(CASE WHEN model = 'Adaptive_Ensemble' THEN p90 END)    AS Best_Case,
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
    FROM {RESULTS_TABLE}
    GROUP BY ds, product, sales_market, forecast_type, run_date
""")

# Leaderboard view (mirrors arr_forecast_v2_leaderboard). Accuracy is per
# (product, model), so it repeats across a product's markets.
spark.sql(f"""
    CREATE OR REPLACE VIEW {LEADERBOARD_VIEW} AS
    WITH m AS (
        SELECT product, sales_market,
            MAX(CASE WHEN model = 'ETS'            THEN model_wape END) AS mape_ets,
            MAX(CASE WHEN model = 'Prophet_trend'  THEN model_wape END) AS mape_prophet,
            MAX(CASE WHEN model LIKE 'Global_LGB%' THEN model_wape END) AS mape_lightgbm,
            MAX(CASE WHEN model = 'MSTL_v2'        THEN model_wape END) AS mape_mstl_v2,
            MAX(CASE WHEN model = 'DHR_ARIMA'      THEN model_wape END) AS mape_dhr_arima,
            MAX(run_date) AS run_date
        FROM {RESULTS_TABLE}
        WHERE model_wape IS NOT NULL
        GROUP BY product, sales_market
    ),
    l AS (
        SELECT *, LEAST(
            COALESCE(mape_ets, 1e9), COALESCE(mape_prophet, 1e9),
            COALESCE(mape_lightgbm, 1e9), COALESCE(mape_mstl_v2, 1e9),
            COALESCE(mape_dhr_arima, 1e9)) AS lv
        FROM m
    )
    SELECT product, sales_market, mape_ets, mape_prophet, mape_lightgbm,
           mape_mstl_v2, mape_dhr_arima,
           CASE WHEN lv >= 1e9 THEN NULL ELSE lv END AS best_mape,
           CASE
               WHEN lv >= 1e9 THEN NULL
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

for kind, obj in [("TABLE", RESULTS_TABLE), ("VIEW", RESULTS_VIEW),
                  ("TABLE", INSIGHTS_TABLE), ("TABLE", PUBLISH_LOG),
                  ("VIEW", RESULTS_V2_VIEW), ("VIEW", LEADERBOARD_VIEW),
                  ("VIEW", INSIGHTS_V2_VIEW)]:
    spark.sql(f"GRANT SELECT ON {kind} {obj} TO `{APP_SERVICE_PRINCIPAL}`")
    print(f"  GRANT SELECT on {kind} {obj}")
print("App service principal can now read the published tables.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 12 — Validation & summary

# COMMAND ----------

r = spark.table(RESULTS_VIEW)
n = r.count()
products = sorted([row["product"] for row in r.select("product").distinct().collect()])
ftypes   = sorted([row["forecast_type"] for row in r.select("forecast_type").distinct().collect()])
models   = sorted([row["model"] for row in r.select("model").distinct().collect()])

assert n > 0, "forecast_results_latest is empty."
assert r.where(F.col("p50").isNotNull()).count() > 0, "No non-null p50."
assert "Total" in products, "Total rollup missing."
assert any(ft in ftypes for ft in ("rolling", "roy")), "No forecast rows."
assert "actuals" in ftypes, "No actuals rows — check arr_forecast_v2 source."

print(f"forecast_results_latest: {n} rows")
print(f"  products      : {products}")
print(f"  forecast_types: {ftypes}")
print(f"  models        : {models}")
print(f"  WAPE attached : {r.where(F.col('model_wape').isNotNull()).count()} rows")
print(f"  insight scopes: {[row['product'] for row in spark.table(INSIGHTS_TABLE).where(F.col('run_date')==F.current_date()).select('product').collect()]}")
print('\nPublish complete — app reads forecast_results / forecast_insights.')
