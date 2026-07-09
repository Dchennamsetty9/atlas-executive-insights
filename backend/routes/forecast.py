"""
routes/forecast.py
Prophet-first, table-driven forecast endpoints for Atlas Executive Insights.

DEPRECATED (V1 path):
    /api/forecast/arr and /api/forecast/leaderboard read `forecast_prophet` which
    has no scheduled writer. The live UI now reads from arr_forecast_v2 via
    forecast_v2.py (/api/forecast/v2/*). This file is kept for the
    /api/forecast/intelligence endpoint (AI Insights tab) only.
    TODO: migrate intelligence to v2 tables and remove this file.

Primary source table:
    datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query

from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/forecast", tags=["forecast"])
logger = logging.getLogger(__name__)

GOLD_CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
GOLD_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "mdl_sales_analytics")
FORECAST_OUTPUT_TABLE = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`forecast_prophet`"
FORECAST_INSIGHTS_TABLE = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`arr_forecast_v2`"
FORECAST_LEADERBOARD_TABLE = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`arr_forecast_v2_leaderboard`"
AI_INSIGHTS_JSON_PATH = "/Volumes/datagroup_mdl/mdl_sales_analytics/forecast_assets/ai_insights_latest.json"


def _live_mode_available() -> bool:
    force_live = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
    return force_live or token_available()


def _f(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _q(value: Optional[str]) -> str:
    return (value or "").replace("'", "''")


def _run_date_filter(table_name: str) -> str:
    return f"run_date = (SELECT MAX(run_date) FROM {table_name})"


def _product_clause(product: Optional[str], product_line: Optional[str]) -> str:
    selected = product_line if product_line not in (None, "", "All") else product
    if selected in (None, "", "All"):
        return ""
    escaped = _q(selected)
    return (
        f"AND COALESCE(CAST(product_line AS STRING), CAST(product AS STRING), 'All') = '{escaped}'"
    )


def _insights_product_clause(product: Optional[str], product_line: Optional[str]) -> str:
    selected = product_line if product_line not in (None, "", "All") else product
    if selected in (None, "", "All"):
        return ""
    escaped = _q(selected)
    return f"AND COALESCE(CAST(product AS STRING), 'All') = '{escaped}'"


def _base_forecast_sql(product: Optional[str], product_line: Optional[str]) -> str:
    return f"""
        SELECT
            CAST(ds AS STRING) AS date,
            SUM(COALESCE(CAST(Actuals AS DOUBLE), CAST(actuals AS DOUBLE), 0)) AS arr_actual,
            SUM(COALESCE(CAST(Most_Likely AS DOUBLE), CAST(most_likely AS DOUBLE), CAST(arr_prophet AS DOUBLE), CAST(yhat AS DOUBLE), 0)) AS arr_likely,
            SUM(COALESCE(CAST(Worst_Case AS DOUBLE), CAST(worst_case AS DOUBLE), CAST(yhat_lower AS DOUBLE), 0)) AS arr_worst,
            SUM(COALESCE(CAST(Best_Case AS DOUBLE), CAST(best_case AS DOUBLE), CAST(yhat_upper AS DOUBLE), 0)) AS arr_best
        FROM {FORECAST_OUTPUT_TABLE}
                WHERE 1=1
                    {_product_clause(product, product_line)}
        GROUP BY ds
        ORDER BY ds
    """


def _products_sql() -> str:
    return f"""
        SELECT DISTINCT COALESCE(CAST(product_line AS STRING), CAST(product AS STRING)) AS product
        FROM {FORECAST_OUTPUT_TABLE}
                WHERE 1=1
          AND COALESCE(CAST(product_line AS STRING), CAST(product AS STRING)) IS NOT NULL
          AND LOWER(COALESCE(CAST(product_line AS STRING), CAST(product AS STRING))) NOT IN ('all', 'total')
        ORDER BY product
    """


def _demo_arr_payload() -> dict:
    actuals = [
        {"date": "2026-01-05", "value": 4100000},
        {"date": "2026-01-12", "value": 4280000},
        {"date": "2026-01-19", "value": 4350000},
        {"date": "2026-01-26", "value": 4420000},
        {"date": "2026-02-02", "value": 4510000},
    ]
    forecast = [
        {"date": "2026-02-09", "value": 4620000, "lower": 4310000, "upper": 4930000},
        {"date": "2026-02-16", "value": 4700000, "lower": 4360000, "upper": 5010000},
        {"date": "2026-02-23", "value": 4790000, "lower": 4430000, "upper": 5140000},
        {"date": "2026-03-02", "value": 4860000, "lower": 4480000, "upper": 5210000},
    ]
    return {
        "source": "demo",
        "products": ["UCC", "ITSG"],
        "data": {
            "actual": {"actuals": actuals},
            "Prophet": {"forecast": forecast, "mape": 19.4},
            "Ensemble": {"forecast": []},
            "LightGBM": {"forecast": []},
            "ETS": {"forecast": []},
            "Chronos": {"forecast": []},
        },
    }


def _demo_leaderboard() -> dict:
    return {
        "source": "demo",
        "data": [
            {"model": "Prophet", "product": "All", "mape": 19.4},
            {"model": "Prophet", "product": "UCC", "mape": 18.9},
            {"model": "Prophet", "product": "ITSG", "mape": 20.1},
        ],
    }


def _trend_from_actuals(actuals: list[dict]) -> tuple[str, float]:
    values = [_f(r.get("value")) for r in actuals if _f(r.get("value")) > 0]
    if len(values) < 2:
        return "stable", 0.0

    growth = (values[-1] - values[0]) / max(values[0], 1)
    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / max(len(values), 1)
    volatility = (variance ** 0.5) / max(mean_val, 1)

    if volatility > 0.15:
        return "volatile", round(growth, 4)
    if growth > 0.03:
        return "accelerating", round(growth, 4)
    if growth < -0.02:
        return "decelerating", round(growth, 4)
    return "stable", round(growth, 4)


def _risk_from_band(most_likely: float, best_case: float, worst_case: float) -> tuple[str, float]:
    if most_likely <= 0:
        return "moderate", 0.85

    relative_width = max(0.0, (best_case - worst_case) / most_likely)
    confidence = max(0.5, min(0.99, 1.0 - (relative_width / 2.2)))

    if relative_width < 0.08:
        return "low", round(confidence, 2)
    if relative_width < 0.18:
        return "moderate", round(confidence, 2)
    return "high", round(confidence, 2)


def _insight_defaults() -> dict:
    return {
        "key_drivers": [
            "V2 ensemble blends ETS, Prophet, LightGBM, and Chronos signals",
            "Current run uses latest Databricks refresh for executive planning",
            "Recent actuals anchor near-term forecast shape",
        ],
        "executive_actions": [
            "Prioritize high-confidence opportunities in the next 30 days",
            "Review top forecasted deals weekly with sales leadership",
            "Protect conversion in late stages to defend most likely case",
        ],
        "downside_risks": [
            "Large-deal slippage can pull results toward the worst-case band",
            "Segment volatility may widen confidence intervals quarter-to-date",
            "Pipeline quality deterioration can reduce close predictability",
        ],
        "upside_opportunities": [
            "UCC and ITSG cross-sell expansion can add upside above baseline",
            "Strong conversion in committed deals can close the gap to best case",
            "Focused acceleration in high-performing markets can lift ARR outcomes",
        ],
    }


def _selected_product(product: Optional[str], product_line: Optional[str]) -> Optional[str]:
    selected = product_line if product_line not in (None, "", "All") else product
    if selected in (None, "", "All"):
        return None
    return str(selected)


def _dict_get_case_insensitive(obj: dict, key: str):
    if key in obj:
        return obj[key]
    key_l = key.lower()
    for k, v in obj.items():
        if str(k).lower() == key_l:
            return v
    return None


def _pick_asset_segment(asset: dict, selected_product: Optional[str]) -> dict:
    """Pick the best product-scoped block from asset JSON if available."""
    if not selected_product:
        if isinstance(asset.get("data"), dict):
            return asset["data"]
        return asset

    product = selected_product.strip()
    product_l = product.lower()

    for container_key in ("by_product", "products", "product_insights", "segments"):
        container = asset.get(container_key)
        if isinstance(container, dict):
            picked = _dict_get_case_insensitive(container, product)
            if isinstance(picked, dict):
                return picked
        if isinstance(container, list):
            for row in container:
                if not isinstance(row, dict):
                    continue
                row_product = str(
                    row.get("product")
                    or row.get("product_line")
                    or row.get("name")
                    or ""
                ).strip().lower()
                if row_product == product_l:
                    return row

    if isinstance(asset.get("data"), dict):
        return asset["data"]
    return asset


def _load_ai_insights_from_uc_asset(product: Optional[str], product_line: Optional[str]) -> Optional[dict]:
    """
    Load AI insights from the UC Volume JSON asset and normalise to frontend shape.
    Returns None when file is not available or payload is invalid.
    """
    path = Path(AI_INSIGHTS_JSON_PATH)
    if not path.exists() or not path.is_file():
        return None

    try:
        with path.open("r", encoding="utf-8") as fp:
            asset = json.load(fp)
    except Exception as exc:
        logger.warning("[forecast/intelligence] failed to read asset %s: %s", AI_INSIGHTS_JSON_PATH, exc)
        return None

    if not isinstance(asset, dict):
        return None

    selected = _selected_product(product, product_line)
    scoped = _pick_asset_segment(asset, selected)
    if not isinstance(scoped, dict):
        return None

    defaults = _insight_defaults()

    payload = {
        "run_date": scoped.get("run_date") or asset.get("run_date") or asset.get("generated_at") or "—",
        "momentum": scoped.get("momentum") or scoped.get("trend_status") or "STABLE",
        "risk_level": scoped.get("risk_level") or "MODERATE RISK",
        "model_confidence": scoped.get("model_confidence") or scoped.get("confidence") or 72,
        "best_model": scoped.get("best_model") or "Prophet",
        "best_mape": scoped.get("best_mape") or scoped.get("mape") or 19.4,
        "ensemble_mape": scoped.get("ensemble_mape") or scoped.get("best_mape") or scoped.get("mape") or 19.4,
        "forecast_most_likely": scoped.get("forecast_most_likely") or scoped.get("most_likely") or 0,
        "forecast_low": scoped.get("forecast_low") or scoped.get("worst_case") or 0,
        "forecast_high": scoped.get("forecast_high") or scoped.get("best_case") or 0,
        "upside": scoped.get("upside") or scoped.get("upside_dollar"),
        "downside": scoped.get("downside") or scoped.get("downside_dollar"),
        "narrative": scoped.get("narrative") or scoped.get("summary") or "",
        "key_drivers": scoped.get("key_drivers") or defaults["key_drivers"],
        "executive_actions": scoped.get("executive_actions") or defaults["executive_actions"],
        "downside_risks": scoped.get("downside_risks") or defaults["downside_risks"],
        "upside_opportunities": scoped.get("upside_opportunities") or defaults["upside_opportunities"],
    }

    return {"source": "live_asset", "data": payload}


def _demo_insights(metric: str = "won_pipeline") -> dict:
    """
    Demo fallback — always returns {source, data} shape matching ForecastIntelligence.jsx.
    """
    defaults = _insight_defaults()
    data_payload = {
        "run_date":             "—",
        "momentum":             "STABLE",
        "risk_level":           "MODERATE RISK",
        "model_confidence":     72,
        "best_model":           "Prophet",
        "best_mape":            19.4,
        "ensemble_mape":        19.4,
        "forecast_most_likely": 17_200_000,
        "forecast_low":         14_620_000,
        "forecast_high":        19_780_000,
        "upside":               "+$2.6M",
        "downside":             "-$2.6M",
        "narrative": (
            "Prophet projects ~$17.2M in Growth ARR over the next 13 weeks "
            "(UCC + ITSG). Connect to Databricks to see live figures."
        ),
        **defaults,
    }
    return {"source": "demo", "data": data_payload}


@router.get("/arr")
async def get_arr_forecast(
    product: Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
):
    """
    Return pre-computed ARR forecasts from forecast_prophet, shaped for ForecastChart.
    """
    if not _live_mode_available():
        return _demo_arr_payload()

    try:
        rows = execute_query(_base_forecast_sql(product, product_line))
        product_rows = execute_query(_products_sql())

        actuals = []
        forecast = []
        for row in rows:
            date_key = str(row.get("date") or "")[:10]
            if not date_key:
                continue

            arr_actual = _f(row.get("arr_actual"))
            arr_likely = _f(row.get("arr_likely"))
            arr_worst = _f(row.get("arr_worst"), arr_likely)
            arr_best = _f(row.get("arr_best"), arr_likely)

            if arr_actual > 0:
                actuals.append({"date": date_key, "value": round(arr_actual, 2)})

            if arr_likely > 0:
                forecast.append(
                    {
                        "date": date_key,
                        "value": round(arr_likely, 2),
                        "lower": round(arr_worst, 2),
                        "upper": round(arr_best, 2),
                    }
                )

        products = [str(r.get("product") or "") for r in product_rows if r.get("product")]

        return {
            "source": "live",
            "products": products,
            "data": {
                "actual": {"actuals": actuals},
                "Prophet": {"forecast": forecast, "mape": 19.4},
                "Ensemble": {"forecast": []},
                "LightGBM": {"forecast": []},
                "ETS": {"forecast": []},
                "Chronos": {"forecast": []},
            },
        }
    except Exception:
        return _demo_arr_payload()


@router.get("/leaderboard")
async def get_leaderboard():
    """
    Return model leaderboard for UI badges. Prophet is default and primary.
    """
    if not _live_mode_available():
        return _demo_leaderboard()

    sql = f"""
        SELECT
            COALESCE(CAST(product_line AS STRING), CAST(product AS STRING), 'All') AS product,
            COALESCE(CAST(mape_prophet AS DOUBLE), CAST(best_mape AS DOUBLE), CAST(mape AS DOUBLE), 19.4) AS mape
        FROM {FORECAST_LEADERBOARD_TABLE}
        WHERE 1=1
        ORDER BY product
    """

    try:
        rows = execute_query(sql)
        data = [
            {
                "model": "Prophet",
                "product": str(r.get("product") or "All"),
                "mape": round(_f(r.get("mape"), 19.4), 1),
            }
            for r in rows
        ]

        if not data:
            data = [{"model": "Prophet", "product": "All", "mape": 19.4}]

        return {"source": "live", "data": data}
    except Exception:
        return _demo_leaderboard()


def _normalize_model_name(model: str) -> str:
    clean = (model or "").strip().lower().replace(" ", "_")
    aliases = {
        "": "prophet",
        "auto": "prophet",
        "ensemble": "prophet",
        "lightgbm": "prophet",
        "ets": "prophet",
        "chronos": "prophet",
    }
    return aliases.get(clean, clean)


def _fallback_intelligence_payload(
    *,
    product: Optional[str],
    product_line: Optional[str],
    reason: str,
) -> dict:
    """Build a non-empty AI insights payload from live forecast tables when JSON is unavailable."""
    if not _live_mode_available():
        return {
            "source": "fallback",
            "error": reason,
            "momentum": "STABLE",
            "risk_level": "MODERATE",
            "model_confidence": 65,
            "best_model": "Prophet",
            "best_mape": 0,
            "forecast_most_likely": 0,
            "forecast_low": 0,
            "forecast_high": 0,
            "narrative": "AI insights JSON is unavailable and live Databricks access is currently not configured.",
            "key_drivers": [
                "Run Panel Writer notebook to publish ai_insights_latest.json to UC Volume.",
                "Ensure Databricks auth is available to backend for table-derived fallback.",
                "Retry AI Insights refresh after artifact and auth are healthy.",
            ],
            "downside_risks": [
                "Missing insights artifact prevents model consensus and CI narrative generation.",
                "Executive action cards are degraded until JSON output is restored.",
                "Decision confidence remains limited without precomputed intelligence context.",
            ],
            "upside_opportunities": [
                "Once JSON artifact is restored, cards will show quantified upside/downside scenarios.",
                "Fallback queries can still populate baseline ARR bounds from live tables.",
                "Automating notebook schedule health checks will prevent future gaps.",
            ],
            "executive_actions": [
                "Run job3_forecast_scoring and Panel Writer to regenerate ai_insights_latest.json.",
                "Verify UC Volume path permissions for backend app identity.",
                "Set alert when the insights artifact is older than 24 hours.",
            ],
        }

    clause = _insights_product_clause(product, product_line)
    try:
        summary_rows = execute_query(
            f"""
            SELECT
                MAX(CAST(run_date AS STRING)) AS run_date,
                SUM(COALESCE(CAST(Most_Likely AS DOUBLE), 0)) AS most_likely,
                SUM(COALESCE(CAST(Worst_Case AS DOUBLE), 0)) AS worst_case,
                SUM(COALESCE(CAST(Best_Case AS DOUBLE), 0)) AS best_case
            FROM {FORECAST_INSIGHTS_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {FORECAST_INSIGHTS_TABLE})
              AND forecast_type IN ('rolling', 'roy')
              {clause}
            """
        )
        top_products = execute_query(
            f"""
            SELECT COALESCE(CAST(product AS STRING), 'Unknown') AS product,
                   SUM(COALESCE(CAST(Most_Likely AS DOUBLE), 0)) AS likely
            FROM {FORECAST_INSIGHTS_TABLE}
            WHERE run_date = (SELECT MAX(run_date) FROM {FORECAST_INSIGHTS_TABLE})
              AND forecast_type IN ('rolling', 'roy')
              {clause}
            GROUP BY COALESCE(CAST(product AS STRING), 'Unknown')
            ORDER BY likely DESC
            LIMIT 3
            """
        )

        s = summary_rows[0] if summary_rows else {}
        likely = _f(s.get("most_likely"))
        worst = _f(s.get("worst_case"), likely)
        best = _f(s.get("best_case"), likely)
        spread_pct = ((best - worst) / likely * 100.0) if likely > 0 else 0.0

        risk_level = "LOW" if spread_pct < 10 else "MODERATE" if spread_pct < 20 else "HIGH"
        momentum = "STABLE"
        conf = max(45, min(92, int(round(100 - min(40, spread_pct * 1.4)))))
        run_date = str(s.get("run_date") or datetime.utcnow().strftime("%Y-%m-%d"))[:10]

        top_lines = [str(r.get("product") or "Unknown") for r in top_products]
        top_text = ", ".join(top_lines) if top_lines else "Total mix"

        return {
            "source": "live_query_fallback",
            "error": reason,
            "run_date": run_date,
            "momentum": momentum,
            "risk_level": risk_level,
            "model_confidence": conf,
            "best_model": "Prophet",
            "best_mape": 0,
            "forecast_most_likely": round(likely, 0),
            "forecast_low": round(worst, 0),
            "forecast_high": round(best, 0),
            "narrative": (
                f"Insights JSON is unavailable ({reason}). Showing live fallback from arr_forecast_v2: "
                f"most likely ${likely/1_000_000:.1f}M, range ${worst/1_000_000:.1f}M-${best/1_000_000:.1f}M."
            ),
            "key_drivers": [
                f"Top product contribution this run: {top_text}.",
                f"Current planning baseline is ${likely/1_000_000:.1f}M ARR.",
                "Fallback values are table-derived and refresh with latest run_date.",
            ],
            "downside_risks": [
                f"Scenario downside vs likely: ${(likely - worst)/1_000_000:.1f}M.",
                f"Band width is {spread_pct:.1f}% of most-likely, indicating {risk_level.lower()} risk.",
                "Missing JSON artifact suppresses richer model-consensus diagnostics.",
            ],
            "upside_opportunities": [
                f"Scenario upside vs likely: ${(best - likely)/1_000_000:.1f}M.",
                "Restoring JSON will re-enable precomputed confidence intervals by product and quarter.",
                "Live fallback still provides current ARR envelope for planning cadence.",
            ],
            "executive_actions": [
                "Re-run Panel Writer notebook to regenerate ai_insights_latest.json.",
                "Validate UC Volume path and app service principal read permissions.",
                "Alert on missing or stale insights artifact before executive review windows.",
            ],
        }
    except Exception as exc:
        logger.warning("[forecast/intelligence] fallback query failed: %s", exc)
        return {
            "source": "fallback",
            "error": f"{reason}; fallback query failed: {exc}",
            "momentum": "STABLE",
            "risk_level": "MODERATE",
            "model_confidence": 55,
            "best_model": "Prophet",
            "best_mape": 0,
            "forecast_most_likely": 0,
            "forecast_low": 0,
            "forecast_high": 0,
            "narrative": "AI insights artifact is unavailable and fallback query failed. Retry after notebook and connectivity checks.",
            "key_drivers": ["Restore insights artifact", "Verify backend Databricks auth", "Retry refresh"],
            "downside_risks": ["Missing artifact", "Fallback query failed", "No model-consensus diagnostics"],
            "upside_opportunities": ["Recover artifact output", "Restore table query access", "Resume quantified executive narratives"],
            "executive_actions": ["Run Panel Writer", "Check app permissions", "Validate endpoint health"],
        }


@router.get("/insights")
async def get_forecast_insights(
    metric: str = Query("won_pipeline"),
    model: str = Query("prophet"),
    product: Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
):
    """Read pre-computed AI insights from UC Volume JSON."""
    try:
        with open(AI_INSIGHTS_JSON_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload
    except FileNotFoundError:
        return _fallback_intelligence_payload(
            product=product,
            product_line=product_line,
            reason="Insights file not found",
        )
    except json.JSONDecodeError:
        return _fallback_intelligence_payload(
            product=product,
            product_line=product_line,
            reason="Invalid JSON",
        )


@router.get("/intelligence")
async def get_forecast_intelligence(
    metric: str = Query("won_pipeline"),
    model: str = Query("prophet"),
    product: Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
):
    """
    Backward-compatible alias consumed by ForecastIntelligence component.
    """
    return await get_forecast_insights(
        metric=metric,
        model=model,
        product=product,
        product_line=product_line,
    )


@router.get("/models")
async def list_models():
    return {
        "models": {
            "prophet": {
                "name": "Prophet",
                "description": "Primary live model from arr_forecast_v2 table",
                "status": "live",
            },
            "ensemble": {
                "name": "Ensemble",
                "description": "Planned",
                "status": "soon",
            },
            "lightgbm": {
                "name": "LightGBM",
                "description": "Planned",
                "status": "soon",
            },
            "ets": {
                "name": "ETS",
                "description": "Planned",
                "status": "soon",
            },
            "chronos": {
                "name": "Chronos",
                "description": "Planned",
                "status": "soon",
            },
        },
        "source_table": f"{GOLD_CATALOG}.{GOLD_SCHEMA}.arr_forecast_v2",
    }


@router.get("/run")
async def deprecated_run_endpoint():
    return {
        "message": "Forecasts are pre-computed by the weekly Databricks Job. Use /api/forecast/arr.",
        "status": "deprecated",
    }
