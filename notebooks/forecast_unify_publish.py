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

# Per-graph "explain this chart in detail" text, precomputed per (graph, product).
# The app shows it behind an Explain icon on every chart. Precomputed baseline;
# a Genie/on-demand path can supersede this later using the same table as fallback.
GRAPH_EXPLAIN_TABLE = f"{CATALOG}.{SCHEMA}.forecast_graph_explanations"

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

# rolling = next 13 weeks; roy = the rest of the year AFTER that window.
# They MUST be disjoint: the app's KPI query sums forecast_type IN
# ('rolling','roy'), so overlapping rows double-count the quarter total.
rolling = fc.where(F.col("ds") <= F.lit(rolling_cutoff)).withColumn("forecast_type", F.lit("rolling"))
roy     = fc.where(F.col("ds") >  F.lit(rolling_cutoff)).withColumn("forecast_type", F.lit("roy"))
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

def _stats(df):
    """Current-quarter landing = realized-so-far + forecast for the quarter's open
    weeks (matches the Overview KPI), plus YoY vs the same quarter last year and
    the implied weekly run-rate. Guarded so a bad slice can't fail the publish."""
    try:
        tot = df[df["grain_level"].astype(str).str.lower() == "total"].copy()
        in_q = tot["ds"].dt.year.eq(_Q_YEAR) & tot["ds"].dt.month.isin(_Q_MONTHS)
        fwd = tot[(tot["model"] == REC_MODEL)
                  & tot["forecast_type"].isin(["rolling", "roy"]) & in_q].sort_values("ds")
        act = tot[(tot["model"] == "ACTUAL") & in_q]
        if fwd.empty and act.empty:
            return None
        fwd_ml = float(fwd["p50"].fillna(0).sum())
        fwd_lo = float(fwd["p10"].fillna(fwd["p50"]).sum())
        fwd_hi = float(fwd["p90"].fillna(fwd["p50"]).sum())
        qtd    = float(act["actual"].fillna(0).sum())
        most_likely = fwd_ml + qtd
        worst = fwd_lo + qtd
        best  = fwd_hi + qtd
        spread_pct = ((best - worst) / most_likely * 100) if most_likely else 0.0
        prior = float(tot[(tot["model"] == "ACTUAL")
                          & tot["ds"].dt.year.eq(_Q_YEAR - 1)
                          & tot["ds"].dt.month.isin(_Q_MONTHS)]["actual"].fillna(0).sum())
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
                    run_rate=run_rate, n_fwd=n_fwd, confidence=round(conf, 0))
    except Exception as _e:
        print(f"  WARN insight stats failed: {_e}")
        return None

def _render(s, label):
    risk = "LOW RISK" if s["confidence"] >= 80 else "MODERATE RISK" if s["confidence"] >= 60 else "HIGH RISK"
    yoy = s.get("yoy")
    yoy_txt = (f" — {'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s['prior'])} last year"
               if yoy is not None else "")
    rr_txt = (f"{_fmt_m(s['run_rate'])}/wk across {s['n_fwd']} open week(s)"
              if s.get("run_rate") else "n/a")
    drivers = [
        f"{label} {_Q_LABEL} landing {_fmt_m(s['most_likely'])} = {_fmt_m(s['qtd'])} realized "
        f"+ {_fmt_m(s['most_likely'] - s['qtd'])} forecast.",
        f"Implied pace: {rr_txt}.",
    ]
    if yoy is not None:
        drivers.append(f"Tracking {'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s['prior'])} in Q{_Q} {_Q_YEAR - 1}.")
    return {
        "product": label, "run_date": str(latest_run), "period": _Q_LABEL,
        "momentum": s["momentum"], "risk_level": risk,
        "model_confidence": s["confidence"], "best_model": REC_MODEL,
        "mape": round(s["wape"], 1) if s["wape"] is not None else None,
        "narrative": (f"{label} {_Q_LABEL} landing is {_fmt_m(s['most_likely'])} "
                      f"({_fmt_m(s['qtd'])} realized + forecast), ranging {_fmt_m(s['worst'])} to "
                      f"{_fmt_m(s['best'])}{yoy_txt}. Momentum {s['momentum'].lower()}."),
        "upside": round(s["upside"], 0), "downside": round(s["downside"], 0),
        "key_drivers": drivers,
        "downside_risks": [
            f"Downside case {_fmt_m(s['worst'])} — {_fmt_m(s['downside'])} below the most-likely path.",
            "Momentum decelerating — watch weekly pacing." if s["momentum"] == "DECELERATING"
                else "Elevated week-to-week volatility." if s["momentum"] == "VOLATILE"
                else "Primary risk is execution against the central path.",
        ],
        "upside_opportunities": [f"Stretch case {_fmt_m(s['best'])} — {_fmt_m(s['upside'])} above the most-likely path."],
        "executive_actions": [
            f"Hold ~{rr_txt} to land the most-likely {_Q_LABEL} outlook.",
            "Focus on the largest at-risk product/region slices; revisit after the next run.",
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
    _sum = lambda k: sum((v.get(k) or 0) for v in stats.values())
    agg = dict(most_likely=_sum("most_likely"), worst=_sum("worst"), best=_sum("best"),
               qtd=_sum("qtd"), prior=_sum("prior"),
               n_fwd=max((v.get("n_fwd") or 0) for v in stats.values()), wape=None)
    agg["upside"]   = max(0.0, agg["best"] - agg["most_likely"])
    agg["downside"] = max(0.0, agg["most_likely"] - agg["worst"])
    agg["spread_pct"] = ((agg["best"] - agg["worst"]) / agg["most_likely"] * 100) if agg["most_likely"] else 0.0
    agg["yoy"] = ((agg["most_likely"] - agg["prior"]) / agg["prior"] * 100) if agg["prior"] else None
    agg["run_rate"] = ((agg["most_likely"] - agg["qtd"]) / agg["n_fwd"]) if agg["n_fwd"] else None
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
}

def _explain(s, label, key):
    ml, qtd, worst, best = s["most_likely"], s["qtd"], s["worst"], s["best"]
    fc = max(0.0, ml - qtd)
    sp = s.get("spread_pct") or 0.0
    mom = (s.get("momentum") or "stable").lower()
    yoy, rr, wape, conf = s.get("yoy"), s.get("run_rate"), s.get("wape"), s.get("confidence")
    yoy_s = (f"{'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s.get('prior'))}") if yoy is not None else "no prior-year baseline"
    rr_s = f"{_fmt_m(rr)}/week across {s.get('n_fwd', 0)} open week(s)" if rr else "n/a"
    wape_s = f"{wape:.1f}% WAPE" if wape is not None else "WAPE unavailable"

    if key == "weekly":
        exp = (f"Weekly Growth ARR for {label}, {_Q_LABEL}. The amber line is realized actuals "
               f"({_fmt_m(qtd)} booked so far); the white line is the {REC_MODEL} most-likely forecast for the "
               f"remaining weeks (+{_fmt_m(fc)}), for a full-quarter landing of {_fmt_m(ml)}. The shaded band is the "
               f"P10–P90 range, {_fmt_m(worst)} to {_fmt_m(best)} (~{sp:.0f}% wide). Forecast momentum is {mom}.")
        b = [f"Landing {_fmt_m(ml)} = {_fmt_m(qtd)} realized + {_fmt_m(fc)} forecast",
             f"Scenario range {_fmt_m(worst)}–{_fmt_m(best)} (~{sp:.0f}% wide)",
             f"Tracking {yoy_s}; momentum {mom}"]
    elif key == "ytd":
        exp = (f"Cumulative Growth ARR for {label} through {_Q_LABEL}: realized actuals build to {_fmt_m(qtd)}, then the "
               f"forecast path extends to a most-likely {_fmt_m(ml)} ({_fmt_m(worst)}–{_fmt_m(best)} across scenarios). "
               f"Use it to see whether the run-rate keeps pace with the quarter target.")
        b = [f"Realized to date {_fmt_m(qtd)}", f"Most-likely finish {_fmt_m(ml)}",
             f"Implied pace {rr_s}"]
    elif key == "seasonality":
        exp = (f"Each line is a year of weekly Growth ARR laid over ISO weeks 1–52, so recurring peaks and troughs line up. "
               f"For {label}, {_Q_LABEL} is tracking {yoy_s}. Use it to spot the quarter-end surges and pacing patterns "
               f"the models lean on.")
        b = ["Overlays years by ISO week to expose seasonality",
             f"{_Q_LABEL} vs last year: {yoy_s}",
             "Watch quarter-end weeks — historically the biggest spikes"]
    elif key == "by_product":
        exp = (f"Splits the {label} {_Q_LABEL} forecast across product lines and geographies. The most-likely total is "
               f"{_fmt_m(ml)}, with worst/best scenarios of {_fmt_m(worst)}/{_fmt_m(best)}. Use it to see which "
               f"segments carry the number and where the risk concentrates.")
        b = [f"Most-likely {_fmt_m(ml)} across segments",
             f"Scenario range {_fmt_m(worst)}–{_fmt_m(best)}",
             "Longer bars = larger share of the quarter"]
    elif key == "monthly":
        exp = (f"Month-by-month for {label} {_Q_LABEL}: realized actuals ({_fmt_m(qtd)} so far) alongside the risk-floor / "
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
    else:
        exp, b = f"Detailed view of {label} Growth ARR for {_Q_LABEL}.", []
    return GRAPH_TITLES[key], exp, b

# Assemble per-product stats incl. the ALL rollup
_explain_stats = dict(stats)
if stats:
    _explain_stats["ALL"] = agg

ge_rows = []
for label, s in _explain_stats.items():
    for key in GRAPH_TITLES:
        title, exp, bullets = _explain(s, "Total portfolio" if label == "ALL" else label, key)
        ge_rows.append((latest_run, label, key, title, exp, json.dumps(bullets)))

if ge_rows:
    ge_df = spark.createDataFrame(
        ge_rows,
        schema="run_date date, product string, graph_key string, title string, "
               "explanation string, bullets string",
    ).withColumn("generated_at", F.current_timestamp())
    (ge_df.write.format("delta").mode("overwrite")
       .option("replaceWhere", "run_date = current_date()")
       .option("mergeSchema", "true")
       .saveAsTable(GRAPH_EXPLAIN_TABLE))
    print(f"Wrote {ge_df.count()} graph explanations to {GRAPH_EXPLAIN_TABLE}.")

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
    WITH cutoff AS (
        SELECT product, DATE_ADD(MIN(ds), (({ROLLING_WEEKS} - 1) * 7)) AS roll_end
        FROM {RESULTS_TABLE}
        WHERE forecast_type IN ('rolling', 'roy')
        GROUP BY product
    ),
    filt AS (
        -- Defensive: keep roy rows only beyond the rolling window so rolling/roy
        -- never overlap (prevents KPI double-count even if the table still holds
        -- overlapping rows from an older run).
        SELECT fr.* FROM {RESULTS_TABLE} fr
        LEFT JOIN cutoff c ON fr.product = c.product
        WHERE fr.forecast_type <> 'roy' OR c.roll_end IS NULL OR fr.ds > c.roll_end
    )
    SELECT
        CAST(ds AS TIMESTAMP) AS ds,
        product, sales_market, forecast_type, run_date,
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
          AND UPPER(TRIM(sales_market)) <> 'UNKNOWN'
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
                  ("VIEW", INSIGHTS_V2_VIEW), ("TABLE", GRAPH_EXPLAIN_TABLE)]:
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
