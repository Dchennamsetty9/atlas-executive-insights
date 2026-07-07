# Databricks notebook source
# MAGIC %md
# MAGIC # Atlas AI Insights Writer — Weekly Batch Cache Generator
# MAGIC
# MAGIC **Purpose:** Read combined UCC + ITSG forecasts from `arr_forecast_v2`,
# MAGIC compute summary stats, call the Databricks Foundation Model API (Claude Haiku)
# MAGIC to generate 7 insight types, and write pre-generated insights to
# MAGIC `arr_insights_cache_v1` so the Atlas UI shows zero-latency, zero-LLM-cost
# MAGIC insights on every page load.
# MAGIC
# MAGIC **Run schedule:** Weekly, after atlas_combined_writer.py completes.
# MAGIC (Wire as a Databricks Job: UCC notebook → ITSG notebook → combined_writer → ai_insights_writer)
# MAGIC
# MAGIC **Cost:** ~$0.007/week at Claude Haiku rates (7 API calls × ~1K tokens each)
# MAGIC
# MAGIC **Output table:** `datagroup_mdl.mdl_sales_analytics.arr_insights_cache_v1`
# MAGIC
# MAGIC **Insight types generated:**
# MAGIC   1. `portfolio_summary`  — Overall UCC+ITSG portfolio health narrative
# MAGIC   2. `ucc_outlook`        — UCC-specific forecast narrative
# MAGIC   3. `itsg_outlook`       — ITSG-specific forecast narrative (ATP-based V4)
# MAGIC   4. `regional_spotlight` — Best/worst performing region by forecast variance
# MAGIC   5. `model_confidence`   — Ensemble agreement and forecast confidence level
# MAGIC   6. `risk_alert`         — Downside risks and P10 scenario analysis
# MAGIC   7. `opportunity`        — Upside opportunities and P90 scenario analysis

# COMMAND ----------
# MAGIC %md ## Cell 1 — Config

# COMMAND ----------

import json
import uuid
import datetime
import numpy as np
import pandas as pd
import requests

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType, StringType, StructField, StructType, TimestampType,
)

# ── Tables ────────────────────────────────────────────────────────────────────
CATALOG       = "datagroup_mdl"
SCHEMA        = "mdl_sales_analytics"
FORECAST_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"
CACHE_TABLE    = f"{CATALOG}.{SCHEMA}.arr_insights_cache_v1"

# ── Databricks Foundation Model API ──────────────────────────────────────────
# Claude Haiku: fastest + cheapest (~$0.007/week for 7 calls × 1K tokens)
# Swap to databricks-claude-sonnet-4-6 for higher quality if budget allows
FM_ENDPOINT    = "databricks-claude-haiku-3-5"
FM_MAX_TOKENS  = 600
FM_TEMPERATURE = 0.3   # low for consistent, non-hallucinating insights

# ── Cache TTL ─────────────────────────────────────────────────────────────────
# Weekly batch: cache expires in 7 days. UI reads cache only — zero LLM per page load.
CACHE_TTL_DAYS = 7

# ── Service principal ─────────────────────────────────────────────────────────
SP_PRINCIPAL   = "324a6ec7-e988-42c7-8a7f-55465f5bea37"

# ── Run metadata ──────────────────────────────────────────────────────────────
NOW_UTC   = datetime.datetime.utcnow()
RUN_ID    = str(uuid.uuid4())[:8]
EXPIRES_AT = NOW_UTC + datetime.timedelta(days=CACHE_TTL_DAYS)

print(f"[ai_insights] run_id={RUN_ID}  started={NOW_UTC.isoformat()}")
print(f"[ai_insights] FM endpoint: {FM_ENDPOINT}")
print(f"[ai_insights] Cache TTL: {CACHE_TTL_DAYS} days → expires {EXPIRES_AT.date()}")

# COMMAND ----------
# MAGIC %md ## Cell 2 — Load combined forecast data

# COMMAND ----------

# Get the latest run_date from arr_forecast_v2
latest_run = spark.sql(f"""
    SELECT MAX(run_date) AS latest_run FROM {FORECAST_TABLE}
""").collect()[0]["latest_run"]

if latest_run is None:
    dbutils.notebook.exit(
        f"[ai_insights] ERROR: {FORECAST_TABLE} is empty. "
        "Run atlas_combined_writer.py and arr_forecast_v2_main.py first."
    )
print(f"[ai_insights] Using forecast run_date = {latest_run}")

# Load rolling + roi rows for UCC and ITSG (not actuals — those are history)
forecast_pd = spark.sql(f"""
    SELECT
        ds, product, sales_market,
        Actuals, Most_Likely, Worst_Case, Best_Case,
        arr_ets, arr_prophet, arr_lightgbm, arr_chronos,
        mape_ets, mape_prophet, mape_lightgbm, mape_chronos,
        forecast_type, run_date
    FROM {FORECAST_TABLE}
    WHERE run_date = '{latest_run}'
      AND product IN ('UCC', 'ITSG', 'Total')
    ORDER BY product, sales_market, ds
""").toPandas()

forecast_pd["ds"] = pd.to_datetime(forecast_pd["ds"])

n_ucc  = len(forecast_pd[forecast_pd["product"] == "UCC"])
n_itsg = len(forecast_pd[forecast_pd["product"] == "ITSG"])
print(f"[ai_insights] Loaded {n_ucc} UCC rows | {n_itsg} ITSG rows | run_date={latest_run}")

# Recent actuals (last 8 weeks) for YoY / trend context
actuals_pd = spark.sql(f"""
    SELECT ds, product, sales_market, Actuals
    FROM {FORECAST_TABLE}
    WHERE run_date = '{latest_run}'
      AND forecast_type = 'actuals'
      AND Actuals IS NOT NULL
      AND ds >= DATEADD(WEEK, -8, '{latest_run}')
    ORDER BY product, sales_market, ds
""").toPandas()
actuals_pd["ds"] = pd.to_datetime(actuals_pd["ds"])
print(f"[ai_insights] Loaded {len(actuals_pd)} recent actuals rows (last 8 weeks)")

# COMMAND ----------
# MAGIC %md ## Cell 3 — Compute summary statistics for prompt context

# COMMAND ----------

def safe_float(v, default=0.0):
    try:
        f = float(v)
        return f if np.isfinite(f) else default
    except:
        return default

def summarise_slice(df: pd.DataFrame, product: str, market: str = "Total") -> dict:
    """
    Compute a compact stats dict for a given (product, market) slice.
    Used to build the AI prompt context.
    """
    sl = df[(df["product"] == product) & (df["sales_market"] == market)].copy()
    if sl.empty:
        return {"product": product, "market": market, "available": False}

    rolling = sl[sl["forecast_type"] == "rolling"].sort_values("ds")
    roy     = sl[sl["forecast_type"] == "roy"].sort_values("ds")
    actuals = sl[sl["forecast_type"] == "actuals"].sort_values("ds")

    # Weekly peak forecast
    rolling_peak  = safe_float(rolling["Most_Likely"].max())
    rolling_avg   = safe_float(rolling["Most_Likely"].mean())
    rolling_sum   = safe_float(rolling["Most_Likely"].sum())

    roy_sum       = safe_float(roy["Most_Likely"].sum())
    total_outlook = rolling_sum + roy_sum   # full remaining year ARR

    # Confidence band: P90-P10 spread as % of P50
    p10_avg = safe_float(rolling["Worst_Case"].mean())
    p90_avg = safe_float(rolling["Best_Case"].mean())
    band_pct = ((p90_avg - p10_avg) / rolling_avg * 100) if rolling_avg > 0 else 0

    # Best MAPE
    mapes = {
        "ETS":       safe_float(sl["mape_ets"].iloc[0],       None) if not sl.empty else None,
        "Prophet":   safe_float(sl["mape_prophet"].iloc[0],   None) if not sl.empty else None,
        "LightGBM":  safe_float(sl["mape_lightgbm"].iloc[0],  None) if not sl.empty else None,
        "DHR-ARIMA": safe_float(sl["mape_chronos"].iloc[0],   None) if not sl.empty else None,  # arr_chronos slot = DHR-ARIMA for ITSG
    }
    valid_mapes = {k: v for k, v in mapes.items() if v and v > 0}
    best_model  = min(valid_mapes, key=valid_mapes.get) if valid_mapes else "Ensemble"
    best_mape   = valid_mapes[best_model] if valid_mapes else None

    # Model agreement: std across individual model forecasts for next week
    next_week_row = rolling.head(1)
    model_vals = []
    for col in ["arr_ets","arr_prophet","arr_lightgbm","arr_chronos"]:
        v = safe_float(next_week_row[col].values[0] if not next_week_row.empty else None, None)
        if v and v > 0:
            model_vals.append(v)
    model_disagree_pct = (np.std(model_vals) / np.mean(model_vals) * 100) if len(model_vals) >= 2 else 0

    # Recent trend: last 4 weeks actuals vs prior 4 weeks
    recent_8 = actuals.tail(8)["Actuals"].values
    trend_pct = 0.0
    if len(recent_8) >= 8:
        prior_4 = np.mean(recent_8[:4])
        last_4  = np.mean(recent_8[4:])
        trend_pct = ((last_4 - prior_4) / prior_4 * 100) if prior_4 > 0 else 0

    return {
        "product":             product,
        "market":              market,
        "available":           True,
        "rolling_avg_weekly":  round(rolling_avg / 1000, 1),   # in $K
        "rolling_sum_13w":     round(rolling_sum / 1_000_000, 2),  # in $M
        "roy_sum":             round(roy_sum / 1_000_000, 2),
        "total_remaining_yr":  round(total_outlook / 1_000_000, 2),
        "p10_avg_weekly":      round(p10_avg / 1000, 1),
        "p90_avg_weekly":      round(p90_avg / 1000, 1),
        "confidence_band_pct": round(band_pct, 1),
        "best_model":          best_model,
        "best_mape_pct":       round(best_mape, 1) if best_mape else None,
        "model_disagreement_pct": round(model_disagree_pct, 1),
        "recent_trend_pct":    round(trend_pct, 1),
        "weeks_ahead":         len(rolling),
    }


# Compute stats for all slices we need
MARKETS = ["Total", "NA", "EMEA", "APAC", "LATAM"]
PRODUCTS = ["UCC", "ITSG"]

stats = {}
for prod in PRODUCTS:
    for mkt in MARKETS:
        key = f"{prod}_{mkt}"
        stats[key] = summarise_slice(forecast_pd, prod, mkt)

# Portfolio total (product='Total')
stats["Total_Total"] = summarise_slice(forecast_pd, "Total", "Total")

# Regional spotlight: find best and worst market by confidence band + trend
regional = {}
for mkt in ["NA","EMEA","APAC","LATAM"]:
    ucc_s  = stats.get(f"UCC_{mkt}",  {})
    itsg_s = stats.get(f"ITSG_{mkt}", {})
    combined_sum = safe_float(ucc_s.get("rolling_sum_13w",0)) + safe_float(itsg_s.get("rolling_sum_13w",0))
    avg_trend    = (safe_float(ucc_s.get("recent_trend_pct",0)) + safe_float(itsg_s.get("recent_trend_pct",0))) / 2
    regional[mkt] = {"combined_rolling_13w": combined_sum, "avg_trend_pct": avg_trend}

best_region  = max(regional, key=lambda m: regional[m]["avg_trend_pct"])
worst_region = min(regional, key=lambda m: regional[m]["avg_trend_pct"])

print(f"[ai_insights] Stats computed for {len(stats)} slices")
print(f"[ai_insights] Best region: {best_region} ({regional[best_region]['avg_trend_pct']:+.1f}% trend)")
print(f"[ai_insights] Worst region: {worst_region} ({regional[worst_region]['avg_trend_pct']:+.1f}% trend)")

# COMMAND ----------
# MAGIC %md ## Cell 4 — FM API helper

# COMMAND ----------

def call_fm(system_prompt: str, user_prompt: str, max_tokens: int = FM_MAX_TOKENS) -> str:
    """
    Call the Databricks Foundation Model API using the workspace token.
    Falls back to a deterministic rule-based summary if the API is unavailable.
    """
    try:
        token  = dbutils.secrets.get(scope="databricks", key="token")
        host   = spark.conf.get("spark.databricks.workspaceUrl")
        url    = f"https://{host}/serving-endpoints/{FM_ENDPOINT}/invocations"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
        payload = {
            "messages": [
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": user_prompt},
            ],
            "max_tokens":  max_tokens,
            "temperature": FM_TEMPERATURE,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ai_insights] WARN: FM call failed ({e}); using fallback text")
        return None


SYSTEM_PROMPT = """You are an executive data analyst for GoTo Technologies, a B2B SaaS company.
You analyze weekly ARR (Annual Recurring Revenue) growth forecasts for two product lines:
- UCC (Unified Communications & Collaboration): GoTo Connect, GoTo Engage
- ITSG (IT Solutions Group): GoTo Resolve, Rescue

Write concise, data-grounded insights for the executive leadership team.
- Lead with the most important number or trend
- Be specific: include dollar figures (in $K or $M) and percentages
- Flag risks and opportunities explicitly
- Tone: confident, direct, executive-ready (no hedging, no jargon)
- Length: 2-4 sentences per insight
- Do NOT use bullet points or markdown headers — write in flowing prose
"""


def make_fallback(insight_type: str, s: dict) -> str:
    """Deterministic fallback if LLM is unavailable."""
    if not s.get("available"):
        return f"No forecast data available for {insight_type}."
    return (
        f"{s['product']} ({s['market']}): "
        f"13-week rolling forecast totals ${s['rolling_sum_13w']}M. "
        f"Best model: {s['best_model']} "
        f"(WAPE: {s['best_mape_pct']}%). "
        f"Confidence band: ±{s['confidence_band_pct']}%. "
        f"Recent 4-week trend: {s['recent_trend_pct']:+.1f}%."
    )

# COMMAND ----------
# MAGIC %md ## Cell 5 — Generate 7 insight types

# COMMAND ----------

INSIGHT_DEFINITIONS = [
    # (insight_type, prompt_fn, fallback_key)
    ("portfolio_summary",  None, "Total_Total"),
    ("ucc_outlook",        None, "UCC_Total"),
    ("itsg_outlook",       None, "ITSG_Total"),
    ("regional_spotlight", None, None),
    ("model_confidence",   None, "UCC_Total"),
    ("risk_alert",         None, "Total_Total"),
    ("opportunity",        None, "Total_Total"),
]


def build_prompts(insight_type: str) -> tuple[str, str]:
    """Return (system_prompt_addition, user_prompt) for each insight type."""

    ucc   = stats.get("UCC_Total",  {})
    itsg  = stats.get("ITSG_Total", {})
    total = stats.get("Total_Total", {})

    def fmt(s):
        if not s.get("available"):
            return "No data"
        return (
            f"13-week rolling sum: ${s['rolling_sum_13w']}M | "
            f"Weekly avg: ${s['rolling_avg_weekly']}K | "
            f"Rest-of-year: ${s['roy_sum']}M | "
            f"P10 (downside) weekly avg: ${s['p10_avg_weekly']}K | "
            f"P90 (upside) weekly avg: ${s['p90_avg_weekly']}K | "
            f"Confidence band: ±{s['confidence_band_pct']}% | "
            f"Best model: {s['best_model']} (WAPE {s['best_mape_pct']}%) | "
            f"Model disagreement: {s['model_disagreement_pct']}% | "
            f"Recent 4-week trend vs prior: {s['recent_trend_pct']:+.1f}%"
        )

    if insight_type == "portfolio_summary":
        return "", f"""Summarize the overall GoTo Technologies ARR growth portfolio for this week:
UCC Growth: {fmt(ucc)}
ITSG Growth: {fmt(itsg)}
Portfolio Total: {fmt(total)}
Write a 3-sentence executive summary covering: (1) combined pipeline health, (2) which product line is leading growth, (3) the single biggest risk or opportunity."""

    elif insight_type == "ucc_outlook":
        mkt_context = " | ".join(
            f"{m}: ${safe_float(stats.get(f'UCC_{m}',{}).get('rolling_sum_13w',0))}M (trend {safe_float(stats.get(f'UCC_{m}',{}).get('recent_trend_pct',0)):+.1f}%)"
            for m in ["NA","EMEA","APAC","LATAM"]
            if stats.get(f"UCC_{m}",{}).get("available")
        )
        return "", f"""Write a UCC Growth ARR forecast outlook:
Total UCC: {fmt(ucc)}
Regional breakdown (13w rolling sum | 4w trend): {mkt_context}
Include: (1) expected 13-week bookings, (2) which region is driving growth or drag, (3) confidence level."""

    elif insight_type == "itsg_outlook":
        # Note: ITSG V4 uses ATP (annualized quota-credited ARR), not TCV
        mkt_context = " | ".join(
            f"{m}: ${safe_float(stats.get(f'ITSG_{m}',{}).get('rolling_sum_13w',0))}M (trend {safe_float(stats.get(f'ITSG_{m}',{}).get('recent_trend_pct',0)):+.1f}%)"
            for m in ["NA","EMEA","APAC","LATAM"]
            if stats.get(f"ITSG_{m}",{}).get("available")
        )
        return "", f"""Write an ITSG Growth ARR forecast outlook.
Note: ITSG forecasts use ATP (amount_towards_plan, annualized quota-credited ARR) — not TCV.
Total ITSG: {fmt(itsg)}
Regional breakdown (13w rolling sum | 4w trend): {mkt_context}
Include: (1) expected 13-week bookings in ATP terms, (2) regional concentration risk, (3) model confidence."""

    elif insight_type == "regional_spotlight":
        best_s  = stats.get(f"UCC_{best_region}",  {})
        worst_s = stats.get(f"UCC_{worst_region}", {})
        return "", f"""Spotlight the two most notable regions for ARR growth this week:
Best-performing region: {best_region}
  UCC trend vs prior 4w: {best_s.get('recent_trend_pct', 0):+.1f}% | Rolling sum: ${best_s.get('rolling_sum_13w',0)}M
  ITSG trend: {safe_float(stats.get(f'ITSG_{best_region}',{}).get('recent_trend_pct',0)):+.1f}%
Weakest region: {worst_region}
  UCC trend vs prior 4w: {worst_s.get('recent_trend_pct', 0):+.1f}% | Rolling sum: ${worst_s.get('rolling_sum_13w',0)}M
  ITSG trend: {safe_float(stats.get(f'ITSG_{worst_region}',{}).get('recent_trend_pct',0)):+.1f}%
Write 2 sentences: (1) what's working in {best_region}, (2) the specific risk in {worst_region} and suggested action."""

    elif insight_type == "model_confidence":
        return "", f"""Assess ensemble model confidence for this week's GoTo ARR forecast:
UCC Total: {fmt(ucc)}
ITSG Total: {fmt(itsg)}
Confidence is HIGH when: band_pct < 20%, model_disagreement < 15%, WAPE < 20%.
Confidence is MEDIUM when: band_pct 20-35%, disagreement 15-25%, WAPE 20-30%.
Confidence is LOW when: any metric exceeds the MEDIUM thresholds.
Write 2 sentences rating overall confidence (HIGH/MEDIUM/LOW for each product) and the key driver of uncertainty."""

    elif insight_type == "risk_alert":
        return "", f"""Identify the top downside risks for GoTo ARR growth this week:
UCC P10 (worst-case) weekly average: ${ucc.get('p10_avg_weekly',0)}K (vs P50: ${ucc.get('rolling_avg_weekly',0)}K)
ITSG P10 (worst-case) weekly average: ${itsg.get('p10_avg_weekly',0)}K (vs P50: ${itsg.get('rolling_avg_weekly',0)}K)
UCC recent trend: {ucc.get('recent_trend_pct', 0):+.1f}% vs prior 4 weeks
ITSG recent trend: {itsg.get('recent_trend_pct', 0):+.1f}% vs prior 4 weeks
Worst region: {worst_region} ({regional[worst_region]['avg_trend_pct']:+.1f}% combined trend)
Write 2-3 sentences identifying the 1-2 biggest downside risks and the magnitude of potential miss."""

    elif insight_type == "opportunity":
        return "", f"""Identify the top upside opportunities for GoTo ARR growth this week:
UCC P90 (best-case) weekly average: ${ucc.get('p90_avg_weekly',0)}K (vs P50: ${ucc.get('rolling_avg_weekly',0)}K)
ITSG P90 (best-case) weekly average: ${itsg.get('p90_avg_weekly',0)}K (vs P50: ${itsg.get('rolling_avg_weekly',0)}K)
Best region: {best_region} ({regional[best_region]['avg_trend_pct']:+.1f}% combined trend)
Write 2 sentences: (1) the upside scenario if P90 materializes, (2) which product/region has the best asymmetric opportunity."""

    return "", f"Generate a {insight_type} insight based on the available forecast data."


# ── Call FM for each insight type ─────────────────────────────────────────────
insights_rows = []
total_calls = 0
failed_calls = 0

for insight_type, _, fallback_key in INSIGHT_DEFINITIONS:
    print(f"[ai_insights] Generating: {insight_type} ...", end=" ")
    _, user_prompt = build_prompts(insight_type)

    text = call_fm(SYSTEM_PROMPT, user_prompt, max_tokens=FM_MAX_TOKENS)
    total_calls += 1

    if text is None:
        failed_calls += 1
        fallback_stats = stats.get(fallback_key, {}) if fallback_key else {}
        text = make_fallback(insight_type, fallback_stats)
        source = "rule"
    else:
        source = "fm"

    print(f"✅ ({source}) {len(text)} chars")

    insights_rows.append({
        "insight_id":    f"{insight_type}_{RUN_ID}",
        "insight_type":  insight_type,
        "text":          text,
        "source":        source,   # 'fm' or 'rule'
        "run_date":      str(datetime.date.today()),
        "generated_at":  NOW_UTC.isoformat(),
        "expires_at":    EXPIRES_AT.isoformat(),
        "model":         FM_ENDPOINT if source == "fm" else "rule_engine",
        "context_json":  json.dumps({
            "ucc_total":    stats.get("UCC_Total",  {}),
            "itsg_total":   stats.get("ITSG_Total", {}),
            "best_region":  best_region,
            "worst_region": worst_region,
        }),
    })

print(f"\n[ai_insights] {total_calls} calls | {total_calls - failed_calls} FM | {failed_calls} fallback")

# COMMAND ----------
# MAGIC %md ## Cell 6 — Write to arr_insights_cache_v1

# COMMAND ----------

CACHE_SCHEMA = StructType([
    StructField("insight_id",    StringType(), False),
    StructField("insight_type",  StringType(), True),
    StructField("text",          StringType(), True),
    StructField("source",        StringType(), True),
    StructField("run_date",      StringType(), True),
    StructField("generated_at",  StringType(), True),
    StructField("expires_at",    StringType(), True),
    StructField("model",         StringType(), True),
    StructField("context_json",  StringType(), True),
])

insights_pd = pd.DataFrame(insights_rows)
cache_sdf   = spark.createDataFrame(insights_pd, schema=CACHE_SCHEMA)

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
        insight_id   STRING  NOT NULL COMMENT 'Unique: insight_type + run_id',
        insight_type STRING  COMMENT 'portfolio_summary | ucc_outlook | itsg_outlook | regional_spotlight | model_confidence | risk_alert | opportunity',
        text         STRING  COMMENT 'AI-generated or rule-engine insight text',
        source       STRING  COMMENT 'fm (LLM) or rule (deterministic fallback)',
        run_date     STRING  COMMENT 'Date this row was generated (YYYY-MM-DD)',
        generated_at STRING  COMMENT 'UTC timestamp of generation',
        expires_at   STRING  COMMENT 'UTC timestamp after which UI should re-fetch',
        model        STRING  COMMENT 'FM endpoint used (or rule_engine)',
        context_json STRING  COMMENT 'JSON snapshot of stats used to generate insight'
    )
    USING DELTA
    TBLPROPERTIES (
        'delta.autoOptimize.optimizeWrite' = 'true',
        'delta.autoOptimize.autoCompact'   = 'true'
    )
    COMMENT 'Pre-generated weekly AI insights cache for Atlas Executive Insights UI.
             Zero LLM calls per page load. TTL: {CACHE_TTL_DAYS} days. Regenerated weekly by atlas_ai_insights_writer.py.'
""")

# Delete today's rows first (idempotent)
spark.sql(f"DELETE FROM {CACHE_TABLE} WHERE run_date = '{datetime.date.today()}'")

cache_sdf.write.mode("append").saveAsTable(CACHE_TABLE)
print(f"✅  Written {len(insights_rows)} insights to {CACHE_TABLE}")

# Verify
spark.sql(f"""
    SELECT insight_type, source, LENGTH(text) AS text_chars, generated_at
    FROM {CACHE_TABLE}
    WHERE run_date = '{datetime.date.today()}'
    ORDER BY insight_type
""").show(10, truncate=False)

# COMMAND ----------
# MAGIC %md ## Cell 7 — GRANT + API endpoint guidance

# COMMAND ----------

# Grant Atlas app SP read access
for tbl in [CACHE_TABLE]:
    try:
        spark.sql(f"GRANT SELECT ON TABLE {tbl} TO `{SP_PRINCIPAL}`")
        print(f"✅  GRANT SELECT on {tbl}")
    except Exception as e:
        print(f"[ai_insights] WARN: GRANT failed ({e})")

print(f"""
╔══════════════════════════════════════════════════════════════════════════╗
║  atlas_ai_insights_writer.py  COMPLETE                                   ║
║                                                                          ║
║  Cache table:   {CACHE_TABLE:<40}    ║
║  Insights written: {len(insights_rows)} types                                          ║
║  FM calls:      {total_calls - failed_calls} succeeded, {failed_calls} fell back to rule engine              ║
║  Expires:       {EXPIRES_AT.date()} (TTL = {CACHE_TTL_DAYS} days)                         ║
║                                                                          ║
║  Atlas UI endpoint to wire:                                              ║
║    GET /api/forecast/insights                                            ║
║    SQL: SELECT insight_type, text, source, generated_at                  ║
║         FROM arr_insights_cache_v1                                        ║
║         WHERE run_date = (SELECT MAX(run_date) FROM arr_insights_cache_v1)║
║                                                                          ║
║  Insight types available:                                                ║
║    portfolio_summary | ucc_outlook | itsg_outlook | regional_spotlight   ║
║    model_confidence  | risk_alert  | opportunity                         ║
╚══════════════════════════════════════════════════════════════════════════╝
""")
