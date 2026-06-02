"""Read-only forecast endpoints backed by precomputed Delta tables."""

import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter

from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/forecast", tags=["forecast"])

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA = os.getenv("DATABRICKS_SCHEMA", "mdl_sales_analytics")

FORECAST_OUTPUT_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`arr_forecast_output`"
FORECAST_INSIGHTS_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`arr_forecast_insights`"
FORECAST_LEADERBOARD_TABLE = f"`{CATALOG}`.`{SCHEMA}`.`arr_model_leaderboard`"


def _live_mode_available() -> bool:
    _on_databricks = bool(os.getenv("DATABRICKS_HOST"))
    _force_live = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
    return token_available() and (_on_databricks or _force_live)


SUPPORTED_MODELS = {
    "lightgbm": {
        "name": "LightGBM",
        "description": "Gradient boosting with AR + calendar features (34.9% MAPE)",
    },
    "prophet": {
        "name": "Prophet",
        "description": "Multiplicative seasonality with quarterly/monthly patterns (34.7% MAPE)",
    },
    "ensemble": {
        "name": "Ensemble (70/30)",
        "description": "70% LightGBM + 30% Prophet weighted blend (31.3% MAPE — best)",
    },
}


MODEL_LABEL_BY_KEY = {
    "lightgbm": "LightGBM",
    "prophet": "Prophet",
    "ensemble": "Ensemble (70/30)",
}


def _normalize_model_label(model: str) -> str:
    m = str(model or "").strip().lower()
    if m in {"lightgbm", "light_gbm"}:
        return "LightGBM"
    if m == "prophet":
        return "Prophet"
    if m in {"ensemble", "ensemble (70/30)", "ensemble_70_30"}:
        return "Ensemble (70/30)"
    if m == "actual":
        return "actual"
    return str(model or "")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list):
            return [str(v) for v in decoded]
    except json.JSONDecodeError:
        pass
    return [s.strip() for s in text.split(";") if s.strip()]


def _table_readiness(table_fqn: str) -> dict:
    out = {
        "table": str(table_fqn).replace("`", "").split(".")[-1],
        "fqn": table_fqn,
        "exists": False,
        "ready": False,
        "row_count": 0,
        "latest_run_date": None,
        "run_date_column": "run_date",
        "error": None,
    }

    try:
        sample_rows = execute_query(f"SELECT * FROM {table_fqn} LIMIT 1")
        out["exists"] = True

        count_rows = execute_query(f"SELECT COUNT(*) AS row_count FROM {table_fqn}")
        if count_rows:
            row = count_rows[0] or {}
            row_count = row.get("row_count")
            if row_count is None and row:
                row_count = next(iter(row.values()))
            out["row_count"] = int(_to_float(row_count, 0))

        latest_rows = execute_query(
            f"SELECT CAST(run_date AS STRING) AS latest_run_date "
            f"FROM {table_fqn} WHERE run_date IS NOT NULL ORDER BY run_date DESC LIMIT 1"
        )
        if latest_rows:
            out["latest_run_date"] = latest_rows[0].get("latest_run_date")

        out["ready"] = bool(out["exists"] and out["row_count"] > 0 and out["latest_run_date"])
        if out["exists"] and out["row_count"] == 0:
            out["error"] = "table exists but has no rows yet"
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


@router.get("/models")
async def list_models():
    return {"models": SUPPORTED_MODELS}


@router.get("/health/tables")
async def forecast_tables_health():
    table_names = [FORECAST_OUTPUT_TABLE, FORECAST_INSIGHTS_TABLE, FORECAST_LEADERBOARD_TABLE]

    if not _live_mode_available():
        return {
            "ready": False,
            "live_mode_available": False,
            "source": "demo",
            "error": "Databricks token/host not available in current runtime",
            "tables": [
                {
                    "table": t,
                    "fqn": t,
                    "exists": False,
                    "ready": False,
                    "row_count": 0,
                    "latest_run_date": None,
                    "run_date_column": "run_date",
                    "error": "live mode unavailable",
                }
                for t in table_names
            ],
        }

    checks = await asyncio.gather(*[asyncio.to_thread(_table_readiness, t) for t in table_names])
    return {
        "ready": all(c.get("ready") for c in checks),
        "live_mode_available": True,
        "source": "live",
        "tables": checks,
    }


@router.get("/arr")
async def get_arr_forecast():
    if not _live_mode_available():
        return {
            "source": "demo",
            "data": {
                "actual": {"actuals": [], "forecast": []},
                "LightGBM": {"actuals": [], "forecast": []},
                "Prophet": {"actuals": [], "forecast": []},
                "Ensemble (70/30)": {"actuals": [], "forecast": []},
            },
            "live_mode_available": False,
            "error": "Databricks token/host not available in current runtime",
        }

    rows = await asyncio.to_thread(
        execute_query,
        (
            "SELECT ds, model, forecast_type, yhat, yhat_lower, yhat_upper "
            f"FROM {FORECAST_OUTPUT_TABLE} "
            "ORDER BY ds"
        ),
    )

    grouped = {
        "actual": {"actuals": [], "forecast": []},
        "LightGBM": {"actuals": [], "forecast": []},
        "Prophet": {"actuals": [], "forecast": []},
        "Ensemble (70/30)": {"actuals": [], "forecast": []},
    }

    for row in rows:
        date_str = str(row.get("ds") or "")[:10]
        if not date_str:
            continue

        model_label = _normalize_model_label(row.get("model"))
        forecast_type = str(row.get("forecast_type") or "").strip().lower()

        point = {
            "date": date_str,
            "value": _to_float(row.get("yhat"), 0.0),
            "lower": _to_float(row.get("yhat_lower"), _to_float(row.get("yhat"), 0.0)),
            "upper": _to_float(row.get("yhat_upper"), _to_float(row.get("yhat"), 0.0)),
        }

        if model_label == "actual" or forecast_type == "actual":
            grouped["actual"]["actuals"].append(point)
            continue

        if model_label not in grouped:
            continue

        if forecast_type == "actual":
            grouped[model_label]["actuals"].append(point)
        else:
            grouped[model_label]["forecast"].append(point)

    return {
        "source": "live",
        "data": grouped,
    }


@router.get("/insights")
async def get_forecast_insights():
    if not _live_mode_available():
        return {
            "source": "demo",
            "data": None,
            "live_mode_available": False,
            "error": "Databricks token/host not available in current runtime",
        }

    rows = await asyncio.to_thread(
        execute_query,
        (
            "SELECT * "
            f"FROM {FORECAST_INSIGHTS_TABLE} "
            "ORDER BY run_date DESC "
            "LIMIT 1"
        ),
    )

    if not rows:
        return {"source": "live", "data": None}

    row = rows[0]
    confidence = row.get("model_confidence")
    confidence_val = int(round(_to_float(confidence, 0)))
    if 0 <= _to_float(confidence, 0) <= 1:
        confidence_val = int(round(_to_float(confidence, 0) * 100))

    payload = {
        "run_date": row.get("run_date"),
        "momentum": row.get("momentum") or row.get("trend_status") or "STABLE",
        "risk_level": row.get("risk_level") or "MODERATE RISK",
        "narrative": row.get("narrative") or row.get("description") or "",
        "model_confidence": confidence_val,
        "upside": row.get("upside") or "",
        "downside": row.get("downside") or "",
        "best_model": row.get("best_model") or "Ensemble (70/30)",
        "best_mape": _to_float(row.get("best_mape"), 0.0),
        "monthly_best_model": row.get("monthly_best_model"),
        "monthly_best_mape": _to_float(row.get("monthly_best_mape"), 0.0),
        "ensemble_mape": _to_float(row.get("ensemble_mape"), 0.0),
        "forecast_most_likely": _to_float(row.get("forecast_most_likely"), 0.0),
        "forecast_low": _to_float(row.get("forecast_low"), 0.0),
        "forecast_high": _to_float(row.get("forecast_high"), 0.0),
        "key_drivers": _parse_json_array(row.get("key_drivers")),
        "executive_actions": _parse_json_array(row.get("executive_actions")),
        "downside_risks": _parse_json_array(row.get("downside_risks")),
        "upside_opportunities": _parse_json_array(row.get("upside_opportunities")),
    }

    return {"source": "live", "data": payload}


@router.get("/leaderboard")
async def get_model_leaderboard():
    if not _live_mode_available():
        return {
            "source": "demo",
            "data": [],
            "live_mode_available": False,
            "error": "Databricks token/host not available in current runtime",
        }

    rows = await asyncio.to_thread(
        execute_query,
        (
            "SELECT model, mape, granularity, type "
            f"FROM {FORECAST_LEADERBOARD_TABLE} "
            "ORDER BY mape ASC"
        ),
    )

    data = [
        {
            "model": _normalize_model_label(r.get("model")),
            "mape": _to_float(r.get("mape"), 0.0),
            "granularity": r.get("granularity") or "weekly",
            "type": r.get("type") or "",
        }
        for r in rows
    ]
    return {"source": "live", "data": data}


@router.get("/run")
async def run_forecast_model():
    return {
        "deprecated": True,
        "message": "Use /api/forecast/arr for pre-computed forecasts",
    }
