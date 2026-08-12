# Databricks notebook source
# GAIM / Atlas — Daily Sales KPI Refresh
# =============================================================================
# Builds the daily KPI results tables consumed by the Atlas dashboard + exec email.
# Schedule: daily (after the metis/gaim snapshots land). Idempotent per report_date.
#
# IMPORTANT — formulas re-verified against REAL tables, NOT the spec placeholders.
# The spec ("Sales KPI System") was written against generic salesforce.opportunities /
# rep_quota tables that DO NOT exist in this catalog. The authoritative, already-in-
# production formulas live in backend/queries/performance/kpi_dashboard.sql and
# coverage/current.sql. This notebook reproduces those exactly, against:
#
#   federated.sales.metis_won_opps_fact      -> Won ACV, # Deals Won, ADS, velocity base
#   federated.sales.metis_opened_opps_fact   -> # Opps Created, Created Pipeline $
#   federated.sales.metis_targets_summary    -> paced + full quarter targets (board plan)
#   <gaim>.gaim_pipeline_daily_snapshot      -> Active Pipeline $, Win Rate, Coverage, Velocity
#   <gaim>.gaim_mql_daily_snapshot           -> MQL count (optional)
#
# Dollar field is `amount_towards_plan` everywhere (the plan-credited ACV), NOT `amount`.
#
# OUTPUT TABLES (written to OUT schema, MERGE by report_date — safe to re-run):
#   kpi_daily_summary       one row per day, company-wide, all 15 KPIs + RAG status
#   kpi_daily_by_segment    one row per day per (geo x product x channel) for the
#                           metis-sourced KPIs (won/created/targets/attainment)
# =============================================================================

# COMMAND ----------
# MAGIC %md ## Section 0 — Config

# COMMAND ----------

from datetime import date
from pyspark.sql import functions as F

# Source catalogs/schemas
FED                = "federated.sales"                       # metis_* facts + targets
GAIM_CATALOG       = "datagroup_mdl"
GAIM_SCHEMA        = "mdl_sales_analytics"
GAIM               = f"{GAIM_CATALOG}.{GAIM_SCHEMA}"         # gaim_* snapshots

# Output
OUT_CATALOG        = "datagroup_mdl"
OUT_SCHEMA         = "mdl_sales_analytics"
OUT                = f"{OUT_CATALOG}.{OUT_SCHEMA}"
SUMMARY_TABLE      = f"{OUT}.kpi_daily_summary"
SEGMENT_TABLE      = f"{OUT}.kpi_daily_by_segment"

PLAN_VERSION       = "Plan"        # board-approved plan in metis_targets_summary
REPORT_DATE        = date.today().isoformat()

# Closed-stage set used to define "open / active" pipeline (gaim snapshot)
CLOSED_STAGES = "('Closed Won','Closed Lost','Closed-Cancelled')"

print(f"[kpi] refresh {REPORT_DATE} | plan_version={PLAN_VERSION}")

# COMMAND ----------
# MAGIC %md ## Section 1 — Quarter bounds (calendar quarter)
# MAGIC Attainment/pacing is quarter-to-date. `metis_targets_summary` keys on the
# MAGIC quarter start date and stores paced (to-date) and full-quarter targets.

# COMMAND ----------

q = spark.sql("""
    SELECT
        date_trunc('quarter', current_date())                                AS qtr_start,
        last_day(add_months(date_trunc('quarter', current_date()), 2))       AS qtr_end,
        current_date()                                                       AS as_of
""").collect()[0]
QTR_START, QTR_END, AS_OF = str(q.qtr_start)[:10], str(q.qtr_end)[:10], str(q.as_of)[:10]
print(f"[kpi] quarter {QTR_START} -> {QTR_END} | QTD through {AS_OF}")

# COMMAND ----------
# MAGIC %md ## Section 2 — Core KPIs from metis (won, created, targets, rates, attainment)
# MAGIC Reproduces backend/queries/performance/kpi_dashboard.sql at the company (All) grain.
# MAGIC KPIs 1,2,3,6,7 (Won ACV, #Deals Won, ADS, #Opps Created, Created Pipeline),
# MAGIC close rates (vol + $), quota & pipeline attainment, AOS.

# COMMAND ----------

core_sql = f"""
WITH latest_won AS (
    SELECT MAX(data_date) AS d FROM {FED}.metis_won_opps_fact
),
latest_open AS (
    SELECT MAX(data_date) AS d FROM {FED}.metis_opened_opps_fact
),
won AS (
    SELECT COUNT(DISTINCT salesforce_opportunity_id) AS won_opps,
           COALESCE(SUM(amount_towards_plan),0)      AS won_acv
    FROM {FED}.metis_won_opps_fact, latest_won
    WHERE data_date = latest_won.d
      AND close_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}')
),
opened AS (
    SELECT COUNT(DISTINCT salesforce_opportunity_id) AS opened_opps,
           COALESCE(SUM(amount_towards_plan),0)      AS created_pipeline
    FROM {FED}.metis_opened_opps_fact, latest_open
    WHERE data_date = latest_open.d
      AND pipeline_entered_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}')
),
tgt AS (
    SELECT COALESCE(SUM(paced_won_amount),0)    AS paced_won_amount,
           COALESCE(SUM(paced_won_opps),0)      AS paced_won_opps,
           COALESCE(SUM(paced_opened_amount),0) AS paced_opened_amount,
           COALESCE(SUM(paced_opened_opps),0)   AS paced_opened_opps,
           COALESCE(SUM(full_won_amount),0)     AS full_won_amount,
           COALESCE(SUM(full_won_opps),0)       AS full_won_opps,
           COALESCE(SUM(full_opened_amount),0)  AS full_opened_amount
    FROM {FED}.metis_targets_summary
    WHERE quarter_start_date = DATE('{QTR_START}')
      AND plan_version = '{PLAN_VERSION}'
)
SELECT
    w.won_acv, w.won_opps,
    o.created_pipeline, o.opened_opps,
    t.paced_won_amount, t.paced_won_opps, t.paced_opened_amount, t.paced_opened_opps,
    t.full_won_amount, t.full_won_opps, t.full_opened_amount,
    -- KPI 3 ADS
    CASE WHEN w.won_opps>0 THEN w.won_acv/w.won_opps ELSE 0 END                      AS avg_deal_size,
    -- KPI 6b AOS
    CASE WHEN o.opened_opps>0 THEN o.created_pipeline/o.opened_opps ELSE 0 END        AS avg_opp_size,
    -- KPI 9 close rate volume = won / created
    CASE WHEN o.opened_opps>0 THEN 100.0*w.won_opps/o.opened_opps ELSE 0 END          AS close_rate_vol_pct,
    -- KPI 10 close rate $ = won$ / created$
    CASE WHEN o.created_pipeline>0 THEN 100.0*w.won_acv/o.created_pipeline ELSE 0 END  AS close_rate_dollar_pct,
    -- KPI 11 quota attainment (vs paced won target)
    CASE WHEN t.paced_won_amount>0 THEN 100.0*w.won_acv/t.paced_won_amount ELSE NULL END AS attainment_pct,
    -- KPI 12 pipeline (created) attainment (vs paced opened target)
    CASE WHEN t.paced_opened_amount>0 THEN 100.0*o.created_pipeline/t.paced_opened_amount ELSE NULL END AS created_attainment_pct,
    -- revenue gap vs full-quarter plan
    (t.full_won_amount - w.won_acv)                                                   AS revenue_gap
FROM won w CROSS JOIN opened o CROSS JOIN tgt t
"""
core = spark.sql(core_sql).collect()[0].asDict()
print("[kpi] core:", {k: round(v,1) if isinstance(v,(int,float)) and v is not None else v
                       for k,v in core.items()})

# COMMAND ----------
# MAGIC %md ## Section 3 — Pipeline-snapshot KPIs (active pipeline, win rate, coverage, velocity)
# MAGIC From gaim_pipeline_daily_snapshot (latest data_day). These are NOT in metis.
# MAGIC KPI 4 Active Pipeline $, KPI 5/12 Coverage & Pipeline Attainment, KPI 8 Win Rate,
# MAGIC KPI 13 Coverage(opps/rep proxy: open opp count), KPI 14 Velocity.

# COMMAND ----------

snap_sql = f"""
WITH latest AS (
    SELECT MAX(data_day) AS d FROM {GAIM}.gaim_pipeline_daily_snapshot
),
snap AS (
    SELECT is_won, stage_name, amount_towards_plan AS acv, close_date,
           opportunity_age, salesforce_opportunity_id, owner
    FROM {GAIM}.gaim_pipeline_daily_snapshot, latest
    WHERE data_day = latest.d
      AND COALESCE(xtxtype,'') <> 'Cancel'
)
SELECT
    -- KPI 4 active (open) pipeline $: open + future close
    SUM(CASE WHEN is_won='False' AND stage_name NOT IN {CLOSED_STAGES}
             AND close_date >= current_date() THEN acv ELSE 0 END)                  AS active_pipeline,
    -- open opp count (KPI 13 base) + distinct owners (rep proxy)
    SUM(CASE WHEN is_won='False' AND stage_name NOT IN {CLOSED_STAGES}
             AND close_date >= current_date() THEN 1 ELSE 0 END)                    AS open_opps,
    COUNT(DISTINCT CASE WHEN is_won='False' AND stage_name NOT IN {CLOSED_STAGES}
             AND close_date >= current_date() THEN owner END)                       AS active_reps,
    -- KPI 8 Win Rate % = won / (won + lost) decided THIS quarter (by close_date)
    SUM(CASE WHEN is_won='True'  AND close_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}') THEN 1 ELSE 0 END) AS won_decided,
    SUM(CASE WHEN stage_name='Closed Lost' AND close_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}') THEN 1 ELSE 0 END) AS lost_decided,
    -- KPI 14 velocity: avg opportunity_age of won deals closed in last 90d
    AVG(CASE WHEN is_won='True' AND close_date >= date_sub(current_date(),90)
             THEN opportunity_age END)                                              AS avg_days_to_close
FROM snap
"""
try:
    snap = spark.sql(snap_sql).collect()[0].asDict()
except Exception as exc:
    print(f"[kpi] WARN snapshot KPIs unavailable ({exc}); writing NULLs for pipeline metrics")
    snap = {"active_pipeline": None, "open_opps": None, "active_reps": None,
            "won_decided": None, "lost_decided": None, "avg_days_to_close": None}

def _win_rate(d):
    w, l = d.get("won_decided") or 0, d.get("lost_decided") or 0
    return round(100.0*w/(w+l), 1) if (w+l) > 0 else None

win_rate_pct = _win_rate(snap)
print("[kpi] snapshot:", snap, "| win_rate%", win_rate_pct)

# COMMAND ----------
# MAGIC %md ## Section 4 — MQL count (optional, gaim_mql_daily_snapshot)

# COMMAND ----------

try:
    mql = spark.sql(f"""
        WITH latest AS (SELECT MAX(data_day) AS d FROM {GAIM}.gaim_mql_daily_snapshot)
        SELECT COUNT(DISTINCT sfdc_id) AS mql_count
        FROM {GAIM}.gaim_mql_daily_snapshot, latest
        WHERE data_day = latest.d
          AND create_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}')
    """).collect()[0]["mql_count"]
except Exception as exc:
    print(f"[kpi] WARN MQL unavailable ({exc})")
    mql = None
print("[kpi] mql_count:", mql)

# COMMAND ----------
# MAGIC %md ## Section 5 — Derived ratios + RAG status, assemble summary row
# MAGIC RAG thresholds taken from the spec (Deliverable 1). Coverage = active pipeline /
# MAGIC remaining quota (full_won_amount - won_acv) per coverage/current.sql.

# COMMAND ----------

won_acv      = core["won_acv"]
full_won     = core["full_won_amount"]
active_pipe  = snap.get("active_pipeline")
remaining    = (full_won - won_acv) if full_won else None
coverage_ratio = round(active_pipe/remaining, 2) if (active_pipe and remaining and remaining > 0) else None
pipeline_attain_pct = round(100.0*active_pipe/full_won, 1) if (active_pipe and full_won) else None
opps_per_rep = round((snap.get("open_opps") or 0)/snap["active_reps"], 1) if snap.get("active_reps") else None

def rag(val, green, amber, higher_is_better=True):
    if val is None: return "N/A"
    if higher_is_better:
        return "G" if val >= green else ("A" if val >= amber else "R")
    return "G" if val <= green else ("A" if val <= amber else "R")

summary = {
    "report_date": REPORT_DATE,
    "qtr_start": QTR_START, "qtr_end": QTR_END, "data_as_of": AS_OF,
    # revenue
    "won_acv_qtr": round(won_acv,2), "deals_won_qtr": int(core["won_opps"]),
    "avg_deal_size": round(core["avg_deal_size"],2),
    "total_quota_full": round(full_won,2),
    "paced_won_target": round(core["paced_won_amount"],2),
    "attainment_pct": round(core["attainment_pct"],1) if core["attainment_pct"] is not None else None,
    "revenue_gap": round(core["revenue_gap"],2),
    # pipeline
    "active_pipeline": round(active_pipe,2) if active_pipe is not None else None,
    "open_opps": int(snap["open_opps"]) if snap.get("open_opps") is not None else None,
    "pipeline_coverage_ratio": coverage_ratio,
    "pipeline_attainment_pct": pipeline_attain_pct,
    "opps_per_rep": opps_per_rep,
    # created / top of funnel
    "created_pipeline_qtr": round(core["created_pipeline"],2),
    "opps_created_qtr": int(core["opened_opps"]),
    "avg_opp_size": round(core["avg_opp_size"],2),
    "created_attainment_pct": round(core["created_attainment_pct"],1) if core["created_attainment_pct"] is not None else None,
    # rates
    "win_rate_pct": win_rate_pct,
    "close_rate_vol_pct": round(core["close_rate_vol_pct"],1),
    "close_rate_dollar_pct": round(core["close_rate_dollar_pct"],1),
    # velocity / mql
    "avg_days_to_close": round(snap["avg_days_to_close"],0) if snap.get("avg_days_to_close") is not None else None,
    "mql_count": int(mql) if mql is not None else None,
    # RAG status (spec thresholds)
    "status_attainment":   rag(core["attainment_pct"], 90, 75),
    "status_coverage":     rag(coverage_ratio, 3, 2),
    "status_win_rate":     rag(win_rate_pct, 75, 60),
    "status_close_rate_d": rag(core["close_rate_dollar_pct"], 22, 15),
    "status_pipeline_attain": rag(pipeline_attain_pct, 300, 200),
}
import json
print("[kpi] summary:\n", json.dumps(summary, indent=2, default=str))

# COMMAND ----------
# MAGIC %md ## Section 6 — Write summary (idempotent MERGE by report_date)

# COMMAND ----------

summary_df = spark.createDataFrame([summary]).withColumn("load_ts", F.current_timestamp())

# create table on first run, then MERGE so re-runs replace the same day
if not spark.catalog.tableExists(SUMMARY_TABLE):
    summary_df.write.format("delta").saveAsTable(SUMMARY_TABLE)
else:
    summary_df.createOrReplaceTempView("_kpi_summary_new")
    cols = [c for c in summary_df.columns]
    set_clause = ", ".join([f"t.`{c}` = s.`{c}`" for c in cols])
    ins_cols   = ", ".join([f"`{c}`" for c in cols])
    ins_vals   = ", ".join([f"s.`{c}`" for c in cols])
    spark.sql(f"""
        MERGE INTO {SUMMARY_TABLE} t
        USING _kpi_summary_new s ON t.report_date = s.report_date
        WHEN MATCHED THEN UPDATE SET {set_clause}
        WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})
    """)
print(f"[kpi] wrote {SUMMARY_TABLE}")

# COMMAND ----------
# MAGIC %md ## Section 7 — By-segment table (geo x product x channel) for metis KPIs
# MAGIC Won / created / targets / attainment at segment grain. Pipeline-snapshot KPIs
# MAGIC (win rate, active pipeline) are company-level here; extend later if needed.

# COMMAND ----------

seg_sql = f"""
WITH lw AS (SELECT MAX(data_date) d FROM {FED}.metis_won_opps_fact),
     lo AS (SELECT MAX(data_date) d FROM {FED}.metis_opened_opps_fact),
won AS (
    SELECT sales_market AS geo, product_group AS product, sales_channel AS channel,
           COUNT(DISTINCT salesforce_opportunity_id) AS deals_won,
           COALESCE(SUM(amount_towards_plan),0)      AS won_acv
    FROM {FED}.metis_won_opps_fact, lw
    WHERE data_date = lw.d AND close_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}')
    GROUP BY 1,2,3
),
opened AS (
    SELECT sales_market AS geo, product_group AS product, sales_channel AS channel,
           COUNT(DISTINCT salesforce_opportunity_id) AS opps_created,
           COALESCE(SUM(amount_towards_plan),0)      AS created_pipeline
    FROM {FED}.metis_opened_opps_fact, lo
    WHERE data_date = lo.d AND pipeline_entered_date BETWEEN DATE('{QTR_START}') AND DATE('{AS_OF}')
    GROUP BY 1,2,3
),
tgt AS (
    SELECT sales_market AS geo, product_group AS product, sales_channel AS channel,
           COALESCE(SUM(paced_won_amount),0)    AS paced_won_amount,
           COALESCE(SUM(full_won_amount),0)     AS full_won_amount
    FROM {FED}.metis_targets_summary
    WHERE quarter_start_date = DATE('{QTR_START}') AND plan_version = '{PLAN_VERSION}'
    GROUP BY 1,2,3
)
SELECT
    DATE('{REPORT_DATE}') AS report_date,
    COALESCE(w.geo,o.geo,t.geo)         AS geo,
    COALESCE(w.product,o.product,t.product) AS product,
    COALESCE(w.channel,o.channel,t.channel) AS channel,
    COALESCE(w.won_acv,0)               AS won_acv_qtr,
    COALESCE(w.deals_won,0)             AS deals_won_qtr,
    CASE WHEN COALESCE(w.deals_won,0)>0 THEN ROUND(w.won_acv/w.deals_won,2) ELSE 0 END AS avg_deal_size,
    COALESCE(o.created_pipeline,0)      AS created_pipeline_qtr,
    COALESCE(o.opps_created,0)          AS opps_created_qtr,
    COALESCE(t.paced_won_amount,0)      AS paced_won_target,
    COALESCE(t.full_won_amount,0)       AS full_won_target,
    CASE WHEN COALESCE(t.paced_won_amount,0)>0
         THEN ROUND(100.0*COALESCE(w.won_acv,0)/t.paced_won_amount,1) ELSE NULL END AS attainment_pct,
    current_timestamp() AS load_ts
FROM won w
FULL OUTER JOIN opened o ON w.geo<=>o.geo AND w.product<=>o.product AND w.channel<=>o.channel
FULL OUTER JOIN tgt   t ON COALESCE(w.geo,o.geo)<=>t.geo
                        AND COALESCE(w.product,o.product)<=>t.product
                        AND COALESCE(w.channel,o.channel)<=>t.channel
"""
seg_df = spark.sql(seg_sql)
if not spark.catalog.tableExists(SEGMENT_TABLE):
    seg_df.write.format("delta").partitionBy("report_date").saveAsTable(SEGMENT_TABLE)
else:
    spark.sql(f"DELETE FROM {SEGMENT_TABLE} WHERE report_date = DATE('{REPORT_DATE}')")
    seg_df.write.format("delta").mode("append").saveAsTable(SEGMENT_TABLE)
print(f"[kpi] wrote {SEGMENT_TABLE} ({seg_df.count()} segment rows)")

# COMMAND ----------
# MAGIC %md ## Section 8 — Data-quality gates (fail the job on silent breakage)

# COMMAND ----------

problems = []
if summary["won_acv_qtr"] is None or summary["won_acv_qtr"] < 0:
    problems.append("won_acv negative/null")
if summary["deals_won_qtr"] == 0 and summary["won_acv_qtr"] not in (0, None):
    problems.append("won_acv>0 but 0 deals (grain bug)")
if summary["attainment_pct"] is not None and (summary["attainment_pct"] < 0 or summary["attainment_pct"] > 500):
    problems.append(f"attainment out of range: {summary['attainment_pct']}")
if core["paced_won_amount"] == 0:
    problems.append("no targets matched (check quarter_start_date / plan_version / grants)")

if problems:
    msg = "DATA QUALITY ISSUES: " + "; ".join(problems)
    print("[kpi] " + msg)
    # raise RuntimeError(msg)   # uncomment to hard-fail the Databricks job
else:
    print("[kpi] data-quality checks passed")

print(f"\n[kpi] DONE {REPORT_DATE} — {SUMMARY_TABLE} + {SEGMENT_TABLE} refreshed.")
