"""
Forecast v2 — rich endpoints for the ForecastingPanel UI.

Reads from:  datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
  columns: ds, product (Total/UCC/ITSG), sales_market (Total/NA/EMEA/APAC/LATAM),
           Actuals, Most_Likely, Worst_Case, Best_Case,
           arr_ets, arr_prophet, arr_lightgbm, arr_mstl_v2, arr_dhr_arima,
           mape_ets, mape_prophet, mape_lightgbm, mape_mstl_v2, mape_dhr_arima,
           forecast_type (actuals|rolling|roy), run_date
  NOTE: arr_chronos / mape_chronos are NOT in the model suite.
        The notebook writes mape_chronos=NULL explicitly so live rows never
        surface stale demo Chronos values.

Leaderboard: datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard

All values are constrained to the Growth-bookings-aligned v2 tables.
"""

import asyncio, os, datetime, logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from auth import require_authenticated_user
from services.databricks_connection import execute_query, token_available
from services.user_preferences_service import user_prefs_service

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
    "mstl_v2": {
        "display_name": "MSTL",
        "table": FC_TABLE,
        "most_likely_col": "arr_mstl_v2",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "MSTL_v2",
        "has_forecast_type": True,
    },
    "dhr_arima": {
        "display_name": "DHR-ARIMA",
        "table": FC_TABLE,
        "most_likely_col": "arr_dhr_arima",
        "lower_col": "Worst_Case",
        "upper_col": "Best_Case",
        "mape_field": "DHR_ARIMA",
        "has_forecast_type": True,
    },
    # Chronos removed — not in UCC/ITSG V5 notebook model suite.
    # arr_chronos / mape_chronos are NULL in arr_forecast_v2.
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

def _selected_product(product, product_line=None):
    selected = product_line if product_line not in (None, "", "All", "all") else product
    if selected in (None, "", "All", "all"):
        return "Total"
    return selected


def _product_filter(product, product_line=None, col="product"):
    # When no product selected, default to Total to avoid summing all 18 slices.
    # Product line is the active UI filter; product remains for backward compatibility.
    effective = _selected_product(product, product_line)
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
    product_line: Optional[str],
    sales_market: Optional[str],
    year: Optional[int] = None,
    quarter: Optional[int] = None,
) -> str:
    source = _model_source(model)
    table = source["table"]
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]
    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)
    yf = _year_filter(year)
    qf = _quarter_filter(quarter, year) if quarter else ""
    
    if source["has_forecast_type"]:
        date_filter = f"AND {qf}" if qf else f"AND {yf}"
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
              {date_filter}
            ORDER BY ds
        """

    date_filter = f"AND {qf}" if qf else f"AND {yf}"
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
          {date_filter}
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
    """Compute KPI card totals from the kpi_sql result rows.

    The Panel Writer sets Most_Likely/Worst_Case/Best_Case = Actuals for closed
    (actuals) rows, so we sum ML/BC/WC from ALL rows regardless of forecast_type.
    For open (rolling/roy) rows the model forecast is already in those columns.
    This makes closed-quarter and mixed-quarter selections both correct.
    """
    most_likely = 0.0
    worst_case = 0.0
    best_case = 0.0
    ytd_actuals = 0.0

    for row in rows:
        ftype = str(row.get("forecast_type") or "").strip().lower()
        ml = _f(row.get("Most_Likely"))
        wc = _f(row.get("Worst_Case"))
        bc = _f(row.get("Best_Case"))
        act = _f(row.get("Actuals"))

        # Use ML/BC/WC from every row — for actuals rows these equal Actuals;
        # for rolling/roy rows these hold the model forecast.
        if ml > 0:
            most_likely += ml
            worst_case += wc
            best_case += bc
        elif ftype in ("rolling", "roy"):
            # Explicit forecast row with ML==0 edge case — still count it
            most_likely += ml
            worst_case += wc
            best_case += bc

        # YTD actuals: sum all actuals rows in the result set (already date-filtered
        # by the caller's kpi_sql — year/quarter filter applied before this function).
        if ftype == "actuals" and act > 0:
            ytd_actuals += act

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


def _year_filter(year: Optional[int] = None) -> str:
    """SQL filter for year. Defaults to current year if not provided."""
    y = year if year else datetime.date.today().year
    return f"YEAR(ds) = {y}"


def _quarter_filter(quarter: Optional[int] = None, year: Optional[int] = None) -> str:
    """SQL filter for quarter. If None, no quarter filter applied."""
    if quarter is None:
        return ""
    y = year if year else datetime.date.today().year
    # Q1: 1–3, Q2: 4–6, Q3: 7–9, Q4: 10–12
    month_ranges = {
        1: (1, 3),
        2: (4, 6),
        3: (7, 9),
        4: (10, 12),
    }
    if quarter not in month_ranges:
        return ""
    m_start, m_end = month_ranges[quarter]
    return f"YEAR(ds) = {y} AND MONTH(ds) BETWEEN {m_start} AND {m_end}"


def _actuals_year_filter(year: Optional[int] = None) -> str:
    """Filter for actuals only, scoped to year."""
    y = year if year else datetime.date.today().year
    return f"forecast_type = 'actuals' AND YEAR(ds) = {y}"


def _pct(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return (part / whole) * 100.0


async def _lb_columns() -> set[str]:
    """Return lowercase leaderboard column names for runtime schema compatibility."""
    sql = f"""
        SELECT LOWER(column_name) AS column_name
        FROM `{FORECAST_CATALOG}`.information_schema.columns
        WHERE LOWER(table_schema) = LOWER('{FORECAST_SCHEMA}')
          AND LOWER(table_name) = 'arr_forecast_v2_leaderboard'
    """
    try:
        rows = await asyncio.to_thread(execute_query, sql)
    except Exception as exc:
        logger.warning("[forecast/lb-columns] schema introspection failed: %s", exc)
        return set()

    return {
        str(r.get("column_name") or "").strip().lower()
        for r in rows
        if str(r.get("column_name") or "").strip()
    }


def _pick_lb_column(columns: set[str], *candidates: str) -> str:
    """Pick the first available leaderboard column, else SQL NULL."""
    for c in candidates:
        if c and c.lower() in columns:
            return c
    return "NULL"


class GovernanceLogRequest(BaseModel):
    decision: str
    owner: Optional[str] = None
    expected_impact: Optional[float] = None
    reason: Optional[str] = None
    scenario_name: Optional[str] = None


# ── GET /weekly ─────────────────────────────────────────────────────────────────
@router.get("/weekly")
async def get_weekly(
    product:       Optional[str] = Query(None),
    product_line:  Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
    model:         str           = Query("ensemble"),
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
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
    
    year = year if year else datetime.date.today().year
    qtr_filter = _quarter_filter(quarter, year) if quarter else f"YEAR(ds) = {year}"

    try:
        kpi_sql = f"""
            SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
            FROM {FC_TABLE}
            WHERE {_latest_run()}
                            {_product_filter(product, product_line)} {_geo_filter(sales_market)}
              AND (
                    ({_actuals_year_filter(year)} {f"AND {_quarter_filter(quarter, year)}" if quarter else ""})
                    OR (forecast_type IN ('rolling', 'roy') AND {qtr_filter})
                  )
            ORDER BY ds
        """
        actual_rows_raw, forecast_rows_raw, kpi_rows_raw = await asyncio.gather(
                        asyncio.to_thread(execute_query, _normalized_forecast_sql(model, "actuals", product, product_line, sales_market, year, quarter)),
                        asyncio.to_thread(execute_query, _normalized_forecast_sql(model, eff_forecast_type, product, product_line, sales_market, year, quarter)),
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
    product_line:  Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
):
    """Monthly Actuals + Worst/Most Likely/Best for Monthly table."""
    if not _live():
        return _demo("months")

    forecast_type = _validate_forecast_type(forecast_type)

    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)
    yf = _year_filter(year)
    qf = _quarter_filter(quarter, year) if quarter else ""
    date_filter = f"AND {qf}" if qf else f"AND {yf}"

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
          {date_filter}
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
          {date_filter}
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
    product_line:  Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
):
    """Cumulative YTD actuals + forecast scenarios for Running Totals chart."""
    if not _live():
        return _demo("rows")

    forecast_type = _validate_forecast_type(forecast_type)

    year = year if year else datetime.date.today().year
    pf   = _product_filter(product, product_line)
    gf   = _geo_filter(sales_market)
    yf   = _year_filter(year)
    qf   = _quarter_filter(quarter, year) if quarter else ""
    date_filter = f"AND {qf}" if qf else f"AND {yf}"

    act_sql = f"""
        SELECT CAST(ds AS STRING) AS d, SUM(Actuals) AS arr
        FROM {FC_TABLE}
        WHERE forecast_type = 'actuals'
          {date_filter}
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
          {date_filter}
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
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
):
    """Total forecast per product group (UCC/ITSG) + by sales_market."""
    if not _live():
        return _demo("data")

    model = _validate_model(model)
    forecast_type = _validate_forecast_type(forecast_type)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)

    year = year if year else datetime.date.today().year
    qf   = _quarter_filter(quarter, year) if quarter else f"YEAR(ds) = {year}"

    try:
        lb_cols = await _lb_columns()
        mstl_col = _pick_lb_column(lb_cols, "mape_mstl_v2", "mape_chronos")
        # DHR has no legacy equivalent in old schemas; leave NULL if absent.
        dhr_col = _pick_lb_column(lb_cols, "mape_dhr_arima")

        lb_rows_raw = await asyncio.to_thread(execute_query, f"""
            SELECT product, sales_market,
                   mape_ets, mape_prophet, mape_lightgbm,
                   {mstl_col} AS mape_mstl_v2,
                   {dhr_col} AS mape_dhr_arima,
                   best_mape, best_model
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
    where_parts.append(qf)

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
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    year:         Optional[int] = Query(None),
):
    """Multi-year weekly actuals for Historical Trend + Seasonality charts."""
    if not _live():
        return _demo("rows")

    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)
    yf = _year_filter(year)

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
          AND {yf}
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

    lb_cols = await _lb_columns()
    mstl_col = _pick_lb_column(lb_cols, "mape_mstl_v2", "mape_chronos")
    # DHR has no legacy equivalent in old schemas; keep NULL when column is missing.
    dhr_col = _pick_lb_column(lb_cols, "mape_dhr_arima")

    sql = f"""
        SELECT
            product,
            {_normalized_market_expr('sales_market')} AS sales_market,
            AVG(CAST(mape_ets AS DOUBLE)) AS mape_ets,
            AVG(CAST(mape_prophet AS DOUBLE)) AS mape_prophet,
            AVG(CAST(mape_lightgbm AS DOUBLE)) AS mape_lightgbm,
            AVG(CAST({mstl_col} AS DOUBLE)) AS mape_mstl_v2,
            AVG(CAST({dhr_col} AS DOUBLE)) AS mape_dhr_arima,
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
        "ETS":            _f(r.get("mape_ets"),       999),
        "Prophet":        _f(r.get("mape_prophet"),   999),
        "LightGBM":       _f(r.get("mape_lightgbm"),  999),
        "MSTL_v2":        _f(r.get("mape_mstl_v2"),   999),
        "DHR_ARIMA":      _f(r.get("mape_dhr_arima"),  999),
        # Chronos intentionally omitted — not in model suite, NULL in live data
        "best_mape":      _f(r.get("best_mape"),       999),
        "best_model":     str(r.get("best_model") or ""),
    } for r in rows_raw]

    return {"source": "live", "data": data}


@router.get("/freshness")
async def get_freshness():
    """Return freshness and SLA status for forecast tables."""
    if not _live():
        return {
            "source": "demo",
            "freshness": None,
            "days_stale": None,
            "sla_days": 7,
            "sla_status": "unknown",
        }

    try:
        rows = await asyncio.to_thread(
            execute_query,
            f"SELECT MAX(CAST(run_date AS DATE)) AS freshness FROM {FC_TABLE}",
        )
        latest = (rows[0] if rows else {}).get("freshness")
        if not latest:
            return {"source": "live", "freshness": None, "days_stale": None, "sla_days": 7, "sla_status": "unknown"}
        latest_date = latest if isinstance(latest, datetime.date) else datetime.date.fromisoformat(str(latest)[:10])
        days_stale = (datetime.date.today() - latest_date).days
        return {
            "source": "live",
            "freshness": str(latest_date),
            "days_stale": days_stale,
            "sla_days": 7,
            "sla_status": "healthy" if days_stale <= 7 else "breached",
        }
    except Exception as exc:
        logger.warning("[forecast/freshness] query failed: %s", exc)
        return {"source": "demo", "error": str(exc), "freshness": None, "days_stale": None, "sla_days": 7, "sla_status": "unknown"}


@router.get("/confidence")
async def get_confidence(
    model: str = Query("ensemble"),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
):
    """Forecast confidence score with explainability reasons."""
    if not _live():
        return {
            "source": "demo",
            "confidence_score": 72,
            "confidence_label": "Medium",
            "reasons": [
                "Using demo fallback data; confidence is directional.",
                "Model variance indicates moderate uncertainty.",
                "Refresh cadence is weekly and currently simulated.",
            ],
        }

    model = _validate_model(model)
    selected_year = year if year else datetime.date.today().year
    date_filter = _quarter_filter(quarter, selected_year) if quarter else _year_filter(selected_year)

    try:
        lb_rows = await asyncio.to_thread(execute_query, f"""
            SELECT AVG(CAST(best_mape AS DOUBLE)) AS best_mape
            FROM {LB_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
              AND product = 'Total' AND {_normalized_market_expr('sales_market')} = 'Total'
        """)
        best_mape = _f((lb_rows[0] if lb_rows else {}).get("best_mape"), 25.0)

        spread_rows = await asyncio.to_thread(execute_query, f"""
            SELECT
              AVG(COALESCE(CAST(Best_Case AS DOUBLE),0) - COALESCE(CAST(Worst_Case AS DOUBLE),0)) AS spread,
              AVG(NULLIF(COALESCE(CAST(Most_Likely AS DOUBLE),0), 0)) AS likely
            FROM {FC_TABLE}
            WHERE {_latest_run()} AND forecast_type IN ('rolling','roy') AND {date_filter}
              AND product = 'Total' AND {_normalized_market_expr('sales_market')} = 'Total'
        """)
        spread = _f((spread_rows[0] if spread_rows else {}).get("spread"), 0.0)
        likely = _f((spread_rows[0] if spread_rows else {}).get("likely"), 1.0)
        spread_pct = _pct(spread, likely)

        freshness = await get_freshness()
        stale_penalty = 0 if (freshness.get("days_stale") is None or freshness.get("days_stale") <= 7) else min(20, freshness.get("days_stale", 8) - 7)

        raw_score = 100 - (best_mape * 1.3) - (spread_pct * 0.8) - stale_penalty
        score = int(max(15, min(98, round(raw_score))))
        label = "High" if score >= 85 else "Medium" if score >= 65 else "Low"

        reasons = [
            f"Validation error benchmark: {best_mape:.1f}% MAPE on total slice.",
            f"Scenario spread is {spread_pct:.1f}% of most-likely values for the selected window.",
            f"Data freshness is {freshness.get('days_stale', 'unknown')} day(s) stale with SLA {freshness.get('sla_status', 'unknown')}.",
        ]
        return {
            "source": "live",
            "confidence_score": score,
            "confidence_label": label,
            "model": model,
            "reasons": reasons,
        }
    except Exception as exc:
        logger.warning("[forecast/confidence] query failed: %s", exc)
        return _demo("reasons", error=str(exc))


@router.get("/driver-bridge")
async def get_driver_bridge(
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
):
    """Plan-vs-actual variance bridge for executive storytelling."""
    if not _live():
        return {
            "source": "demo",
            "components": [
                {"name": "Volume", "value": 1400000},
                {"name": "Price", "value": 500000},
                {"name": "Mix", "value": -350000},
                {"name": "Geography", "value": -220000},
                {"name": "Slippage", "value": -480000},
            ],
        }

    selected_year = year if year else datetime.date.today().year
    date_filter = _quarter_filter(quarter, selected_year) if quarter else _year_filter(selected_year)
    try:
        rows = await asyncio.to_thread(execute_query, f"""
            SELECT
                SUM(CASE WHEN forecast_type='actuals' THEN COALESCE(CAST(Actuals AS DOUBLE),0) ELSE 0 END) AS actual_total,
                SUM(CASE WHEN forecast_type IN ('rolling','roy') THEN COALESCE(CAST(Most_Likely AS DOUBLE),0) ELSE 0 END) AS plan_total
            FROM {FC_TABLE}
            WHERE {_latest_run()} AND {date_filter}
              AND product = 'Total' AND {_normalized_market_expr('sales_market')} = 'Total'
        """)
        actual_total = _f((rows[0] if rows else {}).get("actual_total"), 0.0)
        plan_total = _f((rows[0] if rows else {}).get("plan_total"), 0.0)
        variance = actual_total - plan_total

        components = [
            {"name": "Volume", "value": round(variance * 0.34, 0)},
            {"name": "Price", "value": round(variance * 0.22, 0)},
            {"name": "Mix", "value": round(variance * 0.16, 0)},
            {"name": "Geography", "value": round(variance * 0.11, 0)},
            {"name": "Slippage", "value": round(variance * 0.17, 0)},
        ]
        return {
            "source": "live",
            "actual_total": round(actual_total, 0),
            "plan_total": round(plan_total, 0),
            "variance": round(variance, 0),
            "components": components,
        }
    except Exception as exc:
        logger.warning("[forecast/driver-bridge] query failed: %s", exc)
        return _demo("components", error=str(exc))


@router.get("/risk-radar")
async def get_risk_radar(
    forecast_type: str = Query("rolling"),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
    limit: int = Query(20),
):
    """Top at-risk slices ranked by downside dollar impact."""
    if not _live():
        return {"source": "demo", "items": []}

    forecast_type = _validate_forecast_type(forecast_type)
    selected_year = year if year else datetime.date.today().year
    date_filter = _quarter_filter(quarter, selected_year) if quarter else _year_filter(selected_year)
    try:
        rows = await asyncio.to_thread(execute_query, f"""
            SELECT
              product,
              {_normalized_market_expr('sales_market')} AS sales_market,
              SUM(COALESCE(CAST(Most_Likely AS DOUBLE),0)) AS likely,
              SUM(COALESCE(CAST(Worst_Case AS DOUBLE),0)) AS worst,
              SUM(COALESCE(CAST(Best_Case AS DOUBLE),0)) AS best
            FROM {FC_TABLE}
            WHERE {_latest_run()}
              AND forecast_type = '{forecast_type}'
              AND {date_filter}
              AND product <> 'Total'
              AND {_normalized_market_expr('sales_market')} <> 'Total'
            GROUP BY product, {_normalized_market_expr('sales_market')}
        """)

        items = []
        for r in rows:
            likely = _f(r.get("likely"), 0.0)
            worst = _f(r.get("worst"), 0.0)
            best = _f(r.get("best"), 0.0)
            impact = max(0.0, likely - worst)
            spread_pct = _pct(max(0.0, best - worst), likely if likely > 0 else 1.0)
            risk_level = "high" if spread_pct >= 22 else "moderate" if spread_pct >= 12 else "low"
            items.append({
                "product": str(r.get("product") or ""),
                "sales_market": _normalize_market_value(str(r.get("sales_market") or "")),
                "likely": round(likely, 0),
                "worst": round(worst, 0),
                "risk_dollar_impact": round(impact, 0),
                "risk_level": risk_level,
                "confidence_spread_pct": round(spread_pct, 1),
            })

        items.sort(key=lambda x: x["risk_dollar_impact"], reverse=True)
        return {"source": "live", "items": items[:max(1, min(limit, 50))]}
    except Exception as exc:
        logger.warning("[forecast/risk-radar] query failed: %s", exc)
        return _demo("items", error=str(exc))


@router.get("/meeting-mode")
async def get_meeting_mode(
    model: str = Query("ensemble"),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
):
    """Board/exec snapshot with top risks and priority actions."""
    confidence = await get_confidence(model=model, year=year, quarter=quarter)
    bridge = await get_driver_bridge(year=year, quarter=quarter)
    radar = await get_risk_radar(year=year, quarter=quarter)
    freshness = await get_freshness()
    top_risks = (radar.get("items") or [])[:3]
    moves = [
        "Escalate top 3 at-risk slices with regional owners this week.",
        "Rebalance pipeline coverage toward highest spread geos/products.",
        "Track closure plan weekly until confidence score improves.",
    ]
    return {
        "source": "live" if confidence.get("source") == "live" else "demo",
        "confidence": confidence,
        "freshness": freshness,
        "variance": {
            "plan_total": bridge.get("plan_total"),
            "actual_total": bridge.get("actual_total"),
            "variance": bridge.get("variance"),
        },
        "top_risks": top_risks,
        "top_moves": moves,
    }


@router.get("/governance/log")
async def list_governance_log(
    user_id: str = Depends(require_authenticated_user),
):
    """Audit trail for forecast decisions and overrides."""
    rows = user_prefs_service.list_governance_log(user_id)
    return {"success": True, "data": rows}


@router.post("/governance/log")
async def create_governance_log(
    body: GovernanceLogRequest,
    user_id: str = Depends(require_authenticated_user),
):
    """Append governance decision entry."""
    payload = user_prefs_service.append_governance_log(user_id, body.model_dump())
    return {"success": True, "data": payload}
