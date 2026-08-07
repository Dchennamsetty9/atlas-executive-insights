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
        .withColumn("forecast_view", F.lit("adaptive"))            # default; BOQ rows added in Cell 4b
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
            F.lit("adaptive").alias("forecast_view"),
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

def _render(s, label):
    _pl = s.get("period_label", _Q_LABEL)
    risk = "LOW RISK" if s["confidence"] >= 80 else "MODERATE RISK" if s["confidence"] >= 60 else "HIGH RISK"
    yoy = s.get("yoy")
    yoy_txt = (f" — {'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s['prior'])} last year"
               if yoy is not None else "")
    rr_txt = (f"{_fmt_m(s['run_rate'])}/wk across {s['n_fwd']} open week(s)"
              if s.get("run_rate") else "n/a")
    drivers = [
        f"{label} {_pl} landing {_fmt_m(s['most_likely'])} = {_fmt_m(s['qtd'])} realized "
        f"+ {_fmt_m(s['most_likely'] - s['qtd'])} forecast.",
        f"Implied pace: {rr_txt}.",
    ]
    if yoy is not None:
        drivers.append(f"Tracking {'+' if yoy >= 0 else ''}{yoy:.0f}% YoY vs {_fmt_m(s['prior'])} last year ({_pl.replace(str(_Q_YEAR), str(_Q_YEAR - 1))}).")
    return {
        "product": label, "run_date": str(latest_run), "period": _pl,
        "momentum": s["momentum"], "risk_level": risk,
        "model_confidence": s["confidence"], "best_model": REC_MODEL,
        "mape": round(s["wape"], 1) if s["wape"] is not None else None,
        "narrative": (f"{label} {_pl} landing is {_fmt_m(s['most_likely'])} "
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
            f"Hold ~{rr_txt} to land the most-likely {_pl} outlook.",
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
    GROUP BY ds, product, sales_market, forecast_type, run_date
""")

# Leaderboard view (mirrors arr_forecast_v2_leaderboard). PRODUCT-LEVEL ONLY:
# the monitoring baselines score models per product across all regions, so
# per-region rows just repeated the product value and implied precision the
# pipeline doesn't have. Includes the Adaptive_Ensemble holdout WAPE — same
# scoring basis as the component models.
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
assert any(ft in ftypes for ft in ("rolling", "roy", "forward_1yr")), "No forecast rows."
assert "actuals" in ftypes, "No actuals rows — check arr_forecast_v2 source."

print(f"forecast_results_latest: {n} rows")
print(f"  products      : {products}")
print(f"  forecast_types: {ftypes}")
print(f"  models        : {models}")
print(f"  WAPE attached : {r.where(F.col('model_wape').isNotNull()).count()} rows")
print(f"  insight scopes: {[row['product'] for row in spark.table(INSIGHTS_TABLE).where(F.col('run_date')==F.current_date()).select('product').collect()]}")
print('\nPublish complete — app reads forecast_results / forecast_insights.')
