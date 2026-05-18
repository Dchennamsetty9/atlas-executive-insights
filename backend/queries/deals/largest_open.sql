-- queries/deals/largest_open.sql
-- Top open deals ranked by pipeline value at the latest available snapshot.
-- Placeholders: {table}, {today}, {q_end}, {limit}
SELECT
    ROW_NUMBER() OVER (ORDER BY amount_towards_plan DESC) AS rank,
    opportunity_id,
    opportunity_name,
    amount_towards_plan                                    AS amount,
    stage_name                                             AS stage,
    close_date,
    smoothed_channel                                       AS channel,
    owner_name                                             AS owner,
    days_in_stage,
    CASE WHEN close_date <= '{q_end}' THEN TRUE ELSE FALSE END AS in_quarter,
    CASE WHEN close_date < snapshot_date THEN TRUE ELSE FALSE END AS slipped
FROM {table}
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM {table}
    WHERE snapshot_date <= '{today}'
)
  AND deal_status = 'Open'
  AND amount_towards_plan > 0
ORDER BY amount_towards_plan DESC
LIMIT {limit}
