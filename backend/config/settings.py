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
    
    # Azure OpenAI (optional - for advanced insights)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4"
    azure_openai_api_version: str = "2024-02-15-preview"
    
    # Application
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = os.getenv("DEBUG", "True").lower() == "true"
    api_port: int = int(os.getenv("PORT", "8000"))
    
    # CORS origins — FastAPI CORSMiddleware does NOT support wildcard subdomains,
    # so the workspace hostname must be listed explicitly.
    @property
    def cors_origins(self) -> List[str]:
        origins = [
            "http://localhost:3000",
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
        return origins
    
    # Forecasting
    forecast_default_periods: int = 90
    forecast_confidence_interval: float = 0.95
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"   # silently ignore env vars that don't match declared fields


# Singleton instance
settings = Settings()
