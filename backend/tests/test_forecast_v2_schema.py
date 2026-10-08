"""
Schema guard: every column the forecast SQL generators read from the snapshot
(FC_TABLE) must be in an explicit allow-list, so a stray p30/p10-style reference
fails CI instead of silently turning every endpoint into an 'unavailable' payload.
"""

import asyncio
import datetime

import pytest
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import build_scope

from test_forecast_v2_ops import impl  # reuses the service stubs / import bootstrap

SNAPSHOT_COLUMNS = {c.lower() for c in (
    "ds", "product", "sales_market", "forecast_type", "forecast_view", "run_date",
    "Actuals", "Most_Likely", "Worst_Case", "Best_Case",
    "p05", "p25", "p50", "p75", "p95", "blended_p50", "source", "bands_method",
    "arr_ets", "arr_prophet", "arr_lightgbm", "arr_mstl_v2", "arr_dhr_arima",
    "mape_ets", "mape_prophet", "mape_lightgbm", "mape_mstl_v2", "mape_dhr_arima",
    # per-model P25/P75 (notebook 03, 2026-10-08): the Stretch / Risk numbers of the model views
    "arr_ets_p25", "arr_ets_p75", "arr_prophet_p25", "arr_prophet_p75", "arr_lightgbm_p25", "arr_lightgbm_p75",
    "arr_mstl_v2_p25", "arr_mstl_v2_p75", "arr_dhr_arima_p25", "arr_dhr_arima_p75",
)}
# The incl-Miradore variant has the same columns plus these two (alt table only).
MIRADORE_ONLY_COLUMNS = {"miradore_amount", "miradore_basis"}
MIRADORE_COLUMNS = SNAPSHOT_COLUMNS | MIRADORE_ONLY_COLUMNS
FC_NAME = impl.FC_TABLE_NAME.lower()
FC_NAMES = {FC_NAME, impl.MIRADORE_TABLE_NAME.lower()}


def snapshot_columns_referenced(sql):
    """Columns read directly from FC_TABLE in each SELECT scope (aliases of that
    scope's own projections, usable in GROUP/ORDER BY, are not table columns)."""
    found = set()
    root = build_scope(sqlglot.parse_one(sql, read="databricks"))
    if root is None:  # not a SELECT (e.g. SHOW COLUMNS)
        return found
    for scope in root.traverse():
        fc_aliases = {alias for alias, src in scope.sources.items()
                      if isinstance(src, exp.Table) and src.name.lower() in FC_NAMES}
        if not fc_aliases:
            continue
        select = scope.expression
        own_aliases = {e.alias.lower() for e in getattr(select, "expressions", []) if e.alias}
        n_sources = len(scope.sources)
        for col in scope.columns:
            name = col.name.lower()
            if col.table:
                src_scope, hit = scope, False
                while src_scope is not None:
                    src = src_scope.sources.get(col.table)
                    if src is not None:
                        hit = isinstance(src, exp.Table) and src.name.lower() in FC_NAMES
                        break
                    src_scope = src_scope.parent
                if not hit:
                    continue
            elif n_sources != 1 or name in own_aliases:
                continue
            found.add(name)
    return found


def collect_sql(monkeypatch, miradore=False):
    queries = []
    impl._MIRADORE_CTX.set({"miradore_requested": miradore, "miradore_included": miradore, "reason": None})

    async def query(sql, **kwargs):
        queries.append(sql)
        return []

    monkeypatch.setattr(impl, "_cached_query", query)
    year = datetime.date.today().year
    for model in impl.MODEL_SOURCES:
        for opts in (dict(year=None, quarter=None), dict(year=year, quarter=None),
                     dict(year=year, quarter=3), dict(year=year + 1, quarter=None)):
            for ftype in ("forecast", "actuals"):
                kw = dict(product=None, product_line="UCC", sales_market="NA", model=model,
                          forecast_type=ftype, live_mode=True, **opts)
                asyncio.run(impl.get_weekly(**kw))
                asyncio.run(impl.get_monthly(**kw))
                asyncio.run(impl.get_ytd(**kw))
                asyncio.run(impl.get_by_product(**kw))
                asyncio.run(impl.get_confidence_bands(**kw))
                asyncio.run(impl.get_historical(product=None, product_line="UCC", sales_market="NA",
                                                model=model, year=opts["year"], live_mode=True))
        asyncio.run(impl.get_risk_radar(forecast_type="forecast", model=model, year=year, quarter=None,
                                        limit=5, product_line="ITSG", sales_market=None, live_mode=True))
    asyncio.run(impl.get_forward_outlook(product_line="UCC", sales_market=None, live_mode=True))
    asyncio.run(impl.get_monthly_combined(product_line="ITSG", sales_market="NA", live_mode=True))
    asyncio.run(impl.get_run_delta(product_line="UCC", sales_market="NA", live_mode=True))
    asyncio.run(impl.get_run_history(product_line="UCC", sales_market="NA", live_mode=True))
    asyncio.run(impl.get_leaderboard(live_mode=True))
    asyncio.run(impl.get_freshness(live_mode=True))
    for market_product in ("UCC", "ITSG", None):
        asyncio.run(impl.get_driver_bridge(model="ensemble", product=None, year=year, quarter=3,
                                           product_line=market_product, sales_market=None, live_mode=True))
        asyncio.run(impl.get_confidence(model="ensemble", year=None, quarter=None,
                                        product_line=market_product, sales_market=None, live_mode=True))
    asyncio.run(impl.get_health(strict=False, live_mode=True))
    asyncio.run(impl.get_models(live_mode=True))
    for product in ("UCC", "ITSG"):
        queries.append(impl._model_lab_sql(product))
    return queries


def test_model_sources_use_only_snapshot_columns():
    for key, src in impl.MODEL_SOURCES.items():
        assert src["table"] == impl.FC_TABLE
        for field in ("most_likely_col", "lower_col", "upper_col"):
            col = src[field]
            assert col.lower() in SNAPSHOT_COLUMNS, f"{key}.{field} -> {col}"
        # per-model bands are masked to NULL for everything but the ensemble
        if key != "ensemble":
            assert impl._model_source(key)["lower_col"] == "NULL"


def test_model_bands_use_own_columns_when_published_else_null():
    """Model views get their own arr_<model>_p25/_p75 when the snapshot has them; never the ensemble's band."""
    have = frozenset(f"arr_{k}_{q}" for k in ("ets", "prophet", "lightgbm", "mstl_v2", "dhr_arima") for q in ("p25", "p75"))
    tok = impl._MODEL_BAND_COLS_CTX.set(have)
    try:
        for key, src in impl.MODEL_SOURCES.items():
            if key == "ensemble":
                assert impl._model_source(key)["lower_col"] == "p25"
                continue
            s = impl._model_source(key)
            assert s["lower_col"] == f"{src['most_likely_col']}_p25" and s["upper_col"] == f"{src['most_likely_col']}_p75"
            assert s["lower_col"].lower() in SNAPSHOT_COLUMNS and s["upper_col"].lower() in SNAPSHOT_COLUMNS
        impl._MODEL_BAND_COLS_CTX.set(frozenset({"arr_ets_p25"}))      # half-published -> NULL, not a broken query
        assert impl._model_source("ets")["lower_col"] == "NULL"
    finally:
        impl._MODEL_BAND_COLS_CTX.reset(tok)
    assert impl._model_source("ets")["lower_col"] == "NULL"           # older snapshot / no probe


def test_model_band_probe_is_not_stuck_on_a_stale_answer(monkeypatch):
    """A republish that adds the band columns is picked up within the short probe TTL, not the weekly cache TTL."""
    import asyncio, sys
    state = {"cols": ["ds", "arr_ets"]}
    pkg = sys.modules["routes.forecast_v2"]
    monkeypatch.setattr(pkg, "execute_query", lambda sql, *a, **k: [{"col_name": c} for c in state["cols"]], raising=False)
    monkeypatch.setattr(impl, "_MODEL_BANDS_PROBE", None)
    assert asyncio.run(impl._model_band_columns()) == frozenset()
    impl._MODEL_BANDS_PROBE = (impl._MODEL_BANDS_PROBE[0] - 31, impl._MODEL_BANDS_PROBE[1], impl._MODEL_BANDS_PROBE[2])
    state["cols"] += ["arr_ets_p25", "arr_ets_p75", "mape_ets"]
    assert asyncio.run(impl._model_band_columns()) == frozenset({"arr_ets_p25", "arr_ets_p75"})


def test_miradore_columns_only_valid_on_alt_table():
    assert MIRADORE_ONLY_COLUMNS.isdisjoint(SNAPSHOT_COLUMNS)
    sql = f"SELECT SUM(miradore_amount) AS m FROM {impl.MIRADORE_TABLE} GROUP BY ds"
    assert snapshot_columns_referenced(sql) - MIRADORE_COLUMNS == set()
    assert snapshot_columns_referenced(sql) - SNAPSHOT_COLUMNS == {"miradore_amount"}


def test_extractor_flags_stray_legacy_quantile():
    bad = f"SELECT CAST(p30 AS DOUBLE) AS lower FROM {impl.FC_TABLE} WHERE run_date = '2026-01-01'"
    assert snapshot_columns_referenced(bad) - SNAPSHOT_COLUMNS == {"p30"}
    ok = f"SELECT SUM(p25) AS lower FROM {impl.FC_TABLE} GROUP BY ds ORDER BY lower"
    assert snapshot_columns_referenced(ok) <= SNAPSHOT_COLUMNS


@pytest.mark.parametrize("miradore", [False, True])
def test_generated_sql_references_only_allowed_snapshot_columns(monkeypatch, miradore):
    queries = collect_sql(monkeypatch, miradore=miradore)
    impl._MIRADORE_CTX.set(None)
    assert len(queries) > 100
    table = impl.MIRADORE_TABLE if miradore else impl.FC_TABLE
    allowed = MIRADORE_COLUMNS if miradore else SNAPSHOT_COLUMNS
    used = set()
    for sql in queries:
        if table not in sql:
            continue
        cols = snapshot_columns_referenced(sql)
        used |= cols
        stray = cols - allowed
        assert not stray, f"unknown snapshot column(s) {sorted(stray)} in:\n{sql}"
    # the extractor must actually be seeing the quantile / model columns
    assert {"p25", "p75", "most_likely", "arr_ets", "actuals", "run_date"} <= used
