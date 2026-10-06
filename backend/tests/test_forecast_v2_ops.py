"""
Health endpoint, snapshot-keyed cache, Model Lab (snapshot unpivot) and the
snapshot column allow-list (schema) tests for forecast v2.
"""

import asyncio
import datetime
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

fake_services = types.ModuleType("services")
fake_services.__path__ = [str(pathlib.Path(__file__).parent.parent / "services")]
fake_db = types.ModuleType("services.databricks_connection")
fake_db.DATABRICKS_AVAILABLE = False
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
from routes import forecast_v2 as package  # noqa: E402

REAL_SNAPSHOT_TOKEN = impl._snapshot_token


@pytest.fixture(autouse=True)
def _reset_cache_state(monkeypatch):
    monkeypatch.setattr(impl, "_QUERY_CACHE", {})
    monkeypatch.setattr(impl, "_SNAPSHOT_TOKEN", None)
    monkeypatch.setattr(impl, "_SNAPSHOT_TOKEN_INFLIGHT", None)


# --------------------------------------------------------------------------
# Item 1: health + ERROR logging
# --------------------------------------------------------------------------

def _health_query_factory(latest, counts, columns):
    async def query(sql, endpoint=None, **kwargs):
        if "SHOW COLUMNS" in sql:
            if columns is None:
                raise RuntimeError("boom")
            return [{"col_name": c} for c in columns]
        if "AS latest_run_date" in sql:
            return [{"latest_run_date": latest}]
        return counts
    return query


def test_health_ok(monkeypatch):
    today = datetime.date.today().isoformat()
    counts = [{"product": "UCC", "row_count": 13, "forecast_rows": 5},
              {"product": "ITSG", "row_count": 13, "forecast_rows": 5}]
    monkeypatch.setattr(impl, "_cached_query",
                        _health_query_factory(today, counts, ["ds", "p25", "p50", "p75"]))
    out = asyncio.run(impl.get_health(strict=False, live_mode=True))
    assert out["status"] == "ok" and out["problems"] == []
    assert out["latest_run_date"] == today and out["columns"]["missing"] == []


def test_health_degraded_on_missing_column_and_logs_error(monkeypatch, caplog):
    today = datetime.date.today().isoformat()
    counts = [{"product": "UCC", "row_count": 1, "forecast_rows": 1}]  # ITSG missing
    monkeypatch.setattr(impl, "_cached_query",
                        _health_query_factory(today, counts, ["ds", "p25", "p75"]))
    with caplog.at_level("ERROR"):
        out = asyncio.run(impl.get_health(strict=False, live_mode=True))
    assert out["status"] == "degraded"
    assert out["columns"]["missing"] == ["p50"]
    assert any("ITSG" in p for p in out["problems"])
    assert any(r.levelname == "ERROR" and "forecast/health" in r.message for r in caplog.records)


def test_health_never_raises_and_strict_returns_503(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("down")
    monkeypatch.setattr(impl, "_cached_query", boom)
    out = asyncio.run(impl.get_health(strict=False, live_mode=True))
    assert out["status"] == "degraded"
    resp = asyncio.run(impl.get_health(strict=True, live_mode=True))
    assert resp.status_code == 503
    assert asyncio.run(impl.get_health(strict=False, live_mode=False))["status"] == "degraded"


def test_health_route_registered():
    paths = {r.path for r in package.router.routes}
    assert "/api/forecast/v2/health" in paths
    assert impl._is_live_only_endpoint("/health") and impl._effective_cache_ttl("/health") == 0


def test_masked_live_failure_logs_error(monkeypatch, caplog):
    async def boom(*_a, **_k):
        raise RuntimeError("Unresolved column p30")
    monkeypatch.setattr(impl, "_cached_query", boom)
    with caplog.at_level("WARNING"):
        out = asyncio.run(impl.get_ytd(live_mode=True, product=None, product_line=None,
                                       sales_market=None, forecast_type="forecast",
                                       model="ensemble", year=None, quarter=None))
    assert out["source"] == "unavailable"
    assert any(r.levelname == "ERROR" and "p30" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------
# Item 5: cache invalidation on a new publication
# --------------------------------------------------------------------------

def test_new_run_date_invalidates_cached_entries(monkeypatch):
    state = {"run": "2026-09-29", "data_calls": 0}

    def execute(sql):
        if "AS run_date FROM" in sql and "MAX(run_date)" in sql and "SELECT CAST(MAX" in sql:
            return [{"run_date": state["run"]}]
        state["data_calls"] += 1
        return [{"v": state["run"]}]

    monkeypatch.setattr(package, "execute_query", execute)
    monkeypatch.setattr(impl, "query_cache_scope", lambda: "caller")
    monkeypatch.setattr(impl, "_snapshot_token", REAL_SNAPSHOT_TOKEN)
    monkeypatch.setattr(impl, "SNAPSHOT_TOKEN_TTL_SECONDS", 300)

    now = [1000.0]
    monkeypatch.setattr(impl.time, "time", lambda: now[0])

    q = lambda: asyncio.run(impl._cached_query("SELECT data", endpoint="/weekly"))
    assert q() == [{"v": "2026-09-29"}]
    assert q() == [{"v": "2026-09-29"}] and state["data_calls"] == 1  # cache hit

    state["run"] = "2026-10-06"           # pipeline re-run publishes
    assert q() == [{"v": "2026-09-29"}]   # token still inside its brief TTL
    now[0] += 301                         # token re-checked
    assert q() == [{"v": "2026-10-06"}] and state["data_calls"] == 2
    assert q() == [{"v": "2026-10-06"}] and state["data_calls"] == 2


def test_snapshot_token_failure_is_safe_and_shared(monkeypatch):
    calls = []

    def execute(sql):
        calls.append(sql)
        raise RuntimeError("no access")

    monkeypatch.setattr(package, "execute_query", execute)

    async def run():
        return await asyncio.gather(*(REAL_SNAPSHOT_TOKEN() for _ in range(5)))

    assert asyncio.run(run()) == ["unknown"] * 5
    assert len(calls) == 1  # concurrent callers share one lookup


def test_cache_ttl_and_env_semantics(monkeypatch):
    monkeypatch.setattr(impl, "CACHE_TTL_SECONDS", 300)
    assert impl._effective_cache_ttl("/weekly") == impl.DEFAULT_WEEKLY_SNAPSHOT_TTL
    monkeypatch.setattr(impl, "CACHE_TTL_SECONDS", 0)
    assert impl._effective_cache_ttl("/weekly") == 0


# --------------------------------------------------------------------------
# Item 2: Model Lab reads the snapshot
# --------------------------------------------------------------------------

def test_model_lab_sql_reads_snapshot_and_parses():
    import sqlglot
    sql = impl._model_lab_sql("ITSG")
    assert impl.FC_TABLE in sql and impl._latest_run() in sql
    assert "arr_forecast_app_latest" not in sql and "run_date_utc" not in sql
    assert "product = 'ITSG'" in sql and "= 'Total'" in sql
    for col in ("arr_ets", "arr_prophet", "arr_lightgbm", "arr_mstl_v2", "arr_dhr_arima", "Most_Likely"):
        assert col in sql
    assert len(sqlglot.parse(sql, read="databricks")) == 1


def test_model_lab_response_shape_and_null_bands(monkeypatch):
    async def query(sql, **kwargs):
        return [
            {"ds": "2026-10-12", "run_date": "2026-10-06", "model": "ETS", "forecast": 90.0,
             "p10": None, "p50": 90.0, "p90": None, "recommended": 0},
            {"ds": "2026-10-12", "run_date": "2026-10-06", "model": "Adaptive_Ensemble", "forecast": 100.0,
             "p10": 80.0, "p50": 100.0, "p90": 120.0, "recommended": 1},
        ]
    monkeypatch.setattr(impl, "_cached_query", query)
    out = asyncio.run(impl.get_model_lab(product="UCC", grain="total", sales_market=None, live_mode=True))
    assert out["source"] == "live" and out["recommended_model"] == "Adaptive_Ensemble"
    assert out["run_date"] == "2026-10-06"
    ets = next(r for r in out["rows"] if r["model"] == "ETS")
    assert ets["p10"] is None and ets["p90"] is None and ets["p50"] == 90.0
    ens = next(r for r in out["rows"] if r["model"] == "Adaptive_Ensemble")
    assert (ens["p10"], ens["p90"], ens["recommended"]) == (80.0, 120.0, 1)
    assert set(ens) == {"ds", "model", "forecast", "p10", "p50", "p90", "recommended"}


def test_model_lab_market_grain_unavailable_without_query(monkeypatch):
    async def query(*_a, **_k):
        pytest.fail("market grain must not query")
    monkeypatch.setattr(impl, "_cached_query", query)
    out = asyncio.run(impl.get_model_lab(product="UCC", grain="market", sales_market="NA", live_mode=True))
    assert out["source"] == "unavailable" and out["rows"] == [] and out["models"] == []
