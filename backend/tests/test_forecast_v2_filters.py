"""
tests/test_forecast_v2_filters.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Focused regression tests for rolling forecast date-window behavior.
"""

import asyncio
import datetime
import pathlib
import sys
import types

# Bootstrap import path and service stubs for forecast_v2_impl imports.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

fake_services = types.ModuleType("services")
fake_db = types.ModuleType("services.databricks_connection")
fake_db.execute_query = lambda _sql: []
fake_db.token_available = lambda: False
fake_db.set_request_token = lambda _token: None
fake_prefs = types.ModuleType("services.user_preferences_service")
fake_prefs.user_prefs_service = object()
fake_services.databricks_connection = fake_db
fake_services.user_preferences_service = fake_prefs
sys.modules.setdefault("services", fake_services)
sys.modules["services.databricks_connection"] = fake_db
sys.modules["services.user_preferences_service"] = fake_prefs

from routes import forecast_v2_impl as impl  # noqa: E402


def test_rolling_next_year_filter_is_quarter_anchored():
    filt = impl._rolling_next_year_filter()
    assert "DATE_TRUNC('QUARTER', CURRENT_DATE())" in filt
    assert "ADD_MONTHS(CAST(DATE_TRUNC('QUARTER', CURRENT_DATE()) AS DATE), 12)" in filt
    assert "CAST(ds AS DATE) >=" in filt
    assert "CAST(ds AS DATE) <" in filt


def test_monthly_rolling_uses_rolling_window_and_full_month_forecast(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_monthly(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="rolling",
            model="ensemble",
            year=None,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    assert result["months"] == []
    assert len(captured_sql) == 2  # actuals query + forecast query

    forecast_sql = next(sql for sql in captured_sql if "arr_likely" in sql)

    assert "forecast_results_v2compat" in forecast_sql
    assert "forecast_prophet" not in forecast_sql
    assert "forecast_type IN ('actuals', 'rolling', 'roy')" in forecast_sql

    # Rolling full-year mode should use the quarter-anchored next-12-month window.
    assert "DATE_TRUNC('QUARTER', CURRENT_DATE())" in forecast_sql
    assert "ADD_MONTHS(CAST(DATE_TRUNC('QUARTER', CURRENT_DATE()) AS DATE), 12)" in forecast_sql

    # Monthly table must keep full-month forecasts (not splice to remaining weeks only).
    assert "CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE))" not in forecast_sql


def test_forward_1yr_is_not_aliased_for_forecast_type_sources():
    assert impl._validate_forecast_type("forward_1yr") == "forward_1yr"
    assert impl._effective_forecast_type("ensemble", "forward_1yr") == "forward_1yr"


def test_monthly_clause_for_current_year_rolling_uses_rolling_and_roy():
    current_year = datetime.date.today().year
    clause = impl._monthly_forecast_type_condition(
        forecast_type="rolling",
        rolling_next_year=False,
        selected_year=current_year,
    )
    assert clause == "forecast_type IN ('rolling', 'roy')"


def test_monthly_clause_for_explicit_future_year_uses_forward_1yr_only():
    future_year = datetime.date.today().year + 1
    clause = impl._monthly_forecast_type_condition(
        forecast_type="rolling",
        rolling_next_year=False,
        selected_year=future_year,
    )
    assert clause == "forecast_type = 'forward_1yr'"


def test_ytd_rolling_uses_disjoint_forecast_types_for_next_year_window(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_ytd(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="rolling",
            model="ensemble",
            year=None,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    forecast_sql = next(sql for sql in captured_sql if "SUM(COALESCE(CAST(" in sql and "likely" in sql)
    assert "forecast_type IN ('rolling', 'roy', 'forward_1yr')" in forecast_sql


def test_ytd_future_year_rolling_uses_forward_1yr_only(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_ytd(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="rolling",
            model="ensemble",
            year=datetime.date.today().year + 1,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    forecast_sql = next(sql for sql in captured_sql if "SUM(COALESCE(CAST(" in sql and "likely" in sql)
    assert "forecast_type = 'forward_1yr'" in forecast_sql


def test_ytd_full_year_includes_rolling_and_roy(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_ytd(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="roy",
            model="ensemble",
            year=datetime.date.today().year,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    forecast_sql = next(sql for sql in captured_sql if "SUM(COALESCE(CAST(" in sql and "likely" in sql)
    assert "forecast_type IN ('rolling', 'roy')" in forecast_sql
    assert "forecast_type = 'roy'" not in forecast_sql


def test_ytd_forecast_path_starts_at_last_actual(monkeypatch):
    async def fake_cached_query(_sql, **kwargs):
        if kwargs.get("forecast_type") == "actuals":
            return [
                {"d": "2026-01-05", "arr": 100.0},
                {"d": "2026-01-12", "arr": 200.0},
            ]
        return [
            {"d": "2026-01-26", "worst": 40.0, "likely": 50.0, "best": 60.0},
        ]

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_ytd(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="roy",
            model="ensemble",
            year=2026,
            quarter=None,
            live_mode=True,
        )
    )

    rows = {row["date"]: row for row in result["rows"]}
    assert rows["2026-01-12"]["ytd_actual"] == 300
    assert rows["2026-01-12"]["ytd_likely"] == 300
    assert rows["2026-01-19"]["ytd_likely"] is None
    assert rows["2026-01-26"]["ytd_likely"] == 350


def test_confidence_bands_full_year_includes_rolling_and_roy(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_confidence_bands(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="roy",
            model="ensemble",
            year=datetime.date.today().year,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    forecast_sql = captured_sql[0]
    assert "forecast_type IN ('rolling', 'roy')" in forecast_sql
    assert "forecast_type = 'roy'" not in forecast_sql


def test_confidence_bands_future_year_uses_forward_1yr_only(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_confidence_bands(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="rolling",
            model="ensemble",
            year=datetime.date.today().year + 1,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    forecast_sql = captured_sql[0]
    assert "forecast_type = 'forward_1yr'" in forecast_sql


def test_confidence_bands_quarter_uses_effective_forecast_type(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_confidence_bands(
            product=None,
            product_line=None,
            sales_market=None,
            forecast_type="rolling",
            model="ensemble",
            year=datetime.date.today().year,
            quarter=4,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    forecast_sql = captured_sql[0]
    assert "forecast_type = 'rolling'" in forecast_sql
    assert "forecast_type IN ('rolling', 'roy')" not in forecast_sql


def test_by_product_rolling_uses_all_future_periods(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_by_product(
            product=None,
            product_line=None,
            sales_market=None,
            model="ensemble",
            forecast_type="rolling",
            year=None,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    landing_sql = next(sql for sql in captured_sql if "UNION ALL" in sql and "forecast_type" in sql)
    assert "forecast_type IN ('rolling', 'roy', 'forward_1yr')" in landing_sql
