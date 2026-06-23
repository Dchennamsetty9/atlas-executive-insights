"""
routes/forecast.py
Prophet-first, table-driven forecast endpoints for Atlas Executive Insights.

Primary source table:
  datagroup_mdl.mdl_sales_analytics.forecast_prophet
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/forecast", tags=["forecast"])

GOLD_CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
GOLD_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "mdl_sales_analytics")
FORECAST_OUTPUT_TABLE = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`forecast_prophet`"
FORECAST_INSIGHTS_TABLE = FORECAST_OUTPUT_TABLE
FORECAST_LEADERBOARD_TABLE = f"`{GOLD_CATALOG}`.`{GOLD_SCHEMA}`.`forecast_prophet_leaderboard`"


def _live_mode_available() -> bool:
    on_databricks = bool(
        os.getenv("DATABRICKS_HOST")
        or os.getenv("DATABRICKS_SERVER_HOSTNAME")
    )
    force_live = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
    return token_available() and (on_databricks or force_live)


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


def _base_forecast_sql(product: Optional[str], product_line: Optional[str]) -> str:
    return f"""
        SELECT
            CAST(ds AS STRING) AS date,
            SUM(COALESCE(CAST(Actuals AS DOUBLE), CAST(actuals AS DOUBLE), 0)) AS arr_actual,
            SUM(COALESCE(CAST(Most_Likely AS DOUBLE), CAST(most_likely AS DOUBLE), CAST(arr_prophet AS DOUBLE), CAST(yhat AS DOUBLE), 0)) AS arr_likely,
            SUM(COALESCE(CAST(Worst_Case AS DOUBLE), CAST(worst_case AS DOUBLE), CAST(yhat_lower AS DOUBLE), 0)) AS arr_worst,
            SUM(COALESCE(CAST(Best_Case AS DOUBLE), CAST(best_case AS DOUBLE), CAST(yhat_upper AS DOUBLE), 0)) AS arr_best
        FROM {FORECAST_OUTPUT_TABLE}
        WHERE {_run_date_filter(FORECAST_OUTPUT_TABLE)}
          {_product_clause(product, product_line)}
        GROUP BY ds
        ORDER BY ds
    """


def _products_sql() -> str:
    return f"""
        SELECT DISTINCT COALESCE(CAST(product_line AS STRING), CAST(product AS STRING)) AS product
        FROM {FORECAST_OUTPUT_TABLE}
        WHERE {_run_date_filter(FORECAST_OUTPUT_TABLE)}
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
            "Prophet captures seasonality and trend directly from forecast_prophet",
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


def _demo_insights(metric: str = "won_pipeline") -> dict:
    defaults = _insight_defaults()
    return {
        "source": "demo",
        "model_used": "prophet",
        "model_name": "Prophet",
        "model_confidence": 0.84,
        "trend_status": "stable",
        "risk_level": "moderate",
        "growth_rate": 0.041,
        "forecast_90d": {
            "most_likely": 19600000,
            "best_case": 20900000,
            "worst_case": 18300000,
        },
        "upside_dollar": 1300000,
        "downside_dollar": -1300000,
        "mape": 19.4,
        "rmse": 0.0,
        "description": "Prophet baseline indicates steady ARR momentum with moderate uncertainty over the next 90 days.",
        "metric": metric,
        "history_days": 84,
        "run_date": datetime.utcnow().strftime("%Y-%m-%d"),
        **defaults,
    }


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
            COALESCE(CAST(mape_prophet AS DOUBLE), CAST(mape AS DOUBLE), 19.4) AS mape
        FROM {FORECAST_LEADERBOARD_TABLE}
        WHERE {_run_date_filter(FORECAST_LEADERBOARD_TABLE)}
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


@router.get("/insights")
async def get_forecast_insights(
    metric: str = Query("won_pipeline"),
    model: str = Query("prophet"),
    product: Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
):
    """
    Derive executive forecast intelligence from forecast_prophet.
    This endpoint is resilient and always returns a usable payload.
    """
    model_used = _normalize_model_name(model)
    if model_used != "prophet":
        model_used = "prophet"

    if not _live_mode_available():
        return _demo_insights(metric)

    defaults = _insight_defaults()

    summary_sql = f"""
        SELECT
            MAX(CAST(run_date AS STRING)) AS run_date,
            SUM(COALESCE(CAST(Most_Likely AS DOUBLE), CAST(most_likely AS DOUBLE), CAST(arr_prophet AS DOUBLE), CAST(yhat AS DOUBLE), 0)) AS most_likely,
            SUM(COALESCE(CAST(Best_Case AS DOUBLE), CAST(best_case AS DOUBLE), CAST(yhat_upper AS DOUBLE), 0)) AS best_case,
            SUM(COALESCE(CAST(Worst_Case AS DOUBLE), CAST(worst_case AS DOUBLE), CAST(yhat_lower AS DOUBLE), 0)) AS worst_case,
            AVG(COALESCE(CAST(mape_prophet AS DOUBLE), CAST(mape AS DOUBLE), 19.4)) AS mape
        FROM {FORECAST_INSIGHTS_TABLE}
        WHERE {_run_date_filter(FORECAST_INSIGHTS_TABLE)}
          {_product_clause(product, product_line)}
          AND COALESCE(CAST(Most_Likely AS DOUBLE), CAST(most_likely AS DOUBLE), CAST(arr_prophet AS DOUBLE), CAST(yhat AS DOUBLE), 0) > 0
    """

    actuals_sql = f"""
        SELECT
            CAST(ds AS STRING) AS date,
            SUM(COALESCE(CAST(Actuals AS DOUBLE), CAST(actuals AS DOUBLE), 0)) AS value
        FROM {FORECAST_INSIGHTS_TABLE}
        WHERE {_run_date_filter(FORECAST_INSIGHTS_TABLE)}
          {_product_clause(product, product_line)}
          AND COALESCE(CAST(Actuals AS DOUBLE), CAST(actuals AS DOUBLE), 0) > 0
        GROUP BY ds
        ORDER BY ds
    """

    product_mix_sql = f"""
        SELECT
            COALESCE(CAST(product_line AS STRING), CAST(product AS STRING), 'Unknown') AS product,
            SUM(COALESCE(CAST(Most_Likely AS DOUBLE), CAST(most_likely AS DOUBLE), CAST(arr_prophet AS DOUBLE), CAST(yhat AS DOUBLE), 0)) AS likely
        FROM {FORECAST_INSIGHTS_TABLE}
        WHERE {_run_date_filter(FORECAST_INSIGHTS_TABLE)}
          {_product_clause(product, product_line)}
          AND COALESCE(CAST(Most_Likely AS DOUBLE), CAST(most_likely AS DOUBLE), CAST(arr_prophet AS DOUBLE), CAST(yhat AS DOUBLE), 0) > 0
        GROUP BY COALESCE(CAST(product_line AS STRING), CAST(product AS STRING), 'Unknown')
        ORDER BY likely DESC
        LIMIT 2
    """

    try:
        summary_rows = execute_query(summary_sql)
        actual_rows = execute_query(actuals_sql)
        product_rows = execute_query(product_mix_sql)

        summary = summary_rows[0] if summary_rows else {}
        most_likely = round(_f(summary.get("most_likely")), 0)
        best_case = round(_f(summary.get("best_case"), most_likely), 0)
        worst_case = round(_f(summary.get("worst_case"), most_likely), 0)
        mape = round(_f(summary.get("mape"), 19.4), 1)
        run_date = str(summary.get("run_date") or datetime.utcnow().strftime("%Y-%m-%d"))[:10]

        actuals = [
            {"date": str(r.get("date") or "")[:10], "value": _f(r.get("value"))}
            for r in actual_rows
            if r.get("date")
        ]

        trend_status, growth_rate = _trend_from_actuals(actuals[-12:])
        risk_level, confidence = _risk_from_band(most_likely, best_case, worst_case)

        top_products = [str(r.get("product") or "").strip() for r in product_rows if r.get("product")]
        if top_products:
            defaults["key_drivers"][0] = (
                "Primary contribution mix in this run: " + ", ".join(top_products)
            )

        if risk_level == "high":
            defaults["executive_actions"][0] = "Run weekly risk reviews for top committed opportunities"
        if trend_status == "accelerating":
            defaults["upside_opportunities"][0] = "Current acceleration supports upside above baseline planning"
        if trend_status == "decelerating":
            defaults["downside_risks"][0] = "Decelerating actuals can compress outcomes toward worst-case"

        description = (
            "Prophet baseline from mdl_sales_analytics.forecast_prophet indicates "
            f"a {trend_status} trajectory with {risk_level} uncertainty for the next 90 days."
        )

        return {
            "source": "live",
            "model_used": "prophet",
            "model_name": "Prophet",
            "model_confidence": confidence,
            "trend_status": trend_status,
            "risk_level": risk_level,
            "growth_rate": growth_rate,
            "forecast_90d": {
                "most_likely": most_likely,
                "best_case": best_case,
                "worst_case": worst_case,
            },
            "upside_dollar": round(best_case - most_likely, 0),
            "downside_dollar": round(worst_case - most_likely, 0),
            "mape": mape,
            "rmse": 0.0,
            "description": description,
            "metric": metric,
            "history_days": len(actuals),
            "run_date": run_date,
            **defaults,
        }
    except Exception:
        return _demo_insights(metric)


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
                "description": "Primary live model from forecast_prophet table",
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
        "source_table": f"{GOLD_CATALOG}.{GOLD_SCHEMA}.forecast_prophet",
    }


@router.get("/run")
async def deprecated_run_endpoint():
    return {
        "message": "Forecasts are pre-computed by the weekly Databricks Job. Use /api/forecast/arr.",
        "status": "deprecated",
    }
