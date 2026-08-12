-- queries/performance/revenue_gap.sql
-- ============================================================
-- Revenue Gap Decomposition — Dollarized Impact by KPI
-- Source tables: federated.sales.metis_*
--
-- Uses the same two-funnel decomposition as KPI Trends — Overview in Polaris:
--
--   Opp Volume Funnel:
--     Opened Opps × Close Rate (Vol) × ADS  =  Won Amount
--     Impact = Opened Opps Impact + Close Rate (Vol) Impact + ADS Impact
--
--   Dollar Funnel:
--     Opened Opps × AOS × Close Rate ($)    =  Won Amount
--     Impact = Opened Opps Impact + AOS Impact + Close Rate ($) Impact
--
-- Key identity: within each funnel the two input impacts sum to the output impact.
-- Total shortfall = Won Amount Actual − Paced Target (negative = below target).
-- ============================================================
--
-- Structural placeholders (same as kpi_dashboard.sql):
--   {period_start}, {period_end}, {quarter_start}, {plan_version}
--   {won_filter}, {opened_filter}, {targets_filter}
-- ============================================================

WITH

latest_date AS (
    SELECT MAX(data_date) AS max_date
    FROM   federated.sales.metis_won_opps_fact
),

won_actuals AS (
    SELECT
        COUNT(DISTINCT w.salesforce_opportunity_id)  AS won_opps,
        COALESCE(SUM(w.amount_towards_plan), 0)      AS won_amount
    FROM federated.sales.metis_won_opps_fact  w
    CROSS JOIN latest_date  ld
    WHERE w.data_date  = ld.max_date
      AND w.close_date BETWEEN DATE('{period_start}') AND DATE('{period_end}')
      {won_filter}
),

opened_actuals AS (
    SELECT
        COUNT(DISTINCT o.salesforce_opportunity_id)  AS opened_opps,
        COALESCE(SUM(o.amount_towards_plan), 0)      AS opened_amount
    FROM federated.sales.metis_opened_opps_fact  o
    CROSS JOIN latest_date  ld
    WHERE o.data_date            = ld.max_date
      AND o.pipeline_entered_date BETWEEN DATE('{period_start}') AND DATE('{period_end}')
      {opened_filter}
),

targets_agg AS (
    SELECT
        COALESCE(SUM(paced_won_amount),    0)  AS paced_won_amount,
        COALESCE(SUM(paced_won_opps),      0)  AS paced_won_opps,
        COALESCE(SUM(paced_opened_amount), 0)  AS paced_opened_amount,
        COALESCE(SUM(paced_opened_opps),   0)  AS paced_opened_opps
    FROM federated.sales.metis_targets_summary
    WHERE quarter_start_date = DATE('{quarter_start}')
      AND plan_version        = '{plan_version}'
      {targets_filter}
),

-- ── Derived actuals and targets ──────────────────────────────────────────────
kpis AS (
    SELECT
        -- Actuals
        w.won_opps                                                                      AS a_won_opps,
        w.won_amount                                                                    AS a_won_amount,
        o.opened_opps                                                                   AS a_opened_opps,
        o.opened_amount                                                                 AS a_pipeline,

        CASE WHEN w.won_opps   > 0 THEN w.won_amount / w.won_opps   ELSE 0 END         AS a_ads,
        CASE WHEN o.opened_opps > 0 THEN o.opened_amount / o.opened_opps ELSE 0 END    AS a_aos,
        CASE WHEN o.opened_opps > 0 THEN w.won_opps * 1.0 / o.opened_opps ELSE 0 END  AS a_cr_opps,
        CASE WHEN o.opened_amount > 0 THEN w.won_amount / o.opened_amount ELSE 0 END   AS a_cr_dollar,

        -- Paced targets
        t.paced_won_opps                                                                AS t_won_opps,
        t.paced_won_amount                                                              AS t_won_amount,
        t.paced_opened_opps                                                             AS t_opened_opps,
        t.paced_opened_amount                                                           AS t_pipeline,

        CASE WHEN t.paced_won_opps   > 0 THEN t.paced_won_amount / t.paced_won_opps   ELSE 0 END AS t_ads,
        CASE WHEN t.paced_opened_opps > 0 THEN t.paced_opened_amount / t.paced_opened_opps ELSE 0 END AS t_aos,
        CASE WHEN t.paced_opened_opps > 0 THEN t.paced_won_opps / t.paced_opened_opps ELSE 0 END  AS t_cr_opps,
        CASE WHEN t.paced_opened_amount > 0 THEN t.paced_won_amount / t.paced_opened_amount ELSE 0 END AS t_cr_dollar

    FROM won_actuals w
    CROSS JOIN opened_actuals o
    CROSS JOIN targets_agg    t
)

SELECT
    -- ── Summary ─────────────────────────────────────────────────────────────
    a_won_amount                                                                  AS actual_won_amount,
    t_won_amount                                                                  AS target_won_amount,
    ROUND(a_won_amount - t_won_amount, 2)                                         AS total_gap,
    CASE WHEN t_won_amount > 0
         THEN ROUND((a_won_amount - t_won_amount) / t_won_amount * 100, 1)
         ELSE NULL END                                                            AS gap_pct,

    -- ── Opp Volume Funnel Impacts ────────────────────────────────────────────
    -- Rule: Opened Opps Impact + CR(Vol) Impact + ADS Impact ≈ Total Won $ Gap
    -- (small residual from non-linear interaction terms; impacts allocated at target rates)

    -- Opened Opps Impact: (Actual Opened − Target Opened) × Target CR(Vol) × Target ADS
    ROUND((a_opened_opps - t_opened_opps) * t_cr_opps * t_ads, 2)               AS impact_opened_opps,

    -- Close Rate (Vol) Impact: Actual Opened × (Actual CR − Target CR) × Target ADS
    ROUND(a_opened_opps * (a_cr_opps - t_cr_opps) * t_ads, 2)                   AS impact_close_rate_opps,

    -- Won Opps Impact (direct): (Actual Won Opps − Target) × Target ADS
    ROUND((a_won_opps - t_won_opps) * t_ads, 2)                                  AS impact_won_opps,

    -- ADS Impact: Actual Won Opps × (Actual ADS − Target ADS)
    ROUND(a_won_opps * (a_ads - t_ads), 2)                                       AS impact_ads,

    -- ── Dollar Funnel Impacts ────────────────────────────────────────────────
    -- Rule: Opened Opps Impact + AOS Impact + CR($) Impact ≈ Total Won $ Gap

    -- Pipeline ($ basis): (Actual Pipeline − Target Pipeline) × Target CR($)
    ROUND((a_pipeline - t_pipeline) * t_cr_dollar, 2)                            AS impact_pipeline,

    -- Average Opp Size Impact: Actual Opened × (Actual AOS − Target AOS) × Target CR($)
    ROUND(a_opened_opps * (a_aos - t_aos) * t_cr_dollar, 2)                      AS impact_aos,

    -- Close Rate ($) Impact: Actual Pipeline × (Actual CR$ − Target CR$)
    ROUND(a_pipeline * (a_cr_dollar - t_cr_dollar), 2)                           AS impact_close_rate_dollar,

    -- ── Actuals (for context) ────────────────────────────────────────────────
    ROUND(a_ads, 2)        AS actual_ads,
    ROUND(t_ads, 2)        AS target_ads,
    ROUND(a_aos, 2)        AS actual_aos,
    ROUND(t_aos, 2)        AS target_aos,
    ROUND(a_cr_opps, 4)    AS actual_close_rate_opps,
    ROUND(t_cr_opps, 4)    AS target_close_rate_opps,
    ROUND(a_cr_dollar, 4)  AS actual_close_rate_dollar,
    ROUND(t_cr_dollar, 4)  AS target_close_rate_dollar,
    a_opened_opps          AS actual_opened_opps,
    t_opened_opps          AS target_opened_opps,
    a_pipeline             AS actual_pipeline,
    t_pipeline             AS target_pipeline,
    a_won_opps             AS actual_won_opps,
    t_won_opps             AS target_won_opps

FROM kpis
