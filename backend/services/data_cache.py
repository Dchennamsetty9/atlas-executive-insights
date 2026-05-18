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

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


class DataCache:
    def __init__(self, refresh_interval_minutes: int = 15):
        self.cache: Dict[str, Any] = {}
        self.last_refresh: Dict[str, datetime] = {}
        self.refresh_interval = timedelta(minutes=refresh_interval_minutes)

    def is_stale(self, key: str) -> bool:
        """Return True if the cached value is absent or older than refresh_interval."""
        if key not in self.last_refresh:
            return True
        return datetime.utcnow() - self.last_refresh[key] > self.refresh_interval

    def get(self, key: str) -> Optional[Any]:
        """Return cached value, or None if missing / stale."""
        if self.is_stale(key):
            return None
        return self.cache.get(key)

    def set(self, key: str, data: Any) -> None:
        """Store a value and record the refresh timestamp."""
        self.cache[key] = data
        self.last_refresh[key] = datetime.utcnow()

    def invalidate(self, key: str) -> None:
        """Force the next read for this key to go to the database."""
        self.last_refresh.pop(key, None)

    def invalidate_all(self) -> None:
        """Invalidate every cached entry (triggers full refresh on next request)."""
        self.last_refresh.clear()

    def last_refreshed_at(self, key: str) -> Optional[datetime]:
        """Return the UTC datetime of the last successful refresh, or None."""
        return self.last_refresh.get(key)

    def cache_age_seconds(self, key: str) -> Optional[float]:
        """Return how many seconds old the cached value is, or None if absent."""
        ts = self.last_refresh.get(key)
        if ts is None:
            return None
        return (datetime.utcnow() - ts).total_seconds()


# Singleton used throughout the backend
data_cache = DataCache(refresh_interval_minutes=15)
