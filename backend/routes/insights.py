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
from typing import Any, Dict, List, Optional

from auth import require_authenticated_user
from config.settings import settings
from services.insight_engine import insight_engine
from services.gaim_data_service import get_current_kpi_data
from services.openai_insight_service import answer_executive_question
from services.data_fetcher import DataFetcher

router = APIRouter(prefix="/api/insights", tags=["insights"])
_tables = DataFetcher()


def _severity_from_kpi_status(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "action required":
        return "high"
    if normalized == "watch closely":
        return "medium"
    if normalized == "exceeding target":
        return "low"
    return "low"


def _load_cached_insights() -> List[Dict[str, Any]]:
    table = f"{settings.atlas_catalog}.{settings.atlas_schema}.atlas_insights_cache"
    sql = f"""
        SELECT insight_id, insight_type, kpi_name, kpi_status, headline, narrative,
               recommendation, expires_at, report_date
        FROM {table}
        WHERE report_date = CURRENT_DATE()
          AND expires_at > NOW()
        ORDER BY insight_type ASC, insight_id ASC
    """
    with _tables.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

    insights: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(zip(columns, row))
        action = record.get("recommendation")
        insights.append({
            "id": record.get("insight_id"),
            "type": record.get("insight_type"),
            "title": record.get("headline"),
            "description": record.get("narrative"),
            "action": action,
            "recommendation": action,
            "severity": _severity_from_kpi_status(record.get("kpi_status")),
            "metric": record.get("kpi_name"),
            "kpi_status": record.get("kpi_status"),
            "expires_at": record.get("expires_at"),
            "report_date": record.get("report_date"),
        })
    return insights


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
    try:
        insights = _load_cached_insights()
    except Exception as exc:
        print(f"[Insights] cached insights query failed: {exc} — falling back to generated insights")
        kpi_data = await get_current_kpi_data(
            product=product, quarter=quarter, geo=geo, channel=channel
        )
        insights = insight_engine.generate_all_insights(kpi_data)

    result = {"insights": insights, "count": len(insights)}

    if include_narrative:
        first = insights[0] if insights else None
        result["narrative"] = (
            f"{first.get('title')}: {first.get('description')}"
            if first and first.get("description")
            else (first.get("title") if first else "")
        )

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
