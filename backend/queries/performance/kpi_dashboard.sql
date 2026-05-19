-- queries/performance/kpi_dashboard.sql
-- ============================================================
-- Performance Hub — All 12 KPIs + Paced Targets + Attainment + Status
-- Source tables: federated.sales.metis_*
-- Returns: one row with every KPI actual, paced target, attainment %, and
--          RAG status for the selected period and filter combination.
-- ============================================================
--
-- Structural placeholders (injected by PerformanceHubService — never raw user input):
--   {period_start}    YYYY-MM-DD  first day of reporting period
--   {period_end}      YYYY-MM-DD  last day  of reporting period (≤ latest data_date)
--   {quarter_start}   YYYY-MM-DD  first day of the reporting quarter (for target join)
--   {plan_version}    Plan | FY4 | FY7   (whitelist-validated)
--   {won_filter}      AND-prefixed SQL fragment for metis_won_opps_fact
--   {opened_filter}   AND-prefixed SQL fragment for metis_opened_opps_fact
--   {targets_filter}  AND-prefixed SQL fragment for metis_targets_summary
--
-- Status thresholds:
--   Exceeding Target  ≥ 100 %
--   Watch Closely      85 – 99 %
--   Action Required   < 85 %
-- ============================================================

WITH

latest_date AS (
    -- Use the most-recent loaded snapshot so stale rows are never included.
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),

-- ── Actuals: Won Opportunities ──────────────────────────────────────────────
won_actuals AS (
    SELECT
        COUNT(DISTINCT w.salesforce_opportunity_id)  AS won_opps_count,
        COALESCE(SUM(w.amount_towards_plan), 0)      AS won_amount
    FROM federated.sales.metis_won_opps_fact  w
    CROSS JOIN latest_date  ld
    WHERE w.data_date  = ld.max_date
      AND w.close_date BETWEEN DATE('{period_start}') AND DATE('{period_end}')
      {won_filter}
),

-- ── Actuals: Created / Opened Opportunities ──────────────────────────────────
opened_actuals AS (
    SELECT
        COUNT(DISTINCT o.salesforce_opportunity_id)  AS opened_opps_count,
        COALESCE(SUM(o.amount_towards_plan), 0)      AS opened_amount
    FROM federated.sales.metis_opened_opps_fact  o
    CROSS JOIN latest_date  ld
    WHERE o.data_date            = ld.max_date
      AND o.pipeline_entered_date BETWEEN DATE('{period_start}') AND DATE('{period_end}')
      {opened_filter}
),

-- ── Paced Targets for the Reporting Quarter ──────────────────────────────────
-- paced_* = median-historical-pacing to the current day-of-quarter
-- full_*  = full-quarter board / forecast target
-- For past quarters the service sets period_end = quarter end, so paced ≈ full.
targets_agg AS (
    SELECT
        COALESCE(SUM(paced_won_amount),    0)  AS paced_won_amount,
        COALESCE(SUM(paced_won_opps),      0)  AS paced_won_opps,
        COALESCE(SUM(paced_opened_amount), 0)  AS paced_opened_amount,
        COALESCE(SUM(paced_opened_opps),   0)  AS paced_opened_opps,
        COALESCE(SUM(full_won_amount),     0)  AS full_won_amount,
        COALESCE(SUM(full_won_opps),       0)  AS full_won_opps,
        COALESCE(SUM(full_opened_amount),  0)  AS full_opened_amount,
        COALESCE(SUM(full_opened_opps),    0)  AS full_opened_opps
    FROM federated.sales.metis_targets_summary
    WHERE quarter_start_date = DATE('{quarter_start}')
      AND plan_version        = '{plan_version}'
      {targets_filter}
)

SELECT

    -- ── 1  Won Amount ($) ──────────────────────────────────────────────────
    w.won_amount,
    t.paced_won_amount                                                           AS target_won_amount,
    CASE WHEN t.paced_won_amount > 0
         THEN ROUND(w.won_amount / t.paced_won_amount, 4)    ELSE NULL END      AS won_amount_attainment,
    CASE WHEN t.paced_won_amount = 0                          THEN 'No Target'
         WHEN w.won_amount / t.paced_won_amount >= 1.00       THEN 'Exceeding Target'
         WHEN w.won_amount / t.paced_won_amount >= 0.85       THEN 'Watch Closely'
         ELSE 'Action Required'                               END               AS won_amount_status,

    -- ── 2  # Deals Won ────────────────────────────────────────────────────
    w.won_opps_count,
    t.paced_won_opps                                                             AS target_won_opps,
    CASE WHEN t.paced_won_opps > 0
         THEN ROUND(w.won_opps_count / t.paced_won_opps, 4)  ELSE NULL END      AS won_opps_attainment,
    CASE WHEN t.paced_won_opps = 0                            THEN 'No Target'
         WHEN w.won_opps_count / t.paced_won_opps >= 1.00    THEN 'Exceeding Target'
         WHEN w.won_opps_count / t.paced_won_opps >= 0.85    THEN 'Watch Closely'
         ELSE 'Action Required'                               END               AS won_opps_status,

    -- ── 3  ADS (Average Deal Size) = Won Amount ÷ # Deals Won ─────────────
    CASE WHEN w.won_opps_count > 0
         THEN ROUND(w.won_amount / w.won_opps_count, 2)       ELSE 0 END        AS avg_deal_size,
    CASE WHEN t.paced_won_opps > 0
         THEN ROUND(t.paced_won_amount / t.paced_won_opps, 2) ELSE 0 END        AS target_avg_deal_size,

    -- ── 4  # Opps Created ─────────────────────────────────────────────────
    o.opened_opps_count,
    t.paced_opened_opps                                                          AS target_opened_opps,
    CASE WHEN t.paced_opened_opps > 0
         THEN ROUND(o.opened_opps_count / t.paced_opened_opps, 4) ELSE NULL END AS opened_opps_attainment,
    CASE WHEN t.paced_opened_opps = 0                             THEN 'No Target'
         WHEN o.opened_opps_count / t.paced_opened_opps >= 1.00  THEN 'Exceeding Target'
         WHEN o.opened_opps_count / t.paced_opened_opps >= 0.85  THEN 'Watch Closely'
         ELSE 'Action Required'                                   END           AS opened_opps_status,

    -- ── 5  Created Pipeline ($) ───────────────────────────────────────────
    o.opened_amount                                                              AS pipeline_amount,
    t.paced_opened_amount                                                        AS target_pipeline_amount,
    CASE WHEN t.paced_opened_amount > 0
         THEN ROUND(o.opened_amount / t.paced_opened_amount, 4) ELSE NULL END   AS pipeline_attainment,
    CASE WHEN t.paced_opened_amount = 0                           THEN 'No Target'
         WHEN o.opened_amount / t.paced_opened_amount >= 1.00    THEN 'Exceeding Target'
         WHEN o.opened_amount / t.paced_opened_amount >= 0.85    THEN 'Watch Closely'
         ELSE 'Action Required'                                   END           AS pipeline_status,

    -- ── 6  Average Opp Size (AOS) = Pipeline $ ÷ # Opps Created ──────────
    CASE WHEN o.opened_opps_count > 0
         THEN ROUND(o.opened_amount / o.opened_opps_count, 2)     ELSE 0 END   AS avg_opp_size,
    CASE WHEN t.paced_opened_opps > 0
         THEN ROUND(t.paced_opened_amount / t.paced_opened_opps, 2) ELSE 0 END AS target_avg_opp_size,

    -- ── 7  Close Rate (Volume) = # Deals Won ÷ # Opps Created ────────────
    CASE WHEN o.opened_opps_count > 0
         THEN ROUND(w.won_opps_count * 1.0 / o.opened_opps_count, 4) ELSE 0 END AS close_rate_opps,
    CASE WHEN t.paced_opened_opps > 0
         THEN ROUND(t.paced_won_opps / t.paced_opened_opps, 4)     ELSE 0 END  AS target_close_rate_opps,

    -- ── 8  Close Rate ($) = Won Amount ÷ Pipeline $ ───────────────────────
    CASE WHEN o.opened_amount > 0
         THEN ROUND(w.won_amount / o.opened_amount, 4)              ELSE 0 END  AS close_rate_dollar,
    CASE WHEN t.paced_opened_amount > 0
         THEN ROUND(t.paced_won_amount / t.paced_opened_amount, 4)  ELSE 0 END  AS target_close_rate_dollar,

    -- ── 9  Coverage = Created Pipeline $ ÷ Paced Won Amount Target ────────
    -- Note: "open pipeline" at this grain is represented by created pipeline.
    -- Coverage > 1.0x means pipeline is sufficient to hit paced target.
    CASE WHEN t.paced_won_amount > 0
         THEN ROUND(o.opened_amount / t.paced_won_amount, 4)        ELSE NULL END AS coverage_ratio,
    CASE WHEN t.paced_won_amount = 0                                  THEN 'No Target'
         WHEN o.opened_amount / t.paced_won_amount >= 1.00           THEN 'Exceeding Target'
         WHEN o.opened_amount / t.paced_won_amount >= 0.85           THEN 'Watch Closely'
         ELSE 'Action Required'                                       END         AS coverage_status,

    -- ── 10  Won Amount Attainment % (alias — already computed above) ──────
    -- Exposed again here for explicit card labelling.
    CASE WHEN t.paced_won_amount > 0
         THEN ROUND(w.won_amount / t.paced_won_amount * 100, 1) ELSE NULL END   AS won_amount_attainment_pct,

    -- ── 11  Pipeline Attainment % ─────────────────────────────────────────
    CASE WHEN t.paced_opened_amount > 0
         THEN ROUND(o.opened_amount / t.paced_opened_amount * 100, 1) ELSE NULL END AS pipeline_attainment_pct,

    -- ── 12  MQL Count ─────────────────────────────────────────────────────
    -- Not available in metis_* tables — sourced separately via /api/kpis (mql.sql).
    CAST(NULL AS BIGINT)                                                         AS mql_count,
    CAST(NULL AS DECIMAL(38,2))                                                  AS target_mql_count,

    -- ── Full-quarter targets (for % complete / remaining gap context) ─────
    t.full_won_amount,
    t.full_won_opps,
    t.full_opened_amount,
    t.full_opened_opps,

    -- ── Data freshness ────────────────────────────────────────────────────
    ld.max_date                                                                  AS data_as_of

FROM won_actuals   w
CROSS JOIN opened_actuals  o
CROSS JOIN targets_agg     t
CROSS JOIN latest_date     ld
