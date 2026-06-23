"""
routes/ai_stream.py
====================
Unified streaming AI endpoint for the "Ask AI" panel.

POST /api/ai/ask/stream  →  text/event-stream (SSE)

Intent routing:
  DATA           → Databricks Genie (NL→SQL on live GAIM tables)
  INSIGHT        → Azure OpenAI / Databricks Claude + live KPI context
  RECOMMENDATION → Atlas Intelligence pre-computed patterns + OpenAI synthesis
  Default        → DATA

SSE event protocol
------------------
  {"type": "routing",  "intent": "DATA|INSIGHT|RECOMMENDATION", "text": "..."}
  {"type": "progress", "text": "..."}
  {"type": "sql",      "sql":  "SELECT ..."}
  {"type": "token",    "text": "..."}          <- streamed LLM token
  {"type": "done",     "conversation_id": "..."}
  {"type": "error",    "text": "..."}
"""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import require_authenticated_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai-stream"])


# -- Request model -------------------------------------------------------------

class AskStreamRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    history: List[Dict] = []          # [{question, answer}] -- last N turns


# -- Intent classification -----------------------------------------------------

_DATA_KEYWORDS = {
    "show me", "what was", "how many", "list", "give me", "what is the",
    "compare", "breakdown", "by market", "by channel", "by product",
    "quarter", "last quarter", "this quarter", "q1", "q2", "q3", "q4",
    "total", "sum", "count", "average", "attainment", "vs plan",
    "versus", "ytd", "mtd", "weekly", "daily", "won amount", "pipeline",
    "mql", "close rate", "win rate", "ads ", "coverage",
}

_INSIGHT_KEYWORDS = {
    "why", "what's driving", "what is driving", "explain", "analyze",
    "analyse", "root cause", "what caused", "reason for", "impact of",
    "tell me about", "what does", "what happened", "help me understand",
    "what led to", "interpret",
}

_RECOMMENDATION_KEYWORDS = {
    "recommend", "should we", "should i", "how to improve", "what action",
    "prioritize", "prioritise", "what to do", "how do we", "what should",
    "fix", "address", "improve", "increase", "boost", "strategy",
    "what can we", "how can we",
}


def _classify_intent(question: str) -> str:
    q = question.lower()
    if any(kw in q for kw in _RECOMMENDATION_KEYWORDS):
        return "RECOMMENDATION"
    if any(kw in q for kw in _INSIGHT_KEYWORDS):
        return "INSIGHT"
    if any(kw in q for kw in _DATA_KEYWORDS):
        return "DATA"
    return "DATA"          # default: route to Genie for best data accuracy


# -- SSE helpers ---------------------------------------------------------------

def _sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': event_type, **kwargs})}\n\n"


# -- Async OpenAI streaming client ---------------------------------------------

def _build_async_client():
    try:
        from openai import AsyncAzureOpenAI
        key = (
            os.environ.get("AZURE_OPENAI_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not key or not endpoint or "your-resource" in endpoint:
            return None
        return AsyncAzureOpenAI(
            api_key=key,
            api_version="2024-02-01",
            azure_endpoint=endpoint,
        )
    except ImportError:
        return None


_async_client = _build_async_client()
_DEPLOYMENT   = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4")

try:
    from services.openai_insight_service import SYSTEM_PROMPT
except ImportError:
    SYSTEM_PROMPT = "You are a sales analytics AI for GoTo. Be concise and data-driven."


async def _stream_openai(messages: list) -> AsyncGenerator[str, None]:
    """Stream tokens from Azure OpenAI; degrades gracefully if not configured."""
    if _async_client is None:
        yield _sse(
            "token",
            text=(
                "Azure OpenAI is not configured. "
                "Set AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT to enable AI insights."
            ),
        )
        return

    try:
        stream = await _async_client.chat.completions.create(
            model=_DEPLOYMENT,
            messages=messages,
            temperature=0.3,
            max_tokens=500,
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield _sse("token", text=token)
    except Exception as exc:
        logger.exception("OpenAI streaming error")
        yield _sse("error", text=f"AI error: {exc}")


# -- KPI snapshot helper -------------------------------------------------------

def _get_kpi_snapshot() -> dict:
    """Pull current-quarter KPI snapshot from in-memory cache."""
    try:
        from services.data_cache import data_cache
        cached = data_cache.get("kpis:None:None:All:All:All")
        if cached and isinstance(cached, list):
            return {
                k.get("id", k.get("title", "unknown")): {
                    "value":       k.get("value"),
                    "target":      k.get("target"),
                    "achievement": k.get("targetAchievement"),
                    "trend":       k.get("trend"),
                    "status":      k.get("status"),
                }
                for k in cached
            }
    except Exception:
        pass
    return {}


# -- Core async stream generator -----------------------------------------------

async def _generate_stream(
    question: str,
    conversation_id: Optional[str],
    history: List[Dict],
) -> AsyncGenerator[str, None]:
    from services.genie_service import genie_service

    intent = _classify_intent(question)
    yield _sse("routing", intent=intent, text=f"Routing as {intent.lower()} query...")

    # DATA → Databricks Genie -------------------------------------------------
    if intent == "DATA":
        yield _sse("progress", text="Translating your question to SQL and querying live data...")
        try:
            if conversation_id:
                raw    = await genie_service.send_message(conversation_id, question)
                result = genie_service.parse_genie_response(raw)
            else:
                result = await genie_service.ask_kpi_question(question)

            new_conv_id = result.get("conversation_id") or ""

            if result.get("sql"):
                yield _sse("sql", sql=result["sql"])

            answer = result.get("answer") or "No result returned from Genie."

            # Word-chunk the answer to simulate streaming
            words = answer.split()
            for i, word in enumerate(words):
                sep = " " if i < len(words) - 1 else ""
                yield _sse("token", text=word + sep)
                if i % 10 == 0:
                    await asyncio.sleep(0)

            yield _sse("done", conversation_id=new_conv_id)

        except Exception as exc:
            logger.exception("Genie error in stream")
            yield _sse("error", text=f"Databricks Genie error: {exc}")
            yield _sse("done", conversation_id="")

    # INSIGHT → Azure OpenAI + live KPI context --------------------------------
    elif intent == "INSIGHT":
        yield _sse("progress", text="Loading live KPI context...")
        kpi_snapshot = await asyncio.to_thread(_get_kpi_snapshot)

        yield _sse("progress", text="Generating insight...")

        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-6:]:
            if turn.get("question"):
                msgs.append({"role": "user",      "content": turn["question"]})
            if turn.get("answer"):
                msgs.append({"role": "assistant", "content": turn["answer"]})

        context_block = (
            f"Live KPI Snapshot (current quarter, all markets):\n"
            f"{json.dumps(kpi_snapshot, indent=2)}\n\n"
            if kpi_snapshot else ""
        )
        msgs.append({"role": "user", "content": f"{context_block}Question: {question}"})

        async for chunk in _stream_openai(msgs):
            yield chunk

        yield _sse("done", conversation_id="")

    # RECOMMENDATION → Atlas Intelligence + OpenAI synthesis ------------------
    elif intent == "RECOMMENDATION":
        yield _sse("progress", text="Pulling Atlas Intelligence patterns...")

        atlas_context = ""
        try:
            from services.insight_engine import InsightEngine
            from services.data_cache import data_cache

            cached = data_cache.get("kpis:None:None:All:All:All")
            if cached and isinstance(cached, list):
                kpi_dict = {}
                for k in cached:
                    kid = k.get("id", "")
                    kpi_dict[kid]               = k.get("value")
                    kpi_dict[f"{kid}_target"]   = k.get("target")

                engine   = InsightEngine()
                findings = await asyncio.to_thread(engine.generate_all_insights, kpi_dict)
                if findings:
                    atlas_context = (
                        "Atlas Intelligence Findings (top 3):\n"
                        + json.dumps(findings[:3], indent=2)
                        + "\n\n"
                    )
        except Exception as exc:
            logger.warning("Atlas insights unavailable: %s", exc)

        yield _sse("progress", text="Synthesizing recommendation...")

        kpi_snapshot = await asyncio.to_thread(_get_kpi_snapshot)
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-4:]:
            if turn.get("question"):
                msgs.append({"role": "user",      "content": turn["question"]})
            if turn.get("answer"):
                msgs.append({"role": "assistant", "content": turn["answer"]})

        kpi_block = (
            f"Live KPIs:\n{json.dumps(kpi_snapshot, indent=2)}\n\n"
            if kpi_snapshot else ""
        )
        msgs.append({
            "role":    "user",
            "content": f"{kpi_block}{atlas_context}Question: {question}",
        })

        async for chunk in _stream_openai(msgs):
            yield chunk

        yield _sse("done", conversation_id="")


# -- Endpoint ------------------------------------------------------------------

@router.post("/ask/stream")
async def ask_ai_stream(req: AskStreamRequest, _user: str = Depends(require_authenticated_user)):
    """
    Unified streaming Ask AI endpoint with intent routing.
    Returns a server-sent event (SSE) stream.
    Connect from the browser with: fetch + response.body.getReader()

    Event types: routing | progress | sql | token | done | error
    """
    if not req.question or not req.question.strip():
        async def _empty():
            yield _sse("error", text="question must not be empty")
            yield _sse("done",  conversation_id="")
        return StreamingResponse(_empty(), media_type="text/event-stream")

    return StreamingResponse(
        _generate_stream(
            req.question.strip(),
            req.conversation_id,
            req.history or [],
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",    # disable nginx proxy buffering
        },
    )
