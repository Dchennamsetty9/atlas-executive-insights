"""
tests/test_forecast_v2_resilience.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Confirm that every /api/forecast/v2/* endpoint returns a 200 with
source="demo" when the underlying Databricks read raises an exception
(e.g. PERMISSION_DENIED on a table the app SP cannot access).

No live Databricks connection is required — execute_query is patched.
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Bootstrap the app the same way the test suite already does
# ---------------------------------------------------------------------------
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from bootstrap import app  # noqa: E402

client = TestClient(app)

_PERMISSION_ERROR = Exception("PERMISSION_DENIED: User does not have SELECT privilege on forecast_prophet")

# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

def _mock_execute_query_raises():
    """execute_query always raises — simulates a missing-grant scenario."""
    return patch(
        "routes.forecast_v2.execute_query",
        side_effect=_PERMISSION_ERROR,
    )


def _mock_live_true():
    """_live() returns True so endpoints attempt the real query path."""
    return patch("routes.forecast_v2._live", return_value=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestForecastV2Resilience:
    """All v2 endpoints degrade to 200+demo on DB failure, never 500."""

    def _get(self, path: str, params: dict = None):
        return client.get(path, params=params or {})

    def test_weekly_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/weekly", {"model": "prophet"})
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "demo"
        assert "error" in body
        assert "PERMISSION_DENIED" in body["error"]

    def test_weekly_ensemble_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/weekly", {"model": "ensemble"})
        assert r.status_code == 200
        assert r.json()["source"] == "demo"

    def test_monthly_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/monthly")
        assert r.status_code == 200
        assert r.json()["source"] == "demo"

    def test_ytd_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/ytd")
        assert r.status_code == 200
        assert r.json()["source"] == "demo"

    def test_by_product_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/by-product", {"model": "prophet"})
        assert r.status_code == 200
        assert r.json()["source"] == "demo"

    def test_historical_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/historical")
        assert r.status_code == 200
        assert r.json()["source"] == "demo"

    def test_leaderboard_returns_200_on_db_error(self):
        with _mock_live_true(), _mock_execute_query_raises():
            r = self._get("/api/forecast/v2/leaderboard")
        assert r.status_code == 200
        assert r.json()["source"] == "demo"

    def test_bad_model_returns_400(self):
        with _mock_live_true():
            r = self._get("/api/forecast/v2/weekly", {"model": "invalid_model"})
        assert r.status_code == 400

    def test_bad_forecast_type_returns_400(self):
        with _mock_live_true():
            r = self._get("/api/forecast/v2/weekly", {"model": "ensemble", "forecast_type": "bad_type"})
        assert r.status_code == 400
