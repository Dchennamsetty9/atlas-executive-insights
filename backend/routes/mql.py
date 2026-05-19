"""
routes/mql.py — MQL Analytics endpoints
Data source: datagroup_mdl.mdl_sales_analytics.gaim_mql_daily_snapshot

Endpoints:
  GET /api/mql/volume?period=daily|weekly|monthly
  GET /api/mql/conversion
  GET /api/mql/vs-target
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter

from query_loader import load_query
from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/mql", tags=["mql"])

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA  = os.getenv("DATABRICKS_SCHEMA",  "mdl_sales_analytics")
TABLE   = f"`{CATALOG}`.`{SCHEMA}`.`gaim_mql_daily_snapshot`"

_on_databricks = bool(os.getenv("DATABRICKS_HOST"))
_force_live    = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
_AVAILABLE     = token_available() and (_on_databricks or _force_live)


def _quarter_start() -> str:
    today = datetime.now()
    q = (today.month - 1) // 3
    return datetime(today.year, q * 3 + 1, 1).strftime("%Y-%m-%d")


# ── Demo fallback data ────────────────────────────────────────────────────────

def _demo_volume():
    base = datetime.now()
    rows = []
    for i in range(60, 0, -1):
        d = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({"date": d, "mql_count": 45 + (i % 15) * 3, "trial_count": 12 + (i % 8)})
    return rows


def _demo_conversion():
    base = datetime.now()
    rows = []
    for i in range(60, 0, -1):
        d = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({"date": d, "conversion_rate": round(0.18 - (i % 5) * 0.005 + 0.01, 3)})
    return rows


def _demo_vs_target():
    base = datetime.now()
    rows = []
    for i in range(30, 0, -1):
        d = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({
            "date": d,
            "actual": 40 + (i % 12) * 4,
            "target": 55,
            "pct_to_target": round((40 + (i % 12) * 4) / 55 * 100, 1),
        })
    return rows


# ── Live query helpers ────────────────────────────────────────────────────────

def _query_volume(period: str) -> list:
    trunc = {"daily": "DAY", "weekly": "WEEK", "monthly": "MONTH"}.get(period, "DAY")
    sql = load_query("mql/volume", table=TABLE, trunc=trunc, quarter_start=_quarter_start())
    rows = execute_query(sql)
    return [{"date": str(r["date"]), "mql_count": r["mql_count"], "trial_count": r["trial_count"]} for r in rows]


def _query_conversion() -> list:
    sql = load_query("mql/conversion", table=TABLE, quarter_start=_quarter_start())
    rows = execute_query(sql)
    return [{"date": str(r["date"]), "conversion_rate": float(r.get("conversion_rate") or 0)} for r in rows]


def _query_vs_target() -> list:
    sql = load_query("mql/vs_target", table=TABLE, quarter_start=_quarter_start())
    rows = execute_query(sql)
    out = []
    for r in rows:
        actual = float(r.get("actual") or 0)
        target = float(r.get("target") or 55)
        out.append({
            "date": str(r["date"]),
            "actual": actual,
            "target": target,
            "pct_to_target": round(actual / target * 100, 1) if target else None,
        })
    return out


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/volume")
async def get_mql_volume(period: str = "daily"):
    """MQL count over time. period = daily | weekly | monthly"""
    if _AVAILABLE:
        try:
            rows = await asyncio.to_thread(_query_volume, period)
            return {"data": rows, "period": period, "source": "databricks"}
        except Exception as e:
            print(f"[mql/volume] Databricks error: {e}")
    return {"data": _demo_volume(), "period": period, "source": "demo"}


@router.get("/conversion")
async def get_mql_conversion():
    """MQL-to-Opp conversion rate trend for current quarter."""
    if _AVAILABLE:
        try:
            rows = await asyncio.to_thread(_query_conversion)
            return {"data": rows, "source": "databricks"}
        except Exception as e:
            print(f"[mql/conversion] Databricks error: {e}")

    # AI insight about trend direction
    data = _demo_conversion()
    recent = [r["conversion_rate"] for r in data[-7:]]
    trend = "declining" if len(recent) > 1 and recent[-1] < recent[0] else "stable"
    insight = (
        "Conversion rate is declining — lead quality may be dropping or sales follow-through on MQLs is weakening."
        if trend == "declining"
        else "MQL-to-Opp conversion is stable this quarter."
    )
    return {"data": data, "trend": trend, "insight": insight, "source": "demo"}


@router.get("/vs-target")
async def get_mql_vs_target():
    """MQL actual vs daily target."""
    if _AVAILABLE:
        try:
            rows = await asyncio.to_thread(_query_vs_target)
            return {"data": rows, "source": "databricks"}
        except Exception as e:
            print(f"[mql/vs-target] Databricks error: {e}")
    return {"data": _demo_vs_target(), "source": "demo"}
