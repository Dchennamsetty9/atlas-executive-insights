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
from contextvars import ContextVar

import pytest

# Bootstrap import path and service stubs for forecast_v2_impl imports.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

fake_services = types.ModuleType("services")
fake_db = types.ModuleType("services.databricks_connection")
fake_db.execute_query = lambda _sql: []
fake_db.token_available = lambda: False
fake_db.set_request_token = lambda _token: None
fake_db.query_cache_scope = lambda: None
fake_prefs = types.ModuleType("services.user_preferences_service")
fake_prefs.user_prefs_service = object()
fake_services.databricks_connection = fake_db
fake_services.user_preferences_service = fake_prefs
sys.modules.setdefault("services", fake_services)
sys.modules["services.databricks_connection"] = fake_db
sys.modules["services.user_preferences_service"] = fake_prefs

from routes import forecast_v2_impl as impl  # noqa: E402


def test_canonical_rows_exclude_actualized_forecasts_and_deduplicate():
    sql = impl._normalized_forecast_sql("ensemble", "roy", None, "ITSG", "NA", 2026)
    assert "Actuals IS NOT NULL" in sql
    assert "CAST(ds AS DATE) >" in sql
    assert "forecast_type IN ('rolling', 'roy')" in sql
    assert "PARTITION BY ds" in sql
    assert "product = 'ITSG'" in sql
    assert "SQRT" not in sql


def test_missing_periods_are_unavailable_not_zero():
    months = impl._fill_monthly_gaps([], 2026, True, True)
    assert len(months) == 12
    assert all(row["arr_actual"] is None and row["arr_likely"] is None for row in months)


def test_executive_metrics_do_not_invent_confidence_or_plan(monkeypatch):
    monkeypatch.setattr(impl, "execute_query", lambda sql: pytest.fail("Must not borrow portfolio data"))
    confidence = asyncio.run(impl.get_confidence(model="ets", product_line="ITSG", sales_market="NA", live_mode=True))
    bridge = asyncio.run(impl.get_driver_bridge(model="ets", product=None, product_line="ITSG", sales_market="NA", live_mode=True))
    assert confidence["confidence_score"] is None
    assert bridge["variance"] is None
    for result in (confidence, bridge):
        assert result["source"] == "unavailable"
        assert result["product"] == "ITSG"
        assert result["sales_market"] == "NA"


def test_intelligence_never_falls_back_to_unscoped_text(monkeypatch):
    calls = []
    async def query(sql, **kwargs):
        calls.append(sql)
        return []
    monkeypatch.setattr(impl, "_cached_query", query)
    regional = asyncio.run(impl.get_intelligence(product_line="ITSG", sales_market="NA", live_mode=True))
    assert regional["source"] == "unavailable" and calls == []
    product = asyncio.run(impl.get_intelligence(product_line="ITSG", live_mode=True))
    assert product["source"] == "unavailable"
    assert len(calls) == 1 and "product = 'ITSG'" in calls[0]


def test_risk_radar_scopes_product_region_and_actual_cutoff(monkeypatch):
    calls = []
    async def query(sql, **kwargs):
        calls.append((sql, kwargs))
        return []
    monkeypatch.setattr(impl, "_cached_query", query)
    asyncio.run(impl.get_risk_radar(forecast_type="roy", model="ensemble", year=2026,
        quarter=4, limit=20, product_line="ITSG", sales_market="NA", live_mode=True))
    sql, scope = calls[0]
    assert "product = 'ITSG'" in sql and "= 'NA'" in sql
    assert "actual.run_date = forecast.run_date" in sql
    assert "actual.product = forecast.product" in sql
    assert scope["product"] == "ITSG" and scope["geo"] == "NA"


@pytest.mark.parametrize("model", ["ensemble", "prophet", "ets"])
def test_canonical_queries_parse_as_databricks_sql(monkeypatch, model):
    import sqlglot
    queries = []
    async def query(sql, **kwargs):
        queries.append(sql)
        return []
    monkeypatch.setattr(impl, "_cached_query", query)
    options = dict(product=None, product_line="ITSG", sales_market="NA", model=model,
                   year=2026, quarter=4, forecast_type="rolling", live_mode=True)
    asyncio.run(impl.get_weekly(**options))
    asyncio.run(impl.get_monthly(**options))
    asyncio.run(impl.get_confidence_bands(**options))
    for sql in queries:
        assert "<<<<<<<" not in sql and ">>>>>>>" not in sql
        assert len(sqlglot.parse(sql, read="databricks")) == 1


def test_weekly_actuals_and_forecasts_reconcile_with_kpis(monkeypatch):
    async def query(sql, **kwargs):
        if kwargs["endpoint"] == "/_period_landings":
            return []
        if kwargs["forecast_type"] == "actuals":
            return [{"ds": "2026-09-07", "actual": 100, "forecast_type": "actuals", "publication_id": "2026-09-15"}]
        return [{"ds": "2026-09-07", "value": 999, "lower": 900, "upper": 1100, "publication_id": "2026-09-15"},
                {"ds": "2026-09-14", "value": 40, "lower": 30, "upper": 50, "publication_id": "2026-09-15"}]
    monkeypatch.setattr(impl, "_cached_query", query)
    result = asyncio.run(impl.get_weekly(product=None, product_line="UCC", sales_market=None,
        forecast_type="rolling", model="ensemble", year=2026, quarter=3, live_mode=True))
    assert len(result["rows"]) == 2
    assert result["kpis"] == {"most_likely": 140, "worst_case": 130, "best_case": 150, "ytd_actuals": 100}
    assert result["publication_id"] == "2026-09-15"


def test_monthly_history_failure_keeps_current_data(monkeypatch):
    async def query(sql, **kwargs):
        if kwargs["forecast_type"] == "prediction":
            raise RuntimeError("wide table unavailable")
        if kwargs["forecast_type"] == "actuals":
            return [{"yr": 2026, "qtr": 3, "mth": 9, "arr_actual": 100}]
        return [{"yr": 2026, "qtr": 3, "mth": 9, "arr_likely": 40, "arr_worst": 30, "arr_best": 50}]
    monkeypatch.setattr(impl, "_cached_query", query)
    result = asyncio.run(impl.get_monthly(product=None, product_line="UCC", sales_market=None,
        forecast_type="rolling", model="ensemble", year=2026, quarter=3, live_mode=True))
    month = next(row for row in result["months"] if row["month"] == 9)
    assert month["arr_actual"] == 100 and month["arr_likely"] == 40
    assert month["arr_predicted"] is None and month["accuracy"] is None
    assert result["historical_status"] == "Historical estimate unavailable for this publication"


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


@pytest.mark.parametrize("source,closed,quarter,count,status", [
    ("holdout_closed_quarter", True, "2026Q2", 1, "measured"),
    ("holdout_closed_quarter", False, "2026Q3", 1, "unverified"),
    ("holdout_closed_quarter", True, None, 1, "unverified"),
    ("holdout_closed_quarter", True, "2026Q2", 0, "unverified"),
    ("holdout_closed_quarter", True, "2026Q2", float("nan"), "unverified"),
    ("estimated_0.35x_weekly", False, None, 0, "estimated"),
    ("dollar_weighted_blend", False, None, 0, "blended"),
    ("unknown_method", True, "2026Q2", 1, "unverified"),
])
def test_quarterly_evidence_requires_measured_closed_quarter(source, closed, quarter, count, status):
    row = {"product": "UCC", "sales_market": "Total", "publication_date": "2026-09-09",
           **impl._leaderboard_error_values({"qtr_ensemble": 0})}
    record = {"product": "UCC", "model": "Adaptive_Ensemble", "quarterly_wape": 0,
              "run_date": "2026-09-09", "source": source, "quarter_label": quarter,
              "is_closed": closed, "quarters_evaluated": count}
    evidence = impl._quarterly_evidence(row, [record])
    assert evidence["Ensemble"]["status"] == status
    assert evidence["Ensemble"]["source"] == source
    assert evidence["ETS"]["status"] == "unavailable"


@pytest.mark.parametrize("override", [
    {"product": "ITSG"}, {"model": "ETS"}, {"run_date": "2026-09-08"},
    {"quarterly_wape": 99}, {"quarterly_wape": float("inf")},
])
def test_quarterly_evidence_does_not_borrow_mismatched_records(override):
    row = {"product": "UCC", "sales_market": "Total", "publication_date": "2026-09-09",
           **impl._leaderboard_error_values({"qtr_ensemble": 0.826})}
    record = {"product": "UCC", "model": "Adaptive_Ensemble", "quarterly_wape": 0.826,
              "run_date": "2026-09-09", "source": "holdout_closed_quarter", "quarter_label": "2026Q2",
              "is_closed": True, "quarters_evaluated": 1, **override}
    assert impl._quarterly_evidence(row, [record])["Ensemble"]["status"] == "unverified"


def test_quarterly_evidence_rejects_duplicate_and_regional_records():
    row = {"product": "UCC", "sales_market": "Total", "publication_date": "2026-09-09",
           **impl._leaderboard_error_values({"qtr_ensemble": 0.826})}
    record = {"product": "UCC", "model": "Adaptive_Ensemble", "quarterly_wape": 0.826,
              "run_date": "2026-09-09", "source": "holdout_closed_quarter", "quarter_label": "2026Q2",
              "is_closed": True, "quarters_evaluated": 1}
    assert impl._quarterly_evidence(row, [record, record])["Ensemble"]["status"] == "unverified"
    assert impl._quarterly_evidence({**row, "sales_market": "NA"}, [record])["Ensemble"]["status"] == "unverified"


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


def test_forecast_cache_isolates_callers_and_retains_same_caller_hits(monkeypatch):
    from routes import forecast_v2 as package

    caller = ContextVar("cache_test_caller", default="caller-a")
    calls = []

    def query(_sql):
        calls.append(caller.get())
        return [{"owner": caller.get()}]

    monkeypatch.setattr(package, "execute_query", query)
    monkeypatch.setattr(impl, "query_cache_scope", caller.get)
    monkeypatch.setattr(impl, "CACHE_TTL_SECONDS", 300)
    monkeypatch.setattr(impl, "_QUERY_CACHE", {})

    async def request_as(identity):
        caller.set(identity)
        return await impl._cached_query("SELECT private_data", endpoint="/monthly")

    for identity in ("caller-a", "caller-b", "caller-a", "caller-b"):
        result = asyncio.run(request_as(identity))
        assert result == [{"owner": identity}]
    assert calls == ["caller-a", "caller-b"]
    assert len(impl._QUERY_CACHE) == 2


def test_forecast_cache_without_identity_bypasses_storage(monkeypatch):
    from routes import forecast_v2 as package

    calls = []
    monkeypatch.setattr(package, "execute_query", lambda sql: calls.append(sql) or [])
    monkeypatch.setattr(impl, "query_cache_scope", lambda: None)
    monkeypatch.setattr(impl, "CACHE_TTL_SECONDS", 300)
    monkeypatch.setattr(impl, "_QUERY_CACHE", {})
    for _ in range(2):
        asyncio.run(impl._cached_query("SELECT 1", endpoint="/monthly"))
    assert len(calls) == 2
    assert impl._QUERY_CACHE == {}


def test_forecast_cache_expires_entries_and_limits_live_keys(monkeypatch):
    from routes import forecast_v2 as package

    cache = {f"existing-{index}": (100, []) for index in range(512)}
    cache["expired"] = (0, [])
    monkeypatch.setattr(package, "execute_query", lambda _sql: [{"fresh": True}])
    monkeypatch.setattr(impl, "query_cache_scope", lambda: "caller")
    monkeypatch.setattr(impl, "CACHE_TTL_SECONDS", 50)
    monkeypatch.setattr(impl.time, "time", lambda: 100)
    monkeypatch.setattr(impl, "_QUERY_CACHE", cache)
    result = asyncio.run(impl._cached_query("SELECT 1", endpoint="/monthly"))
    assert result == [{"fresh": True}]
    assert "expired" not in cache
    assert len(cache) == 512


def test_leaderboard_exposes_source_publication_without_inventing_missing_dates(monkeypatch):
    queries = []
    async def columns():
        return set()
    async def query(sql, **kwargs):
        queries.append(sql)
        if kwargs.get("metric") == "ensemble_realized_mape":
            return []
        return [
            {"product": "UCC", "sales_market": "Total", "publication_date": "2026-09-08", "qtr_ensemble": 0.826},
            {"product": "ITSG", "sales_market": "Total", "qtr_ensemble": 12.52},
        ]
    monkeypatch.setattr(impl, "_lb_columns", columns)
    monkeypatch.setattr(impl, "_cached_query", query)
    result = asyncio.run(impl.get_leaderboard(live_mode=True))
    assert "MAX(CAST(run_date AS STRING)) AS publication_date" in queries[0]
    assert result["data"][0]["publication_date"] == "2026-09-08"
    assert result["data"][1]["publication_date"] is None
    assert result["data"][0]["quarterly_errors"]["Ensemble"] == 0.826
    assert result["data"][0]["quarterly_provenance"]["Ensemble"]["status"] == "unverified"


@pytest.mark.parametrize("provenance_available", [True, False])
def test_leaderboard_serves_provenance_without_hiding_query_failure(monkeypatch, provenance_available):
    async def columns():
        return set()

    async def query(sql, **kwargs):
        if kwargs.get("metric") == "quarterly_provenance":
            assert "forecast_quarterly_accuracy" in sql
            assert kwargs["endpoint"] == "/leaderboard"
            if not provenance_available:
                raise RuntimeError("test missing metadata grant")
            return [{"product": "UCC", "model": "Adaptive_Ensemble", "quarterly_wape": 0.826,
                     "run_date": "2026-09-09", "source": "holdout_closed_quarter", "quarter_label": "2026Q2",
                     "is_closed": True, "quarters_evaluated": 1}]
        if kwargs.get("metric") == "ensemble_realized_mape":
            return []
        return [{"product": "UCC", "sales_market": "Total", "publication_date": "2026-09-09", "qtr_ensemble": 0.826}]

    monkeypatch.setattr(impl, "_lb_columns", columns)
    monkeypatch.setattr(impl, "_cached_query", query)
    result = asyncio.run(impl.get_leaderboard(live_mode=True))
    row = result["data"][0]
    assert row["quarterly_errors"]["Ensemble"] == 0.826
    assert row["quarterly_provenance"]["Ensemble"]["status"] == ("measured" if provenance_available else "unverified")


def test_rolling_next_year_filter_is_quarter_anchored():
    filt = impl._rolling_next_year_filter()
    assert "DATE_TRUNC('QUARTER', CURRENT_DATE())" in filt
    assert "ADD_MONTHS(CAST(DATE_TRUNC('QUARTER', CURRENT_DATE()) AS DATE), 12)" in filt
    assert "CAST(ds AS DATE) >=" in filt
    assert "CAST(ds AS DATE) <" in filt


def test_monthly_rolling_uses_all_periods_and_separates_actuals(monkeypatch):
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
    assert len(captured_sql) == 3

    forecast_sql = next(sql for sql in captured_sql if "arr_likely" in sql)
    actuals_sql = next(sql for sql in captured_sql if "AS arr_actual" in sql)
    predicted_sql = next(sql for sql in captured_sql if "AS arr_predicted" in sql)

    assert impl.FC_TABLE in forecast_sql
    assert "forecast_prophet" not in forecast_sql
    assert "forecast_type IN ('rolling', 'roy', 'forward_1yr')" in forecast_sql
    assert "WHERE forecast_type = 'actuals'" in actuals_sql
    assert impl.POWERBI_WIDE_TABLE in predicted_sql
    assert "SQRT" not in forecast_sql

    # Rolling full-year mode should use the quarter-anchored next-12-month window.
    assert "DATE_TRUNC('QUARTER', CURRENT_DATE())" in forecast_sql
    assert "ADD_MONTHS(CAST(DATE_TRUNC('QUARTER', CURRENT_DATE()) AS DATE), 12)" in forecast_sql

    assert "CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE))" in forecast_sql


@pytest.mark.parametrize("forecast_type,year_offset,expected", [
    ("rolling", 0, "forecast_type IN ('rolling', 'roy')"),
    ("rolling", 1, "forecast_type = 'forward_1yr'"),
    ("forward_1yr", 1, "forecast_type = 'forward_1yr'"),
    ("roy", 0, "forecast_type IN ('rolling', 'roy')"),
])
def test_monthly_selected_period_uses_publication_filter(monkeypatch, forecast_type, year_offset, expected):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)
    result = asyncio.run(impl.get_monthly(
        product=None, product_line="UCC", sales_market=None,
        forecast_type=forecast_type, model="ensemble",
        year=datetime.date.today().year + year_offset, quarter=None, live_mode=True,
    ))

    assert result["source"] == "live"
    forecast_sql = next(sql for sql in captured_sql if "AS arr_likely" in sql)
    assert f"AND {expected}" in forecast_sql
    assert impl._latest_run() in forecast_sql


def test_monthly_merges_actuals_predictions_and_remaining_forecast(monkeypatch):
    async def fake_cached_query(_sql, **kwargs):
        rows = {
            "actuals": [{"yr": 2026, "qtr": 3, "mth": 9, "month_name": "September", "arr_actual": 100}],
            "rolling": [{"yr": 2026, "qtr": 3, "mth": 9, "month_name": "September", "arr_likely": 40, "arr_worst": 30, "arr_best": 50}],
            "prediction": [{"yr": 2026, "qtr": 3, "mth": 9, "month_name": "September", "arr_predicted": 95, "arr_pred_worst": 90, "arr_pred_best": 110}],
        }
        return rows[kwargs["forecast_type"]]

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)
    result = asyncio.run(impl.get_monthly(
        product=None, product_line="UCC", sales_market=None,
        forecast_type="rolling", model="ensemble", year=None,
        quarter=None, live_mode=True,
    ))

    assert len(result["months"]) == 1
    month = result["months"][0]
    assert month["arr_actual"] == 100
    assert month["arr_likely"] == 40
    assert month["arr_predicted"] == 95
    assert month["arr_worst"] == 30
    assert month["arr_best"] == 50


def test_monthly_uses_wide_hindcast_for_primary_scenarios(monkeypatch):
    captured = {}

    async def fake_cached_query(sql, **kwargs):
        captured[kwargs["forecast_type"]] = sql
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)
    result = asyncio.run(impl.get_monthly(
        product=None, product_line=None, sales_market=None,
        forecast_type="rolling", model="ensemble", year=2026,
        quarter=None, live_mode=True,
    ))

    assert result["source"] == "live"
    prediction_sql = captured["prediction"]
    assert "arr_forecast_powerbi_wide" in prediction_sql
    assert "Adaptive_Ensemble_P25" in prediction_sql
    assert "Adaptive_Ensemble_P50" in prediction_sql
    assert "Adaptive_Ensemble_P75" in prediction_sql
    assert "product IN ('UCC', 'ITSG')" in prediction_sql


def test_monthly_prophet_uses_native_source_without_run_date(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)
    result = asyncio.run(impl.get_monthly(
        product=None, product_line="UCC", sales_market=None,
        forecast_type="rolling", model="prophet", year=2026,
        quarter=None, live_mode=True,
    ))

    assert result["source"] == "live"
    assert len(captured_sql) == 3
    for sql in captured_sql:
        assert impl.PROPHET_TABLE in sql
        assert "model_name = 'Prophet'" in sql
        assert "is_current = TRUE" in sql
        assert "run_date" not in sql


def test_monthly_quarter_without_year_uses_current_year(monkeypatch):
    captured_sql = []

    async def fake_cached_query(sql, **_kwargs):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)
    today = datetime.date.today()
    current_quarter = ((today.month - 1) // 3) + 1
    result = asyncio.run(impl.get_monthly(
        product=None, product_line="UCC", sales_market=None,
        forecast_type="rolling", model="ensemble", year=None,
        quarter=current_quarter, live_mode=True,
    ))

    assert result["source"] == "live"
    assert len(captured_sql) == 3
    assert all(str(today.year) in sql for sql in captured_sql)
    assert all(row["year"] == today.year for row in result["months"])
    assert len(result["months"]) == 3


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
    assert "forecast_p05" not in forecast_sql
    assert "forecast_p95" not in forecast_sql
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

    assert result["source"] == "unavailable"
    kpi_sql = captured_sql[2]
    assert "forecast_all_models" in kpi_sql
    assert "forecast_p50" in kpi_sql
    assert "model_name = 'Prophet'" in kpi_sql
    assert "is_current = TRUE" in kpi_sql
    assert "run_date" not in kpi_sql
    assert "LOWER(TRIM(CAST(forecast_type AS STRING))) <> 'actuals'" in kpi_sql
    assert "forecast_p05" not in kpi_sql
    assert "forecast_p95" not in kpi_sql
    assert result["kpis"] is None


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

    assert result["source"] == "unavailable"
    assert len(captured_sql) == 3
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
    assert sum(q["landing"] or 0 for q in result["quarters"]) == result["fy_landing"]
    assert result["quarters"][2]["status"] == "unavailable"
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

    assert result["source"] == "unavailable"
    assert result["p30"] is None and result["p70"] is None
    sql = captured_sql[0]
    assert "forecast_all_models" in sql
    assert "forecast_p05" not in sql
    assert "forecast_p50" in sql
    assert "forecast_p95" not in sql
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
        return [{"ds": "2026-10-05", "value": 100, "lower": 80, "upper": 120}]

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
        return [{"ds": "2027-01-04", "value": 100, "lower": 80, "upper": 120}]

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
        return [{"ds": "2026-10-05", "value": 100, "lower": 80, "upper": 120}]

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
    assert "forecast_type IN ('rolling', 'roy')" in forecast_sql
    assert result["p30"] == 80
    assert result["p70"] == 120
    assert "p10" not in result and "p90" not in result


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


@pytest.mark.parametrize("product", [None, "UCC", "ITSG"])
@pytest.mark.parametrize("model", ["prophet", "ensemble"])
def test_by_product_landing_respects_model_source_and_slice_cutoff(monkeypatch, product, model):
    captured = {}

    async def columns():
        return set()

    async def fake_cached_query(sql, **kwargs):
        captured[kwargs.get("metric")] = sql
        return []

    monkeypatch.setattr(impl, "_lb_columns", columns)
    monkeypatch.setattr(impl, "_cached_query", fake_cached_query)
    result = asyncio.run(impl.get_by_product(
        product=None, product_line=product, sales_market=None,
        model=model, forecast_type="rolling", year=None, quarter=None, live_mode=True,
    ))

    assert result["source"] == "live"
    for metric in ("product", "geo"):
        sql = captured[metric]
        assert "actual_rows.product = forecast_rows.product" in sql
        assert "actual_rows.sales_market" in sql and "forecast_rows.sales_market" in sql
        if model == "prophet":
            assert impl.PROPHET_TABLE in sql
            assert impl.FC_TABLE not in sql
            assert "run_date" not in sql
            assert "is_current = TRUE" in sql
            assert "model_name = 'Prophet'" in sql
            assert "forecast_p50" in sql
        else:
            assert impl.FC_TABLE in sql
            assert "run_date" in sql
            assert "forecast_type IN ('rolling', 'roy', 'forward_1yr')" in sql
    if model == "prophet" and product is None:
        assert "product = 'Total'" not in captured["geo"]
        assert "product IN ('UCC','ITSG')" in captured["geo"]
    else:
        assert f"product = '{product or 'Total'}'" in captured["geo"]
