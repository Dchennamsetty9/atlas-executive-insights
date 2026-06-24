"""
routes/ai.py
=============
AI Service Layer — 7 endpoints covering all AI touchpoints in the dashboard.

  Feature 1  GET  /api/ai/executive-summary    → Top banner: status + headline + action
  Feature 2  GET  /api/ai/hidden-insights      → Expandable panel: 3-5 non-obvious patterns
  Feature 3  POST /api/ai/kpi-card-insight     → Click ↓ Insights on a KPI card
  Feature 4  POST /api/ai/kpi-modal-insight    → One-liner inside KPI detail modal
  Feature 5  POST /api/ai/forecast-intelligence → 4-box: drivers / actions / risks / opps
  Feature 6  POST /api/ai/chart-annotation     → Inline annotation on MQL / Pipeline charts
  Feature 7  POST /api/ai/ask                  → Ask AI Chat: text-to-SQL → execute → interpret

All endpoints return {"success": true, "data": {...}} on success, or raise HTTP 500
on unrecoverable error.  The AI methods themselves never raise (they return fallback data),
so 500s only fire if the KPI fetch itself fails.

Federated tables used by text-to-SQL (Feature 7) via ai_service._TABLE_CONTEXT:
  federated.sales.metis_won_opps_fact       — won opportunities at daily granularity
  federated.sales.metis_opened_opps_fact    — opened/created opportunities
  federated.sales.metis_targets_summary     — quarterly targets with pacing

Filter dimensions supported by federated tables:
  sales_market  : NA, EMEA, LATAM, APAC, AUS/ROW
  sales_channel : Enterprise, Partner, Mid-Market, MSP, GSI, Small Business
  product_genus : GoToConnect, GoToWebinar, Rescue, Central, Resolve
  fuel_source   : Marketing, Sales, Partner, Unknown
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import require_authenticated_user
from services.ai_service import ai_service
from services.gaim_data_service import GAIMDataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Module-level GAIM service for Features 1 & 2 (they need live KPI data)
_gaim = GAIMDataService()


# ── Pydantic request models ───────────────────────────────────────────────────

class KPICardInsightRequest(BaseModel):
    kpi_name:   str
    kpi_value:  Any
    kpi_target: Any
    trend_data: List[Dict[str, Any]] = []
    context:    Optional[Dict[str, Any]] = None


class KPIModalInsightRequest(BaseModel):
    kpi_name:  str
    kpi_value: Any
    trend_data: List[Dict[str, Any]] = []


class ForecastIntelligenceRequest(BaseModel):
    forecast_data: Dict[str, Any]
    actuals:       Dict[str, Any]


class ChartAnnotationRequest(BaseModel):
    chart_type:  str
    data_points: List[Dict[str, Any]]
    metric_name: str


class AskAIRequest(BaseModel):
    question: str


# ── Feature 1: Executive Summary Banner ──────────────────────────────────────

@router.get("/executive-summary")
async def executive_summary(
    geo:          str = Query("All"),
    channel:      str = Query("All"),
    product:      str = Query("All"),
    fuel_source:  str = Query("All"),
):
    """
    Returns {status, headline, action, confidence, fallback_used}.
    Fetches live KPIs (or demo data if no token) then asks the LLM to summarise.

    Filter params map to federated table columns:
      geo         → sales_market  (NA, EMEA, LATAM, APAC, AUS/ROW)
      channel     → sales_channel (Enterprise, Partner, Mid-Market, MSP, GSI, Small Business)
      product     → product_genus (GoToConnect, GoToWebinar, Rescue, Central, Resolve)
      fuel_source → fuel_source   (Marketing, Sales, Partner, Unknown)
    """
    try:
        filters  = {"geo": geo, "channel": channel, "product": product, "fuel_source": fuel_source}
        kpi_list = await _gaim.fetch_kpis(filters=filters)
        result   = await ai_service.generate_executive_summary(kpi_list)
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("executive_summary failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Feature 2: Hidden Insights Panel ─────────────────────────────────────────

@router.get("/hidden-insights")
async def hidden_insights(
    geo:          str = Query("All"),
    channel:      str = Query("All"),
    product:      str = Query("All"),
    fuel_source:  str = Query("All"),
):
    """
    Returns {insights: [{title, detail, severity}], fallback_used}.

    Filter params map to federated table columns:
      geo         → sales_market, channel → sales_channel,
      product     → product_genus,  fuel_source → fuel_source
    """
    try:
        filters  = {"geo": geo, "channel": channel, "product": product, "fuel_source": fuel_source}
        kpi_list = await _gaim.fetch_kpis(filters=filters)
        result   = await ai_service.generate_hidden_insights(kpi_list)
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("hidden_insights failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Feature 3: KPI Card Insight ───────────────────────────────────────────────

@router.post("/kpi-card-insight")
async def kpi_card_insight(req: KPICardInsightRequest):
    """
    Returns {summary, trend_direction, risk_level, recommendation, comparison}.
    """
    try:
        result = await ai_service.generate_kpi_card_insight(
            req.kpi_name, req.kpi_value, req.kpi_target,
            req.trend_data, req.context,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("kpi_card_insight failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Feature 4: KPI Detail Modal Insight ──────────────────────────────────────

@router.post("/kpi-modal-insight")
async def kpi_modal_insight(req: KPIModalInsightRequest):
    """Returns {insight} — one-liner for the trend in a KPI detail modal."""
    try:
        result = await ai_service.generate_kpi_modal_insight(
            req.kpi_name, req.kpi_value, req.trend_data,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("kpi_modal_insight failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Feature 5: Forecast Intelligence 4-box ───────────────────────────────────

@router.post("/forecast-intelligence")
async def forecast_intelligence(req: ForecastIntelligenceRequest):
    """
    Returns {key_drivers, actions, risks, opportunities} — 3 bullets each.
    """
    try:
        result = await ai_service.generate_forecast_intelligence(
            req.forecast_data, req.actuals,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("forecast_intelligence failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Feature 6: Chart Annotation ──────────────────────────────────────────────

@router.post("/chart-annotation")
async def chart_annotation(req: ChartAnnotationRequest):
    """Returns {annotation, highlight_index} — one-line finding for a chart."""
    try:
        result = await ai_service.generate_chart_annotation(
            req.chart_type, req.data_points, req.metric_name,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("chart_annotation failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Feature 7: Ask AI Chat (Text-to-SQL) ─────────────────────────────────────

@router.post("/ask")
async def ask_ai(req: AskAIRequest, _user: str = Depends(require_authenticated_user)):
    """
    Full text-to-SQL → execute → interpret pipeline.
    Returns {answer, sql, data, visualization_hint, fallback_used}.

    - In demo mode (no Databricks token) the SQL is generated but execution
      returns a helpful message instead of real rows.
    - All SQL is generated by the LLM; no user input is embedded directly.
    """
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    try:
        result = await ai_service.ask_ai(req.question.strip())
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("ask_ai failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def ai_health():
    import os
    return {
        "status":        "ok",
        "primary_model": os.getenv("DATABRICKS_AI_PRIMARY_ENDPOINT", "databricks-claude-sonnet-4-6"),
        "fallback_model": os.getenv("DATABRICKS_AI_FALLBACK_ENDPOINT", "databricks-gemini-3-1-flash-lite"),
        "features":      [1, 2, 3, 4, 5, 6, 7],
    }
