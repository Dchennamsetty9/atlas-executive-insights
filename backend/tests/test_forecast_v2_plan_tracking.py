"""Plan tracking (/driver-bridge), derived /confidence and /meeting-mode: live paths, honest unavailability."""

import asyncio
import datetime

import pytest
import sqlglot

from test_forecast_v2_ops import impl  # reuses the service stubs / import bootstrap

QUARTER = dict(year=2026, quarter=3)  # 2026-07-01 .. 2026-09-30


@pytest.fixture(autouse=True)
def _fixed_snapshot_token(monkeypatch):
    async def token():
        return "test-run"
    monkeypatch.setattr(impl, "_snapshot_token", token)


def _snap(product, ds, ftype, actual=None, likely=None):
    return {"product": product, "ds": ds, "forecast_type": ftype, "actual": actual, "likely": likely}


def _plan(ds, value, run="2026-06-30", hi=None):
    return {"ds": ds, "p50_min": value, "p50_max": value if hi is None else hi, "run_date": run}


def _router(snapshot, plans):
    """Fake _cached_query: snapshot rows for FC_TABLE reads, plans keyed by vintage prefix."""
    calls = []

    async def query(sql, **kwargs):
        calls.append(sql)
        if "forecast_vintages" in sql:
            prefix = "ucc" if "ucc_forecast_vintages" in sql else "itsg"
            return plans.get(prefix, [])
        return snapshot
    return query, calls


def _bridge(**kw):
    kw.setdefault("model", "ensemble")
    kw.setdefault("product", None)
    kw.setdefault("sales_market", None)
    kw.setdefault("live_mode", True)
    return asyncio.run(impl.get_driver_bridge(**{**QUARTER, **kw}))


UCC_SNAP = [
    _snap("UCC", "2026-07-06", "actuals", actual=110.0),
    _snap("UCC", "2026-07-13", "actuals", actual=90.0),
    _snap("UCC", "2026-07-20", "forecast", likely=105.0),
    _snap("UCC", "2026-07-27", "boq_forward", likely=95.0),
]
UCC_PLAN = [_plan("2026-07-06", 100.0), _plan("2026-07-13", 100.0),
            _plan("2026-07-20", 100.0), _plan("2026-07-27", 100.0)]


def test_bridge_live_single_product(monkeypatch):
    query, calls = _router(UCC_SNAP, {"ucc": UCC_PLAN})
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge(product_line="UCC")
    assert r["source"] == "live" and r["reason"] is None
    assert r["actual_total"] == 200.0 and r["plan_total"] == r["plan_total_closed"] == 200.0
    assert r["variance"] == 0.0 and r["variance_pct"] == 0.0
    assert r["plan_total_quarter"] == 400.0 and r["outlook_total"] == 400.0 and r["outlook_vs_plan"] == 0.0
    assert r["weeks_closed"] == 2 and r["quarter_label"] == "Q3 2026"
    assert r["components"] == [{"name": "UCC", "driver": "UCC", "actual": 200.0, "plan": 200.0,
                                "variance": 0.0, "value": 0.0}]
    assert "issued on or before" in r["basis"] and "Most_Likely" in r["basis"]
    vint = next(s for s in calls if "forecast_vintages" in s)
    assert "run_date_utc AS DATE) <= DATE'2026-07-01'" in vint
    assert "model = 'Adaptive_Ensemble'" in vint
    for sql in calls:
        sqlglot.parse_one(sql, read="databricks")


def test_bridge_total_sums_products_with_variance(monkeypatch):
    snap = UCC_SNAP[:2] + [
        _snap("ITSG", "2026-07-06", "actuals", actual=40.0),
        _snap("ITSG", "2026-07-13", "actuals", actual=60.0),
        _snap("UCC", "2026-07-20", "forecast", likely=100.0),
        _snap("ITSG", "2026-07-20", "forecast", likely=50.0),
    ]
    plans = {"ucc": [_plan(d, 80.0) for d in ("2026-07-06", "2026-07-13", "2026-07-20")],
             "itsg": [_plan(d, 50.0) for d in ("2026-07-06", "2026-07-13", "2026-07-20")]}
    query, _ = _router(snap, plans)
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge()
    assert r["product"] == "Total" and r["source"] == "live"
    assert r["actual_total"] == 300.0 and r["plan_total_closed"] == 260.0
    assert r["variance"] == 40.0 and r["variance_pct"] == round(40 / 260 * 100, 2)
    assert r["plan_total_quarter"] == 390.0 and r["outlook_total"] == 450.0
    assert r["outlook_vs_plan"] == 60.0
    assert {c["name"]: c["variance"] for c in r["components"]} == {"UCC": 40.0, "ITSG": 0.0}


@pytest.mark.parametrize("market", ["NA", "EMEA"])
def test_bridge_non_total_market_unavailable_without_query(monkeypatch, market):
    monkeypatch.setattr(impl, "_cached_query", lambda *a, **k: pytest.fail("must not query"))
    r = _bridge(product_line="UCC", sales_market=market)
    assert r["source"] == "unavailable" and "total grain" in r["reason"]
    assert r["actual_total"] is None and r["variance"] is None and r["components"] == []


def test_bridge_no_closed_weeks_keeps_quarter_plan_and_outlook(monkeypatch):
    snap = [_snap("UCC", "2026-07-06", "forecast", likely=100.0),
            _snap("UCC", "2026-07-13", "forecast", likely=120.0)]
    query, _ = _router(snap, {"ucc": [_plan("2026-07-06", 90.0), _plan("2026-07-13", 90.0)]})
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge(product_line="UCC")
    assert r["source"] == "unavailable" and r["reason"] == "No closed weeks in Q3 2026 yet"
    assert r["plan_total_quarter"] == 180.0 and r["outlook_total"] == 220.0
    assert r["actual_total"] is None and r["variance"] is None and r["weeks_closed"] == 0


def test_bridge_no_vintage_before_quarter_is_not_substituted(monkeypatch):
    query, _ = _router(UCC_SNAP, {"ucc": []})
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge(product_line="UCC")
    assert r["source"] == "unavailable"
    assert "on or before 2026-07-01" in r["reason"] and "not substituted" in r["reason"]
    assert r["plan_total"] is None and r["variance"] is None and r["outlook_total"] is None


def test_bridge_one_product_missing_plan_makes_total_unavailable(monkeypatch):
    snap = UCC_SNAP[:2] + [_snap("ITSG", "2026-07-06", "actuals", actual=1.0)]
    query, _ = _router(snap, {"ucc": UCC_PLAN})
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge()
    assert r["source"] == "unavailable" and "ITSG" in r["reason"] and r["variance"] is None


def test_bridge_missing_or_conflicting_closed_week_plan_is_unavailable(monkeypatch):
    plans = {"ucc": [_plan("2026-07-06", 100.0), _plan("2026-07-13", 100.0, hi=105.0),
                     _plan("2026-07-20", 100.0), _plan("2026-07-27", 100.0)]}
    query, _ = _router(UCC_SNAP, plans)
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge(product_line="UCC")
    assert r["source"] == "unavailable" and "missing for 1 closed week" in r["reason"]
    assert "conflicting" in r["reason"] and r["variance"] is None and r["weeks_closed"] == 2


def test_bridge_partial_quarter_plan_omits_quarter_totals(monkeypatch):
    query, _ = _router(UCC_SNAP, {"ucc": UCC_PLAN[:3]})  # last week has no plan
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge(product_line="UCC")
    assert r["source"] == "live" and r["variance"] == 0.0
    assert r["plan_total_quarter"] is None and r["outlook_vs_plan"] is None
    assert r["outlook_total"] == 400.0


def test_bridge_no_snapshot_rows_and_query_failure(monkeypatch):
    query, _ = _router([], {"ucc": UCC_PLAN})
    monkeypatch.setattr(impl, "_cached_query", query)
    assert "No snapshot rows for Q3 2026" in _bridge(product_line="UCC")["reason"]

    async def boom(sql, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(impl, "_cached_query", boom)
    r = _bridge(product_line="UCC")
    assert r["source"] == "unavailable" and "could not be read" in r["reason"]


def test_bridge_not_live_and_default_quarter(monkeypatch):
    monkeypatch.setattr(impl, "_cached_query", lambda *a, **k: pytest.fail("must not query"))
    assert _bridge(product_line="UCC", live_mode=False)["source"] == "unavailable"
    today = datetime.date.today()
    r = asyncio.run(impl.get_driver_bridge(model="ensemble", product=None, year=None, quarter=None,
                                           product_line="UCC", sales_market=None, live_mode=False))
    assert r["quarter_label"] == f"Q{(today.month - 1) // 3 + 1} {today.year}"


# ── /confidence ───────────────────────────────────────────────────────────────

def _conf_rows(*rows):
    async def query(sql, **kwargs):
        assert "forecast_quarterly_accuracy" in sql
        return list(rows)
    return query


def _conf(**kw):
    kw.setdefault("model", "ensemble")
    kw.setdefault("sales_market", None)
    kw.setdefault("live_mode", True)
    return asyncio.run(impl.get_confidence(**kw))


def test_confidence_derived_from_closed_quarter_error(monkeypatch):
    monkeypatch.setattr(impl, "_cached_query", _conf_rows(
        {"product": "Total", "model": "Adaptive_Ensemble", "quarterly_wape": 8.2,
         "quarter_label": "Q2 2026", "source": "dollar_weighted_blend"},
        {"product": "Total", "model": "ETS", "quarterly_wape": 40.0, "quarter_label": "Q2 2026", "source": "x"}))
    r = _conf()
    assert r["source"] == "live" and r["confidence_score"] == 91.8 and r["confidence_label"] == "High"
    assert r["product"] == "Total" and r["quarter_label"] == "Q2 2026" and r["error_pct"] == 8.2
    assert "not a statistical confidence interval" in r["basis"]
    assert any("8.2%" in x and "Q2 2026" in x for x in r["reasons"])


@pytest.mark.parametrize("wape,score,label", [(15.0, 85.0, "High"), (16.0, 84.0, "Medium"),
                                              (30.0, 70.0, "Medium"), (31.0, 69.0, "Low"),
                                              (250.0, 0.0, "Low"), (0.0, 100.0, "High")])
def test_confidence_thresholds_and_clamp(monkeypatch, wape, score, label):
    monkeypatch.setattr(impl, "_cached_query", _conf_rows(
        {"product": "Total", "model": "Adaptive_Ensemble", "quarterly_wape": wape,
         "quarter_label": "Q2 2026", "source": "holdout_closed_quarter"}))
    r = _conf()
    assert (r["confidence_score"], r["confidence_label"]) == (score, label)


def test_confidence_lightgbm_matches_any_global_lgb_and_product(monkeypatch):
    seen = []

    async def query(sql, **kw):
        seen.append(sql)
        return [{"product": "ITSG", "model": "Global_LGB_Q50_ITSG", "quarterly_wape": 20.0,
                 "quarter_label": "Q2 2026", "source": "estimated_x"}]
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _conf(model="lightgbm", product_line="ITSG")
    assert r["source"] == "live" and r["confidence_score"] == 80.0 and r["confidence_label"] == "Medium"
    assert "product = 'ITSG'" in seen[0]
    assert any("estimated" in x for x in r["reasons"])
    sqlglot.parse_one(seen[0], read="databricks")


def test_confidence_unavailable_reasons(monkeypatch):
    monkeypatch.setattr(impl, "_cached_query", _conf_rows())
    r = _conf()
    assert r["source"] == "unavailable" and r["confidence_score"] is None
    assert "Adaptive_Ensemble" in r["reason"] and r["reasons"] == []

    monkeypatch.setattr(impl, "_cached_query", _conf_rows(
        {"product": "Total", "model": "Adaptive_Ensemble", "quarterly_wape": None, "quarter_label": "Q2"}))
    assert "missing or invalid" in _conf()["reason"]

    monkeypatch.setattr(impl, "_cached_query", _conf_rows(
        {"product": "Total", "model": "ETS", "quarterly_wape": 1.0},
        {"product": "Total", "model": "ETS", "quarterly_wape": 2.0}))
    assert "Ambiguous" in _conf(model="ets")["reason"]

    monkeypatch.setattr(impl, "_cached_query", lambda *a, **k: pytest.fail("must not query"))
    assert "total grain" in _conf(sales_market="NA")["reason"]
    assert _conf(live_mode=False)["source"] == "unavailable"

    async def boom(sql, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(impl, "_cached_query", boom)
    assert "could not be read" in _conf()["reason"]


# ── /meeting-mode ─────────────────────────────────────────────────────────────

def _meeting(monkeypatch, confidence, bridge, radar):
    async def conf(**kw):
        return confidence

    async def br(**kw):
        return bridge

    async def rr(**kw):
        return radar

    async def fresh(**kw):
        return {"source": "live"}
    monkeypatch.setattr(impl, "get_confidence", conf)
    monkeypatch.setattr(impl, "get_driver_bridge", br)
    monkeypatch.setattr(impl, "get_risk_radar", rr)
    monkeypatch.setattr(impl, "get_freshness", fresh)
    monkeypatch.setattr(impl, "_live_mode_dependency", lambda: True)
    return asyncio.run(impl.get_meeting_mode(model="ensemble", year=None, quarter=None,
                                             product_line=None, sales_market=None))


LIVE_BRIDGE = {"source": "live", "plan_total": 200.0, "plan_total_closed": 200.0, "plan_total_quarter": 400.0,
               "actual_total": 210.0, "variance": 10.0, "variance_pct": 5.0, "outlook_total": 410.0,
               "outlook_vs_plan": 10.0, "weeks_closed": 2, "quarter_label": "Q3 2026", "basis": "b", "reason": None}


def test_meeting_mode_only_lists_really_unavailable_sections(monkeypatch):
    r = _meeting(monkeypatch, {"source": "live"}, LIVE_BRIDGE, {"source": "unavailable", "items": []})
    assert r["source"] == "live" and r["status"] == "partial"
    assert r["unavailable_sections"] == ["recommendations"]
    assert r["variance"]["variance"] == 10.0 and r["variance"]["outlook_vs_plan"] == 10.0
    assert r["variance"]["quarter_label"] == "Q3 2026"


def test_meeting_mode_everything_unavailable(monkeypatch):
    bridge = {"source": "unavailable", "reason": "No closed weeks in Q3 2026 yet", "plan_total_quarter": 400.0}
    r = _meeting(monkeypatch, {"source": "unavailable"}, bridge, {"source": "unavailable", "items": []})
    assert r["source"] == "unavailable"
    assert r["unavailable_sections"] == ["confidence", "plan_variance", "recommendations"]
    assert r["variance"]["reason"] == "No closed weeks in Q3 2026 yet"
    assert r["variance"]["variance"] is None and r["variance"]["plan_total_quarter"] == 400.0


def test_meeting_mode_live_when_only_radar_live_keeps_top_risks(monkeypatch):
    items = [{"product": "UCC"}, {"product": "ITSG"}, {"product": "X"}, {"product": "Y"}]
    r = _meeting(monkeypatch, {"source": "live"}, {"source": "unavailable"}, {"source": "live", "items": items})
    assert r["source"] == "live" and r["top_risks"] == items[:3]
    assert r["unavailable_sections"] == ["plan_variance", "recommendations"]


def test_plan_takes_the_latest_run_not_every_run_of_the_day():
    """The pipeline is re-run several times a day; the plan is the LAST run issued on/before the quarter start."""
    sql = impl._bridge_plan_sql("itsg", "ITSG", datetime.date(2026, 10, 1), datetime.date(2026, 12, 31))
    assert "ORDER BY COALESCE(CAST(run_timestamp_utc AS TIMESTAMP), CAST(run_date_utc AS TIMESTAMP)) DESC" in sql
    assert "run_date_utc AS DATE) <= DATE'2026-10-01'" in sql
    legacy = impl._bridge_plan_sql("itsg", "ITSG", datetime.date(2026, 10, 1), datetime.date(2026, 12, 31), by_timestamp=False)
    assert "run_timestamp_utc" not in legacy and "ORDER BY CAST(run_date_utc AS DATE) DESC" in legacy
    sqlglot.parse_one(sql, read="databricks"); sqlglot.parse_one(legacy, read="databricks")


def test_bridge_falls_back_to_date_ranking_when_vintages_lack_run_timestamp(monkeypatch):
    calls = []

    async def query(sql, **kwargs):
        calls.append(sql)
        if "forecast_vintages" in sql:
            if "run_timestamp_utc" in sql:
                raise RuntimeError("UNRESOLVED_COLUMN run_timestamp_utc")
            return UCC_PLAN
        return UCC_SNAP
    monkeypatch.setattr(impl, "_cached_query", query)
    r = _bridge(product_line="UCC")
    assert r["source"] == "live" and r["plan_total"] == 200.0
    assert any("run_timestamp_utc" in s for s in calls) and any("forecast_vintages" in s and "run_timestamp_utc" not in s for s in calls)
