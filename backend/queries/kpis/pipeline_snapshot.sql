-- queries/kpis/pipeline_snapshot.sql
-- Core pipeline KPIs: Won Pipeline, Won Volume, Win Rate, ADS, Active Pipeline.
-- Compares current snapshot vs 90 days prior.
--
-- Placeholders: {catalog}, {schema}, {filter_clause}
-- Note: {filter_clause} is constructed from VALIDATED whitelist values only —
--       never from raw user input.
WITH latest AS (
    SELECT MAX(data_day) AS d
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
),
snap AS (
    SELECT *
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
    WHERE data_day = (SELECT d FROM latest)
      AND xtxtype <> 'Cancel'
      {filter_clause}
),
won AS (
    SELECT
        SUM(amount_towards_plan)                      AS won_pipeline,
        COUNT(DISTINCT opportunities_created_ids)     AS won_volume
    FROM snap
    WHERE is_won = 'True'
),
lost AS (
    SELECT
        COUNT(DISTINCT opportunities_created_ids)     AS lost_volume
    FROM snap
    WHERE is_won = 'False'
      AND stage_name IN ('Closed Lost', 'Closed-Cancelled')
),
active AS (
    SELECT
        SUM(amount_towards_plan)                      AS active_pipeline,
        COUNT(DISTINCT opportunities_created_ids)     AS open_volume
    FROM snap
    WHERE stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
),
prev AS (
    SELECT
        SUM(amount_towards_plan)                      AS prev_won_pipeline,
        COUNT(DISTINCT opportunities_created_ids)     AS prev_won_volume
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
    WHERE data_day = DATE_ADD((SELECT d FROM latest), -90)
      AND is_won = 'True'
      AND xtxtype <> 'Cancel'
      {filter_clause}
)
SELECT
    w.won_pipeline,
    w.won_volume,
    l.lost_volume,
    a.active_pipeline,
    a.open_volume,
    p.prev_won_pipeline,
    p.prev_won_volume,
    -- Win Rate: resolved deals only (not affected by open-deal timing)
    CASE WHEN (w.won_volume + l.lost_volume) > 0
         THEN w.won_volume * 100.0 / (w.won_volume + l.lost_volume)
         ELSE 0 END AS win_rate_pct,
    -- Average Deal Size
    CASE WHEN w.won_volume > 0
         THEN w.won_pipeline / w.won_volume
         ELSE 0 END AS ads,
    -- Average Open Opportunity Size
    CASE WHEN a.open_volume > 0
         THEN a.active_pipeline / a.open_volume
         ELSE 0 END AS open_opp_size
FROM won w, lost l, active a, prev p
