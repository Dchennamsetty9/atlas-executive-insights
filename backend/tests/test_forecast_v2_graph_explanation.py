"""Composite graph-explanation keys (ai_insights, exec_mode) are composed live
from stored per-chart rows in forecast_graph_explanations."""

import asyncio
import json
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

from fastapi import HTTPException  # noqa: E402
from routes import forecast_v2_impl as impl  # noqa: E402


def _row(text, bullets, region="Total", run_date="2026-10-05"):
    return {"title": "t", "explanation": text, "bullets": json.dumps(bullets),
            "run_date": run_date, "region": region, "scope_period": "quarter"}


def _call(monkeypatch, store, **kw):
    """store: {(graph_key, region): row}. Records every SQL issued."""
    sqls = []

    def execute(sql):
        sqls.append(sql)
        g = sql.split("graph_key = '")[1].split("'")[0]
        r = sql.split("region = '")[1].split("'")[0] if "region = '" in sql else "Total"
        row = store.get((g, r))
        return [row] if row else []

    monkeypatch.setattr(impl, "execute_query", execute)
    monkeypatch.setattr(impl, "_live", lambda: True)
    args = dict(graph="ai_insights", product=None, product_line=None,
                sales_market=None, year=None, quarter=None)
    args.update(kw)
    return asyncio.run(impl.get_graph_explanation(**args)), sqls


def test_ai_insights_joins_outlook_then_accuracy(monkeypatch):
    store = {("quarterly_outlook", "Total"): _row("Outlook text.", ["a", "b"]),
             ("accuracy", "Total"): _row("Accuracy text.", ["B", "c"], run_date="2026-10-06")}
    out, sqls = _call(monkeypatch, store)
    assert out["source"] == "live" and out["graph"] == "ai_insights"
    assert out["title"] == "AI Insights"
    assert out["explanation"] == "Outlook text.\n\nAccuracy text."
    assert out["bullets"] == ["a", "b", "c"]  # case-insensitive de-dup
    assert out["run_date"] == "2026-10-06"
    assert not any("'by_product'" in s for s in sqls)


def test_exec_mode_uses_three_components_and_caps_bullets(monkeypatch):
    store = {(g, "Total"): _row(f"{g} text", [f"{g}-{i}" for i in range(4)])
             for g in ("quarterly_outlook", "by_product", "accuracy")}
    out, _ = _call(monkeypatch, store, graph="exec_mode", product_line="UCC")
    assert out["title"] == "Exec Mode" and out["product"] == "UCC"
    assert out["explanation"].split("\n\n") == ["quarterly_outlook text", "by_product text", "accuracy text"]
    assert len(out["bullets"]) == 6


def test_partial_components_still_live(monkeypatch):
    out, _ = _call(monkeypatch, {("accuracy", "Total"): _row("Only accuracy.", ["x"])},
                   graph="exec_mode")
    assert out["source"] == "live" and out["explanation"] == "Only accuracy."


def test_no_components_returns_generating_fallback(monkeypatch):
    out, _ = _call(monkeypatch, {})
    assert out["source"] == "demo"
    assert "being generated" in out["explanation"]


def test_region_cascade_and_scope_note_merged(monkeypatch):
    store = {("quarterly_outlook", "Total"): _row("O.", []),
             ("accuracy", "NA"): _row("A.", [], region="NA")}
    out, _ = _call(monkeypatch, store, sales_market="NA", year=1999)
    assert out["source"] == "live"
    assert "outside the precomputed window" in out["scope_note"]
    assert "No region-specific explanation for NA" in out["scope_note"]


def test_unknown_key_still_rejected(monkeypatch):
    with pytest.raises(HTTPException) as ei:
        _call(monkeypatch, {}, graph="trend")
    assert ei.value.status_code == 400


def test_single_key_behaviour_unchanged(monkeypatch):
    out, _ = _call(monkeypatch, {("weekly", "Total"): _row("W.", ["w"])}, graph="weekly")
    assert out["source"] == "live" and out["explanation"] == "W." and out["bullets"] == ["w"]
