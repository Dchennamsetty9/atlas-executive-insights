-- queries/coverage/trend.sql
-- Daily coverage ratio throughout the current quarter.
-- Coverage = same-quarter open pipeline / (plan target - QTD booked)
-- Placeholders: {table}, {q_start}, {q_end}
SELECT
    snapshot_date,
    ROUND(
        SUM(CASE WHEN close_date <= '{q_end}' THEN amount_towards_plan ELSE 0 END)
        / NULLIF(
            MAX(quarter_plan_target)
            - SUM(CASE WHEN deal_status = 'Won' THEN amount_towards_plan ELSE 0 END),
            0
        ),
    2) AS coverage_ratio
FROM {table}
WHERE snapshot_date BETWEEN '{q_start}' AND CURRENT_DATE
  AND deal_status IN ('Open', 'Won')
GROUP BY snapshot_date
ORDER BY snapshot_date
