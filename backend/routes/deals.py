"""
routes/deals.py — Largest Open Deals
Data source: datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot

Endpoints:
  GET /api/deals/largest-open?limit=20
"""

import asyncio
import os
from datetime import datetime, date

from fastapi import APIRouter

from query_loader import load_query
from services.databricks_connection import execute_query, DATABRICKS_AVAILABLE

router = APIRouter(prefix="/api/deals", tags=["deals"])

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA  = os.getenv("DATABRICKS_SCHEMA",  "mdl_sales_analytics")
TABLE   = f"`{CATALOG}`.`{SCHEMA}`.`gaim_pipeline_daily_snapshot`"

_AVAILABLE = DATABRICKS_AVAILABLE and bool(os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN"))


def _quarter_end() -> str:
    today = datetime.now()
    q     = (today.month - 1) // 3
    m_end = (q + 1) * 3
    import calendar
    last_day = calendar.monthrange(today.year, m_end)[1]
    return datetime(today.year, m_end, last_day).strftime("%Y-%m-%d")


STAGE_ORDER = {
    "Prospecting": 1, "Qualification": 2, "Needs Analysis": 3,
    "Value Proposition": 4, "Perception Analysis": 5, "Proposal": 6,
    "Negotiation": 7, "Closed Won": 8, "Closed Lost": 9,
}


def _stage_category(stage: str) -> str:
    n = STAGE_ORDER.get(stage, 5)
    if n <= 2: return "early"
    if n <= 5: return "mid"
    return "late"


# ── Demo fallback ─────────────────────────────────────────────────────────────

def _demo_deals(limit: int = 20):
    import random
    random.seed(13)
    stages = list(STAGE_ORDER.keys())[:-2]
    channels = ["Enterprise", "Partner", "Mid-Market", "MSP"]
    q_end = _quarter_end()
    today = datetime.now().strftime("%Y-%m-%d")
    deals = []
    for i in range(1, limit + 1):
        amt       = random.randint(50_000, 3_000_000)
        stage     = random.choice(stages)
        close_str = q_end if random.random() > 0.35 else f"{datetime.now().year + (1 if random.random() > 0.6 else 0)}-{random.randint(1,12):02d}-28"
        slipped   = random.random() > 0.8
        deals.append({
            "rank":           i,
            "opportunity_id": f"OPP-{10000 + i}",
            "opportunity_name": f"Deal {chr(64 + (i % 26) + 1)} — {random.choice(['Renewal', 'Expansion', 'New Logo', 'Upsell'])}",
            "amount":         amt,
            "stage":          stage,
            "stage_category": _stage_category(stage),
            "close_date":     close_str,
            "in_quarter":     close_str <= q_end,
            "channel":        random.choice(channels),
            "owner":          f"AE {chr(64 + (i % 10) + 1)}.",
            "days_in_stage":  random.randint(3, 120),
            "slipped":        slipped,
        })
    deals.sort(key=lambda x: x["amount"], reverse=True)
    for i, d in enumerate(deals):
        d["rank"] = i + 1
    return deals


# ── Live query ────────────────────────────────────────────────────────────────

def _query_largest(limit: int) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    q_end = _quarter_end()
    sql = load_query("deals/largest_open", table=TABLE, today=today, q_end=q_end, limit=limit)
    rows = execute_query(sql)
    result = []
    for r in rows:
        stage = r.get("stage") or "Unknown"
        result.append({
            "rank":             int(r.get("rank") or 0),
            "opportunity_id":   r.get("opportunity_id") or "",
            "opportunity_name": r.get("opportunity_name") or "—",
            "amount":           float(r.get("amount") or 0),
            "stage":            stage,
            "stage_category":   _stage_category(stage),
            "close_date":       str(r.get("close_date") or ""),
            "in_quarter":       bool(r.get("in_quarter")),
            "channel":          r.get("channel") or "—",
            "owner":            r.get("owner") or "—",
            "days_in_stage":    int(r.get("days_in_stage") or 0),
            "slipped":          bool(r.get("slipped")),
        })
    return result


def _top_deal_insight(deals: list) -> str:
    if not deals:
        return ""
    top5_val = sum(d["amount"] for d in deals[:5])
    total    = sum(d["amount"] for d in deals)
    pct      = round(top5_val / total * 100) if total else 0
    top1     = deals[0]
    return (
        f"Your top 5 deals represent ${top5_val/1e6:.1f}M ({pct}% of total open pipeline). "
        f"If \"{top1['opportunity_name'][:40]}\" (${top1['amount']/1e6:.1f}M) slips, pipeline concentration risk increases significantly."
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/largest-open")
async def get_largest_open_deals(limit: int = 20):
    """Top open deals by pipeline value with AI concentration risk insight."""
    if _AVAILABLE:
        try:
            deals   = await asyncio.to_thread(_query_largest, limit)
            insight = _top_deal_insight(deals)
            return {"data": deals, "insight": insight, "source": "databricks"}
        except Exception as e:
            print(f"[deals/largest-open] Databricks error: {e}")

    deals   = _demo_deals(limit)
    insight = _top_deal_insight(deals)
    return {"data": deals, "insight": insight, "source": "demo"}
