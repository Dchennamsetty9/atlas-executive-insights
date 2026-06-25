"""
Forecast v2 — rich endpoints for the ForecastingPanel UI.

Reads from:  datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
  columns: ds, product (Total/UCC/ITSG), sales_market (Total/NA/EMEA/APAC/LATAM),
           Actuals, Most_Likely, Worst_Case, Best_Case,
           arr_ets, arr_prophet, arr_lightgbm, arr_chronos,
           mape_ets, mape_prophet, mape_lightgbm, mape_chronos,
           forecast_type (actuals|rolling|roy), run_date

Leaderboard: datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard

All values are constrained to the Growth-bookings-aligned v2 tables.
"""

import asyncio, os, datetime, logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, HTTPException
from services.databricks_connection import execute_query, token_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forecast/v2", tags=["forecast-v2"])

FORECAST_CATALOG = os.getenv("FORECAST_CATALOG", "datagroup_mdl")
FORECAST_SCHEMA = os.getenv("FORECAST_SCHEMA", "mdl_sales_analytics")
GOLD = f"{FORECAST_CATALOG}.{FORECAST_SCHEMA}"
FC_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_v2`"
LB_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_v2_leaderboard`"

VALID_FORECAST_TYPES = {"actuals", "rolling", "roy"}
MODEL_SOURCES: Dict[str, Dict[str, Any]] = {
    "ets": {
        "display_name": "ETS",
        "table": FC_TABLE,
        "most_likely_col": "arr_ets",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "ETS",
        "has_forecast_type": True,
    },
    "prophet": {
        "display_name": "Prophet",
        "table": FC_TABLE,
        "most_likely_col": "arr_prophet",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "Prophet",
        "has_forecast_type": True,
    },
    "lightgbm": {
        "display_name": "LightGBM",
        "table": FC_TABLE,
        "most_likely_col": "arr_lightgbm",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "LightGBM",
        "has_forecast_type": True,
    },
    "chronos": {
        "display_name": "Chronos",
        "table": FC_TABLE,
        "most_likely_col": "arr_chronos",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "Chronos",
        "has_forecast_type": True,
    },
    "ensemble": {
        "display_name": "Ensemble",
        "table": FC_TABLE,
        "most_likely_col": "Most_Likely",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "best_mape",
        "has_forecast_type": True,
    },
}


def _live() -> bool:
    force_live = os.getenv("FORCE_LIVE_DATA", "").lower() == "true"
    has_host = bool(os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_SERVER_HOSTNAME"))
    # In Databricks Apps we may rely on OAuth/service-principal auth without a PAT.
    # FORCE_LIVE_DATA should bypass the token precheck so we attempt real queries
    # and return concrete errors instead of silently showing demo mode.
    return force_live or (has_host and token_available())


def _validate_forecast_type(forecast_type: str) -> str:
    ft = (forecast_type or "").strip().lower()
    if ft not in VALID_FORECAST_TYPES:
        raise HTTPException(status_code=400, detail="Invalid forecast_type")
    return ft


def _validate_model(model: str) -> str:
    key = (model or "").strip().lower()
    if key not in MODEL_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid model")
    return key


def _model_source(model: str) -> Dict[str, Any]:
    return MODEL_SOURCES[_validate_model(model)]

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None and v != "" else default
    except (TypeError, ValueError):
        return default

def _demo(key: str, error: str = "Databricks unavailable"):
    return {"source": "demo", "live_mode_available": False,
            "error": error, key: []}

def _product_filter(product, col="product"):
    # When no product selected, default to Total to avoid summing all 18 slices
    effective = product if (product and product not in ("All", "all")) else "Total"
    return f"AND {col} = '{effective.replace(chr(39), chr(39)*2)}'"


def _normalize_market_value(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() == "all":
        return "Total"
    if raw.upper() == "UNKNOWN":
        return "Unknown"
    return raw


def _normalized_market_expr(col: str = "sales_market") -> str:
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) = 'UNKNOWN' "
        f"THEN 'Unknown' ELSE TRIM(CAST({col} AS STRING)) END"
    )


def _geo_filter(geo, col="sales_market"):
    # When no geo selected, default to Total to avoid double-counting.
    # Normalize UNKNOWN/Unknown into a canonical 'Unknown' bucket at query time.
    effective = _normalize_market_value(geo)
    return f"AND {_normalized_market_expr(col)} = '{effective.replace(chr(39), chr(39)*2)}'"

def _latest_run():
    return f"run_date = (SELECT MAX(run_date) FROM {FC_TABLE})"


def _effective_forecast_type(model: str, forecast_type: str) -> str:
    source = _model_source(model)
    if source["has_forecast_type"]:
        return forecast_type
    # Backward-compat fallback if a model source does not expose forecast_type.
    return "actuals" if forecast_type == "actuals" else "rolling"


def _normalized_forecast_sql(
    model: str,
    forecast_type: str,
    product: Optional[str],
    sales_market: Optional[str],
) -> str:
    source = _model_source(model)
    table = source["table"]
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]
    pf = _product_filter(product)
    gf = _geo_filter(sales_market)

    if source["has_forecast_type"]:
        return f"""
            SELECT
                CAST(ds AS STRING) AS ds,
                '{model}' AS model,
                CAST(forecast_type AS STRING) AS forecast_type,
                COALESCE(CAST({value_col} AS DOUBLE), 0) AS value,
                COALESCE(CAST({lower_col} AS DOUBLE), 0) AS lower,
                COALESCE(CAST({upper_col} AS DOUBLE), 0) AS upper,
                COALESCE(CAST(Actuals AS DOUBLE), 0) AS actual
            FROM {table}
            WHERE {_latest_run()}
                            AND forecast_type = '{forecast_type}'
              {pf} {gf}
            ORDER BY ds
        """

    return f"""
        SELECT
            CAST(ds AS STRING) AS ds,
            '{model}' AS model,
            CASE
                WHEN COALESCE(CAST(Actuals AS DOUBLE), 0) > 0 AND CAST(ds AS DATE) < current_date() THEN 'actuals'
                ELSE 'rolling'
            END AS forecast_type,
            COALESCE(CAST({value_col} AS DOUBLE), 0) AS value,
            COALESCE(CAST({lower_col} AS DOUBLE), 0) AS lower,
            COALESCE(CAST({upper_col} AS DOUBLE), 0) AS upper,
            COALESCE(CAST(Actuals AS DOUBLE), 0) AS actual
        FROM {table}
        WHERE 1=1
                                        AND CAST(ds AS DATE) >= ADD_MONTHS(current_date(), -36)
                    AND CASE
                                WHEN COALESCE(CAST(Actuals AS DOUBLE), 0) > 0 AND CAST(ds AS DATE) < current_date() THEN 'actuals'
                                ELSE 'rolling'
                            END = '{forecast_type}'
          {pf} {gf}
        ORDER BY ds
    """



def _normalise_rows(rows: list[Dict[str, Any]], model: str) -> list[Dict[str, Any]]:
    normalized = []
    for row in rows:
        ds = str(row.get("ds") or "")[:10]
        if not ds:
            continue
        normalized.append({
            "ds": ds,
            "model": model,
            "forecast_type": str(row.get("forecast_type") or "rolling"),
            "value": _f(row.get("value")),
            "lower": _f(row.get("lower")),
            "upper": _f(row.get("upper")),
            "actual": _f(row.get("actual")),
        })
    return normalized


def _summary_kpis(rows: list[Dict[str, Any]]) -> Dict[str, float]:
    most_likely = 0.0
    worst_case = 0.0
    best_case = 0.0
    ytd_actuals = 0.0
    current_year = datetime.date.today().year

    for row in rows:
        ftype = str(row.get("forecast_type") or "").strip().lower()
        ds_val = str(row.get("ds") or "")[:10]
        if ftype in ("rolling", "roy"):
            most_likely += _f(row.get("Most_Likely"))
            worst_case += _f(row.get("Worst_Case"))
            best_case += _f(row.get("Best_Case"))
        if ftype == "actuals" and ds_val[:4].isdigit() and int(ds_val[:4]) == current_year:
            ytd_actuals += _f(row.get("Actuals"))

    return {
        "most_likely": round(most_likely, 0),
        "worst_case": round(worst_case, 0),
        "best_case": round(best_case, 0),
        "ytd_actuals": round(ytd_actuals, 0),
    }


def _model_mape_for_row(row: Dict[str, Any], model: str) -> float | None:
    source = _model_source(model)
    field = source["mape_field"]
    if not field:
        return None
    value = row.get(field)
    parsed = _f(value, 999)
    return round(parsed, 1) if parsed < 999 else None


# ── GET /weekly ─────────────────────────────────────────────────────────────────
@router.get("/weekly")
async def get_weekly(
    product:       Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
    model:         str           = Query("ensemble"),
):
    """
    Weekly actuals + forecast rows for WeeklyForecastChart.
    Actuals rows have Actuals set; forecast rows have Most_Likely/Worst_Case/Best_Case.
    """
    if not _live():
        return _demo("rows")

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)

    try:
        kpi_sql = f"""
            SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
            FROM {FC_TABLE}
            WHERE {_latest_run()}
              {_product_filter(product)} {_geo_filter(sales_market)}
              AND forecast_type IN ('actuals', 'rolling', 'roy')
            ORDER BY ds
        """
        actual_rows_raw, forecast_rows_raw, kpi_rows_raw = await asyncio.gather(
            asyncio.to_thread(execute_query, _normalized_forecast_sql(model, "actuals", product, sales_market)),
            asyncio.to_thread(execute_query, _normalized_forecast_sql(model, eff_forecast_type, product, sales_market)),
            asyncio.to_thread(execute_query, kpi_sql),
        )
    except Exception as exc:
        logger.warning("[forecast/weekly] query failed for model=%s: %s", model, exc)
        return _demo("rows", error=str(exc))

    actual_rows = _normalise_rows(actual_rows_raw, model)
    forecast_rows = _normalise_rows(forecast_rows_raw, model)
    kpis = _summary_kpis(kpi_rows_raw)

    rows = []
    for r in actual_rows:
        rows.append({
            "date": r["ds"],
            "type": "actual",
            "arr_actual": r["actual"],
            "arr_worst": None, "arr_likely": None, "arr_best": None,
        })
    for r in forecast_rows:
        rows.append({
            "date":       r["ds"],
            "type":       "forecast",
            "arr_actual": None,
            "arr_model":  r["value"],
            "arr_likely": r["value"],
            "arr_worst":  r["lower"],
            "arr_best":   r["upper"],
        })

    rows.sort(key=lambda x: x["date"])
    return {
        "source": "live",
        "model": model,
        "forecast_type": eff_forecast_type,
        "rows": rows,
        "kpis": kpis,
    }


# ── GET /monthly ────────────────────────────────────────────────────────────────
@router.get("/monthly")
async def get_monthly(
    product:       Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
):
    """Monthly Actuals + Worst/Most Likely/Best for Monthly table."""
    if not _live():
        return _demo("months")

    forecast_type = _validate_forecast_type(forecast_type)

    pf = _product_filter(product)
    gf = _geo_filter(sales_market)

    act_sql = f"""
        SELECT
            year(ds)                     AS yr,
            quarter(ds)                  AS qtr,
            month(ds)                    AS mth,
            date_format(ds, 'MMMM')      AS month_name,
            SUM(Actuals)                 AS arr_actual
        FROM {FC_TABLE}
        WHERE forecast_type = 'actuals'
          AND {_latest_run()}
          {pf} {gf}
        GROUP BY yr, qtr, mth, month_name
        ORDER BY yr, mth
    """

    fc_sql = f"""
        SELECT
            year(ds)                     AS yr,
            quarter(ds)                  AS qtr,
            month(ds)                    AS mth,
            date_format(ds, 'MMMM')      AS month_name,
            SUM(Worst_Case)              AS arr_worst,
            SUM(Most_Likely)             AS arr_likely,
            SUM(Best_Case)               AS arr_best
        FROM {FC_TABLE}
        WHERE forecast_type = '{forecast_type}'
          AND {_latest_run()}
          {pf} {gf}
        GROUP BY yr, qtr, mth, month_name
        ORDER BY yr, mth
    """

    try:
        act_rows, fc_rows = await asyncio.gather(
            asyncio.to_thread(execute_query, act_sql),
            asyncio.to_thread(execute_query, fc_sql),
        )
    except Exception as exc:
        logger.warning("[forecast/monthly] query failed: %s", exc)
        return _demo("months", error=str(exc))

    act_map = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): _f(r.get("arr_actual"))
        for r in act_rows
    }

    months = []
    for r in fc_rows:
        yr, mth = int(_f(r.get("yr"))), int(_f(r.get("mth")))
        months.append({
            "year":       yr,
            "quarter":    int(_f(r.get("qtr"))),
            "month":      mth,
            "month_name": str(r.get("month_name") or ""),
            "arr_actual": act_map.get((yr, mth)),
            "arr_worst":  _f(r.get("arr_worst")),
            "arr_likely": _f(r.get("arr_likely")),
            "arr_best":   _f(r.get("arr_best")),
        })

    return {"source": "live", "months": months}


# ── GET /ytd ────────────────────────────────────────────────────────────────────
@router.get("/ytd")
async def get_ytd(
    product:       Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
):
    """Cumulative YTD actuals + forecast scenarios for Running Totals chart."""
    if not _live():
        return _demo("rows")

    forecast_type = _validate_forecast_type(forecast_type)

    year = datetime.date.today().year
    pf   = _product_filter(product)
    gf   = _geo_filter(sales_market)

    act_sql = f"""
        SELECT CAST(ds AS STRING) AS d, SUM(Actuals) AS arr
        FROM {FC_TABLE}
        WHERE forecast_type = 'actuals'
          AND year(ds) = {year}
          AND {_latest_run()}
          {pf} {gf}
        GROUP BY ds ORDER BY ds
    """

    fc_sql = f"""
        SELECT CAST(ds AS STRING) AS d,
               SUM(Worst_Case)  AS worst,
               SUM(Most_Likely) AS likely,
               SUM(Best_Case)   AS best
        FROM {FC_TABLE}
        WHERE forecast_type = '{forecast_type}'
          AND year(ds) = {year}
          AND {_latest_run()}
          {pf} {gf}
        GROUP BY ds ORDER BY ds
    """

    try:
        act_rows, fc_rows = await asyncio.gather(
            asyncio.to_thread(execute_query, act_sql),
            asyncio.to_thread(execute_query, fc_sql),
        )
    except Exception as exc:
        logger.warning("[forecast/ytd] query failed: %s", exc)
        return _demo("rows", error=str(exc))

    act_map = {str(r.get("d") or "")[:10]: _f(r.get("arr")) for r in act_rows}
    fc_map  = {str(r.get("d") or "")[:10]: r for r in fc_rows}

    cum_a = cum_w = cum_l = cum_b = 0.0
    rows = []
    for d in sorted(set(list(act_map) + list(fc_map))):
        if d in act_map:
            cum_a += act_map[d]
        fc = fc_map.get(d)
        if fc:
            cum_w += _f(fc.get("worst"))
            cum_l += _f(fc.get("likely"))
            cum_b += _f(fc.get("best"))
        rows.append({
            "date":       d,
            "ytd_actual": round(cum_a, 0) if d in act_map else None,
            "ytd_worst":  round(cum_w, 0) if fc else None,
            "ytd_likely": round(cum_l, 0) if fc else None,
            "ytd_best":   round(cum_b, 0) if fc else None,
        })

    return {"source": "live", "rows": rows}


# ── GET /by-product ─────────────────────────────────────────────────────────────
@router.get("/by-product")
async def get_by_product(
    model:         str = Query("ensemble"),
    forecast_type: str = Query("rolling"),
    sales_market:  Optional[str] = Query(None),
):
    """Total forecast per product group (UCC/ITSG) + by sales_market."""
    if not _live():
        return _demo("data")

    model = _validate_model(model)
    forecast_type = _validate_forecast_type(forecast_type)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)

    try:
        lb_rows_raw = await asyncio.to_thread(execute_query, f"""
            SELECT product, sales_market, mape_ets, mape_prophet, mape_lightgbm, mape_chronos, best_mape, best_model
            FROM {LB_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
        """)
    except Exception as exc:
        logger.warning("[forecast/by-product] leaderboard fetch failed (continuing): %s", exc)
        lb_rows_raw = []
    lb_rows = {
        (str(r.get("product") or ""), str(r.get("sales_market") or "")): r
        for r in lb_rows_raw
    }

    source = _model_source(model)
    table = source["table"]
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]

    where_parts = []
    if source["has_forecast_type"]:
        where_parts.append(f"forecast_type = '{eff_forecast_type}'")
        where_parts.append(_latest_run())
    else:
        where_parts.append("COALESCE(CAST(Actuals AS DOUBLE), 0) = 0")

    prod_sql = f"""
        SELECT
            product,
            SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS arr_worst,
            SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr_likely,
            SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS arr_best
        FROM {table}
        WHERE {' AND '.join(where_parts)}
          AND sales_market = 'Total'
          AND product IN ('UCC','ITSG')
        GROUP BY product
        ORDER BY product
    """

    norm_geo_expr = _normalized_market_expr("sales_market")
    geo_sql = f"""
        SELECT
            {norm_geo_expr} AS sales_market,
            SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS arr_worst,
            SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr_likely,
            SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS arr_best
        FROM {table}
        WHERE {' AND '.join(where_parts)}
          AND product = 'Total'
          AND {norm_geo_expr} IN ('NA','EMEA','APAC','LATAM','Unknown')
        GROUP BY {norm_geo_expr}
        ORDER BY arr_likely DESC
    """

    try:
        prod_rows, geo_rows = await asyncio.gather(
            asyncio.to_thread(execute_query, prod_sql),
            asyncio.to_thread(execute_query, geo_sql),
        )
    except Exception as exc:
        logger.warning("[forecast/by-product] query failed for model=%s: %s", model, exc)
        return _demo("data", error=str(exc))

    by_product = [{
        "product":     str(r.get("product") or ""),
        "product_line": str(r.get("product") or ""),
        "arr_worst":   _f(r.get("arr_worst")),
        "arr_likely":  _f(r.get("arr_likely")),
        "arr_best":    _f(r.get("arr_best")),
        "best_mape":   _model_mape_for_row(lb_rows.get((str(r.get("product") or ""), "Total"), {}), model),
    } for r in prod_rows]

    by_geo = [{
        "sales_market": _normalize_market_value(str(r.get("sales_market") or "")),
        "arr_worst":    _f(r.get("arr_worst")),
        "arr_likely":   _f(r.get("arr_likely")),
        "arr_best":     _f(r.get("arr_best")),
    } for r in geo_rows]

    return {"source": "live", "by_product": by_product,
            "by_product_line": by_product, "by_geo": by_geo}


@router.get("/models")
async def get_models():
    """Return registry-backed forecast models with source table and freshness metadata."""
    if not _live():
        return {"source": "demo", "models": []}

    # Canonical panel freshness is the arr_forecast_v2 run_date (the table the UI is based on).
    canonical_refresh: Optional[str] = None
    try:
        canonical_rows = await asyncio.to_thread(
            execute_query,
            f"SELECT MAX(CAST(run_date AS STRING)) AS freshness FROM {FC_TABLE}",
        )
        canonical_refresh = str((canonical_rows[0] if canonical_rows else {}).get("freshness") or "")[:10] or None
    except Exception:
        canonical_refresh = None

    freshness_cache: Dict[str, Optional[str]] = {}
    for key, source in MODEL_SOURCES.items():
        table = source["table"]
        if table in freshness_cache:
            continue
        freshness_sql = (
            f"SELECT MAX(CAST(run_date AS STRING)) AS freshness FROM {table}"
            if source["has_forecast_type"]
            else f"SELECT MAX(CAST(ds AS STRING)) AS freshness FROM {table}"
        )
        try:
            rows = await asyncio.to_thread(execute_query, freshness_sql)
            freshness_cache[table] = str((rows[0] if rows else {}).get("freshness") or "")[:10] or None
        except Exception:
            freshness_cache[table] = None

    models = []
    for key, source in MODEL_SOURCES.items():
        table_refresh = freshness_cache.get(source["table"])
        models.append({
            "key": key,
            "display_name": source["display_name"],
            "source_table": source["table"].replace('`', ''),
            # Keep a single "Updated <date>" across model switches in the header.
            "latest_refresh": canonical_refresh or table_refresh,
            "table_latest_refresh": table_refresh,
            "has_forecast_type": source["has_forecast_type"],
            "supported_forecast_types": ["actuals", "rolling", "roy"] if source["has_forecast_type"] else ["actuals", "rolling"],
        })

    return {"source": "live", "models": models}


# ── GET /historical ─────────────────────────────────────────────────────────────
@router.get("/historical")
async def get_historical(
    product:      Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
):
    """Multi-year weekly actuals for Historical Trend + Seasonality charts."""
    if not _live():
        return _demo("rows")

    pf = _product_filter(product)
    gf = _geo_filter(sales_market)

    sql = f"""
        SELECT
            CAST(ds AS STRING)          AS date,
            year(ds)                    AS year,
            weekofyear(ds)              AS iso_week,
            quarter(ds)                 AS quarter,
            SUM(Actuals)                AS arr
        FROM {FC_TABLE}
        WHERE forecast_type = 'actuals'
          AND {_latest_run()}
          {pf} {gf}
        GROUP BY ds, year(ds), weekofyear(ds), quarter(ds)
        ORDER BY ds
    """

    try:
        rows_raw = await asyncio.to_thread(execute_query, sql)
    except Exception as exc:
        logger.warning("[forecast/historical] query failed: %s", exc)
        return _demo("rows", error=str(exc))
    rows = [{
        "date":     str(r.get("date") or "")[:10],
        "year":     int(_f(r.get("year"))),
        "iso_week": int(_f(r.get("iso_week"))),
        "quarter":  int(_f(r.get("quarter"))),
        "arr":      _f(r.get("arr")),
    } for r in rows_raw]

    return {"source": "live", "rows": rows}


# ── GET /leaderboard ────────────────────────────────────────────────────────────
@router.get("/leaderboard")
async def get_leaderboard():
    """MAPE leaderboard — all product × sales_market slices."""
    if not _live():
        return _demo("data")

    sql = f"""
        SELECT
            product,
            {_normalized_market_expr('sales_market')} AS sales_market,
            AVG(CAST(mape_ets AS DOUBLE)) AS mape_ets,
            AVG(CAST(mape_prophet AS DOUBLE)) AS mape_prophet,
            AVG(CAST(mape_lightgbm AS DOUBLE)) AS mape_lightgbm,
            AVG(CAST(mape_chronos AS DOUBLE)) AS mape_chronos,
            AVG(CAST(best_mape AS DOUBLE)) AS best_mape,
            MAX(best_model) AS best_model
        FROM {LB_TABLE}
        WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
        GROUP BY product, {_normalized_market_expr('sales_market')}
        ORDER BY best_mape
    """

    try:
        rows_raw = await asyncio.to_thread(execute_query, sql)
    except Exception as exc:
        logger.warning("[forecast/leaderboard] query failed: %s", exc)
        return _demo("data", error=str(exc))
    data = [{
        "product":        str(r.get("product") or ""),
        "sales_market":   _normalize_market_value(str(r.get("sales_market") or "")),
        "ETS":            _f(r.get("mape_ets"),    999),
        "Prophet":        _f(r.get("mape_prophet"), 999),
        "LightGBM":       _f(r.get("mape_lightgbm"),999),
        "Chronos":        _f(r.get("mape_chronos"), 999),
        "best_mape":      _f(r.get("best_mape"),    999),
        "best_model":     str(r.get("best_model") or ""),
    } for r in rows_raw]

    return {"source": "live", "data": data}
