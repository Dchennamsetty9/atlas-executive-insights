"""
backend/routes/genie.py
FastAPI router for the Databricks Genie natural-language-to-SQL AI layer.

Endpoints
---------
POST /api/genie/ask                  — ask a question (new or follow-up conversation)
GET  /api/genie/suggested-questions  — context-aware starter questions
GET  /api/genie/conversation/{id}    — check conversation state (lightweight)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from auth import require_authenticated_user
from services.genie_service import genie_service

router = APIRouter(prefix="/api/genie", tags=["genie"])


class GenieQuestion(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = "default"


@router.post("/ask")
async def ask_genie(request: GenieQuestion, _user: str = Depends(require_authenticated_user)):
    """
    Ask the Metis Genie Space a natural-language question about sales KPIs.

    - If `conversation_id` is supplied the question is sent as a follow-up in
      that conversation (Genie keeps context across turns).
    - If omitted a new conversation is started.

    Returns
    -------
    {
        "conversation_id": "...",   # keep this for follow-up questions
        "message_id":      "...",
        "answer":          "...",   # narrative answer from Genie
        "sql":             "...",   # generated SQL (may be null)
        "data":            [...],   # raw Genie attachments
        "status":          "COMPLETED"
    }
    """
    try:
        if request.conversation_id:
            result = await genie_service.send_message(
                request.conversation_id, request.question
            )
            return genie_service.parse_genie_response(result)
        else:
            return await genie_service.ask_kpi_question(request.question)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Genie error: {str(exc)}")


@router.get("/suggested-questions")
async def get_suggested_questions():
    """
    Return the curated list of questions that work well with the
    Metis - Sales KPI Analytics Genie Space.
    """
    return {
        "questions": [
            "Show me won amount vs Plan for this quarter",
            "What is our attainment against target for each market?",
            "Compare ADS this quarter to last quarter",
            "Close rate by channel for UCaaS",
            "Show me won opps over the past 7 quarters",
            "What's pipeline coverage for EMEA?",
            "Which product has the highest win rate this quarter?",
            "How does created pipeline compare YoY?",
            "Which segment is underperforming against targets?",
            "What's driving the change in active pipeline?",
        ]
    }


@router.get("/space-info")
async def get_space_info():
    """Return static metadata about the connected Genie Space."""
    return {
        "space_id":    "01f10b2015dc1186928a78ee0bb4869f",
        "space_name":  "Metis - Sales KPI Analytics",
        "warehouse":   "c24ee33594e13e93",
        "host":        "goto-data-dock.cloud.databricks.com",
        "capabilities": [
            "Compare actuals vs targets (Plan or FY)",
            "Analyze trends by time period",
            "Slice by market / channel / product / fuel",
            "Smart target pacing with equivalent-days comparison",
            "Multi-quarter historical analysis",
        ],
    }
