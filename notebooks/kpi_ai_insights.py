# Databricks notebook source
# GAIM / Atlas — KPI AI Insights Generator
# =============================================================================
# Reads the latest kpi_daily_summary row and produces 5-7 structured executive
# insights via the Databricks-hosted Claude endpoint, then writes them to
# kpi_ai_insights_log. Runs AFTER kpi_daily_refresh (job dependency).
#
# Uses the SAME model-serving pattern as the app (databricks-claude-sonnet-4-6),
# so NO external Anthropic API key is needed. Never fabricates metrics — the
# prompt only receives values that exist in kpi_daily_summary, and the job
# degrades gracefully (writes nothing, logs a warning) if the model call fails.
# =============================================================================

# COMMAND ----------
# MAGIC %md ## Section 0 — Config

# COMMAND ----------

import json
from datetime import datetime, timezone
from pyspark.sql import functions as F
from pyspark.sql.types import (StructType, StructField, StringType, TimestampType)

OUT            = "datagroup_mdl.mdl_sales_analytics"
SUMMARY_TABLE  = f"{OUT}.kpi_daily_summary"
INSIGHTS_TABLE = f"{OUT}.kpi_ai_insights_log"
LLM_ENDPOINT   = "databricks-claude-sonnet-4-6"   # same endpoint the app/job3 use

# COMMAND ----------
# MAGIC %md ## Section 1 — Pull the latest KPI summary row

# COMMAND ----------

rows = spark.sql(f"""
    SELECT * FROM {SUMMARY_TABLE}
    ORDER BY report_date DESC
    LIMIT 1
""").collect()
if not rows:
    dbutils.notebook.exit("No kpi_daily_summary rows yet — run kpi_daily_refresh first.")
kpi = rows[0].asDict()
REPORT_DATE = str(kpi["report_date"])
print(f"[kpi-ai] generating insights for {REPORT_DATE}")

# COMMAND ----------
# MAGIC %md ## Section 2 — Build the prompt (spec Deliverable 8 framework + thresholds)

# COMMAND ----------

def _fmt_money(v):
    return f"${v/1e6:.1f}M" if isinstance(v, (int, float)) and v is not None else "n/a"
def _fmt(v, suffix=""):
    return f"{v}{suffix}" if v is not None else "n/a"

SYSTEM = """You are a senior sales analytics advisor for a B2B SaaS company (GoTo).
You receive daily KPI data and produce structured, actionable insights for the
executive team (CEO, CFO, CRO).

ANALYSIS FRAMEWORK (allocate effort accordingly):
  25% Revenue performance (quota attainment, gap, trajectory)
  25% Pipeline health (coverage, velocity, attainment)
  20% Deal quality (ADS, close rate, large-deal risk)
  15% Leading indicators (opps created, MQL, created pipeline)
  15% Forecast & actions (will we hit quota? the #1 action)

OUTPUT RULES:
- Return ONLY valid JSON. No markdown, no preamble.
- 5-7 insights, ordered by business severity (CRITICAL first).
- Each insight needs a concrete recommended_action with a named owner.
- NEVER fabricate metrics not in the input. If a metric is missing/null, raise the
  data gap as its own insight.

STATUS THRESHOLDS:
  CRITICAL : attainment <70%, coverage <2x, win_rate <60%, close_rate_$ <15%
  WARNING  : attainment 70-89%, coverage 2-3x, win_rate 60-74%, close_rate_$ 15-21%
  ON_TRACK : attainment >=90%, coverage >=3x, win_rate >=75%, close_rate_$ >=22%

JSON SCHEMA:
{"insights":[{"severity":"CRITICAL|WARNING|ON_TRACK","title":"...","metric":"...",
"current_value":"...","target_value":"...","root_cause":"...",
"recommended_action":"...","action_owner":"CEO|CFO|CRO|VP Sales|VP Marketing|Manager|Rep",
"timeline":"This week|This month|This quarter","expected_impact":"..."}]}"""

USER = f"""Today is {REPORT_DATE}. Quarter {kpi.get('qtr_start')} to {kpi.get('qtr_end')},
data as of {kpi.get('data_as_of')}. Quarter-to-date KPIs:
- Won ACV QTD:        {_fmt_money(kpi.get('won_acv_qtr'))} (full-quarter plan {_fmt_money(kpi.get('total_quota_full'))})
- Quota attainment:   {_fmt(kpi.get('attainment_pct'),'%')} (vs paced target {_fmt_money(kpi.get('paced_won_target'))})
- Revenue gap:        {_fmt_money(kpi.get('revenue_gap'))}
- Active pipeline:    {_fmt_money(kpi.get('active_pipeline'))}
- Pipeline coverage:  {_fmt(kpi.get('pipeline_coverage_ratio'),'x')}
- Pipeline attain %:  {_fmt(kpi.get('pipeline_attainment_pct'),'%')}
- # Deals won:        {_fmt(kpi.get('deals_won_qtr'))}
- Avg deal size:      {_fmt_money(kpi.get('avg_deal_size'))}
- Win rate:           {_fmt(kpi.get('win_rate_pct'),'%')}
- Close rate (vol):   {_fmt(kpi.get('close_rate_vol_pct'),'%')}
- Close rate ($):     {_fmt(kpi.get('close_rate_dollar_pct'),'%')}
- Opps created QTD:   {_fmt(kpi.get('opps_created_qtr'))}
- Created pipeline:   {_fmt_money(kpi.get('created_pipeline_qtr'))}
- Avg days to close:  {_fmt(kpi.get('avg_days_to_close'))}
- MQL count:          {_fmt(kpi.get('mql_count'))}
Return the JSON insights now."""

# COMMAND ----------
# MAGIC %md ## Section 3 — Call Claude via Databricks model serving

# COMMAND ----------

insights = []
try:
    from mlflow.deployments import get_deploy_client
    client = get_deploy_client("databricks")
    resp = client.predict(
        endpoint=LLM_ENDPOINT,
        inputs={
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user",   "content": USER},
            ],
            "max_tokens": 2048,
            "temperature": 0.2,
        },
    )
    raw = resp["choices"][0]["message"]["content"].strip()
    # strip ```json fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        raw = raw[4:].strip() if raw.lower().startswith("json") else raw.strip()
    insights = json.loads(raw).get("insights", [])
    print(f"[kpi-ai] model returned {len(insights)} insights")
except Exception as exc:
    print(f"[kpi-ai] WARN model call/parse failed ({exc}); writing nothing this run")

# COMMAND ----------
# MAGIC %md ## Section 4 — Persist (idempotent: replace today's rows)

# COMMAND ----------

if insights:
    schema = StructType([
        StructField("report_date",        StringType()),
        StructField("rank",               StringType()),
        StructField("severity",           StringType()),
        StructField("title",              StringType()),
        StructField("metric",             StringType()),
        StructField("current_value",      StringType()),
        StructField("target_value",       StringType()),
        StructField("root_cause",         StringType()),
        StructField("recommended_action", StringType()),
        StructField("action_owner",       StringType()),
        StructField("timeline",           StringType()),
        StructField("expected_impact",    StringType()),
        StructField("created_at",         TimestampType()),
    ])
    now = datetime.now(timezone.utc)
    records = [
        (REPORT_DATE, str(i+1),
         str(d.get("severity","")), str(d.get("title","")), str(d.get("metric","")),
         str(d.get("current_value","")), str(d.get("target_value","")),
         str(d.get("root_cause","")), str(d.get("recommended_action","")),
         str(d.get("action_owner","")), str(d.get("timeline","")),
         str(d.get("expected_impact","")), now)
        for i, d in enumerate(insights)
    ]
    df = spark.createDataFrame(records, schema)

    if not spark.catalog.tableExists(INSIGHTS_TABLE):
        df.write.format("delta").partitionBy("report_date").saveAsTable(INSIGHTS_TABLE)
    else:
        spark.sql(f"DELETE FROM {INSIGHTS_TABLE} WHERE report_date = '{REPORT_DATE}'")
        df.write.format("delta").mode("append").saveAsTable(INSIGHTS_TABLE)
    print(f"[kpi-ai] wrote {len(records)} insights -> {INSIGHTS_TABLE}")
else:
    print("[kpi-ai] no insights to write (model unavailable or empty)")

print(f"[kpi-ai] DONE {REPORT_DATE}")
