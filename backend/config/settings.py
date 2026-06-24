"""
Configuration settings for the backend application
"""

from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Databricks (recommended - same source as Performance Hub)
    # When deployed to Databricks Apps, these are auto-provided
    databricks_server_hostname: str = os.getenv("DATABRICKS_SERVER_HOSTNAME", os.getenv("DATABRICKS_HOST", "goto-data-dock.cloud.databricks.com"))
    databricks_http_path: str = "/sql/1.0/warehouses/c24ee33594e13e93"
    databricks_access_token: str = os.getenv("DATABRICKS_TOKEN", "")
    databricks_catalog: str = "datagroup_mdl"
    databricks_schema: str = "mdl_sales_analytics"
    
    # SQL Server (alternative)
    db_server: str = ""
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_driver: str = "ODBC Driver 18 for SQL Server"
    
    # Application
    environment: str = os.getenv("ENVIRONMENT", "production")
    debug: bool = os.getenv("DEBUG", "False").lower() == "true"
    api_port: int = int(os.getenv("PORT", "8000"))
    auth_allow_anonymous_local: bool = os.getenv("AUTH_ALLOW_ANONYMOUS_LOCAL", "true").lower() == "true"
    enable_debug_endpoints: bool = os.getenv("ENABLE_DEBUG_ENDPOINTS", "false").lower() == "true"
    
    # CORS origins — FastAPI CORSMiddleware does NOT support wildcard subdomains,
    # so the workspace hostname must be listed explicitly.
    @property
    def cors_origins(self) -> List[str]:
        origins = [
            "http://localhost:3000",
            "http://localhost:3002",   # Vite dev server
            "http://localhost:5173",
            "https://goto-data-dock.cloud.databricks.com",
        ]
        # Add DATABRICKS_HOST if injected by Databricks Apps runtime
        host = os.getenv("DATABRICKS_HOST", "")
        if host:
            # Ensure it is a proper https:// origin (strip trailing slashes)
            if not host.startswith("http"):
                host = f"https://{host}"
            host = host.rstrip("/")
            if host not in origins:
                origins.append(host)

        app_host = os.getenv("APP_URL", "").rstrip("/")
        if app_host and app_host not in origins:
            origins.append(app_host)
        return origins
    
    # Forecasting
    forecast_default_periods: int = 90
    forecast_confidence_interval: float = 0.95

    # Set DEMO_MODE=true in .env to skip Databricks entirely and use built-in demo data.
    demo_mode: bool = False

    # ── Notifications ─────────────────────────────────────────────────────────
    # SMTP (email alerts)
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "atlas-alerts@goto.com")
    smtp_tls: bool = os.getenv("SMTP_TLS", "true").lower() == "true"

    # Slack (webhook-based alerts)
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    slack_channel: str = os.getenv("SLACK_CHANNEL", "#atlas-alerts")

    # Alert thresholds (default: alert when metric drops below N% of target)
    alert_threshold_at_risk: float = float(os.getenv("ALERT_THRESHOLD_AT_RISK", "0.90"))
    alert_threshold_critical: float = float(os.getenv("ALERT_THRESHOLD_CRITICAL", "0.75"))

    # ── User Preferences Delta table (Databricks) ─────────────────────────────
    user_prefs_catalog: str = os.getenv("USER_PREFS_CATALOG", "datagroup_mdl")
    user_prefs_schema: str = os.getenv("USER_PREFS_SCHEMA", "mdl_sales_analytics")
    user_prefs_table: str = os.getenv("USER_PREFS_TABLE", "atlas_user_preferences")
    actions_table: str = os.getenv("ACTIONS_TABLE", "atlas_executive_actions")
    notifications_table: str = os.getenv("NOTIFICATIONS_TABLE", "atlas_notifications")

    # ── Gold Layer (pre-computed Delta tables) ────────────────────────────────
    atlas_catalog: str = os.getenv("ATLAS_CATALOG", "datagroup_mdl")
    atlas_schema: str = os.getenv("ATLAS_SCHEMA", "mdl_sales_analytics")
    atlas_kpi_table_prefix: str = os.getenv("ATLAS_KPI_TABLE_PREFIX", "atlas_kpi")

    # ── AWS SES (email notifications via Amazon SES) ──────────────────────────
    # When ses_region is set, SES is preferred over SMTP.
    ses_region: str = os.getenv("AWS_SES_REGION", "")
    ses_from_email: str = os.getenv("SES_FROM_EMAIL", "atlas-alerts@goto.com")

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"   # silently ignore env vars that don't match declared fields


# Singleton instance
settings = Settings()
