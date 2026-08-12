-- queries/performance/mom_comparison.sql
-- ============================================================
-- Month-over-Month Fair Comparison
-- Uses is_in_mom_period = true to compare equivalent days in each month.
-- Structurally identical to qoq_comparison.sql but at monthly grain.
-- ============================================================
--
-- Structural placeholders:
--   {current_month_start}    YYYY-MM-DD  first day of current month
--   {prior_month_start}      YYYY-MM-DD  first day of prior month
--   {current_quarter_start}  YYYY-MM-DD  for target lookup (paced)
--   {prior_quarter_start}    YYYY-MM-DD  for prior-month target lookup
--   {plan_version}           Plan | FY4 | FY7
--   {won_filter}, {opened_filter}, {targets_filter}
-- ============================================================

WITH

latest_date AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),

-- Current month — equivalent-day window via is_in_mom_period
cm_won AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS won_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS won_amount
    FROM federated.sales.metis_won_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date        = ld.max_date
      AND is_in_mom_period = TRUE
      AND close_date       >= DATE('{current_month_start}')
      {won_filter}
),

cm_opened AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS opened_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS opened_amount
    FROM federated.sales.metis_opened_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date              = ld.max_date
      AND is_in_mom_period       = TRUE
      AND pipeline_entered_date  >= DATE('{current_month_start}')
      {opened_filter}
),

-- Prior month — same equivalent-day flag
pm_won AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS won_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS won_amount
    FROM federated.sales.metis_won_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date        = ld.max_date
      AND is_in_mom_period = TRUE
      AND close_date        BETWEEN DATE('{prior_month_start}')
                                AND DATE_ADD(DATE('{current_month_start}'), -1)
      {won_filter}
),

pm_opened AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS opened_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS opened_amount
    FROM federated.sales.metis_opened_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date             = ld.max_date
      AND is_in_mom_period      = TRUE
      AND pipeline_entered_date  BETWEEN DATE('{prior_month_start}')
                                    AND DATE_ADD(DATE('{current_month_start}'), -1)
      {opened_filter}
),

-- Targets: paced for current quarter, full for prior quarter
cq_targets AS (
    SELECT
        COALESCE(SUM(paced_won_amount),    0)  AS paced_won_amount,
        COALESCE(SUM(paced_opened_amount), 0)  AS paced_opened_amount
    FROM federated.sales.metis_targets_summary
    WHERE quarter_start_date = DATE('{current_quarter_start}')
      AND plan_version        = '{plan_version}'
      {targets_filter}
),

pq_targets AS (
    SELECT
        COALESCE(SUM(full_won_amount),     0)  AS paced_won_amount,
        COALESCE(SUM(full_opened_amount),  0)  AS paced_opened_amount
    FROM federated.sales.metis_targets_summary
    WHERE quarter_start_date = DATE('{prior_quarter_start}')
      AND plan_version        = '{plan_version}'
      {targets_filter}
)

SELECT
    -- ── Current Month ────────────────────────────────────────────────────────
    cmw.won_amount                                                               AS cm_won_amount,
    cmw.won_opps                                                                 AS cm_won_opps,
    cmo.opened_amount                                                            AS cm_pipeline,
    cmo.opened_opps                                                              AS cm_opened_opps,
    CASE WHEN cmw.won_opps   > 0 THEN ROUND(cmw.won_amount / cmw.won_opps, 2)     ELSE 0 END AS cm_ads,
    CASE WHEN cmo.opened_opps > 0 THEN ROUND(cmo.opened_amount / cmo.opened_opps, 2) ELSE 0 END AS cm_aos,
    CASE WHEN cmo.opened_opps > 0 THEN ROUND(cmw.won_opps * 1.0 / cmo.opened_opps, 4) ELSE 0 END AS cm_close_rate_opps,
    CASE WHEN cmo.opened_amount > 0 THEN ROUND(cmw.won_amount / cmo.opened_amount, 4) ELSE 0 END AS cm_close_rate_dollar,

    -- ── Prior Month (equivalent days) ────────────────────────────────────────
    pmw.won_amount                                                               AS pm_won_amount,
    pmw.won_opps                                                                 AS pm_won_opps,
    pmo.opened_amount                                                            AS pm_pipeline,
    pmo.opened_opps                                                              AS pm_opened_opps,
    CASE WHEN pmw.won_opps   > 0 THEN ROUND(pmw.won_amount / pmw.won_opps, 2)     ELSE 0 END AS pm_ads,
    CASE WHEN pmo.opened_opps > 0 THEN ROUND(pmo.opened_amount / pmo.opened_opps, 2) ELSE 0 END AS pm_aos,
    CASE WHEN pmo.opened_opps > 0 THEN ROUND(pmw.won_opps * 1.0 / pmo.opened_opps, 4) ELSE 0 END AS pm_close_rate_opps,
    CASE WHEN pmo.opened_amount > 0 THEN ROUND(pmw.won_amount / pmo.opened_amount, 4) ELSE 0 END AS pm_close_rate_dollar,

    -- ── MoM Change (absolute) ────────────────────────────────────────────────
    ROUND(cmw.won_amount  - pmw.won_amount,  2)                                  AS delta_won_amount,
    ROUND(cmw.won_opps    - pmw.won_opps,    0)                                  AS delta_won_opps,
    ROUND(cmo.opened_amount - pmo.opened_amount, 2)                              AS delta_pipeline,
    ROUND(cmo.opened_opps   - pmo.opened_opps,   0)                              AS delta_opened_opps,

    -- ── MoM Change (%) ───────────────────────────────────────────────────────
    CASE WHEN pmw.won_amount    > 0 THEN ROUND((cmw.won_amount    - pmw.won_amount)    / pmw.won_amount    * 100, 1) ELSE NULL END AS pct_change_won_amount,
    CASE WHEN pmw.won_opps      > 0 THEN ROUND((cmw.won_opps      - pmw.won_opps)      / pmw.won_opps      * 100, 1) ELSE NULL END AS pct_change_won_opps,
    CASE WHEN pmo.opened_amount > 0 THEN ROUND((cmo.opened_amount - pmo.opened_amount) / pmo.opened_amount * 100, 1) ELSE NULL END AS pct_change_pipeline,
    CASE WHEN pmo.opened_opps   > 0 THEN ROUND((cmo.opened_opps   - pmo.opened_opps)   / pmo.opened_opps   * 100, 1) ELSE NULL END AS pct_change_opened_opps

FROM cm_won     cmw
CROSS JOIN cm_opened   cmo
CROSS JOIN pm_won      pmw
CROSS JOIN pm_opened   pmo
CROSS JOIN cq_targets  cqt
CROSS JOIN pq_targets  pqt
