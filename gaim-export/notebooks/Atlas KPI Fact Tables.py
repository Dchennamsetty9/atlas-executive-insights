# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Config
# Atlas KPI Fact Tables — GoTo Sales Operations
# ═══════════════════════════════════════════════
# Creates 6 production KPI tables in datagroup_mdl.mdl_sales_analytics:
#
#   atlas_kpi_fact_won           — Closed Won deals (24-month history)
#   atlas_kpi_fact_pipeline      — Active open opportunities (current snapshot)
#   atlas_kpi_fact_lost          — Closed Lost deals (12-month history)
#   atlas_kpi_daily_summary      — Company-wide KPIs (one row per day)
#   atlas_kpi_daily_by_rep       — Rep-level KPIs
#   atlas_kpi_daily_by_territory — Territory rollup
#
# Sources:
#   federated.sales.metis_won_opps_fact
#   federated.sales.metis_opened_opps_fact
#   federated.sales.metis_targets_summary
#   datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
#
# Atlas SP access granted at end of notebook (SP 324a6ec7)
print("Atlas KPI Fact Tables — starting build")
print(f"Run date: {spark.sql('SELECT CURRENT_DATE()').collect()[0][0]}")

# COMMAND ----------

# DBTITLE 1,Table 1 — atlas_kpi_fact_won
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- TABLE 1: atlas_kpi_fact_won
# MAGIC -- Source: federated.sales.metis_won_opps_fact
# MAGIC -- Coverage: 24 months of Closed Won deals
# MAGIC -- Grain: one row per opportunity x product_genus
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_won
# MAGIC USING DELTA
# MAGIC TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
# MAGIC AS
# MAGIC SELECT
# MAGIC   salesforce_opportunity_id                                          AS opp_id,
# MAGIC   opportunity_name,
# MAGIC   sales_market                                                       AS geo,
# MAGIC   sales_channel,
# MAGIC   product_family,
# MAGIC   product_group,
# MAGIC   product_major,
# MAGIC   product_genus,
# MAGIC   business_unit,
# MAGIC   fuel_source,
# MAGIC   ROUND(COALESCE(CAST(amount_towards_plan AS DOUBLE), 0), 2)        AS acv,
# MAGIC   close_date,
# MAGIC   YEAR(close_date)                                                   AS year,
# MAGIC   QUARTER(close_date)                                                AS quarter,
# MAGIC   MONTH(close_date)                                                  AS month,
# MAGIC   DATE_TRUNC('quarter', close_date)                                  AS quarter_start,
# MAGIC   data_date,
# MAGIC   CURRENT_TIMESTAMP()                                                AS load_timestamp
# MAGIC FROM federated.sales.metis_won_opps_fact
# MAGIC WHERE close_date >= DATE_SUB(CURRENT_DATE(), 730)  -- 24 months
# MAGIC   AND COALESCE(CAST(amount_towards_plan AS DOUBLE), 0) >= 0;
# MAGIC
# MAGIC SELECT 'atlas_kpi_fact_won' AS table_name, COUNT(*) AS row_count,
# MAGIC        ROUND(SUM(acv)/1e6, 2) AS total_acv_m,
# MAGIC        MIN(close_date) AS earliest_close, MAX(close_date) AS latest_close
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_won

# COMMAND ----------

# DBTITLE 1,Table 2 — atlas_kpi_fact_pipeline
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- TABLE 2: atlas_kpi_fact_pipeline
# MAGIC -- Source: gaim_pipeline_daily_snapshot (latest snapshot only)
# MAGIC -- Coverage: Active open deals with future close dates
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_pipeline
# MAGIC USING DELTA
# MAGIC TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
# MAGIC AS
# MAGIC WITH latest AS (
# MAGIC   SELECT MAX(data_day) AS max_day
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
# MAGIC )
# MAGIC SELECT
# MAGIC   COALESCE(opportunities_created_ids, opportunity)                   AS opp_id,
# MAGIC   opportunity                                                        AS opportunity_name,
# MAGIC   owner                                                              AS rep_name,
# MAGIC   market                                                             AS geo,
# MAGIC   sales_channel,
# MAGIC   product_family,
# MAGIC   product_group,
# MAGIC   stage_name,
# MAGIC   stage_group,
# MAGIC   ROUND(COALESCE(amount_towards_plan, 0), 2)                        AS acv,
# MAGIC   close_date,
# MAGIC   pipeline_entered_date,
# MAGIC   COALESCE(opportunity_age, 0)                                       AS age_days,
# MAGIC   data_day                                                           AS snapshot_day,
# MAGIC   CURRENT_TIMESTAMP()                                                AS load_timestamp
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot g
# MAGIC CROSS JOIN latest l
# MAGIC WHERE g.data_day = l.max_day
# MAGIC   AND LOWER(COALESCE(is_won,  '')) != 'true'   -- exclude closed won
# MAGIC   AND (lost_code IS NULL OR lost_code = '')     -- exclude closed lost
# MAGIC   AND (close_date IS NULL OR close_date >= CURRENT_DATE())
# MAGIC   AND COALESCE(amount_towards_plan, 0) > 0;
# MAGIC
# MAGIC SELECT 'atlas_kpi_fact_pipeline' AS table_name, COUNT(*) AS row_count,
# MAGIC        ROUND(SUM(acv)/1e6, 2) AS total_pipeline_m,
# MAGIC        COUNT(DISTINCT rep_name) AS rep_count, MAX(snapshot_day) AS snapshot
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_pipeline

# COMMAND ----------

# DBTITLE 1,Table 3 — atlas_kpi_fact_lost
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- TABLE 3: atlas_kpi_fact_lost
# MAGIC -- Source: gaim_pipeline_daily_snapshot (latest snapshot)
# MAGIC -- Coverage: Closed Lost deals from last 12 months
# MAGIC -- Powers revenue gap decomposition and win-rate calculation
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_lost
# MAGIC USING DELTA
# MAGIC TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
# MAGIC AS
# MAGIC WITH latest AS (
# MAGIC   SELECT MAX(data_day) AS max_day
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
# MAGIC )
# MAGIC SELECT
# MAGIC   COALESCE(opportunities_created_ids, opportunity)                   AS opp_id,
# MAGIC   opportunity                                                        AS opportunity_name,
# MAGIC   owner                                                              AS rep_name,
# MAGIC   market                                                             AS geo,
# MAGIC   sales_channel,
# MAGIC   product_family,
# MAGIC   product_group,
# MAGIC   ROUND(COALESCE(amount_towards_plan, 0), 2)                        AS acv,
# MAGIC   close_date,
# MAGIC   YEAR(close_date)                                                   AS year,
# MAGIC   QUARTER(close_date)                                                AS quarter,
# MAGIC   COALESCE(lost_code, 'Not Captured')                                AS loss_reason,
# MAGIC   data_day                                                           AS snapshot_day,
# MAGIC   CURRENT_TIMESTAMP()                                                AS load_timestamp
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot g
# MAGIC CROSS JOIN latest l
# MAGIC WHERE g.data_day = l.max_day
# MAGIC   AND lost_code IS NOT NULL AND lost_code != ''
# MAGIC   AND close_date >= DATE_SUB(CURRENT_DATE(), 365);
# MAGIC
# MAGIC SELECT 'atlas_kpi_fact_lost' AS table_name, COUNT(*) AS row_count,
# MAGIC        ROUND(SUM(acv)/1e6, 2) AS total_lost_m,
# MAGIC        COUNT(DISTINCT loss_reason) AS distinct_reasons
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_lost

# COMMAND ----------

# DBTITLE 1,Table 4 — atlas_kpi_daily_summary
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- TABLE 4: atlas_kpi_daily_summary
# MAGIC -- One row per report_date — all 15 company-wide KPIs
# MAGIC -- Quota from: metis_targets_summary (paced targets)
# MAGIC -- Created pipeline from: metis_opened_opps_fact
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_summary
# MAGIC USING DELTA
# MAGIC AS
# MAGIC WITH qtr AS (
# MAGIC   SELECT
# MAGIC     DATE_TRUNC('quarter', CURRENT_DATE())                            AS qtr_start,
# MAGIC     LAST_DAY(ADD_MONTHS(DATE_TRUNC('quarter', CURRENT_DATE()), 2))  AS qtr_end
# MAGIC ),
# MAGIC won AS (
# MAGIC   SELECT
# MAGIC     COALESCE(SUM(acv), 0)        AS won_acv_qtr,
# MAGIC     COUNT(DISTINCT opp_id)       AS deals_won_qtr
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_won w
# MAGIC   CROSS JOIN qtr q
# MAGIC   WHERE w.close_date BETWEEN q.qtr_start AND CURRENT_DATE()
# MAGIC ),
# MAGIC pipeline AS (
# MAGIC   SELECT
# MAGIC     COALESCE(SUM(acv), 0)        AS pipeline_acv,
# MAGIC     COUNT(DISTINCT opp_id)       AS pipeline_opps
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_pipeline
# MAGIC ),
# MAGIC lost AS (
# MAGIC   SELECT
# MAGIC     COALESCE(SUM(acv), 0)        AS lost_acv_qtr,
# MAGIC     COUNT(DISTINCT opp_id)       AS deals_lost_qtr
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_lost l
# MAGIC   CROSS JOIN qtr q
# MAGIC   WHERE l.close_date BETWEEN q.qtr_start AND CURRENT_DATE()
# MAGIC ),
# MAGIC created AS (
# MAGIC   SELECT
# MAGIC     COALESCE(SUM(CAST(amount_towards_plan AS DOUBLE)), 0)  AS created_pipeline_qtr,
# MAGIC     COUNT(DISTINCT salesforce_opportunity_id)              AS opps_created_qtr,
# MAGIC     COUNT(DISTINCT CASE WHEN fuel_source = 'Marketing' THEN salesforce_opportunity_id END) AS mql_count
# MAGIC   FROM federated.sales.metis_opened_opps_fact oo
# MAGIC   CROSS JOIN qtr q
# MAGIC   WHERE oo.pipeline_entered_date BETWEEN q.qtr_start AND CURRENT_DATE()
# MAGIC ),
# MAGIC quota AS (
# MAGIC   SELECT
# MAGIC     COALESCE(SUM(paced_won_amount),    0)  AS paced_quota,
# MAGIC     COALESCE(SUM(full_won_amount),     0)  AS full_quota,
# MAGIC     COALESCE(SUM(paced_opened_amount), 0)  AS paced_pipeline_target
# MAGIC   FROM federated.sales.metis_targets_summary t
# MAGIC   CROSS JOIN qtr q
# MAGIC   WHERE t.quarter_start_date = q.qtr_start
# MAGIC     AND t.plan_version = 'Plan'  -- Board/Plan version only, excludes FY duplicate rows
# MAGIC ),
# MAGIC velocity AS (
# MAGIC   SELECT AVG(opportunity_age) AS avg_days_to_close
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot g
# MAGIC   CROSS JOIN (SELECT MAX(data_day) AS max_day
# MAGIC               FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot) l
# MAGIC   CROSS JOIN qtr q
# MAGIC   WHERE g.data_day = l.max_day
# MAGIC     AND LOWER(COALESCE(is_won, '')) = 'true'
# MAGIC     AND g.close_date BETWEEN q.qtr_start AND CURRENT_DATE()
# MAGIC )
# MAGIC SELECT
# MAGIC   CURRENT_DATE()                                                     AS report_date,
# MAGIC   q.qtr_start,
# MAGIC   q.qtr_end,
# MAGIC   -- Revenue
# MAGIC   w.won_acv_qtr,
# MAGIC   w.deals_won_qtr,
# MAGIC   ROUND(w.won_acv_qtr / NULLIF(w.deals_won_qtr, 0), 2)             AS avg_deal_size,
# MAGIC   qt.paced_quota                                                     AS total_quota,
# MAGIC   qt.full_quota,
# MAGIC   ROUND(100.0 * w.won_acv_qtr / NULLIF(qt.paced_quota, 0), 1)      AS attainment_pct,
# MAGIC   ROUND(qt.paced_quota - w.won_acv_qtr, 2)                          AS revenue_gap,
# MAGIC   -- Pipeline (active = created QTD minus already won; matches ACTIVE PIPELINE $ card in app)
# MAGIC   ROUND(cr.created_pipeline_qtr - w.won_acv_qtr, 2)                 AS pipeline_acv,
# MAGIC   p.pipeline_opps,
# MAGIC   ROUND((cr.created_pipeline_qtr - w.won_acv_qtr) / NULLIF(qt.paced_quota, 0), 2) AS pipeline_coverage_ratio,
# MAGIC   ROUND(100.0 * cr.created_pipeline_qtr / NULLIF(qt.paced_pipeline_target, 0), 1)    AS pipeline_attainment_pct,
# MAGIC   -- Created
# MAGIC   cr.created_pipeline_qtr,
# MAGIC   cr.opps_created_qtr,
# MAGIC   -- Rates
# MAGIC   ROUND(100.0 * w.deals_won_qtr /
# MAGIC     NULLIF(w.deals_won_qtr + l.deals_lost_qtr, 0), 1)               AS win_rate_pct,
# MAGIC   ROUND(100.0 * w.won_acv_qtr /
# MAGIC     NULLIF(cr.created_pipeline_qtr, 0), 1)                          AS close_rate_dollar_pct,
# MAGIC   ROUND(100.0 * w.deals_won_qtr /
# MAGIC     NULLIF(cr.opps_created_qtr, 0), 1)                              AS close_rate_vol_pct,
# MAGIC   -- Gap components
# MAGIC   ROUND(l.lost_acv_qtr * -1, 2)                                     AS lost_volume_impact,
# MAGIC   ROUND(qt.paced_quota - cr.created_pipeline_qtr, 2)                 AS pipeline_gap,
# MAGIC   -- Velocity
# MAGIC   ROUND(COALESCE(v.avg_days_to_close, 0), 1)                        AS avg_days_to_close,
# MAGIC   -- Derived
# MAGIC   ROUND(p.pipeline_acv / NULLIF(p.pipeline_opps, 0), 2)             AS avg_opp_size,
# MAGIC   COALESCE(cr.mql_count, 0)                                          AS mql_count,
# MAGIC   CURRENT_TIMESTAMP()                                                AS load_timestamp
# MAGIC FROM won w
# MAGIC CROSS JOIN pipeline p
# MAGIC CROSS JOIN lost l
# MAGIC CROSS JOIN quota qt
# MAGIC CROSS JOIN created cr
# MAGIC CROSS JOIN velocity v
# MAGIC CROSS JOIN qtr q;
# MAGIC
# MAGIC SELECT * FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_summary

# COMMAND ----------

# DBTITLE 1,Table 5 — atlas_kpi_daily_by_rep
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- TABLE 5: atlas_kpi_daily_by_rep
# MAGIC -- Rep-level KPIs from gaim_pipeline_daily_snapshot (owner column)
# MAGIC -- Partitioned by report_date for daily incremental load
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_rep
# MAGIC USING DELTA
# MAGIC PARTITIONED BY (report_date)
# MAGIC AS
# MAGIC WITH qtr AS (
# MAGIC   SELECT DATE_TRUNC('quarter', CURRENT_DATE()) AS qtr_start
# MAGIC ),
# MAGIC latest AS (
# MAGIC   SELECT MAX(data_day) AS max_day
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
# MAGIC ),
# MAGIC snap AS (
# MAGIC   SELECT * FROM datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot g
# MAGIC   CROSS JOIN latest l WHERE g.data_day = l.max_day
# MAGIC ),
# MAGIC won_by_rep AS (
# MAGIC   SELECT
# MAGIC     owner                                                            AS rep_name,
# MAGIC     market                                                           AS territory,
# MAGIC     COALESCE(SUM(amount_towards_plan), 0)                           AS won_acv_qtr,
# MAGIC     COUNT(DISTINCT COALESCE(opportunities_created_ids, opportunity)) AS deals_won_qtr
# MAGIC   FROM snap CROSS JOIN qtr q
# MAGIC   WHERE LOWER(COALESCE(is_won, '')) = 'true'
# MAGIC     AND close_date BETWEEN q.qtr_start AND CURRENT_DATE()
# MAGIC   GROUP BY owner, market
# MAGIC ),
# MAGIC pipe_by_rep AS (
# MAGIC   SELECT
# MAGIC     owner                                                            AS rep_name,
# MAGIC     COALESCE(SUM(amount_towards_plan), 0)                           AS pipeline_acv,
# MAGIC     COUNT(DISTINCT COALESCE(opportunities_created_ids, opportunity)) AS pipeline_opps
# MAGIC   FROM snap
# MAGIC   WHERE LOWER(COALESCE(is_won, '')) != 'true'
# MAGIC     AND (lost_code IS NULL OR lost_code = '')
# MAGIC     AND (close_date IS NULL OR close_date >= CURRENT_DATE())
# MAGIC     AND COALESCE(amount_towards_plan, 0) > 0
# MAGIC   GROUP BY owner
# MAGIC ),
# MAGIC lost_by_rep AS (
# MAGIC   SELECT
# MAGIC     owner                                                            AS rep_name,
# MAGIC     COUNT(DISTINCT COALESCE(opportunities_created_ids, opportunity)) AS deals_lost_qtr
# MAGIC   FROM snap CROSS JOIN qtr q
# MAGIC   WHERE lost_code IS NOT NULL AND lost_code != ''
# MAGIC     AND close_date BETWEEN q.qtr_start AND CURRENT_DATE()
# MAGIC   GROUP BY owner
# MAGIC )
# MAGIC SELECT
# MAGIC   CURRENT_DATE()                                                     AS report_date,
# MAGIC   w.rep_name,
# MAGIC   w.territory,
# MAGIC   w.won_acv_qtr,
# MAGIC   w.deals_won_qtr,
# MAGIC   ROUND(w.won_acv_qtr / NULLIF(w.deals_won_qtr, 0), 2)             AS avg_deal_size,
# MAGIC   COALESCE(p.pipeline_acv,  0)                                      AS pipeline_acv,
# MAGIC   COALESCE(p.pipeline_opps, 0)                                      AS pipeline_opps,
# MAGIC   ROUND(100.0 * w.deals_won_qtr /
# MAGIC     NULLIF(w.deals_won_qtr + COALESCE(l.deals_lost_qtr, 0), 0), 1) AS win_rate_pct,
# MAGIC   CASE
# MAGIC     WHEN w.won_acv_qtr > 0 AND COALESCE(p.pipeline_acv, 0) > w.won_acv_qtr THEN 'G'
# MAGIC     WHEN w.won_acv_qtr > 0 THEN 'A'
# MAGIC     ELSE 'R'
# MAGIC   END                                                                AS status_indicator,
# MAGIC   CURRENT_TIMESTAMP()                                                AS load_timestamp
# MAGIC FROM won_by_rep w
# MAGIC LEFT JOIN pipe_by_rep p ON w.rep_name = p.rep_name
# MAGIC LEFT JOIN lost_by_rep l ON w.rep_name = l.rep_name;
# MAGIC
# MAGIC SELECT 'atlas_kpi_daily_by_rep' AS tbl, COUNT(*) AS rows,
# MAGIC        COUNT(DISTINCT rep_name) AS reps, COUNT(DISTINCT territory) AS territories
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_rep

# COMMAND ----------

# DBTITLE 1,Table 6 — atlas_kpi_daily_by_territory
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- TABLE 6: atlas_kpi_daily_by_territory
# MAGIC -- Territory rollup from kpi_daily_by_rep + quota targets
# MAGIC -- Used for Territory Comparison view in Atlas
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC CREATE OR REPLACE TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_territory
# MAGIC USING DELTA
# MAGIC PARTITIONED BY (report_date)
# MAGIC AS
# MAGIC WITH quota_by_territory AS (
# MAGIC   SELECT
# MAGIC     sales_market                                                     AS territory,
# MAGIC     COALESCE(SUM(paced_won_amount), 0)                              AS paced_quota,
# MAGIC     COALESCE(SUM(full_won_amount),  0)                              AS full_quota
# MAGIC   FROM federated.sales.metis_targets_summary
# MAGIC   WHERE quarter_start_date = DATE_TRUNC('quarter', CURRENT_DATE())
# MAGIC   GROUP BY sales_market
# MAGIC )
# MAGIC SELECT
# MAGIC   CURRENT_DATE()                                                     AS report_date,
# MAGIC   r.territory,
# MAGIC   COUNT(DISTINCT r.rep_name)                                        AS rep_count,
# MAGIC   COALESCE(SUM(r.won_acv_qtr),   0)                                AS won_acv_qtr,
# MAGIC   COALESCE(SUM(r.deals_won_qtr), 0)                                AS deals_won_qtr,
# MAGIC   ROUND(COALESCE(SUM(r.won_acv_qtr), 0) /
# MAGIC     NULLIF(COALESCE(SUM(r.deals_won_qtr), 0), 0), 2)               AS avg_deal_size,
# MAGIC   COALESCE(qt.paced_quota, 0)                                       AS territory_quota,
# MAGIC   ROUND(100.0 * COALESCE(SUM(r.won_acv_qtr), 0) /
# MAGIC     NULLIF(COALESCE(qt.paced_quota, 0), 0), 1)                     AS attainment_pct,
# MAGIC   COALESCE(SUM(r.pipeline_acv), 0)                                  AS pipeline_acv,
# MAGIC   ROUND(COALESCE(SUM(r.pipeline_acv), 0) /
# MAGIC     NULLIF(COALESCE(qt.paced_quota, 0), 0), 2)                     AS coverage_ratio,
# MAGIC   CURRENT_TIMESTAMP()                                                AS load_timestamp
# MAGIC FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_rep r
# MAGIC LEFT JOIN quota_by_territory qt ON r.territory = qt.territory
# MAGIC WHERE r.report_date = CURRENT_DATE()
# MAGIC GROUP BY r.territory, qt.paced_quota;
# MAGIC
# MAGIC SELECT * FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_territory
# MAGIC ORDER BY won_acv_qtr DESC

# COMMAND ----------

# DBTITLE 1,Data Quality Checks
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- DATA QUALITY — Row counts, totals, freshness
# MAGIC -- Run after full notebook execution to verify
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC SELECT tbl, row_count, note FROM (
# MAGIC   SELECT 1 AS s, 'atlas_kpi_fact_won' AS tbl, COUNT(*) AS row_count,
# MAGIC          CONCAT('ACV=',ROUND(SUM(acv)/1e6,1),'M | ',MIN(close_date),' to ',MAX(close_date)) AS note
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_won
# MAGIC   UNION ALL
# MAGIC   SELECT 2, 'atlas_kpi_fact_pipeline', COUNT(*),
# MAGIC          CONCAT('Pipeline=',ROUND(SUM(acv)/1e6,1),'M | ',COUNT(DISTINCT rep_name),' reps | snap=',MAX(snapshot_day))
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_pipeline
# MAGIC   UNION ALL
# MAGIC   SELECT 3, 'atlas_kpi_fact_lost', COUNT(*),
# MAGIC          CONCAT('Lost=',ROUND(SUM(acv)/1e6,1),'M | ',COUNT(DISTINCT loss_reason),' reasons')
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_lost
# MAGIC   UNION ALL
# MAGIC   SELECT 4, 'atlas_kpi_daily_summary', COUNT(*),
# MAGIC          CONCAT('Won=',ROUND(MAX(won_acv_qtr)/1e6,1),'M | Att=',MAX(attainment_pct),'% | Cov=',MAX(pipeline_coverage_ratio),'x | Win=',MAX(win_rate_pct),'%')
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_summary
# MAGIC   UNION ALL
# MAGIC   SELECT 5, 'atlas_kpi_daily_by_rep', COUNT(*),
# MAGIC          CONCAT(COUNT(DISTINCT rep_name),' reps | ',COUNT(DISTINCT territory),' territories')
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_rep
# MAGIC   UNION ALL
# MAGIC   SELECT 6, 'atlas_kpi_daily_by_territory', COUNT(*),
# MAGIC          CONCAT(COUNT(DISTINCT territory),' territories')
# MAGIC   FROM datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_territory
# MAGIC ) ORDER BY s

# COMMAND ----------

# DBTITLE 1,GRANT — Atlas Executive Insights SP access
# MAGIC %sql
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC -- GRANT READ access to atlas-executive-insights service principal
# MAGIC -- App: atlas-executive-insights | SP Client ID: 324a6ec7-e988-42c7-8a7f-55465f5bea37
# MAGIC -- ═══════════════════════════════════════════════
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_won           TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_pipeline      TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_fact_lost          TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_summary      TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_rep       TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_kpi_daily_by_territory TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# MAGIC -- forecast_prophet: SELECT granted by Sona.Manukyan@goto.com (table owner) — confirmed 2026-06-24
# MAGIC -- GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.forecast_prophet TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`

# COMMAND ----------

# DBTITLE 1,Check SP grants on forecast_prophet
display(spark.sql("SHOW GRANTS ON TABLE federated.sales.metis_won_opps_fact"))

# COMMAND ----------

# DBTITLE 1,GRANT — atlas_insights_cache SP access
# MAGIC %sql
# MAGIC GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_insights_cache
# MAGIC   TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;


