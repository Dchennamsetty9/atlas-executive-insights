"""
databricks_connection.py
Lightweight connection module for Databricks SQL Warehouse.
Shared by data_fetcher and gaim_data_service.

Token priority (first non-empty wins):
  1. DATABRICKS_TOKEN   — injected automatically by Databricks Apps at runtime
  2. DATABRICKS_ACCESS_TOKEN — set in local .env for development
  3. settings.databricks_access_token — populated by pydantic-settings from .env
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

HOST      = os.getenv("DATABRICKS_SERVER_HOSTNAME") \
         or os.getenv("DATABRICKS_HOST", "goto-data-dock.cloud.databricks.com")
# Strip https:// prefix — the SDK expects a bare hostname
HOST = HOST.removeprefix("https://").removeprefix("http://").rstrip("/")
HTTP_PATH = os.getenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/c24ee33594e13e93")

# Maximum total time the SDK retry loop will run before giving up.
# Default is 900 s — far too long for a web request; cap at 12 s so a failed
# connection fails fast and the caller can fall back to demo data.
# On Databricks Apps (warm warehouse, local network) this is plenty.
_RETRY_TIMEOUT = 12.0


def _resolve_token() -> str:
    """
    Return the active Databricks PAT from any configured source.

    Priority:
      1. DATABRICKS_TOKEN env var  — set by Databricks Apps at runtime
      2. DATABRICKS_ACCESS_TOKEN env var — set in local .env (loaded by
         pydantic-settings when the Settings singleton is constructed)
      3. settings.databricks_access_token — direct pydantic-settings read
         (catches the case where pydantic-settings has the value but hasn't
         propagated it to os.environ, which is the default in v2)
    """
    token = os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN")
    if not token:
        try:
            from config.settings import settings  # lazy import to avoid circular deps
            token = settings.databricks_access_token
        except Exception:
            pass
    return token or ""


def token_available() -> bool:
    """Return True if any Databricks token source is configured."""
    return DATABRICKS_AVAILABLE and bool(_resolve_token())


def get_connection():
    """
    Return a live Databricks SQL connection.
    Raises RuntimeError if connector is not installed or no token is found.

    Connection parameters:
      _socket_timeout=10           — 10 s per individual socket operation
      _retry_stop_after_attempts_duration=30  — 30 s total retry budget
        (overrides SDK default of 900 s, which caused /api/kpis to hang)
    """
    if not DATABRICKS_AVAILABLE:
        raise RuntimeError(
            "databricks-sql-connector is not installed. "
            "Run: pip install databricks-sql-connector"
        )

    token = _resolve_token()
    if not token:
        raise RuntimeError(
            "No Databricks token found. Set DATABRICKS_TOKEN (production) or "
            "DATABRICKS_ACCESS_TOKEN in backend/.env (local dev)."
        )

    return sql.connect(
        server_hostname=HOST,
        http_path=HTTP_PATH,
        access_token=token,
        _socket_timeout=5,                       # 5 s per socket op — fail fast locally
        _retry_stop_after_attempts_duration=_RETRY_TIMEOUT,  # 12 s total retry budget
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
