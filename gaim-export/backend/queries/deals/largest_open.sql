-- queries/deals/largest_open.sql
-- Top open deals ranked by pipeline value at the latest available snapshot.
-- Placeholders: {table}, {today}, {q_end}, {limit}
--
-- Column notes (gaim_pipeline_daily_snapshot):
--   date column          = data_day          (not snapshot_date)
--   open deal filter     = stage_name NOT IN closed stages  (not deal_status='Open')
--   deal identifier      = opportunities_created_ids  (not opportunity_id)
--   dollar amount        = amount            (full ACV)
SELECT
    ROW_NUMBER() OVER (ORDER BY amount DESC)         AS rank,
    opportunities_created_ids                        AS opportunity_id,
    amount                                           AS amount,
    stage_name                                       AS stage,
    close_date,
    smoothed_channel                                 AS channel,
    CASE WHEN close_date <= '{q_end}' THEN TRUE ELSE FALSE END AS in_quarter,
    CASE WHEN close_date < data_day   THEN TRUE ELSE FALSE END AS slipped
FROM {table}
WHERE data_day = (
    SELECT MAX(data_day)
    FROM {table}
    WHERE data_day <= '{today}'
)
  AND xtxtype <> 'Cancel'
  AND stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
  AND amount > 0
ORDER BY amount DESC
LIMIT {limit}
