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
)}
FC_NAME = impl.FC_TABLE_NAME.lower()


def snapshot_columns_referenced(sql):
    """Columns read directly from FC_TABLE in each SELECT scope (aliases of that
    scope's own projections, usable in GROUP/ORDER BY, are not table columns)."""
    found = set()
    root = build_scope(sqlglot.parse_one(sql, read="databricks"))
    if root is None:  # not a SELECT (e.g. SHOW COLUMNS)
        return found
    for scope in root.traverse():
        fc_aliases = {alias for alias, src in scope.sources.items()
                      if isinstance(src, exp.Table) and src.name.lower() == FC_NAME}
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
                        hit = isinstance(src, exp.Table) and src.name.lower() == FC_NAME
                        break
                    src_scope = src_scope.parent
                if not hit:
                    continue
            elif n_sources != 1 or name in own_aliases:
                continue
            found.add(name)
    return found


def collect_sql(monkeypatch):
    queries = []

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


def test_extractor_flags_stray_legacy_quantile():
    bad = f"SELECT CAST(p30 AS DOUBLE) AS lower FROM {impl.FC_TABLE} WHERE run_date = '2026-01-01'"
    assert snapshot_columns_referenced(bad) - SNAPSHOT_COLUMNS == {"p30"}
    ok = f"SELECT SUM(p25) AS lower FROM {impl.FC_TABLE} GROUP BY ds ORDER BY lower"
    assert snapshot_columns_referenced(ok) <= SNAPSHOT_COLUMNS


def test_generated_sql_references_only_allowed_snapshot_columns(monkeypatch):
    queries = collect_sql(monkeypatch)
    assert len(queries) > 100
    used = set()
    for sql in queries:
        if impl.FC_TABLE not in sql:
            continue
        cols = snapshot_columns_referenced(sql)
        used |= cols
        stray = cols - SNAPSHOT_COLUMNS
        assert not stray, f"unknown snapshot column(s) {sorted(stray)} in:\n{sql}"
    # the extractor must actually be seeing the quantile / model columns
    assert {"p25", "p75", "most_likely", "arr_ets", "actuals", "run_date"} <= used
