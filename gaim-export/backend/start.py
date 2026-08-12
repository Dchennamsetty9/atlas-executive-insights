"""
Databricks Apps entry-point wrapper.

Reads DATABRICKS_APP_PORT (injected by Databricks Apps at runtime) so the
process binds to exactly the port the platform expects.  Falls back to the
PORT env var and then 8000 for local development.

The app.yaml command array calls:
    python backend/start.py
"""
import os
import uvicorn

port = int(
    os.environ.get("DATABRICKS_APP_PORT")
    or os.environ.get("PORT")
    or 8000
)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        app_dir="backend",
        # Reload is only safe in development; in Databricks Apps ENVIRONMENT=production
        reload=os.environ.get("ENVIRONMENT", "development") == "development",
    )
