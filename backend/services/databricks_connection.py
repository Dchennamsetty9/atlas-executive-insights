"""
databricks_connection.py
Lightweight connection module for Databricks SQL Warehouse.
Shared by data_fetcher and gaim_data_service.
"""

import logging
import os
import time
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    from databricks import sql
    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False

HOST      = os.getenv("DATABRICKS_SERVER_HOSTNAME", "goto-data-dock.cloud.databricks.com")
HTTP_PATH = os.getenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/c24ee33594e13e93")


def get_connection():
    """
    Return a live Databricks SQL connection.
    Uses DATABRICKS_TOKEN from environment (Personal Access Token).
    Raises RuntimeError if connector is not installed or token is missing.
    """
    if not DATABRICKS_AVAILABLE:
        raise RuntimeError(
            "databricks-sql-connector is not installed. "
            "Run: pip install databricks-sql-connector"
        )

    # Accept either DATABRICKS_TOKEN (preferred) or DATABRICKS_ACCESS_TOKEN (legacy .env key)
    token = os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "Neither DATABRICKS_TOKEN nor DATABRICKS_ACCESS_TOKEN is set. "
            "Export your Personal Access Token before starting the backend."
        )

    return sql.connect(
        server_hostname=HOST,
        http_path=HTTP_PATH,
        access_token=token,
        _socket_timeout=10,   # 10 s per socket op — fail fast so threads don't linger
    )


def execute_query(
    query: str,
    params=None,
    *,
    max_attempts: int = 1,   # No retries on hot-path; fail fast → demo data
    backoff: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Execute a SQL query and return results as a list of dicts.
    Opens a fresh connection per call (stateless helper).

    Transient connection/timeout errors are retried up to `max_attempts` times
    with exponential backoff (default: 3 attempts, 2 s base delay).

    Args:
        query:        SQL string (use ? placeholders for bound params if supported).
        params:       Optional list of parameter values.
        max_attempts: Total number of attempts before re-raising the error.
        backoff:      Base delay in seconds; actual delay = backoff * attempt_number.

    Returns:
        List of dicts, one per row, keyed by column name.
    """
    _TRANSIENT_SIGNALS = ("timeout", "connection", "reset", "unavailable", "retry", "refused", "broken pipe")

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    return [dict(zip(columns, row)) for row in rows]
        except Exception as exc:
            msg = str(exc).lower()
            is_transient = any(k in msg for k in _TRANSIENT_SIGNALS)
            if is_transient and attempt < max_attempts:
                wait = backoff * attempt
                logger.warning(
                    "Databricks transient error (attempt %d/%d); retrying in %.1fs — %s",
                    attempt, max_attempts, wait, exc,
                )
                time.sleep(wait)
                last_exc = exc
                continue
            raise  # Non-transient or final attempt — propagate immediately

    raise last_exc  # Unreachable unless max_attempts <= 0; satisfies type checker
