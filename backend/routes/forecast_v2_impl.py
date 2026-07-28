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

import asyncio, os, datetime, logging, json, time
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
# Default to the legacy tables for production safety. Environments that have the
# new unified compat views can opt in via env vars without code changes.
FC_TABLE_NAME = os.getenv("FORECAST_V2_RESULTS_TABLE", "arr_forecast_v2")
LB_TABLE_NAME = os.getenv("FORECAST_V2_LEADERBOARD_TABLE", "arr_forecast_v2_leaderboard")
INSIGHTS_TABLE_NAME = os.getenv("FORECAST_V2_INSIGHTS_TABLE", "arr_forecast_insights")
ACCURACY_HISTORY_TABLE_NAME = os.getenv("FORECAST_V2_ACCURACY_HISTORY_TABLE", "ucc_forecast_accuracy_history")
FC_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{FC_TABLE_NAME}`"
LB_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{LB_TABLE_NAME}`"
INSIGHTS_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{INSIGHTS_TABLE_NAME}`"
ACCURACY_HISTORY_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{ACCURACY_HISTORY_TABLE_NAME}`"
# V5 notebook outputs (UCC Forecast Foundation V5 + ITSG Growth ARR V5).
# APP_TABLE is the unified app-facing table both notebooks are designed to write,
# partitioned by product_group and refreshed each weekly run (run_date_utc).
# ITSG populates it today; UCC writes the same shape to ucc_forecast_v5.
APP_TABLE      = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_app_latest`"
UCC_V5_TABLE   = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`ucc_forecast_v5`"
ITSG_V5_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`itsg_forecast_v5`"
INSIGHTS_PATH = "/Volumes/datagroup_mdl/mdl_sales_analytics/forecast_assets/ai_insights_latest.json"

VALID_FORECAST_TYPES = {"actuals", "rolling", "roy"}
CACHE_TTL_SECONDS = int(os.getenv("FORECAST_V2_CACHE_TTL_SECONDS", "300"))
_QUERY_CACHE: Dict[str, tuple[float, Any]] = {}
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
    # The connector already resolves host defaults and multiple auth modes
    # (forwarded user token, PAT, or OAuth M2M). Requiring explicit host env vars
    # here causes false demo-mode fallbacks even when live Databricks auth exists.
    return force_live or token_available()


def _live_mode_dependency() -> bool:
    """Dependency wrapper so route handlers don't call _live() directly."""
    from routes import forecast_v2 as forecast_v2_pkg

    return forecast_v2_pkg._live()


def _cache_key(endpoint: str, sql: str, **params: Any) -> str:
    encoded = "&".join(
        f"{k}={json.dumps(v, sort_keys=True, default=str)}"
        for k, v in sorted(params.items())
    )
    return f"{endpoint}|{sql}|{encoded}"


async def _cached_query(sql: str, endpoint: str, **params: Any) -> list[Dict[str, Any]]:
    """Small in-process TTL cache for repeated identical read queries."""
    from routes import forecast_v2 as forecast_v2_pkg

    if CACHE_TTL_SECONDS <= 0:
        return await asyncio.to_thread(forecast_v2_pkg.execute_query, sql)

    key = _cache_key(endpoint, sql, **params)
    now = time.time()
    if len(_QUERY_CACHE) > 512:
        expired_keys = [k for k, (ts, _) in _QUERY_CACHE.items() if (now - ts) >= CACHE_TTL_SECONDS]
        for expired_key in expired_keys:
            _QUERY_CACHE.pop(expired_key, None)
    hit = _QUERY_CACHE.get(key)
    if hit and (now - hit[0]) < CACHE_TTL_SECONDS:
        return hit[1]

    rows = await asyncio.to_thread(forecast_v2_pkg.execute_query, sql)
    _QUERY_CACHE[key] = (now, rows)
    return rows


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


def _model_mape_for_row(row: Dict[str, Any], model: str) -> Optional[float]:
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
    SHOW COLUMNS IN {LB_TABLE}
    """
    try:
        rows = await _cached_query(sql, endpoint="/leaderboard/columns")
    except Exception as exc:
        logger.warning("[forecast/lb-columns] schema introspection failed: %s", exc)
        return set()

    return {
        str(r.get("col_name") or r.get("column_name") or "").strip().lower()
        for r in rows
        if str(r.get("col_name") or r.get("column_name") or "").strip()
    }


def _pick_lb_column(columns: set[str], *candidates: str) -> str:
    """Pick the first available leaderboard column, else SQL NULL."""
    for c in candidates:
        if c and c.lower() in columns:
            return c
    return "NULL"


def _pick_column(columns: set[str], *candidates: str) -> Optional[str]:
    for c in candidates:
        if c and c.lower() in columns:
            return c
    return None


async def _table_columns(table_name_sql: str, endpoint: str) -> set[str]:
    sql = f"""
    SHOW COLUMNS IN {table_name_sql}
    """
    try:
        rows = await _cached_query(sql, endpoint=endpoint)
    except Exception as exc:
        logger.warning("[forecast/table-columns] schema introspection failed for %s: %s", table_name_sql, exc)
        return set()

    return {
        str(r.get("col_name") or r.get("column_name") or "").strip().lower()
        for r in rows
        if str(r.get("col_name") or r.get("column_name") or "").strip()
    }


def _model_aliases(model: str) -> list[str]:
    key = (model or "").strip().lower()
    aliases = {
        "ensemble": ["ensemble", "adaptive_ensemble", "most_likely"],
        "prophet": ["prophet", "prophet_trend"],
        "ets": ["ets"],
        "lightgbm": ["lightgbm", "lgbm"],
        "mstl_v2": ["mstl_v2", "mstl"],
        "dhr_arima": ["dhr_arima", "dhr-arima", "arima"],
    }
    return aliases.get(key, [key])


async def _backtest_rows_from_accuracy_history(
    horizon_weeks: int,
    model: str,
    product: Optional[str],
    product_line: Optional[str],
    sales_market: Optional[str],
) -> list[Dict[str, Any]]:
    cols = await _table_columns(ACCURACY_HISTORY_TABLE, endpoint="/backtest/accuracy-history/columns")
    if not cols:
        return []

    ds_col = _pick_column(cols, "ds", "week_start", "week_date", "forecast_week", "target_week", "actual_week")
    run_col = _pick_column(cols, "run_date", "forecast_run_date", "created_at", "generated_at")
    pred_col = _pick_column(cols, "predicted", "predicted_value", "forecast", "forecast_value", "p50", "most_likely", "yhat")
    actual_col = _pick_column(cols, "actual", "actuals", "actual_value", "arr_actual")
    low_col = _pick_column(cols, "worst", "p10", "lower", "lower_bound", "forecast_p10")
    high_col = _pick_column(cols, "best", "p90", "upper", "upper_bound", "forecast_p90")
    wape_col = _pick_column(cols, "wape", "wape_pct", "mape", "mape_pct")
    horizon_col = _pick_column(cols, "horizon_weeks", "weeks_ahead", "horizon", "lead_weeks", "forecast_horizon_weeks")
    product_col = _pick_column(cols, "product", "product_line", "product_group")
    market_col = _pick_column(cols, "sales_market", "market", "geo", "region")
    model_col = _pick_column(cols, "model", "model_name")

    if not ds_col or not pred_col or not actual_col:
        return []

    def q(name: str) -> str:
        return f"`{name}`"

    pred_expr = f"CAST({q(pred_col)} AS DOUBLE)"
    actual_expr = f"CAST({q(actual_col)} AS DOUBLE)"

    if low_col and high_col:
        low_expr = f"CAST({q(low_col)} AS DOUBLE)"
        high_expr = f"CAST({q(high_col)} AS DOUBLE)"
    elif wape_col:
        wape_frac = f"CASE WHEN ABS(CAST({q(wape_col)} AS DOUBLE)) <= 1 THEN ABS(CAST({q(wape_col)} AS DOUBLE)) ELSE ABS(CAST({q(wape_col)} AS DOUBLE))/100 END"
        low_expr = f"({pred_expr}) * (1 - {wape_frac})"
        high_expr = f"({pred_expr}) * (1 + {wape_frac})"
    else:
        low_expr = f"({pred_expr}) * 0.92"
        high_expr = f"({pred_expr}) * 1.08"

    where_parts = [f"COALESCE({actual_expr}, 0) > 0"]

    if horizon_col:
        where_parts.append(f"CAST({q(horizon_col)} AS INT) = {int(horizon_weeks)}")

    effective_product = _selected_product(product, product_line)
    if product_col and effective_product != "Total":
        escaped = effective_product.replace("'", "''")
        where_parts.append(f"UPPER(TRIM(CAST({q(product_col)} AS STRING))) = UPPER('{escaped}')")

    effective_geo = _normalize_market_value(sales_market)
    if market_col and effective_geo != "Total":
        escaped_geo = effective_geo.replace("'", "''")
        where_parts.append(
            f"CASE WHEN UPPER(TRIM(CAST({q(market_col)} AS STRING))) = 'UNKNOWN' THEN 'Unknown' ELSE TRIM(CAST({q(market_col)} AS STRING)) END = '{escaped_geo}'"
        )

    if model_col:
        aliases = _model_aliases(model)
        alias_list = ", ".join("'" + a.replace("'", "''") + "'" for a in aliases)
        where_parts.append(f"LOWER(TRIM(CAST({q(model_col)} AS STRING))) IN ({alias_list})")

    run_expr = f"CAST({q(run_col)} AS STRING)" if run_col else "NULL"

    sql = f"""
        SELECT
            CAST(CAST({q(ds_col)} AS DATE) AS STRING) AS ds,
            {run_expr} AS run_date,
            {pred_expr} AS predicted,
            {low_expr} AS worst,
            {high_expr} AS best,
            {actual_expr} AS actual
        FROM {ACCURACY_HISTORY_TABLE}
        WHERE {' AND '.join(where_parts)}
        ORDER BY CAST({q(ds_col)} AS DATE)
        LIMIT 104
    """

    try:
        rows_raw = await _cached_query(
            sql,
            endpoint="/backtest/accuracy-history",
            model=model,
            forecast_type="rolling",
            product=_selected_product(product, product_line),
            geo=_normalize_market_value(sales_market),
            year=None,
            quarter=None,
            horizon_weeks=horizon_weeks,
        )
    except Exception as exc:
        logger.warning("[forecast/backtest] accuracy-history fallback failed: %s", exc)
        return []

    return [
        {
            "ds": r.get("ds"),
            "run_date": r.get("run_date"),
            "predicted": _f(r.get("predicted")),
            "worst": _f(r.get("worst")),
            "best": _f(r.get("best")),
            "actual": _f(r.get("actual")),
        }
        for r in (rows_raw or [])
        if r.get("ds")
    ]


class GovernanceLogRequest(BaseModel):
    decision: str
    owner: Optional[str] = None
    expected_impact: Optional[float] = None
    reason: Optional[str] = None
    scenario_name: Optional[str] = None


# ── GET /intelligence ──────────────────────────────────────────────────────────
@router.get("/intelligence")
async def get_intelligence(
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Read pre-computed AI insights from Delta table arr_forecast_insights."""
    if not live_mode:
        return {
            "error": "Not in live mode",
            "narrative": "AI Insights unavailable — configure Databricks auth.",
        }
    
    try:
        # Prefer freshest writer output but avoid information_schema access,
        # which some service principals cannot read in UC.
        try:
            rows = await _cached_query(f"""
                SELECT *
                FROM {INSIGHTS_TABLE}
                ORDER BY CAST(updated_at AS TIMESTAMP) DESC, CAST(run_date AS TIMESTAMP) DESC
                LIMIT 1
            """, endpoint="/intelligence", model="ensemble", forecast_type="rolling", product="Total", geo="Total", year=None, quarter=None, variant="updated_at")
        except Exception:
            # Fallback for schemas without updated_at.
            rows = await _cached_query(f"""
                SELECT *
                FROM {INSIGHTS_TABLE}
                ORDER BY CAST(run_date AS TIMESTAMP) DESC
                LIMIT 1
            """, endpoint="/intelligence", model="ensemble", forecast_type="rolling", product="Total", geo="Total", year=None, quarter=None, variant="run_date")
        
        if not rows:
            return {
                "error": "No insights data",
                "narrative": "AI Insights table is empty — run Panel Writer notebook.",
            }
        
        # Extract and parse the JSON payload from whichever key exists.
        row = rows[0] or {}
        json_value = (
            row.get("insights_json")
            or row.get("payload")
            or row.get("insight_payload")
            or row.get("json_payload")
        )
        if json_value is None:
            return {
                "error": "Invalid insights data",
                "narrative": "AI Insights payload is null — re-run Panel Writer.",
            }

        payload = json.loads(json_value) if isinstance(json_value, str) else json_value
        if not isinstance(payload, dict):
            return {
                "error": "Invalid insights data",
                "narrative": "AI Insights payload format is invalid — re-run Panel Writer.",
            }

        if row.get("run_date") and not payload.get("run_date"):
            payload["run_date"] = str(row.get("run_date"))
        if row.get("updated_at"):
            payload["updated_at"] = str(row.get("updated_at"))

        payload["source"] = "live"
        return payload
        
    except Exception as exc:
        exc_str = str(exc)
        if "information_schema" in exc_str.lower() or "TABLE_OR_VIEW_NOT_FOUND" in exc_str:
            return {
                "error": "No insights data",
                "narrative": "AI Insights table has not been created yet — run Step 7 of the Panel Writer notebook.",
            }
        logger.warning("[forecast/v2/intelligence] failed to read table: %s", exc)
        return {
            "error": "Query failed",
            "narrative": f"AI Insights read error: {exc}",
        }


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
    live_mode:     bool          = Depends(_live_mode_dependency),
):
    """
    Weekly actuals + forecast rows for WeeklyForecastChart.
    Actuals rows have Actuals set; forecast rows have Most_Likely/Worst_Case/Best_Case.
    """
    if not live_mode:
        return _demo("rows")

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    
    year = year if year else datetime.date.today().year
    qtr_filter = _quarter_filter(quarter, year) if quarter else f"YEAR(ds) = {year}"

    try:
        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        
        # FIX: Prevent double-counting in quarterly view
        # When filtering by quarter, determine if it's historical or future
        # and select ONLY actuals (past) or ONLY forecasts (future) — not both
        if quarter is not None:
            today = datetime.date.today()
            current_quarter = ((today.month - 1) // 3) + 1
            is_past_quarter = (year < today.year) or (year == today.year and quarter < current_quarter)
            
            # Past quarter: show actuals only
            # Future quarter: show forecasts only
            if is_past_quarter:
                kpi_sql = f"""
                    SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
                    FROM {FC_TABLE}
                    WHERE {_latest_run()}
                            {_product_filter(product, product_line)} {_geo_filter(sales_market)}
                      AND forecast_type = 'actuals' AND {qtr_filter}
                    ORDER BY ds
                """
            else:
                kpi_sql = f"""
                    SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
                    FROM {FC_TABLE}
                    WHERE {_latest_run()}
                            {_product_filter(product, product_line)} {_geo_filter(sales_market)}
                      AND forecast_type IN ('rolling', 'roy') AND {qtr_filter}
                    ORDER BY ds
                """
        else:
            # Full year: prevent double-counting by splitting on temporal boundary
            # Use actuals for past/present, forecasts for future
            today_str = datetime.date.today().isoformat()
            kpi_sql = f"""
                SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
                FROM {FC_TABLE}
                WHERE {_latest_run()}
                                {_product_filter(product, product_line)} {_geo_filter(sales_market)}
                  AND (
                        (forecast_type = 'actuals' AND YEAR(ds) = {year})
                        OR (forecast_type IN ('rolling', 'roy') AND YEAR(ds) = {year} AND CAST(ds AS DATE) > CAST('{today_str}' AS DATE))
                      )
                ORDER BY ds
            """
        
        actual_rows_raw, forecast_rows_raw, kpi_rows_raw = await asyncio.gather(
            _cached_query(_normalized_forecast_sql(model, "actuals", product, product_line, sales_market, year, quarter), endpoint="/weekly", model=model, forecast_type="actuals", product=key_product, geo=key_geo, year=year, quarter=quarter),
            _cached_query(_normalized_forecast_sql(model, eff_forecast_type, product, product_line, sales_market, year, quarter), endpoint="/weekly", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter),
            _cached_query(kpi_sql, endpoint="/weekly", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter, metric="kpis"),
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
    model:         str           = Query("ensemble"),
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
    live_mode:     bool          = Depends(_live_mode_dependency),
):
    """Monthly Actuals + Worst/Most Likely/Best for Monthly table."""
    if not live_mode:
        return _demo("months")

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    source = _model_source(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]

    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)
    yf = _year_filter(year)
    qf = _quarter_filter(quarter, year) if quarter else ""
    date_filter = f"AND {qf}" if qf else f"AND {yf}"

    # FIX: Prevent double-counting in quarterly view
    # When filtering by quarter, determine if it's historical or future
    include_actuals = True
    include_forecasts = True
    if quarter is not None:
        today = datetime.date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        is_past_quarter = (year < today.year) or (year == today.year and quarter < current_quarter)
        if is_past_quarter:
            include_forecasts = False  # Past quarter: show actuals only
        else:
            include_actuals = False  # Future quarter: show forecasts only

    act_sql = None
    if include_actuals:
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

    fc_sql = None
    if include_forecasts:
        fc_sql = f"""
            SELECT
                year(ds)                     AS yr,
                quarter(ds)                  AS qtr,
                month(ds)                    AS mth,
                date_format(ds, 'MMMM')      AS month_name,
                SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS arr_worst,
                SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr_likely,
                SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS arr_best
            FROM {FC_TABLE}
            WHERE forecast_type = '{eff_forecast_type}'
              AND {_latest_run()}
              {pf} {gf}
              {date_filter}
            GROUP BY yr, qtr, mth, month_name
            ORDER BY yr, mth
        """

    try:
        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        
        tasks = []
        if act_sql:
            tasks.append(_cached_query(act_sql, endpoint="/monthly", model=model, forecast_type="actuals", product=key_product, geo=key_geo, year=year, quarter=quarter))
        else:
            tasks.append(None)
        
        if fc_sql:
            tasks.append(_cached_query(fc_sql, endpoint="/monthly", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter))
        else:
            tasks.append(None)
        
        results = await asyncio.gather(*tasks)
        act_rows = results[0] if include_actuals else []
        fc_rows = results[1] if include_forecasts else []
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

    return {
        "source": "live",
        "model": model,
        "forecast_type": eff_forecast_type,
        "months": months,
    }


# ── GET /ytd ────────────────────────────────────────────────────────────────────
@router.get("/ytd")
async def get_ytd(
    product:       Optional[str] = Query(None),
    product_line:  Optional[str] = Query(None),
    sales_market:  Optional[str] = Query(None),
    forecast_type: str           = Query("rolling"),
    model:         str           = Query("ensemble"),
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
    live_mode:     bool          = Depends(_live_mode_dependency),
):
    """Cumulative YTD actuals + forecast scenarios for Running Totals chart."""
    if not live_mode:
        return _demo("rows")

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    source = _model_source(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]

    year = year if year else datetime.date.today().year
    pf   = _product_filter(product, product_line)
    gf   = _geo_filter(sales_market)
    yf   = _year_filter(year)
    qf   = _quarter_filter(quarter, year) if quarter else ""
    date_filter = f"AND {qf}" if qf else f"AND {yf}"

    # FIX: Prevent double-counting in quarterly view
    include_actuals = True
    include_forecasts = True
    if quarter is not None:
        today = datetime.date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        is_past_quarter = (year < today.year) or (year == today.year and quarter < current_quarter)
        if is_past_quarter:
            include_forecasts = False  # Past quarter: show actuals only
        else:
            include_actuals = False  # Future quarter: show forecasts only

    act_sql = None
    if include_actuals:
        act_sql = f"""
            SELECT CAST(ds AS STRING) AS d, SUM(Actuals) AS arr
            FROM {FC_TABLE}
            WHERE forecast_type = 'actuals'
              {date_filter}
              AND {_latest_run()}
              {pf} {gf}
            GROUP BY ds ORDER BY ds
        """

    fc_sql = None
    if include_forecasts:
        fc_sql = f"""
            SELECT CAST(ds AS STRING) AS d,
                 SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS worst,
                 SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS likely,
                 SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS best
            FROM {FC_TABLE}
             WHERE forecast_type = '{eff_forecast_type}'
              {date_filter}
              AND {_latest_run()}
              {pf} {gf}
            GROUP BY ds ORDER BY ds
        """

    try:
        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        
        tasks = []
        if act_sql:
            tasks.append(_cached_query(act_sql, endpoint="/ytd", model=model, forecast_type="actuals", product=key_product, geo=key_geo, year=year, quarter=quarter))
        else:
            tasks.append(None)
        
        if fc_sql:
            tasks.append(_cached_query(fc_sql, endpoint="/ytd", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter))
        else:
            tasks.append(None)
        
        results = await asyncio.gather(*tasks)
        act_rows = results[0] if include_actuals else []
        fc_rows = results[1] if include_forecasts else []
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

    return {
        "source": "live",
        "model": model,
        "forecast_type": eff_forecast_type,
        "rows": rows,
    }


# ── GET /by-product ─────────────────────────────────────────────────────────────
@router.get("/by-product")
async def get_by_product(
    product:       Optional[str] = Query(None),
    product_line:  Optional[str] = Query(None),
    model:         str = Query("ensemble"),
    forecast_type: str = Query("rolling"),
    sales_market:  Optional[str] = Query(None),
    year:          Optional[int] = Query(None),
    quarter:       Optional[int] = Query(None),
    live_mode:     bool          = Depends(_live_mode_dependency),
):
    """Total forecast per product group (UCC/ITSG) + by sales_market."""
    if not live_mode:
        return _demo("data")

    model = _validate_model(model)
    forecast_type = _validate_forecast_type(forecast_type)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)

    year = year if year else datetime.date.today().year
    qf   = _quarter_filter(quarter, year) if quarter else f"YEAR(ds) = {year}"

    # FIX: Prevent double-counting in quarterly view
    use_forecast_type = True
    if quarter is not None:
        today = datetime.date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        is_past_quarter = (year < today.year) or (year == today.year and quarter < current_quarter)
        if is_past_quarter:
            use_forecast_type = False  # Past quarter: show actuals only

    try:
        lb_cols = await _lb_columns()
        mstl_col = _pick_lb_column(lb_cols, "mape_mstl_v2", "mape_chronos")
        # DHR has no legacy equivalent in old schemas; leave NULL if absent.
        dhr_col = _pick_lb_column(lb_cols, "mape_dhr_arima")

        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        lb_rows_raw = await _cached_query(f"""
            SELECT product, sales_market,
                   mape_ets, mape_prophet, mape_lightgbm,
                   {mstl_col} AS mape_mstl_v2,
                   {dhr_col} AS mape_dhr_arima,
                   best_mape, best_model
            FROM {LB_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
        """, endpoint="/by-product", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter, metric="leaderboard")
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
        if use_forecast_type:
            where_parts.append(f"forecast_type = '{eff_forecast_type}'")
            where_parts.append(_latest_run())
        else:
            where_parts.append("forecast_type = 'actuals'")
            where_parts.append(_latest_run())
    else:
        where_parts.append("COALESCE(CAST(Actuals AS DOUBLE), 0) = 0")
    where_parts.append(qf)

    pf = _product_filter(product, product_line)
    selected_product = _selected_product(product, product_line)
    geo_product = "Total" if selected_product == "Total" else selected_product.replace(chr(39), chr(39) * 2)

    prod_sql = f"""
        SELECT
            product,
            SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS arr_worst,
            SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr_likely,
            SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS arr_best
        FROM {table}
        WHERE {' AND '.join(where_parts)}
          {pf}
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
                    AND product = '{geo_product}'
          AND {norm_geo_expr} IN ('NA','EMEA','APAC','LATAM','Unknown')
        GROUP BY {norm_geo_expr}
        ORDER BY arr_likely DESC
    """

    try:
        prod_rows, geo_rows = await asyncio.gather(
            _cached_query(prod_sql, endpoint="/by-product", model=model, forecast_type=eff_forecast_type, product=key_product, geo="Total", year=year, quarter=quarter, metric="product"),
            _cached_query(geo_sql, endpoint="/by-product", model=model, forecast_type=eff_forecast_type, product=selected_product, geo=key_geo, year=year, quarter=quarter, metric="geo"),
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
async def get_models(
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Return registry-backed forecast models with source table and freshness metadata."""
    if not live_mode:
        return {"source": "demo", "models": []}

    # Canonical panel freshness is the arr_forecast_v2 run_date (the table the UI is based on).
    canonical_refresh: Optional[str] = None
    try:
        canonical_rows = await _cached_query(
            f"SELECT MAX(CAST(run_date AS STRING)) AS freshness FROM {FC_TABLE}",
            endpoint="/models",
            model="ensemble",
            forecast_type="rolling",
            product="Total",
            geo="Total",
            year=None,
            quarter=None,
            metric="canonical_refresh",
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
            rows = await _cached_query(freshness_sql, endpoint="/models", model=key, forecast_type="rolling", product="Total", geo="Total", year=None, quarter=None, metric="table_refresh")
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
    live_mode:    bool          = Depends(_live_mode_dependency),
):
    """Multi-year weekly actuals for Historical Trend + Seasonality charts.

    When year is omitted, returns a rolling 3-year window (current year − 2 to current)
    so the Multi-Year overlay chart always shows meaningful multi-line data.
    When year is specified, returns only that year for single-year trend filtering.
    """
    if not live_mode:
        return _demo("rows")

    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)

    if year:
        date_clause = f"AND {_year_filter(year)}"
    else:
        # Default: last 3 calendar years for multi-year overlay charts
        current_year = datetime.date.today().year
        date_clause = f"AND YEAR(ds) BETWEEN {current_year - 2} AND {current_year}"

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
          {date_clause}
          {pf} {gf}
        GROUP BY ds, year(ds), weekofyear(ds), quarter(ds)
        ORDER BY ds
    """

    try:
        rows_raw = await _cached_query(sql, endpoint="/historical", model="ensemble", forecast_type="actuals", product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=year, quarter=None)
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


# ── GET /confidence-bands ───────────────────────────────────────────────────────
@router.get("/confidence-bands")
async def get_confidence_bands(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    forecast_type: str          = Query("rolling"),
    model:        str           = Query("ensemble"),
    year:         Optional[int] = Query(None),
    quarter:      Optional[int] = Query(None),
    live_mode:    bool          = Depends(_live_mode_dependency),
):
    """
    Percentile prediction-interval totals for the selected period.
    Returns {p10, p90, most_likely} summed over all weeks in the filter window.
    These come directly from the source model P10/P90 stored in the p10/p90 columns —
    not synthetic ±% offsets — so they match the UCC/ITSG notebook executive summaries.
    """
    if not live_mode:
        return {
            "source": "demo",
            "p10": 11_817_000, "most_likely": 14_588_000, "p90": 18_546_000,
            "product": "Total", "period": "Q3 2026",
        }

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    source = _model_source(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)
    selected_year = year if year else datetime.date.today().year
    date_filter = f"AND {_quarter_filter(quarter, selected_year)}" if quarter else f"AND {_year_filter(selected_year)}"

    # For non-ensemble selections, use the selected model's lower/upper bands.
    p10_col = source["lower_col"]
    p90_col = source["upper_col"]
    p50_col = source["most_likely_col"]

    sql = f"""
        SELECT
            SUM(COALESCE(CAST({p10_col}    AS DOUBLE), 0)) AS p10,
                        SUM(COALESCE(CAST({p50_col}    AS DOUBLE), 0)) AS most_likely,
            SUM(COALESCE(CAST({p90_col}    AS DOUBLE), 0)) AS p90,
            SUM(COALESCE(CAST(Worst_Case   AS DOUBLE), 0)) AS worst_case,
            SUM(COALESCE(CAST(Best_Case    AS DOUBLE), 0)) AS best_case
        FROM {FC_TABLE}
        WHERE {_latest_run()}
                    AND forecast_type = '{eff_forecast_type}'
          {pf} {gf}
          {date_filter}
    """

    try:
        rows = await _cached_query(sql, endpoint="/confidence-bands", model=model, forecast_type=eff_forecast_type, product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=selected_year, quarter=quarter)
    except Exception as exc:
        logger.warning("[forecast/confidence-bands] query failed: %s", exc)
        return {"source": "demo", "error": str(exc), "p10": None, "most_likely": None, "p90": None}

    r = rows[0] if rows else {}
    p10_val  = _f(r.get("p10") or r.get("worst_case"))
    ml_val   = _f(r.get("most_likely"))
    p90_val  = _f(r.get("p90") or r.get("best_case"))

    return {
        "source": "live",
        "model": model,
        "forecast_type": eff_forecast_type,
        "p10":         round(p10_val, 0),
        "most_likely": round(ml_val, 0),
        "p90":         round(p90_val, 0),
        "worst_case":  round(_f(r.get("worst_case")), 0),
        "best_case":   round(_f(r.get("best_case")), 0),
    }


# ── GET /backtest ───────────────────────────────────────────────────────────────
def _demo_backtest_rows(horizon_weeks: int):
    """Synthetic forecast-vs-actual history for demo mode (12 closed weeks)."""
    import math
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    rows = []
    base = 11_200_000
    for i in range(12, 0, -1):
        ds = monday - datetime.timedelta(weeks=i)
        actual = base + (12 - i) * 95_000 + math.sin(i / 2.0) * 240_000
        # Older-horizon forecasts drift further from actuals
        drift = (1 + horizon_weeks * 0.012) * (1 + math.sin(i / 1.7) * 0.05)
        predicted = actual * drift
        rows.append({
            "ds": ds.isoformat(),
            "run_date": (ds - datetime.timedelta(weeks=horizon_weeks)).isoformat(),
            "predicted": round(predicted, 0),
            "worst": round(predicted * 0.88, 0),
            "best": round(predicted * 1.14, 0),
            "actual": round(actual, 0),
        })
    return rows


def _backtest_summary(rows):
    """Coverage %, MAPE, and signed bias for forecast-vs-actual pairs."""
    scored = [r for r in rows if _f(r.get("actual")) > 0 and r.get("predicted") is not None]
    if not scored:
        return {"weeks_scored": 0, "coverage_pct": None, "mape_pct": None, "bias_pct": None}
    n = len(scored)
    covered = sum(
        1 for r in scored
        if _f(r.get("worst")) <= _f(r.get("actual")) <= _f(r.get("best"))
    )
    ape = [abs(_f(r["predicted"]) - _f(r["actual"])) / _f(r["actual"]) for r in scored]
    bias = [(_f(r["predicted"]) - _f(r["actual"])) / _f(r["actual"]) for r in scored]
    return {
        "weeks_scored": n,
        "coverage_pct": round(covered / n * 100, 1),
        "mape_pct": round(sum(ape) / n * 100, 1),
        "bias_pct": round(sum(bias) / n * 100, 1),
    }


@router.get("/backtest")
async def get_backtest(
    horizon_weeks: int = Query(4, ge=1, le=13),
    model: str = Query("ensemble"),
    product: Optional[str] = None,
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """
    Forecast-vs-Reality trust view.

    arr_forecast_v2 retains every weekly run (delete-then-append per run_date),
    so for each week that has since closed as an actual we can look up what the
    model predicted `horizon_weeks` beforehand. Returns per-week pairs plus
    summary stats:
      coverage_pct — share of weeks where the actual landed inside the P10–P90
                     band (should approach ~80% if intervals are calibrated)
      mape_pct     — mean absolute % error of the point forecast at this horizon
      bias_pct     — signed mean % error (positive = systematic over-forecast)
    """
    model = _validate_model(model)
    if not live_mode:
        rows = _demo_backtest_rows(horizon_weeks)
        return {"source": "demo", "model": model, "horizon_weeks": horizon_weeks,
                "rows": rows, "summary": _backtest_summary(rows)}

    source = _model_source(model)
    value_col = source["most_likely_col"]
    pf = _product_filter(product, product_line)
    gf = _geo_filter(sales_market)
    lo_days = (horizon_weeks - 1) * 7 + 1
    hi_days = horizon_weeks * 7

    sql = f"""
        WITH actuals AS (
            SELECT CAST(ds AS DATE) AS ds,
                   MAX(CAST(Actuals AS DOUBLE)) AS actual
            FROM {FC_TABLE}
            WHERE forecast_type = 'actuals'
              AND {_latest_run()}
              AND COALESCE(CAST(Actuals AS DOUBLE), 0) > 0
              {pf} {gf}
            GROUP BY CAST(ds AS DATE)
        ),
        fc AS (
            SELECT CAST(ds AS DATE) AS ds,
                   CAST(run_date AS DATE) AS run_date,
                   CAST({value_col} AS DOUBLE) AS predicted,
                   CAST(Worst_Case AS DOUBLE) AS worst,
                   CAST(Best_Case AS DOUBLE) AS best,
                   ROW_NUMBER() OVER (
                       PARTITION BY CAST(ds AS DATE)
                       ORDER BY CAST(run_date AS DATE) DESC
                   ) AS rn
            FROM {FC_TABLE}
            WHERE forecast_type IN ('rolling', 'roy')
              AND DATEDIFF(CAST(ds AS DATE), CAST(run_date AS DATE))
                  BETWEEN {lo_days} AND {hi_days}
              {pf} {gf}
        )
        SELECT CAST(f.ds AS STRING) AS ds,
               CAST(f.run_date AS STRING) AS run_date,
               f.predicted, f.worst, f.best, a.actual
        FROM fc f
        JOIN actuals a ON f.ds = a.ds
        WHERE f.rn = 1
        ORDER BY f.ds
    """

    try:
        rows_raw = await _cached_query(sql, endpoint="/backtest", model=model, forecast_type="rolling", product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=None, quarter=None, horizon_weeks=horizon_weeks)
    except Exception as exc:
        logger.warning("[forecast/backtest] query failed: %s", exc)
        rows = _demo_backtest_rows(horizon_weeks)
        return {"source": "demo", "error": str(exc), "model": model,
                "horizon_weeks": horizon_weeks,
                "rows": rows, "summary": _backtest_summary(rows)}

    rows = [
        {
            "ds": r.get("ds"),
            "run_date": r.get("run_date"),
            "predicted": _f(r.get("predicted")),
            "worst": _f(r.get("worst")),
            "best": _f(r.get("best")),
            "actual": _f(r.get("actual")),
        }
        for r in (rows_raw or [])
    ]

    source_detail = None
    if not rows:
        fallback_rows = await _backtest_rows_from_accuracy_history(
            horizon_weeks=horizon_weeks,
            model=model,
            product=product,
            product_line=product_line,
            sales_market=sales_market,
        )
        if fallback_rows:
            rows = fallback_rows
            source_detail = ACCURACY_HISTORY_TABLE_NAME

    response = {"source": "live", "model": model, "horizon_weeks": horizon_weeks,
                "rows": rows, "summary": _backtest_summary(rows)}
    if source_detail:
        response["source_detail"] = source_detail
    return response


# ── GET /run-delta ──────────────────────────────────────────────────────────────
def _demo_run_delta():
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    prev_monday = monday - datetime.timedelta(weeks=1)
    return {
        "source": "demo", "available": True,
        "latest_run": monday.isoformat(), "previous_run": prev_monday.isoformat(),
        "overlap_weeks": 12,
        "total": {"current": 148_600_000, "previous": 149_800_000,
                  "delta": -1_200_000, "delta_pct": -0.8},
        "drivers": [
            {"product": "UCC",  "sales_market": "NA",   "delta": -820_000},
            {"product": "ITSG", "sales_market": "EMEA", "delta": -410_000},
            {"product": "UCC",  "sales_market": "APAC", "delta": 230_000},
        ],
    }


@router.get("/run-delta")
async def get_run_delta(
    product: Optional[str] = None,
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """
    'What changed since last run' — compares the two most recent forecast
    vintages retained in arr_forecast_v2 (ensemble Most_Likely).

    Compares ONLY overlapping future weeks present in both runs; the rolling
    window slides each Monday, so comparing raw totals would show a phantom
    'drop' every week as a closed week rolls out of the window.

    Headline = selected product (or Total) at sales_market='Total'.
    Drivers  = largest absolute moves across sub-slices of the selection.
    """
    effective = _selected_product(product, product_line)
    effective_geo = _normalize_market_value(sales_market)
    if not live_mode:
        return _demo_run_delta()

    norm = _normalized_market_expr("sales_market")
    sql = f"""
        WITH runs AS (
            SELECT DISTINCT CAST(run_date AS DATE) AS rd
            FROM {FC_TABLE}
            ORDER BY rd DESC
            LIMIT 2
        ),
        fc AS (
            SELECT CAST(run_date AS DATE) AS rd, product,
                   {norm} AS sales_market,
                   CAST(ds AS DATE) AS ds,
                   CAST(Most_Likely AS DOUBLE) AS ml
            FROM {FC_TABLE}
            WHERE forecast_type IN ('rolling', 'roy')
              AND CAST(run_date AS DATE) IN (SELECT rd FROM runs)
              AND CAST(ds AS DATE) >= (SELECT MAX(rd) FROM runs)
        )
        SELECT a.product, a.sales_market,
               SUM(a.ml) AS curr_ml,
               SUM(b.ml) AS prev_ml,
               COUNT(*) AS overlap_weeks,
               CAST(MAX(a.rd) AS STRING) AS latest_run,
               CAST(MAX(b.rd) AS STRING) AS previous_run
        FROM fc a
        JOIN fc b
          ON a.ds = b.ds AND a.product = b.product AND a.sales_market = b.sales_market
         AND b.rd < a.rd
        WHERE a.rd = (SELECT MAX(rd) FROM runs)
        GROUP BY a.product, a.sales_market
    """
    try:
        rows = await _cached_query(sql, endpoint="/run-delta", model="ensemble", forecast_type="rolling", product=effective, geo=effective_geo, year=None, quarter=None)
    except Exception as exc:
        logger.warning("[forecast/run-delta] query failed: %s", exc)
        return {**_demo_run_delta(), "error": str(exc)}

    if not rows:
        # Only one retained run (or no overlap) — nothing to compare yet
        return {"source": "live", "available": False,
                "reason": "Fewer than two forecast runs retained — check back after the next Monday run."}

    slices = [{
        "product":       str(r.get("product") or ""),
        "sales_market":  str(r.get("sales_market") or ""),
        "curr":          _f(r.get("curr_ml")),
        "prev":          _f(r.get("prev_ml")),
        "overlap_weeks": int(_f(r.get("overlap_weeks"))),
        "latest_run":    r.get("latest_run"),
        "previous_run":  r.get("previous_run"),
    } for r in rows]

    headline = next(
        (s for s in slices if s["product"] == effective and s["sales_market"] == effective_geo),
        None,
    )
    if headline is None:
        return {"source": "live", "available": False,
                "reason": f"No overlapping forecast weeks for {effective}/{effective_geo}."}

    delta = headline["curr"] - headline["prev"]
    delta_pct = (delta / headline["prev"] * 100) if headline["prev"] else None

    # Drivers: sub-slices of the selection with the largest absolute moves.
    # Region selected → break down by product within that region;
    # product selected → break down by region within that product;
    # both specific  → fully-specified slice, no sub-drivers.
    if effective != "Total" and effective_geo != "Total":
        pool = []
    elif effective_geo != "Total":
        pool = [s for s in slices if s["product"] != "Total" and s["sales_market"] == effective_geo]
    elif effective == "Total":
        pool = [s for s in slices if s["product"] != "Total" and s["sales_market"] == "Total"]
    else:
        pool = [s for s in slices if s["product"] == effective and s["sales_market"] != "Total"]
    drivers = sorted(
        ({"product": s["product"], "sales_market": s["sales_market"],
          "delta": round(s["curr"] - s["prev"], 0)} for s in pool),
        key=lambda d: abs(d["delta"]), reverse=True,
    )[:3]

    return {
        "source": "live", "available": True,
        "latest_run": headline["latest_run"], "previous_run": headline["previous_run"],
        "overlap_weeks": headline["overlap_weeks"],
        "total": {
            "current": round(headline["curr"], 0),
            "previous": round(headline["prev"], 0),
            "delta": round(delta, 0),
            "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        },
        "drivers": drivers,
    }


# ── GET /model-lab ──────────────────────────────────────────────────────────────
_MODEL_LAB_MARKETS = {"NA", "EMEA", "APAC", "LATAM", "UNKNOWN"}


def _demo_model_lab(product: str, grain: str):
    """Synthetic per-model forecast for demo mode — Adaptive Ensemble + 3 members."""
    import math
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    base = 12_000_000 if product == "UCC" else 6_500_000
    models = [
        ("Adaptive_Ensemble", 1.00, 1),
        ("Prophet_trend",     1.03, 0),
        ("MSTL_v2",           0.97, 0),
        ("DHR_ARIMA",         1.06, 0),
    ]
    rows = []
    for name, bias, rec in models:
        for i in range(1, 14):
            ds = monday + datetime.timedelta(weeks=i)
            p50 = base * bias + i * 90_000 + math.sin(i / 3.0) * 180_000
            rows.append({
                "ds": ds.isoformat(), "model": name,
                "forecast": round(p50, 0), "p50": round(p50, 0),
                "p10": round(p50 * 0.90, 0), "p90": round(p50 * 1.12, 0),
                "recommended": rec,
            })
    return {
        "source": "demo", "product": product, "grain": grain,
        "run_date": monday.isoformat(),
        "recommended_model": "Adaptive_Ensemble",
        "models": [m[0] for m in models],
        "rows": rows,
    }


def _model_lab_sql(table: str, has_pg: bool, product: str, grain: str, market: Optional[str]) -> str:
    latest_col = "run_date_utc" if has_pg else "run_timestamp_utc"
    pg_clause = f"AND product_group = '{product}'" if has_pg else ""
    mkt_clause = ""
    if grain == "market" and market and market != "All":
        mkt_clause = f"AND UPPER(TRIM(CAST(sales_market AS STRING))) = '{market.upper()}'"
    return f"""
        SELECT
            CAST(ds AS STRING) AS ds,
            CAST(model AS STRING) AS model,
            CAST(sales_market AS STRING) AS sales_market,
            COALESCE(CAST(forecast AS DOUBLE), CAST(p50 AS DOUBLE)) AS forecast,
            CAST(p10 AS DOUBLE) AS p10,
            CAST(p50 AS DOUBLE) AS p50,
            CAST(p90 AS DOUBLE) AS p90,
            CAST(recommended_for_exec AS INT) AS recommended,
            CAST({latest_col} AS STRING) AS run_date
        FROM {table}
        WHERE grain_level = '{grain}'
          {pg_clause}
          {mkt_clause}
          AND {latest_col} = (SELECT MAX({latest_col}) FROM {table} WHERE grain_level = '{grain}' {pg_clause})
        ORDER BY model, ds
    """


@router.get("/model-lab")
async def get_model_lab(
    product: str = Query("UCC"),
    grain: str = Query("total"),
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """
    Per-model forecast curves with each model's own P10/P50/P90, sourced from the
    V5 notebook output tables (arr_forecast_app_latest — the unified app table both
    UCC & ITSG V5 notebooks feed each weekly run; falls back to ucc_forecast_v5 /
    itsg_forecast_v5). Unlike arr_forecast_v2, bands here are genuinely per-model,
    so switching model changes the confidence band, not just the center line.
    """
    product = (product or "UCC").strip().upper()
    if product not in {"UCC", "ITSG"}:
        raise HTTPException(status_code=400, detail="Invalid product (UCC|ITSG)")
    grain = (grain or "total").strip().lower()
    if grain not in {"total", "market"}:
        raise HTTPException(status_code=400, detail="Invalid grain (total|market)")
    mkt = None
    if sales_market:
        mkt = _normalize_market_value(sales_market)
        if mkt != "Total" and mkt.upper() not in _MODEL_LAB_MARKETS:
            raise HTTPException(status_code=400, detail="Invalid sales_market")

    if not live_mode:
        return _demo_model_lab(product, grain)

    # Try the unified app table first, then the per-product V5 table.
    candidates = [(APP_TABLE, True)]
    candidates.append((UCC_V5_TABLE if product == "UCC" else ITSG_V5_TABLE, False))

    rows_raw, err = None, None
    for table, has_pg in candidates:
        try:
            rows_raw = await _cached_query(
                _model_lab_sql(table, has_pg, product, grain, mkt),
                endpoint="/model-lab",
                model="ensemble",
                forecast_type="rolling",
                product=product,
                geo=mkt or "Total",
                year=None,
                quarter=None,
                grain=grain,
                table=table,
            )
            if rows_raw:
                break
        except Exception as exc:
            err = str(exc)
            logger.warning("[forecast/model-lab] %s query failed: %s", table, exc)

    if not rows_raw:
        demo = _demo_model_lab(product, grain)
        if err:
            demo["error"] = err
        return demo

    rows, models, recommended, run_date = [], [], None, None
    for r in rows_raw:
        m = str(r.get("model") or "")
        if m not in models:
            models.append(m)
        if int(_f(r.get("recommended"))) == 1 and recommended is None:
            recommended = m
        run_date = run_date or r.get("run_date")
        rows.append({
            "ds": r.get("ds"), "model": m,
            "forecast": _f(r.get("forecast")),
            "p10": _f(r.get("p10")), "p50": _f(r.get("p50")), "p90": _f(r.get("p90")),
            "recommended": int(_f(r.get("recommended"))),
        })
    return {
        "source": "live", "product": product, "grain": grain,
        "sales_market": mkt, "run_date": run_date,
        "recommended_model": recommended or (models[0] if models else None),
        "models": models, "rows": rows,
    }


# ── GET /leaderboard ────────────────────────────────────────────────────────────
@router.get("/leaderboard")
async def get_leaderboard(
    live_mode: bool = Depends(_live_mode_dependency),
):
    """MAPE leaderboard — all product × sales_market slices."""
    if not live_mode:
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
        rows_raw = await _cached_query(sql, endpoint="/leaderboard", model="ensemble", forecast_type="rolling", product="Total", geo="Total", year=None, quarter=None)
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

    # Ensemble realized MAPE per slice — not stored in the leaderboard table
    # (the ensemble is the blend, not a holdout-scored model), so compute it
    # empirically: past-run Most_Likely forecasts vs weeks that later closed
    # as actuals (arr_forecast_v2 retains every weekly run_date). Best-effort:
    # on failure the leaderboard simply ships without the Ensemble column.
    try:
        norm = _normalized_market_expr("sales_market")
        ens_sql = f"""
            WITH actuals AS (
                SELECT product, {norm} AS sales_market,
                       CAST(ds AS DATE) AS ds,
                       MAX(CAST(Actuals AS DOUBLE)) AS actual
                FROM {FC_TABLE}
                WHERE forecast_type = 'actuals'
                  AND {_latest_run()}
                  AND COALESCE(CAST(Actuals AS DOUBLE), 0) > 0
                GROUP BY product, {norm}, CAST(ds AS DATE)
            ),
            fc AS (
                SELECT product, {norm} AS sales_market,
                       CAST(ds AS DATE) AS ds,
                       CAST(Most_Likely AS DOUBLE) AS predicted,
                       ROW_NUMBER() OVER (
                           PARTITION BY product, {norm}, CAST(ds AS DATE)
                           ORDER BY CAST(run_date AS DATE) DESC
                       ) AS rn
                FROM {FC_TABLE}
                WHERE forecast_type IN ('rolling', 'roy')
                  AND CAST(run_date AS DATE) < CAST(ds AS DATE)
            )
            SELECT f.product, f.sales_market,
                   AVG(ABS(f.predicted - a.actual) / a.actual) * 100 AS mape_ensemble
            FROM fc f
            JOIN actuals a
              ON f.product = a.product AND f.sales_market = a.sales_market AND f.ds = a.ds
            WHERE f.rn = 1
            GROUP BY f.product, f.sales_market
        """
        ens_rows = await _cached_query(ens_sql, endpoint="/leaderboard", model="ensemble", forecast_type="rolling", product="Total", geo="Total", year=None, quarter=None, metric="ensemble_realized_mape")
        ens_map = {
            (str(r.get("product") or ""), _normalize_market_value(str(r.get("sales_market") or ""))):
                _f(r.get("mape_ensemble"), 999)
            for r in (ens_rows or [])
        }
        for row in data:
            val = ens_map.get((row["product"], row["sales_market"]))
            if val is not None and val < 999:
                row["Ensemble"] = round(val, 1)
    except Exception as exc:
        logger.warning("[forecast/leaderboard] ensemble realized MAPE failed: %s", exc)

    return {"source": "live", "data": data}


@router.get("/freshness")
async def get_freshness(
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Return freshness and SLA status for forecast tables."""
    if not live_mode:
        return {
            "source": "demo",
            "freshness": None,
            "days_stale": None,
            "sla_days": 7,
            "sla_status": "unknown",
        }

    try:
        rows = await _cached_query(
            f"SELECT MAX(CAST(run_date AS DATE)) AS freshness FROM {FC_TABLE}",
            endpoint="/freshness",
            model="ensemble",
            forecast_type="rolling",
            product="Total",
            geo="Total",
            year=None,
            quarter=None,
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
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Forecast confidence score with explainability reasons."""
    if not live_mode:
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
        lb_rows = await _cached_query(f"""
            SELECT AVG(CAST(best_mape AS DOUBLE)) AS best_mape
            FROM {LB_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE})
              AND product = 'Total' AND {_normalized_market_expr('sales_market')} = 'Total'
        """, endpoint="/confidence", model=model, forecast_type="rolling", product="Total", geo="Total", year=selected_year, quarter=quarter, metric="best_mape")
        best_mape = _f((lb_rows[0] if lb_rows else {}).get("best_mape"), 25.0)

        spread_rows = await _cached_query(f"""
            SELECT
              AVG(COALESCE(CAST(Best_Case AS DOUBLE),0) - COALESCE(CAST(Worst_Case AS DOUBLE),0)) AS spread,
              AVG(NULLIF(COALESCE(CAST(Most_Likely AS DOUBLE),0), 0)) AS likely
            FROM {FC_TABLE}
            WHERE {_latest_run()} AND forecast_type IN ('rolling','roy') AND {date_filter}
              AND product = 'Total' AND {_normalized_market_expr('sales_market')} = 'Total'
        """, endpoint="/confidence", model=model, forecast_type="rolling", product="Total", geo="Total", year=selected_year, quarter=quarter, metric="spread")
        spread = _f((spread_rows[0] if spread_rows else {}).get("spread"), 0.0)
        likely = _f((spread_rows[0] if spread_rows else {}).get("likely"), 1.0)
        spread_pct = _pct(spread, likely)

        freshness = await get_freshness(live_mode=live_mode)
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
    model: Optional[str] = Query("ensemble"),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Plan-vs-actual variance bridge for executive storytelling."""
    if not live_mode:
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
    model_key = _validate_model(model or "ensemble")
    source = _model_source(model_key)
    value_col = source["most_likely_col"]
    today_str = datetime.date.today().isoformat()
    try:
        rows = await _cached_query(f"""
            SELECT
                SUM(CASE WHEN forecast_type='actuals' THEN COALESCE(CAST(Actuals AS DOUBLE),0) ELSE 0 END) AS actual_total,
                SUM(CASE WHEN forecast_type IN ('rolling','roy') AND CAST(ds AS DATE) > CAST('{today_str}' AS DATE) THEN COALESCE(CAST({value_col} AS DOUBLE),0) ELSE 0 END) AS plan_total
            FROM {FC_TABLE}
            WHERE {_latest_run()} AND {date_filter}
              AND product = 'Total' AND {_normalized_market_expr('sales_market')} = 'Total'
        """, endpoint="/driver-bridge", model=model_key, forecast_type="rolling", product="Total", geo="Total", year=selected_year, quarter=quarter)
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
    model: str = Query("ensemble"),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
    limit: int = Query(20),
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Top at-risk slices ranked by downside dollar impact."""
    if not live_mode:
        return {"source": "demo", "items": []}

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    source = _model_source(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]
    selected_year = year if year else datetime.date.today().year
    date_filter = _quarter_filter(quarter, selected_year) if quarter else _year_filter(selected_year)
    try:
        rows = await _cached_query(f"""
                        SELECT
                            product,
                            {_normalized_market_expr('sales_market')} AS sales_market,
                            SUM(COALESCE(CAST({value_col} AS DOUBLE),0)) AS likely,
                            SUM(COALESCE(CAST({lower_col} AS DOUBLE),0)) AS worst,
                            SUM(COALESCE(CAST({upper_col} AS DOUBLE),0)) AS best
                        FROM {FC_TABLE}
                        WHERE {_latest_run()}
                            AND forecast_type = '{eff_forecast_type}'
                            AND {date_filter}
                            AND product <> 'Total'
                            AND {_normalized_market_expr('sales_market')} <> 'Total'
                        GROUP BY product, {_normalized_market_expr('sales_market')}
        """, endpoint="/risk-radar", model=model, forecast_type=eff_forecast_type, product="Total", geo="Total", year=selected_year, quarter=quarter, limit=limit)

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
        return {
            "source": "live",
            "model": model,
            "forecast_type": eff_forecast_type,
            "items": items[:max(1, min(limit, 50))],
        }
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
    try:
        live_mode = _live_mode_dependency()
        confidence = await get_confidence(model=model, year=year, quarter=quarter, live_mode=live_mode)
        bridge = await get_driver_bridge(model=model, year=year, quarter=quarter, live_mode=live_mode)
        # Explicitly pass forecast_type to avoid FastAPI Query default objects when
        # this endpoint calls get_risk_radar as a plain Python function.
        radar = await get_risk_radar(forecast_type="rolling", model=model, year=year, quarter=quarter, live_mode=live_mode)
        freshness = await get_freshness(live_mode=live_mode)
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
    except Exception as exc:
        logger.warning("[forecast/meeting-mode] failed: %s", exc)
        return {
            "source": "demo",
            "error": str(exc),
            "confidence": {
                "source": "demo",
                "confidence_score": 72,
                "confidence_label": "Medium",
                "reasons": [
                    "Fallback mode: unable to compute live confidence.",
                    "Review Databricks connectivity and table grants.",
                ],
            },
            "freshness": {
                "source": "demo",
                "freshness": None,
                "days_stale": None,
                "sla_days": 7,
                "sla_status": "unknown",
            },
            "variance": {
                "plan_total": None,
                "actual_total": None,
                "variance": None,
            },
            "top_risks": [],
            "top_moves": [
                "Escalate top 3 at-risk slices with regional owners this week.",
                "Rebalance pipeline coverage toward highest spread geos/products.",
                "Track closure plan weekly until confidence score improves.",
            ],
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

