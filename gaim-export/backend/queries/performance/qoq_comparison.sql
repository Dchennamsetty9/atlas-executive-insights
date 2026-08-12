-- queries/performance/qoq_comparison.sql
-- ============================================================
-- Quarter-over-Quarter Fair Comparison
-- Uses is_in_qoq_period = true to compare equivalent days in each quarter.
-- "Equivalent days" accounts for end-of-quarter acceleration:
--   e.g., if today is day 42 of Q2, it compares against day 42 of Q1,
--   adjusted to match the deal-velocity profile of each period.
-- ============================================================
--
-- Structural placeholders:
--   {current_quarter_start}   YYYY-MM-DD  first day of current quarter
--   {prior_quarter_start}     YYYY-MM-DD  first day of prior quarter
--   {plan_version}            Plan | FY4 | FY7
--   {won_filter}              AND-prefixed fragment for metis_won_opps_fact
--   {opened_filter}           AND-prefixed fragment for metis_opened_opps_fact
--   {targets_filter}          AND-prefixed fragment for metis_targets_summary
-- ============================================================

WITH

latest_date AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),

-- Current quarter — equivalent-day window via is_in_qoq_period
cq_won AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS won_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS won_amount
    FROM federated.sales.metis_won_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date            = ld.max_date
      AND is_in_qoq_period     = TRUE
      AND close_date           >= DATE('{current_quarter_start}')
      {won_filter}
),

cq_opened AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS opened_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS opened_amount
    FROM federated.sales.metis_opened_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date              = ld.max_date
      AND is_in_qoq_period       = TRUE
      AND pipeline_entered_date  >= DATE('{current_quarter_start}')
      {opened_filter}
),

-- Prior quarter — same equivalent-day window
pq_won AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS won_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS won_amount
    FROM federated.sales.metis_won_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date        = ld.max_date
      AND is_in_qoq_period = TRUE
      AND close_date        BETWEEN DATE('{prior_quarter_start}')
                                AND DATE_ADD(DATE('{current_quarter_start}'), -1)
      {won_filter}
),

pq_opened AS (
    SELECT
        COUNT(DISTINCT salesforce_opportunity_id)  AS opened_opps,
        COALESCE(SUM(amount_towards_plan), 0)      AS opened_amount
    FROM federated.sales.metis_opened_opps_fact
    CROSS JOIN latest_date ld
    WHERE data_date             = ld.max_date
      AND is_in_qoq_period      = TRUE
      AND pipeline_entered_date  BETWEEN DATE('{prior_quarter_start}')
                                    AND DATE_ADD(DATE('{current_quarter_start}'), -1)
      {opened_filter}
),

-- Targets (paced for current quarter, full for prior quarter)
cq_targets AS (
    SELECT
        COALESCE(SUM(paced_won_amount),    0)  AS paced_won_amount,
        COALESCE(SUM(paced_won_opps),      0)  AS paced_won_opps,
        COALESCE(SUM(paced_opened_amount), 0)  AS paced_opened_amount,
        COALESCE(SUM(paced_opened_opps),   0)  AS paced_opened_opps
    FROM federated.sales.metis_targets_summary
    WHERE quarter_start_date = DATE('{current_quarter_start}')
      AND plan_version        = '{plan_version}'
      {targets_filter}
),

pq_targets AS (
    SELECT
        COALESCE(SUM(full_won_amount),     0)  AS paced_won_amount,
        COALESCE(SUM(full_won_opps),       0)  AS paced_won_opps,
        COALESCE(SUM(full_opened_amount),  0)  AS paced_opened_amount,
        COALESCE(SUM(full_opened_opps),    0)  AS paced_opened_opps
    FROM federated.sales.metis_targets_summary
    WHERE quarter_start_date = DATE('{prior_quarter_start}')
      AND plan_version        = '{plan_version}'
      {targets_filter}
)

SELECT
    -- ── Current Quarter ──────────────────────────────────────────────────────
    cqw.won_amount                                                               AS cq_won_amount,
    cqw.won_opps                                                                 AS cq_won_opps,
    cqo.opened_amount                                                            AS cq_pipeline,
    cqo.opened_opps                                                              AS cq_opened_opps,
    CASE WHEN cqw.won_opps   > 0 THEN ROUND(cqw.won_amount / cqw.won_opps, 2)     ELSE 0 END AS cq_ads,
    CASE WHEN cqo.opened_opps > 0 THEN ROUND(cqo.opened_amount / cqo.opened_opps, 2) ELSE 0 END AS cq_aos,
    CASE WHEN cqo.opened_opps > 0 THEN ROUND(cqw.won_opps * 1.0 / cqo.opened_opps, 4) ELSE 0 END AS cq_close_rate_opps,
    CASE WHEN cqo.opened_amount > 0 THEN ROUND(cqw.won_amount / cqo.opened_amount, 4) ELSE 0 END AS cq_close_rate_dollar,

    -- ── Prior Quarter (equivalent days) ─────────────────────────────────────
    pqw.won_amount                                                               AS pq_won_amount,
    pqw.won_opps                                                                 AS pq_won_opps,
    pqo.opened_amount                                                            AS pq_pipeline,
    pqo.opened_opps                                                              AS pq_opened_opps,
    CASE WHEN pqw.won_opps   > 0 THEN ROUND(pqw.won_amount / pqw.won_opps, 2)     ELSE 0 END AS pq_ads,
    CASE WHEN pqo.opened_opps > 0 THEN ROUND(pqo.opened_amount / pqo.opened_opps, 2) ELSE 0 END AS pq_aos,
    CASE WHEN pqo.opened_opps > 0 THEN ROUND(pqw.won_opps * 1.0 / pqo.opened_opps, 4) ELSE 0 END AS pq_close_rate_opps,
    CASE WHEN pqo.opened_amount > 0 THEN ROUND(pqw.won_amount / pqo.opened_amount, 4) ELSE 0 END AS pq_close_rate_dollar,

    -- ── QoQ Change (absolute) ────────────────────────────────────────────────
    ROUND(cqw.won_amount - pqw.won_amount, 2)                                    AS delta_won_amount,
    ROUND(cqw.won_opps   - pqw.won_opps, 0)                                      AS delta_won_opps,
    ROUND(cqo.opened_amount - pqo.opened_amount, 2)                              AS delta_pipeline,
    ROUND(cqo.opened_opps   - pqo.opened_opps, 0)                                AS delta_opened_opps,

    -- ── QoQ Change (%) ───────────────────────────────────────────────────────
    CASE WHEN pqw.won_amount    > 0 THEN ROUND((cqw.won_amount    - pqw.won_amount)    / pqw.won_amount    * 100, 1) ELSE NULL END AS pct_change_won_amount,
    CASE WHEN pqw.won_opps      > 0 THEN ROUND((cqw.won_opps      - pqw.won_opps)      / pqw.won_opps      * 100, 1) ELSE NULL END AS pct_change_won_opps,
    CASE WHEN pqo.opened_amount > 0 THEN ROUND((cqo.opened_amount - pqo.opened_amount) / pqo.opened_amount * 100, 1) ELSE NULL END AS pct_change_pipeline,
    CASE WHEN pqo.opened_opps   > 0 THEN ROUND((cqo.opened_opps   - pqo.opened_opps)   / pqo.opened_opps   * 100, 1) ELSE NULL END AS pct_change_opened_opps,

    -- ── Paced Targets ────────────────────────────────────────────────────────
    cqt.paced_won_amount                                                          AS cq_target_won_amount,
    pqt.paced_won_amount                                                          AS pq_target_won_amount,
    cqt.paced_opened_amount                                                       AS cq_target_pipeline,
    pqt.paced_opened_amount                                                       AS pq_target_pipeline,

    -- ── Attainment ───────────────────────────────────────────────────────────
    CASE WHEN cqt.paced_won_amount > 0 THEN ROUND(cqw.won_amount / cqt.paced_won_amount * 100, 1) ELSE NULL END AS cq_won_attainment_pct,
    CASE WHEN pqt.paced_won_amount > 0 THEN ROUND(pqw.won_amount / pqt.paced_won_amount * 100, 1) ELSE NULL END AS pq_won_attainment_pct

FROM cq_won     cqw
CROSS JOIN cq_opened   cqo
CROSS JOIN pq_won      pqw
CROSS JOIN pq_opened   pqo
CROSS JOIN cq_targets  cqt
CROSS JOIN pq_targets  pqt
