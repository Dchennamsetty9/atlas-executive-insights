"""
databricks_connection.py
Lightweight connection module for Databricks SQL Warehouse.
Shared by data_fetcher and gaim_data_service.

Auth priority (first usable wins):
    1. Databricks SDK auto-discovery (Apps service principal)
    2. Request/user token via x-forwarded-access-token
    3. PAT via DATABRICKS_TOKEN / DATABRICKS_ACCESS_TOKEN
    4. OAuth M2M via DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET
"""

import hashlib
import json
import logging
import os
import time
from contextvars import ContextVar
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    from databricks import sql
    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False

try:
    from databricks.sdk.core import Config as _SdkConfig
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

HOST      = os.getenv("DATABRICKS_SERVER_HOSTNAME") \
         or os.getenv("DATABRICKS_HOST", "goto-data-dock.cloud.databricks.com")
# Strip https:// prefix — the SDK expects a bare hostname
HOST = HOST.removeprefix("https://").removeprefix("http://").rstrip("/")
HTTP_PATH = os.getenv("DATABRICKS_SQL_WAREHOUSE_PATH") \
         or os.getenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/c24ee33594e13e93")

# Maximum total time the SDK retry loop will run before giving up.
# Default is 900 s — far too long for an interactive request. Keep a generous
# interactive default for cold warehouses, but allow deployments to override it.
_RETRY_TIMEOUT = float(os.getenv("DATABRICKS_QUERY_TIMEOUT_SECONDS", "45"))

# Per-request token (set by inject_forwarded_token middleware in main.py).
# Databricks Apps forwards the active user's OAuth token as
# x-forwarded-access-token on every request; capturing it here allows all
# downstream SQL calls within that request to run as the user rather than
# as the app's service account.
_request_token: ContextVar[str] = ContextVar("_request_token", default="")


def set_request_token(token: str) -> None:
    """Called by the request middleware to store the forwarded user token."""
    _request_token.set(token)


def _resolve_token() -> str:
    """
    Return the active Databricks PAT from any configured source.

    Priority:
      1. Per-request ContextVar   — set by middleware from x-forwarded-access-token
         (Databricks Apps user identity passthrough)
      2. DATABRICKS_TOKEN env var  — injected by Databricks Apps service account
      3. DATABRICKS_ACCESS_TOKEN env var — set in local .env (loaded by
         pydantic-settings when the Settings singleton is constructed)
      4. settings.databricks_access_token — direct pydantic-settings read
    """
    tok = _request_token.get()
    if tok:
        return tok
    token = os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN")
    if not token:
        try:
            from config.settings import settings  # lazy import to avoid circular deps
            token = settings.databricks_access_token
        except Exception:
            pass
    return token or ""


def _oauth_m2m_available() -> bool:
    """Return True when service-principal OAuth credentials are configured."""
    return bool(os.environ.get("DATABRICKS_CLIENT_ID") and os.environ.get("DATABRICKS_CLIENT_SECRET"))


def _sdk_credentials_provider():
    """Return (access_token, hostname) via the Databricks SDK, or (None, None).

    In Databricks Apps the SDK auto-discovers the service-principal credentials
    injected by the runtime, eliminating the need for a static DATABRICKS_TOKEN
    or explicit M2M secrets.  Returns a fresh bearer token string rather than
    a credentials_provider callable — this avoids the 'dict' object is not
    callable incompatibility between SDK 0.140+ and sql-connector 4.x.
    """
    if not _SDK_AVAILABLE:
        return None, None
    try:
        cfg = _SdkConfig()
        try:
            headers = cfg.authenticate()
        except TypeError:
            headers = {}
            cfg.authenticate(headers)
        auth_value = headers.get("Authorization", "")
        if not auth_value:
            return None, None
        token = auth_value.removeprefix("Bearer ").strip()
        if not token:
            return None, None
        host = (cfg.host or "").removeprefix("https://").removeprefix("http://").rstrip("/")
        return token, host
    except Exception:
        return None, None


def token_available() -> bool:
    """Return True if PAT/user-token, OAuth M2M, or SDK auto-auth is configured."""
    if not DATABRICKS_AVAILABLE:
        return False
    if os.environ.get("GAIM_SQL_PAT") or bool(_resolve_token()) or _oauth_m2m_available():
        return True
    provider, _ = _sdk_credentials_provider()
    return provider is not None


def query_cache_scope() -> str | None:
    token = os.environ.get("GAIM_SQL_PAT") or _resolve_token()
    if token:
        credentials = ("token", token)
    elif _oauth_m2m_available():
        credentials = ("oauth-m2m", os.environ["DATABRICKS_CLIENT_ID"], os.environ["DATABRICKS_CLIENT_SECRET"])
    elif _sdk_credentials_provider()[0] is not None:
        credentials = ("sdk-auto",)
    else:
        return None
    identity = json.dumps((HOST, HTTP_PATH, credentials)).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


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

    # 1. Explicit PAT from secret scope — GAIM_SQL_PAT avoids the reserved
    #    DATABRICKS_TOKEN name that the Apps runtime may overwrite.
    explicit_pat = os.environ.get("GAIM_SQL_PAT") or os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN")
    if explicit_pat:
        return sql.connect(
            server_hostname=HOST,
            http_path=HTTP_PATH,
            access_token=explicit_pat,
            _socket_timeout=10,
            _retry_stop_after_attempts_duration=_RETRY_TIMEOUT,
        )

    # 2. Forwarded user token (x-forwarded-access-token from Apps proxy)
    forwarded = _request_token.get()
    if forwarded:
        return sql.connect(
            server_hostname=HOST,
            http_path=HTTP_PATH,
            access_token=forwarded,
            _socket_timeout=10,
            _retry_stop_after_attempts_duration=_RETRY_TIMEOUT,
        )

    # 3. SDK auto-discovery (app service principal — last resort)
    sdk_token, sdk_host = _sdk_credentials_provider()
    if sdk_token:
        return sql.connect(
            server_hostname=sdk_host or HOST,
            http_path=HTTP_PATH,
            access_token=sdk_token,
            _socket_timeout=10,
            _retry_stop_after_attempts_duration=_RETRY_TIMEOUT,
        )

    if _oauth_m2m_available():
        return sql.connect(
            server_hostname=HOST,
            http_path=HTTP_PATH,
            auth_type="oauth-m2m",
            oauth_client_id=os.environ.get("DATABRICKS_CLIENT_ID"),
            oauth_client_secret=os.environ.get("DATABRICKS_CLIENT_SECRET"),
            _socket_timeout=10,
            _retry_stop_after_attempts_duration=_RETRY_TIMEOUT,
        )

    raise RuntimeError(
        "No Databricks credentials found. Set DATABRICKS_TOKEN / DATABRICKS_ACCESS_TOKEN "
        "or DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET."
    )


def execute_query(
    query: str,
    params=None,
    *,
    max_attempts: int = 2,   # Retry once on cold-start failures (was 1)
    backoff: float = 3.0,
    max_rows: int | None = None,
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
        max_rows:     Optional positive bound on fetched rows; callers must also
                  constrain SQL when a server-side result limit is required.

    Returns:
        List of dicts, one per row, keyed by column name.
    """
    if max_rows is not None and (not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows <= 0):
        raise ValueError("max_rows must be a positive integer")
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
                    rows = cursor.fetchmany(max_rows) if max_rows is not None else cursor.fetchall()
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
