"""
data_cache.py
In-memory TTL cache for KPI data.
Avoids hammering Databricks on every page load; data is refreshed at most
every `refresh_interval_minutes` minutes.

Usage
-----
    from services.data_cache import data_cache

    cached = data_cache.get("kpis:All:All:All")
    if cached is None:
        cached = await gaim_service.fetch_kpis(...)
        data_cache.set("kpis:All:All:All", cached)
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def kpi_cache_prefix(user_id, credential_scope, geo=None, channel=None, product=None):
    if not user_id or not credential_scope:
        return None
    identity = hashlib.sha256(json.dumps([user_id, credential_scope]).encode("utf-8")).hexdigest()
    prefix = f"kpis:{identity}:"
    if geo is not None:
        prefix += json.dumps([geo, channel, product], separators=(",", ":")) + ":"
    return prefix


def kpi_cache_key(user_id, credential_scope, start_date, end_date, geo, channel, product):
    prefix = kpi_cache_prefix(user_id, credential_scope, geo, channel, product)
    return prefix + json.dumps([start_date, end_date]) if prefix else None


class DataCache:
    def __init__(self, refresh_interval_minutes: int = 15):
        self.cache: Dict[str, Any] = {}
        self.last_refresh: Dict[str, datetime] = {}
        self.refresh_interval = timedelta(minutes=refresh_interval_minutes)

    def is_stale(self, key: str) -> bool:
        """Return True if the cached value is absent or older than refresh_interval."""
        if key not in self.last_refresh:
            return True
        return datetime.now(timezone.utc) - self.last_refresh[key] > self.refresh_interval

    def get(self, key: str) -> Optional[Any]:
        """Return cached value, or None if missing / stale."""
        if self.is_stale(key):
            self.invalidate(key)
            return None
        return self.cache.get(key)

    def set(self, key: str, data: Any) -> None:
        """Store a value and record the refresh timestamp."""
        now = datetime.now(timezone.utc)
        for stale_key in list(self.last_refresh):
            if now - self.last_refresh[stale_key] > self.refresh_interval:
                self.invalidate(stale_key)
        if key not in self.cache and len(self.cache) >= 512:
            self.invalidate(next(iter(self.cache)))
        self.cache[key] = data
        self.last_refresh[key] = now

    def invalidate(self, key: str) -> None:
        """Force the next read for this key to go to the database."""
        self.cache.pop(key, None)
        self.last_refresh.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        for key in list(self.cache):
            if key.startswith(prefix):
                self.invalidate(key)

    def invalidate_all(self) -> None:
        """Invalidate every cached entry (triggers full refresh on next request)."""
        self.cache.clear()
        self.last_refresh.clear()

    def last_refreshed_at(self, key: str) -> Optional[datetime]:
        """Return the UTC datetime of the last successful refresh, or None."""
        return self.last_refresh.get(key)

    def cache_age_seconds(self, key: str) -> Optional[float]:
        """Return how many seconds old the cached value is, or None if absent."""
        ts = self.last_refresh.get(key)
        if ts is None:
            return None
        return (datetime.now(timezone.utc) - ts).total_seconds()


# Default to the weekly published-snapshot cadence so dashboard reads stay stable
# across the entire forecast refresh cycle instead of re-querying every page load.
DEFAULT_WEEKLY_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60
DATA_REFRESH_INTERVAL_MINUTES = int(os.getenv("DATA_REFRESH_INTERVAL_MINUTES", "10080"))

# Prefer the explicit env override when provided; otherwise default to a 7-day
# snapshot window to match the weekly publication pattern used by forecast_v2.
if DATA_REFRESH_INTERVAL_MINUTES <= 0:
    DATA_REFRESH_INTERVAL_MINUTES = 10080

# Singleton used throughout the backend
data_cache = DataCache(refresh_interval_minutes=DATA_REFRESH_INTERVAL_MINUTES)
