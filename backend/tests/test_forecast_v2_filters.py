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


def test_quarterly_badges_preserve_zero_and_published_precision():
    values = impl._leaderboard_error_values({
        "qtr_ensemble": 0, "mape_ensemble": 17.8,
        "qtr_ets": 8.745, "mape_ets": 28,
    })
    assert values["Ensemble"] == 0
    assert values["quarterly_errors"]["Ensemble"] == 0
    assert values["quarterly_errors"]["ETS"] == 8.745


def test_weekly_fallback_is_not_exposed_as_quarterly_error():
    values = impl._leaderboard_error_values({"mape_ets": 28})
    assert values["ETS"] == 28
    assert values["quarterly_errors"]["ETS"] is None
    assert all(value is None for value in values["quarterly_errors"].values())
    assert "Ensemble" not in values


def test_backtest_unsupported_scopes_never_query_or_substitute_history(monkeypatch):
    def forbidden_query(_sql):
        raise AssertionError("Unsupported scopes must not query a different product or model")
    monkeypatch.setattr(impl, "execute_query", forbidden_query)
    for product, market, model, live, expected in [
        (None, None, "ensemble", True, "combined_history_unverified"),
        ("UCC", "NA", "ensemble", True, "region_history_unverified"),
        ("ITSG", None, "prophet", True, "model_history_unverified"),
        ("UCC", None, "ensemble", False, "source_unavailable"),
    ]:
        result = asyncio.run(impl.get_backtest(horizon_weeks=4, model=model,
            product_line=product, sales_market=market, live_mode=live))
        assert result["source"] == "unavailable" and result["rows"] == []
        assert result["reason"] == expected


def test_backtest_itsg_uses_only_itsg_sources_and_no_empty_fallback(monkeypatch):
    queries = []
    monkeypatch.setattr(impl, "execute_query", lambda sql: queries.append(sql) or [])
    result = asyncio.run(impl.get_backtest(horizon_weeks=4, model="ensemble",
        product_line="ITSG", live_mode=True))
    assert len(queries) == 1
    assert "itsg_forecast_vintages" in queries[0] and "itsg_forecast_cbe" in queries[0]
    assert "ucc_" not in queries[0] and "accuracy_history" not in queries[0]
    assert result["reason"] == "no_matched_history" and result["rows"] == []


def test_backtest_query_error_returns_no_demo_or_raw_error(monkeypatch):
    def failed_query(_sql):
        raise RuntimeError("private SQL details")
    monkeypatch.setattr(impl, "execute_query", failed_query)
    result = asyncio.run(impl.get_backtest(horizon_weeks=4, model="ensemble",
        product_line="UCC", live_mode=True))
    assert result["reason"] == "source_query_failed" and result["rows"] == []
    assert "private SQL" not in str(result)


def test_accuracy_reads_bypass_daily_cache_for_new_publications(monkeypatch):
    from routes import forecast_v2 as package
    calls = []
    def query(sql):
        calls.append(sql)
        return [{"publication": len(calls)}]
    monkeypatch.setattr(package, "execute_query", query)
    monkeypatch.setattr(impl, "CACHE_TTL_SECONDS", 86400)
    monkeypatch.setattr(impl, "_QUERY_CACHE", {})
    for endpoint in ("/leaderboard", "/leaderboard/columns"):
        first = asyncio.run(impl._cached_query("SELECT 1", endpoint=endpoint))
        second = asyncio.run(impl._cached_query("SELECT 1", endpoint=endpoint))
        assert first != second  # A newly published run is visible without a restart.
    assert len(calls) == 4
    assert impl._QUERY_CACHE == {}


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


def test_prophet_source_uses_forecast_all_models_without_run_date():
    source = impl._model_source("prophet")
    assert source["table"] == impl.PROPHET_TABLE
    assert source["most_likely_col"] == "forecast_p50"
    assert source["has_forecast_type"] is True
    assert source["no_run_date"] is True
    assert source["model_filter"] == "model_name = 'Prophet'"

    forecast_sql = impl._normalized_forecast_sql(
        model="prophet",
        forecast_type="rolling",
        product=None,
        product_line="UCC",
        sales_market="NA",
        year=datetime.date.today().year,
    )

    assert "forecast_all_models" in forecast_sql
    assert "forecast_p50" in forecast_sql
    assert "forecast_p05" in forecast_sql
    assert "forecast_p95" in forecast_sql
    assert "SUM(COALESCE(CAST(forecast_p50 AS DOUBLE), 0)) AS value" in forecast_sql
    assert "GROUP BY ds, forecast_type" in forecast_sql
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) <> 'actuals'" in forecast_sql
    assert "model_name = 'Prophet'" in forecast_sql
    assert "is_current = TRUE" in forecast_sql
    assert "run_date" not in forecast_sql
    assert "product = 'UCC'" in forecast_sql
    assert "sales_market" in forecast_sql


def test_prophet_weekly_kpis_use_forecast_prophet_without_run_date(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_weekly(
            product=None,
            product_line="UCC",
            sales_market="NA",
            forecast_type="rolling",
            model="prophet",
            year=datetime.date.today().year,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    kpi_sql = captured_sql[2]
    assert "forecast_all_models" in kpi_sql
    assert "forecast_p50" in kpi_sql
    assert "model_name = 'Prophet'" in kpi_sql
    assert "is_current = TRUE" in kpi_sql
    assert "run_date" not in kpi_sql
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) <> 'actuals'" in kpi_sql
    assert "THEN NULL ELSE CAST(forecast_p50 AS DOUBLE) END AS Most_Likely" in kpi_sql
    assert "THEN NULL ELSE CAST(forecast_p05 AS DOUBLE) END AS Worst_Case" in kpi_sql
    assert "THEN NULL ELSE CAST(forecast_p95 AS DOUBLE) END AS Best_Case" in kpi_sql


def test_prophet_weekly_all_regions_uses_total_market_rollup(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_weekly(
            product=None,
            product_line="UCC",
            sales_market=None,
            forecast_type="rolling",
            model="prophet",
            year=datetime.date.today().year,
            quarter=3,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    assert len(captured_sql) == 4
    assert all("forecast_all_models" in sql for sql in captured_sql)
    assert all("product = 'UCC'" in sql for sql in captured_sql)
    assert all("sales_market" in sql for sql in captured_sql)
    assert all("= 'Total'" in sql for sql in captured_sql)


def test_period_landings_reconciles_quarters_and_fy(monkeypatch):
    async def fake_cached_query(sql, **_kwargs):
        assert "forecast_all_models" in sql
        assert "SUM(CASE" in sql
        return [
            {"qtr": 1, "actual": 100.0, "forecast": 0.0, "landing": 100.0, "worst": 100.0, "best": 100.0},
            {"qtr": 2, "actual": 40.0, "forecast": 60.0, "landing": 100.0, "worst": 90.0, "best": 110.0},
        ]

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl._period_landings(
            source=impl._model_source("prophet"),
            product=None,
            product_line="UCC",
            sales_market=None,
            year=datetime.date.today().year,
        )
    )

    assert result["fy_landing"] == 200
    assert sum(q["landing"] for q in result["quarters"]) == result["fy_landing"]
    assert result["quarters"][0]["landing"] == result["quarters"][0]["actual"] + result["quarters"][0]["forecast"]
    assert result["quarters"][1]["landing"] == result["quarters"][1]["actual"] + result["quarters"][1]["forecast"]


def test_summary_kpis_counts_prophet_forecast_type_rows():
    kpis = impl._summary_kpis([
        {"forecast_type": "actuals", "Actuals": 100, "Most_Likely": None, "Worst_Case": None, "Best_Case": None},
        {"forecast_type": "forecast", "Actuals": None, "Most_Likely": 50, "Worst_Case": 40, "Best_Case": 60},
    ])

    assert kpis["most_likely"] == 150
    assert kpis["worst_case"] == 140
    assert kpis["best_case"] == 160
    assert kpis["ytd_actuals"] == 100


def test_prophet_ytd_uses_forecast_prophet_without_forecast_type(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_ytd(
            product=None,
            product_line="UCC",
            sales_market="NA",
            forecast_type="rolling",
            model="prophet",
            year=datetime.date.today().year,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    assert len(captured_sql) == 2
    assert all("forecast_all_models" in sql for sql in captured_sql)
    assert all("model_name = 'Prophet'" in sql for sql in captured_sql)
    assert all("is_current = TRUE" in sql for sql in captured_sql)
    assert all("run_date" not in sql for sql in captured_sql)
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) = 'actuals'" in captured_sql[0]
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) <> 'actuals'" in captured_sql[1]


def test_prophet_confidence_bands_use_native_interval_columns(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_confidence_bands(
            product=None,
            product_line="UCC",
            sales_market="NA",
            forecast_type="rolling",
            model="prophet",
            year=datetime.date.today().year,
            quarter=None,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    sql = captured_sql[0]
    assert "forecast_all_models" in sql
    assert "forecast_p05" in sql
    assert "forecast_p50" in sql
    assert "forecast_p95" in sql
    assert "model_name = 'Prophet'" in sql
    assert "is_current = TRUE" in sql
    assert "run_date" not in sql
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) <> 'actuals'" in sql


def test_prophet_historical_uses_forecast_prophet_actuals(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)

    result = asyncio.run(
        impl.get_historical(
            product=None,
            product_line="ITSG",
            sales_market="EMEA",
            model="prophet",
            year=datetime.date.today().year,
            live_mode=True,
        )
    )

    assert result["source"] == "live"
    sql = captured_sql[0]
    assert "forecast_all_models" in sql
    assert "actuals" in sql
    assert "model_name = 'Prophet'" in sql
    assert "is_current = TRUE" in sql
    assert "run_date" not in sql
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) = 'actuals'" in sql


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
