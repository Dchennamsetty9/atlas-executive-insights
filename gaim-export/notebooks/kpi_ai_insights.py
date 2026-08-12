# Databricks notebook source
# GAIM / Atlas — AI Insights Generation  (atlas_job2_insights_generation)
# =============================================================================
# Cell 1  Config
# Cell 2  Load KPIs from atlas_kpi_daily_summary + by_rep + by_territory
# Cell 3  Rule engine — classify all 14 KPI cards with threshold logic
# Cell 4  FM API calls — per-KPI JSON insights, revenue gap narrative, rep coaching
# Cell 5  Write to atlas_insights_cache  (6-hour TTL, Delta, created on first run)
# Cell 6  GRANT SP + data-quality check
#
# Runs AFTER atlas_job1_metrics_refresh (job dependency in bundle).
# FM endpoint: databricks-claude-sonnet-4-5  (swap in Cell 1 if needed;
#   any endpoint that accepts {"messages":[...]} and returns choices[0].message.content
#   works — including databricks-meta-llama-3-1-70b-instruct or gpt-4o via Azure AI).
# Degrades gracefully: if FM call fails the rule-engine rows are still written
# (insight_type="rule", fm_narrative=None), so the app always has something to show.
# =============================================================================

# COMMAND ----------
# MAGIC %md ## Cell 1 — Config

# COMMAND ----------

import json, uuid
from datetime import datetime, timezone, timedelta
from pyspark.sql import functions as F, Row
from pyspark.sql.types import (
    StructType, StructField,
    StringType, TimestampType, BooleanType
)

# ── Catalogs / tables ────────────────────────────────────────────────────────
OUT              = "datagroup_mdl.mdl_sales_analytics"
KPI_SUMMARY      = f"{OUT}.atlas_kpi_daily_summary"
KPI_BY_REP       = f"{OUT}.atlas_kpi_daily_by_rep"
KPI_BY_TERRITORY = f"{OUT}.atlas_kpi_daily_by_territory"
INSIGHTS_CACHE   = f"{OUT}.atlas_insights_cache"

# ── FM endpoint ──────────────────────────────────────────────────────────────
# Swap for any endpoint that accepts the OpenAI chat-completions schema:
#   databricks-claude-sonnet-4-5  (Anthropic, recommended)
#   databricks-claude-sonnet-4-6
#   databricks-meta-llama-3-1-70b-instruct  (open-weight fallback)
#   azure-gpt-4o  (if Azure AI endpoint is configured in your workspace)
FM_ENDPOINT      = "databricks-claude-sonnet-4-5"
FM_MAX_TOKENS    = 1200
INSIGHTS_TTL_H   = 6          # cache rows expire after 6 hours
SP_PRINCIPAL     = "324a6ec7-e988-42c7-8a7f-55465f5bea37"

NOW_UTC          = datetime.now(timezone.utc)
EXPIRES_AT       = NOW_UTC + timedelta(hours=INSIGHTS_TTL_H)

print(f"[insights] run={NOW_UTC.isoformat()}  expires={EXPIRES_AT.isoformat()}")
print(f"[insights] FM endpoint: {FM_ENDPOINT}")

# COMMAND ----------
# MAGIC %md ## Cell 2 — Load KPIs

# COMMAND ----------

# Latest summary row
rows = spark.sql(f"""
    SELECT * FROM {KPI_SUMMARY}
    ORDER BY report_date DESC LIMIT 1
""").collect()
if not rows:
    dbutils.notebook.exit(
        "atlas_kpi_daily_summary has no rows — run atlas_job1_metrics_refresh first."
    )
kpi = rows[0].asDict()
REPORT_DATE = str(kpi.get("report_date", "unknown"))
print(f"[insights] loaded KPIs for {REPORT_DATE}")

# At-risk reps (status_indicator = 'R')
try:
    at_risk_reps = spark.sql(f"""
        SELECT rep_name, territory, won_acv_qtr, pipeline_acv, win_rate_pct
        FROM {KPI_BY_REP}
        WHERE report_date = (SELECT MAX(report_date) FROM {KPI_BY_REP})
          AND status_indicator = 'R'
        ORDER BY won_acv_qtr ASC
        LIMIT 10
    """).collect()
except Exception as e:
    print(f"[insights] WARN: could not load at-risk reps ({e}); continuing")
    at_risk_reps = []

# Territory breakdown
try:
    territories = spark.sql(f"""
        SELECT territory, attainment_pct, pipeline_acv, coverage_ratio
        FROM {KPI_BY_TERRITORY}
        WHERE report_date = (SELECT MAX(report_date) FROM {KPI_BY_TERRITORY})
        ORDER BY attainment_pct ASC
    """).collect()
except Exception as e:
    print(f"[insights] WARN: could not load territories ({e}); continuing")
    territories = []

print(f"[insights] {len(at_risk_reps)} at-risk reps  |  {len(territories)} territories")

# COMMAND ----------
# MAGIC %md ## Cell 3 — Rule Engine (classify all 14 KPI cards)

# COMMAND ----------

def _pct(v):
    """Safe percentage — returns float or None."""
    try: return float(v)
    except: return None

def _money(v):
    try: return float(v)
    except: return 0.0

def classify(pct, exceed=110, warn=90):
    """Return status string matching the app's badge logic."""
    if pct is None: return "No Data"
    if pct >= exceed: return "Exceeding Target"
    if pct >= warn:   return "Watch Closely"
    return "Action Required"

# ── Build KPI card list (14 cards matching the app layout) ───────────────────
attainment     = _pct(kpi.get("attainment_pct"))
pipe_attain    = _pct(kpi.get("pipeline_attainment_pct") or kpi.get("created_attainment_pct"))
win_rate       = _pct(kpi.get("win_rate_pct"))
close_vol      = _pct(kpi.get("close_rate_vol_pct"))
close_dollar   = _pct(kpi.get("close_rate_dollar_pct"))

# Coverage: active_pipeline / (full_won_amount + buffer).  If pre-computed, use directly.
active_pipe    = _money(kpi.get("active_pipeline") or kpi.get("pipeline_acv"))
full_quota     = _money(kpi.get("full_won_amount") or kpi.get("full_quota") or 1)
coverage_raw   = (active_pipe / full_quota * 100) if full_quota else None
coverage_pct   = _pct(kpi.get("pipeline_coverage_ratio") or coverage_raw)

won_acv        = _money(kpi.get("won_acv_qtr") or kpi.get("won_acv"))
deals_won      = int(kpi.get("deals_won_qtr") or kpi.get("won_opps") or 0)
avg_deal       = _money(kpi.get("avg_deal_size"))
opps_created   = int(kpi.get("opps_created_qtr") or kpi.get("opened_opps") or 0)
created_pipe   = _money(kpi.get("created_pipeline_qtr") or kpi.get("created_pipeline"))
avg_opp_size   = _money(kpi.get("avg_opp_size"))
revenue_gap    = _money(kpi.get("revenue_gap"))
mql_count      = int(kpi.get("mql_count") or 0)

KPI_CARDS = [
    {"id": "won_acv",              "label": "WON ACV",               "value": won_acv,      "target": full_quota,    "pct": attainment},
    {"id": "deals_won",            "label": "DEALS WON",             "value": deals_won,    "target": None,          "pct": attainment},
    {"id": "avg_deal_size",        "label": "AVG DEAL SIZE",         "value": avg_deal,     "target": None,          "pct": None},
    {"id": "opps_created",         "label": "OPPS CREATED",          "value": opps_created, "target": None,          "pct": pipe_attain},
    {"id": "created_pipeline",     "label": "CREATED PIPELINE",      "value": created_pipe, "target": None,          "pct": pipe_attain},
    {"id": "avg_opp_size",         "label": "AVG OPP SIZE",          "value": avg_opp_size, "target": None,          "pct": None},
    {"id": "active_pipeline",      "label": "ACTIVE PIPELINE",       "value": active_pipe,  "target": full_quota,    "pct": coverage_pct},
    {"id": "close_rate_vol",       "label": "CLOSE RATE VOL",        "value": close_vol,    "target": 25.0,          "pct": (close_vol/25*100) if close_vol else None},
    {"id": "close_rate_dollar",    "label": "CLOSE RATE $",          "value": close_dollar, "target": 25.0,          "pct": (close_dollar/25*100) if close_dollar else None},
    {"id": "win_rate",             "label": "WIN RATE",              "value": win_rate,     "target": 30.0,          "pct": (win_rate/30*100) if win_rate else None},
    {"id": "coverage",             "label": "COVERAGE",              "value": coverage_pct, "target": 300.0,         "pct": (coverage_pct/3) if coverage_pct else None},
    {"id": "won_attainment",       "label": "WON ATTAINMENT %",      "value": attainment,   "target": 100.0,         "pct": attainment},
    {"id": "pipeline_attainment",  "label": "PIPELINE ATTAINMENT %", "value": pipe_attain,  "target": 100.0,         "pct": pipe_attain},
    {"id": "mql_count",            "label": "MQL COUNT",             "value": mql_count,    "target": None,          "pct": None},
]

for card in KPI_CARDS:
    card["status"] = classify(card["pct"])

action_required = [c for c in KPI_CARDS if c["status"] == "Action Required"]
watch_closely   = [c for c in KPI_CARDS if c["status"] == "Watch Closely"]
exceeding       = [c for c in KPI_CARDS if c["status"] == "Exceeding Target"]

print(f"[rule-engine] Action Required: {[c['label'] for c in action_required]}")
print(f"[rule-engine] Watch Closely:   {[c['label'] for c in watch_closely]}")
print(f"[rule-engine] Exceeding:       {[c['label'] for c in exceeding]}")

# COMMAND ----------
# MAGIC %md ## Cell 4 — FM API Calls (3 calls: KPI insights, revenue gap, rep coaching)

# COMMAND ----------

import mlflow.deployments

def _fm_call(messages: list, label: str) -> str | None:
    """Call the FM endpoint; return content string or None on any error."""
    try:
        client = mlflow.deployments.get_deploy_client("databricks")
        resp   = client.predict(
            endpoint=FM_ENDPOINT,
            inputs={"messages": messages, "max_tokens": FM_MAX_TOKENS}
        )
        content = resp["choices"][0]["message"]["content"]
        print(f"[fm] {label}: {len(content)} chars")
        return content
    except Exception as e:
        print(f"[fm] WARN {label} failed ({e}); skipping FM narrative")
        return None

def _safe_json(text: str | None, fallback):
    if not text: return fallback
    # Strip markdown fences if present
    clean = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:    return json.loads(clean)
    except: return fallback

# ── Call 1: Per-KPI structured insights ──────────────────────────────────────
kpi_summary_for_prompt = {
    "report_date":          REPORT_DATE,
    "won_acv":              won_acv,
    "deals_won":            deals_won,
    "attainment_pct":       attainment,
    "active_pipeline":      active_pipe,
    "coverage_pct":         coverage_pct,
    "win_rate_pct":         win_rate,
    "close_rate_vol_pct":   close_vol,
    "close_rate_dollar_pct":close_dollar,
    "pipeline_attainment_pct": pipe_attain,
    "created_pipeline":     created_pipe,
    "revenue_gap":          revenue_gap,
    "mql_count":            mql_count,
    "action_required_kpis": [c["label"] for c in action_required],
    "watch_closely_kpis":   [c["label"] for c in watch_closely],
}

kpi_insights_raw = _fm_call([
    {"role": "system", "content": (
        "You are an executive sales analyst. Given sales KPI data, return ONLY a JSON array "
        "of 4-6 insight objects. Each object must have exactly these keys: "
        "\"kpi_id\" (string, snake_case), \"headline\" (≤12 words), "
        "\"narrative\" (2 sentences, plain English, no jargon), "
        "\"recommendation\" (1 concrete action sentence), "
        "\"severity\" (\"critical\"|\"warning\"|\"positive\"). "
        "Never fabricate numbers not in the data. Return valid JSON only."
    )},
    {"role": "user", "content": f"KPI data:\n{json.dumps(kpi_summary_for_prompt, default=str)}"}
], label="kpi_insights")

kpi_insights_list = _safe_json(kpi_insights_raw, [])
print(f"[fm] parsed {len(kpi_insights_list)} KPI insight objects")

# ── Call 2: Revenue gap narrative ────────────────────────────────────────────
gap_context = {
    "revenue_gap":      revenue_gap,
    "full_quota":       full_quota,
    "won_acv":          won_acv,
    "attainment_pct":   attainment,
    "active_pipeline":  active_pipe,
    "win_rate_pct":     win_rate,
    "close_rate_vol":   close_vol,
    "report_date":      REPORT_DATE,
}
gap_raw = _fm_call([
    {"role": "system", "content": (
        "You are an executive sales analyst. Return a JSON object with exactly these keys: "
        "\"headline\" (≤12 words), \"narrative\" (3 sentences explaining the revenue gap "
        "and primary drivers), \"top_lever\" (the single most impactful action to close the gap). "
        "Return valid JSON only."
    )},
    {"role": "user", "content": f"Revenue gap context:\n{json.dumps(gap_context, default=str)}"}
], label="revenue_gap")
gap_insight = _safe_json(gap_raw, {})

# ── Call 3: At-risk rep coaching summary ─────────────────────────────────────
coaching_raw = None
if at_risk_reps:
    rep_data = [r.asDict() for r in at_risk_reps[:5]]
    coaching_raw = _fm_call([
        {"role": "system", "content": (
            "You are a sales manager coach. Given a list of at-risk reps (status=R), "
            "return a JSON object with: \"headline\" (≤10 words), "
            "\"narrative\" (2 sentences on the pattern across at-risk reps), "
            "\"coaching_actions\" (array of 3 concrete strings). "
            "Return valid JSON only."
        )},
        {"role": "user", "content": f"At-risk reps:\n{json.dumps(rep_data, default=str)}"}
    ], label="rep_coaching")
coaching_insight = _safe_json(coaching_raw, {})

# COMMAND ----------
# MAGIC %md ## Cell 5 — Write to atlas_insights_cache

# COMMAND ----------

SCHEMA = StructType([
    StructField("insight_id",        StringType(),    False),
    StructField("report_date",       StringType(),    False),
    StructField("insight_type",      StringType(),    False),   # kpi | revenue_gap | rep_coaching | rule
    StructField("kpi_id",            StringType(),    True),
    StructField("severity",          StringType(),    True),    # critical | warning | positive | info
    StructField("headline",          StringType(),    True),
    StructField("narrative",         StringType(),    True),
    StructField("recommendation",    StringType(),    True),
    StructField("fm_model",          StringType(),    True),
    StructField("is_fm_generated",   BooleanType(),   False),
    StructField("generated_at",      TimestampType(), False),
    StructField("expires_at",        TimestampType(), False),
])

rows_to_write = []

def _row(insight_type, kpi_id, severity, headline, narrative, recommendation, fm_generated):
    return Row(
        insight_id      = str(uuid.uuid4()),
        report_date     = REPORT_DATE,
        insight_type    = insight_type,
        kpi_id          = kpi_id,
        severity        = severity,
        headline        = headline or "",
        narrative       = narrative or "",
        recommendation  = recommendation or "",
        fm_model        = FM_ENDPOINT if fm_generated else None,
        is_fm_generated = fm_generated,
        generated_at    = NOW_UTC,
        expires_at      = EXPIRES_AT,
    )

# FM-generated KPI insights (highest fidelity)
for ins in kpi_insights_list:
    rows_to_write.append(_row(
        insight_type   = "kpi",
        kpi_id         = ins.get("kpi_id"),
        severity       = ins.get("severity", "info"),
        headline       = ins.get("headline"),
        narrative      = ins.get("narrative"),
        recommendation = ins.get("recommendation"),
        fm_generated   = True,
    ))

# Revenue gap insight
if gap_insight.get("headline"):
    rows_to_write.append(_row(
        insight_type   = "revenue_gap",
        kpi_id         = "revenue_gap",
        severity       = "critical" if (revenue_gap or 0) > full_quota * 0.1 else "warning",
        headline       = gap_insight.get("headline"),
        narrative      = gap_insight.get("narrative"),
        recommendation = gap_insight.get("top_lever"),
        fm_generated   = True,
    ))

# Rep coaching insight
if coaching_insight.get("headline"):
    rows_to_write.append(_row(
        insight_type   = "rep_coaching",
        kpi_id         = None,
        severity       = "warning",
        headline       = coaching_insight.get("headline"),
        narrative      = coaching_insight.get("narrative"),
        recommendation = "; ".join(coaching_insight.get("coaching_actions", [])),
        fm_generated   = True,
    ))

# Rule-engine fallback rows (always written — ensures cache is never empty)
for card in action_required:
    rows_to_write.append(_row(
        insight_type   = "rule",
        kpi_id         = card["id"],
        severity       = "critical",
        headline       = f"{card['label']} requires immediate attention",
        narrative      = (
            f"{card['label']} is at {round(card['pct'],1) if card['pct'] else 'N/A'}% of target — "
            f"below the 90% threshold. Immediate action needed to avoid quarter-end shortfall."
        ),
        recommendation = "Review pipeline coverage and accelerate deals in final stages.",
        fm_generated   = False,
    ))
for card in watch_closely:
    rows_to_write.append(_row(
        insight_type   = "rule",
        kpi_id         = card["id"],
        severity       = "warning",
        headline       = f"{card['label']} is in Watch Closely zone",
        narrative      = (
            f"{card['label']} is at {round(card['pct'],1) if card['pct'] else 'N/A'}% of target. "
            f"On track but trending toward risk — monitor closely."
        ),
        recommendation = "Schedule weekly cadence check to keep metric in green zone.",
        fm_generated   = False,
    ))

print(f"[cache] writing {len(rows_to_write)} insight rows for {REPORT_DATE}")

df_insights = spark.createDataFrame(rows_to_write, schema=SCHEMA)

# Create table on first run; otherwise delete today's rows then append
if not spark.catalog.tableExists(INSIGHTS_CACHE):
    (df_insights.write
        .format("delta")
        .partitionBy("report_date")
        .saveAsTable(INSIGHTS_CACHE))
    print(f"[cache] created {INSIGHTS_CACHE}")
else:
    spark.sql(f"DELETE FROM {INSIGHTS_CACHE} WHERE report_date = '{REPORT_DATE}'")
    (df_insights.write
        .format("delta")
        .mode("append")
        .saveAsTable(INSIGHTS_CACHE))
    print(f"[cache] appended to {INSIGHTS_CACHE}")

# Auto-expire rows older than TTL (keep table from growing unbounded)
spark.sql(f"""
    DELETE FROM {INSIGHTS_CACHE}
    WHERE expires_at < current_timestamp()
      AND report_date <> '{REPORT_DATE}'
""")
print("[cache] cleaned up expired rows")

# COMMAND ----------
# MAGIC %md ## Cell 6 — GRANT + Data Quality

# COMMAND ----------

# Grant app service principal read access
try:
    spark.sql(f"GRANT SELECT ON TABLE {INSIGHTS_CACHE} TO `{SP_PRINCIPAL}`")
    print(f"[grant] SELECT granted on {INSIGHTS_CACHE} to {SP_PRINCIPAL}")
except Exception as e:
    print(f"[grant] WARN: GRANT failed ({e}) — may already exist or require admin")

# Data quality check
dq = spark.sql(f"""
    SELECT
        insight_type,
        severity,
        COUNT(*)                AS row_count,
        SUM(CASE WHEN is_fm_generated THEN 1 ELSE 0 END) AS fm_rows,
        MIN(expires_at)         AS expires_at
    FROM {INSIGHTS_CACHE}
    WHERE report_date = '{REPORT_DATE}'
    GROUP BY insight_type, severity
    ORDER BY insight_type, severity
""").collect()

total = sum(r["row_count"] for r in dq)
print(f"\n[dq] {total} total rows in cache for {REPORT_DATE}")
for r in dq:
    print(f"  {r['insight_type']:15s} {r['severity']:10s}  rows={r['row_count']}  fm={r['fm_rows']}")

# Sample headlines
samples = spark.sql(f"""
    SELECT insight_type, severity, headline
    FROM {INSIGHTS_CACHE}
    WHERE report_date = '{REPORT_DATE}'
    ORDER BY insight_type, severity
    LIMIT 6
""").collect()
print("\n[sample headlines]")
for s in samples:
    print(f"  [{s['insight_type']}|{s['severity']}] {s['headline']}")

dbutils.notebook.exit(json.dumps({
    "status": "success",
    "report_date": REPORT_DATE,
    "rows_written": total,
    "fm_endpoint": FM_ENDPOINT,
    "expires_at": EXPIRES_AT.isoformat(),
}))

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
