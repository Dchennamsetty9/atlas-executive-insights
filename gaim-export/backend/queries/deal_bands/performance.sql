-- queries/deal_bands/performance.sql
-- Deal volume, value, win rate grouped by deal-size band,
-- compared against a prior snapshot date.
--
-- Placeholders: {table}, {today}, {prior_date}, {band_cases}
-- Note: {band_cases} is built from a static Python constant (BANDS), not user input.
--
-- Column notes (gaim_pipeline_daily_snapshot):
--   date column   = data_day         (not snapshot_date)
--   deal id       = opportunities_created_ids  (not opportunity_id)
--   won deals     = is_won = 'True'
--   lost deals    = stage_name IN ('Closed Lost','Closed-Cancelled')
WITH classified AS (
    SELECT
        CASE {band_cases} END                  AS band,
        data_day,
        opportunities_created_ids              AS opportunity_id,
        amount_towards_plan,
        CASE
            WHEN is_won = 'True' THEN 'Won'
            WHEN stage_name IN ('Closed Lost','Closed-Cancelled') THEN 'Lost'
            ELSE 'Open'
        END                                    AS deal_status
    FROM {table}
    WHERE data_day IN ('{today}', '{prior_date}')
      AND xtxtype <> 'Cancel'
      AND (
            is_won = 'True'
            OR stage_name NOT IN ('Closed Won', 'Closed Lost', 'Closed-Cancelled')
            OR stage_name IN ('Closed Lost', 'Closed-Cancelled')
      )
),
current_p AS (
    SELECT
        band,
        COUNT(DISTINCT opportunity_id)                        AS volume,
        SUM(amount_towards_plan)                              AS value,
        SUM(CASE WHEN deal_status = 'Won'  THEN 1 ELSE 0 END) * 1.0
            / NULLIF(SUM(CASE WHEN deal_status IN ('Won','Lost') THEN 1 ELSE 0 END), 0) * 100
                                                              AS win_rate
    FROM classified
    WHERE data_day = '{today}'
    GROUP BY band
),
prior_p AS (
    SELECT
        band,
        COUNT(DISTINCT opportunity_id)                        AS p_volume,
        SUM(amount_towards_plan)                              AS p_value,
        SUM(CASE WHEN deal_status = 'Won'  THEN 1 ELSE 0 END) * 1.0
            / NULLIF(SUM(CASE WHEN deal_status IN ('Won','Lost') THEN 1 ELSE 0 END), 0) * 100
                                                              AS p_win_rate
    FROM classified
    WHERE data_day = '{prior_date}'
    GROUP BY band
)
SELECT
    c.band,
    c.volume,
    c.value,
    ROUND(c.win_rate,    1)                                   AS win_rate,
    p.p_volume                                                AS prior_volume,
    p.p_value                                                 AS prior_value,
    ROUND(p.p_win_rate,  1)                                   AS prior_win_rate,
    ROUND((c.volume - p.p_volume) / NULLIF(p.p_volume, 0) * 100, 1) AS volume_chg_pct,
    ROUND((c.value  - p.p_value)  / NULLIF(p.p_value,  0) * 100, 1) AS value_chg_pct
FROM current_p c
LEFT JOIN prior_p p ON c.band = p.band
ORDER BY CASE c.band
    WHEN '$0–$10K'      THEN 1
    WHEN '$10K–$25K'    THEN 2
    WHEN '$25K–$100K'   THEN 3
    WHEN '$100K–$500K'  THEN 4
    WHEN '$500K–$1M'    THEN 5
    WHEN '$1M+'          THEN 6
END,
current_p AS (
    SELECT
        band,
        COUNT(DISTINCT opportunity_id)                    AS volume,
        SUM(amount_towards_plan)                          AS value,
        AVG(days_in_stage)                                AS avg_cycle,
        SUM(CASE WHEN deal_status = 'Won' THEN 1 ELSE 0 END) * 1.0
            / NULLIF(SUM(CASE WHEN deal_status IN ('Won','Lost') THEN 1 ELSE 0 END), 0) * 100
                                                          AS win_rate
    FROM classified
    WHERE snapshot_date = '{today}'
    GROUP BY band
),
prior_p AS (
    SELECT
        band,
        COUNT(DISTINCT opportunity_id)                    AS p_volume,
        SUM(amount_towards_plan)                          AS p_value,
        SUM(CASE WHEN deal_status = 'Won' THEN 1 ELSE 0 END) * 1.0
            / NULLIF(SUM(CASE WHEN deal_status IN ('Won','Lost') THEN 1 ELSE 0 END), 0) * 100
                                                          AS p_win_rate
    FROM classified
    WHERE snapshot_date = '{prior_date}'
    GROUP BY band
)
SELECT
    c.band,
    c.volume,
    c.value,
    ROUND(c.win_rate,    1)                               AS win_rate,
    ROUND(c.avg_cycle)                                    AS avg_cycle_days,
    p.p_volume                                            AS prior_volume,
    p.p_value                                             AS prior_value,
    ROUND(p.p_win_rate,  1)                               AS prior_win_rate,
    ROUND((c.volume - p.p_volume) / NULLIF(p.p_volume, 0) * 100, 1) AS volume_chg_pct,
    ROUND((c.value  - p.p_value)  / NULLIF(p.p_value,  0) * 100, 1) AS value_chg_pct
FROM current_p c
LEFT JOIN prior_p p ON c.band = p.band
ORDER BY CASE c.band
    WHEN '$0\u2013$10K'      THEN 1
    WHEN '$10K\u2013$25K'    THEN 2
    WHEN '$25K\u2013$100K'   THEN 3
    WHEN '$100K\u2013$500K'  THEN 4
    WHEN '$500K\u2013$1M'    THEN 5
    WHEN '$1M+'              THEN 6
END
