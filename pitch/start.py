"""
Databricks Apps entry-point for the pitch presentation app.
Reads DATABRICKS_APP_PORT (injected by Databricks Apps at runtime).
"""
import os
import uvicorn

port = int(
    os.environ.get("DATABRICKS_APP_PORT")
    or os.environ.get("PORT")
    or 8001
)

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        app_dir=os.path.dirname(os.path.abspath(__file__)),
        reload=False,
    )
