"""
Forecast v2 — rich endpoints for the ForecastingPanel UI.

New Delta tables (arr_forecast_ensemble_v2):
  run_timestamp, forecast_type (rolling|roy), product, product_line,
  forecast_week_start, forecast_step, horizon_weeks,
  arr_worst_case, arr_most_likely, arr_best_case, arr_ensemble,
  arr_ets, arr_prophet, arr_lightgbm, arr_chronos,
  mape_ets, mape_prophet, mape_lightgbm, mape_chronos, ensemble_weights

New Delta table (arr_actuals_weekly):
  week_start, product, product_line, arr_actual, deal_count,
  year, quarter, iso_week, is_quarter_end_week
"""

import asyncio, json, os
from typing import Any, Optional

from fastapi import APIRouter, Query
from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/forecast/v2", tags=["forecast-v2"])

GOLD = os.getenv("FORECAST_CATALOG", "datagroup_mdl") + "." + \
       os.getenv("FORECAST_SCHEMA",  "mdl_sales_analytics")

FC_TABLE      = f"`{GOLD.replace('.', '`.`')}`.`arr_forecast_ensemble_v2`"
ACTUALS_TABLE = f"`{GOLD.replace('.', '`.`')}`.`arr_actuals_weekly`"
LB_TABLE      = f"`{GOLD.replace('.', '`.`')}`.`arr_forecast_leaderboard_v2`"


def _live() -> bool:
    return token_available() and (
        bool(os.getenv("DATABRICKS_HOST")) or
        os.getenv("FORCE_LIVE_DATA", "").lower() == "true"
    )

def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None and v != "" else default
    except (TypeError, ValueError):
        return default

def _demo_response(key: str):
    return {"source": "demo", "live_mode_available": False,
            "error": "Databricks unavailable", "data": None, key: []}


# ── Weekly forecast with scenarios ─────────────────────────────────────────────
@router.get("/weekly")
async def get_weekly_forecast(
    product:       Optional[str] = Query(None),
    product_line:  Optional[str] = Query(None),
    geo:           Optional[str] = Query(None),
    forecast_type: str           = Query("rolling", regex="^(rolling|roy)$"),
    model:         str           = Query("ensemble", regex="^(ets|prophet|lightgbm|chronos|ensemble)$"),
):
    """
    Weekly forecast rows — worst_case / most_likely / best_case / actuals.
    Returns data shaped for the WeeklyForecastChart and ForecastVsActuals charts.
    """
    if not _live():
        return _demo_response("rows")

    filters = [f"forecast_type = '{forecast_type}'",
               "run_timestamp = (SELECT MAX(run_timestamp) FROM " + FC_TABLE + ")"]
    if product:
        filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")

    model_col = {
        "ets": "arr_ets", "prophet": "arr_prophet",
        "lightgbm": "arr_lightgbm", "chronos": "arr_chronos",
        "ensemble": "arr_ensemble",
    }[model]

    fc_sql = f"""
        SELECT
            CAST(forecast_week_start AS STRING) AS week_start,
            SUM({model_col})      AS arr_model,
            SUM(arr_worst_case)   AS arr_worst,
            SUM(arr_most_likely)  AS arr_likely,
            SUM(arr_best_case)    AS arr_best,
            SUM(arr_ensemble)     AS arr_ensemble
        FROM {FC_TABLE}
        WHERE {" AND ".join(filters)}
        GROUP BY forecast_week_start
        ORDER BY forecast_week_start
    """

    # Historical actuals: last 52 weeks
    act_filters = ["week_start >= dateadd(WEEK, -52, current_date())"]
    if product:
        act_filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        act_filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")

    act_sql = f"""
        SELECT
            CAST(week_start AS STRING) AS week_start,
            SUM(arr_actual) AS arr_actual,
            SUM(deal_count) AS deal_count,
            MAX(year)       AS year,
            MAX(quarter)    AS quarter,
            MAX(iso_week)   AS iso_week,
            MAX(is_quarter_end_week) AS is_qe
        FROM {ACTUALS_TABLE}
        WHERE {" AND ".join(act_filters)}
        GROUP BY week_start
        ORDER BY week_start
    """

    fc_rows, act_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, fc_sql),
        asyncio.to_thread(execute_query, act_sql),
    )

    actuals_map = {
        str(r.get("week_start") or "")[:10]: {
            "arr_actual":  _f(r.get("arr_actual")),
            "deal_count":  int(_f(r.get("deal_count"))),
            "year":        int(_f(r.get("year"))),
            "quarter":     int(_f(r.get("quarter"))),
            "iso_week":    int(_f(r.get("iso_week"))),
            "is_qe":       int(_f(r.get("is_qe"))),
        }
        for r in act_rows
    }

    rows = []
    for r in act_rows:
        d = str(r.get("week_start") or "")[:10]
        if d:
            rows.append({
                "date": d, "type": "actual",
                "arr_actual":  _f(r.get("arr_actual")),
                "arr_worst":   None, "arr_likely": None, "arr_best": None,
                "year": int(_f(r.get("year"))), "quarter": int(_f(r.get("quarter"))),
                "iso_week": int(_f(r.get("iso_week"))), "is_qe": int(_f(r.get("is_qe"))),
            })
    for r in fc_rows:
        d = str(r.get("week_start") or "")[:10]
        if d:
            rows.append({
                "date": d, "type": "forecast",
                "arr_actual":  actuals_map.get(d, {}).get("arr_actual"),
                "arr_model":   _f(r.get("arr_model")),
                "arr_worst":   _f(r.get("arr_worst")),
                "arr_likely":  _f(r.get("arr_likely")),
                "arr_best":    _f(r.get("arr_best")),
                "arr_ensemble":_f(r.get("arr_ensemble")),
                "year": actuals_map.get(d, {}).get("year",
                         int(d[:4]) if d else 0),
                "quarter": actuals_map.get(d, {}).get("quarter", 0),
                "iso_week": actuals_map.get(d, {}).get("iso_week", 0),
                "is_qe": actuals_map.get(d, {}).get("is_qe", 0),
            })

    rows.sort(key=lambda x: x["date"])
    return {"source": "live", "model": model, "forecast_type": forecast_type, "rows": rows}


# ── Monthly table ──────────────────────────────────────────────────────────────
@router.get("/monthly")
async def get_monthly_table(
    product:       Optional[str] = Query(None),
    product_line:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
):
    """Monthly aggregated actuals + worst/likely/best forecast — for the Monthly table."""
    if not _live():
        return _demo_response("months")

    fc_filters = [
        f"forecast_type = '{forecast_type}'",
        "run_timestamp = (SELECT MAX(run_timestamp) FROM " + FC_TABLE + ")",
    ]
    if product:
        fc_filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        fc_filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")

    fc_sql = f"""
        SELECT
            year(forecast_week_start)    AS yr,
            quarter(forecast_week_start) AS qtr,
            month(forecast_week_start)   AS mth,
            date_format(forecast_week_start, 'MMMM') AS month_name,
            SUM(arr_worst_case)  AS arr_worst,
            SUM(arr_most_likely) AS arr_likely,
            SUM(arr_best_case)   AS arr_best
        FROM {FC_TABLE}
        WHERE {" AND ".join(fc_filters)}
        GROUP BY yr, qtr, mth, month_name
        ORDER BY yr, mth
    """

    act_filters = []
    if product:
        act_filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        act_filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")
    act_where = ("WHERE " + " AND ".join(act_filters)) if act_filters else ""

    act_sql = f"""
        SELECT
            year       AS yr,
            quarter    AS qtr,
            month(week_start) AS mth,
            date_format(week_start, 'MMMM') AS month_name,
            SUM(arr_actual) AS arr_actual
        FROM {ACTUALS_TABLE}
        {act_where}
        GROUP BY year, quarter, month(week_start), date_format(week_start, 'MMMM')
        ORDER BY yr, mth
    """

    fc_rows, act_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, fc_sql),
        asyncio.to_thread(execute_query, act_sql),
    )

    # Merge by yr+mth key
    act_map = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): _f(r.get("arr_actual"))
        for r in act_rows
    }

    months = []
    for r in fc_rows:
        yr, mth = int(_f(r.get("yr"))), int(_f(r.get("mth")))
        months.append({
            "year":        yr,
            "quarter":     int(_f(r.get("qtr"))),
            "month":       mth,
            "month_name":  str(r.get("month_name") or ""),
            "arr_actual":  act_map.get((yr, mth)),
            "arr_worst":   _f(r.get("arr_worst")),
            "arr_likely":  _f(r.get("arr_likely")),
            "arr_best":    _f(r.get("arr_best")),
        })

    return {"source": "live", "months": months}


# ── YTD running totals ─────────────────────────────────────────────────────────
@router.get("/ytd")
async def get_ytd_running_totals(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    forecast_type: str          = Query("rolling"),
):
    """Cumulative YTD actuals + forecast scenarios — for the Running Totals chart."""
    if not _live():
        return _demo_response("rows")

    import datetime
    year = datetime.date.today().year

    act_filters = [f"year = {year}"]
    if product:
        act_filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        act_filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")

    act_sql = f"""
        SELECT CAST(week_start AS STRING) AS d, SUM(arr_actual) AS arr
        FROM {ACTUALS_TABLE}
        WHERE {" AND ".join(act_filters)}
        GROUP BY week_start ORDER BY week_start
    """

    fc_filters = [
        f"year(forecast_week_start) = {year}",
        f"forecast_type = '{forecast_type}'",
        "run_timestamp = (SELECT MAX(run_timestamp) FROM " + FC_TABLE + ")",
    ]
    if product:
        fc_filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        fc_filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")

    fc_sql = f"""
        SELECT CAST(forecast_week_start AS STRING) AS d,
               SUM(arr_worst_case) AS worst, SUM(arr_most_likely) AS likely,
               SUM(arr_best_case)  AS best
        FROM {FC_TABLE}
        WHERE {" AND ".join(fc_filters)}
        GROUP BY forecast_week_start ORDER BY forecast_week_start
    """

    act_rows, fc_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, act_sql),
        asyncio.to_thread(execute_query, fc_sql),
    )

    cum_actual  = 0.0
    cum_worst   = 0.0
    cum_likely  = 0.0
    cum_best    = 0.0
    act_map     = {str(r.get("d") or "")[:10]: _f(r.get("arr")) for r in act_rows}
    fc_map      = {str(r.get("d") or "")[:10]: r for r in fc_rows}

    all_dates = sorted(set(list(act_map) + list(fc_map)))
    rows = []
    for d in all_dates:
        if d in act_map:
            cum_actual += act_map[d]
        fc = fc_map.get(d)
        if fc:
            cum_worst  += _f(fc.get("worst"))
            cum_likely += _f(fc.get("likely"))
            cum_best   += _f(fc.get("best"))
        rows.append({
            "date":        d,
            "ytd_actual":  round(cum_actual,  0) if d in act_map else None,
            "ytd_worst":   round(cum_worst,   0) if fc else None,
            "ytd_likely":  round(cum_likely,  0) if fc else None,
            "ytd_best":    round(cum_best,    0) if fc else None,
        })

    return {"source": "live", "rows": rows}


# ── By-product breakdown ───────────────────────────────────────────────────────
@router.get("/by-product")
async def get_by_product(forecast_type: str = Query("rolling")):
    """13-week total forecast per product and per product_line (ITSG/UCC)."""
    if not _live():
        return _demo_response("products")

    sql = f"""
        SELECT
            product, product_line,
            SUM(arr_worst_case)  AS arr_worst,
            SUM(arr_most_likely) AS arr_likely,
            SUM(arr_best_case)   AS arr_best,
            AVG(mape_ets)        AS mape_ets,
            AVG(mape_prophet)    AS mape_prophet,
            AVG(mape_lightgbm)   AS mape_lgb,
            AVG(mape_chronos)    AS mape_chronos
        FROM {FC_TABLE}
        WHERE forecast_type = '{forecast_type}'
          AND run_timestamp = (SELECT MAX(run_timestamp) FROM {FC_TABLE})
        GROUP BY product, product_line
        ORDER BY arr_likely DESC
    """
    rows = await asyncio.to_thread(execute_query, sql)
    products = [
        {
            "product":       str(r.get("product") or ""),
            "product_line":  str(r.get("product_line") or ""),
            "arr_worst":     _f(r.get("arr_worst")),
            "arr_likely":    _f(r.get("arr_likely")),
            "arr_best":      _f(r.get("arr_best")),
            "best_mape":     min(
                _f(r.get("mape_ets"),     999),
                _f(r.get("mape_prophet"), 999),
                _f(r.get("mape_lgb"),     999),
                _f(r.get("mape_chronos"), 999),
            ),
        }
        for r in rows
    ]
    # Product-line rollup
    line_totals: dict[str, dict] = {}
    for p in products:
        pl = p["product_line"]
        if pl not in line_totals:
            line_totals[pl] = {"product_line": pl, "products": [],
                                "arr_worst": 0, "arr_likely": 0, "arr_best": 0}
        line_totals[pl]["arr_worst"]  += p["arr_worst"]
        line_totals[pl]["arr_likely"] += p["arr_likely"]
        line_totals[pl]["arr_best"]   += p["arr_best"]
        line_totals[pl]["products"].append(p)

    return {
        "source": "live",
        "forecast_type": forecast_type,
        "by_product":     products,
        "by_product_line": list(line_totals.values()),
    }


# ── Historical multi-year actuals ──────────────────────────────────────────────
@router.get("/historical")
async def get_historical(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
):
    """
    Weekly actuals by year (2022-present) for the Historical Trend
    and Historical Seasonality charts.
    """
    if not _live():
        return _demo_response("rows")

    filters = []
    if product:
        filters.append(f"product = '{product.replace(chr(39), chr(39)*2)}'")
    if product_line:
        filters.append(f"product_line = '{product_line.replace(chr(39), chr(39)*2)}'")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = f"""
        SELECT
            CAST(week_start AS STRING) AS week_start,
            year, quarter, iso_week,
            SUM(arr_actual)  AS arr,
            SUM(deal_count)  AS deal_count,
            MAX(is_quarter_end_week) AS is_qe
        FROM {ACTUALS_TABLE}
        {where}
        GROUP BY week_start, year, quarter, iso_week
        ORDER BY week_start
    """
    rows = await asyncio.to_thread(execute_query, sql)
    data = [
        {
            "date":      str(r.get("week_start") or "")[:10],
            "year":      int(_f(r.get("year"))),
            "quarter":   int(_f(r.get("quarter"))),
            "iso_week":  int(_f(r.get("iso_week"))),
            "arr":       _f(r.get("arr")),
            "deal_count":int(_f(r.get("deal_count"))),
            "is_qe":     int(_f(r.get("is_qe"))),
        }
        for r in rows
    ]
    return {"source": "live", "rows": data}


# ── Leaderboard ────────────────────────────────────────────────────────────────
@router.get("/leaderboard")
async def get_leaderboard_v2():
    if not _live():
        return _demo_response("data")
    rows = await asyncio.to_thread(execute_query, f"""
        SELECT product, product_line,
               `ETS`, `Prophet`, `LightGBM`, `Chronos`,
               best_model, best_mape
        FROM {LB_TABLE}
        ORDER BY best_mape ASC
    """)
    data = [
        {
            "product":      str(r.get("product") or ""),
            "product_line": str(r.get("product_line") or ""),
            "ETS":          _f(r.get("ETS")),
            "Prophet":      _f(r.get("Prophet")),
            "LightGBM":     _f(r.get("LightGBM")),
            "Chronos":      _f(r.get("Chronos")),
            "best_model":   str(r.get("best_model") or ""),
            "best_mape":    _f(r.get("best_mape")),
        }
        for r in rows
    ]
    return {"source": "live", "data": data}
