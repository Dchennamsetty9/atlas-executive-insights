-- queries/coverage/current.sql
-- Pipeline coverage ratio at a given snapshot date.
-- Coverage = in-quarter open pipeline / (full-quarter plan target - QTD won pipeline)
-- Healthy range: 2-4x
--
-- Placeholders: {catalog}, {schema}, {snap_date}, {q_start}, {q_end}
-- Column notes (gaim_pipeline_daily_snapshot):
--   date       = data_day          (not snapshot_date)
--   deal open  = stage_name NOT IN closed stages  (not deal_status='Open')
--   deal won   = is_won = 'True'   (not deal_status='Won')
--   dollar amt = amount            (full ACV)
WITH latest AS (
    SELECT MAX(data_day) AS d
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
    WHERE data_day <= '{snap_date}'
),
snap AS (
    SELECT is_won, stage_name, amount, close_date
    FROM {catalog}.{schema}.gaim_pipeline_daily_snapshot
    WHERE data_day = (SELECT d FROM latest)
      AND xtxtype <> 'Cancel'
      AND (
            is_won = 'True'
            OR stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
      )
),
targets AS (
    SELECT SUM(Daily_Plan_Dollar) AS plan_target
    FROM {catalog}.{schema}.gaim_partner_sales_targets_cy_daily
    WHERE report_date BETWEEN '{q_start}' AND '{q_end}'
)
SELECT
    SUM(CASE WHEN s.is_won = 'False'
              AND s.close_date <= '{q_end}' THEN s.amount ELSE 0 END) AS same_q_pipeline,
    SUM(CASE WHEN s.is_won = 'False'
              AND s.close_date >  '{q_end}' THEN s.amount ELSE 0 END) AS not_same_q_pipeline,
    SUM(CASE WHEN s.is_won = 'False'         THEN s.amount ELSE 0 END) AS open_pipeline,
    MAX(t.plan_target)                                                  AS plan_target,
    SUM(CASE WHEN s.is_won = 'True'          THEN s.amount ELSE 0 END) AS qtd_booked
FROM snap s
CROSS JOIN targets t
