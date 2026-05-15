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
    databricks_server_hostname: str = os.getenv("DATABRICKS_HOST", "")
    databricks_http_path: str = "/sql/1.0/warehouses/c24ee33594e13e93"
    databricks_access_token: str = os.getenv("DATABRICKS_TOKEN", "")
    # Using federated sales tables to avoid catalog permissions issues
    databricks_catalog: str = "federated"
    databricks_schema: str = "sales"
    
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
    
    # CORS origins - allow Databricks workspace domains
    cors_origins: List[str] = [
        "http://localhost:3000", 
        "http://localhost:5173",
        "https://*.cloud.databricks.com",  # Databricks Apps domain
        os.getenv("DATABRICKS_HOST", "")
    ]
    
    # Forecasting
    forecast_default_periods: int = 90
    forecast_confidence_interval: float = 0.95
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Singleton instance
settings = Settings()
