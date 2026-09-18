"""
Forecast v2 — rich endpoints for the ForecastingPanel UI.

Reads from:  datagroup_mdl.mdl_sales_analytics.forecast_app_snapshot
  (materialized latest-run-only snapshot of forecast_results_v2compat,
   written by forecast_unify_publish weekly — no MAX(run_date) subquery needed).
  columns: ds, product (Total/UCC/ITSG), sales_market (Total/NA/EMEA/APAC/LATAM),
           Actuals, Most_Likely, Worst_Case, Best_Case,
           arr_ets, arr_prophet, arr_lightgbm, arr_mstl_v2, arr_dhr_arima,
           mape_ets, mape_prophet, mape_lightgbm, mape_mstl_v2, mape_dhr_arima,
           forecast_type (actuals|rolling|roy|forward_1yr), run_date
  NOTE: All values (Most_Likely, Worst_Case, Best_Case, p10, p90) are EXACT
        pass-throughs from the published forecast. No band math, no sqrt
        reconstruction, no * 0.90/1.10 approximations.

Leaderboard: datagroup_mdl.mdl_sales_analytics.forecast_leaderboard_v2compat

All values are constrained to the Growth-bookings-aligned unified forecast tables.
"""

import asyncio, os, datetime, logging, json, time, math
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from auth import require_authenticated_user
from services.databricks_connection import execute_query, token_available, query_cache_scope
from services.user_preferences_service import user_prefs_service
from routes.forecast_backtest import RETAINED_MODELS, build_backtest_query, backtest_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forecast/v2", tags=["forecast-v2"])

FORECAST_CATALOG = os.getenv("FORECAST_CATALOG", "datagroup_mdl")
FORECAST_SCHEMA = os.getenv("FORECAST_SCHEMA", "mdl_sales_analytics")
GOLD = f"{FORECAST_CATALOG}.{FORECAST_SCHEMA}"
# DEPRECATED: V1 tables below are no longer used by any endpoint. Kept for reference.
FORECAST_PROPHET_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_prophet`"
# PowerBI wide table — has Ensemble P25/P50/P75 for ALL periods incl. hindcast.
# Used by /monthly for forecast scenarios so closed months show real model predictions.
POWERBI_WIDE_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_powerbi_wide`"
PROPHET_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_all_models`"  # DEPRECATED
# Default to the unified compat views (source of truth from forecast_unify_publish).
# These views expose exact p10/p50/p90 values from the per-product V5 pipelines.
# To revert to legacy tables, set env vars to arr_forecast_v2 / arr_forecast_v2_leaderboard.
FC_TABLE_NAME = os.getenv("FORECAST_V2_RESULTS_TABLE", "forecast_app_snapshot")
LB_TABLE_NAME = os.getenv("FORECAST_V2_LEADERBOARD_TABLE", "forecast_leaderboard_v2compat")
# Default = the unified insights (compat view over forecast_insights, written by
# forecast_unify_publish daily) so the AI tab matches the rest of the panel.
# Env-overridable back to arr_forecast_insights if needed.
INSIGHTS_TABLE_NAME = os.getenv("FORECAST_V2_INSIGHTS_TABLE", "forecast_insights_v2compat")
# Base unified insights table (long format, one row per product) — used for
# product-scoped intelligence.
UNIFIED_INSIGHTS_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_insights`"
ACCURACY_HISTORY_TABLE_NAME = os.getenv("FORECAST_V2_ACCURACY_HISTORY_TABLE", "ucc_forecast_accuracy_history")
FC_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{FC_TABLE_NAME}`"
LB_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{LB_TABLE_NAME}`"
QUARTERLY_ACCURACY_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_quarterly_accuracy`"
INSIGHTS_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{INSIGHTS_TABLE_NAME}`"
ACCURACY_HISTORY_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{ACCURACY_HISTORY_TABLE_NAME}`"
# V5 notebook outputs (UCC Forecast Foundation V5 + ITSG Growth ARR V5).
# APP_TABLE is the unified app-facing table both notebooks are designed to write,
# partitioned by product_group and refreshed each weekly run (run_date_utc).
# ITSG populates it today; UCC writes the same shape to ucc_forecast_v5.
APP_TABLE      = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_app_latest`"  # DEPRECATED
UCC_V5_TABLE   = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`ucc_forecast_v5`"  # DEPRECATED
ITSG_V5_TABLE  = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`itsg_forecast_v5`"  # DEPRECATED
# Retained forecast-vs-actual vintages produced by the UCC V5 notebook — powers
# the Forecast-vs-Reality (backtest) view with real history. UCC-only, no geo split.
UCC_ACCURACY_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`ucc_forecast_accuracy_history`"
# Per-model vintage history (append-only) — all 6 models with p50, used for
# per-model quarterly accuracy matrix.
UCC_VINTAGES_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`ucc_forecast_vintages`"
# Current Best Estimate (actual + forecast) for UCC Growth ARR.
UCC_CBE_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`ucc_forecast_cbe`"
# Precomputed per-graph "explain this chart" text (forecast_unify_publish notebook).
GRAPH_EXPLAIN_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_graph_explanations`"
# Scenario analysis tables (forecast_unify_publish Cell 13).
SCENARIO_GRID_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_scenario_grid`"
SENSITIVITY_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_sensitivity`"
MODEL_SCENARIOS_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_model_scenarios`"
HIST_SCENARIOS_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_historical_scenarios`"
# Per-model static predictions with calibrated p10-p90 (latest run only, no MAX subquery needed).
PURE_TABLE = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`forecast_pure_predictions`"

_GRAPH_KEYS = {"weekly", "ytd", "seasonality", "by_product", "monthly",
               "accuracy", "model_lab", "backtest",
               "quarterly_outlook", "multi_model"}
# Map the app's model key → the model label stored in the accuracy-history table.
_ACC_MODEL = {
    "ensemble": "Adaptive_Ensemble", "prophet": "Prophet_trend", "ets": "ETS",
    "mstl_v2": "MSTL_v2", "dhr_arima": "DHR_ARIMA", "lightgbm": "Global_LGB_Q50_UCC",
}
INSIGHTS_PATH = "/Volumes/datagroup_mdl/mdl_sales_analytics/forecast_assets/ai_insights_latest.json"

VALID_FORECAST_TYPES = {"actuals", "rolling", "roy", "forward_1yr"}
CACHE_TTL_SECONDS = int(os.getenv("FORECAST_V2_CACHE_TTL_SECONDS", "300"))
_QUERY_CACHE: Dict[str, tuple[float, Any]] = {}
MODEL_SOURCES: Dict[str, Dict[str, Any]] = {
    "ets": {
        "display_name": "ETS",
        "table": FC_TABLE,
        "most_likely_col": "arr_ets",
        "lower_col": "p30",
        "upper_col": "p70",
        "mape_field": "ETS",
        "has_forecast_type": True,
    },
    "prophet": {
        "display_name": "Prophet",
        "table": FC_TABLE,
        "most_likely_col": "arr_prophet",
        "lower_col": "p30",
        "upper_col": "p70",
        "mape_field": "Prophet",
        "has_forecast_type": True,
    },
    "lightgbm": {
        "display_name": "LightGBM",
        "table": FC_TABLE,
        "most_likely_col": "arr_lightgbm",
        "lower_col": "p30",
        "upper_col": "p70",
        "mape_field": "LightGBM",
        "has_forecast_type": True,
    },
    "mstl_v2": {
        "display_name": "MSTL",
        "table": FC_TABLE,
        "most_likely_col": "arr_mstl_v2",
        "lower_col": "p30",
        "upper_col": "p70",
        "mape_field": "MSTL_v2",
        "has_forecast_type": True,
    },
    "dhr_arima": {
        "display_name": "DHR-ARIMA",
        "table": FC_TABLE,
        "most_likely_col": "arr_dhr_arima",
        "lower_col": "p30",
        "upper_col": "p70",
        "mape_field": "DHR_ARIMA",
        "has_forecast_type": True,
    },
    # Chronos removed — not in UCC/ITSG V5 notebook model suite.
    # arr_chronos / mape_chronos are NULL in arr_forecast_v2.
    "ensemble": {
        "display_name": "Ensemble",
        "table": FC_TABLE,
        "most_likely_col": "Most_Likely",
        "lower_col": "p30",
        "upper_col": "p70",
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

    # Accuracy publication checks must see the latest successful daily write, not
    # the deployment's 24-hour forecast cache. This also avoids cross-user reuse.
    if endpoint in ("/leaderboard", "/leaderboard/columns") or CACHE_TTL_SECONDS <= 0:
        return await asyncio.to_thread(forecast_v2_pkg.execute_query, sql)

    scope = query_cache_scope()
    if scope is None:
        return await asyncio.to_thread(forecast_v2_pkg.execute_query, sql)

    key = f"{scope}|{_cache_key(endpoint, sql, **params)}"
    now = time.time()
    expired_keys = [key for key, (created, _) in _QUERY_CACHE.items() if (now - created) >= CACHE_TTL_SECONDS]
    for expired_key in expired_keys:
        _QUERY_CACHE.pop(expired_key, None)
    hit = _QUERY_CACHE.get(key)
    if hit and (now - hit[0]) < CACHE_TTL_SECONDS:
        return hit[1]

    rows = await asyncio.to_thread(forecast_v2_pkg.execute_query, sql)
    if len(_QUERY_CACHE) >= 512:
        _QUERY_CACHE.pop(next(iter(_QUERY_CACHE)))
    _QUERY_CACHE[key] = (time.time(), rows)
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
    key = _validate_model(model)
    source = dict(MODEL_SOURCES[key])
    if key != "ensemble":
        source.update(lower_col="NULL", upper_col="NULL")
    return source

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None and v != "" else default
    except (TypeError, ValueError):
        return default

def _demo(key: str, error: str = "Databricks unavailable"):
    return {"source": "unavailable", "live_mode_available": False,
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


def _source_product_filter(source: Dict[str, Any], product, product_line=None, col="product"):
    # forecast_all_models stores product slices (UCC/ITSG) plus sales_market='Total',
    # but does not store a product='Total' aggregate row. Other compat views do.
    if source.get("no_run_date") and _selected_product(product, product_line) == "Total":
        return ""
    return _product_filter(product, product_line, col)


def _source_geo_filter(source: Dict[str, Any], geo, col="sales_market"):
    # forecast_all_models publishes a sales_market='Total' rollup row. Use it
    # for All Regions so we do not sum Total plus individual markets.
    return _geo_filter(geo, col)


def _source_base_filter(source: Dict[str, Any]) -> str:
    clauses = []
    if source.get("model_filter"):
        clauses.append(source["model_filter"])
    if source.get("no_run_date"):
        clauses.append("is_current = TRUE")
    return "".join(f"AND {clause} " for clause in clauses)


def _source_forecast_type_filter(source: Dict[str, Any], actuals: bool = False, col: str = "forecast_type") -> str:
    if source.get("no_run_date"):
        expr = f"LOWER(TRIM(CAST({col} AS STRING)))"
        return f"{expr} = 'actuals'" if actuals else f"{expr} <> 'actuals'"
    return f"{col} = 'actuals'" if actuals else f"{col} IN ('rolling', 'roy')"


def _normalize_market_value(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() == "all":
        return "Total"
    if raw.upper() in ("UNKNOWN", "UNASSIGNED"):
        return "Unknown"
    if raw.upper() == "NORTH AMERICA":
        return "NA"
    return raw


def _normalized_market_expr(col: str = "sales_market") -> str:
    return (
        f"CASE WHEN UPPER(TRIM(CAST({col} AS STRING))) IN ('UNKNOWN', 'UNASSIGNED') "
        f"THEN 'Unknown' WHEN UPPER(TRIM(CAST({col} AS STRING))) = 'NORTH AMERICA' "
        f"THEN 'NA' ELSE TRIM(CAST({col} AS STRING)) END"
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


def _monthly_forecast_type_condition(
    forecast_type: str,
    rolling_next_year: bool,
    selected_year: int,
) -> str:
    if forecast_type == "actuals":
        return f"forecast_type = '{forecast_type}'"
    if rolling_next_year:
        return "forecast_type IN ('rolling', 'roy', 'forward_1yr')"
    if selected_year > datetime.date.today().year:
        return "forecast_type = 'forward_1yr'"
    return "forecast_type IN ('rolling', 'roy')"


def _normalized_forecast_sql(
    model: str,
    forecast_type: str,
    product: Optional[str],
    product_line: Optional[str],
    sales_market: Optional[str],
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    rolling_next_year: bool = False,
) -> str:
    source = _model_source(model)
    table = source["table"]
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]
    table = source["table"]
    actuals_col = source.get("actuals_col", "Actuals")
    pf = _source_product_filter(source, product, product_line)
    gf = _source_geo_filter(source, sales_market)
    base_filter = _source_base_filter(source)
    yf = _year_filter(year)
    qf = _quarter_filter(quarter, year) if quarter else ""
    rolling_filter = _rolling_next_year_filter() if (rolling_next_year and quarter is None) else ""

    if source.get("no_run_date"):
        date_filter = f"AND {qf}" if qf else (f"AND {rolling_filter}" if rolling_filter else f"AND {yf}")
        row_type = "actuals" if forecast_type == "actuals" else "forecast"
        if row_type == "actuals":
            row_filter = f"AND {_source_forecast_type_filter(source, actuals=True)} AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0"
        else:
            row_filter = (
                f"AND {_source_forecast_type_filter(source)} "
                f"AND CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE)) FROM {table} "
                f"WHERE {_source_base_filter(source).replace('AND ', '', 1) if _source_base_filter(source) else '1=1'} "
                f"AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0 {pf} {gf}), DATE'1900-01-01') "
                f"AND COALESCE(CAST({value_col} AS DOUBLE), 0) > 0"
            )
        return f"""
            SELECT
                CAST(ds AS STRING) AS ds,
                '{model}' AS model,
                CAST(forecast_type AS STRING) AS forecast_type,
                SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS value,
                SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS lower,
                SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS upper,
                SUM(COALESCE(CAST({actuals_col} AS DOUBLE), 0)) AS actual,
                CAST(NULL AS STRING) AS publication_id,
                1 AS duplicate_count
            FROM {table}
            WHERE 1=1
              {base_filter}
              {pf} {gf}
              {date_filter}
              {row_filter}
            GROUP BY ds, forecast_type
            ORDER BY ds
        """
    
    if source["has_forecast_type"]:
        date_filter = f"AND {qf}" if qf else (f"AND {rolling_filter}" if rolling_filter else f"AND {yf}")
        type_filter = ("forecast_type = 'actuals' AND Actuals IS NOT NULL"
                       if forecast_type == "actuals" else
                       _monthly_forecast_type_condition("rolling", rolling_next_year, year or datetime.date.today().year)
                       + f" AND {_forecast_after_actuals_pred(pf, gf)}")
        return f"""
            SELECT
                CAST(ds AS STRING) AS ds,
                '{model}' AS model,
                CAST(forecast_type AS STRING) AS forecast_type,
                COALESCE(CAST({value_col} AS DOUBLE), 0) AS value,
                CAST({lower_col} AS DOUBLE) AS lower,
                CAST({upper_col} AS DOUBLE) AS upper,
                CAST(run_date AS STRING) AS publication_id,
                COUNT(*) OVER (PARTITION BY ds, forecast_type) AS duplicate_count,
                COALESCE(CAST(Actuals AS DOUBLE), 0) AS actual,
                CAST(p20 AS DOUBLE) AS p20,
                CAST(p30 AS DOUBLE) AS p30,
                CAST(p40 AS DOUBLE) AS p40,
                CAST(p60 AS DOUBLE) AS p60,
                CAST(p70 AS DOUBLE) AS p70,
                CAST(p80 AS DOUBLE) AS p80
            FROM {table}
            WHERE {_latest_run()}
                            AND {type_filter}
              {pf} {gf}
              {date_filter}
                        QUALIFY ROW_NUMBER() OVER (PARTITION BY ds ORDER BY
                                CASE forecast_type WHEN 'actuals' THEN 0 WHEN 'rolling' THEN 1 WHEN 'roy' THEN 2 ELSE 3 END) = 1
            ORDER BY ds
        """

    raise ValueError(f"Unsupported forecast source for model {model}")



def _normalise_rows(rows: list[Dict[str, Any]], model: str) -> list[Dict[str, Any]]:
    normalized = []
    for row in rows:
        if _f(row.get("duplicate_count")) > 1:
            raise HTTPException(status_code=503, detail="Duplicate forecast rows in selected publication")
        ds = str(row.get("ds") or "")[:10]
        if not ds:
            continue
        entry = {
            "ds": ds,
            "model": model,
            "forecast_type": str(row.get("forecast_type") or "rolling"),
            "value": _f(row.get("value")),
            "lower": _f(row.get("lower")) if row.get("lower") is not None and model == "ensemble" else None,
            "upper": _f(row.get("upper")) if row.get("upper") is not None and model == "ensemble" else None,
            "actual": _f(row.get("actual")),
            "publication_id": row.get("publication_id"),
        }
        # Pass through p20-p80 quantiles when available (fan chart)
        for q in ("p20", "p30", "p40", "p60", "p70", "p80"):
            v = row.get(q)
            if v is not None:
                entry[q] = _f(v)
        normalized.append(entry)
    return normalized


def _fill_weekly_gaps(rows: list[Dict[str, Any]], year: int) -> list[Dict[str, Any]]:
    """Fill missing weeks with zero-value placeholder rows to prevent chart gaps.
    
    Generates all weeks from year start to today (or end of year), merging with
    actual data. Missing weeks get placeholder rows with all numeric values set to 0,
    type set to null string to indicate interpolation.
    """
    import datetime as dt
    
    # Extract existing dates from rows
    existing_dates = {r.get("date") or r.get("ds") for r in rows}
    
    if not existing_dates:
        return rows
    
    # Find min/max date to fill range
    min_date = min(existing_dates)
    max_date = min(max(existing_dates), dt.date.today().isoformat())
    
    # Generate all Mondays (start of ISO week) in range
    start = dt.datetime.fromisoformat(min_date).date()
    end = dt.datetime.fromisoformat(max_date).date()
    
    # Align to Monday (ISO week start)
    start = start - dt.timedelta(days=start.weekday())
    
    all_mondays = []
    current = start
    while current <= end:
        all_mondays.append(current.isoformat())
        current += dt.timedelta(days=7)
    
    # Build result with existing + fill-in rows
    result = {}
    for r in rows:
        d = r.get("date") or r.get("ds")
        result[d] = r
    
    for monday in all_mondays:
        if monday not in result:
            # Create placeholder row for missing week
            result[monday] = {
                "date": monday,
                "type": "",  # Empty type indicates interpolated/zero row
                "arr_actual": None,
                "arr_model": None,
                "arr_likely": None,
                "arr_worst": None,
                "arr_best": None,
                "status": "unavailable",
            }
    
    # Return sorted by date
    return sorted(result.values(), key=lambda x: x.get("date") or "")


def _fill_monthly_gaps(months: list[Dict[str, Any]], year: int, include_actuals: bool, include_forecasts: bool, quarter: Optional[int] = None) -> list[Dict[str, Any]]:
    """Fill missing months with zero-value placeholders to prevent table gaps.

    Scoped to the selected quarter's 3 months when a quarter is given, otherwise
    all 12 months of the year.
    """
    # Map existing months
    month_map = {int(m.get("month", 0)): m for m in months}

    if quarter is not None:
        month_range = range((quarter - 1) * 3 + 1, (quarter - 1) * 3 + 4)
    else:
        month_range = range(1, 13)

    result = []
    for mth in month_range:
        if mth in month_map:
            result.append(month_map[mth])
        else:
            # Create placeholder for missing month
            month_names = ["", "January", "February", "March", "April", "May", "June",
                           "July", "August", "September", "October", "November", "December"]
            result.append({
                "year": year,
                "quarter": ((mth - 1) // 3) + 1,
                "month": mth,
                "month_name": month_names[mth],
                "arr_actual": None,
                "arr_worst": None,
                "arr_likely": None,
                "arr_best": None,
                "status": "unavailable",
            })
    
    return result


def _summary_kpis(rows: list[Dict[str, Any]]) -> Dict[str, float]:
    """Compute KPI card totals from the kpi_sql result rows.

    EXACT SUM approach: the notebook publishes exact p10/p50/p90 per week.
    The app sums them directly for quarter totals — no variance reconstruction.

    The Panel Writer sets Most_Likely/Worst_Case/Best_Case = Actuals for closed
    (actuals) rows, so we sum ML/BC/WC from ALL rows regardless of forecast_type.
    For open (rolling/roy) rows the model forecast is already in those columns.
    This makes closed-quarter and mixed-quarter selections both correct.

    NOTE: The previous implementation used sqrt(sum of squares) to combine weekly
    half-widths in quadrature. This produced artificially tight quarter bands that
    understated risk. The correct approach is simple SUM because the published
    weekly quantiles ARE the source of truth — the app should not reconstruct them.
    """
    most_likely = 0.0
    worst_case = 0.0
    best_case = 0.0
    ytd_actuals = 0.0
    bands_available = True

    for row in rows:
        ftype = str(row.get("forecast_type") or "").strip().lower()
        ml = _f(row.get("Most_Likely"))
        wc = _f(row.get("Worst_Case"))
        bc = _f(row.get("Best_Case"))
        act = _f(row.get("Actuals"))

        if ftype == "actuals":
            most_likely += act
            worst_case += act
            best_case += act
            ytd_actuals += act
            continue

        if ml > 0 or ftype not in ("", "actuals"):
            bands_available = bands_available and row.get("Worst_Case") is not None and row.get("Best_Case") is not None
            most_likely += ml
            worst_case += wc
            best_case += bc

    return {
        "most_likely": round(most_likely, 0),
        "worst_case": round(max(0.0, worst_case), 0) if bands_available else None,
        "best_case": round(best_case, 0) if bands_available else None,
        "ytd_actuals": round(ytd_actuals, 0),
    }


def _forecast_after_actuals_pred(pf: str = "", gf: str = "") -> str:
    """SQL predicate: keep forecast rows strictly AFTER the last closed actual
    week for the current slice. This is the canonical actuals/forecast splice:
    it prevents double-counting weeks that have both an actual and a stale
    forecast row, and (unlike splitting on today's date) never drops the
    in-flight week whose forecast ds is a past Monday but has no actual yet."""
    return (
        f"CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE)) FROM {FC_TABLE} "
        f"WHERE forecast_type = 'actuals' AND {_latest_run()} "
        f"AND Actuals IS NOT NULL {pf} {gf}), DATE'1900-01-01')"
    )


async def _period_landings(
    source: Dict[str, Any],
    product: Optional[str],
    product_line: Optional[str],
    sales_market: Optional[str],
    year: int,
    quarter: Optional[int] = None,
) -> Dict[str, Any]:
    """Canonical period landings: each week contributes actual OR forecast, never both."""
    model = next(key for key, candidate in MODEL_SOURCES.items()
                 if candidate["most_likely_col"] == source["most_likely_col"])
    actual_sql = _normalized_forecast_sql(model, "actuals", product, product_line, sales_market, year, quarter)
    forecast_sql = _normalized_forecast_sql(model, "rolling", product, product_line, sales_market, year, quarter)
    sql = f"""
        WITH actual_weeks AS ({actual_sql}), forecast_weeks AS ({forecast_sql}),
        weeks AS (SELECT * FROM actual_weeks UNION ALL SELECT * FROM forecast_weeks)
        SELECT QUARTER(ds) AS qtr,
            SUM(CASE WHEN forecast_type = 'actuals' THEN actual ELSE 0 END) AS actual,
            SUM(CASE WHEN forecast_type <> 'actuals' THEN value ELSE 0 END) AS forecast,
            SUM(CASE WHEN forecast_type = 'actuals' THEN actual ELSE value END) AS landing,
            CASE WHEN COUNT(CASE WHEN forecast_type <> 'actuals' AND lower IS NULL THEN 1 END) > 0
                THEN NULL ELSE SUM(CASE WHEN forecast_type = 'actuals' THEN actual ELSE lower END) END AS worst,
            CASE WHEN COUNT(CASE WHEN forecast_type <> 'actuals' AND upper IS NULL THEN 1 END) > 0
                THEN NULL ELSE SUM(CASE WHEN forecast_type = 'actuals' THEN actual ELSE upper END) END AS best
        FROM weeks GROUP BY QUARTER(ds) ORDER BY qtr
    """

    rows = await _cached_query(sql, endpoint="/_period_landings", model="custom", forecast_type="landing", product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=year, quarter=quarter)
    by_q = {int(_f(r.get("qtr"))): r for r in rows}
    today = datetime.date.today()
    current_quarter = ((today.month - 1) // 3) + 1
    quarters = []
    for q in (1, 2, 3, 4):
        row = by_q.get(q, {})
        if not row:
            quarters.append({"q": q, "actual": None, "forecast": None, "landing": None,
                             "worst": None, "best": None, "status": "unavailable"})
            continue
        actual = _f(row.get("actual"))
        forecast = _f(row.get("forecast"))
        landing = _f(row.get("landing"))
        status = "closed" if forecast == 0 and actual > 0 else "in_progress" if actual > 0 else "future"
        if year < today.year or (year == today.year and q < current_quarter):
            status = "closed"
        quarters.append({
            "q": q,
            "actual": round(actual, 0),
            "forecast": round(forecast, 0),
            "landing": round(landing, 0),
            "worst": round(_f(row.get("worst")), 0) if row.get("worst") is not None else None,
            "best": round(_f(row.get("best")), 0) if row.get("best") is not None else None,
            "status": status,
        })

    fy_landing = sum(q["landing"] or 0 for q in quarters)
    actuals_ytd = sum(q["actual"] or 0 for q in quarters)
    return {
        "fy_landing": round(fy_landing, 0),
        "fy_worst": sum(q["worst"] for q in quarters) if all(q["worst"] is not None for q in quarters) else None,
        "fy_best": sum(q["best"] for q in quarters) if all(q["best"] is not None for q in quarters) else None,
        "actuals_ytd": round(actuals_ytd, 0),
        "pct_realized": round((actuals_ytd / fy_landing) * 100, 1) if fy_landing > 0 else 0,
        "quarters": quarters,
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


def _rolling_next_year_filter() -> str:
    """Quarter-anchored rolling 12-month window (e.g., Q3 -> next Q2)."""
    return (
        "CAST(ds AS DATE) >= CAST(DATE_TRUNC('QUARTER', CURRENT_DATE()) AS DATE) "
        "AND CAST(ds AS DATE) < ADD_MONTHS(CAST(DATE_TRUNC('QUARTER', CURRENT_DATE()) AS DATE), 12)"
    )


def _v5_latest_col(has_pg: bool) -> str:
    return "run_date_utc" if has_pg else "run_timestamp_utc"


def _v5_scope(product_line: Optional[str], sales_market: Optional[str]) -> tuple[str, str, str]:
    product = _selected_product(None, product_line)
    market = _normalize_market_value(sales_market)

    if market != "Total":
        grain = "market"
    else:
        grain = "total"

    return product, market, grain


def _v5_next_year_filter() -> str:
    return (
        "CAST(ds AS DATE) >= CAST(DATE_TRUNC('MONTH', CURRENT_DATE()) AS DATE) "
        "AND CAST(ds AS DATE) < ADD_MONTHS(CAST(DATE_TRUNC('MONTH', CURRENT_DATE()) AS DATE), 12)"
    )


def _v5_forward_sql(product: str, market: str) -> str:
    """V2: Forward outlook from forecast_app_snapshot (Ensemble scenarios pre-computed)."""
    pf = _product_filter(None, product)
    gf = _geo_filter(market)
    return f"""
        SELECT
            CAST(ds AS STRING) AS ds,
            CAST(Worst_Case AS DOUBLE) AS arr_worst,
            CAST(Most_Likely AS DOUBLE) AS arr_likely,
            CAST(Best_Case AS DOUBLE) AS arr_best
        FROM {FC_TABLE}
        WHERE {_latest_run()}
          {pf} {gf}
          AND {_fc_type_predicate('forecast')}
          AND {_v5_next_year_filter()}
        ORDER BY ds
    """


def _v5_monthly_sql(product: str, market: str) -> str:
    """V2: Monthly Ensemble scenarios from forecast_app_snapshot."""
    pf = _product_filter(None, product)
    gf = _geo_filter(market)
    return f"""
        SELECT
            YEAR(ds) AS yr,
            QUARTER(ds) AS qtr,
            MONTH(ds) AS mth,
            DATE_FORMAT(ds, 'MMMM') AS month_name,
            SUM(CAST(Worst_Case AS DOUBLE)) AS arr_worst,
            SUM(CAST(Most_Likely AS DOUBLE)) AS arr_likely,
            SUM(CAST(Best_Case AS DOUBLE)) AS arr_best
        FROM {FC_TABLE}
        WHERE {_latest_run()}
          {pf} {gf}
          AND {_fc_type_predicate('forecast')}
          AND {_v5_next_year_filter()}
        GROUP BY yr, qtr, mth, month_name
        ORDER BY yr, mth
    """


def _actuals_monthly_next_year_sql(product_line: Optional[str], sales_market: Optional[str]) -> str:
    return f"""
        SELECT
            YEAR(ds) AS yr,
            QUARTER(ds) AS qtr,
            MONTH(ds) AS mth,
            DATE_FORMAT(ds, 'MMMM') AS month_name,
            SUM(COALESCE(CAST(Actuals AS DOUBLE), 0)) AS arr_actual
        FROM {FC_TABLE}
        WHERE forecast_type = 'actuals'
          AND {_latest_run()}
          {_product_filter(None, product_line)}
          {_geo_filter(sales_market)}
          AND {_v5_next_year_filter()}
        GROUP BY yr, qtr, mth, month_name
        ORDER BY yr, mth
    """


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
    product: Optional[str] = None,
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    model: str = "ensemble",
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Read pre-computed AI insights, scoped to the selected product (UCC/ITSG,
    or the ALL portfolio row when no product is selected). Insights are
    product-level for the current quarter; a region selection gets an explicit
    scope note rather than silently ignoring it."""
    if not live_mode:
        return {
            "error": "Not in live mode",
            "narrative": "AI Insights unavailable — configure Databricks auth.",
        }

    today = datetime.date.today()
    if model != "ensemble" or (year is not None and year != today.year) or (quarter is not None and quarter != (today.month - 1) // 3 + 1):
        return {"source": "unavailable", "reason": "Published AI insights cover only the current Ensemble quarter", "data": None}
    eff = _selected_product(product, product_line)
    prod = "ALL" if eff in ("Total", "All", None) else eff
    region = _normalize_market_value(sales_market)
    if region != "Total":
        return {"source": "unavailable", "reason": "No region-scoped published AI insights", "data": None}
    scope_note = (f"Insights are product-level (all regions); the {region} filter "
                  f"does not narrow this tab.") if region != "Total" else None

    # Preferred: product-scoped row from the unified insights table.
    try:
        rows = await _cached_query(f"""
                        SELECT insights_json, run_date FROM {UNIFIED_INSIGHTS_TABLE}
                        WHERE product = '{prod.replace(chr(39), chr(39)*2)}'
                            AND run_date = (SELECT MAX(run_date) FROM {FC_TABLE})
            LIMIT 1
        """, endpoint="/intelligence", model="ensemble", forecast_type="rolling", product=prod, geo="Total", year=None, quarter=None, variant="unified")
        if rows and rows[0].get("insights_json"):
            payload = json.loads(rows[0]["insights_json"])
            if isinstance(payload, dict):
                if scope_note:
                    payload["scope_note"] = scope_note
                return {"source": "live", "data": payload, "publication_id": str(rows[0].get("run_date")),
                    "period_basis": "current_quarter", "model": model, "product": eff}
    except Exception as exc:
        logger.warning("[forecast/intelligence] unified table read failed, falling back: %s", exc)

    return {"source": "unavailable", "reason": "No published AI insights for this selection", "data": None}


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

    rolling_next_year = (forecast_type == "rolling" and year is None and quarter is None)
    year = year if year else datetime.date.today().year

    # 2027+ data lives under forecast_type='forward_1yr' in the unified view.
    # Override eff_forecast_type so queries find the correct rows.
    _is_future_year = (year > datetime.date.today().year)
    if _is_future_year:
        eff_forecast_type = "forward_1yr"
    if quarter:
        qtr_filter = _quarter_filter(quarter, year)
    elif rolling_next_year:
        qtr_filter = _rolling_next_year_filter()
    else:
        qtr_filter = f"YEAR(ds) = {year}"

    try:
        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        
        # Resolve the Most_Likely column for the selected model so KPI cards
        # reflect the chosen model, not always the ensemble.
        # Worst_Case / Best_Case (P10/P90 bands) stay as ensemble columns — they
        # are the calibrated scenario range regardless of the point-forecast model.
        _kpi_src = _model_source(model)
        _ml_col = _kpi_src.get("most_likely_col") or "Most_Likely"
        # For actuals rows the model column is NULL — fall back to Actuals for those.
        _ml_expr = (
            f"COALESCE(CAST({_ml_col} AS DOUBLE), CAST(Actuals AS DOUBLE), 0)"
            if _ml_col != "Most_Likely"
            else "COALESCE(CAST(Most_Likely AS DOUBLE), 0)"
        )

        # FIX: Prevent double-counting in quarterly view
        # When filtering by quarter, determine if it's historical or future
        # and select ONLY actuals (past) or ONLY forecasts (future) — not both
        if _kpi_src.get("no_run_date"):
            _table = _kpi_src["table"]
            _actual_col = _kpi_src.get("actuals_col", "Actuals")
            _value_col = _kpi_src["most_likely_col"]
            _lower_col = _kpi_src["lower_col"]
            _upper_col = _kpi_src["upper_col"]
            _pf = _source_product_filter(_kpi_src, product, product_line)
            _gf = _source_geo_filter(_kpi_src, sales_market)
            _after_actual = (
                f"CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE)) FROM {_table} "
                f"WHERE COALESCE(CAST({_actual_col} AS DOUBLE), 0) > 0 {_pf} {_gf}), DATE'1900-01-01')"
            )
            kpi_sql = f"""
                SELECT ds,
                       CAST({_actual_col} AS DOUBLE) AS Actuals,
                       CASE WHEN {_source_forecast_type_filter(_kpi_src, actuals=True)} THEN NULL ELSE CAST({_value_col} AS DOUBLE) END AS Most_Likely,
                       CASE WHEN {_source_forecast_type_filter(_kpi_src, actuals=True)} THEN NULL ELSE CAST({_lower_col} AS DOUBLE) END AS Worst_Case,
                       CASE WHEN {_source_forecast_type_filter(_kpi_src, actuals=True)} THEN NULL ELSE CAST({_upper_col} AS DOUBLE) END AS Best_Case,
                                             forecast_type
                FROM {_table}
                                WHERE ({qtr_filter})
                                    AND {_kpi_src["model_filter"]}
                                    AND is_current = TRUE
                  {_pf} {_gf}
                  AND (
                                                ({_source_forecast_type_filter(_kpi_src, actuals=True)} AND COALESCE(CAST({_actual_col} AS DOUBLE), 0) > 0)
                                                OR ({_source_forecast_type_filter(_kpi_src)} AND {_after_actual} AND COALESCE(CAST({_value_col} AS DOUBLE), 0) > 0)
                      )
                ORDER BY ds
            """
        elif quarter is not None:
            today = datetime.date.today()
            current_quarter = ((today.month - 1) // 3) + 1
            is_past_quarter = (year < today.year) or (year == today.year and quarter < current_quarter)

            # Past quarter: show actuals only
            # Future quarter: show forecasts only
            if is_past_quarter:
                kpi_sql = f"""
                    SELECT ds, Actuals,
                           {_ml_expr} AS Most_Likely,
                           COALESCE(CAST(p30 AS DOUBLE), 0) AS Worst_Case,
                           COALESCE(CAST(p70 AS DOUBLE), 0) AS Best_Case,
                           forecast_type
                    FROM {FC_TABLE}
                    WHERE {_latest_run()}
                            {_product_filter(product, product_line)} {_geo_filter(sales_market)}
                      AND forecast_type = 'actuals' AND {qtr_filter}
                    ORDER BY ds
                """
            else:
                # Current/future quarter: ACTUALS for closed weeks + FORECAST for
                # weeks after the last closed actual — so the KPI "Most Likely" is
                # the full-quarter LANDING (realized + forecast), matching the AI
                # insight, with no double-count and no dropped in-flight week.
                _pf = _product_filter(product, product_line)
                _gf = _geo_filter(sales_market)
                if _is_future_year:
                    # Future year quarters: all data is forward_1yr, no actuals exist.
                    kpi_sql = f"""
                        SELECT ds, Actuals,
                               {_ml_expr} AS Most_Likely,
                               COALESCE(CAST(p30 AS DOUBLE), 0) AS Worst_Case,
                               COALESCE(CAST(p70 AS DOUBLE), 0) AS Best_Case,
                               forecast_type
                        FROM {FC_TABLE}
                        WHERE {_latest_run()}
                                {_pf} {_gf}
                          AND forecast_type = 'forward_1yr'
                          AND {qtr_filter}
                        ORDER BY ds
                    """
                else:
                    kpi_sql = f"""
                        SELECT ds, Actuals,
                               {_ml_expr} AS Most_Likely,
                               COALESCE(CAST(p30 AS DOUBLE), 0) AS Worst_Case,
                               COALESCE(CAST(p70 AS DOUBLE), 0) AS Best_Case,
                               forecast_type
                        FROM {FC_TABLE}
                        WHERE {_latest_run()}
                                {_pf} {_gf}
                          AND (
                                (forecast_type = 'actuals' AND {qtr_filter})
                                OR (forecast_type IN ('rolling', 'roy') AND {qtr_filter}
                                    AND {_forecast_after_actuals_pred(_pf, _gf)})
                              )
                        ORDER BY ds
                    """
        else:
            # Full year: actuals + forecast spliced after the last closed actual
            # week (no double-count, keeps the in-flight week).
            _pf = _product_filter(product, product_line)
            _gf = _geo_filter(sales_market)
            if _is_future_year:
                # Future year (2027+): only forward_1yr rows exist, no actuals.
                kpi_sql = f"""
                    SELECT ds, Actuals,
                           {_ml_expr} AS Most_Likely,
                           COALESCE(CAST(p30 AS DOUBLE), 0) AS Worst_Case,
                           COALESCE(CAST(p70 AS DOUBLE), 0) AS Best_Case,
                           forecast_type
                    FROM {FC_TABLE}
                    WHERE {_latest_run()}
                                    {_pf} {_gf}
                      AND forecast_type = 'forward_1yr'
                      AND {qtr_filter}
                    ORDER BY ds
                """
            else:
                _kpi_eff = _selected_product(product, product_line)
                _kpi_pw_pf = ("AND product IN ('UCC', 'ITSG')"
                              if _kpi_eff == 'Total'
                              else f"AND product = '{_kpi_eff}'")
                kpi_sql = f"""
                    SELECT q.ds,
                        COALESCE(pw.actual_val, q.Actuals) AS Actuals,
                        CASE WHEN pw.actual_val IS NOT NULL AND q.forecast_type != 'actuals'
                             THEN pw.actual_val ELSE q.Most_Likely END AS Most_Likely,
                        CASE WHEN pw.actual_val IS NOT NULL AND q.forecast_type != 'actuals'
                             THEN pw.actual_val ELSE q.Worst_Case END AS Worst_Case,
                        CASE WHEN pw.actual_val IS NOT NULL AND q.forecast_type != 'actuals'
                             THEN pw.actual_val ELSE q.Best_Case END AS Best_Case,
                        CASE WHEN pw.actual_val IS NOT NULL THEN 'actuals'
                             ELSE q.forecast_type END AS forecast_type
                    FROM (
                        SELECT ds, Actuals,
                               {_ml_expr} AS Most_Likely,
                               COALESCE(CAST(p30 AS DOUBLE), 0) AS Worst_Case,
                               COALESCE(CAST(p70 AS DOUBLE), 0) AS Best_Case,
                               forecast_type
                        FROM {FC_TABLE}
                        WHERE {_latest_run()}
                                        {_pf} {_gf}
                          AND (
                                (forecast_type = 'actuals' AND {qtr_filter})
                                OR (forecast_type IN ('rolling', 'roy') AND {qtr_filter}
                                    AND {_forecast_after_actuals_pred(_pf, _gf)})
                              )
                    ) q
                    LEFT JOIN (
                        SELECT CAST(ds AS DATE) AS ds, SUM(actuals) AS actual_val
                        FROM {POWERBI_WIDE_TABLE}
                        WHERE sales_market = 'Total' {_kpi_pw_pf}
                        GROUP BY CAST(ds AS DATE)
                        HAVING SUM(actuals) > 0
                    ) pw ON CAST(q.ds AS DATE) = pw.ds
                    ORDER BY q.ds
                """
        
        actual_rows_raw, forecast_rows_raw, quarterly_summary = await asyncio.gather(
            _cached_query(_normalized_forecast_sql(model, "actuals", product, product_line, sales_market, year, quarter, rolling_next_year=rolling_next_year), endpoint="/weekly", model=model, forecast_type="actuals", product=key_product, geo=key_geo, year=year, quarter=quarter),
            _cached_query(_normalized_forecast_sql(model, eff_forecast_type, product, product_line, sales_market, year, quarter, rolling_next_year=rolling_next_year), endpoint="/weekly", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter),
            _period_landings(_kpi_src, product, product_line, sales_market, year, quarter=None),
        )
    except Exception as exc:
        logger.warning("[forecast/weekly] query failed for model=%s: %s", model, exc)
        return _demo("rows", error=str(exc))

    actual_rows = _normalise_rows(actual_rows_raw, model)
    forecast_rows = _normalise_rows(forecast_rows_raw, model)
    # Actuals card + band come from the KPI query, which is now scoped to the
    # selected quarter (actuals for closed weeks) or the full year — so the
    # 'Actuals' number tracks whatever period is selected.
    publications = {row["publication_id"] for row in actual_rows + forecast_rows if row["publication_id"]}
    if len(publications) > 1:
        return _demo("rows", "Publication changed during query; refresh required")

    rows = []
    for r in actual_rows:
        rows.append({
            "date": r["ds"],
            "type": "actual",
            "arr_actual": r["actual"],
            "arr_worst": None, "arr_likely": None, "arr_best": None,
        })
    for r in forecast_rows:
        if actual_rows and r["ds"] <= max(actual["ds"] for actual in actual_rows):
            continue
        _entry = {
            "date":       r["ds"],
            "type":       "forecast",
            "arr_actual": None,
            "arr_model":  r["value"],
            "arr_likely": r["value"],
            "arr_worst":  r["lower"],
            "arr_best":   r["upper"],
        }
        # Fan chart quantiles (p20-p80)
        for _q in ("p20", "p30", "p40", "p60", "p70", "p80"):
            if _q in r:
                _entry[f"arr_{_q}"] = r[_q]
        rows.append(_entry)

    rows.sort(key=lambda x: x["date"])
    kpis = _summary_kpis([{
        "forecast_type": "actuals" if row["type"] == "actual" else "forecast",
        "Actuals": row.get("arr_actual"), "Most_Likely": row.get("arr_likely"),
        "Worst_Case": row.get("arr_worst"), "Best_Case": row.get("arr_best"),
    } for row in rows])
    rows = _fill_weekly_gaps(rows, year)  # Fill missing weeks with zero placeholders
    return {
        "source": "live" if actual_rows or forecast_rows else "unavailable",
        "publication_id": next(iter(publications), None),
        "actuals_basis": "published_actuals_rows",
        "band_quantiles": [0.3, 0.7] if model == "ensemble" else None,
        "band_aggregation": "sum_of_weekly_quantiles_not_calibrated_period_quantiles",
        "model": model,
        "forecast_type": eff_forecast_type,
        "rows": rows,
        "kpis": kpis if actual_rows or forecast_rows else None,
        "quarterly_summary": quarterly_summary,
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
    table = source["table"]
    actuals_col = source.get("actuals_col", "Actuals")
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]

    rolling_next_year = (forecast_type == "rolling" and year is None and quarter is None)
    selected_year = year if year else datetime.date.today().year

    # Include ALL disjoint forecast periods so the monthly view shows complete
    # months (rolling covers first 13 wks, roy the rest of FY, forward_1yr 2027+).
    fc_type_clause = _monthly_forecast_type_condition(
        forecast_type=forecast_type,
        rolling_next_year=rolling_next_year,
        selected_year=selected_year,
    )

    pf = _source_product_filter(source, product, product_line)
    gf = _source_geo_filter(source, sales_market)
    yf = _year_filter(selected_year)
    qf = _quarter_filter(quarter, selected_year) if quarter else ""
    date_filter = f"AND {qf}" if qf else (f"AND {_rolling_next_year_filter()}" if rolling_next_year else f"AND {yf}")

    # Closed quarter → actuals only. Current/future quarter → BOTH: actuals for
    # closed weeks + forecast for open weeks (spliced after the last actual, so
    # no double-count). A month can legitimately show both an Actuals figure
    # (closed weeks) and forecast scenarios (open weeks) — separate columns.
    include_actuals = True
    include_forecasts = True
    if quarter is not None:
        today = datetime.date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        is_past_quarter = (selected_year < today.year) or (selected_year == today.year and quarter < current_quarter)
        if is_past_quarter:
            include_forecasts = False  # closed quarter: actuals only

    act_sql = None
    if include_actuals:
        if not source.get("no_run_date"):
            act_sql = f"""
                SELECT
                    year(ds)                     AS yr,
                    quarter(ds)                  AS qtr,
                    month(ds)                    AS mth,
                    date_format(ds, 'MMMM')      AS month_name,
                    SUM(Actuals)                 AS arr_actual,
                    CAST(MIN(run_date) AS STRING) AS publication_id,
                    COUNT(*) - COUNT(DISTINCT ds) AS duplicate_count
                FROM {FC_TABLE}
                WHERE forecast_type = 'actuals'
                  AND {_latest_run()}
                  {pf} {gf}
                  {date_filter}
                GROUP BY yr, qtr, mth, month_name
                ORDER BY yr, mth
            """
        else:
            act_sql = f"""
                SELECT
                    year(ds)                     AS yr,
                    quarter(ds)                  AS qtr,
                    month(ds)                    AS mth,
                    date_format(ds, 'MMMM')      AS month_name,
                    SUM(CAST({actuals_col} AS DOUBLE)) AS arr_actual
                FROM {table}
                                WHERE {_source_forecast_type_filter(source, actuals=True)}
                                    AND {_source_base_filter(source).replace('AND ', '', 1)}
                                    AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0
                  {pf} {gf}
                  {date_filter}
                GROUP BY yr, qtr, mth, month_name
                ORDER BY yr, mth
            """

    fc_sql = None
    if include_forecasts:
        if not source.get("no_run_date"):
            fc_sql = f"""
                SELECT
                    year(ds)                AS yr,
                    quarter(ds)             AS qtr,
                    month(ds)               AS mth,
                    date_format(ds, 'MMMM') AS month_name,
                                        CASE WHEN COUNT(lower) = COUNT(*) THEN SUM(lower) END AS arr_worst,
                                        SUM(value) AS arr_likely,
                                        CASE WHEN COUNT(upper) = COUNT(*) THEN SUM(upper) END AS arr_best,
                                        MIN(publication_id) AS publication_id,
                                        MAX(duplicate_count) - 1 AS duplicate_count
                FROM (
                                        {_normalized_forecast_sql(model, forecast_type, product, product_line, sales_market, selected_year, quarter, rolling_next_year)}
                ) weekly
                GROUP BY yr, qtr, mth, month_name
                ORDER BY yr, mth
            """
        else:
            after_actual = (
                f"CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE)) FROM {table} "
                f"WHERE {_source_base_filter(source).replace('AND ', '', 1)} "
                f"AND {_source_forecast_type_filter(source, actuals=True)} AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0 {pf} {gf}), DATE'1900-01-01')"
            )
            fc_sql = f"""
                SELECT
                    year(ds)                     AS yr,
                    quarter(ds)                  AS qtr,
                    month(ds)                    AS mth,
                    date_format(ds, 'MMMM')      AS month_name,
                    SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS arr_worst,
                    SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr_likely,
                    SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS arr_best
                FROM {table}
                                WHERE {_source_forecast_type_filter(source)}
                                    AND {_source_base_filter(source).replace('AND ', '', 1)}
                                    AND {after_actual}
                  AND COALESCE(CAST({value_col} AS DOUBLE), 0) > 0
                  {pf} {gf}
                  {date_filter}
                GROUP BY yr, qtr, mth, month_name
                ORDER BY yr, mth
            """

    pred_sql = None
    if include_actuals:
        if not source.get("no_run_date"):
            wide_model = {
                "ensemble": "Adaptive_Ensemble",
                "prophet": "Prophet",
                "ets": "ETS",
                "mstl_v2": "MSTL_v2",
                "dhr_arima": "DHR_ARIMA",
                "lightgbm": "Global_LGB_Q50",
            }[model]
            wide_product_filter = (
                "AND product IN ('UCC', 'ITSG')"
                if _selected_product(product, product_line) == "Total"
                else pf
            )
            pred_sql = f"""
                SELECT
                    year(ds)                     AS yr,
                    quarter(ds)                  AS qtr,
                    month(ds)                    AS mth,
                    date_format(ds, 'MMMM')      AS month_name,
                    CASE WHEN COUNT({wide_model}_P50) = COUNT(*) THEN SUM(CAST({wide_model}_P50 AS DOUBLE)) END AS arr_predicted,
                    SUM(CAST({wide_model}_P25 AS DOUBLE)) AS arr_pred_worst,
                    SUM(CAST({wide_model}_P75 AS DOUBLE)) AS arr_pred_best,
                    CAST(MIN(run_date) AS STRING) AS publication_id,
                    CONCAT_WS(', ', SORT_ARRAY(COLLECT_SET(model_fill_source))) AS historical_basis
                FROM {POWERBI_WIDE_TABLE}
                WHERE run_date = (SELECT MAX(run_date) FROM {FC_TABLE})
                                    {wide_product_filter} {gf}
                  {date_filter}
                GROUP BY yr, qtr, mth, month_name
                ORDER BY yr, mth
            """
        else:
            pred_sql = f"""
                SELECT
                    year(ds)                     AS yr,
                    quarter(ds)                  AS qtr,
                    month(ds)                    AS mth,
                    date_format(ds, 'MMMM')      AS month_name,
                    SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr_predicted,
                    SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS arr_pred_worst,
                    SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS arr_pred_best
                FROM {table}
                WHERE {_source_forecast_type_filter(source, actuals=True)}
                  AND {_source_base_filter(source).replace('AND ', '', 1)}
                  {pf} {gf}
                  {date_filter}
                GROUP BY yr, qtr, mth, month_name
                ORDER BY yr, mth
            """

    try:
        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        
        # Gather only the queries actually built. gather() (not manual sequential
        # awaits) ensures that if one query raises, the sibling coroutine is
        # consumed/cancelled instead of leaking a never-awaited coroutine.
        pending = []
        if act_sql:
            pending.append(("act", _cached_query(act_sql, endpoint="/monthly", model=model, forecast_type="actuals", product=key_product, geo=key_geo, year=year, quarter=quarter)))
        if fc_sql:
            pending.append(("fc", _cached_query(fc_sql, endpoint="/monthly", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter)))
        if pred_sql:
            pending.append(("pred", _cached_query(pred_sql, endpoint="/monthly", model=model, forecast_type="prediction", product=key_product, geo=key_geo, year=year, quarter=quarter)))
        results = await asyncio.gather(*(c for _, c in pending), return_exceptions=True)
        res_map = {}
        history_error = None
        for (key, _), result in zip(pending, results):
            if isinstance(result, BaseException):
                if key != "pred":
                    raise result
                history_error = "Historical estimate unavailable for this publication"
                result = []
            res_map[key] = result
        act_rows = res_map.get("act", [])
        fc_rows = res_map.get("fc", [])
        pred_rows = res_map.get("pred", [])
        publications = {str(row["publication_id"]) for row in act_rows + fc_rows + pred_rows if row.get("publication_id")}
        if len(publications) > 1:
            return _demo("months", "Publication changed during query; refresh required")
        if any(_f(row.get("duplicate_count")) > 0 for row in act_rows + fc_rows):
            return _demo("months", "Duplicate rows in selected publication")
    except Exception as exc:
        logger.warning("[forecast/monthly] query failed: %s", exc)
        return _demo("months", error=str(exc))

    act_map = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): r
        for r in act_rows
    }
    fc_by_month = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): r
        for r in fc_rows
    }
    pred_map = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): r
        for r in pred_rows
    }

    # Merge keys from BOTH sides: months with only actuals (closed months /
    # closed quarters) must still appear — previously the list was built from
    # forecast rows only, so actuals-only months vanished.
    months = []
    for key in sorted(set(act_map) | set(fc_by_month) | set(pred_map)):
        yr, mth = key
        a = act_map.get(key)
        f = fc_by_month.get(key)
        p = pred_map.get(key)
        src = f or a or p
        months.append({
            "year":       yr,
            "quarter":    int(_f(src.get("qtr"))),
            "month":      mth,
            "month_name": str(src.get("month_name") or ""),
            "arr_actual": _f(a.get("arr_actual")) if a else None,
            "arr_worst":  _f(f.get("arr_worst")) if f and f.get("arr_worst") is not None and model == "ensemble" else None,
            "arr_likely": _f(f.get("arr_likely")) if f else None,
            "arr_best":   _f(f.get("arr_best")) if f and f.get("arr_best") is not None and model == "ensemble" else None,
            "historical_basis": (p.get("historical_basis") or "wide_hindcast_or_proxy") if p else "unavailable",
            "historical_band_quantiles": [0.25, 0.75] if p else None,
            "accuracy": None,
            "arr_predicted":  _f(p.get("arr_predicted")) if p and p.get("arr_predicted") is not None else None,
            "arr_pred_worst": _f(p.get("arr_pred_worst")) if p else None,
            "arr_pred_best":  _f(p.get("arr_pred_best")) if p else None,
        })

    if rolling_next_year:
        months.sort(key=lambda r: (int(_f(r.get("year"))), int(_f(r.get("month")))))
    else:
        months = _fill_monthly_gaps(months, selected_year, include_actuals, include_forecasts, quarter)
    return {
        "source": "live",
        "model": model,
        "forecast_type": eff_forecast_type,
        "months": months,
        "publication_id": next(iter(publications), None),
        "historical_status": history_error or ("available_estimate" if pred_rows else "unavailable"),
        "band_quantiles": [0.3, 0.7] if model == "ensemble" else None,
        "band_aggregation": "sum_of_weekly_quantiles_not_calibrated_period_quantiles",
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
    table = source["table"]
    actuals_col = source.get("actuals_col", "Actuals")

    rolling_next_year = (forecast_type == "rolling" and year is None and quarter is None)
    year = year if year else datetime.date.today().year
    # 2027+ data lives under forecast_type='forward_1yr'.
    _is_future_year = (year > datetime.date.today().year)
    if _is_future_year:
        eff_forecast_type = "forward_1yr"
    pf   = _source_product_filter(source, product, product_line)
    gf   = _source_geo_filter(source, sales_market)
    yf   = _year_filter(year)
    qf   = _quarter_filter(quarter, year) if quarter else ""
    date_filter = f"AND {qf}" if qf else (f"AND {_rolling_next_year_filter()}" if rolling_next_year else f"AND {yf}")

    # Closed quarter → actuals only. Current/future quarter → keep BOTH so the
    # running total shows realized-to-date (amber) plus the forecast path. The
    # actuals and forecast rows cover different weeks, so there's no double-count.
    include_actuals = True if not _is_future_year else False
    include_forecasts = True
    if quarter is not None:
        today = datetime.date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        is_past_quarter = (year < today.year) or (year == today.year and quarter < current_quarter)
        if is_past_quarter:
            include_forecasts = False  # closed quarter: actuals only

    act_sql = None
    if include_actuals:
        if not source.get("no_run_date"):
            act_sql = f"""
                SELECT CAST(ds AS STRING) AS d, SUM(Actuals) AS arr
                FROM {FC_TABLE}
                WHERE forecast_type = 'actuals'
                  {date_filter}
                  AND {_latest_run()}
                  {pf} {gf}
                GROUP BY ds ORDER BY ds
            """
        else:
            act_sql = f"""
                SELECT CAST(ds AS STRING) AS d, SUM(CAST({actuals_col} AS DOUBLE)) AS arr
                FROM {table}
                                WHERE {_source_forecast_type_filter(source, actuals=True)}
                  AND {_source_base_filter(source).replace('AND ', '', 1)}
                  AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0
                  {date_filter}
                  {pf} {gf}
                GROUP BY ds ORDER BY ds
            """

    fc_sql = None
    if include_forecasts:
        # For future years (2027+), skip _forecast_after_actuals_pred — all rows
        # are inherently beyond any closed actual week.
        _after_pred = "" if _is_future_year else f"AND {_forecast_after_actuals_pred(pf, gf)}"
        if rolling_next_year:
            fc_type_clause = "forecast_type IN ('rolling', 'roy', 'forward_1yr')"
        elif quarter is None and not _is_future_year:
            fc_type_clause = "forecast_type IN ('rolling', 'roy')"
        else:
            fc_type_clause = f"forecast_type = '{eff_forecast_type}'"
        if not source.get("no_run_date"):
            fc_sql = f"""
                SELECT CAST(ds AS STRING) AS d,
                     SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS worst,
                     SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS likely,
                     SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS best
                FROM {FC_TABLE}
                 WHERE {fc_type_clause}
                  {date_filter}
                  AND {_latest_run()}
                  {_after_pred}
                  {pf} {gf}
                GROUP BY ds ORDER BY ds
            """
        else:
            after_actual = (
                f"CAST(ds AS DATE) > COALESCE((SELECT MAX(CAST(ds AS DATE)) FROM {table} "
                f"WHERE {_source_base_filter(source).replace('AND ', '', 1)} "
                f"AND {_source_forecast_type_filter(source, actuals=True)} AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0 {pf} {gf}), DATE'1900-01-01')"
            )
            fc_sql = f"""
                SELECT CAST(ds AS STRING) AS d,
                     SUM(COALESCE(CAST({lower_col} AS DOUBLE), 0)) AS worst,
                     SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS likely,
                     SUM(COALESCE(CAST({upper_col} AS DOUBLE), 0)) AS best
                FROM {table}
                                WHERE {_source_forecast_type_filter(source)}
                                    AND {_source_base_filter(source).replace('AND ', '', 1)}
                                    AND {after_actual}
                  AND COALESCE(CAST({value_col} AS DOUBLE), 0) > 0
                  {date_filter}
                  {pf} {gf}
                GROUP BY ds ORDER BY ds
            """

    try:
        key_product = _selected_product(product, product_line)
        key_geo = _normalize_market_value(sales_market)
        
        # Gather only the queries actually built (None in gather = TypeError,
        # which is what broke quarter mode before). Using gather also consumes
        # the sibling coroutine if one raises — no leaked never-awaited coroutine.
        pending = []
        if act_sql:
            pending.append(("act", _cached_query(act_sql, endpoint="/ytd", model=model, forecast_type="actuals", product=key_product, geo=key_geo, year=year, quarter=quarter)))
        if fc_sql:
            pending.append(("fc", _cached_query(fc_sql, endpoint="/ytd", model=model, forecast_type=eff_forecast_type, product=key_product, geo=key_geo, year=year, quarter=quarter)))
        results = await asyncio.gather(*(c for _, c in pending))
        res_map = {k: r for (k, _), r in zip(pending, results)}
        act_rows = res_map.get("act", [])
        fc_rows = res_map.get("fc", [])
    except Exception as exc:
        logger.warning("[forecast/ytd] query failed: %s", exc)
        return _demo("rows", error=str(exc))

    act_map = {str(r.get("d") or "")[:10]: _f(r.get("arr")) for r in act_rows}
    fc_map  = {str(r.get("d") or "")[:10]: r for r in fc_rows}

    # Date range for the running total: the SELECTED PERIOD's own span (quarter
    # start→end, or Jan 1→Dec 31), extended through the forecast weeks — capped
    # at the last date that actually has data so the line never flat-tails.
    import datetime as dt
    if rolling_next_year:
        quarter_start = datetime.date.today().replace(month=(((datetime.date.today().month - 1) // 3) * 3) + 1, day=1)
        range_start = quarter_start
        range_end_seed = range_start + datetime.timedelta(days=370)
        range_end = datetime.date(range_end_seed.year, range_end_seed.month, 1) - datetime.timedelta(days=1)
    elif quarter is not None:
        qsm = (quarter - 1) * 3 + 1
        range_start = dt.date(year, qsm, 1)
        period_end = dt.date(year, 12, 31) if qsm + 2 >= 12 else (dt.date(year, qsm + 3, 1) - dt.timedelta(days=1))
        range_end = period_end
    else:
        range_start = dt.date(year, 1, 1)
        range_end = dt.date(year, 12, 31)

    _data_dates = [d for d in list(act_map.keys()) + list(fc_map.keys()) if d]
    if _data_dates:
        last_data = dt.date.fromisoformat(max(_data_dates)[:10])
        range_end = min(range_end, max(last_data, min(dt.date.today(), range_end)))
    else:
        range_end = min(dt.date.today(), range_end)
    all_dates = [
        (range_start + dt.timedelta(days=i)).isoformat()
        for i in range((range_end - range_start).days + 1)
    ]

    # Compute cumulative totals, filling gaps with previous values
    cum_a = cum_w = cum_l = cum_b = 0.0
    last_actual_date = max(act_map) if act_map else None
    rows = []
    for d in all_dates:
        if d in act_map:
            cum_a += act_map[d]
        if d in fc_map:
            fc = fc_map[d]
            cum_w += _f(fc.get("worst", 0))
            cum_l += _f(fc.get("likely", 0))
            cum_b += _f(fc.get("best", 0))
        
        rows.append({
            "date":       d,
            "ytd_actual": round(cum_a, 0) if include_actuals and (last_actual_date is None or d <= last_actual_date) else None,
            "ytd_worst":  round(cum_a + cum_w, 0) if include_forecasts and (d in fc_map or d == last_actual_date) else None,
            "ytd_likely": round(cum_a + cum_l, 0) if include_forecasts and (d in fc_map or d == last_actual_date) else None,
            "ytd_best":   round(cum_a + cum_b, 0) if include_forecasts and (d in fc_map or d == last_actual_date) else None,
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

    rolling_next_year = (forecast_type == "rolling" and year is None and quarter is None)
    year = year if year else datetime.date.today().year
    # 2027+ data lives under forecast_type='forward_1yr' in the unified view.
    _is_future_year = (year > datetime.date.today().year)
    if quarter:
        period_filter = _quarter_filter(quarter, year)
    elif rolling_next_year:
        period_filter = _rolling_next_year_filter()
    else:
        period_filter = f"YEAR(ds) = {year}"

    # Determine the correct forecast_type filter for the landing union.
    # A full-year or quarter view needs BOTH rolling + roy to capture all weeks;
    # using only 'rolling' misses the rest-of-year chunk beyond the 13-week window.
    # Future years (2027+) use 'forward_1yr' exclusively.
    if rolling_next_year:
        _fc_type_pred = "forecast_type IN ('rolling', 'roy', 'forward_1yr')"
    elif _is_future_year:
        _fc_type_pred = "forecast_type = 'forward_1yr'"
    else:
        _fc_type_pred = "forecast_type IN ('rolling', 'roy')"

    # Totals are the period LANDING: actuals for closed weeks + forecast spliced
    # after the last actual (matches the Overview KPI and the AI insight). A
    # closed quarter naturally has only actuals rows in the latest run; a future
    # quarter only forecast rows — the union handles all cases uniformly.

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
    actuals_col = source.get("actuals_col", "Actuals")
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]
    actuals_type = _source_forecast_type_filter(source, actuals=True)
    forecast_types = _source_forecast_type_filter(source) if source.get("no_run_date") else _fc_type_pred
    source_filter = _source_base_filter(source) if source.get("no_run_date") else f"AND {_latest_run()}"

    pf = _product_filter(product, product_line)
    selected_product = _selected_product(product, product_line)
    geo_product = "Total" if selected_product == "Total" else selected_product.replace(chr(39), chr(39) * 2)
    norm_geo_expr = _normalized_market_expr("sales_market")

    def _landing_union(extra_where: str) -> str:
        """Actuals + spliced forecast rows for the period, one row per week.
        Actual weeks carry zero spread (worst=likely=best=actual)."""
        return f"""(
            SELECT product, {norm_geo_expr} AS sales_market, ds,
                                     CAST({actuals_col} AS DOUBLE) AS likely,
                                     CAST({actuals_col} AS DOUBLE) AS worst,
                                     CAST({actuals_col} AS DOUBLE) AS best
            FROM {table}
                        WHERE {actuals_type} {source_filter} AND {period_filter}
                            AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0 {extra_where}
            UNION ALL
            SELECT product, {norm_geo_expr} AS sales_market, ds,
                   COALESCE(CAST({value_col} AS DOUBLE), 0),
                   COALESCE(CAST({lower_col} AS DOUBLE), 0),
                   COALESCE(CAST({upper_col} AS DOUBLE), 0)
                        FROM {table} forecast_rows
                        WHERE {forecast_types} {source_filter} AND {period_filter}
                            AND CAST(forecast_rows.ds AS DATE) > COALESCE((
                                    SELECT MAX(CAST(actual_rows.ds AS DATE)) FROM {table} actual_rows
                                    WHERE {actuals_type} {source_filter}
                                        AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0
                                        AND actual_rows.product = forecast_rows.product
                                        AND {_normalized_market_expr('actual_rows.sales_market')} = {_normalized_market_expr('forecast_rows.sales_market')}
                            ), DATE'1900-01-01') {extra_where}
        )"""

    # EXACT SUM of weekly bands — no sqrt variance compression.
    # The published weekly p10/p50/p90 ARE the source of truth.
    _band_select = """
            SUM(likely) AS arr_likely,
            SUM(worst) AS arr_worst,
            SUM(best) AS arr_best
    """

    prod_sql = f"""
        SELECT product, {_band_select}
        FROM {_landing_union("AND sales_market = 'Total' AND product IN ('UCC','ITSG')")} u
        GROUP BY product
        ORDER BY product
    """

    geo_product_filter = "AND product IN ('UCC','ITSG')" if source.get("no_run_date") and selected_product == "Total" else f"AND product = '{geo_product}'"
    geo_sql = f"""
        SELECT sales_market, {_band_select}
        FROM {_landing_union(geo_product_filter)} u
        WHERE sales_market IN ('NA','EMEA','APAC','LATAM','Unknown')
        GROUP BY sales_market
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
    model:        str           = Query("ensemble"),
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

    model = _validate_model(model)
    source = _model_source(model)
    value_col = source["most_likely_col"]
    actuals_col = source.get("actuals_col", "Actuals")
    pf = _source_product_filter(source, product, product_line)
    gf = _source_geo_filter(source, sales_market)
    current_year = datetime.date.today().year

    if year:
        date_clause = f"AND {_year_filter(year)}"
    else:
        # Default: last 3 calendar years for multi-year overlay charts
        date_clause = f"AND YEAR(ds) BETWEEN {current_year - 2} AND {current_year}"

    if not source.get("no_run_date"):
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
    else:
        actuals_col = source.get("actuals_col", "Actuals")
        sql = f"""
            SELECT
                CAST(ds AS STRING)          AS date,
                year(ds)                    AS year,
                weekofyear(ds)              AS iso_week,
                quarter(ds)                 AS quarter,
                SUM(CAST({actuals_col} AS DOUBLE)) AS arr
                        FROM {source["table"]}
                        WHERE {_source_forecast_type_filter(source, actuals=True)}
                            AND {_source_base_filter(source).replace('AND ', '', 1)}
                            AND COALESCE(CAST({actuals_col} AS DOUBLE), 0) > 0
              {date_clause}
              {pf} {gf}
            GROUP BY ds, year(ds), weekofyear(ds), quarter(ds)
            ORDER BY ds
        """

    try:
        rows_raw = await _cached_query(sql, endpoint="/historical", model=model, forecast_type="actuals", product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=year, quarter=None)
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

    if source.get("no_run_date"):
        fc_cont_sql = f"""
            SELECT
                CAST(ds AS STRING)          AS date,
                year(ds)                    AS year,
                weekofyear(ds)              AS iso_week,
                quarter(ds)                 AS quarter,
                SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr
            FROM {source["table"]}
            WHERE {_source_forecast_type_filter(source)}
              AND {_source_base_filter(source).replace('AND ', '', 1)}
              AND COALESCE(CAST({value_col} AS DOUBLE), 0) > 0
              AND YEAR(ds) = {current_year}
              {pf} {gf}
            GROUP BY ds, year(ds), weekofyear(ds), quarter(ds)
            ORDER BY ds
        """
    else:
        fc_cont_sql = f"""
            SELECT
                CAST(ds AS STRING)          AS date,
                year(ds)                    AS year,
                weekofyear(ds)              AS iso_week,
                quarter(ds)                 AS quarter,
                SUM(COALESCE(CAST({value_col} AS DOUBLE), 0)) AS arr
            FROM {FC_TABLE}
            WHERE forecast_type IN ('rolling', 'roy')
              AND {_latest_run()}
              AND YEAR(ds) = {current_year}
              AND {_forecast_after_actuals_pred(pf, gf)}
              {pf} {gf}
            GROUP BY ds, year(ds), weekofyear(ds), quarter(ds)
            ORDER BY ds
        """

    try:
        fc_rows_raw = await _cached_query(fc_cont_sql, endpoint="/historical", model=model, forecast_type="forecast", product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=current_year, quarter=None, metric="forecast_continuation")
    except Exception:
        fc_rows_raw = []
    forecast_continuation = [{
        "date":     str(r.get("date") or "")[:10],
        "year":     int(_f(r.get("year"))),
        "iso_week": int(_f(r.get("iso_week"))),
        "quarter":  int(_f(r.get("quarter"))),
        "arr":      _f(r.get("arr")),
    } for r in fc_rows_raw]

    weeks_per_year: Dict[int, int] = {}
    for r in rows:
        weeks_per_year[r["year"]] = weeks_per_year.get(r["year"], 0) + 1
    lfl_max_week = max((r["iso_week"] for r in rows if r["year"] == current_year), default=52)
    lfl_totals: Dict[int, float] = {}
    for r in rows:
        if r["iso_week"] <= lfl_max_week:
            lfl_totals[r["year"]] = lfl_totals.get(r["year"], 0.0) + r["arr"]
    data_health = {
        "total_rows": len(rows),
        "years_available": sorted(weeks_per_year),
        "min_year_weeks": min(weeks_per_year.values()) if weeks_per_year else 0,
        "sufficient_for_yoy": all(v >= 10 for v in weeks_per_year.values()) if weeks_per_year else False,
        "model": model,
        "product": _selected_product(product, product_line),
        "geo": _normalize_market_value(sales_market),
    }

    return {
        "source": "live",
        "rows": rows,
        "forecast_continuation": forecast_continuation,
        "weeks_per_year": weeks_per_year,
        "lfl_totals": {str(k): round(v, 0) for k, v in lfl_totals.items()},
        "lfl_max_week": lfl_max_week,
        "data_health": data_health,
    }


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
        return _demo("rows")

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    source = _model_source(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    pf = _source_product_filter(source, product, product_line)
    gf = _source_geo_filter(source, sales_market)
    rolling_next_year = (forecast_type == "rolling" and year is None and quarter is None)
    selected_year = year if year else datetime.date.today().year
    date_filter = (
        f"AND {_quarter_filter(quarter, selected_year)}"
        if quarter
        else (f"AND {_rolling_next_year_filter()}" if rolling_next_year else f"AND {_year_filter(selected_year)}")
    )

    # For non-ensemble selections, use the selected model's lower/upper bands.
    p10_col = source["lower_col"]
    p90_col = source["upper_col"]
    p50_col = source["most_likely_col"]
    table = source["table"]

    if quarter is not None:
        cb_fc_pred = f"forecast_type = '{eff_forecast_type}'"
    elif rolling_next_year:
        cb_fc_pred = "forecast_type IN ('rolling', 'roy', 'forward_1yr')"
    elif selected_year > datetime.date.today().year:
        cb_fc_pred = "forecast_type = 'forward_1yr'"
    else:
        cb_fc_pred = "forecast_type IN ('rolling', 'roy')"

    sql = _normalized_forecast_sql(model, forecast_type, product, product_line,
                                   sales_market, selected_year, quarter, rolling_next_year)

    try:
        rows = await _cached_query(sql, endpoint="/confidence-bands", model=model, forecast_type=eff_forecast_type, product=_selected_product(product, product_line), geo=_normalize_market_value(sales_market), year=selected_year, quarter=quarter)
    except Exception as exc:
        logger.warning("[forecast/confidence-bands] query failed: %s", exc)
        return _demo("rows", str(exc))

    rows = _normalise_rows(rows, model)
    p10_val = sum(row["lower"] for row in rows) if rows and all(row["lower"] is not None for row in rows) else None
    ml_val = sum(row["value"] for row in rows) if rows else None
    p90_val = sum(row["upper"] for row in rows) if rows and all(row["upper"] is not None for row in rows) else None

    return {
        "source": "live" if rows else "unavailable",
        "publication_id": rows[0].get("publication_id") if rows else None,
        "band_quantiles": [0.3, 0.7] if model == "ensemble" else None,
        "band_aggregation": "sum_of_weekly_quantiles_not_calibrated_period_quantiles",
        "model": model,
        "forecast_type": eff_forecast_type,
        "p30": p10_val,
        "most_likely": ml_val,
        "p70": p90_val,
        "worst_case": p10_val,
        "best_case": p90_val,
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
    """Score only same-product, total-grain retained publications at the selected horizon."""
    model = _validate_model(model)
    effective_product = str(_selected_product(product, product_line)).strip().upper()
    effective_product = "Total" if effective_product in ("ALL", "TOTAL") else effective_product
    market = _normalize_market_value(sales_market)
    market = "Total" if market.upper() in ("ALL", "TOTAL") else market
    if effective_product not in ("UCC", "ITSG", "Total"):
        raise HTTPException(status_code=400, detail="Invalid backtest product")
    scope = dict(product=effective_product, market=market, model=model, horizon_weeks=horizon_weeks)
    if not live_mode:
        return backtest_response(**scope, reason="source_unavailable")
    if effective_product == "Total":
        return backtest_response(**scope, reason="combined_history_unverified")
    if market != "Total":
        return backtest_response(**scope, reason="region_history_unverified")
    if model not in RETAINED_MODELS:
        return backtest_response(**scope, reason="model_history_unverified")
    prefix = effective_product.lower()
    vintages = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{prefix}_forecast_vintages`"
    actuals = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`{prefix}_forecast_cbe`"
    sql = build_backtest_query(vintages, actuals, effective_product, model, horizon_weeks)
    try:
        # No shared cache: preserve caller identity and never reuse another scope's pairs.
        raw_rows = await asyncio.to_thread(execute_query, sql)
    except Exception as exc:
        logger.warning("[forecast/backtest] retained source query failed: %s", exc)
        return backtest_response(**scope, reason="source_query_failed")
    response = backtest_response(**scope, raw_rows=raw_rows or [])
    response["source_detail"] = f"{prefix}_forecast_vintages + {prefix}_forecast_cbe"
    return response


# ── GET /graph-explanation ────────────────────────────────────────────────────
_DEMO_EXPLAIN = {
    "title": "Chart Explanation",
    "explanation": ("This chart shows the ARR forecast for the selected product and time period. "
                    "Confidence bands represent the P10 (Risk Floor) to P90 (Stretch Case) range — "
                    "the most likely outcome sits at the P50 centerline. "
                    "Actuals are shown in orange up to today; forecast lines extend to the right."),
    "bullets": ["Ensemble model combines ETS, Prophet, and LightGBM for robustness",
                "Wider bands mean higher uncertainty further out in the forecast horizon",
                "Band coverage target is ~80% — actuals should fall inside the range 4 out of 5 weeks"],
}


@router.get("/graph-explanation")
async def get_graph_explanation(
    graph: str = Query(...),
    product: Optional[str] = None,
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
):
    """Precomputed 'explain this chart in detail' text, matched to the user's
    selection (graph × product × region × period). The notebook precomputes the
    matrix for the CURRENT quarter and CURRENT full year; selections outside
    that (past quarters/years) fall back to the nearest scope with an explicit
    scope_note so the user knows what the text covers."""
    key = (graph or "").strip().lower()
    if key not in _GRAPH_KEYS:
        raise HTTPException(status_code=400, detail="Invalid graph key")
    eff = _selected_product(product, product_line)          # Total | UCC | ITSG
    prod = "ALL" if eff in ("Total", "All", None) else eff
    region = _normalize_market_value(sales_market)          # Total | NA | EMEA | ...

    today = datetime.date.today()
    cur_q, cur_y = ((today.month - 1) // 3) + 1, today.year
    req_period = "quarter" if quarter is not None else "year"

    # Selection outside the precomputed window (current quarter / current year)?
    scope_note = None
    if (year is not None and year != cur_y) or (quarter is not None and quarter != cur_q):
        sel = f"Q{quarter} {year or cur_y}" if quarter is not None else f"FY {year}"
        scope_note = (f"Your selection ({sel}) is outside the precomputed window — "
                      f"showing the current {'quarter' if req_period == 'quarter' else 'year'} explanation instead.")

    if not _live():
        return {"source": "demo", "graph": key, "product": prod, **_DEMO_EXPLAIN}

    def _sql(where_region: str, where_period: str) -> str:
        return f"""
            SELECT title, explanation, bullets, CAST(run_date AS STRING) AS run_date,
                   region, scope_period
            FROM {GRAPH_EXPLAIN_TABLE}
            WHERE graph_key = '{key}' AND product = '{prod.replace(chr(39), chr(39)*2)}'
              AND region = '{where_region.replace(chr(39), chr(39)*2)}'
              AND scope_period = '{where_period}'
              AND run_date = (SELECT MAX(run_date) FROM {GRAPH_EXPLAIN_TABLE})
            LIMIT 1
        """

    rows = None
    # Cascade: exact (region, period) → Total region → legacy schema (no region cols)
    for wr, wp, note in (
        (region, req_period, None),
        ("Total", req_period, f"No region-specific explanation for {region} — showing all-regions." if region != "Total" else None),
    ):
        try:
            rows = await asyncio.to_thread(execute_query, _sql(wr, wp))
        except Exception as exc:
            logger.warning("[forecast/graph-explanation] query failed (schema fallback): %s", exc)
            # Legacy table without region/scope_period columns (pre-matrix runs)
            try:
                rows = await asyncio.to_thread(execute_query, f"""
                    SELECT title, explanation, bullets, CAST(run_date AS STRING) AS run_date
                    FROM {GRAPH_EXPLAIN_TABLE}
                    WHERE graph_key = '{key}' AND product = '{prod.replace(chr(39), chr(39)*2)}'
                      AND run_date = (SELECT MAX(run_date) FROM {GRAPH_EXPLAIN_TABLE})
                    LIMIT 1
                """)
                note = "Explanation covers the product's current quarter (all regions) — re-run the unify notebook for selection-specific text."
            except Exception as exc2:
                logger.warning("[forecast/graph-explanation] legacy query failed: %s", exc2)
                rows = None
        if rows:
            if note:
                scope_note = f"{scope_note} {note}".strip() if scope_note else note
            break

    if not rows:
        return {"source": "demo", "graph": key, "product": prod, **_DEMO_EXPLAIN,
                "explanation": ("Personalized explanation for this chart is being generated — "
                                 "it will appear here after the next daily forecast run (7am ET).")}

    r = rows[0]
    try:
        bullets = json.loads(r.get("bullets") or "[]")
    except Exception:
        bullets = []
    return {
        "source": "live", "graph": key, "product": prod,
        "region": r.get("region") or "Total", "scope_period": r.get("scope_period") or "quarter",
        "scope_note": scope_note,
        "title": r.get("title"), "explanation": r.get("explanation"),
        "bullets": bullets, "run_date": r.get("run_date"),
    }


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


@router.get("/run-history")
async def get_run_history(
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Return one adjacent-vintage comparison row for every retained run."""
    if not live_mode:
        return {"source": "demo", "available": False, "runs": []}

    product_filter = (
        "AND product IN ('UCC', 'ITSG')"
        if not product_line or product_line in ("All", "all")
        else _product_filter(product_line, col="product")
    )
    market_filter = _source_geo_filter({}, sales_market) if sales_market else ""
    norm = _normalized_market_expr("sales_market")
    sql = f"""
        WITH ranked_runs AS (
            SELECT rd, ROW_NUMBER() OVER (ORDER BY rd DESC) AS rn
            FROM (
                SELECT DISTINCT CAST(run_date AS DATE) AS rd
                FROM {FC_TABLE}
            )
        ), pairs AS (
            SELECT current.rd AS current_rd, previous.rd AS previous_rd
            FROM ranked_runs current
            JOIN ranked_runs previous ON previous.rn = current.rn + 1
        ), fc AS (
            SELECT CAST(run_date AS DATE) AS rd,
                   product, {norm} AS sales_market,
                   CAST(ds AS DATE) AS ds,
                   CAST(Most_Likely AS DOUBLE) AS ml
            FROM {FC_TABLE}
            WHERE forecast_type IN ('rolling', 'roy')
              {product_filter} {market_filter}
        )
        SELECT p.current_rd, p.previous_rd,
               a.product, a.sales_market,
               SUM(a.ml) AS current_ml,
               SUM(b.ml) AS previous_ml,
               COUNT(*) AS overlap_weeks
        FROM pairs p
        JOIN fc a ON a.rd = p.current_rd
        JOIN fc b ON b.rd = p.previous_rd
          AND a.ds = b.ds
          AND a.product = b.product
          AND a.sales_market = b.sales_market
        GROUP BY p.current_rd, p.previous_rd, a.product, a.sales_market
        ORDER BY p.current_rd DESC, ABS(SUM(a.ml) - SUM(b.ml)) DESC
    """
    try:
        rows = await _cached_query(sql, endpoint="/run-history", model="ensemble",
                                   forecast_type="rolling", product=product_line,
                                   geo=sales_market, year=None, quarter=None)
    except Exception as exc:
        logger.warning("[forecast/run-history] query failed: %s", exc)
        return {"source": "live", "available": False, "runs": [], "error": str(exc)}

    history = {}
    for row in rows:
        key = (str(row.get("current_rd")), str(row.get("previous_rd")))
        current = _f(row.get("current_ml"))
        previous = _f(row.get("previous_ml"))
        item = history.setdefault(key, {
            "run_date": key[0], "previous_run": key[1], "overlap_weeks": 0,
            "current": 0, "previous": 0, "delta": 0, "delta_pct": None, "drivers": [],
        })
        item["current"] += current
        item["previous"] += previous
        item["overlap_weeks"] += int(_f(row.get("overlap_weeks")))
        item["drivers"].append({
            "product": row.get("product"), "sales_market": row.get("sales_market"),
            "delta": current - previous,
        })

    result = []
    for item in history.values():
        item["delta"] = item["current"] - item["previous"]
        item["delta_pct"] = (item["delta"] / item["previous"] * 100) if item["previous"] else None
        item["drivers"] = sorted(item["drivers"], key=lambda d: abs(d["delta"]), reverse=True)[:3]
        result.append(item)
    return {"source": "live", "available": bool(result), "runs": result}


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


def _model_lab_sql(product: str) -> str:
    """Per-model forecast from forecast_pure_predictions (latest run, calibrated bands).
    Normalizes model names (Prophet_trend→Prophet, LGB variants→Global_LGB_Q50).
    Only Adaptive_Ensemble is recommended_for_exec."""
    return f"""
        SELECT
            CAST(ds AS STRING) AS ds,
            CASE
                WHEN model = 'Prophet_trend' THEN 'Prophet'
                WHEN model LIKE 'Global_LGB_Q50_%' THEN 'Global_LGB_Q50'
                ELSE model
            END AS model,
            COALESCE(CAST(blended_p50 AS DOUBLE), CAST(p50 AS DOUBLE)) AS forecast,
            CAST(p10 AS DOUBLE) AS p10,
            CAST(p50 AS DOUBLE) AS p50,
            CAST(p90 AS DOUBLE) AS p90,
            CASE WHEN model = 'Adaptive_Ensemble' THEN 1 ELSE 0 END AS recommended,
            CAST(run_date AS STRING) AS run_date
        FROM {PURE_TABLE}
        WHERE product = '{product}'
          AND model NOT IN ('Global_LGB_Q50')
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

    # V2: read per-model bands from forecast_pure_predictions (total grain only).
    # Market-grain model lab is not available (pure_predictions has no sales_market).
    if grain == "market":
        return _demo_model_lab(product, grain)

    rows_raw, err = None, None
    try:
        rows_raw = await _cached_query(
            _model_lab_sql(product),
            endpoint="/model-lab",
            model="ensemble",
            forecast_type="forecast",
            product=product,
            geo="Total",
            year=None,
            quarter=None,
            grain=grain,
        )
    except Exception as exc:
        err = str(exc)
        logger.warning("[forecast/model-lab] pure_predictions query failed: %s", exc)

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


@router.get("/forward-outlook")
async def get_forward_outlook(
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    live_mode: bool = Depends(_live_mode_dependency),
):
    """
    Forward 12-month weekly outlook from V5 forecast tables (Adaptive_Ensemble).
    Returns actual+forecast-ready series for executive forward-looking visuals.
    """
    if not live_mode:
        return _demo("rows")

    product, market, grain = _v5_scope(product_line, sales_market)

    rows_raw = None
    err = None
    try:
        rows_raw = await _cached_query(
            _v5_forward_sql(product, market),
            endpoint="/forward-outlook",
            model="ensemble",
            forecast_type="forecast",
            product=product,
            geo=market,
            year=None,
            quarter=None,
        )
    except Exception as exc:
        err = str(exc)
        logger.warning("[forecast/forward-outlook] snapshot query failed: %s", exc)

    if not rows_raw:
        return _demo("rows", error=err or "No V5 forward outlook rows")

    rows = []
    for r in rows_raw:
        ds = str(r.get("ds") or "")[:10]
        if not ds:
            continue
        rows.append({
            "date": ds,
            "arr_actual": None,
            "arr_worst": round(_f(r.get("arr_worst")), 0),
            "arr_likely": round(_f(r.get("arr_likely")), 0),
            "arr_best": round(_f(r.get("arr_best")), 0),
        })

    return {
        "source": "live",
        "forecast_type": "forward_1yr",
        "product": product,
        "sales_market": market,
        "rows": rows,
    }


@router.get("/monthly-combined")
async def get_monthly_combined(
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    live_mode: bool = Depends(_live_mode_dependency),
):
    """
    Monthly combined view for the next 12 months:
    - actuals from arr_forecast_v2 (closed weeks)
    - forecast scenarios from V5 Adaptive_Ensemble output
    """
    if not live_mode:
        return _demo("months")

    product, market, grain = _v5_scope(product_line, sales_market)

    fc_rows_raw = None
    err = None
    try:
        fc_rows_raw = await _cached_query(
            _v5_monthly_sql(product, market),
            endpoint="/monthly-combined",
            model="ensemble",
            forecast_type="forecast",
            product=product,
            geo=market,
            year=None,
            quarter=None,
        )
    except Exception as exc:
        err = str(exc)
        logger.warning("[forecast/monthly-combined] snapshot query failed: %s", exc)

    if not fc_rows_raw:
        return _demo("months", error=err or "No V5 monthly combined rows")

    try:
        act_rows_raw = await _cached_query(
            _actuals_monthly_next_year_sql(product_line, sales_market),
            endpoint="/monthly-combined",
            model="ensemble",
            forecast_type="actuals",
            product=_selected_product(None, product_line),
            geo=_normalize_market_value(sales_market),
            year=None,
            quarter=None,
            metric="actuals",
        )
    except Exception as exc:
        logger.warning("[forecast/monthly-combined] actuals query failed: %s", exc)
        act_rows_raw = []

    act_map = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): r
        for r in act_rows_raw
    }
    fc_map = {
        (int(_f(r.get("yr"))), int(_f(r.get("mth")))): r
        for r in fc_rows_raw
    }

    months = []
    for key in sorted(set(act_map) | set(fc_map)):
        yr, mth = key
        a = act_map.get(key)
        f = fc_map.get(key)
        src = f or a
        months.append({
            "year": yr,
            "quarter": int(_f(src.get("qtr"))),
            "month": mth,
            "month_name": str(src.get("month_name") or ""),
            "arr_actual": round(_f(a.get("arr_actual")), 0) if a else None,
            "arr_worst": round(_f(f.get("arr_worst")), 0) if f else None,
            "arr_likely": round(_f(f.get("arr_likely")), 0) if f else None,
            "arr_best": round(_f(f.get("arr_best")), 0) if f else None,
        })

    return {
        "source": "live",
        "forecast_type": "forward_1yr",
        "product": product,
        "sales_market": market,
        "months": months,
    }


# ── GET /weekly-all-models ────────────────────────────────────────────────────
@router.get("/weekly-all-models")
async def get_weekly_all_models(
    product_line: Optional[str] = None,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """All model weekly forecasts in one query — powers the multi-model cumulative line chart.
    Returns rows with ds, actual, and one column per model (ensemble, ets, prophet, lgbm, mstl, dhr).
    Forecasts limited to future weeks; actuals returned for all closed weeks."""
    if not live_mode:
        import random, datetime as dt
        today = dt.date.today()
        rows = []
        base = 250_000
        for i in range(52):
            d = today - dt.timedelta(weeks=26) + dt.timedelta(weeks=i)
            is_actual = d < today
            actual = base + random.randint(-40000, 80000) if is_actual else None
            rows.append({
                "date": str(d), "actual": actual,
                "ensemble": base + random.randint(-30000, 60000) if not is_actual else None,
                "ets":      base + random.randint(-50000, 80000) if not is_actual else None,
                "prophet":  base + random.randint(-45000, 75000) if not is_actual else None,
                "lgbm":     base + random.randint(-35000, 65000) if not is_actual else None,
                "mstl":     base + random.randint(-40000, 70000) if not is_actual else None,
                "dhr":      base + random.randint(-55000, 85000) if not is_actual else None,
            })
        return {"rows": rows, "source": "demo"}

    eff_year = year or datetime.date.today().year
    # Individual model columns (arr_ets, arr_prophet, etc.) only exist on
    # product-level rows (UCC / ITSG), NOT on the pre-computed Total rollup.
    # So for "All Products" we SUM across UCC+ITSG; for a specific product we filter.
    eff_product = _selected_product(None, product_line)
    if eff_product in ("Total", "All", None):
        prod_filter = "AND product IN ('UCC', 'ITSG')"
    else:
        prod_filter = f"AND product = '{eff_product.replace(chr(39), chr(39)*2)}'"

    yf = _year_filter(eff_year)
    qf = _quarter_filter(quarter, eff_year) if quarter else ""
    rolling_next_year = (year is None and quarter is None)
    date_filter = f"AND {qf}" if qf else (f"AND {_rolling_next_year_filter()}" if rolling_next_year else f"AND {yf}")

    # Use arr_forecast_v2 directly — it has per-model columns (arr_ets, arr_prophet,
    # arr_lightgbm, etc.) written by arr_forecast_v2_main.py.  forecast_results_v2compat
    # only has Most_Likely (Adaptive_Ensemble) at product level; the individual model
    # columns are NULL there because the V5 pipeline only writes ensemble rows.
    ARR_V2 = f"`{FORECAST_CATALOG}`.`{FORECAST_SCHEMA}`.`arr_forecast_v2`"
    sql = f"""
        SELECT
            CAST(ds AS STRING) AS ds,
            SUM(COALESCE(CAST(Actuals       AS DOUBLE), 0)) AS actual,
            SUM(COALESCE(CAST(Most_Likely   AS DOUBLE), 0)) AS ensemble,
            SUM(COALESCE(CAST(arr_ets       AS DOUBLE), 0)) AS ets,
            SUM(COALESCE(CAST(arr_prophet   AS DOUBLE), 0)) AS prophet,
            SUM(COALESCE(CAST(arr_lightgbm  AS DOUBLE), 0)) AS lgbm,
            SUM(COALESCE(CAST(arr_mstl_v2   AS DOUBLE), 0)) AS mstl,
            SUM(COALESCE(CAST(arr_dhr_arima AS DOUBLE), 0)) AS dhr,
            forecast_type
        FROM {ARR_V2}
        WHERE run_date = (SELECT MAX(run_date) FROM {ARR_V2})
          {prod_filter}
          AND {_normalized_market_expr('sales_market')} = 'Total'
          {date_filter}
        GROUP BY ds, forecast_type
        ORDER BY ds, CASE forecast_type WHEN 'actuals' THEN 0 ELSE 1 END
    """

    try:
        rows_raw = await _cached_query(sql, endpoint="/weekly-all-models",
                                       model="ensemble", forecast_type="rolling",
                                       product=_selected_product(None, product_line),
                                       geo="Total", year=eff_year, quarter=quarter)
    except Exception as exc:
        logger.warning("[forecast/weekly-all-models] query failed: %s", exc)
        return _demo("rows", error=str(exc))

    # Merge actuals and forecast rows for the same date into one point.
    # The compat view can have both forecast_type=actuals and rolling for the same ds.
    merged: dict[str, dict] = {}
    for r in rows_raw:
        ftype = str(r.get("forecast_type") or "").strip().lower()
        ds = str(r.get("ds") or "")[:10]
        if ds not in merged:
            merged[ds] = {"date": ds, "actual": None, "ensemble": None,
                          "ets": None, "prophet": None, "lgbm": None, "mstl": None, "dhr": None}
        if ftype == "actuals":
            v = _f(r.get("actual"))
            if v > 0:
                merged[ds]["actual"] = v
        else:
            for col, key in [("ensemble","ensemble"),("ets","ets"),("prophet","prophet"),
                              ("lgbm","lgbm"),("mstl","mstl"),("dhr","dhr")]:
                v = _f(r.get(key))
                if v > 0 and merged[ds][col] is None:
                    merged[ds][col] = v

    rows = sorted(merged.values(), key=lambda x: x["date"])
    return {"rows": rows, "source": "live"}


# ── GET /accuracy-by-quarter ───────────────────────────────────────────────────
@router.get("/accuracy-by-quarter")
async def get_accuracy_by_quarter(
    product_line: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Quarterly sMAPE matrix: rows = models, columns = past quarters.
    Uses ucc_forecast_vintages (per-model forecast history, 6 models) joined
    against ucc_forecast_cbe actuals at total level. Returns long-format rows
    which are pivoted into the model x quarter matrix for the Accuracy tab."""
    if not live_mode:
        # Demo: return a plausible matrix for display
        return {"quarters": ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"],
                "models": [
                    {"model": "Ensemble",  "values": [18.2, 16.4, 21.1, 14.8, 17.3, 19.6]},
                    {"model": "Prophet",   "values": [22.1, 19.8, 24.3, 18.2, 21.0, 23.5]},
                    {"model": "ETS",       "values": [25.4, 21.3, 27.8, 20.1, 24.2, 26.1]},
                    {"model": "LightGBM",  "values": [20.3, 18.1, 22.6, 16.9, 19.8, 21.4]},
                    {"model": "MSTL",      "values": [23.7, 20.4, 25.9, 19.3, 22.5, 24.8]},
                    {"model": "DHR-ARIMA", "values": [26.8, 23.2, 29.1, 21.7, 25.6, 27.9]},
                ]}

    pf_inner = _product_filter(None, product_line)                       # single-table CTE
    pf_outer = _product_filter(None, product_line, col="f.product")      # joined scope — must
    # be qualified: both sides of the join expose `product`, and an unqualified
    # reference raises AMBIGUOUS_REFERENCE in Spark (this is why the matrix was
    # falling back to the empty demo payload).

    # Use arr_forecast_v2 directly — it is append-only so past runs' forecast
    # rows (rolling/roy) for now-historical weeks still exist there.
    # The compat view only shows max(run_date) so those historical vintages are gone.
    # CRITICAL: restrict to product='UCC' only. The ITSG and Total rows in
    # arr_forecast_v2 contain ALL revenue (not Growth-only), while actuals from
    # the CBE pipeline are Growth-only. Comparing them produces 100-200% sMAPE.

    # One vintage per week: the EARLIEST run that forecast it ("as first
    # published"). Averaging every retained vintage over-weights easy 1-week-
    # ahead re-forecasts and late-quarter weeks (which accumulate more runs).
    # Scores every CLOSED WEEK (the actuals join enforces closure), including
    # the elapsed portion of the current quarter — labelled "(QTD)" — because
    # arr_forecast_v2 only retains vintages from mid-June 2026, so a strict
    # closed-quarters-only matrix is empty until the first full quarter closes.
    sql = f"""
        WITH actuals AS (
            SELECT CAST(ds AS DATE) AS ds, CAST(forecast AS DOUBLE) AS actual
            FROM {UCC_CBE_TABLE}
            WHERE source = 'actual' AND model = 'Adaptive_Ensemble'
              AND grain_level = 'total' AND UPPER(sales_market) = 'ALL'
              AND COALESCE(CAST(forecast AS DOUBLE), 0) > 0
        ),
        fc AS (
            SELECT model, CAST(ds AS DATE) AS ds,
                   CAST(run_date_utc AS DATE) AS run_date,
                   CAST(p50 AS DOUBLE) AS p50,
                   ROW_NUMBER() OVER (
                       PARTITION BY model, CAST(ds AS DATE)
                       ORDER BY CAST(run_date_utc AS DATE) ASC
                   ) AS rn
            FROM {UCC_VINTAGES_TABLE}
            WHERE grain_level = 'total' AND UPPER(sales_market) = 'ALL'
              AND CAST(ds AS DATE) < CURRENT_DATE()
              AND COALESCE(CAST(p50 AS DOUBLE), 0) > 0
        )
        SELECT
            YEAR(f.ds) AS yr,
            QUARTER(f.ds) AS qtr,
            f.model,
            COUNT(*) AS n_weeks,
            ROUND(AVG(
                ABS(f.p50 - a.actual)
                / ((ABS(f.p50) + ABS(a.actual)) / 2.0) * 100
            ), 1) AS smape
        FROM fc f
        INNER JOIN actuals a ON f.ds = a.ds
        WHERE f.rn = 1
        GROUP BY YEAR(f.ds), QUARTER(f.ds), f.model
        ORDER BY yr, qtr, f.model
        LIMIT 120
    """

    def _demo_matrix(error: Optional[str] = None):
        # Same shape as the live payload so the matrix always renders,
        # explicitly demo-flagged (previously error/empty returned a shapeless
        # payload and the tab showed a blank empty-state).
        out = {"source": "demo",
               "quarters": ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"],
               "models": [
                   {"model": "Ensemble",  "values": [18.2, 16.4, 21.1, 14.8, 17.3, 19.6]},
                   {"model": "Prophet",   "values": [22.1, 19.8, 24.3, 18.2, 21.0, 23.5]},
                   {"model": "ETS",       "values": [25.4, 21.3, 27.8, 20.1, 24.2, 26.1]},
                   {"model": "LightGBM",  "values": [20.3, 18.1, 22.6, 16.9, 19.8, 21.4]},
                   {"model": "MSTL",      "values": [23.7, 20.4, 25.9, 19.3, 22.5, 24.8]},
                   {"model": "DHR-ARIMA", "values": [26.8, 23.2, 29.1, 21.7, 25.6, 27.9]},
               ]}
        if error:
            out["error"] = error
        return out

    try:
        rows_raw = await _cached_query(sql, endpoint="/accuracy-by-quarter",
                                       model="ensemble", forecast_type="actuals",
                                       product=_selected_product(None, product_line),
                                       geo="Total", year=None, quarter=None)
    except Exception as exc:
        logger.warning("[forecast/accuracy-by-quarter] query failed: %s", exc)
        return _demo_matrix(str(exc))

    if not rows_raw:
        # No quarterly vintage data available (typical for the new unified pipeline
        # which only retains 1 run_date). Return a fallback using the monitoring
        # baseline WAPE so the accuracy card shows the model's true holdout accuracy.
        try:
            lb_rows = await _cached_query(
                f"SELECT best_mape FROM {LB_TABLE} WHERE run_date = (SELECT MAX(run_date) FROM {LB_TABLE}) LIMIT 1",
                endpoint="/accuracy-by-quarter", model="ensemble", forecast_type="actuals",
                product="Total", geo="Total", year=None, quarter=None, metric="lb_fallback"
            )
            if lb_rows and lb_rows[0].get("best_mape") is not None:
                wape = round(float(lb_rows[0]["best_mape"]), 1)
                _today = datetime.date.today()
                _cur_q = ((_today.month - 1) // 3) + 1
                return {
                    "source": "live",
                    "basis": "holdout WAPE from monitoring baseline (no quarterly vintage data yet)",
                    "quarters": [f"Q{_cur_q} {_today.year} (holdout)"],
                    "n_weeks": [13],
                    "models": [
                        {"model": "Ensemble", "values": [wape]},
                        {"model": "Prophet", "values": [None]},
                        {"model": "ETS", "values": [None]},
                        {"model": "LightGBM", "values": [None]},
                        {"model": "MSTL", "values": [None]},
                        {"model": "DHR-ARIMA", "values": [None]},
                    ],
                }
        except Exception:
            pass
        return _demo_matrix()

    # -- Pivot long-format results (one row per model per quarter) into matrix --
    MODEL_DISPLAY_MAP = {
        "Adaptive_Ensemble": ("Ensemble", "ens_mape"),
        "Prophet_trend": ("Prophet", "prophet_mape"),
        "ETS": ("ETS", "ets_mape"),
        "Global_LGB_Q50_UCC": ("LightGBM", "lgbm_mape"),
        "MSTL_v2": ("MSTL", "mstl_mape"),
        "DHR_ARIMA": ("DHR-ARIMA", "dhr_mape"),
    }
    _today = datetime.date.today()
    _cur_q, _cur_y = ((_today.month - 1) // 3) + 1, _today.year

    # Collect unique quarters in order and per-model values
    qtr_order: list[str] = []
    qtr_n_weeks: dict[str, int] = {}
    model_vals: dict[str, dict] = {}  # model -> {qtr_label: smape}

    for r in rows_raw:
        yr, qtr = int(r.get("yr", 0)), int(r.get("qtr", 0))
        label = f"Q{qtr} {yr}" + (" (QTD)" if qtr == _cur_q and yr == _cur_y else "")
        if label not in qtr_order:
            qtr_order.append(label)
        qtr_n_weeks[label] = max(qtr_n_weeks.get(label, 0), int(_f(r.get("n_weeks"))))
        model_raw = str(r.get("model", ""))
        smape_val = _f(r.get("smape"), None)
        if model_raw not in model_vals:
            model_vals[model_raw] = {}
        model_vals[model_raw][label] = smape_val

    # Build response in canonical model order
    models_out = []
    for raw_name, (display_name, _) in MODEL_DISPLAY_MAP.items():
        vals = model_vals.get(raw_name, {})
        models_out.append({"model": display_name, "values": [vals.get(q) for q in qtr_order]})

    return {"quarters": qtr_order, "n_weeks": [qtr_n_weeks.get(q, 0) for q in qtr_order],
            "models": models_out,
            "basis": "first-published forecast vs closed actuals (one vintage per week, per model)",
            "source": "live"}


# ── GET /leaderboard ────────────────────────────────────────────────────────────
_BADGE_MODELS = {
    "Ensemble": "ensemble", "ETS": "ets", "Prophet": "prophet",
    "LightGBM": "lightgbm", "MSTL_v2": "mstl_v2", "DHR_ARIMA": "dhr_arima",
}


def _leaderboard_error_values(row):
    """Expose published quarterly values separately; zero is a valid error."""
    quarterly = {label: _f(row.get(f"qtr_{key}"), None) for label, key in _BADGE_MODELS.items()}
    # Provenance tells the frontend pill whether the quarterly error is from a
    # closed-quarter holdout ('measured') or missing ('unavailable').  Without
    # this the pill defaults to '(unverified)'.
    quarterly_provenance = {
        label: {"status": "measured"} if val is not None else {"status": "unavailable"}
        for label, val in quarterly.items()
    }
    values = {label: value if value is not None else _f(row.get(f"mape_{_BADGE_MODELS[label]}"), 999)
              for label, value in quarterly.items()}
    if values["Ensemble"] == 999:
        values.pop("Ensemble")
    return {**values, "quarterly_errors": quarterly, "quarterly_provenance": quarterly_provenance}


def _quarterly_evidence(row, records):
    evidence = {}
    for label, key in _BADGE_MODELS.items():
        value = row["quarterly_errors"][label]
        evidence[label] = {"status": "unavailable" if value is None else "unverified"}
        if value is None or not math.isfinite(value) or row["sales_market"] != "Total":
            continue
        matches = [record for record in records
                   if record.get("product") == row["product"]
                   and (str(record.get("model", "")).startswith("Global_LGB") if key == "lightgbm"
                        else record.get("model") == _ACC_MODEL[key])]
        if len(matches) != 1:
            continue
        record = matches[0]
        published_value = _f(record.get("quarterly_wape"), None)
        publication_date = str(record.get("run_date") or "")[:10]
        if (published_value is None or not math.isfinite(published_value)
                or not math.isclose(value, published_value, rel_tol=1e-9, abs_tol=1e-9)
                or not publication_date or publication_date != str(row.get("publication_date") or "")[:10]):
            continue
        source = str(record.get("source") or "")
        quarter = str(record.get("quarter_label") or "").strip() or None
        closed = str(record.get("is_closed")).lower() in ("true", "1")
        count = _f(record.get("quarters_evaluated"), 0)
        count = int(count) if math.isfinite(count) and count > 0 and count.is_integer() else 0
        status = "unverified"
        if source.startswith("estimated_"):
            status = "estimated"
        elif source == "dollar_weighted_blend":
            status = "blended"
        elif source == "holdout_closed_quarter" and quarter and closed and count > 0:
            status = "measured"
        evidence[label] = {
            "status": status, "source": source or None, "source_model": record.get("model"),
            "quarter": quarter, "is_closed": closed, "quarters_evaluated": count,
            "publication_date": publication_date,
            "published_at": str(record["published_at_utc"]) if record.get("published_at_utc") is not None else None,
        }
    return evidence


@router.get("/leaderboard")
async def get_leaderboard(
    live_mode: bool = Depends(_live_mode_dependency),
):
    """MAPE leaderboard — all product × sales_market slices.
    Includes quarterly error from monitoring baselines when available."""
    if not live_mode:
        return _demo("data")

    lb_cols = await _lb_columns()
    mstl_col = _pick_lb_column(lb_cols, "mape_mstl_v2", "mape_chronos")
    # DHR has no legacy equivalent in old schemas; keep NULL when column is missing.
    dhr_col = _pick_lb_column(lb_cols, "mape_dhr_arima")
    # Ensemble holdout WAPE (from the monitoring baselines via the unify view);
    # NULL on legacy schemas → realized-MAPE fallback below fills it.
    ens_col = _pick_lb_column(lb_cols, "mape_ensemble")

    sql = f"""
        SELECT
            product,
            {_normalized_market_expr('sales_market')} AS sales_market,
            AVG(CAST({ens_col} AS DOUBLE)) AS mape_ensemble,
            AVG(CAST(mape_ets AS DOUBLE)) AS mape_ets,
            AVG(CAST(mape_prophet AS DOUBLE)) AS mape_prophet,
            AVG(CAST(mape_lightgbm AS DOUBLE)) AS mape_lightgbm,
            AVG(CAST({mstl_col} AS DOUBLE)) AS mape_mstl_v2,
            AVG(CAST({dhr_col} AS DOUBLE)) AS mape_dhr_arima,
            AVG(CAST(best_mape AS DOUBLE)) AS best_mape,
            MAX(best_model) AS best_model,
            MAX(CAST(run_date AS STRING)) AS publication_date,
            AVG(CAST({_pick_lb_column(lb_cols, 'quarterly_wape_ensemble')} AS DOUBLE)) AS qtr_ensemble,
            AVG(CAST({_pick_lb_column(lb_cols, 'quarterly_wape_ets')} AS DOUBLE)) AS qtr_ets,
            AVG(CAST({_pick_lb_column(lb_cols, 'quarterly_wape_prophet')} AS DOUBLE)) AS qtr_prophet,
            AVG(CAST({_pick_lb_column(lb_cols, 'quarterly_wape_lightgbm')} AS DOUBLE)) AS qtr_lightgbm,
            AVG(CAST({_pick_lb_column(lb_cols, 'quarterly_wape_mstl_v2')} AS DOUBLE)) AS qtr_mstl_v2,
            AVG(CAST({_pick_lb_column(lb_cols, 'quarterly_wape_dhr_arima')} AS DOUBLE)) AS qtr_dhr_arima
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
                **_leaderboard_error_values(r),
        "publication_date": str(r["publication_date"]) if r.get("publication_date") is not None else None,
        # Chronos intentionally omitted — not in model suite, NULL in live data
        "best_mape":      _f(r.get("best_mape"),       999),
        "best_model":     str(r.get("best_model") or ""),
    } for r in rows_raw]

    try:
        quarterly_records = await _cached_query(f"""
            SELECT product, model, quarterly_wape, quarter_label, is_closed,
                   quarters_evaluated, source, run_date, published_at_utc
            FROM {QUARTERLY_ACCURACY_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {QUARTERLY_ACCURACY_TABLE})
        """, endpoint="/leaderboard", metric="quarterly_provenance")
    except Exception as exc:
        logger.warning("[forecast/leaderboard] quarterly provenance unavailable: %s", exc)
        quarterly_records = []
    for row in data:
        row["quarterly_provenance"] = _quarterly_evidence(row, quarterly_records)

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
            # Holdout WAPE from the view wins; realized MAPE only fills gaps.
            if "Ensemble" in row:
                continue
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
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    return {
        "source": "unavailable", "confidence_score": None,
        "confidence_label": "Unavailable", "model": _validate_model(model),
        "product": _selected_product(None, product_line),
        "sales_market": _normalize_market_value(sales_market),
        "reason": "No validated confidence score for this model, period and selection.",
        "reasons": [],
    }


@router.get("/driver-bridge")
async def get_driver_bridge(
    model: Optional[str] = Query("ensemble"),
    product: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    return {
        "source": "unavailable", "components": [],
        "actual_total": None, "plan_total": None, "variance": None,
        "model": _validate_model(model or "ensemble"),
        "product": _selected_product(product, product_line),
        "sales_market": _normalize_market_value(sales_market),
        "reason": "No approved plan or matched issued forecast for the same closed weeks.",
    }


@router.get("/risk-radar")
async def get_risk_radar(
    forecast_type: str = Query("rolling"),
    model: str = Query("ensemble"),
    year: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
    limit: int = Query(20),
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
    live_mode: bool = Depends(_live_mode_dependency),
):
    """Top at-risk slices ranked by downside dollar impact."""
    if not live_mode or model != "ensemble":
        return _demo("items", "Published P30/P70 risk bounds unavailable for this selection")

    forecast_type = _validate_forecast_type(forecast_type)
    model = _validate_model(model)
    source = _model_source(model)
    eff_forecast_type = _effective_forecast_type(model, forecast_type)
    value_col = source["most_likely_col"]
    lower_col = source["lower_col"]
    upper_col = source["upper_col"]
    selected_year = year if year else datetime.date.today().year
    date_filter = _quarter_filter(quarter, selected_year) if quarter else _year_filter(selected_year)
    product_pred = (_product_filter(None, product_line) if _selected_product(None, product_line) != "Total" else "AND product IN ('UCC', 'ITSG')")
    market_pred = (_geo_filter(sales_market) if _normalize_market_value(sales_market) != "Total" else f"AND {_normalized_market_expr()} <> 'Total'")
    type_pred = _monthly_forecast_type_condition(forecast_type, False, selected_year)
    try:
        rows = await _cached_query(f"""
                        SELECT
                            product,
                            {_normalized_market_expr('sales_market')} AS sales_market,
                            SUM(COALESCE(CAST({value_col} AS DOUBLE),0)) AS likely,
                            SUM(COALESCE(CAST({lower_col} AS DOUBLE),0)) AS worst,
                            SUM(COALESCE(CAST({upper_col} AS DOUBLE),0)) AS best
                                                FROM (
                                                        SELECT * FROM {FC_TABLE} forecast
                                                        WHERE {_latest_run()} AND {type_pred} AND {date_filter}
                                                            {product_pred} {market_pred}
                                                            AND CAST(ds AS DATE) > COALESCE((
                                                                SELECT MAX(CAST(actual.ds AS DATE)) FROM {FC_TABLE} actual
                                                                WHERE actual.forecast_type = 'actuals' AND actual.Actuals IS NOT NULL
                                                                    AND actual.run_date = forecast.run_date
                                                                    AND actual.product = forecast.product
                                                                    AND actual.sales_market = forecast.sales_market
                                                            ), DATE'1900-01-01')
                                                        QUALIFY ROW_NUMBER() OVER (PARTITION BY ds, product, sales_market ORDER BY
                                                                CASE forecast_type WHEN 'rolling' THEN 1 WHEN 'roy' THEN 2 ELSE 3 END) = 1
                                                ) scoped
                        GROUP BY product, {_normalized_market_expr('sales_market')}
        """, endpoint="/risk-radar", model=model, forecast_type=eff_forecast_type, product=_selected_product(None, product_line), geo=_normalize_market_value(sales_market), year=selected_year, quarter=quarter, limit=limit)

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
    product_line: Optional[str] = None,
    sales_market: Optional[str] = None,
):
    """Board/exec snapshot with top risks and priority actions."""
    try:
        live_mode = _live_mode_dependency()
        confidence = await get_confidence(model=model, year=year, quarter=quarter, product_line=product_line, sales_market=sales_market, live_mode=live_mode)
        bridge = await get_driver_bridge(model=model, product=None, year=year, quarter=quarter, product_line=product_line, sales_market=sales_market, live_mode=live_mode)
        # Explicitly pass forecast_type to avoid FastAPI Query default objects when
        # this endpoint calls get_risk_radar as a plain Python function.
        radar = await get_risk_radar(forecast_type="rolling", model=model, year=year, quarter=quarter, limit=20, product_line=product_line, sales_market=sales_market, live_mode=live_mode)
        freshness = await get_freshness(live_mode=live_mode)
        top_risks = (radar.get("items") or [])[:3]
        moves = []
        return {
            "source": "live" if radar.get("source") == "live" else "unavailable",
            "status": "partial",
            "unavailable_sections": ["confidence", "plan_variance", "recommendations"],
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
        return _demo("top_risks", "Meeting data unavailable for this selection")


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


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO ANALYSIS ENDPOINTS (powers Exec Mode scenario UI)
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/scenario-grid")
async def get_scenario_grid(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    quarter:      Optional[str] = Query(None),
    live_mode:    bool          = Depends(_live_mode_dependency),
):
    """
    Named scenario outcomes (Conservative / Baseline / Stretch) from real model
    quantiles, broken down by product x market x fiscal quarter.

    The UI shows 1-click scenario buttons and the sliders interpolate between
    these real model-derived outcomes.
    """
    if not live_mode:
        return _demo("scenarios", error="Databricks unavailable")

    effective_product = _selected_product(product, product_line)
    effective_market = _normalize_market_value(sales_market)

    where_parts = ["run_date = (SELECT MAX(run_date) FROM " + SCENARIO_GRID_TABLE + ")"]
    if effective_product != "Total" or product_line:
        where_parts.append(f"product = '{effective_product}'")
    if effective_market != "Total":
        where_parts.append(f"sales_market = '{effective_market}'")
    if quarter:
        where_parts.append(f"fiscal_quarter = '{quarter}'")

    where_clause = " AND ".join(where_parts)

    sql = f"""
        SELECT
            product,
            sales_market,
            fiscal_quarter,
            ROUND(conservative, 2) AS conservative,
            ROUND(baseline, 2) AS baseline,
            ROUND(stretch, 2) AS stretch,
            ROUND(most_likely, 2) AS most_likely,
            CAST(weeks_in_quarter AS INT) AS weeks_in_quarter,
            ROUND(actual_to_date, 2) AS actual_to_date,
            CAST(actual_weeks AS INT) AS actual_weeks,
            CAST(fiscal_year AS INT) AS fiscal_year,
            source_model
        FROM {SCENARIO_GRID_TABLE}
        WHERE {where_clause}
        ORDER BY product, fiscal_quarter, sales_market
    """

    try:
        rows = await _cached_query(sql, endpoint="/scenario-grid",
                                   product=effective_product,
                                   geo=effective_market, quarter=quarter)
    except Exception as exc:
        logger.warning("[forecast/scenario-grid] query failed: %s", exc)
        return _demo("scenarios", error=str(exc))

    scenarios = [{
        "product": r.get("product"),
        "sales_market": r.get("sales_market"),
        "fiscal_quarter": r.get("fiscal_quarter"),
        "conservative": _f(r.get("conservative")),
        "baseline": _f(r.get("baseline")),
        "stretch": _f(r.get("stretch")),
        "most_likely": _f(r.get("most_likely")),
        "weeks_in_quarter": int(_f(r.get("weeks_in_quarter"))),
        "actual_to_date": _f(r.get("actual_to_date"), default=None),
        "actual_weeks": int(_f(r.get("actual_weeks"))) if r.get("actual_weeks") else None,
        "fiscal_year": int(_f(r.get("fiscal_year"))),
        "source_model": r.get("source_model"),
    } for r in rows]

    return {"source": "live", "scenarios": scenarios}


@router.get("/sensitivity")
async def get_sensitivity_coefficients(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    live_mode:    bool          = Depends(_live_mode_dependency),
):
    """
    Per-driver elasticity coefficients computed from historical pipeline data.

    Powers the Pipeline Sensitivity Simulator with real data-driven relationships:
    - win_rate: % ARR change per 1 percentage-point change in win rate
    - deal_size: % ARR change per 1% change in avg deal size
    - coverage: % ARR change per 0.1x change in pipeline coverage
    - pipeline_volume: % ARR change per 1% change in opened deal count

    The UI sliders multiply these coefficients by the user's adjustment to compute
    a realistic scenario delta, grounded in historical correlation.
    """
    if not live_mode:
        return _demo("coefficients", error="Databricks unavailable")

    effective_product = _selected_product(product, product_line)
    effective_market = _normalize_market_value(sales_market)

    where_parts = ["run_date = (SELECT MAX(run_date) FROM " + SENSITIVITY_TABLE + ")"]
    if effective_product != "Total":
        where_parts.append(f"product = '{effective_product}'")
    if effective_market != "Total":
        where_parts.append(f"sales_market = '{effective_market}'")

    where_clause = " AND ".join(where_parts)

    sql = f"""
        SELECT
            product,
            sales_market,
            driver,
            driver_unit,
            ROUND(baseline_value, 2) AS baseline_value,
            ROUND(elasticity_pct, 4) AS elasticity_pct,
            ROUND(correlation, 3) AS correlation,
            CAST(n_observations AS INT) AS n_observations,
            description
        FROM {SENSITIVITY_TABLE}
        WHERE {where_clause}
        ORDER BY product, sales_market, driver
    """

    try:
        rows = await _cached_query(sql, endpoint="/sensitivity",
                                   product=effective_product,
                                   geo=effective_market)
    except Exception as exc:
        logger.warning("[forecast/sensitivity] query failed: %s", exc)
        return _demo("coefficients", error=str(exc))

    coefficients = [{
        "product": r.get("product"),
        "sales_market": r.get("sales_market"),
        "driver": r.get("driver"),
        "driver_unit": r.get("driver_unit"),
        "baseline_value": _f(r.get("baseline_value")),
        "elasticity_pct": _f(r.get("elasticity_pct")),
        "correlation": _f(r.get("correlation")),
        "n_observations": int(_f(r.get("n_observations"))),
        "description": r.get("description"),
    } for r in rows]

    return {"source": "live", "coefficients": coefficients}


@router.get("/model-scenarios")
async def get_model_scenarios(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    live_mode:    bool          = Depends(_live_mode_dependency),
):
    """
    Model-as-scenario mapping: each forecasting model classified as a scenario
    archetype (conservative / baseline / stretch) based on its bias vs ensemble.

    Powers the "Use model X as a scenario" dropdown and comparison charts.
    Returns % deviation from ensemble and accuracy metrics for context.
    """
    if not live_mode:
        return _demo("models", error="Databricks unavailable")

    effective_product = _selected_product(product, product_line)

    where_parts = ["run_date = (SELECT MAX(run_date) FROM " + MODEL_SCENARIOS_TABLE + ")"]
    if effective_product != "Total":
        where_parts.append(f"product = '{effective_product}'")

    where_clause = " AND ".join(where_parts)

    sql = f"""
        SELECT
            product,
            model,
            scenario_archetype,
            ROUND(pct_vs_ensemble, 2) AS pct_vs_ensemble,
            ROUND(fy_forecast_p50, 2) AS fy_forecast_p50,
            ROUND(wape, 2) AS wape,
            ROUND(cv_wape, 2) AS cv_wape,
            description
        FROM {MODEL_SCENARIOS_TABLE}
        WHERE {where_clause}
        ORDER BY product, pct_vs_ensemble
    """

    try:
        rows = await _cached_query(sql, endpoint="/model-scenarios",
                                   product=effective_product)
    except Exception as exc:
        logger.warning("[forecast/model-scenarios] query failed: %s", exc)
        return _demo("models", error=str(exc))

    models = [{
        "product": r.get("product"),
        "model": r.get("model"),
        "scenario_archetype": r.get("scenario_archetype"),
        "pct_vs_ensemble": _f(r.get("pct_vs_ensemble")),
        "fy_forecast_p50": _f(r.get("fy_forecast_p50")),
        "wape": _f(r.get("wape"), default=None),
        "cv_wape": _f(r.get("cv_wape"), default=None),
        "description": r.get("description"),
    } for r in rows]

    return {"source": "live", "models": models}


@router.get("/historical-scenarios")
async def get_historical_scenarios(
    product:      Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    sales_market: Optional[str] = Query(None),
    fiscal_year:  Optional[int] = Query(None),
    live_mode:    bool          = Depends(_live_mode_dependency),
):
    """
    Historical quarterly pipeline conditions alongside actual ARR outcomes.

    Powers the "When conditions were X, ARR was Y" what-if anchoring panel.
    Shows win_rate, deal_size, coverage, pipeline_volume for each quarter
    so leadership can compare current conditions to historical analogs.
    """
    if not live_mode:
        return _demo("history", error="Databricks unavailable")

    effective_product = _selected_product(product, product_line)
    effective_market = _normalize_market_value(sales_market)

    where_parts = ["run_date = (SELECT MAX(run_date) FROM " + HIST_SCENARIOS_TABLE + ")"]
    if effective_product != "Total":
        where_parts.append(f"product = '{effective_product}'")
    if effective_market != "Total":
        where_parts.append(f"sales_market = '{effective_market}'")
    if fiscal_year:
        where_parts.append(f"fiscal_year = {int(fiscal_year)}")

    where_clause = " AND ".join(where_parts)

    sql = f"""
        SELECT
            product,
            period,
            CAST(fiscal_year AS INT) AS fiscal_year,
            fiscal_quarter,
            sales_market,
            ROUND(CAST(actual_arr AS DOUBLE), 2) AS actual_arr,
            ROUND(CAST(pipeline_created AS DOUBLE), 2) AS pipeline_created,
            CAST(deals_won AS INT) AS deals_won,
            CAST(deals_opened AS INT) AS deals_opened,
            ROUND(CAST(avg_deal_size AS DOUBLE), 2) AS avg_deal_size,
            ROUND(win_rate_pct, 2) AS win_rate_pct,
            ROUND(CAST(coverage_x AS DOUBLE), 2) AS coverage_x,
            ROUND(qoq_growth_pct, 1) AS qoq_growth_pct
        FROM {HIST_SCENARIOS_TABLE}
        WHERE {where_clause}
        ORDER BY fiscal_year, fiscal_quarter, sales_market
    """

    try:
        rows = await _cached_query(sql, endpoint="/historical-scenarios",
                                   product=effective_product,
                                   geo=effective_market, year=fiscal_year)
    except Exception as exc:
        logger.warning("[forecast/historical-scenarios] query failed: %s", exc)
        return _demo("history", error=str(exc))

    history = [{
        "product": r.get("product"),
        "period": r.get("period"),
        "fiscal_year": int(_f(r.get("fiscal_year"))),
        "fiscal_quarter": r.get("fiscal_quarter"),
        "sales_market": r.get("sales_market"),
        "actual_arr": _f(r.get("actual_arr")),
        "pipeline_created": _f(r.get("pipeline_created")),
        "deals_won": int(_f(r.get("deals_won"))),
        "deals_opened": int(_f(r.get("deals_opened"))),
        "avg_deal_size": _f(r.get("avg_deal_size")),
        "win_rate_pct": _f(r.get("win_rate_pct")),
        "coverage_x": _f(r.get("coverage_x")),
        "qoq_growth_pct": _f(r.get("qoq_growth_pct"), default=None),
    } for r in rows]

    return {"source": "live", "history": history}
