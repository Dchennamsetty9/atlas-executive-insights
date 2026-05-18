-- queries/coverage/current.sql
-- Pipeline coverage ratio at a given snapshot date.
-- Coverage = same-quarter open pipeline / (plan target - QTD booked)
-- Placeholders: {table}, {snap_date}, {q_end}
SELECT
    SUM(CASE WHEN close_date <= '{q_end}' THEN amount_towards_plan ELSE 0 END) AS same_q_pipeline,
    SUM(CASE WHEN close_date >  '{q_end}' THEN amount_towards_plan ELSE 0 END) AS not_same_q_pipeline,
    SUM(amount_towards_plan)                                                    AS open_pipeline,
    MAX(quarter_plan_target)                                                    AS plan_target,
    SUM(CASE WHEN deal_status = 'Won' THEN amount_towards_plan ELSE 0 END)     AS qtd_booked
FROM {table}
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM {table}
    WHERE snapshot_date <= '{snap_date}'
)
  AND deal_status IN ('Open', 'Won')
