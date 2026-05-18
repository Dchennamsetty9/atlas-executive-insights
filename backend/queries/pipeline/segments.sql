-- queries/pipeline/segments.sql
-- Pipeline value and deal volume broken down by a segment dimension,
-- compared against a prior period (YoY or QoQ).
--
-- Placeholders: {table}, {col}, {q_end}, {prior_start}, {prior_end}
-- Note: {col} must be validated against DIMENSION_COLUMNS whitelist before use.
WITH current_q AS (
    SELECT
        {col}                               AS segment,
        SUM(amount_towards_plan)            AS current_value,
        COUNT(DISTINCT opportunity_id)      AS current_volume
    FROM {table}
    WHERE snapshot_date = '{q_end}'
      AND deal_status IN ('Won', 'Open')
    GROUP BY 1
),
prior_q AS (
    SELECT
        {col}                               AS segment,
        SUM(amount_towards_plan)            AS prior_value,
        COUNT(DISTINCT opportunity_id)      AS prior_volume
    FROM {table}
    WHERE snapshot_date = (
        SELECT MAX(snapshot_date)
        FROM {table}
        WHERE snapshot_date BETWEEN '{prior_start}' AND '{prior_end}'
    )
      AND deal_status IN ('Won', 'Open')
    GROUP BY 1
)
SELECT
    c.segment,
    c.current_value,
    c.current_volume,
    p.prior_value,
    p.prior_volume,
    ROUND((c.current_value  - p.prior_value)  / NULLIF(p.prior_value,  0) * 100, 1) AS value_yoy_pct,
    ROUND((c.current_volume - p.prior_volume) / NULLIF(p.prior_volume, 0) * 100, 1) AS volume_yoy_pct,
    ROUND(c.current_value / NULLIF(c.current_volume, 0))                             AS avg_deal_size
FROM current_q c
LEFT JOIN prior_q p ON c.segment = p.segment
ORDER BY c.current_value DESC
