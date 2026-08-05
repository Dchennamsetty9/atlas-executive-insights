# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Config
# Atlas | Job2 — AI Insights Generation
# ══════════════════════════════════════════════════════════════
# Reads atlas_kpi_daily_summary -> runs rule engine ->
# calls Databricks FM API -> writes to atlas_insights_cache
# Schedule: every 6h at :30 (offset 30m after Job1 refresh)
# ══════════════════════════════════════════════════════════════

import json
import uuid
from datetime import datetime, timedelta
from pyspark.sql import Row
from pyspark.sql.types import (
    StructType, StructField, StringType, TimestampType,
    DateType, DoubleType
)
import mlflow.deployments

# ── Config ─────────────────────────────────────────────────────
CATALOG         = "datagroup_mdl"
SCHEMA          = "mdl_sales_analytics"
INSIGHTS_TABLE  = f"{CATALOG}.{SCHEMA}.atlas_insights_cache"
FM_ENDPOINT     = "databricks-claude-sonnet-4-5"   # Databricks Foundation Model endpoint
INSIGHTS_TTL_H  = 6                                 # hours before cache expires

print(f"Atlas AI Insights -- starting | endpoint={FM_ENDPOINT}")
print(f"Run date: {spark.sql('SELECT CURRENT_DATE()').collect()[0][0]}")

# COMMAND ----------

# DBTITLE 1,Load KPIs
# Load latest KPI snapshot + rep/territory supporting data
kpi = spark.sql(f"""
    SELECT * FROM {CATALOG}.{SCHEMA}.atlas_kpi_daily_summary
    ORDER BY report_date DESC LIMIT 1
""").first()

territories = spark.sql(f"""
    SELECT territory, won_acv_qtr, territory_quota, attainment_pct,
           pipeline_acv, coverage_ratio, rep_count
    FROM {CATALOG}.{SCHEMA}.atlas_kpi_daily_by_territory
    WHERE report_date = CURRENT_DATE()
    ORDER BY attainment_pct ASC
""").collect()

at_risk_reps = spark.sql(f"""
    SELECT rep_name, territory, won_acv_qtr, pipeline_acv, win_rate_pct
    FROM {CATALOG}.{SCHEMA}.atlas_kpi_daily_by_rep
    WHERE report_date = CURRENT_DATE()
      AND status_indicator = 'R'
    ORDER BY won_acv_qtr ASC
    LIMIT 10
""").collect()

print(f"KPI date     : {kpi.report_date}")
print(f"Won ACV      : ${kpi.won_acv_qtr/1e6:.2f}M  |  Attainment: {kpi.attainment_pct:.1f}%")
print(f"Pipeline ACV : ${kpi.pipeline_acv/1e6:.1f}M  |  Coverage:   {kpi.pipeline_coverage_ratio:.2f}x")
print(f"Territories  : {len(territories)}  |  At-risk reps: {len(at_risk_reps)}")

# COMMAND ----------

# DBTITLE 1,Rule Engine
# ── Rule engine: classify each KPI card status ────────────────

def classify(value, target, higher_is_better=True):
    """Returns (status_label, attainment_pct)."""
    if not target or target == 0:
        return ('Watch Closely', None)
    pct = (value / target * 100) if higher_is_better else (target / value * 100)
    if pct >= 100:
        return ('Exceeding Target', round(pct, 1))
    elif pct >= 80:
        return ('Watch Closely', round(pct, 1))
    else:
        return ('Action Required', round(pct, 1))

# Targets — aligned to app screenshot definitions
TGT_WON_ACV        = float(kpi.full_quota)           # full quarter plan
TGT_PIPELINE       = float(kpi.total_quota) * 2.5    # 2.5x paced quota
TGT_CREATED_PIPE   = float(kpi.total_quota) * 3.0    # 3x paced quota
TGT_WIN_RATE       = 35.0    # %
TGT_CLOSE_VOL      = 30.0    # %
TGT_CLOSE_DOL      = 20.0    # %
TGT_COVERAGE       = 3.0     # ratio
TGT_WON_ATT        = 100.0   # %
TGT_PIPE_ATT       = 100.0   # %
TGT_DAYS_CLOSE     = 45      # days (lower = better)

kpi_statuses = {
    'WON_ACV':             classify(kpi.won_acv_qtr,            TGT_WON_ACV),
    'PIPELINE_ACV':        classify(kpi.pipeline_acv,            TGT_PIPELINE),
    'CREATED_PIPELINE':    classify(kpi.created_pipeline_qtr,    TGT_CREATED_PIPE),
    'WIN_RATE':            classify(float(kpi.win_rate_pct),     TGT_WIN_RATE),
    'CLOSE_RATE_VOL':      classify(float(kpi.close_rate_vol_pct), TGT_CLOSE_VOL),
    'CLOSE_RATE_DOLLAR':   classify(kpi.close_rate_dollar_pct,   TGT_CLOSE_DOL),
    'COVERAGE':            classify(kpi.pipeline_coverage_ratio, TGT_COVERAGE),
    'WON_ATTAINMENT':      classify(kpi.attainment_pct,          TGT_WON_ATT),
    'PIPELINE_ATTAINMENT': classify(kpi.pipeline_attainment_pct, TGT_PIPE_ATT),
    'DAYS_TO_CLOSE':       classify(TGT_DAYS_CLOSE, kpi.avg_days_to_close),  # lower is better
    'MQL_COUNT':           ('Watch Closely', None),
    'AVG_DEAL_SIZE':       ('Watch Closely', None),
    'AVG_OPP_SIZE':        ('Watch Closely', None),
    'OPPS_CREATED':        ('Watch Closely', None),
}

action_required = [k for k,(s,_) in kpi_statuses.items() if s == 'Action Required']
exceeding       = [k for k,(s,_) in kpi_statuses.items() if s == 'Exceeding Target']
print(f"Action Required  ({len(action_required)}): {action_required}")
print(f"Exceeding Target ({len(exceeding)}): {exceeding}")

# COMMAND ----------

# DBTITLE 1,Call FM API
# ── Databricks Foundation Model API calls ─────────────────────

fm_client = mlflow.deployments.get_deploy_client("databricks")

def call_fm(prompt: str, system: str = None, max_tokens: int = 1500) -> str:
    """Call Databricks FM endpoint, return response text."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = fm_client.predict(
            endpoint=FM_ENDPOINT,
            inputs={"messages": messages, "max_tokens": max_tokens, "temperature": 0.3}
        )
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"FM API error: {e}")
        return ""

SYSTEM = (
    "You are an AI sales analytics assistant for GoTo. "
    "Generate concise, actionable insights for sales leadership. "
    "Be specific with numbers. Never use placeholder text. "
    "Output ONLY valid JSON when asked for JSON."
)

# Build KPI context block (reused across prompts)
kpi_ctx = f"""Current QTD KPI Snapshot (as of {kpi.report_date}):
  Won ACV:             ${kpi.won_acv_qtr/1e6:.2f}M  vs  target ${TGT_WON_ACV/1e6:.2f}M  -> {kpi_statuses['WON_ACV'][0]}
  Won Attainment:      {kpi.attainment_pct:.1f}%  -> {kpi_statuses['WON_ATTAINMENT'][0]}
  Active Pipeline:     ${kpi.pipeline_acv/1e6:.1f}M  -> {kpi_statuses['PIPELINE_ACV'][0]}
  Pipeline Attainment: {kpi.pipeline_attainment_pct:.1f}%  -> {kpi_statuses['PIPELINE_ATTAINMENT'][0]}
  Created Pipeline:    ${kpi.created_pipeline_qtr/1e6:.1f}M  -> {kpi_statuses['CREATED_PIPELINE'][0]}
  Win Rate:            {kpi.win_rate_pct:.1f}%  vs target {TGT_WIN_RATE}%  -> {kpi_statuses['WIN_RATE'][0]}
  Close Rate (Vol):    {kpi.close_rate_vol_pct:.1f}%  vs target {TGT_CLOSE_VOL}%  -> {kpi_statuses['CLOSE_RATE_VOL'][0]}
  Close Rate ($):      {kpi.close_rate_dollar_pct:.1f}%  vs target {TGT_CLOSE_DOL}%  -> {kpi_statuses['CLOSE_RATE_DOLLAR'][0]}
  Coverage Ratio:      {kpi.pipeline_coverage_ratio:.2f}x  vs target {TGT_COVERAGE}x  -> {kpi_statuses['COVERAGE'][0]}
  MQL Count:           {kpi.mql_count}
  Avg Deal Size:       ${kpi.avg_deal_size/1e3:.1f}K
  Avg Days to Close:   {kpi.avg_days_to_close:.0f} days
  Revenue Gap:         ${kpi.revenue_gap/1e6:.2f}M remaining to hit paced quota"""

# ── Prompt 1: per-KPI card insights (JSON array) ──────────────
kpi_prompt = f"""{kpi_ctx}

Generate a JSON array with one object per KPI. Each object must have:
  "kpi_name":       one of [WON_ACV, WON_ATTAINMENT, PIPELINE_ACV, PIPELINE_ATTAINMENT, CREATED_PIPELINE, WIN_RATE, CLOSE_RATE_VOL, CLOSE_RATE_DOLLAR, COVERAGE, MQL_COUNT, AVG_DEAL_SIZE, OPPS_CREATED, AVG_OPP_SIZE, DAYS_TO_CLOSE]
  "status":         "Action Required" | "Watch Closely" | "Exceeding Target"
  "headline":       max 12 words, specific to the number shown
  "narrative":      2 sentences, business context, no generic filler
  "recommendation": one specific, actionable item for sales leadership

Return ONLY the JSON array. No markdown fences, no extra text."""

print("[1/3] Calling FM API for KPI card insights...")
kpi_insights_raw = call_fm(kpi_prompt, system=SYSTEM, max_tokens=2500)
print(f"  Response: {len(kpi_insights_raw)} chars")

# ── Prompt 2: Revenue gap narrative ───────────────────────────
bottom_terr = chr(10).join(
    f"  {t.territory or 'Unknown'}: {(t.attainment_pct or 0):.0f}% attainment, ${(t.won_acv_qtr or 0)/1e6:.1f}M won"
    for t in territories[:3]
)
gap_prompt = f"""{kpi_ctx}

Revenue Gap Detail:
  Lost ACV impact:  ${abs(float(kpi.lost_volume_impact))/1e6:.2f}M lost to competition/churn this quarter
  Pipeline gap:     ${abs(float(kpi.pipeline_gap))/1e6:.2f}M pipeline vs target
  Bottom territories (by attainment):
{bottom_terr}

Write a 3-sentence executive narrative for the Revenue Gap section.
Identify the single biggest lever to close the ${kpi.revenue_gap/1e6:.1f}M gap. Be specific with dollar amounts."""

print("[2/3] Calling FM API for revenue gap narrative...")
gap_narrative = call_fm(gap_prompt, system=SYSTEM, max_tokens=400)
print(f"  Response: {len(gap_narrative)} chars")

# ── Prompt 3: At-risk rep coaching summary ────────────────────
rep_summary = ""
if at_risk_reps:
    rep_lines = chr(10).join(
        f"  {r.rep_name} ({r.territory}): ${r.won_acv_qtr/1e6:.2f}M won, "
        f"${r.pipeline_acv/1e6:.2f}M pipeline, {r.win_rate_pct:.0f}% win rate"
        for r in at_risk_reps[:5]
    )
    rep_prompt = f"""The following {len(at_risk_reps)} reps are At-Risk (Red) this quarter:\n{rep_lines}\n\nWrite 2 sentences for frontline managers: what pattern do you see, and what is the single most important coaching action?"""
    print(f"[3/3] Calling FM API for {len(at_risk_reps)} at-risk reps...")
    rep_summary = call_fm(rep_prompt, system=SYSTEM, max_tokens=300)
    print(f"  Response: {len(rep_summary)} chars")
else:
    print("[3/3] No at-risk reps — skipping rep prompt")

print("\nAll FM API calls complete.")

# COMMAND ----------

# DBTITLE 1,Write to atlas_insights_cache
# ── Parse FM responses + build rows ──────────────────────────

now        = datetime.utcnow()
expires_at = now + timedelta(hours=INSIGHTS_TTL_H)
report_date = kpi.report_date
rows = []

# 1) KPI card insights — parse JSON from FM response
try:
    raw = kpi_insights_raw.strip()
    if raw.startswith("```"):                          # strip markdown fences if present
        raw = "\n".join(raw.split("\n")[1:])
        raw = raw.rsplit("```", 1)[0].strip()
    kpi_insights = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"JSON parse warning: {e} -- storing raw response as single insight")
    kpi_insights = [{"kpi_name": "KPI_SUMMARY", "status": "Watch Closely",
                     "headline": "AI parse error -- see narrative for raw output",
                     "narrative": kpi_insights_raw[:800], "recommendation": "Check FM endpoint."}]

for item in kpi_insights:
    # Supplement status from rule engine if FM returned something unexpected
    rule_status = kpi_statuses.get(item.get("kpi_name", ""), (item.get("status", "Watch Closely"), None))[0]
    rows.append(Row(
        insight_id     = str(uuid.uuid4()),
        generated_at   = now,
        report_date    = report_date,
        insight_type   = "kpi_card",
        kpi_name       = item.get("kpi_name", ""),
        kpi_value      = None,
        kpi_status     = rule_status,
        headline       = item.get("headline", ""),
        narrative      = item.get("narrative", ""),
        recommendation = item.get("recommendation", ""),
        expires_at     = expires_at,
        load_timestamp = now,
    ))

# 2) Revenue gap narrative row
rows.append(Row(
    insight_id     = str(uuid.uuid4()),
    generated_at   = now,
    report_date    = report_date,
    insight_type   = "revenue_gap",
    kpi_name       = "Revenue Gap Decomposition",
    kpi_value      = float(kpi.revenue_gap),
    kpi_status     = kpi_statuses["WON_ATTAINMENT"][0],
    headline       = f"${kpi.revenue_gap/1e6:.1f}M remaining to hit paced quota this quarter",
    narrative      = gap_narrative,
    recommendation = "",
    expires_at     = expires_at,
    load_timestamp = now,
))

# 3) At-risk rep summary row
if rep_summary:
    rows.append(Row(
        insight_id     = str(uuid.uuid4()),
        generated_at   = now,
        report_date    = report_date,
        insight_type   = "rep_alert",
        kpi_name       = f"At-Risk Reps ({len(at_risk_reps)})",
        kpi_value      = float(len(at_risk_reps)),
        kpi_status     = "Action Required",
        headline       = f"{len(at_risk_reps)} reps flagged At-Risk with low pipeline cover",
        narrative      = rep_summary,
        recommendation = "",
        expires_at     = expires_at,
        load_timestamp = now,
    ))

# ── Write to Delta table ──────────────────────────────────────
schema = StructType([
    StructField("insight_id",     StringType(),    False),
    StructField("generated_at",   TimestampType(), True),
    StructField("report_date",    DateType(),      True),
    StructField("insight_type",   StringType(),    True),
    StructField("kpi_name",       StringType(),    True),
    StructField("kpi_value",      DoubleType(),    True),
    StructField("kpi_status",     StringType(),    True),
    StructField("headline",       StringType(),    True),
    StructField("narrative",      StringType(),    True),
    StructField("recommendation", StringType(),    True),
    StructField("expires_at",     TimestampType(), True),
    StructField("load_timestamp", TimestampType(), True),
])

df_insights = spark.createDataFrame(rows, schema)

(df_insights.write
    .format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .saveAsTable(INSIGHTS_TABLE))

print(f"Written {len(rows)} insights to {INSIGHTS_TABLE}")
print(f"  kpi_card rows : {sum(1 for r in rows if r.insight_type == 'kpi_card')}")
print(f"  revenue_gap   : {sum(1 for r in rows if r.insight_type == 'revenue_gap')}")
print(f"  rep_alert     : {sum(1 for r in rows if r.insight_type == 'rep_alert')}")
print(f"  expires_at    : {expires_at} UTC")

# COMMAND ----------

# DBTITLE 1,GRANT + Data Quality Check
# ── DQ: verify today's rows by type ──────────────────────────
dq = spark.sql(f"""
    SELECT
        insight_type,
        COUNT(*) AS row_count,
        COUNT(CASE WHEN kpi_status = 'Action Required'  THEN 1 END) AS action_required,
        COUNT(CASE WHEN kpi_status = 'Exceeding Target' THEN 1 END) AS exceeding,
        MAX(generated_at)                                            AS latest_generated
    FROM {INSIGHTS_TABLE}
    WHERE report_date = CURRENT_DATE()
    GROUP BY insight_type
    ORDER BY insight_type
""")
display(dq)

# ── Sample: show first 3 kpi_card headlines ───────────────────
print("\nSample headlines:")
sample = spark.sql(f"""
    SELECT kpi_name, kpi_status, headline
    FROM {INSIGHTS_TABLE}
    WHERE report_date = CURRENT_DATE()
      AND insight_type = 'kpi_card'
    ORDER BY generated_at DESC
    LIMIT 5
""").collect()
for row in sample:
    print(f"  [{row.kpi_status:20s}] {row.kpi_name}: {row.headline}")

# COMMAND ----------

# DBTITLE 1,GRANT — SP access to insights cache (run manually)
# MAGIC %sql
# MAGIC -- Run manually once after first execution (auto-approval blocks GRANT in automated cells)
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_insights_cache
# MAGIC   TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;

# COMMAND ----------




