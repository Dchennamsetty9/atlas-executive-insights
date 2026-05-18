"""
routes/pipeline_segments.py — Pipeline Analytics by Segment
Data source: datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot

Endpoints:
  GET /api/pipeline/segments?dimension=channel|geo|fuel_mix&compare=yoy|qoq
  GET /api/pipeline/segment-insights
"""

import asyncio
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter

from query_loader import load_query
from services.databricks_connection import execute_query, DATABRICKS_AVAILABLE

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA  = os.getenv("DATABRICKS_SCHEMA",  "mdl_sales_analytics")
TABLE   = f"`{CATALOG}`.`{SCHEMA}`.`gaim_pipeline_daily_snapshot`"

_AVAILABLE = DATABRICKS_AVAILABLE and bool(os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN"))

DIMENSION_COLUMNS = {
    "channel":  "smoothed_channel",
    "geo":      "sales_market",
    "fuel_mix": "fuel_mix",
    "product":  "product_genus",
    "purchase":  "purchase_type",
}


def _quarter_dates(offset_years: int = 0):
    today = datetime.now()
    year  = today.year - offset_years
    q     = (today.month - 1) // 3
    q_start = datetime(year, q * 3 + 1, 1).strftime("%Y-%m-%d")
    q_end   = today.strftime("%Y-%m-%d").replace(str(today.year), str(year))
    return q_start, q_end


# ── Demo fallback ─────────────────────────────────────────────────────────────

def _demo_segments(dimension: str):
    segments = {
        "channel":  ["Enterprise", "Partner", "Mid-Market", "MSP", "Small Business"],
        "geo":      ["NA", "EMEA", "LATAM", "APAC"],
        "fuel_mix": ["Marketing", "BDR", "AE", "Partner"],
        "product":  ["GoToConnect", "Rescue", "Central", "Resolve", "GoToWebinar"],
        "purchase": ["Expansion", "New", "Non-Recurring"],
    }.get(dimension, ["Segment A", "Segment B", "Segment C"])

    import random
    random.seed(42)
    results = []
    for seg in segments:
        current_val  = random.randint(800_000, 5_000_000)
        current_vol  = random.randint(40, 200)
        prior_val    = int(current_val * random.uniform(0.75, 1.25))
        prior_vol    = int(current_vol * random.uniform(0.75, 1.25))
        results.append({
            "segment":      seg,
            "current_value": current_val,
            "current_volume": current_vol,
            "prior_value":  prior_val,
            "prior_volume": prior_vol,
            "value_yoy_pct": round((current_val - prior_val) / prior_val * 100, 1),
            "volume_yoy_pct": round((current_vol - prior_vol) / prior_vol * 100, 1),
            "avg_deal_size": round(current_val / current_vol),
        })
    return results


# ── Live query ────────────────────────────────────────────────────────────────

def _query_segments(dimension: str, compare: str) -> list:
    col       = DIMENSION_COLUMNS.get(dimension, "smoothed_channel")
    today     = datetime.now()
    q         = (today.month - 1) // 3
    q_end     = today.strftime("%Y-%m-%d")

    years_ago    = 1 if compare == "yoy" else 0
    month_shift  = 3 if compare == "qoq" else 0
    prior_year   = today.year - years_ago
    prior_q_mon  = (q * 3 + 1) - month_shift
    if prior_q_mon < 1:
        prior_q_mon += 12
        prior_year  -= 1
    prior_start  = datetime(prior_year, prior_q_mon, 1).strftime("%Y-%m-%d")
    prior_end    = q_end.replace(str(today.year), str(prior_year)) if years_ago else datetime(today.year, q * 3 + 1, 1).strftime("%Y-%m-%d")

    sql = load_query(
        "pipeline/segments",
        table=TABLE,
        col=col,
        q_end=q_end,
        prior_start=prior_start,
        prior_end=prior_end,
    )
    rows = execute_query(sql)
    return [
        {
            "segment":        r["segment"],
            "current_value":  float(r.get("current_value") or 0),
            "current_volume": int(r.get("current_volume") or 0),
            "prior_value":    float(r.get("prior_value") or 0),
            "prior_volume":   int(r.get("prior_volume") or 0),
            "value_yoy_pct":  float(r.get("value_yoy_pct") or 0),
            "volume_yoy_pct": float(r.get("volume_yoy_pct") or 0),
            "avg_deal_size":  float(r.get("avg_deal_size") or 0),
        }
        for r in rows
    ]


def _generate_segment_insights(segments: list, compare: str) -> list:
    """Auto-flag notable segments based on YoY/QoQ performance."""
    insights = []
    period   = "YoY" if compare == "yoy" else "QoQ"

    for s in segments:
        vp  = s.get("value_yoy_pct") or 0
        cvp = s.get("volume_yoy_pct") or 0
        seg = s.get("segment", "Unknown")

        if vp < -10:
            insights.append({
                "severity": "high",
                "segment":  seg,
                "message":  f"{seg} pipeline is down {abs(vp):.0f}% {period} in value — investigate pipeline generation for this segment.",
            })
        elif vp > 15:
            insights.append({
                "severity": "opportunity",
                "segment":  seg,
                "message":  f"{seg} is outperforming {period} by {vp:.0f}% — identify the driver and replicate it.",
            })

        # Volume up but $ down = deal size shrinking
        if cvp > 5 and vp < -5:
            insights.append({
                "severity": "medium",
                "segment":  seg,
                "message":  f"{seg} volume is up {cvp:.0f}% {period} but pipeline value is down {abs(vp):.0f}% — average deal size is shrinking.",
            })

    return insights


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/segments")
async def get_pipeline_segments(
    dimension: str = "channel",
    compare:   str = "yoy",
):
    """Pipeline $ value and volume broken down by segment dimension, vs prior period."""
    if _AVAILABLE:
        try:
            rows     = await asyncio.to_thread(_query_segments, dimension, compare)
            insights = _generate_segment_insights(rows, compare)
            return {"data": rows, "insights": insights, "dimension": dimension, "compare": compare, "source": "databricks"}
        except Exception as e:
            print(f"[pipeline/segments] Databricks error: {e}")

    rows     = _demo_segments(dimension)
    insights = _generate_segment_insights(rows, compare)
    return {"data": rows, "insights": insights, "dimension": dimension, "compare": compare, "source": "demo"}


@router.get("/segment-insights")
async def get_segment_insights(dimension: str = "channel", compare: str = "yoy"):
    """AI-generated segment commentary (re-uses /segments logic, returns only insights)."""
    resp = await get_pipeline_segments(dimension=dimension, compare=compare)
    return {"insights": resp["insights"], "source": resp["source"]}
