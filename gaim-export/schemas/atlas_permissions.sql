-- =============================================================================
-- Atlas Executive Insights — Service Principal Permission Model
-- Run in Databricks SQL Editor (admin account required)
--
-- TWO principals:
--   atlas-app-sp      → the app service principal (Databricks Apps runtime)
--   atlas-workflow-sp → the Databricks Workflow service principal
--
-- Replace the principal names with your actual SP application IDs or display names.
-- Find them at: Workspace Settings → Identity & Access → Service Principals
-- =============================================================================


-- =============================================================================
-- PART A: App Service Principal (atlas-app-sp)
-- Principle of least privilege: READ-ONLY on all atlas.* gold tables.
-- WRITE on three user-data tables only.
-- No access to raw source tables (datagroup_mdl.mdl_sales_analytics).
-- =============================================================================

-- A1. Allow the SP to use the catalog and gold schema
GRANT USE CATALOG ON CATALOG datagroup_mdl
  TO `atlas-app-sp`;

GRANT USE SCHEMA ON SCHEMA datagroup_mdl.atlas
  TO `atlas-app-sp`;

GRANT USE SCHEMA ON SCHEMA datagroup_mdl.mdl_sales_analytics
  TO `atlas-app-sp`;

-- A2. Read all gold tables (current + future)
GRANT SELECT ON ALL TABLES IN SCHEMA datagroup_mdl.atlas
  TO `atlas-app-sp`;

-- Re-run after adding new gold tables (Unity Catalog does not retroactively grant):
-- ALTER DEFAULT PRIVILEGES IN SCHEMA datagroup_mdl.atlas GRANT SELECT ON TABLES TO `atlas-app-sp`;

-- A3. Write only to the three user-data tables
GRANT INSERT, UPDATE ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_user_preferences
  TO `atlas-app-sp`;

GRANT INSERT, UPDATE ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_executive_actions
  TO `atlas-app-sp`;

GRANT INSERT, UPDATE ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_notifications
  TO `atlas-app-sp`;

-- A4. Read-only on federated.sales.* (for pass-through live KPI queries when gold table is stale)
GRANT USE CATALOG ON CATALOG federated          TO `atlas-app-sp`;
GRANT USE SCHEMA  ON SCHEMA   federated.sales    TO `atlas-app-sp`;
GRANT SELECT      ON ALL TABLES IN SCHEMA federated.sales   TO `atlas-app-sp`;

-- A5. Explicit DENY on any write to raw MDL tables (defense in depth)
-- Unity Catalog does not have DENY; instead ensure no WRITE grants are issued.
-- Audit with:
--   SHOW GRANTS ON SCHEMA datagroup_mdl.mdl_sales_analytics;


-- =============================================================================
-- PART B: Workflow Service Principal (atlas-workflow-sp)
-- Needs READ on source tables and WRITE on atlas.* gold tables.
-- Does NOT need write on user-data tables (that is the app's domain).
-- =============================================================================

-- B1. Catalog + schema access
GRANT USE CATALOG ON CATALOG datagroup_mdl          TO `atlas-workflow-sp`;
GRANT USE CATALOG ON CATALOG federated              TO `atlas-workflow-sp`;

GRANT USE SCHEMA  ON SCHEMA datagroup_mdl.atlas                TO `atlas-workflow-sp`;
GRANT USE SCHEMA  ON SCHEMA datagroup_mdl.mdl_sales_analytics  TO `atlas-workflow-sp`;
GRANT USE SCHEMA  ON SCHEMA federated.sales                    TO `atlas-workflow-sp`;

-- B2. Read all source tables
GRANT SELECT ON ALL TABLES IN SCHEMA datagroup_mdl.mdl_sales_analytics  TO `atlas-workflow-sp`;
GRANT SELECT ON ALL TABLES IN SCHEMA federated.sales                    TO `atlas-workflow-sp`;

-- B3. Create + write all atlas gold tables
GRANT CREATE TABLE ON SCHEMA datagroup_mdl.atlas  TO `atlas-workflow-sp`;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA datagroup_mdl.atlas
  TO `atlas-workflow-sp`;

-- B4. Read user-data tables to check alert suppression (cooldown)
GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_notifications
  TO `atlas-workflow-sp`;

-- B5. Databricks Foundation Model API access
-- Controlled via workspace-level settings → not a SQL grant.
-- Ensure atlas-workflow-sp is added to: Workspace Settings → AI & Governance → Serving endpoints


-- =============================================================================
-- PART C: Verify grants (run as admin to audit)
-- =============================================================================

-- SHOW GRANTS ON SCHEMA datagroup_mdl.atlas;
-- SHOW GRANTS ON SCHEMA federated.sales;
-- SHOW GRANTS ON TABLE datagroup_mdl.mdl_sales_analytics.atlas_user_preferences;


-- =============================================================================
-- PART D: Row-Level Security (optional — add if multi-tenant requirements emerge)
-- Example: restrict Partner leaders to their own channel rows only
-- =============================================================================

/*
CREATE ROW FILTER atlas_channel_filter ON datagroup_mdl.atlas.metrics_summary (geo, channel)
AS (user_name_in_group('atlas-partner-leaders') = FALSE
    OR channel = current_user_attribute('default_channel')
    OR channel = 'All');

ALTER TABLE datagroup_mdl.atlas.metrics_summary
  SET ROW FILTER atlas_channel_filter ON (geo, channel);
*/
