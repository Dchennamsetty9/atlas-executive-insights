"""
Forecast v2 — rich endpoints for the ForecastingPanel UI.

Reads from:  datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
  columns: ds, product (Total/UCC/ITSG), sales_market (Total/NA/EMEA/APAC/LATAM),
           Actuals, Most_Likely, Worst_Case, Best_Case,
           arr_ets, arr_prophet, arr_lightgbm, arr_chronos,
           mape_ets, mape_prophet, mape_lightgbm, mape_chronos,
           forecast_type (actuals|rolling|roy), run_date

Leaderboard: datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard
"""

import asyncio, os, datetime
from typing import Optional

from fastapi import APIRouter, Query
from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/forecast/v2", tags=["forecast-v2"])

GOLD      = (os.getenv("FORECAST_CATALOG", "datagroup_mdl") + "." +
             os.getenv("FORECAST_SCHEMA",  "mdl_sales_analytics"))
FC_TABLE  = f"`{GOLD}`.`arr_forecast_v2`"
LB_TABLE  = f"`{GOLD}`.`arr_forecast_v2_leaderboard`"


def _live() -> bool:
    return token_available() and (
        bool(os.getenv("DATABRICKS_HOST")) or
        os.getenv("FORCE_LIVE_DATA", "").lower() == "true"
    )

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None and v != "" else default
    except (TypeError, ValueError):
        return default

def _demo(key: str):
    return {"source": "demo", "live_mode_available": False,
            "error": "Databricks unavailable", key: []}

def _product_filter(product, col="product"):
    if not product or product == "All":
        return ""
    return f"AND {col} = '{product.replace(chr(39), chr(39)*2)}'"

def _geo_filter(geo, col="sales_market"):
    if not geo or geo == "All":
        return ""
    return f"AND {col} = '{geo.replace(chr(39), chr(39)*2)}'"

def _latest_run():
    return f"run_date = (SELECT MAX(run_date) FROM {FC_TABLE})"


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

    model_col = {
        "ets": "arr_ets", "prophet": "arr_prophet",
        "lightgbm": "arr_lightgbm", "chronos": "arr_chronos",
        "ensemble": "Most_Likely",
    }.get(model, "Most_Likely")

    pf = _product_filter(product)
    gf = _geo_filter(sales_market)

    # Historical actuals (last 78 weeks)
    act_sql = f"""
        SELECT
            CAST(ds AS STRING) AS date,
            SUM(Actuals)       AS arr_actual
        FROM {FC_TABLE}
        WHERE forecast_type = 'actuals'
          AND {_latest_run()}
          AND ds >= dateadd(WEEK, -78, current_date())
          {pf} {gf}
        GROUP BY ds
        ORDER BY ds
    """

    # Forecast rows
    fc_sql = f"""
        SELECT
            CAST(ds AS STRING) AS date,
            SUM({model_col})   AS arr_model,
            SUM(Most_Likely)   AS arr_likely,
            SUM(Worst_Case)    AS arr_worst,
            SUM(Best_Case)     AS arr_best
        FROM {FC_TABLE}
        WHERE forecast_type = '{forecast_type}'
          AND {_latest_run()}
          {pf} {gf}
        GROUP BY ds
        ORDER BY ds
    """

    act_rows, fc_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, act_sql),
        asyncio.to_thread(execute_query, fc_sql),
    )

    rows = []
    for r in act_rows:
        rows.append({
            "date": str(r.get("date") or "")[:10],
            "type": "actual",
            "arr_actual": _f(r.get("arr_actual")),
            "arr_worst": None, "arr_likely": None, "arr_best": None,
        })
    for r in fc_rows:
        rows.append({
            "date":       str(r.get("date") or "")[:10],
            "type":       "forecast",
            "arr_actual": None,
            "arr_model":  _f(r.get("arr_model")),
            "arr_likely": _f(r.get("arr_likely")),
            "arr_worst":  _f(r.get("arr_worst")),
            "arr_best":   _f(r.get("arr_best")),
        })

    rows.sort(key=lambda x: x["date"])
    return {"source": "live", "model": model, "forecast_type": forecast_type, "rows": rows}


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

    act_rows, fc_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, act_sql),
        asyncio.to_thread(execute_query, fc_sql),
    )

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

    act_rows, fc_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, act_sql),
        asyncio.to_thread(execute_query, fc_sql),
    )

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
    forecast_type: str = Query("rolling"),
    sales_market:  Optional[str] = Query(None),
):
    """Total forecast per product group (UCC/ITSG) + by sales_market."""
    if not _live():
        return _demo("data")

    gf = _geo_filter(sales_market)

    # Per product group (UCC / ITSG), geo = Total
    prod_sql = f"""
        SELECT
            product,
            SUM(Worst_Case)  AS arr_worst,
            SUM(Most_Likely) AS arr_likely,
            SUM(Best_Case)   AS arr_best,
            AVG(mape_ets)    AS mape_ets,
            AVG(mape_prophet) AS mape_prophet,
            AVG(mape_lightgbm) AS mape_lightgbm,
            AVG(mape_chronos)  AS mape_chronos
        FROM {FC_TABLE}
        WHERE forecast_type = '{forecast_type}'
          AND sales_market = 'Total'
          AND product IN ('UCC','ITSG')
          AND {_latest_run()}
        GROUP BY product
        ORDER BY product
    """

    # Per geo (Total across products)
    geo_sql = f"""
        SELECT
            sales_market,
            SUM(Worst_Case)  AS arr_worst,
            SUM(Most_Likely) AS arr_likely,
            SUM(Best_Case)   AS arr_best
        FROM {FC_TABLE}
        WHERE forecast_type = '{forecast_type}'
          AND product = 'Total'
          AND sales_market IN ('NA','EMEA','APAC','LATAM')
          AND {_latest_run()}
        GROUP BY sales_market
        ORDER BY arr_likely DESC
    """

    prod_rows, geo_rows = await asyncio.gather(
        asyncio.to_thread(execute_query, prod_sql),
        asyncio.to_thread(execute_query, geo_sql),
    )

    def mape_min(r):
        vals = [_f(r.get(c), 999) for c in
                ["mape_ets","mape_prophet","mape_lightgbm","mape_chronos"]]
        valid = [v for v in vals if v < 999]
        return round(min(valid), 1) if valid else None

    by_product = [{
        "product":     str(r.get("product") or ""),
        "product_line": str(r.get("product") or ""),
        "arr_worst":   _f(r.get("arr_worst")),
        "arr_likely":  _f(r.get("arr_likely")),
        "arr_best":    _f(r.get("arr_best")),
        "best_mape":   mape_min(r),
    } for r in prod_rows]

    by_geo = [{
        "sales_market": str(r.get("sales_market") or ""),
        "arr_worst":    _f(r.get("arr_worst")),
        "arr_likely":   _f(r.get("arr_likely")),
        "arr_best":     _f(r.get("arr_best")),
    } for r in geo_rows]

    return {"source": "live", "by_product": by_product,
            "by_product_line": by_product, "by_geo": by_geo}


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

    rows_raw = await asyncio.to_thread(execute_query, sql)
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
            product, sales_market,
            mape_ets, mape_prophet, mape_lightgbm, mape_chronos,
            best_mape, best_model
        FROM {LB_TABLE}
        WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
        ORDER BY best_mape
    """

    rows_raw = await asyncio.to_thread(execute_query, sql)
    data = [{
        "product":        str(r.get("product") or ""),
        "sales_market":   str(r.get("sales_market") or ""),
        "ETS":            _f(r.get("mape_ets"),    999),
        "Prophet":        _f(r.get("mape_prophet"), 999),
        "LightGBM":       _f(r.get("mape_lightgbm"),999),
        "Chronos":        _f(r.get("mape_chronos"), 999),
        "best_mape":      _f(r.get("best_mape"),    999),
        "best_model":     str(r.get("best_model") or ""),
    } for r in rows_raw]

    return {"source": "live", "data": data}
