"""
routes/insights.py
FastAPI router — AI-generated hidden insights from GAIM KPI data.

Endpoints:
  GET /api/insights/hidden-patterns      — all four insight modules + optional OpenAI narrative
  GET /api/insights/impact-decomposition — dollarized revenue gap breakdown only
  POST /api/insights/ask                 — answer a free-form executive question
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from auth import require_authenticated_user
from services.insight_engine import insight_engine
from services.gaim_data_service import get_current_kpi_data
from services.openai_insight_service import (
    generate_insight_narrative,
    answer_executive_question,
)

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/hidden-patterns")
async def get_hidden_insights(
    product:         Optional[str]  = None,
    quarter:         Optional[str]  = None,
    geo:             Optional[str]  = None,
    channel:         Optional[str]  = None,
    include_narrative: bool         = False,
):
    """
    AI-generated hidden insights derived from live GAIM KPI data.

    Pass include_narrative=true to also get an OpenAI-generated executive summary
    (requires AZURE_OPENAI_KEY + AZURE_OPENAI_ENDPOINT env vars).
    """
    kpi_data = await get_current_kpi_data(
        product=product, quarter=quarter, geo=geo, channel=channel
    )
    insights = insight_engine.generate_all_insights(kpi_data)

    result = {"insights": insights, "count": len(insights)}

    if include_narrative:
        result["narrative"] = await generate_insight_narrative(kpi_data, insights)

    return result


@router.get("/impact-decomposition")
async def get_impact_decomposition(
    product: Optional[str] = None,
    quarter: Optional[str] = None,
    geo:     Optional[str] = None,
    channel: Optional[str] = None,
):
    """Dollarized impact breakdown of the current revenue gap."""
    kpi_data = await get_current_kpi_data(
        product=product, quarter=quarter, geo=geo, channel=channel
    )
    decomposition = insight_engine.decompose_revenue_gap(kpi_data)
    return {"decomposition": decomposition, "count": len(decomposition)}


class ExecutiveQuestion(BaseModel):
    question: str
    product:  Optional[str] = None
    geo:      Optional[str] = None
    channel:  Optional[str] = None


@router.post("/ask")
async def ask_executive_question(body: ExecutiveQuestion, _user: str = Depends(require_authenticated_user)):
    """
    Answer a free-form executive question grounded in live KPI data.
    Uses Azure OpenAI with the GAIM system prompt; falls back to a plain message
    if credentials are not configured.
    """
    kpi_context = await get_current_kpi_data(
        product=body.product, geo=body.geo, channel=body.channel
    )
    answer = await answer_executive_question(body.question, kpi_context)
    return {"question": body.question, "answer": answer}
