"""In-quarter pace outlook endpoint: reads the per-product pace tables, never combines errors, fail-soft."""
import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_forecast_v2_ops import impl, package  # noqa: E402

app = FastAPI()
app.include_router(package.router)
client = TestClient(app)


def _row(q="2026Q4", land=15.0e6, model=14.0e6, validated=True, mape=2.8, mmape=8.6, n=4, wk=8):
    return {"run_date": "2026-10-20", "asof_date": "2026-11-23", "quarter_label": q, "weeks_closed": wk,
            "qtd_actual": 9.0e6, "remaining_forecast": 5.0e6, "pace_factor": 1.05, "outlook_landing": land,
            "model_landing": model, "validated": validated, "backtest_mape_pct": mape, "model_mape_pct": mmape,
            "n_quarters": n}


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    monkeypatch.setattr(impl, "_QUERY_CACHE", {})
    monkeypatch.setattr(impl, "_SNAPSHOT_TOKEN", None)
    monkeypatch.setattr(package, "_live", lambda: True)


def _db(monkeypatch, tables):
    def execute(sql):
        if "AS run_date FROM" in sql:
            return [{"run_date": "2026-10-20"}]
        for name, rows in tables.items():
            if name in sql:
                if isinstance(rows, Exception):
                    raise rows
                return rows
        return []
    monkeypatch.setattr(package, "execute_query", execute)


def test_single_product(monkeypatch):
    _db(monkeypatch, {"ucc_forecast_pace_outlook": [_row()]})
    r = client.get("/api/forecast/v2/pace-outlook?product_line=UCC").json()
    assert r["source"] == "live" and r["quarter_label"] == "2026Q4" and r["total"] is None
    p = r["products"][0]
    assert p["product"] == "UCC" and p["validated"] is True and p["outlook_landing"] == 15.0e6 and p["weeks_closed"] == 8


def test_all_sums_landing_but_never_combines_errors(monkeypatch):
    _db(monkeypatch, {"ucc_forecast_pace_outlook": [_row(land=15e6, model=14e6)],
                      "itsg_forecast_pace_outlook": [_row(land=4e6, model=3.5e6, validated=False, mape=None, mmape=None, n=0, wk=2)]})
    r = client.get("/api/forecast/v2/pace-outlook?product_line=All").json()
    assert r["total"] == {"outlook_landing": 19e6, "model_landing": 17.5e6, "validated": False}
    assert "backtest_mape_pct" not in r["total"] and [p["product"] for p in r["products"]] == ["UCC", "ITSG"]


def test_string_validated_flag_and_missing_values(monkeypatch):
    row = _row(); row["validated"] = "false"; row["backtest_mape_pct"] = None; row["outlook_landing"] = float("nan")
    _db(monkeypatch, {"itsg_forecast_pace_outlook": [row]})
    p = client.get("/api/forecast/v2/pace-outlook?product_line=ITSG").json()["products"][0]
    assert p["validated"] is False and p["backtest_mape_pct"] is None and p["outlook_landing"] is None


@pytest.mark.parametrize("tables,reason", [
    ({"ucc_forecast_pace_outlook": []}, "No pace outlook has been published for UCC yet."),
    ({"ucc_forecast_pace_outlook": RuntimeError("TABLE_OR_VIEW_NOT_FOUND")}, "Pace outlook for UCC could not be read."),
])
def test_unavailable_is_reported_not_raised(monkeypatch, tables, reason):
    _db(monkeypatch, tables)
    r = client.get("/api/forecast/v2/pace-outlook?product_line=UCC")
    assert r.status_code == 200 and r.json()["source"] == "unavailable" and r.json()["reason"] == reason


def test_different_quarters_are_not_mixed(monkeypatch):
    _db(monkeypatch, {"ucc_forecast_pace_outlook": [_row(q="2026Q4")], "itsg_forecast_pace_outlook": [_row(q="2026Q3")]})
    r = client.get("/api/forecast/v2/pace-outlook?product_line=All").json()
    assert r["source"] == "unavailable" and r["total"] is None and "different quarters" in r["reason"]
