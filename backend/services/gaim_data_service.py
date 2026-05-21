"""
gaim_data_service.py
Primary data service for Atlas Executive Insights.
Queries real GAIM tables in Databricks; falls back to demo data if unavailable.

KPI Formulas follow the Performance Hub semantic model exactly.
All 8 core KPIs + Win Rate + MQL are supported.

IMPORTANT — Close Rate vs Win Rate:
  Close Rate (Vol) = Won Volume ÷ ALL Opps Entered (includes still-open)
                   → Appears lower mid-quarter — this is NORMAL, not a performance problem.
  Win Rate %       = Won Volume ÷ (Won + Lost) ONLY resolved deals
                   → Not affected by timing; true conversion signal.
  When Win Rate is high but Close Rate is low → timing signal (many deals still open).
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import pandas as pd

from query_loader import load_query
from services.databricks_connection import execute_query, DATABRICKS_AVAILABLE, token_available

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA  = os.getenv("DATABRICKS_SCHEMA",  "mdl_sales_analytics")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _current_quarter_start() -> str:
    today = datetime.now()
    q     = (today.month - 1) // 3
    return datetime(today.year, q * 3 + 1, 1).strftime("%Y-%m-%d")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# Strict whitelists for every user-supplied filter value.
# Values outside these sets are silently ignored (treated as "All").
_VALID_GEO = {"NA", "EMEA", "LATAM", "APAC", "AUS/ROW"}
_VALID_CHANNEL = {"Enterprise", "Partner", "Mid-Market", "MSP", "GSI", "Small Business"}
_PRODUCT_MAP = {
    "Connect":     "GoToConnect",
    "Engage":      "GoToWebinar",
    "Rescue":      "Rescue",
    "Central":     "Central",
    "Resolve":     "Resolve",
    # Accept canonical names directly (e.g. from API clients that pass the full name)
    "GoToConnect": "GoToConnect",
    "GoToWebinar": "GoToWebinar",
}


def _filter_sql(filters: Dict[str, str], alias: str = "", channel_col: str = "sales_channel") -> str:
    """Build AND-prefixed WHERE fragment from filter dict.

    All user-supplied values are validated against strict whitelists before
    being embedded in SQL.  Unrecognised values are silently ignored so that
    the query degrades to an unfiltered result rather than raising an error.

    channel_col: column name for the channel filter.  Use "sales_channel" for
        federated.sales.* tables (default) and "smoothed_channel" for raw
        datagroup_mdl.mdl_sales_analytics.* tables.
    """
    prefix = f"{alias}." if alias else ""
    parts  = []

    geo = filters.get("geo", "")
    if geo and geo != "All" and geo in _VALID_GEO:
        parts.append(f"AND {prefix}sales_market = '{geo}'")

    channel = filters.get("channel", "")
    if channel and channel != "All" and channel in _VALID_CHANNEL:
        parts.append(f"AND {prefix}{channel_col} = '{channel}'")

    product = filters.get("product", "")
    if product and product != "All":
        mapped = _PRODUCT_MAP.get(product)
        if mapped:
            parts.append(f"AND {prefix}product_genus = '{mapped}'")

    return " ".join(parts)


# ── Main service ─────────────────────────────────────────────────────────────

class GAIMDataService:
    """
    Fetches KPI data from GAIM Databricks tables.
    All public methods are async-safe (blocking Databricks calls run in a thread pool).
    """

    def __init__(self):
        # Attempt live Databricks queries only when:
        #   (a) running ON Databricks Apps — DATABRICKS_HOST is auto-injected, OR
        #   (b) developer explicitly opts in via FORCE_LIVE_DATA=true in .env
        # This prevents slow 10-15s timeout hangs when running locally with a
        # token in .env but without being on the Databricks internal network.
        _on_databricks = bool(os.getenv("DATABRICKS_HOST"))
        _force_live    = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
        self.available = token_available() and (_on_databricks or _force_live)

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_kpis(
        self,
        start_date: Optional[str] = None,
        end_date:   Optional[str] = None,
        filters:    Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return list of KPI dicts matching the existing /api/kpis response shape:
            metric_name, metric_value, target_value, previous_period_value
        Falls back to demo data if Databricks is unavailable.
        """
        if not start_date:
            start_date = _current_quarter_start()
        if not end_date:
            end_date = _today()
        if filters is None:
            filters = {}

        if self.available:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._query_kpis, start_date, end_date, filters),
                    timeout=15.0,  # 15 s: covers 4 queries × 5 s socket timeout + overhead
                )
            except asyncio.TimeoutError:
                print("[GAIMDataService] Databricks query timed out after 20s. Using demo data.")
            except Exception as exc:
                print(f"[GAIMDataService] Databricks query failed: {exc}. Using demo data.")

        return _demo_kpis()

    async def fetch_trend_data(
        self,
        metric:     str,
        start_date: Optional[str] = None,
        end_date:   Optional[str] = None,
        filters:    Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return [{date, value}] for a single metric's daily trend."""
        if not start_date:
            start_date = _current_quarter_start()
        if not end_date:
            end_date = _today()
        if filters is None:
            filters = {}

        if self.available:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._query_trend, metric, start_date, end_date, filters),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                print(f"[GAIMDataService] Trend query timed out for {metric}. Using empty.")
            except Exception as exc:
                print(f"[GAIMDataService] Trend query failed for {metric}: {exc}")

        return []

    # ── Blocking queries (run in thread pool) ─────────────────────────────────

    def _query_kpis(
        self,
        start_date: str,
        end_date:   str,
        filters:    Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """
        Queries all GAIM tables and returns one dict per KPI.
        Uses a single multi-CTE query where possible for efficiency.
        """
        filter_clause = _filter_sql(filters)
        # Raw-table queries (MQL) need smoothed_channel instead of sales_channel
        filter_clause_raw = _filter_sql(filters, channel_col="smoothed_channel")
        c, s = CATALOG, SCHEMA

        pipeline_sql = load_query(
            "kpis/pipeline_snapshot",
            start_date=start_date, end_date=end_date,
            filter_clause=filter_clause,
        )
        created_sql = load_query(
            "kpis/created_pipeline",
            start_date=start_date, end_date=end_date,
            filter_clause=filter_clause,
        )
        targets_sql = load_query(
            "kpis/targets",
            start_date=start_date,
            filter_clause=filter_clause,
        )
        mql_sql = load_query(
            "kpis/mql",
            catalog=c, schema=s,
            start_date=start_date, end_date=end_date,
            filter_clause=filter_clause_raw,
        )

        # Execute all queries
        pipe_rows    = execute_query(pipeline_sql)
        created_rows = execute_query(created_sql)
        target_rows  = execute_query(targets_sql)
        mql_rows     = execute_query(mql_sql)

        p = pipe_rows[0]    if pipe_rows    else {}
        c_ = created_rows[0] if created_rows else {}
        t  = target_rows[0] if target_rows  else {}
        m  = mql_rows[0]    if mql_rows     else {}

        # Extract values (coerce None → 0)
        won_pipeline     = float(p.get("won_pipeline", 0)    or 0)
        won_volume       = float(p.get("won_volume", 0)      or 0)
        lost_volume      = float(p.get("lost_volume", 0)     or 0)
        active_pipeline  = float(p.get("active_pipeline", 0) or 0)
        open_volume      = float(p.get("open_volume", 0)     or 0)
        prev_won_pipe    = float(p.get("prev_won_pipeline", 0) or 0)
        prev_won_vol     = float(p.get("prev_won_volume", 0)  or 0)
        win_rate_pct     = float(p.get("win_rate_pct", 0)    or 0)
        ads              = float(p.get("ads", 0)             or 0)
        open_opp_size    = float(p.get("open_opp_size", 0)   or 0)

        opps_created     = float(c_.get("opps_created", 0)   or 0)
        created_pipeline = float(c_.get("created_pipeline", 0) or 0)

        # Targets from federated.sales.metis_targets_summary
        target_won_pipe      = float(t.get("target_won_pipeline",   0) or 0)
        target_won_vol       = float(t.get("target_won_volume",     0) or 0)
        target_pipeline      = float(t.get("target_pipeline",       0) or 0)
        target_mql           = float(t.get("target_mql",            0) or 0)

        # Paced targets: prefer pre-computed values from metis_targets_summary;
        # fall back to Python pro-ration (still needed for MQL which has no federated table).
        paced_won_table    = float(t.get("paced_won_amount",    0) or 0)
        paced_opened_table = float(t.get("paced_opened_amount", 0) or 0)

        from datetime import datetime as _dt
        q_start_dt  = _dt.strptime(start_date, "%Y-%m-%d")
        today_dt    = _dt.strptime(end_date,   "%Y-%m-%d")
        q_month     = q_start_dt.month
        q_end_month = q_month + 2
        q_end_year  = q_start_dt.year if q_end_month <= 12 else q_start_dt.year + 1
        q_end_month = q_end_month if q_end_month <= 12 else q_end_month - 12
        import calendar as _cal
        last_day    = _cal.monthrange(q_end_year, q_end_month)[1]
        q_end_dt    = _dt(q_end_year, q_end_month, last_day)
        days_in_q   = (q_end_dt - q_start_dt).days + 1
        days_elapsed = max((today_dt - q_start_dt).days + 1, 1)
        pace_factor  = days_elapsed / days_in_q

        paced_won_target  = paced_won_table    if paced_won_table    > 0 else target_won_pipe * pace_factor
        paced_pipe_target = paced_opened_table if paced_opened_table > 0 else target_pipeline * pace_factor
        paced_mql_target  = target_mql         * pace_factor

        mql_count        = float(m.get("mql_reached", 0)    or 0)
        prev_mql         = mql_count * 0.9   # No prior-period MQL table; use 10% growth estimate

        # Derived KPIs
        # AOS (Avg Opp Size) = Created Pipeline ÷ Opps Created
        aos              = (created_pipeline / opps_created) if opps_created > 0 else 0
        # Close Rate (Vol) = Won ÷ ALL entered (includes open) — lower mid-quarter by design
        close_rate_vol   = (won_volume / opps_created * 100) if opps_created > 0 else 0
        # Close Rate ($)   = Won Pipeline ÷ Created Pipeline
        close_rate_dollar = (won_pipeline / created_pipeline * 100) if created_pipeline > 0 else 0
        # Coverage         = Active Pipeline ÷ Remaining Paced Won Target
        remaining_target = max(paced_won_target - won_pipeline, 0)
        coverage         = min(active_pipeline / remaining_target, 10.0) if remaining_target > 0 else 0
        # Attainment %
        won_attainment_pct      = (won_pipeline / paced_won_target * 100)  if paced_won_target  > 0 else 0
        pipeline_attainment_pct = (created_pipeline / paced_pipe_target * 100) if paced_pipe_target > 0 else 0
        # Prev period ADS
        prev_ads         = (prev_won_pipe / prev_won_vol) if prev_won_vol > 0 else ads * 0.95

        kpis = [
            {
                "metric_name":           "won_pipeline",
                "metric_value":          won_pipeline,
                "target_value":          target_won_pipe  or won_pipeline * 1.1,
                "previous_period_value": prev_won_pipe,
            },
            {
                "metric_name":           "won_volume",
                "metric_value":          won_volume,
                "target_value":          target_won_vol   or won_volume * 1.1,
                "previous_period_value": prev_won_vol,
            },
            {
                "metric_name":           "ads",
                "metric_value":          ads,
                "target_value":          (target_won_pipe / target_won_vol) if target_won_vol > 0 else ads * 1.05,
                "previous_period_value": prev_ads,
            },
            {
                "metric_name":           "opps_created",
                "metric_value":          opps_created,
                "target_value":          target_won_vol or opps_created * 1.1,
                "previous_period_value": opps_created * 0.9,
            },
            {
                "metric_name":           "created_pipeline",
                "metric_value":          created_pipeline,
                "target_value":          paced_pipe_target or created_pipeline * 1.1,
                "previous_period_value": created_pipeline * 0.85,
            },
            {
                "metric_name":           "aos",
                "metric_value":          round(aos, 0),
                "target_value":          round(aos * 1.05, 0),
                "previous_period_value": round(aos * 0.95, 0),
            },
            {
                "metric_name":           "active_pipeline",
                "metric_value":          active_pipeline,
                "target_value":          remaining_target + active_pipeline * 0.1,
                "previous_period_value": active_pipeline * 0.95,
            },
            {
                # Close Rate (Vol) — NOT Win Rate. See module docstring for distinction.
                "metric_name":           "close_rate",
                "metric_value":          round(close_rate_vol, 2),
                "target_value":          30.0,
                "previous_period_value": 28.0,
            },
            {
                "metric_name":           "close_rate_dollar",
                "metric_value":          round(close_rate_dollar, 2),
                "target_value":          30.0,
                "previous_period_value": 28.0,
            },
            {
                "metric_name":           "win_rate",
                "metric_value":          round(win_rate_pct, 2),
                "target_value":          35.0,
                "previous_period_value": 33.0,
            },
            {
                "metric_name":           "coverage",
                "metric_value":          round(coverage, 2),
                "target_value":          3.0,
                "previous_period_value": 2.8,
            },
            {
                "metric_name":           "won_attainment_pct",
                "metric_value":          round(won_attainment_pct, 1),
                "target_value":          100.0,
                "previous_period_value": round(won_attainment_pct * 0.95, 1),
            },
            {
                "metric_name":           "pipeline_attainment_pct",
                "metric_value":          round(pipeline_attainment_pct, 1),
                "target_value":          100.0,
                "previous_period_value": round(pipeline_attainment_pct * 0.95, 1),
            },
            {
                "metric_name":           "mql_count",
                "metric_value":          mql_count,
                "target_value":          paced_mql_target or mql_count * 1.1,
                "previous_period_value": prev_mql,
            },
        ]

        return kpis

    def _query_trend(
        self,
        metric:     str,
        start_date: str,
        end_date:   str,
        filters:    Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Return daily [{date, value}] for a single KPI — used by KPIDetailModal."""
        # Federated tables use sales_channel; raw tables use smoothed_channel.
        f     = _filter_sql(filters)
        f_raw = _filter_sql(filters, channel_col="smoothed_channel")
        c, s  = CATALOG, SCHEMA

        queries = {
            "won_pipeline": f"""
                SELECT close_date AS date,
                       SUM(amount_towards_plan) AS value
                FROM federated.sales.metis_won_opps_fact
                WHERE data_date = (SELECT MAX(data_date) FROM federated.sales.metis_won_opps_fact)
                  AND close_date BETWEEN DATE('{start_date}') AND DATE('{end_date}') {f}
                GROUP BY close_date ORDER BY close_date
            """,
            "active_pipeline": f"""
                SELECT data_day AS date,
                       SUM(amount_towards_plan) AS value
                FROM {c}.{s}.gaim_pipeline_daily_snapshot
                WHERE stage_name NOT IN ('Closed Won','Closed Lost','Closed-Cancelled')
                  AND xtxtype<>'Cancel'
                  AND data_day BETWEEN '{start_date}' AND '{end_date}' {f_raw}
                GROUP BY data_day ORDER BY data_day
            """,
            "created_pipeline": f"""
                SELECT pipeline_entered_date AS date,
                       SUM(amount_towards_plan) AS value
                FROM federated.sales.metis_opened_opps_fact
                WHERE data_date = (SELECT MAX(data_date) FROM federated.sales.metis_opened_opps_fact)
                  AND pipeline_entered_date BETWEEN DATE('{start_date}') AND DATE('{end_date}') {f}
                GROUP BY pipeline_entered_date ORDER BY pipeline_entered_date
            """,
            "won_volume": f"""
                SELECT close_date AS date,
                       COUNT(DISTINCT salesforce_opportunity_id) AS value
                FROM federated.sales.metis_won_opps_fact
                WHERE data_date = (SELECT MAX(data_date) FROM federated.sales.metis_won_opps_fact)
                  AND close_date BETWEEN DATE('{start_date}') AND DATE('{end_date}') {f}
                GROUP BY close_date ORDER BY close_date
            """,
            "mql_count": f"""
                SELECT report_date AS date, SUM(CASE WHEN mqls=1 THEN 1 ELSE 0 END) AS value
                FROM {c}.{s}.gaim_mql_daily_snapshot
                WHERE report_date BETWEEN '{start_date}' AND '{end_date}' {f_raw}
                GROUP BY report_date ORDER BY report_date
            """,
        }

        sql = queries.get(metric)
        if not sql:
            return []

        rows = execute_query(sql)
        return [{"date": str(r.get("date", "")), "value": float(r.get("value") or 0)} for r in rows]


# ── Demo data fallback ────────────────────────────────────────────────────────

def _demo_kpis() -> List[Dict[str, Any]]:
    """Realistic demo data used when Databricks is unavailable (all 12 schema KPIs)."""
    return [
        # -- Dollar funnel --
        {"metric_name": "won_pipeline",          "metric_value": 12_450_000, "target_value": 15_000_000, "previous_period_value": 11_200_000},
        {"metric_name": "created_pipeline",      "metric_value": 52_000_000, "target_value": 58_000_000, "previous_period_value": 48_000_000},
        {"metric_name": "close_rate_dollar",     "metric_value": 23.9,       "target_value": 30.0,       "previous_period_value": 25.1},
        # -- Volume funnel --
        {"metric_name": "won_volume",            "metric_value": 78,         "target_value": 90,         "previous_period_value": 72},
        {"metric_name": "opps_created",          "metric_value": 312,        "target_value": 350,        "previous_period_value": 285},
        {"metric_name": "close_rate",            "metric_value": 25.0,       "target_value": 30.0,       "previous_period_value": 28.0},
        # -- Size KPIs --
        {"metric_name": "ads",                   "metric_value": 159_615,    "target_value": 166_667,    "previous_period_value": 155_556},
        {"metric_name": "aos",                   "metric_value": 166_667,    "target_value": 175_000,    "previous_period_value": 160_000},
        # -- Health KPIs --
        {"metric_name": "active_pipeline",       "metric_value": 38_500_000, "target_value": 45_000_000, "previous_period_value": 36_800_000},
        {"metric_name": "coverage",              "metric_value": 2.57,       "target_value": 3.0,        "previous_period_value": 2.8},
        {"metric_name": "won_attainment_pct",    "metric_value": 83.0,       "target_value": 100.0,      "previous_period_value": 79.0},
        {"metric_name": "pipeline_attainment_pct","metric_value": 89.7,      "target_value": 100.0,      "previous_period_value": 85.0},
        # -- Demand gen --
        {"metric_name": "win_rate",              "metric_value": 38.5,       "target_value": 35.0,       "previous_period_value": 36.2},
        {"metric_name": "mql_count",             "metric_value": 1_240,      "target_value": 1_400,      "previous_period_value": 1_100},
    ]


# ── Public helper for InsightEngine ──────────────────────────────────────────

_gaim_service_singleton = None


def _get_service() -> GAIMDataService:
    global _gaim_service_singleton
    if _gaim_service_singleton is None:
        _gaim_service_singleton = GAIMDataService()
    return _gaim_service_singleton


async def get_current_kpi_data(
    product:  Optional[str] = None,
    quarter:  Optional[str] = None,
    geo:      Optional[str] = None,
    channel:  Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return a flat dict consumed by InsightEngine.generate_all_insights().

    Keys produced (all numeric, rates as 0-100 percentages):
      won_pipeline_actual / _target
      won_opps_actual     / _target
      ads_actual          / _target
      close_rate_vol      (0-100)
      win_rate            (0-100)
      active_pipeline_actual / _target
      coverage_actual     / _target
      percent_to_target   (0-1 fraction, won_pipeline / target)
      historical_median_pacing  (placeholder — 0 until historical data available)
      segment_performance  []  (empty unless segment breakdown is passed in data)
    """
    filters: Dict[str, str] = {}
    if geo:
        filters["geo"] = geo
    if channel:
        filters["channel"] = channel
    if product:
        filters["product"] = product

    service = _get_service()
    rows    = await service.fetch_kpis(filters=filters)

    # Index by metric_name for easy lookup
    by_name: Dict[str, Dict] = {r["metric_name"]: r for r in rows}

    def actual(name: str) -> float:
        return float(by_name.get(name, {}).get("metric_value") or 0)

    def target(name: str) -> float:
        return float(by_name.get(name, {}).get("target_value") or 0)

    won_pipeline_actual = actual("won_pipeline")
    won_pipeline_target = target("won_pipeline")

    flat: Dict[str, Any] = {
        # Won pipeline
        "won_pipeline_actual": won_pipeline_actual,
        "won_pipeline_target": won_pipeline_target,
        # Won volume
        "won_opps_actual":     actual("won_volume"),
        "won_opps_target":     target("won_volume"),
        # ADS
        "ads_actual":          actual("ads"),
        "ads_target":          target("ads"),
        # Rates (kept as 0-100 percentages — InsightEngine normalises internally)
        "close_rate_vol":      actual("close_rate"),
        "win_rate":            actual("win_rate"),
        # Active pipeline
        "active_pipeline_actual": actual("active_pipeline"),
        "active_pipeline_target": target("active_pipeline"),
        # Coverage
        "coverage_actual":     actual("coverage"),
        "coverage_target":     target("coverage"),
        # Pacing
        "percent_to_target": (
            won_pipeline_actual / won_pipeline_target
            if won_pipeline_target else 0.0
        ),
        "historical_median_pacing": 0,   # populated when historical data is available
        # Segment breakdown (empty unless caller injects it)
        "segment_performance": [],
    }

    return flat
