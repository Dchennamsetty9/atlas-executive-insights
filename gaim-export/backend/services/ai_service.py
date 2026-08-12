"""
services/ai_service.py
========================
AI insight generation using Databricks Foundation Model API.

Primary endpoint:  databricks-claude-sonnet-4-6
Fallback endpoint: databricks-gemini-3-1-flash-lite

Authentication
--------------
On Databricks Apps : WorkspaceClient() auto-authenticates via the app's
                     service principal OAuth token.  No extra config needed.
Locally            : Reads DATABRICKS_HOST + DATABRICKS_TOKEN from the
                     environment (same vars used by the SQL connector).

Usage
-----
    from services.ai_service import ai_service

    insight = await ai_service.generate_insight(kpi_data, gap_data)

The call is async-safe: the blocking SDK request runs in a thread pool so it
never blocks the FastAPI event loop.

Fallback chain
--------------
  1. databricks-claude-sonnet-4-6
  2. databricks-gemini-3-1-flash-lite
  3. Rule-based plain-text summary (no LLM call — always works)
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional
import re

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Endpoint names ─────────────────────────────────────────────────────────────
_PRIMARY_ENDPOINT  = os.getenv("DATABRICKS_AI_PRIMARY_ENDPOINT", "databricks-claude-sonnet-4-6")
_FALLBACK_ENDPOINT = os.getenv("DATABRICKS_AI_FALLBACK_ENDPOINT", "databricks-gemini-3-1-flash-lite")
_MAX_TOKENS        = 150   # ~3-4 sentences; executive summary only
_DEFAULT_WAREHOUSE_ID = "c24ee33594e13e93"

# ── Impact column → human-readable label ──────────────────────────────────────
_DRIVER_LABELS: Dict[str, str] = {
    "impact_opened_opps":        "Opened Opps Volume",
    "impact_close_rate_opps":    "Close Rate (Volume)",
    "impact_ads":                "Average Deal Size",
    "impact_pipeline":           "Pipeline ($)",
    "impact_aos":                "Average Opp Size",
    "impact_close_rate_dollar":  "Close Rate ($)",
}


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(kpi: Dict[str, Any], gap: Dict[str, Any]) -> str:
    """
    Build the LLM prompt from live KPI and gap data.
    Targets < 500 input tokens; expects < 200 output tokens.
    """
    won_amt      = kpi.get("won_amount", 0) or 0
    won_target   = kpi.get("target_won_amount", 0) or 0
    won_att      = (kpi.get("won_amount_attainment_pct") or 0)
    won_status   = kpi.get("won_amount_status", "")
    deals_won    = kpi.get("won_opps_count", 0) or 0
    won_opps_att = (kpi.get("won_opps_attainment") or 0) * 100
    ads          = kpi.get("avg_deal_size", 0) or 0
    pipeline     = kpi.get("pipeline_amount", 0) or 0
    cr_opps      = (kpi.get("close_rate_opps") or 0) * 100
    coverage     = kpi.get("coverage_ratio") or 0

    # Find the biggest gap driver (largest absolute negative impact)
    biggest_driver = ""
    driver_impact  = 0.0
    for col, label in _DRIVER_LABELS.items():
        val = gap.get(col) or 0
        if abs(val) > abs(driver_impact):
            driver_impact  = val
            biggest_driver = label

    # RAG emoji based on status
    emoji = {"Exceeding Target": "🟢", "Watch Closely": "🟡"}.get(won_status, "🔴")

    return (
        f"You are an executive sales analyst. Analyze this QTD performance "
        f"and give a 2-sentence insight + 1 actionable recommendation. "
        f"Start with {emoji} and use dollar figures.\n\n"
        f"Won Amount: ${won_amt:,.0f} ({won_att:.0f}% of ${won_target:,.0f} target)\n"
        f"Deals Won: {deals_won:,} ({won_opps_att:.0f}% of target)\n"
        f"ADS: ${ads:,.0f}\n"
        f"Pipeline Created: ${pipeline:,.0f}\n"
        f"Close Rate (Vol): {cr_opps:.1f}%\n"
        f"Coverage: {coverage:.1f}x\n"
        f"Biggest Gap Driver: {biggest_driver} (${driver_impact:+,.0f} impact)"
    )


def _rule_based_summary(kpi: Dict[str, Any], gap: Dict[str, Any]) -> str:
    """
    Plain-text summary when no LLM endpoint is reachable.
    Never fails — always returns a useful string.
    """
    won_att  = kpi.get("won_amount_attainment_pct") or 0
    status   = kpi.get("won_amount_status", "No Target")
    won_amt  = kpi.get("won_amount", 0) or 0
    target   = kpi.get("target_won_amount", 0) or 0
    gap_amt  = (won_amt - target)
    emoji    = {"Exceeding Target": "🟢", "Watch Closely": "🟡"}.get(status, "🔴")

    biggest_driver = ""
    driver_impact  = 0.0
    for col, label in _DRIVER_LABELS.items():
        val = gap.get(col) or 0
        if abs(val) > abs(driver_impact):
            driver_impact  = val
            biggest_driver = label

    direction = "above" if gap_amt >= 0 else "below"
    rec_line  = (
        f"Focus on improving {biggest_driver} to recover the largest portion of the gap."
        if gap_amt < 0 and biggest_driver
        else "Maintain current pace across all KPIs."
    )

    return (
        f"{emoji} Revenue is ${abs(won_amt):,.0f} vs ${target:,.0f} target "
        f"({won_att:.0f}% attainment), ${abs(gap_amt):,.0f} {direction} paced target. "
        f"{biggest_driver} accounts for the largest impact at ${driver_impact:+,.0f}. "
        f"Recommendation: {rec_line}"
    )


# ── Core service ───────────────────────────────────────────────────────────────

class AIService:
    """
    Async-safe wrapper around the Databricks Serving Endpoint API.

    The WorkspaceClient is constructed lazily on first use so that module
    import is instant and never triggers a credential-discovery network call.
    """

    def __init__(self) -> None:
        self._client = None   # lazy — created on first call

    def _get_client(self):
        """Return (or create) the WorkspaceClient, reading credentials from env."""
        if self._client is None:
            try:
                from databricks.sdk import WorkspaceClient
                self._client = WorkspaceClient()
            except Exception as exc:
                logger.warning("Could not create WorkspaceClient: %s", exc)
                self._client = None
        return self._client

    def _call_endpoint(self, endpoint: str, prompt: str) -> str:
        """Blocking call to a Databricks serving endpoint."""
        w = self._get_client()
        if w is None:
            raise RuntimeError("WorkspaceClient unavailable")

        response = w.serving_endpoints.query(
            name     = endpoint,
            messages = [{"role": "user", "content": prompt}],
            max_tokens = _MAX_TOKENS,
        )
        return response.choices[0].message.content

    def _generate_sync(self, prompt: str) -> str:
        """
        Try primary → fallback → rule-based.
        Runs synchronously; call via asyncio.to_thread() from async context.
        """
        for endpoint in (_PRIMARY_ENDPOINT, _FALLBACK_ENDPOINT):
            try:
                text = self._call_endpoint(endpoint, prompt)
                logger.info("AI insight generated via %s", endpoint)
                return text
            except Exception as exc:
                logger.warning("Endpoint %s failed: %s — trying next", endpoint, exc)

        logger.warning("All LLM endpoints failed — using rule-based summary")
        return None   # Signal to caller to use rule-based fallback

    async def generate_insight(
        self,
        kpi_data: Dict[str, Any],
        gap_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate an executive insight for the given KPI snapshot.

        Returns a dict with:
          insight      : the generated text (or rule-based summary)
          prompt       : the prompt that was sent to the model
          model        : which endpoint produced the response
          fallback_used: True if the rule-based summary was returned
        """
        if gap_data is None:
            gap_data = {}

        prompt = _build_prompt(kpi_data, gap_data)

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(self._generate_sync, prompt),
                timeout=20.0,   # 20 s: covers both endpoints + network
            )
        except asyncio.TimeoutError:
            logger.warning("AI insight timed out after 20s — using rule-based summary")
            text = None
        except Exception as exc:
            logger.warning("AI insight error: %s — using rule-based summary", exc)
            text = None

        fallback_used = text is None
        insight_text  = text if text else _rule_based_summary(kpi_data, gap_data)

        return {
            "insight":       insight_text,
            "prompt":        prompt,
            "fallback_used": fallback_used,
            "model":         "rule-based" if fallback_used else "databricks-endpoint",
        }


    @staticmethod
    def _warehouse_id_from_http_path(http_path: str) -> str:
        """Extract Databricks warehouse ID from /sql/1.0/warehouses/<id>."""
        match = re.search(r"/warehouses/([^/?]+)", http_path or "")
        return match.group(1) if match else _DEFAULT_WAREHOUSE_ID


    @staticmethod
    def _is_safe_read_only_sql(statement: str) -> bool:
        """Allow only single-statement SELECT/CTE queries and reject mutating SQL."""
        if not statement or not statement.strip():
            return False

        # Strip /* */ and -- comments before safety checks.
        no_block_comments = re.sub(r"/\*.*?\*/", " ", statement, flags=re.S)
        no_line_comments = re.sub(r"--.*?$", " ", no_block_comments, flags=re.M)
        normalized = no_line_comments.strip()

        # Allow at most one trailing semicolon, but disallow chained statements.
        stripped_trailing = normalized.rstrip(";").strip()
        if ";" in stripped_trailing:
            return False

        upper_stmt = stripped_trailing.upper()
        if not (upper_stmt.startswith("SELECT") or upper_stmt.startswith("WITH")):
            return False

        forbidden = r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|CALL)\b"
        if re.search(forbidden, upper_stmt):
            return False

        return True

    # ── Generic multi-turn LLM helpers ──────────────────────────────────────

    def _call_llm_messages_sync(
        self, messages: list, max_tokens: int = 512
    ) -> str:
        """Send a messages list to the LLM.  Primary → fallback endpoints."""
        try:
            from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
        except ImportError as exc:
            raise RuntimeError("databricks-sdk not available") from exc

        w = self._get_client()
        if w is None:
            raise RuntimeError("WorkspaceClient unavailable")

        sdk_messages = [
            ChatMessage(role=ChatMessageRole(m["role"]), content=m["content"])
            for m in messages
        ]

        for endpoint in (_PRIMARY_ENDPOINT, _FALLBACK_ENDPOINT):
            try:
                resp = w.serving_endpoints.query(
                    name=endpoint,
                    messages=sdk_messages,
                    max_tokens=max_tokens,
                )
                logger.info("AI response from %s", endpoint)
                return resp.choices[0].message.content
            except Exception as exc:
                logger.warning("Endpoint %s failed: %s — trying next", endpoint, exc)

        raise RuntimeError("All LLM endpoints failed")

    def _call_llm_json_sync(
        self, messages: list, max_tokens: int = 512
    ) -> Dict[str, Any]:
        """Call LLM and parse the response as JSON (strips markdown fences)."""
        import json as _json

        raw = self._call_llm_messages_sync(messages, max_tokens)
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return _json.loads(cleaned.strip())

    async def _ai_json(
        self,
        messages: list,
        max_tokens: int = 512,
        default: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Async wrapper around _call_llm_json_sync with 25 s timeout + fallback."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_llm_json_sync, messages, max_tokens),
                timeout=25.0,
            )
        except Exception as exc:
            logger.warning("AI JSON call failed: %s", exc)
            return default or {}

    def _execute_sql_sync(self, query: str) -> list:
        """Run a SQL query against the Databricks SQL warehouse and return rows as dicts."""
        w = self._get_client()
        if w is None:
            raise RuntimeError("WorkspaceClient unavailable")

        if not self._is_safe_read_only_sql(query):
            raise ValueError("Only single-statement read-only SELECT queries are allowed")

        warehouse_id = self._warehouse_id_from_http_path(settings.databricks_http_path)

        result = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=query,
            wait_timeout="30s",
        )
        state = result.status.state.value if result.status and result.status.state else "UNKNOWN"
        if state != "SUCCEEDED":
            raise RuntimeError(f"SQL execution failed (state={state}): {result.status.error if result.status else 'unknown'}")

        columns = [col.name for col in result.manifest.schema.columns]
        rows = []
        if result.result and result.result.data_array:
            for row in result.result.data_array:
                rows.append(dict(zip(columns, row)))
        return rows

    # ── Feature 1: Executive Summary Banner ─────────────────────────────────

    async def generate_executive_summary(
        self,
        kpi_list: list,
        gap_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Given a list of KPI dicts (from /api/kpis), returns:
          {status, headline, action, confidence, fallback_used}
        status is "green" | "yellow" | "red".
        """
        import json as _json

        # Compact representation for the prompt (keep token count low)
        summary_rows = []
        for k in kpi_list[:14]:
            att = k.get("targetAchievement") or k.get("target_achievement") or 0
            summary_rows.append(
                f"  {k.get('name', k.get('metric_name', '?'))}: "
                f"{k.get('value', k.get('metric_value', 0))} "
                f"({att:.0f}% of target)"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an executive sales analytics advisor. "
                    "Given a QTD KPI snapshot, return a JSON object with exactly these keys:\n"
                    '  "status": "green" (all on track), "yellow" (some at risk), or "red" (critical issues)\n'
                    '  "headline": one sentence ≤20 words summarising overall performance\n'
                    '  "action": the single most impactful action right now, ≤15 words\n'
                    '  "confidence": float 0-1\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": "QTD KPI snapshot:\n" + "\n".join(summary_rows),
            },
        ]

        result = await self._ai_json(messages, max_tokens=256)

        if not result:
            # Rule-based fallback
            total = len(kpi_list)
            red   = sum(1 for k in kpi_list if (k.get("targetAchievement") or 0) < 85)
            yell  = sum(1 for k in kpi_list if 85 <= (k.get("targetAchievement") or 0) < 100)
            status = "red" if red > total // 3 else ("yellow" if yell > 0 or red > 0 else "green")
            return {
                "status":        status,
                "headline":      f"{total - red - yell}/{total} KPIs on track QTD.",
                "action":        "Review KPIs requiring attention.",
                "confidence":    0.5,
                "fallback_used": True,
            }

        result["fallback_used"] = False
        return result

    # ── Feature 2: Hidden Insights ───────────────────────────────────────────

    async def generate_hidden_insights(
        self, kpi_list: list
    ) -> Dict[str, Any]:
        """
        Returns {"insights": [{title, detail, severity}]} with 3-5 non-obvious patterns.
        """
        import json as _json

        rows = []
        for k in kpi_list[:14]:
            rows.append({
                "name":       k.get("name", k.get("metric_name")),
                "value":      k.get("value", k.get("metric_value")),
                "target":     k.get("target", k.get("target_value")),
                "attainment": k.get("targetAchievement", k.get("target_achievement")),
                "trend":      k.get("trend"),
            })

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior sales analytics expert. "
                    "Identify 3-5 NON-OBVIOUS insights from this KPI data. "
                    "Look for cross-metric correlations, leading indicators, anomalies, hidden risks.\n"
                    'Return JSON: {"insights": [{"title": "...", "detail": "2-3 sentences", "severity": "info|warning|critical"}]}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {"role": "user", "content": _json.dumps(rows, default=str)},
        ]

        result = await self._ai_json(messages, max_tokens=1024)
        if not result or "insights" not in result:
            return {"insights": [], "fallback_used": True}
        result["fallback_used"] = False
        return result

    # ── Feature 3: KPI Card Insight ──────────────────────────────────────────

    async def generate_kpi_card_insight(
        self,
        kpi_name: str,
        kpi_value: Any,
        kpi_target: Any,
        trend_data: list,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Deep-dive on a single KPI card.
        Returns {summary, trend_direction, risk_level, recommendation, comparison}.
        """
        import json as _json

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a KPI analyst. Provide a focused deep-dive on one KPI. "
                    'Return JSON: {"summary": "2-3 sentences", "trend_direction": "up|down|flat", '
                    '"risk_level": "low|medium|high", "recommendation": "specific action ≤15 words", '
                    '"comparison": "vs target context ≤12 words"}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": _json.dumps({
                    "kpi": kpi_name,
                    "value": kpi_value,
                    "target": kpi_target,
                    "trend": trend_data[-10:] if trend_data else [],
                    "context": context or {},
                }, default=str),
            },
        ]

        result = await self._ai_json(messages, max_tokens=400)
        if not result:
            return {
                "summary": f"{kpi_name} is at {kpi_value} vs target {kpi_target}.",
                "trend_direction": "flat",
                "risk_level": "medium",
                "recommendation": "Monitor this KPI closely.",
                "comparison": "See target above.",
                "fallback_used": True,
            }
        result["fallback_used"] = False
        return result

    # ── Feature 4: KPI Detail Modal Insight ─────────────────────────────────

    async def generate_kpi_modal_insight(
        self,
        kpi_name: str,
        kpi_value: Any,
        trend_data: list,
    ) -> Dict[str, Any]:
        """One-liner insight for the trend chart in a KPI detail modal."""
        import json as _json

        messages = [
            {
                "role": "system",
                "content": (
                    "Write exactly ONE sentence (max 20 words) explaining what this KPI trend means for the business. "
                    'Return JSON: {"insight": "your sentence"}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": _json.dumps({
                    "kpi": kpi_name,
                    "value": kpi_value,
                    "trend": trend_data[-7:] if trend_data else [],
                }, default=str),
            },
        ]

        result = await self._ai_json(messages, max_tokens=128)
        if not result or "insight" not in result:
            return {"insight": f"{kpi_name} trend data shown above.", "fallback_used": True}
        result["fallback_used"] = False
        return result

    # ── Feature 5: Forecast Intelligence (4-box) ────────────────────────────

    async def generate_forecast_intelligence(
        self,
        forecast_data: Dict[str, Any],
        actuals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Returns {key_drivers, actions, risks, opportunities} — 3 bullets each.
        """
        import json as _json

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a sales forecasting strategist. "
                    "Produce a 4-box analysis, 3 bullet points per box (≤12 words each). "
                    'Return JSON: {"key_drivers": ["...","...","..."], "actions": ["...","...","..."], '
                    '"risks": ["...","...","..."], "opportunities": ["...","...","..."]}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": _json.dumps({
                    "forecast": forecast_data,
                    "actuals": actuals,
                }, default=str),
            },
        ]

        defaults = {
            "key_drivers":   ["Won pipeline pacing vs. quarterly target", "Close rate vs. prior period", "Deal volume entering funnel"],
            "actions":       ["Accelerate late-stage deal reviews", "Increase prospecting cadence for at-risk reps", "Review pricing on stuck deals"],
            "risks":         ["Coverage ratio below 3× may limit upside", "Late-stage slippage could miss quarter", "Seasonal slowdown in deal velocity"],
            "opportunities": ["Expansion deals showing strong conversion", "Mid-market segment outperforming plan", "Pipeline build ahead of target in EMEA"],
        }

        result = await self._ai_json(messages, max_tokens=600, default=defaults)
        result["fallback_used"] = result == defaults
        return result

    # ── Feature 6: Chart Annotation ─────────────────────────────────────────

    async def generate_chart_annotation(
        self,
        chart_type: str,
        data_points: list,
        metric_name: str,
    ) -> Dict[str, Any]:
        """One-line contextual finding for a chart (MQL, Pipeline, ARR, etc.)."""
        import json as _json

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a chart annotation engine. "
                    "Identify the single most interesting finding in the data in one line (≤15 words). "
                    "Also identify which 0-based data point index to highlight (or null). "
                    'Return JSON: {"annotation": "...", "highlight_index": int|null}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": _json.dumps({
                    "chart": chart_type,
                    "metric": metric_name,
                    "data": data_points[-30:] if data_points else [],
                }, default=str),
            },
        ]

        result = await self._ai_json(messages, max_tokens=128)
        if not result or "annotation" not in result:
            return {"annotation": "", "highlight_index": None, "fallback_used": True}
        result["fallback_used"] = False
        return result

    # ── Feature 7: Ask AI Chat (Text-to-SQL) ────────────────────────────────

    _TABLE_CONTEXT = (
        "TABLE: federated.sales.metis_won_opps_fact\n"
        "Description: Won opportunities at daily granularity — one row per won opportunity.\n"
        "Key columns: "
        "close_date (DATE — the date the deal was won), "
        "salesforce_opportunity_id (STRING — use COUNT(DISTINCT ...) for deal counts), "
        "amount_towards_plan (DECIMAL — ACV / won revenue), "
        "sales_market (STRING — geo dimension: NA, EMEA, LATAM, APAC, AUS/ROW), "
        "sales_channel (STRING — Enterprise, Partner, Mid-Market, MSP, GSI, Small Business), "
        "product_group (STRING), product_family (STRING), "
        "product_genus (STRING — GoToConnect, GoToWebinar, Rescue, Central, Resolve), "
        "category (STRING — New Business, Expansion, Renewal), "
        "fuel_source (STRING — Marketing, Sales, Partner, Unknown), "
        "is_in_qoq_period (BOOLEAN — TRUE = within QTD same-period-last-quarter window), "
        "is_in_mom_period (BOOLEAN — TRUE = within MTD same-period-last-month window), "
        "data_date (DATE — data load date; use CURRENT_DATE() for latest)\n\n"

        "TABLE: federated.sales.metis_opened_opps_fact\n"
        "Description: Opened / created opportunities at daily granularity — one row per opportunity.\n"
        "Key columns: "
        "pipeline_entered_date (DATE — date opportunity entered pipeline), "
        "salesforce_opportunity_id (STRING — use COUNT(DISTINCT ...) for opp counts), "
        "amount_towards_plan (DECIMAL — pipeline value), "
        "sales_market (STRING), sales_channel (STRING), "
        "product_group (STRING), product_family (STRING), product_genus (STRING), "
        "category (STRING), fuel_source (STRING), "
        "is_in_qoq_period (BOOLEAN), is_in_mom_period (BOOLEAN), "
        "data_date (DATE)\n\n"

        "TABLE: federated.sales.metis_targets_summary\n"
        "Description: Quarterly targets with pacing — already aggregated at quarter × dimension grain.\n"
        "Key columns: "
        "quarter_start_date (DATE — first day of the quarter), "
        "plan_version (STRING — filter with plan_version = 'Plan' for official targets), "
        "sales_market (STRING), sales_channel (STRING), "
        "product_genus (STRING), product_family (STRING), product_group (STRING), "
        "fuel_source (STRING), "
        "full_won_opps (DECIMAL — full-quarter won opp target), "
        "full_won_amount (DECIMAL — full-quarter won revenue target), "
        "full_opened_opps (DECIMAL — full-quarter pipeline opp target), "
        "full_opened_amount (DECIMAL — full-quarter pipeline value target), "
        "paced_won_opps (DECIMAL — QTD-paced won opp target), "
        "paced_won_amount (DECIMAL — QTD-paced won revenue target), "
        "paced_opened_opps (DECIMAL — QTD-paced pipeline opp target), "
        "paced_opened_amount (DECIMAL — QTD-paced pipeline value target)"
    )

    def _generate_sql_sync(self, question: str) -> Dict[str, Any]:
        """Step 1: natural language → SQL via LLM."""
        import json as _json

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a SQL expert for Databricks Unity Catalog. "
                    "Convert the user's question into SQL using ONLY these tables:\n\n"
                    + self._TABLE_CONTEXT
                    + "\n\nRules:\n"
                    "- Use fully qualified table names (federated.sales.<table>)\n"
                    "- For WON revenue/deal metrics query metis_won_opps_fact using close_date\n"
                    "- For PIPELINE/OPENED metrics query metis_opened_opps_fact using pipeline_entered_date\n"
                    "- For TARGETS query metis_targets_summary; always add plan_version = 'Plan'\n"
                    "- Always use COUNT(DISTINCT salesforce_opportunity_id) for opportunity counts\n"
                    "- data_date is DATE type; use CURRENT_DATE() for today\n"
                    "- For 'current quarter': DATE_TRUNC('quarter', close_date) = DATE_TRUNC('quarter', CURRENT_DATE())\n"
                    "- sales_market values: NA, EMEA, LATAM, APAC, AUS/ROW\n"
                    "- product_genus values: GoToConnect, GoToWebinar, Rescue, Central, Resolve\n"
                    "- Use is_in_qoq_period = TRUE to compare QTD vs same-period last quarter\n"
                    "- For paced targets use paced_won_amount / paced_won_opps from metis_targets_summary\n"
                    "- Limit to 100 rows max\n"
                    'Return JSON: {"sql": "...", "visualization_hint": "table|bar|line|number"}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {"role": "user", "content": question},
        ]
        return self._call_llm_json_sync(messages, max_tokens=512)

    def _interpret_results_sync(
        self, question: str, sql: str, rows: list
    ) -> str:
        """Step 3: interpret SQL results back into natural language."""
        import json as _json

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an executive sales analyst. "
                    "Given a question and query results, provide a clear 2-3 sentence answer. "
                    "Use specific numbers. If results are empty, say so clearly. "
                    'Return JSON: {"answer": "..."}\n'
                    "Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": _json.dumps({
                    "question": question,
                    "sql": sql,
                    "results": rows[:20],
                    "total_rows": len(rows),
                }, default=str),
            },
        ]
        result = self._call_llm_json_sync(messages, max_tokens=400)
        return result.get("answer", "Could not interpret results.")

    async def ask_ai(self, question: str) -> Dict[str, Any]:
        """
        Full text-to-SQL → execute → interpret pipeline.
        Returns {answer, sql, data, visualization_hint, fallback_used}.
        """
        # Step 1: Generate SQL
        try:
            sql_resp = await asyncio.wait_for(
                asyncio.to_thread(self._generate_sql_sync, question),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("SQL generation failed: %s", exc)
            return {
                "answer": "Unable to generate a query for that question. Please try rephrasing.",
                "sql": None,
                "data": [],
                "visualization_hint": "none",
                "fallback_used": True,
            }

        generated_sql = sql_resp.get("sql", "")
        viz_hint      = sql_resp.get("visualization_hint", "table")

        # Step 2: Execute SQL
        try:
            rows = await asyncio.wait_for(
                asyncio.to_thread(self._execute_sql_sync, generated_sql),
                timeout=35.0,
            )
        except Exception as exc:
            logger.warning("SQL execution failed: %s", exc)
            # If generated SQL fails (common: federated UC permissions),
            # route to Databricks Genie so users still get an answer.
            try:
                from services.genie_service import genie_service

                genie_result = await asyncio.wait_for(
                    genie_service.ask_kpi_question(question),
                    timeout=45.0,
                )
                return {
                    "answer": genie_result.get("answer") or "Genie returned no answer.",
                    "sql": genie_result.get("sql") or generated_sql,
                    "data": genie_result.get("data") or [],
                    "visualization_hint": viz_hint,
                    "fallback_used": True,
                    "source": "genie",
                }
            except Exception as genie_exc:
                logger.warning("Genie fallback failed: %s", genie_exc)
            return {
                "answer": f"Query generated but failed to execute: {exc}",
                "sql":    generated_sql,
                "data":   [],
                "visualization_hint": viz_hint,
                "fallback_used": True,
                "source": "sql-error",
            }

        # Step 3: Interpret results
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(self._interpret_results_sync, question, generated_sql, rows),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("Result interpretation failed: %s", exc)
            answer = f"Found {len(rows)} row(s). Could not generate a natural-language summary."

        return {
            "answer":             answer,
            "sql":                generated_sql,
            "data":               rows,
            "visualization_hint": viz_hint,
            "fallback_used":      False,
            "source":             "statement-execution",
        }


# ── Module-level singleton ─────────────────────────────────────────────────────
# WorkspaceClient is NOT created here — only on first generate_insight() call.
ai_service = AIService()
