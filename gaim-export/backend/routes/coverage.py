"""
routes/coverage.py — Pipeline Coverage with YoY Comparison
Data source: datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot

Coverage = Open Pipeline (in-quarter close date) ÷ (Plan Target - QTD Booked)
Healthy range: 2–4x  |  Below 2x = risk

Endpoints:
  GET /api/coverage/current  — current coverage ratio + components
  GET /api/coverage/yoy      — same time last year comparison
  GET /api/coverage/trend    — daily coverage over current quarter
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter

from query_loader import load_query
from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/coverage", tags=["coverage"])

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA  = os.getenv("DATABRICKS_SCHEMA",  "mdl_sales_analytics")

_on_databricks = bool(os.getenv("DATABRICKS_HOST"))
_force_live    = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
_AVAILABLE     = token_available() and (_on_databricks or _force_live)


def _quarter_start(year_offset: int = 0) -> str:
    today = datetime.now()
    year  = today.year - year_offset
    q     = (today.month - 1) // 3
    return datetime(year, q * 3 + 1, 1).strftime("%Y-%m-%d")


def _quarter_end(year_offset: int = 0) -> str:
    today = datetime.now()
    year  = today.year - year_offset
    q     = (today.month - 1) // 3
    m_end = (q + 1) * 3
    import calendar
    last_day = calendar.monthrange(year, m_end)[1]
    return datetime(year, m_end, last_day).strftime("%Y-%m-%d")


def _today(year_offset: int = 0) -> str:
    d = datetime.now()
    if year_offset:
        return d.replace(year=d.year - year_offset).strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


# ── Demo fallback ─────────────────────────────────────────────────────────────

def _demo_current():
    open_pipeline = 28_500_000
    plan_target   = 42_000_000
    qtd_booked    = 12_300_000
    remaining     = max(plan_target - qtd_booked, 1)
    coverage      = round(open_pipeline / remaining, 2)
    same_q_pct    = 0.63
    return {
        "coverage_ratio":      coverage,
        "open_pipeline":       open_pipeline,
        "same_q_pipeline":     int(open_pipeline * same_q_pct),
        "not_same_q_pipeline": int(open_pipeline * (1 - same_q_pct)),
        "plan_target":         plan_target,
        "qtd_booked":          qtd_booked,
        "remaining_target":    remaining,
        "same_q_pct":          same_q_pct,
        "status":              "risk" if coverage < 2 else "healthy" if coverage <= 4 else "excess",
        "insight": (
            f"Coverage at {coverage:.1f}x is {'below' if coverage < 2 else 'within'} the healthy range (2–4x). "
            + (f"You need ${max(0, remaining - open_pipeline)/1e6:.1f}M more pipeline or accelerated close rates to hit target." if coverage < 2 else "Pipeline is sufficient to support the quarter target.")
        ),
    }


def _demo_yoy():
    current = _demo_current()
    return {
        "current":        current,
        "prior_year":     {
            "coverage_ratio":  2.8,
            "open_pipeline":   24_000_000,
            "qtd_booked":      10_500_000,
            "remaining_target": 31_500_000,
        },
        "coverage_yoy_delta": round(current["coverage_ratio"] - 2.8, 2),
        "pipeline_yoy_pct":   round((current["open_pipeline"] - 24_000_000) / 24_000_000 * 100, 1),
    }


def _demo_trend():
    base   = datetime.now()
    q_start = _quarter_start()
    rows   = []
    days   = (base - datetime.strptime(q_start, "%Y-%m-%d")).days
    for i in range(max(days, 1), 0, -1):
        d       = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        cov     = round(3.2 - i * 0.015 + (i % 7) * 0.05, 2)
        rows.append({"date": d, "coverage_ratio": max(1.0, cov)})
    return rows


# ── Live queries ──────────────────────────────────────────────────────────────

def _query_current(year_offset: int = 0) -> dict:
    snap_date = _today(year_offset)
    q_start   = _quarter_start(year_offset)
    q_end     = _quarter_end(year_offset)
    sql = load_query(
        "coverage/current",
        catalog=CATALOG, schema=SCHEMA,
        snap_date=snap_date, q_start=q_start, q_end=q_end,
    )
    rows = execute_query(sql)
    r = rows[0] if rows else {}
    open_p   = float(r.get("open_pipeline") or 0)
    same_q   = float(r.get("same_q_pipeline") or 0)
    not_same = float(r.get("not_same_q_pipeline") or 0)
    target   = float(r.get("plan_target") or 1)
    booked   = float(r.get("qtd_booked") or 0)
    remaining = max(target - booked, 1)
    coverage  = round(same_q / remaining, 2)
    same_q_pct = round(same_q / open_p, 2) if open_p else 0

    return {
        "coverage_ratio":      coverage,
        "open_pipeline":       open_p,
        "same_q_pipeline":     same_q,
        "not_same_q_pipeline": not_same,
        "plan_target":         target,
        "qtd_booked":          booked,
        "remaining_target":    remaining,
        "same_q_pct":          same_q_pct,
        "status":              "risk" if coverage < 2 else "healthy" if coverage <= 4 else "excess",
        "insight": (
            f"Coverage at {coverage:.1f}x is {'below' if coverage < 2 else 'within'} the healthy range (2–4x). "
            + (f"You need ${max(0, remaining - same_q)/1e6:.1f}M more in-quarter pipeline to hit target." if coverage < 2 else "Pipeline is sufficient.")
        ),
    }


def _query_trend() -> list:
    q_start = _quarter_start()
    q_end   = _quarter_end()
    sql = load_query(
        "coverage/trend",
        catalog=CATALOG, schema=SCHEMA,
        q_start=q_start, q_end=q_end,
    )
    rows = execute_query(sql)
    return [{"date": str(r["snapshot_date"]), "coverage_ratio": float(r.get("coverage_ratio") or 0)} for r in rows]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/current")
async def get_coverage_current():
    """Current pipeline coverage ratio with components and AI insight."""
    if _AVAILABLE:
        try:
            data = await asyncio.to_thread(_query_current, 0)
            return {**data, "source": "databricks"}
        except Exception as e:
            print(f"[coverage/current] Databricks error: {e}")
    return {**_demo_current(), "source": "demo"}


@router.get("/yoy")
async def get_coverage_yoy():
    """Current coverage vs same point in time last year."""
    if _AVAILABLE:
        try:
            current   = await asyncio.to_thread(_query_current, 0)
            prior     = await asyncio.to_thread(_query_current, 1)
            delta     = round(current["coverage_ratio"] - prior["coverage_ratio"], 2)
            pipe_yoy  = round((current["open_pipeline"] - prior["open_pipeline"]) / max(prior["open_pipeline"], 1) * 100, 1)
            return {
                "current":            current,
                "prior_year":         prior,
                "coverage_yoy_delta": delta,
                "pipeline_yoy_pct":   pipe_yoy,
                "source": "databricks",
            }
        except Exception as e:
            print(f"[coverage/yoy] Databricks error: {e}")
    return {**_demo_yoy(), "source": "demo"}


@router.get("/trend")
async def get_coverage_trend():
    """Daily coverage ratio trend for the current quarter."""
    if _AVAILABLE:
        try:
            rows = await asyncio.to_thread(_query_trend)
            return {"data": rows, "source": "databricks"}
        except Exception as e:
            print(f"[coverage/trend] Databricks error: {e}")
    return {"data": _demo_trend(), "source": "demo"}
