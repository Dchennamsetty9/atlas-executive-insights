"""
openai_insight_service.py
Azure OpenAI natural-language layer for the Atlas Hidden Insights Engine.

Provides two public async functions:
  generate_insight_narrative(kpi_data, insights) -> str
      Generates a 3-5 bullet executive summary from detected KPI patterns.

  answer_executive_question(question, kpi_context) -> str
      Answers a free-form question using the live KPI snapshot as context.

Both functions degrade gracefully: if AZURE_OPENAI_KEY / AZURE_OPENAI_ENDPOINT
are not set the functions return a plain-text fallback so nothing else breaks.

The openai SDK's create() calls are synchronous; they are run in a thread pool
via asyncio.to_thread so the FastAPI event loop is never blocked.
"""

import asyncio
import os
from typing import Any, Dict, List

try:
    from openai import AzureOpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


# ── Client ────────────────────────────────────────────────────────────────────

def _build_client():
    """Return an AzureOpenAI client, or None if credentials are absent."""
    if not _OPENAI_AVAILABLE:
        return None
    # Support both env var names (AZURE_OPENAI_KEY is the Task-5 spec name;
    # AZURE_OPENAI_API_KEY is the name already used in .env and settings.py)
    key = (
        os.environ.get("AZURE_OPENAI_KEY")
        or os.environ.get("AZURE_OPENAI_API_KEY")
    )
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not key or not endpoint or "your-resource" in endpoint or "your-api-key" in (key or ""):
        return None
    return AzureOpenAI(
        api_key=key,
        api_version="2024-02-01",
        azure_endpoint=endpoint,
    )


_client = _build_client()
_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4")


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are an executive analytics AI for GoTo's GAIM sales intelligence system.

Key metric definitions you MUST understand:
- Won Pipeline $   = Total ACV from closed-won deals
- Active Pipeline $ = Total value of open (not yet closed) deals
- ADS (Average Deal Size) = Won Pipeline $ / Won Opps count
- Win Rate         = Won / (Won + Lost)  -- ONLY resolved deals, excludes open
- Close Rate (Vol) = Won / All Opened Opps -- includes open deals in denominator
- Close Rate ($)   = Won Pipeline $ / Created Pipeline $ -- dollar-weighted
- Coverage %       = Active Pipeline / Remaining Target
- Created Pipeline = New opportunities entered into funnel in selected period
- MQL              = Marketing Qualified Leads handed to sales

CRITICAL DISTINCTION:
- Close Rate INCLUDES open deals -> appears lower mid-quarter (this is normal, NOT a problem)
- Win Rate EXCLUDES open deals -> unaffected by timing
- When Win Rate is high but Close Rate is low = TIMING signal, not performance issue

Dollarized Impact Logic:
- Each KPI gap translates to dollar revenue impact
- Won Opps Impact  = (Actual - Target opps) x Target ADS
- ADS Impact       = (Actual - Target ADS) x Actual won opps
- Large negative pipeline + small close rate gap = VOLUME problem
- Large negative close rate + small pipeline gap = CONVERSION problem

Segment Dimensions Available:
- Channel (Enterprise, Partner, Mid-Market, MSP, GSI, Small Business)
- Geo/Market (NA, EMEA, LATAM, APAC)
- Product hierarchy (Group -> Family -> Genus)
- Fuel Source (Marketing, BDR, AE, Partner)
- Deal Band ($0-10K, $10K-25K, $25K-100K, $100K-500K, $500K-1M, $1M+)
- Purchase Type (Expansion, New, Cancel, Non-Recurring)

When analyzing data:
1. Always decompose revenue gaps into component KPI drivers
2. Flag when Win Rate and Close Rate diverge (timing signal)
3. Identify segment-level patterns hidden in aggregates
4. Compare current pacing to historical same-day benchmarks
5. Quantify insights in dollars whenever possible
6. Prioritize: which lever has the biggest dollar impact?

Tone: Executive-level. Concise. Lead with insight, then explain why.
Always include dollar amounts. Return plain text, no JSON wrappers.
"""


# ── Blocking helpers (run inside asyncio.to_thread) ──────────────────────────

def _call_chat(messages: List[Dict], max_tokens: int) -> str:
    """Blocking OpenAI call — must be wrapped in asyncio.to_thread."""
    response = _client.chat.completions.create(  # type: ignore[union-attr]
        model=_DEPLOYMENT,
        messages=messages,
        temperature=0.3,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


# ── Public async API ──────────────────────────────────────────────────────────

async def generate_insight_narrative(
    kpi_data: Dict[str, Any],
    insights: List[Dict],
) -> str:
    """
    Generate a concise executive insight summary (3-5 bullet points) from
    live KPI data and the patterns detected by InsightEngine.

    Falls back to a plain-text summary derived from the detected patterns
    when Azure OpenAI credentials are not configured.
    """
    if _client is None:
        return _fallback_narrative(insights)

    user_content = (
        f"Current KPI Data:\n{kpi_data}\n\n"
        f"Detected Patterns:\n{insights}\n\n"
        "Generate a concise executive insight summary (3-5 bullet points).\n"
        "Focus on: What is happening, Why it matters, What to do about it.\n"
        "Include specific dollar amounts and percentages."
    )

    return await asyncio.to_thread(
        _call_chat,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        500,
    )


async def answer_executive_question(
    question: str,
    kpi_context: Dict[str, Any],
) -> str:
    """
    Answer a free-form executive question grounded in the live KPI snapshot.

    Falls back to a generic "data unavailable" message when Azure OpenAI
    credentials are not configured.
    """
    if _client is None:
        return (
            "Azure OpenAI is not configured. "
            "Please set AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT."
        )

    return await asyncio.to_thread(
        _call_chat,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role":    "user",
                "content": f"Context:\n{kpi_context}\n\nQuestion: {question}",
            },
        ],
        400,
    )


# ── Fallback (no credentials) ─────────────────────────────────────────────────

def _fallback_narrative(insights: List[Dict]) -> str:
    """Build a plain-text summary from InsightEngine output without OpenAI."""
    if not insights:
        return "No significant patterns detected in current KPI data."

    lines = ["Executive Summary (rule-based — Azure OpenAI not configured):", ""]
    for ins in insights:
        title = ins.get("title", "Unnamed insight")
        desc  = ins.get("description", "")
        rec   = ins.get("recommendation", "")
        lines.append(f"- **{title}**: {desc}")
        if rec:
            lines.append(f"  Recommendation: {rec}")
    return "\n".join(lines)
