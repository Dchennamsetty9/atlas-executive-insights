-- =============================================================================
-- Atlas Executive Insights — Gold Layer DDL
-- Catalog : datagroup_mdl
-- Schema  : atlas  (CREATE SCHEMA IF NOT EXISTS before running)
-- Refreshed by four Databricks Workflow jobs (see databricks.yml)
-- =============================================================================

-- ── 0. Schema ─────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS datagroup_mdl.atlas
  COMMENT 'Atlas Executive Insights pre-computed gold layer. READ-ONLY for app service principal.';

USE CATALOG datagroup_mdl;
USE SCHEMA   atlas;


-- ── 1. metrics_summary ────────────────────────────────────────────────────────
-- One row per (metric_key, geo, channel, product) per refresh.
-- Written by Job 1 (every 4h). App reads with a simple point-in-time SELECT.
-- All dimension values default to 'All' for the unfiltered, all-up roll-up.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.metrics_summary (
  metric_key           STRING  NOT NULL  COMMENT 'won_pipeline | win_rate | won_volume | ads | opps_created | created_pipeline | active_pipeline | coverage | mql',
  metric_label         STRING            COMMENT 'Human-readable label shown in the UI',
  metric_value         DOUBLE            COMMENT 'Current period value (QTD unless otherwise noted)',
  target_value         DOUBLE            COMMENT 'Paced target for the current period',
  annual_target        DOUBLE            COMMENT 'Full-quarter (or full-year) plan target',
  previous_value       DOUBLE            COMMENT 'Same point last quarter (QoQ comparison)',
  attainment_pct       DOUBLE            COMMENT 'metric_value / target_value * 100',
  status               STRING            COMMENT 'On Track | At Risk | Exceeding',
  delta_pct            DOUBLE            COMMENT 'Period-over-period % change vs previous_value',
  period_start         DATE              COMMENT 'Quarter start date',
  period_end           DATE              COMMENT 'As-of date (snapshot date)',
  geo                  STRING  DEFAULT 'All',
  channel              STRING  DEFAULT 'All',
  product              STRING  DEFAULT 'All',
  fuel_source          STRING  DEFAULT 'All',
  source_row_count     BIGINT            COMMENT 'Row count from source query for data quality checks',
  refreshed_at         TIMESTAMP         COMMENT 'UTC timestamp of last write'
)
USING DELTA
PARTITIONED BY (period_start, geo, channel)
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact'   = 'true'
)
COMMENT 'Current KPI values vs paced targets. Refreshed every 4h by Atlas Job1.';


-- ── 2. metrics_history ────────────────────────────────────────────────────────
-- Daily grain, 18 months rolling. Powers sparklines and trend charts.
-- Written by Job 1. APPEND only — existing dates are upserted via MERGE.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.metrics_history (
  metric_key    STRING  NOT NULL  COMMENT 'Same keys as metrics_summary.metric_key',
  metric_date   DATE    NOT NULL  COMMENT 'Calendar date of the data point',
  metric_value  DOUBLE            COMMENT 'Value on that date',
  geo           STRING  DEFAULT 'All',
  channel       STRING  DEFAULT 'All',
  product       STRING  DEFAULT 'All',
  refreshed_at  TIMESTAMP
)
USING DELTA
PARTITIONED BY (metric_key, geo)
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact'   = 'true',
  'delta.deletedFileRetentionDuration' = 'interval 30 days'
)
COMMENT 'Daily KPI time-series for sparklines and trend charts. 18-month rolling window.';


-- ── 3. insights_cache ─────────────────────────────────────────────────────────
-- AI-generated insights with a TTL of 6h. Written by Job 2.
-- The app filters: WHERE is_active = TRUE AND expires_at > CURRENT_TIMESTAMP()
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.insights_cache (
  insight_id        STRING  NOT NULL  COMMENT 'UUIDv4 generated at write time',
  title             STRING,
  description       STRING,
  recommendation    STRING,
  why_text          STRING            COMMENT 'Explanation shown in "Why am I seeing this?" expansion',
  severity          STRING            COMMENT 'high | medium | low',
  category          STRING            COMMENT 'pipeline | conversion | deals | forecast | coverage',
  icon              STRING            COMMENT 'Emoji or icon identifier for the UI',
  metric            STRING            COMMENT 'Primary metric this insight relates to',
  geo               STRING  DEFAULT 'All',
  channel           STRING  DEFAULT 'All',
  product           STRING  DEFAULT 'All',
  model_used        STRING            COMMENT 'LLM endpoint that generated this (e.g. databricks-claude-sonnet-4-6)',
  generated_at      TIMESTAMP,
  expires_at        TIMESTAMP         COMMENT 'is_active flipped to FALSE after this time',
  is_active         BOOLEAN DEFAULT TRUE
)
USING DELTA
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact'   = 'true'
)
COMMENT 'AI-generated insights. Refreshed every 6h by Atlas Job2.';


-- ── 4. forecast_results ───────────────────────────────────────────────────────
-- Multi-model forecast outputs. Written by Job 3 (nightly).
-- One row per (metric, model, forecast_date). App reads the latest run.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.forecast_results (
  forecast_run_id   STRING  NOT NULL  COMMENT 'UUIDv4 for the entire batch run',
  metric_key        STRING  NOT NULL,
  model_name        STRING  NOT NULL  COMMENT 'holt_winters | arima | triple_smoothing | linear_seasonal',
  horizon_days      INT               COMMENT '30 | 60 | 90',
  forecast_date     DATE              COMMENT 'Calendar date being forecasted',
  forecast_value    DOUBLE,
  lower_bound       DOUBLE            COMMENT '95% confidence interval lower',
  upper_bound       DOUBLE            COMMENT '95% confidence interval upper',
  mape              DOUBLE            COMMENT 'Mean Absolute Percentage Error on 30-day holdout',
  rmse              DOUBLE,
  model_confidence  DOUBLE            COMMENT '0–1 derived from (1 - mape/100) clamped',
  trend_status      STRING            COMMENT 'accelerating | stable | decelerating | volatile',
  risk_level        STRING            COMMENT 'low | moderate | high',
  best_case_90d     DOUBLE,
  worst_case_90d    DOUBLE,
  most_likely_90d   DOUBLE,
  upside_dollar     DOUBLE            COMMENT 'best_case_90d - most_likely_90d',
  downside_dollar   DOUBLE            COMMENT 'most_likely_90d - worst_case_90d',
  description       STRING            COMMENT 'AI-generated 2-sentence narrative for this forecast',
  key_drivers       STRING            COMMENT 'JSON array of 3 bullet strings',
  executive_actions STRING            COMMENT 'JSON array of 3 recommended actions',
  downside_risks    STRING            COMMENT 'JSON array of 3 risk statements',
  upside_opportunities STRING         COMMENT 'JSON array of 3 opportunity statements',
  history_days      INT               COMMENT 'Number of historical days used in training',
  geo               STRING  DEFAULT 'All',
  generated_at      TIMESTAMP,
  model_version     INT     DEFAULT 1
)
USING DELTA
PARTITIONED BY (metric_key, model_name)
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact'   = 'true',
  'delta.deletedFileRetentionDuration' = 'interval 7 days'
)
COMMENT 'Multi-model forecast outputs with confidence intervals. Refreshed nightly by Atlas Job3.';


-- ── 5. alerts_queue ───────────────────────────────────────────────────────────
-- Threshold-breach alerts pending Slack/email dispatch. Written by Job 4.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.alerts_queue (
  alert_id          STRING  NOT NULL  COMMENT 'UUIDv4',
  rule_id           STRING            COMMENT 'FK → alert_rules.rule_id',
  metric_key        STRING,
  alert_type        STRING            COMMENT 'threshold_breach | trend_reversal | forecast_miss',
  severity          STRING            COMMENT 'critical | warning | info',
  title             STRING,
  body              STRING,
  current_value     DOUBLE,
  threshold_value   DOUBLE,
  attainment_pct    DOUBLE,
  geo               STRING  DEFAULT 'All',
  channel           STRING  DEFAULT 'All',
  notified_slack    BOOLEAN DEFAULT FALSE,
  notified_email    BOOLEAN DEFAULT FALSE,
  notified_in_app   BOOLEAN DEFAULT FALSE,
  created_at        TIMESTAMP,
  dispatched_at     TIMESTAMP,
  status            STRING  DEFAULT 'pending'  COMMENT 'pending | dispatched | suppressed | acknowledged'
)
USING DELTA
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
COMMENT 'Threshold-breach alerts pending notification dispatch. Checked every 4h by Atlas Job4.';


-- ── 6. alert_rules ────────────────────────────────────────────────────────────
-- Configurable thresholds. Edit directly in Databricks or via /api/preferences.
-- NOT auto-populated by jobs — seeded once with defaults below.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.alert_rules (
  rule_id            STRING  NOT NULL,
  metric_key         STRING  NOT NULL,
  rule_type          STRING            COMMENT 'below_pct_of_target | trend_negative_n_days | forecast_miss_pct',
  threshold_value    DOUBLE            COMMENT 'For below_pct_of_target: 0.90 means alert at <90% of target',
  severity           STRING            COMMENT 'critical | warning',
  notify_slack       BOOLEAN DEFAULT TRUE,
  notify_email       BOOLEAN DEFAULT TRUE,
  notify_in_app      BOOLEAN DEFAULT TRUE,
  slack_channel      STRING  DEFAULT '#atlas-alerts',
  email_recipients   STRING            COMMENT 'Comma-separated. Falls back to NOTIFICATION_EMAIL env var.',
  cooldown_hours     INT     DEFAULT 4 COMMENT 'Min hours between repeat alerts for the same metric',
  is_active          BOOLEAN DEFAULT TRUE,
  created_at         TIMESTAMP,
  updated_at         TIMESTAMP
)
USING DELTA
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
COMMENT 'Configurable alert threshold rules. Seeded once; edit via Databricks SQL Editor or /api/preferences.';


-- ── 7. revenue_gap_decomposition ──────────────────────────────────────────────
-- Waterfall breakdown of revenue shortfall drivers. Written by Job 1.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.revenue_gap_decomposition (
  decomp_id             STRING  NOT NULL,
  period_start          DATE,
  period_end            DATE,
  geo                   STRING  DEFAULT 'All',
  channel               STRING  DEFAULT 'All',
  product               STRING  DEFAULT 'All',
  -- Headline numbers
  target_won_amount     DOUBLE,
  actual_won_amount     DOUBLE,
  total_gap             DOUBLE  COMMENT 'actual - target (negative = shortfall)',
  -- Five-factor decomposition (sum ≈ total_gap)
  impact_won_volume     DOUBLE  COMMENT 'Gap attributable to won deal count',
  impact_close_rate     DOUBLE  COMMENT 'Gap attributable to close rate (volume)',
  impact_ads            DOUBLE  COMMENT 'Gap attributable to average deal size',
  impact_pipeline       DOUBLE  COMMENT 'Gap attributable to pipeline $',
  impact_close_rate_dollar DOUBLE COMMENT 'Gap attributable to $ close rate',
  -- Raw KPI values used in decomposition
  won_volume            DOUBLE,
  close_rate_pct        DOUBLE,
  avg_deal_size         DOUBLE,
  active_pipeline       DOUBLE,
  opps_created          DOUBLE,
  refreshed_at          TIMESTAMP
)
USING DELTA
PARTITIONED BY (period_start, geo)
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
COMMENT 'Waterfall revenue gap decomposition. Refreshed every 4h by Atlas Job1.';


-- ── 8. extended_analytics ─────────────────────────────────────────────────────
-- Pre-aggregated data for all 5 analytics tabs. Flexible key-value structure
-- so new tabs can be added without schema changes.
CREATE TABLE IF NOT EXISTS datagroup_mdl.atlas.extended_analytics (
  tab_name         STRING  NOT NULL  COMMENT 'mql | pipeline_segments | deal_bands | coverage | largest_deals',
  dimension_key    STRING            COMMENT 'e.g. geo, channel, product, deal_size_band, stage',
  dimension_value  STRING            COMMENT 'e.g. NA, Partner, GoToConnect, $50K-$100K, Negotiation',
  metric_key       STRING,
  metric_value     DOUBLE,
  secondary_value  DOUBLE            COMMENT 'e.g. volume alongside $, or prior-period value',
  period_start     DATE,
  geo              STRING  DEFAULT 'All',
  channel          STRING  DEFAULT 'All',
  metadata_json    STRING            COMMENT 'JSON blob for tab-specific extra columns (stage, owner, days_in_stage, etc.)',
  refreshed_at     TIMESTAMP
)
USING DELTA
PARTITIONED BY (tab_name, period_start)
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true')
COMMENT 'Pre-aggregated analytics for all 5 extended tabs. Refreshed every 4h by Atlas Job1.';


-- =============================================================================
-- SEED DATA: Default alert rules
-- Run once after table creation. Uses INSERT ... ON CONFLICT DO NOTHING pattern
-- via MERGE to be idempotent.
-- =============================================================================

MERGE INTO datagroup_mdl.atlas.alert_rules AS t
USING (
  SELECT * FROM VALUES
    ('rule_won_pipeline_critical', 'won_pipeline',    'below_pct_of_target', 0.75, 'critical', TRUE, TRUE, TRUE, '#atlas-alerts', 'dchennamsetty@goto.com', 4,  TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
    ('rule_won_pipeline_warning',  'won_pipeline',    'below_pct_of_target', 0.90, 'warning',  TRUE, TRUE, TRUE, '#atlas-alerts', 'dchennamsetty@goto.com', 4,  TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
    ('rule_win_rate_critical',     'win_rate',        'below_pct_of_target', 0.75, 'critical', TRUE, TRUE, TRUE, '#atlas-alerts', 'dchennamsetty@goto.com', 8,  TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
    ('rule_pipeline_warning',      'active_pipeline', 'below_pct_of_target', 0.80, 'warning',  TRUE, FALSE,TRUE, '#atlas-alerts', 'dchennamsetty@goto.com', 12, TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
    ('rule_coverage_warning',      'coverage',        'below_pct_of_target', 0.80, 'warning',  TRUE, FALSE,TRUE, '#atlas-alerts', 'dchennamsetty@goto.com', 12, TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
    ('rule_mql_warning',           'mql',             'below_pct_of_target', 0.85, 'warning',  FALSE,FALSE,TRUE, '#atlas-alerts', 'dchennamsetty@goto.com', 24, TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
  AS src (rule_id, metric_key, rule_type, threshold_value, severity, notify_slack, notify_email, notify_in_app, slack_channel, email_recipients, cooldown_hours, is_active, created_at, updated_at)
) AS s ON t.rule_id = s.rule_id
WHEN NOT MATCHED THEN INSERT *;
