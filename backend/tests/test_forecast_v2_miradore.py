"""
Per-request Miradore switch: ?include_miradore selects forecast_app_snapshot_incl_miradore
(verified available, else silent fallback reported in `scope`), caches never mix the two
tables, and UCC / default behaviour is unchanged.
"""

import asyncio
import pathlib
import sys
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_forecast_v2_ops import impl, package  # noqa: E402  (service stubs + import bootstrap)

app = FastAPI()
app.include_router(package.router)
client = TestClient(app)

BASE = impl.FC_TABLE
ALT = impl.MIRADORE_TABLE


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    monkeypatch.setattr(impl, "_QUERY_CACHE", {})
    monkeypatch.setattr(impl, "_SNAPSHOT_TOKEN", None)
    monkeypatch.setattr(impl, "_SNAPSHOT_TOKEN_INFLIGHT", None)
    monkeypatch.setattr(impl, "_MIRADORE_PROBE", None)
    monkeypatch.setattr(impl, "_MIRADORE_PROBE_INFLIGHT", None)
    monkeypatch.setattr(package, "_live", lambda: True)


def _fake_db(monkeypatch, alt_state="ok", log=None):
    """alt_state: ok | missing | empty. Records every SQL text."""
    log = log if log is not None else []

    def execute(sql):
        log.append(sql)
        if ALT in sql and "miradore_max" in sql:
            if alt_state == "missing":
                raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")
            return [{"run_date": None if alt_state == "empty" else "2026-10-06", "miradore_max": 1.0}]
        if "AS run_date FROM" in sql:
            return [{"run_date": "2026-10-06"}]
        return []

    monkeypatch.setattr(package, "execute_query", execute)
    return log


def _data_sql(log):
    return [s for s in log if "miradore_max" not in s and "AS run_date FROM" not in s]


def test_default_reads_base_table_only(monkeypatch):
    log = _fake_db(monkeypatch)
    body = client.get("/api/forecast/v2/weekly?product_line=ITSG").json()
    assert body["scope"] == {"miradore_requested": False, "miradore_included": False, "reason": None}
    assert not any(ALT in s for s in log)  # not even a probe
    assert all(BASE in s for s in _data_sql(log))


def test_include_true_reads_alt_table_and_scope(monkeypatch):
    log = _fake_db(monkeypatch)
    for path in ("weekly", "ytd", "monthly", "by-product", "confidence-bands"):
        body = client.get(f"/api/forecast/v2/{path}?product_line=ITSG&include_miradore=true").json()
        assert body["scope"] == {"miradore_requested": True, "miradore_included": True, "reason": None}, path
    snap = [s for s in _data_sql(log) if ALT in s or BASE in s]  # some reads use other tables
    assert snap and all(ALT in s and BASE not in s for s in snap)


def test_ucc_request_still_valid_with_flag(monkeypatch):
    # UCC rows are identical in both tables, so the flag may be on; SQL still filters UCC.
    log = _fake_db(monkeypatch)
    client.get("/api/forecast/v2/weekly?product_line=UCC&include_miradore=true")
    assert any("product = 'UCC'" in s and ALT in s for s in _data_sql(log))


@pytest.mark.parametrize("state,reason", [("missing", "miradore_table_error"), ("empty", "miradore_table_empty")])
def test_fallback_when_alt_unavailable(monkeypatch, state, reason):
    log = _fake_db(monkeypatch, alt_state=state)
    body = client.get("/api/forecast/v2/weekly?product_line=ITSG&include_miradore=true").json()
    assert body["scope"] == {"miradore_requested": True, "miradore_included": False, "reason": reason}
    data = _data_sql(log)
    assert data and all(BASE in s and ALT not in s for s in data)


def test_probe_is_cached_between_requests(monkeypatch):
    log = _fake_db(monkeypatch)
    for _ in range(3):
        client.get("/api/forecast/v2/weekly?product_line=ITSG&include_miradore=true")
    assert sum("miradore_max" in s for s in log) == 1


def test_model_views_exclude_miradore(monkeypatch):
    log = _fake_db(monkeypatch)
    body = client.get("/api/forecast/v2/weekly?product_line=ITSG&model=ets&include_miradore=true").json()
    assert body["scope"] == {"miradore_requested": True, "miradore_included": False,
                             "reason": "model_views_exclude_miradore"}
    body = client.get("/api/forecast/v2/model-lab?product=ITSG&include_miradore=true").json()
    assert body["scope"]["reason"] == "model_views_exclude_miradore"
    assert not any(ALT in s for s in log)


def test_not_live_reports_reason(monkeypatch):
    _fake_db(monkeypatch)
    monkeypatch.setattr(package, "_live", lambda: False)
    body = client.get("/api/forecast/v2/weekly?include_miradore=true").json()
    assert body["scope"]["miradore_included"] is False
    assert body["scope"]["reason"] == "databricks_unavailable"


def test_cache_isolation_between_tables(monkeypatch):
    log = _fake_db(monkeypatch)
    monkeypatch.setattr(impl, "query_cache_scope", lambda: "caller")

    def run(included):
        async def go():
            impl._MIRADORE_CTX.set({"miradore_requested": included, "miradore_included": included, "reason": None})
            return await impl._cached_query("SELECT 1 /* same text */", endpoint="/weekly")
        return asyncio.run(go())

    run(False); run(True); run(False); run(True)
    # Same SQL text, but separate cache namespaces: one execution per table state.
    assert sum(s == "SELECT 1 /* same text */" for s in log) == 2

    async def tokens():
        impl._MIRADORE_CTX.set(None)
        base = await impl._snapshot_token()
        impl._MIRADORE_CTX.set({"miradore_requested": True, "miradore_included": True, "reason": None})
        return base, await impl._snapshot_token()

    base, alt = asyncio.run(tokens())
    assert base == "2026-10-06" and alt == "miradore:2026-10-06"


def test_latest_run_and_model_source_follow_table(monkeypatch):
    async def go(included):
        impl._MIRADORE_CTX.set({"miradore_requested": included, "miradore_included": included, "reason": None})
        return impl._latest_run(), impl._model_source("ensemble")["table"], impl._fc_table()

    run, table, fc = asyncio.run(go(True))
    assert ALT in run and table == ALT and fc == ALT
    run, table, fc = asyncio.run(go(False))
    assert BASE in run and table == BASE and fc == BASE


def test_health_reports_miradore_without_changing_status(monkeypatch):
    _fake_db(monkeypatch)
    body = client.get("/api/forecast/v2/health?include_miradore=true").json()
    assert body["table"] == BASE.replace("`", "")
    assert body["miradore"]["present"] is True and body["miradore"]["latest_run_date"] == "2026-10-06"
    impl._MIRADORE_PROBE = None
    _fake_db(monkeypatch, alt_state="missing")
    body = client.get("/api/forecast/v2/health").json()
    assert body["miradore"]["present"] is False and body["miradore"]["reason"] == "miradore_table_error"
    assert "scope" in body
