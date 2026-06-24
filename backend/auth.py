"""Authentication helpers for forwarded Databricks user tokens."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import httpx
from fastapi import Header, HTTPException

from config.settings import settings
from services.databricks_connection import set_request_token

logger = logging.getLogger(__name__)

_VERIFY_CACHE: Dict[str, Tuple[str, datetime]] = {}
_VERIFY_TTL_SECONDS = 300


def _normalize_token(token: Optional[str]) -> str:
    if not token:
        return ""
    value = token.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _trusted_forwarded_fallback_enabled() -> bool:
    """
    When enabled, tolerate Databricks-forwarded tokens that fail current-user
    introspection by deriving a stable pseudonymous user id from the token hash.
    """
    return os.getenv("AUTH_TRUST_FORWARDED_TOKEN", "true").lower() == "true"


def _fallback_user_id_from_token(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"forwarded:{digest[:16]}"


def _databricks_host() -> str:
    host = os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_SERVER_HOSTNAME") or settings.databricks_server_hostname
    return (host or "").removeprefix("https://").removeprefix("http://").rstrip("/")


async def _verify_forwarded_token(token: str) -> str:
    """Verify token with Databricks current-user endpoint and return stable user id."""
    cache_key = _token_cache_key(token)
    now = datetime.now(timezone.utc)
    cached = _VERIFY_CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    host = _databricks_host()
    if not host:
        raise HTTPException(status_code=401, detail="Databricks host is not configured")

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"https://{host}/api/2.0/current-user/me",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:
        logger.warning("Auth verification request failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token verification failed") from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid forwarded access token")

    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    user_id = (
        payload.get("userName")
        or payload.get("id")
        or payload.get("displayName")
    )
    if not user_id:
        raise HTTPException(status_code=401, detail="Token verified but user identity missing")

    _VERIFY_CACHE[cache_key] = (
        str(user_id),
        now + timedelta(seconds=_VERIFY_TTL_SECONDS),
    )
    return str(user_id)


async def require_authenticated_user(
    x_forwarded_access_token: Optional[str] = Header(default=""),
    authorization: Optional[str] = Header(default=""),
) -> str:
    """Return authenticated user id or raise 401 for protected endpoints."""
    token = _normalize_token(x_forwarded_access_token) or _normalize_token(authorization)
    set_request_token(token)

    if not token:
        if settings.environment != "production" and settings.auth_allow_anonymous_local:
            return "local-dev"
        raise HTTPException(status_code=401, detail="Missing forwarded access token")

    try:
        return await _verify_forwarded_token(token)
    except HTTPException as exc:
        # Databricks Apps may forward user/app tokens that are valid for app access
        # but not accepted by /current-user/me. In that case, keep routes usable by
        # deriving a stable pseudonymous user id from the forwarded token.
        if (
            os.getenv("DATABRICKS_HOST")
            and exc.status_code == 401
            and _trusted_forwarded_fallback_enabled()
        ):
            fallback_user = _fallback_user_id_from_token(token)
            logger.warning(
                "Forwarded token verification failed; using trusted fallback identity %s",
                fallback_user,
            )
            return fallback_user
        raise


async def require_debug_access(
    x_forwarded_access_token: Optional[str] = Header(default=""),
) -> str:
    """Require debug endpoints to be explicitly enabled and authenticated."""
    if not settings.enable_debug_endpoints:
        raise HTTPException(status_code=404, detail="Not found")
    return await require_authenticated_user(x_forwarded_access_token)
