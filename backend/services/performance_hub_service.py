"""
services/performance_hub_service.py
====================================
Data service for the Performance Hub dashboard.

Queries federated.sales.metis_* tables to compute all 12 core KPIs,
revenue gap decomposition, QoQ/MoM comparisons, and quarterly/monthly trends.

Source tables
-------------
  federated.sales.metis_opened_opps_fact  — created/opened opportunities
  federated.sales.metis_won_opps_fact     — closed-won opportunities
  federated.sales.metis_targets_summary   — paced + full quarterly targets

Filter validation
-----------------
All user-supplied filter values are validated against strict whitelists before
being embedded in SQL.  Unknown values are silently treated as "All" so the
query degrades gracefully rather than raising errors or leaking raw input into SQL.

Period logic
------------
  QTD          : quarter_start .. today          (paced targets)
  MTD          : month_start .. today            (paced targets)
  YTD          : year_start  .. today            (paced targets)
  LAST_QUARTER : prior quarter start .. end      (full targets)
  CUSTOM       : caller-supplied dates           (paced if current quarter, full if past)
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from config.settings import settings
from query_loader import load_query
from services.data_fetcher import DataFetcher
from services.databricks_connection import DATABRICKS_AVAILABLE, execute_query, token_available

# ── Whitelists ────────────────────────────────────────────────────────────────
# All user-supplied filter values must be in these sets.
# Unrecognised values are ignored (treated as "All").

_VALID_MARKET: frozenset[str] = frozenset({
    "NA", "EMEA", "AUS/ROW", "INDIA", "LATAM",
})

_VALID_CHANNEL: frozenset[str] = frozenset({
    "Enterprise", "Mid-Market", "Small Business", "MSP", "Partner",
    "Strategic", "Distributed Enterprise", "FSP JR", "GSI", "RPSM",
    "Sales Other",
})

_VALID_PRODUCT_GROUP: frozenset[str] = frozenset({"ITSG", "UCC"})

_VALID_PRODUCT_FAMILY: frozenset[str] = frozenset({
    "Access", "RSG-IT", "Events", "Meetings", "Service", "UCaaS",
})

_VALID_PRODUCT_GENUS: frozenset[str] = frozenset({
    "GoToConnect", "Rescue", "GoToMyPC", "GoToWebinar",
    "GoToMeeting", "GoToTraining", "OpenVoice", "Central",
    "Resolve", "Bold360", "Grasshopper",
})

_VALID_FUEL_SOURCE: frozenset[str] = frozenset({
    "Marketing", "BDR", "AE", "Partner",
})

_VALID_PLAN_VERSION: frozenset[str] = frozenset({"Plan", "FY4", "FY7"})

_VALID_PERIOD_TYPE: frozenset[str] = frozenset({
    "QTD", "MTD", "YTD", "LAST_QUARTER", "CUSTOM",
})

# ── Filter dataclass ──────────────────────────────────────────────────────────


@dataclass
class PerformanceFilters:
    """
    All filter parameters for Performance Hub queries.
    None / empty string / 'All' means "no filter on that dimension".
    """
    period_type:     str            = "QTD"   # QTD | MTD | YTD | LAST_QUARTER | CUSTOM
    custom_start:    Optional[str]  = None    # YYYY-MM-DD; only when period_type = CUSTOM
    custom_end:      Optional[str]  = None
    sales_market:    Optional[str]  = None
    sales_channel:   Optional[str]  = None
    product_group:   Optional[str]  = None
    product_family:  Optional[str]  = None
    product_genus:   Optional[str]  = None
    fuel_source:     Optional[str]  = None
    plan_version:    str            = "Plan"


# ── Date helpers ──────────────────────────────────────────────────────────────

def _quarter_start(d: date) -> date:
    return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def _prior_quarter_start(d: date) -> date:
    qs = _quarter_start(d)
    # Go back one day from quarter start → previous quarter, then find its start
    prev = qs - timedelta(days=1)
    return _quarter_start(prev)


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _prior_month_start(d: date) -> date:
    ms = _month_start(d)
    prev = ms - timedelta(days=1)
    return date(prev.year, prev.month, 1)


def _year_start(d: date) -> date:
    return date(d.year, 1, 1)


def _resolve_period(filters: PerformanceFilters) -> tuple[str, str, str]:
    """
    Returns (period_start, period_end, quarter_start) as YYYY-MM-DD strings.
    period_end is capped at today (never in the future).
    """
    today = date.today()
    pt    = filters.period_type.upper()

    if pt == "QTD":
        qs    = _quarter_start(today)
        start = qs
        end   = today
    elif pt == "MTD":
        start = _month_start(today)
        end   = today
        qs    = _quarter_start(today)
    elif pt == "YTD":
        start = _year_start(today)
        end   = today
        qs    = _quarter_start(today)
    elif pt == "LAST_QUARTER":
        pqs   = _prior_quarter_start(today)
        qs    = pqs
        start = pqs
        # End = last day of prior quarter (one day before current quarter start)
        end   = _quarter_start(today) - timedelta(days=1)
    elif pt == "CUSTOM" and filters.custom_start and filters.custom_end:
        start = date.fromisoformat(filters.custom_start)
        end   = min(date.fromisoformat(filters.custom_end), today)
        qs    = _quarter_start(start)
    else:
        # Fallback to QTD
        qs    = _quarter_start(today)
        start = qs
        end   = today

    return start.isoformat(), end.isoformat(), qs.isoformat()


# ── Filter clause builder ─────────────────────────────────────────────────────

# Column names differ slightly between tables — define the mapping here.
_COL_MAP_FACTS = {
    "sales_market":   "sales_market",
    "sales_channel":  "sales_channel",
    "product_group":  "product_group",
    "product_family": "product_family",
    "product_genus":  "product_genus",
    "fuel_source":    "fuel_source",
}

_COL_MAP_TARGETS = {
    "sales_market":   "sales_market",
    "sales_channel":  "sales_channel",
    "product_group":  "product_group",
    "product_family": "product_family",
    "product_genus":  "product_genus",
    "fuel_source":    "fuel_source",
}


def _build_filter_clause(
    filters: PerformanceFilters,
    col_map: Dict[str, str],
) -> str:
    """
    Build an AND-prefixed SQL WHERE fragment from validated filter values.
    Only dimensions present in col_map are included.
    Column names and values are strictly validated — raw user input is never
    interpolated directly.
    """
    parts: List[str] = []

    checks = [
        ("sales_market",   filters.sales_market,   _VALID_MARKET),
        ("sales_channel",  filters.sales_channel,  _VALID_CHANNEL),
        ("product_group",  filters.product_group,  _VALID_PRODUCT_GROUP),
        ("product_family", filters.product_family, _VALID_PRODUCT_FAMILY),
        ("product_genus",  filters.product_genus,  _VALID_PRODUCT_GENUS),
        ("fuel_source",    filters.fuel_source,    _VALID_FUEL_SOURCE),
    ]

    for key, value, valid_set in checks:
        if value and value not in ("", "All") and value in valid_set and key in col_map:
            col = col_map[key]
            # Value is whitelist-validated above — safe to embed as literal.
            parts.append(f"AND {col} = '{value}'")

    return "\n      ".join(parts) if parts else ""


def _validate_plan_version(v: str) -> str:
    return v if v in _VALID_PLAN_VERSION else "Plan"


# ── AI Insight prompt template ────────────────────────────────────────────────

AI_INSIGHT_PROMPT = """\
You are an executive sales analyst. Generate a concise, data-driven insight (3–5 sentences)
based on the Performance Hub KPI data below. Your insight should:
1. State the top headline (are we above or below target, and by how much?).
2. Identify the single largest driver of any gap using the dollarized impact data.
3. Give one concrete, actionable recommendation.
4. Use dollar figures and percentages, not vague language.

--- KPI DATA ---
Period: {period_label}
Filters: {filter_summary}

Won Amount:        ${won_amount:,.0f}  vs  target ${target_won_amount:,.0f}  ({won_amount_attainment_pct:.1f}%)  [{won_amount_status}]
# Deals Won:       {won_opps_count:,}  vs  target {target_won_opps:,.0f}  ({won_opps_attainment:.1%})
# Opps Created:   {opened_opps_count:,}  vs  target {target_opened_opps:,.0f}  ({opened_opps_attainment:.1%})
Pipeline $:        ${pipeline_amount:,.0f}  vs  target ${target_pipeline_amount:,.0f}  ({pipeline_attainment:.1%})
ADS:               ${avg_deal_size:,.0f}  vs  target ${target_avg_deal_size:,.0f}
AOS:               ${avg_opp_size:,.0f}  vs  target ${target_avg_opp_size:,.0f}
Close Rate (Vol):  {close_rate_opps:.1%}  vs  target {target_close_rate_opps:.1%}
Close Rate ($):    {close_rate_dollar:.1%}  vs  target {target_close_rate_dollar:.1%}
Coverage:          {coverage_ratio:.2f}x  (>1.0x = sufficient pipeline)

--- REVENUE GAP DECOMPOSITION ---
Total Gap:               ${total_gap:+,.0f}
  Opp Volume Funnel:
    Opened Opps Impact:  ${impact_opened_opps:+,.0f}
    Close Rate (Vol):    ${impact_close_rate_opps:+,.0f}
    ADS Impact:          ${impact_ads:+,.0f}
  Dollar Funnel:
    Pipeline Impact:     ${impact_pipeline:+,.0f}
    AOS Impact:          ${impact_aos:+,.0f}
    Close Rate ($):      ${impact_close_rate_dollar:+,.0f}

Positive = above target contribution. Negative = below target drag.

Write your insight now:
"""


# ── Main service class ────────────────────────────────────────────────────────


class PerformanceHubService:
    """
    All public methods are async-safe; blocking Databricks calls run via
    asyncio.to_thread() so they never block the event loop.

    Falls back to empty/demo data when Databricks is unavailable.
    """

    def __init__(self) -> None:
        _on_databricks = bool(os.getenv("DATABRICKS_HOST"))
        _force_live    = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
        self.available = DATABRICKS_AVAILABLE and token_available() and (_on_databricks or _force_live)
        self._data_fetcher = DataFetcher()

    # ── Public async API ──────────────────────────────────────────────────────

    async def fetch_kpi_dashboard(
        self, filters: PerformanceFilters
    ) -> Dict[str, Any]:
        """
        Returns all 12 KPI actuals, paced targets, attainment %, and status.
        Single-row result as a flat dict.
        """
        if self.available:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self.get_kpi_summary_from_table, filters),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                print("[PerformanceHub] kpi_dashboard timed out — returning demo data")
            except Exception as exc:
                print(f"[PerformanceHub] kpi_dashboard failed: {exc} — returning demo data")
        return _demo_kpi_dashboard()

    async def fetch_revenue_gap(
        self, filters: PerformanceFilters
    ) -> Dict[str, Any]:
        """
        Returns dollarized revenue gap decomposition for the two-funnel model.
        """
        if self.available:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._query_revenue_gap, filters),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                print("[PerformanceHub] revenue_gap timed out — returning empty")
            except Exception as exc:
                print(f"[PerformanceHub] revenue_gap failed: {exc} — returning empty")
        return {}

    async def fetch_qoq_comparison(
        self, filters: PerformanceFilters
    ) -> Dict[str, Any]:
        """
        Returns current-quarter vs prior-quarter metrics using is_in_qoq_period.
        """
        if self.available:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._query_qoq_comparison, filters),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                print("[PerformanceHub] qoq_comparison timed out — returning empty")
            except Exception as exc:
                print(f"[PerformanceHub] qoq_comparison failed: {exc} — returning empty")
        return {}

    async def fetch_mom_comparison(
        self, filters: PerformanceFilters
    ) -> Dict[str, Any]:
        """
        Returns current-month vs prior-month metrics using is_in_mom_period.
        """
        if self.available:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._query_mom_comparison, filters),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                print("[PerformanceHub] mom_comparison timed out — returning empty")
            except Exception as exc:
                print(f"[PerformanceHub] mom_comparison failed: {exc} — returning empty")
        return {}

    async def fetch_trend(
        self,
        grain:   str,            # "quarterly" | "monthly"
        filters: PerformanceFilters,
        n_quarters: int = 6,
    ) -> List[Dict[str, Any]]:
        """
        Returns time-series trend data.
          grain="quarterly" → one row per quarter (last n_quarters)
          grain="monthly"   → one row per month   (last n_quarters × 3 months)
        """
        if self.available:
            try:
                fn = (self._query_trend_quarterly if grain == "quarterly"
                      else self._query_trend_monthly)
                return await asyncio.wait_for(
                    asyncio.to_thread(fn, filters, n_quarters),
                    timeout=25.0,
                )
            except asyncio.TimeoutError:
                print(f"[PerformanceHub] trend_{grain} timed out — returning empty")
            except Exception as exc:
                print(f"[PerformanceHub] trend_{grain} failed: {exc} — returning empty")
        return []

    async def build_ai_prompt(
        self,
        kpi_data: Dict[str, Any],
        gap_data: Dict[str, Any],
        filters:  PerformanceFilters,
        period_label: str = "",
    ) -> str:
        """
        Builds a ready-to-send LLM prompt populated with live KPI values.
        Pass the result to your LLM client (Azure OpenAI, Databricks FMAPI, etc.).
        """
        if not period_label:
            start, end, _ = _resolve_period(filters)
            period_label  = f"{start} to {end}"

        filter_parts = [
            f"Market={filters.sales_market or 'All'}",
            f"Channel={filters.sales_channel or 'All'}",
            f"Product={filters.product_genus or filters.product_family or filters.product_group or 'All'}",
            f"Fuel={filters.fuel_source or 'All'}",
            f"Plan={filters.plan_version}",
        ]

        merged = {**kpi_data, **gap_data}
        # Provide zero-safe defaults for every placeholder
        safe: Dict[str, Any] = {
            "period_label":              period_label,
            "filter_summary":            ", ".join(filter_parts),
            "won_amount":                merged.get("won_amount", 0),
            "target_won_amount":         merged.get("target_won_amount", 0),
            "won_amount_attainment_pct": (merged.get("won_amount_attainment_pct") or 0),
            "won_amount_status":         merged.get("won_amount_status", "N/A"),
            "won_opps_count":            merged.get("won_opps_count", 0),
            "target_won_opps":           merged.get("target_won_opps", 0),
            "won_opps_attainment":       (merged.get("won_opps_attainment") or 0),
            "opened_opps_count":         merged.get("opened_opps_count", 0),
            "target_opened_opps":        merged.get("target_opened_opps", 0),
            "opened_opps_attainment":    (merged.get("opened_opps_attainment") or 0),
            "pipeline_amount":           merged.get("pipeline_amount", 0),
            "target_pipeline_amount":    merged.get("target_pipeline_amount", 0),
            "pipeline_attainment":       (merged.get("pipeline_attainment") or 0),
            "avg_deal_size":             merged.get("avg_deal_size", 0),
            "target_avg_deal_size":      merged.get("target_avg_deal_size", 0),
            "avg_opp_size":              merged.get("avg_opp_size", 0),
            "target_avg_opp_size":       merged.get("target_avg_opp_size", 0),
            "close_rate_opps":           merged.get("close_rate_opps", 0),
            "target_close_rate_opps":    merged.get("target_close_rate_opps", 0),
            "close_rate_dollar":         merged.get("close_rate_dollar", 0),
            "target_close_rate_dollar":  merged.get("target_close_rate_dollar", 0),
            "coverage_ratio":            merged.get("coverage_ratio") or 0,
            "total_gap":                 merged.get("total_gap", 0),
            "impact_opened_opps":        merged.get("impact_opened_opps", 0),
            "impact_close_rate_opps":    merged.get("impact_close_rate_opps", 0),
            "impact_ads":                merged.get("impact_ads", 0),
            "impact_pipeline":           merged.get("impact_pipeline", 0),
            "impact_aos":                merged.get("impact_aos", 0),
            "impact_close_rate_dollar":  merged.get("impact_close_rate_dollar", 0),
        }

        return AI_INSIGHT_PROMPT.format(**safe)

    # ── Blocking query implementations (run in thread pool) ───────────────────

    def _execute_table_query(
        self,
        query: str,
        params: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        with self._data_fetcher.get_connection() as connection:
            with connection.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def _status_from_pct(self, value: Optional[float]) -> str:
        pct = float(value or 0)
        if pct >= 100:
            return "Exceeding Target"
        if pct >= 85:
            return "Watch Closely"
        return "Action Required"

    def _coverage_status_from_ratio(self, value: Optional[float]) -> str:
        ratio = float(value or 0)
        if ratio >= 1:
            return "Exceeding Target"
        if ratio >= 0.85:
            return "Watch Closely"
        return "Action Required"

    def _map_kpi_summary_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        won_acv_qtr = float(row.get("won_acv_qtr") or 0)
        deals_won_qtr = int(row.get("deals_won_qtr") or 0)
        total_quota = float(row.get("total_quota") or 0)
        full_quota = float(row.get("full_quota") or 0)
        attainment_pct = float(row.get("attainment_pct") or 0)
        pipeline_acv = float(row.get("pipeline_acv") or 0)
        pipeline_opps = int(row.get("pipeline_opps") or 0)
        pipeline_coverage_ratio = float(row.get("pipeline_coverage_ratio") or 0)
        pipeline_attainment_pct = float(row.get("pipeline_attainment_pct") or 0)
        created_pipeline_qtr = float(row.get("created_pipeline_qtr") or 0)
        opps_created_qtr = int(row.get("opps_created_qtr") or 0)
        win_rate_pct = float(row.get("win_rate_pct") or 0)
        close_rate_dollar_pct = float(row.get("close_rate_dollar_pct") or 0)
        close_rate_vol_pct = float(row.get("close_rate_vol_pct") or 0)

        target_pipeline_amount = 0.0
        if pipeline_acv and pipeline_attainment_pct:
            target_pipeline_amount = pipeline_acv / (pipeline_attainment_pct / 100.0)

        mapped = dict(row)
        mapped.update({
            "won_amount": won_acv_qtr,
            "target_won_amount": total_quota,
            "full_won_amount": full_quota,
            "won_amount_attainment": attainment_pct / 100.0,
            "won_amount_attainment_pct": attainment_pct,
            "won_amount_status": self._status_from_pct(attainment_pct),
            "won_opps_count": deals_won_qtr,
            "target_won_opps": None,
            "won_opps_attainment": None,
            "won_opps_status": self._status_from_pct(attainment_pct),
            "avg_deal_size": float(row.get("avg_deal_size") or 0),
            "target_avg_deal_size": None,
            "opened_opps_count": opps_created_qtr,
            "target_opened_opps": None,
            "opened_opps_attainment": None,
            "opened_opps_status": self._status_from_pct(attainment_pct),
            "pipeline_amount": pipeline_acv,
            "target_pipeline_amount": target_pipeline_amount,
            "pipeline_opps_count": pipeline_opps,
            "pipeline_attainment": pipeline_attainment_pct / 100.0,
            "pipeline_attainment_pct": pipeline_attainment_pct,
            "pipeline_status": self._status_from_pct(pipeline_attainment_pct),
            "avg_opp_size": float(row.get("avg_opp_size") or 0),
            "target_avg_opp_size": None,
            "close_rate_opps": close_rate_vol_pct / 100.0,
            "close_rate_vol_pct": close_rate_vol_pct,
            "target_close_rate_opps": None,
            "close_rate_dollar": close_rate_dollar_pct / 100.0,
            "close_rate_dollar_pct": close_rate_dollar_pct,
            "target_close_rate_dollar": None,
            "coverage_ratio": pipeline_coverage_ratio,
            "coverage_status": self._coverage_status_from_ratio(pipeline_coverage_ratio),
            "win_rate": win_rate_pct / 100.0,
            "win_rate_pct": win_rate_pct,
            "revenue_gap": float(row.get("revenue_gap") or 0),
            "mql_count": row.get("mql_count"),
            "avg_days_to_close": row.get("avg_days_to_close"),
            "data_as_of": row.get("report_date"),
        })
        return mapped

    def get_kpi_summary_from_table(
        self,
        filters: Optional[PerformanceFilters] = None,
    ) -> Dict[str, Any]:
        table = (
            f"{settings.atlas_catalog}.{settings.atlas_schema}."
            f"{settings.atlas_kpi_table_prefix}_daily_summary"
        )
        sql = f"""
        SELECT *
        FROM {table}
        WHERE report_date = CURRENT_DATE()
        LIMIT 1
        """
        rows = self._execute_table_query(sql)
        if rows:
            return self._map_kpi_summary_row(rows[0])
        return self._query_kpi_dashboard(filters or PerformanceFilters())

    def _query_kpi_dashboard(self, filters: PerformanceFilters) -> Dict[str, Any]:
        start, end, qs = _resolve_period(filters)
        won_f     = _build_filter_clause(filters, _COL_MAP_FACTS)
        targets_f = _build_filter_clause(filters, _COL_MAP_TARGETS)

        sql = load_query(
            "performance/kpi_dashboard",
            period_start  = start,
            period_end    = end,
            quarter_start = qs,
            plan_version  = _validate_plan_version(filters.plan_version),
            won_filter    = won_f,
            opened_filter = won_f,    # same columns; opened_filter = won_filter
            targets_filter= targets_f,
        )
        rows = execute_query(sql)
        return rows[0] if rows else {}

    def _query_revenue_gap(self, filters: PerformanceFilters) -> Dict[str, Any]:
        start, end, qs = _resolve_period(filters)
        won_f     = _build_filter_clause(filters, _COL_MAP_FACTS)
        targets_f = _build_filter_clause(filters, _COL_MAP_TARGETS)

        sql = load_query(
            "performance/revenue_gap",
            period_start  = start,
            period_end    = end,
            quarter_start = qs,
            plan_version  = _validate_plan_version(filters.plan_version),
            won_filter    = won_f,
            opened_filter = won_f,
            targets_filter= targets_f,
        )
        rows = execute_query(sql)
        return rows[0] if rows else {}

    def _query_qoq_comparison(self, filters: PerformanceFilters) -> Dict[str, Any]:
        today = date.today()
        cqs   = _quarter_start(today).isoformat()
        pqs   = _prior_quarter_start(today).isoformat()
        won_f     = _build_filter_clause(filters, _COL_MAP_FACTS)
        targets_f = _build_filter_clause(filters, _COL_MAP_TARGETS)

        sql = load_query(
            "performance/qoq_comparison",
            current_quarter_start = cqs,
            prior_quarter_start   = pqs,
            plan_version          = _validate_plan_version(filters.plan_version),
            won_filter            = won_f,
            opened_filter         = won_f,
            targets_filter        = targets_f,
        )
        rows = execute_query(sql)
        return rows[0] if rows else {}

    def _query_mom_comparison(self, filters: PerformanceFilters) -> Dict[str, Any]:
        today  = date.today()
        cms    = _month_start(today).isoformat()
        pms    = _prior_month_start(today).isoformat()
        cqs    = _quarter_start(today).isoformat()
        # The prior month might be in the prior quarter
        pq_ms  = _prior_month_start(today)
        pqs    = _quarter_start(pq_ms).isoformat()
        won_f     = _build_filter_clause(filters, _COL_MAP_FACTS)
        targets_f = _build_filter_clause(filters, _COL_MAP_TARGETS)

        sql = load_query(
            "performance/mom_comparison",
            current_month_start   = cms,
            prior_month_start     = pms,
            current_quarter_start = cqs,
            prior_quarter_start   = pqs,
            plan_version          = _validate_plan_version(filters.plan_version),
            won_filter            = won_f,
            opened_filter         = won_f,
            targets_filter        = targets_f,
        )
        rows = execute_query(sql)
        return rows[0] if rows else {}

    def _query_trend_quarterly(
        self, filters: PerformanceFilters, n_quarters: int
    ) -> List[Dict[str, Any]]:
        won_f     = _build_filter_clause(filters, _COL_MAP_FACTS)
        targets_f = _build_filter_clause(filters, _COL_MAP_TARGETS)

        sql = load_query(
            "performance/trend_quarterly",
            n_quarters    = n_quarters,
            plan_version  = _validate_plan_version(filters.plan_version),
            won_filter    = won_f,
            opened_filter = won_f,
            targets_filter= targets_f,
        )
        return execute_query(sql)

    def _query_trend_monthly(
        self, filters: PerformanceFilters, n_quarters: int
    ) -> List[Dict[str, Any]]:
        today  = date.today()
        # period_start = start of (n_quarters) ago
        qs     = _quarter_start(today)
        # Go back n_quarters quarters
        back   = date(qs.year, qs.month, 1)
        for _ in range(n_quarters - 1):
            back = _prior_quarter_start(back)
        won_f     = _build_filter_clause(filters, _COL_MAP_FACTS)
        targets_f = _build_filter_clause(filters, _COL_MAP_TARGETS)

        sql = load_query(
            "performance/trend_monthly",
            period_start  = back.isoformat(),
            period_end    = today.isoformat(),
            plan_version  = _validate_plan_version(filters.plan_version),
            won_filter    = won_f,
            opened_filter = won_f,
            targets_filter= targets_f,
        )
        return execute_query(sql)


# ── Demo / fallback data ──────────────────────────────────────────────────────

def _demo_kpi_dashboard() -> Dict[str, Any]:
    """Plausible demo values for local development (no Databricks token)."""
    return {
        # Won Amount
        "won_amount": 18_400_000,
        "target_won_amount": 22_000_000,
        "won_amount_attainment": 0.836,
        "won_amount_attainment_pct": 83.6,
        "won_amount_status": "Action Required",
        # Deals Won
        "won_opps_count": 147,
        "target_won_opps": 175,
        "won_opps_attainment": 0.84,
        "won_opps_status": "Watch Closely",
        # ADS
        "avg_deal_size": 125_170,
        "target_avg_deal_size": 125_714,
        # Opps Created
        "opened_opps_count": 312,
        "target_opened_opps": 340,
        "opened_opps_attainment": 0.918,
        "opened_opps_status": "Watch Closely",
        # Pipeline
        "pipeline_amount": 39_800_000,
        "target_pipeline_amount": 44_000_000,
        "pipeline_attainment": 0.905,
        "pipeline_attainment_pct": 90.5,
        "pipeline_status": "Watch Closely",
        # AOS
        "avg_opp_size": 127_564,
        "target_avg_opp_size": 129_412,
        # Close Rate Vol
        "close_rate_opps": 0.471,
        "target_close_rate_opps": 0.515,
        # Close Rate $
        "close_rate_dollar": 0.462,
        "target_close_rate_dollar": 0.500,
        # Coverage
        "coverage_ratio": 1.81,
        "coverage_status": "Exceeding Target",
        # Attainment %
        "won_amount_attainment_pct": 83.6,
        "pipeline_attainment_pct": 90.5,
        # MQL (from separate source)
        "mql_count": None,
        "target_mql_count": None,
        # Full targets
        "full_won_amount": 26_000_000,
        "full_won_opps": 207,
        "full_opened_amount": 52_000_000,
        "full_opened_opps": 402,
        "data_as_of": date.today().isoformat(),
    }
