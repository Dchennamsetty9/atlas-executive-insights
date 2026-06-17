"""Read-only forecast endpoints backed by precomputed Delta tables.

Schema (arr_forecast_ensemble):
  run_timestamp, product, forecast_week_start, forecast_step, horizon_weeks,
  arr_ensemble, arr_ets, arr_prophet, arr_lightgbm, arr_chronos,
  mape_ets, mape_prophet, mape_lightgbm, mape_chronos, ensemble_weights

Schema (arr_forecast_leaderboard):
  product, ETS, Prophet, LightGBM, Chronos, best_model, best_mape
"""

import asyncio
import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Query

from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/forecast", tags=["forecast"])

# ── Catalog / table config ────────────────────────────────────────────────────
GOLD_CATALOG = os.getenv("FORECAST_CATALOG", "datagroup_mdl")
GOLD_SCHEMA  = os.getenv("FORECAST_SCHEMA",  "mdl_sales_analytics")

ENSEMBLE_TABLE   = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`arr_forecast_ensemble`"
LEADERBOARD_TABLE = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`arr_forecast_leaderboard`"

# Source table for fetching recent actuals
ACTUALS_CATALOG = os.getenv("ACTUALS_CATALOG", "datalake_transform")
ACTUALS_TABLE   = f"`{ACTUALS_CATALOG}`.`cds_sfdc_opp_products_latest`"

CHANNEL_EXCLUSIONS = ("'Care'", "'Sales Other'")
PURCHASE_TYPE      = "Growth"

# Model column → display label
MODEL_COL_MAP = {
    "arr_ets":      "ETS",
    "arr_prophet":  "Prophet",
    "arr_lightgbm": "LightGBM",
    "arr_chronos":  "Chronos",
    "arr_ensemble": "Ensemble",
}

SUPPORTED_MODELS = {
    "ets":      {"name": "ETS",      "description": "Exponential Smoothing (statsmodels Holt-Winters)"},
    "prophet":  {"name": "Prophet",  "description": "Facebook Prophet with quarterly seasonality"},
    "lightgbm": {"name": "LightGBM", "description": "Gradient boosting with lag + rolling features"},
    "chronos":  {"name": "Chronos",  "description": "Amazon Chronos-T5-Small (zero-shot foundation model)"},
    "ensemble": {"name": "Ensemble", "description": "MAPE-weighted blend of all available models"},
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _live_mode_available() -> bool:
    _on_databricks = bool(os.getenv("DATABRICKS_HOST"))
    _force_live    = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
    return token_available() and (_on_databricks or _force_live)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _empty_response(reason: str) -> dict:
    """Return a consistent empty response when live mode is unavailable."""
    return {
        "source": "demo",
        "live_mode_available": False,
        "error": reason,
        "data": {
            "actual":    {"actuals": [], "forecast": []},
            "ETS":       {"actuals": [], "forecast": []},
            "Prophet":   {"actuals": [], "forecast": []},
            "LightGBM":  {"actuals": [], "forecast": []},
            "Chronos":   {"actuals": [], "forecast": []},
            "Ensemble":  {"actuals": [], "forecast": []},
        },
    }


# ── Routes ────────────────────────────────────────────────────────────────────
@router.get("/models")
async def list_models():
    return {"models": SUPPORTED_MODELS}


@router.get("/arr")
async def get_arr_forecast(product: Optional[str] = Query(None, description="Filter by product name")):
    """
    Return pre-computed ARR forecasts from Delta, shaped for the ForecastChart.

    Response shape:
    {
      "source": "live" | "demo",
      "products": [...],          // all available products
      "data": {
        "actual":   {"actuals": [{date, value}], "forecast": []},
        "ETS":      {"actuals": [], "forecast": [{date, value, lower, upper}]},
        "Prophet":  ...,
        "LightGBM": ...,
        "Chronos":  ...,
        "Ensemble": ...,
      }
    }
    """
    if not _live_mode_available():
        return _empty_response("Databricks token/host not available in current runtime")

    # ── 1. Fetch forecast rows (latest run only) ──────────────────────────────
    product_filter = ""
    if product:
        safe = product.replace("'", "''")
        product_filter = f" AND product = '{safe}'"

    forecast_sql = f"""
        SELECT
            forecast_week_start,
            product,
            arr_ets,
            arr_prophet,
            arr_lightgbm,
            arr_chronos,
            arr_ensemble
        FROM {ENSEMBLE_TABLE}
        WHERE run_timestamp = (SELECT MAX(run_timestamp) FROM {ENSEMBLE_TABLE})
        {product_filter}
        ORDER BY forecast_week_start
    """

    forecast_rows = await asyncio.to_thread(execute_query, forecast_sql)

    # Aggregate across products (or single product if filtered)
    fc_by_week: dict[str, dict[str, float]] = {}
    products_seen: set[str] = set()

    for row in forecast_rows:
        date_str = str(row.get("forecast_week_start") or "")[:10]
        if not date_str:
            continue
        products_seen.add(str(row.get("product") or ""))
        if date_str not in fc_by_week:
            fc_by_week[date_str] = {col: 0.0 for col in MODEL_COL_MAP}
        for col in MODEL_COL_MAP:
            fc_by_week[date_str][col] += _to_float(row.get(col), 0.0)

    # ── 2. Fetch recent actuals from source table ─────────────────────────────
    excl = ", ".join(CHANNEL_EXCLUSIONS)
    product_actual_filter = ""
    if products_seen:
        # use the product names seen in forecast table for consistent actuals
        prod_list = ", ".join(f"'{p.replace(chr(39), chr(39)+chr(39))}'" for p in products_seen)
        product_actual_filter = f"AND product_genus IN ({prod_list})"

    actuals_sql = f"""
        SELECT
            date_trunc('week', close_date) AS week_start,
            SUM(amount_towards_plan)       AS arr
        FROM {ACTUALS_TABLE}
        WHERE sales_channel NOT IN ({excl})
          AND purchase_type_rollup = '{PURCHASE_TYPE}'
          AND is_won   = 'True'
          AND is_closed = 'True'
          AND close_date >= add_months(current_date(), -18)
          {product_actual_filter}
        GROUP BY date_trunc('week', close_date)
        ORDER BY week_start
    """

    try:
        actual_rows = await asyncio.to_thread(execute_query, actuals_sql)
    except Exception:
        actual_rows = []

    # ── 3. Build response structure ───────────────────────────────────────────
    data: dict[str, dict] = {
        "actual":   {"actuals": [], "forecast": []},
        "ETS":      {"actuals": [], "forecast": []},
        "Prophet":  {"actuals": [], "forecast": []},
        "LightGBM": {"actuals": [], "forecast": []},
        "Chronos":  {"actuals": [], "forecast": []},
        "Ensemble": {"actuals": [], "forecast": []},
    }

    for row in actual_rows:
        date_str = str(row.get("week_start") or "")[:10]
        if date_str:
            data["actual"]["actuals"].append({
                "date":  date_str,
                "value": _to_float(row.get("arr"), 0.0),
            })

    for date_str, cols in sorted(fc_by_week.items()):
        # Confidence band: ±15% of ensemble value (model-level uncertainty)
        ensemble_val = cols["arr_ensemble"]
        band = ensemble_val * 0.15

        for col, label in MODEL_COL_MAP.items():
            val = cols[col]
            if val == 0.0:
                continue  # model not available for this product
            data[label]["forecast"].append({
                "date":  date_str,
                "value": round(val, 2),
                "lower": round(max(0, val - band), 2),
                "upper": round(val + band, 2),
            })

    return {
        "source": "live",
        "products": sorted(products_seen),
        "data": data,
    }


@router.get("/leaderboard")
async def get_model_leaderboard():
    """
    Return MAPE leaderboard from arr_forecast_leaderboard Delta table.

    Response shape:
    {"source": "live", "data": [{model, mape, product, best_model, best_mape}]}
    """
    if not _live_mode_available():
        return {
            "source": "demo",
            "data": [],
            "live_mode_available": False,
            "error": "Databricks token/host not available in current runtime",
        }

    rows = await asyncio.to_thread(
        execute_query,
        f"""
        SELECT
            product,
            `ETS`      AS mape_ets,
            `Prophet`  AS mape_prophet,
            `LightGBM` AS mape_lgb,
            `Chronos`  AS mape_chronos,
            best_model,
            best_mape
        FROM {LEADERBOARD_TABLE}
        ORDER BY product
        """,
    )

    data = []
    for row in rows:
        product    = str(row.get("product") or "")
        best_model = str(row.get("best_model") or "")
        best_mape  = _to_float(row.get("best_mape"), 0.0)
        for col, label in [("mape_ets", "ETS"), ("mape_prophet", "Prophet"),
                            ("mape_lgb", "LightGBM"), ("mape_chronos", "Chronos")]:
            m = _to_float(row.get(col), None)
            if m is not None and m > 0:
                data.append({
                    "model":      label,
                    "product":    product,
                    "mape":       round(m, 2),
                    "best_model": best_model,
                    "best_mape":  round(best_mape, 2),
                })

    # Sort: best MAPE first
    data.sort(key=lambda r: r["mape"])
    return {"source": "live", "data": data}


@router.get("/health/tables")
async def forecast_tables_health():
    tables = [ENSEMBLE_TABLE, LEADERBOARD_TABLE]
    if not _live_mode_available():
        return {
            "ready": False,
            "live_mode_available": False,
            "source": "demo",
            "error": "Databricks token/host not available in current runtime",
            "tables": [{"table": t, "exists": False, "ready": False} for t in tables],
        }

    async def _check(tbl: str) -> dict:
        try:
            rows = await asyncio.to_thread(execute_query, f"SELECT COUNT(*) AS n FROM {tbl}")
            n = _to_float((rows[0] or {}).get("n", 0), 0)
            return {"table": tbl, "exists": True, "ready": n > 0, "row_count": int(n)}
        except Exception as exc:
            return {"table": tbl, "exists": False, "ready": False, "error": str(exc)}

    checks = await asyncio.gather(*[_check(t) for t in tables])
    return {
        "ready": all(c.get("ready") for c in checks),
        "live_mode_available": True,
        "source": "live",
        "tables": checks,
    }


@router.get("/run")
async def run_forecast_model():
    return {
        "deprecated": True,
        "message": "Forecasts are pre-computed by the weekly Databricks Job. Use /api/forecast/arr.",
    }
