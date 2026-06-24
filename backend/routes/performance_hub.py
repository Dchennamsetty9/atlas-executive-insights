"""
routes/performance_hub.py
===========================
Performance Hub API — all 12 core KPIs, revenue gap decomposition,
QoQ/MoM comparison, and quarterly/monthly trend data.

Data source: federated.sales.metis_* tables

Endpoints
---------
  GET  /api/performance/kpis            → All 12 KPI actuals + targets + attainment + status
  GET  /api/performance/revenue-gap     → Dollarized impact decomposition (two-funnel model)
  GET  /api/performance/qoq             → Quarter-over-quarter fair comparison
  GET  /api/performance/mom             → Month-over-month fair comparison
  GET  /api/performance/trend           → Quarterly or monthly KPI time series
  GET  /api/performance/ai-insight      → Pre-built LLM prompt with live data injected
  GET  /api/performance/filters         → Available filter dimension values

Common query parameters (all GET endpoints except /filters)
------------------------------------------------------------
  period      : QTD | MTD | YTD | LAST_QUARTER | CUSTOM  (default: QTD)
  start_date  : YYYY-MM-DD  required when period=CUSTOM
  end_date    : YYYY-MM-DD  required when period=CUSTOM
  market      : NA | EMEA | AUS/ROW | INDIA | LATAM
  channel     : Enterprise | Mid-Market | Small Business | MSP | Partner | ...
  product_group   : ITSG | UCC
  product_family  : Access | RSG-IT | Events | Meetings | Service | UCaaS
  product_genus   : GoToConnect | Rescue | GoToMyPC | ...
  fuel_source : Marketing | BDR | AE | Partner
  plan_version: Plan | FY4 | FY7  (default: Plan)
"""

from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional

from config.settings import settings
from services.performance_hub_service import (
    PerformanceFilters,
    PerformanceHubService,
    _VALID_MARKET,
    _VALID_CHANNEL,
    _VALID_PRODUCT_GROUP,
    _VALID_PRODUCT_FAMILY,
    _VALID_PRODUCT_GENUS,
    _VALID_FUEL_SOURCE,
    _VALID_PLAN_VERSION,
)
from services.ai_service import ai_service
from services.data_fetcher import DataFetcher

router  = APIRouter(prefix="/api/performance", tags=["performance"])
_svc    = PerformanceHubService()
_tables = DataFetcher()


# ── Shared parameter extraction ───────────────────────────────────────────────

def _get_filters(
    period:         str = "QTD",
    start_date:     Optional[str] = None,
    end_date:       Optional[str] = None,
    market:         Optional[str] = None,
    channel:        Optional[str] = None,
    product_group:  Optional[str] = None,
    product_family: Optional[str] = None,
    product_genus:  Optional[str] = None,
    fuel_source:    Optional[str] = None,
    plan_version:   str = "Plan",
) -> PerformanceFilters:
    return PerformanceFilters(
        period_type    = period.upper(),
        custom_start   = start_date,
        custom_end     = end_date,
        sales_market   = market        or None,
        sales_channel  = channel       or None,
        product_group  = product_group or None,
        product_family = product_family or None,
        product_genus  = product_genus or None,
        fuel_source    = fuel_source   or None,
        plan_version   = plan_version,
    )


def _escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _query_atlas_table(table_name: str, where_clauses: Optional[List[str]] = None, order_by: Optional[str] = None) -> List[Dict[str, Any]]:
    table = f"{settings.atlas_catalog}.{settings.atlas_schema}.{table_name}"
    where_sql = "\n          ".join(where_clauses or [])
    order_sql = f"\n        ORDER BY {order_by}" if order_by else ""
    sql = f"""
        SELECT *
        FROM {table}
        WHERE report_date = CURRENT_DATE()
          {where_sql}
        {order_sql}
    """
    try:
        with _tables.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as exc:
        print(f"[PerformanceHub] atlas table query failed for {table_name}: {exc}")
        return []


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/kpis", summary="All 12 KPI actuals, paced targets, attainment %, and RAG status")
async def get_kpi_dashboard(
    period:         str           = Query("QTD",  description="QTD | MTD | YTD | LAST_QUARTER | CUSTOM"),
    start_date:     Optional[str] = Query(None,   description="YYYY-MM-DD (CUSTOM only)"),
    end_date:       Optional[str] = Query(None,   description="YYYY-MM-DD (CUSTOM only)"),
    market:         Optional[str] = Query(None),
    channel:        Optional[str] = Query(None),
    product_group:  Optional[str] = Query(None),
    product_family: Optional[str] = Query(None),
    product_genus:  Optional[str] = Query(None),
    fuel_source:    Optional[str] = Query(None),
    plan_version:   str           = Query("Plan", description="Plan | FY4 | FY7"),
) -> Dict[str, Any]:
    filters = _get_filters(
        period, start_date, end_date,
        market, channel, product_group, product_family, product_genus,
        fuel_source, plan_version,
    )
    return await _svc.fetch_kpi_dashboard(filters)


@router.get("/by-rep", summary="Rep-level daily KPI summary from materialized Atlas tables")
async def get_rep_performance(
    territory: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Optional atlas_kpi_daily_by_rep status_indicator filter"),
) -> Dict[str, Any]:
    where_clauses: List[str] = []
    if territory:
        where_clauses.append(f"AND territory = '{_escape_sql_literal(territory)}'")
    if status:
        where_clauses.append(f"AND status_indicator = '{_escape_sql_literal(status)}'")

    rows = _query_atlas_table(
        "atlas_kpi_daily_by_rep",
        where_clauses=where_clauses,
        order_by="status_indicator ASC, rep_name ASC",
    )
    return {"rows": rows, "count": len(rows), "report_date": rows[0].get("report_date") if rows else None}


@router.get("/by-territory", summary="Territory daily KPI summary from materialized Atlas tables")
async def get_territory_performance() -> Dict[str, Any]:
    rows = _query_atlas_table(
        "atlas_kpi_daily_by_territory",
        order_by="territory ASC",
    )
    return {"rows": rows, "count": len(rows), "report_date": rows[0].get("report_date") if rows else None}


@router.get("/revenue-gap", summary="Dollarized revenue gap decomposition — two-funnel model")
async def get_revenue_gap(
    period:         str           = Query("QTD"),
    start_date:     Optional[str] = Query(None),
    end_date:       Optional[str] = Query(None),
    market:         Optional[str] = Query(None),
    channel:        Optional[str] = Query(None),
    product_group:  Optional[str] = Query(None),
    product_family: Optional[str] = Query(None),
    product_genus:  Optional[str] = Query(None),
    fuel_source:    Optional[str] = Query(None),
    plan_version:   str           = Query("Plan"),
) -> Dict[str, Any]:
    filters = _get_filters(
        period, start_date, end_date,
        market, channel, product_group, product_family, product_genus,
        fuel_source, plan_version,
    )
    return await _svc.fetch_revenue_gap(filters)


@router.get("/qoq", summary="Quarter-over-quarter fair comparison (equivalent-day window)")
async def get_qoq_comparison(
    market:         Optional[str] = Query(None),
    channel:        Optional[str] = Query(None),
    product_group:  Optional[str] = Query(None),
    product_family: Optional[str] = Query(None),
    product_genus:  Optional[str] = Query(None),
    fuel_source:    Optional[str] = Query(None),
    plan_version:   str           = Query("Plan"),
) -> Dict[str, Any]:
    filters = _get_filters(
        market=market, channel=channel,
        product_group=product_group, product_family=product_family,
        product_genus=product_genus, fuel_source=fuel_source,
        plan_version=plan_version,
    )
    return await _svc.fetch_qoq_comparison(filters)


@router.get("/mom", summary="Month-over-month fair comparison (equivalent-day window)")
async def get_mom_comparison(
    market:         Optional[str] = Query(None),
    channel:        Optional[str] = Query(None),
    product_group:  Optional[str] = Query(None),
    product_family: Optional[str] = Query(None),
    product_genus:  Optional[str] = Query(None),
    fuel_source:    Optional[str] = Query(None),
    plan_version:   str           = Query("Plan"),
) -> Dict[str, Any]:
    filters = _get_filters(
        market=market, channel=channel,
        product_group=product_group, product_family=product_family,
        product_genus=product_genus, fuel_source=fuel_source,
        plan_version=plan_version,
    )
    return await _svc.fetch_mom_comparison(filters)


@router.get("/trend", summary="Quarterly or monthly KPI time series")
async def get_trend(
    grain:          str           = Query("quarterly", description="quarterly | monthly"),
    n_quarters:     int           = Query(6,           description="Number of quarters to look back (max 12)", ge=1, le=12),
    market:         Optional[str] = Query(None),
    channel:        Optional[str] = Query(None),
    product_group:  Optional[str] = Query(None),
    product_family: Optional[str] = Query(None),
    product_genus:  Optional[str] = Query(None),
    fuel_source:    Optional[str] = Query(None),
    plan_version:   str           = Query("Plan"),
) -> List[Dict[str, Any]]:
    if grain not in ("quarterly", "monthly"):
        grain = "quarterly"
    filters = _get_filters(
        market=market, channel=channel,
        product_group=product_group, product_family=product_family,
        product_genus=product_genus, fuel_source=fuel_source,
        plan_version=plan_version,
    )
    return await _svc.fetch_trend(grain, filters, n_quarters)


@router.get("/ai-insight", summary="AI-generated executive insight (Claude Sonnet 4 → Gemini Flash fallback)")
async def get_ai_insight(
    period:         str           = Query("QTD"),
    start_date:     Optional[str] = Query(None),
    end_date:       Optional[str] = Query(None),
    market:         Optional[str] = Query(None),
    channel:        Optional[str] = Query(None),
    product_group:  Optional[str] = Query(None),
    product_family: Optional[str] = Query(None),
    product_genus:  Optional[str] = Query(None),
    fuel_source:    Optional[str] = Query(None),
    plan_version:   str           = Query("Plan"),
) -> Dict[str, Any]:
    """
    Fetches KPI dashboard + revenue gap in parallel, sends them to
    databricks-claude-sonnet-4 (fallback: databricks-gemini-2-5-flash),
    and returns the generated executive insight.

    Response fields:
      insight       — the generated text (2 sentences + recommendation)
      kpi_data      — full KPI snapshot used to build the prompt
      gap_data      — revenue gap decomposition used to build the prompt
      prompt        — the exact prompt sent to the model
      fallback_used — true if rule-based summary was used (no LLM available)
    """
    filters = _get_filters(
        period, start_date, end_date,
        market, channel, product_group, product_family, product_genus,
        fuel_source, plan_version,
    )

    import asyncio
    kpi_data, gap_data = await asyncio.gather(
        _svc.fetch_kpi_dashboard(filters),
        _svc.fetch_revenue_gap(filters),
    )

    ai_result = await ai_service.generate_insight(kpi_data, gap_data)

    return {
        "insight":       ai_result["insight"],
        "kpi_data":      kpi_data,
        "gap_data":      gap_data,
        "prompt":        ai_result["prompt"],
        "fallback_used": ai_result["fallback_used"],
    }


@router.get("/filters", summary="Available filter dimension values")
async def get_filter_options() -> Dict[str, Any]:
    """
    Returns the valid values for every filter dimension.
    Used by the frontend to populate dropdowns.
    """
    return {
        "period_types":      ["QTD", "MTD", "YTD", "LAST_QUARTER", "CUSTOM"],
        "markets":           sorted(_VALID_MARKET),
        "channels":          sorted(_VALID_CHANNEL),
        "product_groups":    sorted(_VALID_PRODUCT_GROUP),
        "product_families":  sorted(_VALID_PRODUCT_FAMILY),
        "product_genera":    sorted(_VALID_PRODUCT_GENUS),
        "fuel_sources":      sorted(_VALID_FUEL_SOURCE),
        "plan_versions":     sorted(_VALID_PLAN_VERSION),
        "status_thresholds": {
            "exceeding_target": "≥ 100%",
            "watch_closely":    "85–99%",
            "action_required":  "< 85%",
        },
    }
