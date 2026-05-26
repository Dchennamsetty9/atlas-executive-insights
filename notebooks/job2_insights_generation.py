# Databricks notebook source
# Atlas Executive Insights — Job 2: AI Insights Generation
# Schedule: every 6 hours (offset 30 min from Job 1)
# Writes: atlas.insights_cache
# Reads:  atlas.metrics_summary (gold), atlas.forecast_results (gold, if available)
# Uses:   Databricks Foundation Model API (databricks-claude-sonnet-4-6)

# COMMAND ----------
# MAGIC %md ## Atlas Job 2 — AI Insights Generation
# MAGIC
# MAGIC Two-phase approach:
# MAGIC 1. **Rule engine** — deterministic threshold checks produce structured data
# MAGIC 2. **LLM enrichment** — each rule finding is sent to Claude Sonnet to generate the
# MAGIC    human-readable `title`, `description`, `recommendation`, and `why_text`
# MAGIC
# MAGIC Falls back gracefully to rule-only text if the LLM endpoint is unavailable.

# COMMAND ----------

import uuid, json, re, os
from datetime import datetime, timedelta
from pyspark.sql import functions as F

CATALOG     = "datagroup_mdl"
GOLD_SCHEMA = "atlas"
GOLD        = f"{CATALOG}.{GOLD_SCHEMA}"
RUN_ID      = str(uuid.uuid4())
NOW         = datetime.utcnow()
TTL_HOURS   = 6
EXPIRES_AT  = NOW + timedelta(hours=TTL_HOURS)

print(f"[Job2] Starting Insights Generation — {NOW.isoformat()} | run_id={RUN_ID}")

# COMMAND ----------
# MAGIC %md ### Step 1 — Load current metrics and forecast data

# COMMAND ----------

metrics = (
    spark.table(f"{GOLD}.metrics_summary")
    .filter(F.col("geo") == "All")
    .filter(F.col("channel") == "All")
    .filter(F.col("product") == "All")
).collect()

metrics_dict = {row["metric_key"]: dict(row.asDict()) for row in metrics}
print(f"[Job2] Loaded {len(metrics_dict)} metrics from metrics_summary")

# Load latest forecast (may not exist on first run)
try:
    latest_run = spark.sql(f"""
        SELECT metric_key, model_name, most_likely_90d, trend_status, risk_level, mape
        FROM {GOLD}.forecast_results
        WHERE generated_at = (SELECT MAX(generated_at) FROM {GOLD}.forecast_results)
        AND geo = 'All'
    """).collect()
    forecast_dict = {row["metric_key"]: dict(row.asDict()) for row in latest_run}
    print(f"[Job2] Loaded {len(forecast_dict)} forecast rows")
except Exception as e:
    forecast_dict = {}
    print(f"[Job2] No forecast data available yet: {e}")

# COMMAND ----------
# MAGIC %md ### Step 2 — Rule engine: threshold checks

# COMMAND ----------

RULE_DEFINITIONS = [
    # (metric_key, threshold_pct, severity, category, icon)
    ("won_pipeline",    0.75, "high",   "pipeline",   "🔴"),
    ("won_pipeline",    0.90, "medium", "pipeline",   "🟡"),
    ("win_rate",        0.75, "high",   "conversion", "🔴"),
    ("win_rate",        0.90, "medium", "conversion", "🟡"),
    ("active_pipeline", 0.80, "medium", "pipeline",   "🟡"),
    ("coverage",        0.80, "medium", "pipeline",   "🟡"),
    ("ads",             0.90, "low",    "deals",      "💡"),
    ("opps_created",    0.85, "medium", "pipeline",   "🟡"),
    ("mql",             0.80, "medium", "pipeline",   "🟡"),
]

# Also generate positive highlights (exceeding)
POSITIVE_THRESHOLDS = [
    ("won_pipeline",    1.10, "low",    "pipeline",   "🚀"),
    ("win_rate",        1.10, "low",    "conversion", "🚀"),
    ("ads",             1.05, "low",    "deals",      "💚"),
]

findings = []  # List of dicts to pass to LLM

def make_finding(m_key, actual, paced, annual, attainment_pct, severity, category, icon, finding_type="underperforming"):
    return {
        "metric_key":    m_key,
        "metric_label":  actual,  # will be replaced
        "actual":        float(actual or 0),
        "paced_target":  float(paced or 0),
        "annual_target": float(annual or 0),
        "attainment_pct": float(attainment_pct or 0),
        "severity":      severity,
        "category":      category,
        "icon":          icon,
        "finding_type":  finding_type,
        "trend_status":  forecast_dict.get(m_key, {}).get("trend_status", "unknown"),
        "risk_level":    forecast_dict.get(m_key, {}).get("risk_level", "unknown"),
        "mape":          forecast_dict.get(m_key, {}).get("mape"),
    }

for (m_key, threshold, severity, category, icon) in RULE_DEFINITIONS:
    m = metrics_dict.get(m_key)
    if not m:
        continue
    actual  = m["metric_value"] or 0
    paced   = m["target_value"] or 0
    annual  = m["annual_target"] or 0
    attainment = m["attainment_pct"] or 0
    if paced > 0 and (actual / paced) < threshold:
        findings.append(make_finding(m_key, actual, paced, annual, attainment, severity, category, icon, "underperforming"))

for (m_key, threshold, severity, category, icon) in POSITIVE_THRESHOLDS:
    m = metrics_dict.get(m_key)
    if not m:
        continue
    actual = m["metric_value"] or 0
    paced  = m["target_value"] or 0
    if paced > 0 and (actual / paced) >= threshold:
        findings.append(make_finding(m_key, actual, paced, m["annual_target"], m["attainment_pct"], severity, category, icon, "exceeding"))

# Deduplicate: keep highest severity per metric
seen = {}
deduped = []
sev_rank = {"high": 0, "medium": 1, "low": 2}
for f in findings:
    k = f["metric_key"]
    if k not in seen or sev_rank[f["severity"]] < sev_rank[seen[k]]:
        seen[k] = f["severity"]
        deduped.append(f)

print(f"[Job2] Rule engine produced {len(deduped)} findings")

# COMMAND ----------
# MAGIC %md ### Step 3 — LLM enrichment via Databricks Foundation Model API

# COMMAND ----------

try:
    from databricks.sdk import WorkspaceClient
    client = WorkspaceClient()
    LLM_AVAILABLE = True
    LLM_ENDPOINT  = "databricks-claude-sonnet-4-6"
    print(f"[Job2] LLM available — endpoint: {LLM_ENDPOINT}")
except Exception as e:
    client = None
    LLM_AVAILABLE = False
    print(f"[Job2] LLM not available: {e} — will use rule-based text only")


SYSTEM_PROMPT = (
    "You are an executive sales analytics assistant. Given a sales KPI finding, "
    "write concise, business-focused insight text. Be direct and actionable. "
    "No marketing fluff. Use specific numbers when provided. Respond ONLY with "
    "a JSON object containing: title (max 60 chars), description (1-2 sentences), "
    "recommendation (1 concrete action), why_text (1 sentence explaining why this "
    "insight was surfaced). No markdown, no code fences — raw JSON only."
)

def fmt_money(v):
    if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def llm_enrich(finding: dict) -> dict:
    """Call LLM to get title/description/recommendation/why_text for a finding."""
    if not LLM_AVAILABLE:
        return rule_based_text(finding)

    prompt = (
        f"Metric: {finding['metric_key'].replace('_', ' ').title()}\n"
        f"Current value: {fmt_money(finding['actual']) if finding['actual'] > 1000 else round(finding['actual'],1)}\n"
        f"Paced target: {fmt_money(finding['paced_target']) if finding['paced_target'] > 1000 else round(finding['paced_target'],1)}\n"
        f"Attainment: {finding['attainment_pct']:.1f}%\n"
        f"Finding type: {finding['finding_type']}\n"
        f"Trend: {finding['trend_status']}\n"
        f"Risk level: {finding['risk_level']}\n"
        "Generate the JSON insight."
    )

    try:
        response = client.serving_endpoints.query(
            name=LLM_ENDPOINT,
            messages=[
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": prompt},
            ],
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        # Strip accidental code fences if LLM adds them
        raw = re.sub(r"^```json?\n?", "", raw).rstrip("`").strip()
        parsed = json.loads(raw)
        return {
            "title":          parsed.get("title", ""),
            "description":    parsed.get("description", ""),
            "recommendation": parsed.get("recommendation", ""),
            "why_text":       parsed.get("why_text", ""),
            "model_used":     LLM_ENDPOINT,
        }
    except Exception as e:
        print(f"[Job2] LLM call failed for {finding['metric_key']}: {e}")
        return rule_based_text(finding)


def rule_based_text(finding: dict) -> dict:
    """Deterministic fallback when LLM is unavailable."""
    m_label = finding["metric_key"].replace("_", " ").title()
    actual  = finding["actual"]
    paced   = finding["paced_target"]
    att     = finding["attainment_pct"]
    a_fmt   = fmt_money(actual) if actual > 1000 else f"{round(actual,1)}"
    p_fmt   = fmt_money(paced)  if paced  > 1000 else f"{round(paced,1)}"

    if finding["finding_type"] == "exceeding":
        return {
            "title":          f"{m_label} exceeding pace at {att:.0f}%",
            "description":    f"{m_label} is at {a_fmt} vs paced target of {p_fmt} — {att:.0f}% attainment.",
            "recommendation": f"Capture learnings and assess if target should be revised upward.",
            "why_text":       f"This metric is outperforming its paced quarterly target.",
            "model_used":     "rule_based",
        }
    else:
        gap = paced - actual
        g_fmt = fmt_money(gap) if gap > 1000 else f"{round(gap,1)}"
        return {
            "title":          f"{m_label} is {att:.0f}% of pace — {g_fmt} gap",
            "description":    f"{m_label} is at {a_fmt} vs paced target of {p_fmt}, leaving a gap of {g_fmt}.",
            "recommendation": f"Review {m_label.lower()} pipeline and prioritize highest-likelihood opportunities.",
            "why_text":       f"This metric is below its paced quarterly target threshold.",
            "model_used":     "rule_based",
        }

# COMMAND ----------
# MAGIC %md ### Step 4 — Write to atlas.insights_cache

# COMMAND ----------

# Expire all current active insights before writing new batch
spark.sql(f"""
    UPDATE {GOLD}.insights_cache
    SET is_active = FALSE
    WHERE is_active = TRUE
""")

insight_rows = []
for finding in deduped:
    enriched = llm_enrich(finding)
    insight_rows.append({
        "insight_id":     str(uuid.uuid4()),
        "title":          enriched["title"],
        "description":    enriched["description"],
        "recommendation": enriched["recommendation"],
        "why_text":       enriched["why_text"],
        "severity":       finding["severity"],
        "category":       finding["category"],
        "icon":           finding["icon"],
        "metric":         finding["metric_key"],
        "geo":            "All",
        "channel":        "All",
        "product":        "All",
        "model_used":     enriched.get("model_used", "rule_based"),
        "generated_at":   NOW,
        "expires_at":     EXPIRES_AT,
        "is_active":      True,
    })

if insight_rows:
    insight_df = spark.createDataFrame(insight_rows)
    insight_df.write.mode("append").saveAsTable(f"{GOLD}.insights_cache")
    print(f"[Job2] Written {len(insight_rows)} insights to {GOLD}.insights_cache")
else:
    print("[Job2] No insights generated — all metrics on track!")

print("[Job2] AI Insights Generation COMPLETE ✓")
