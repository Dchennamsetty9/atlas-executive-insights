"""
routes/deal_bands.py — Deal Band Analysis endpoints
Data source: datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot

Endpoints:
  GET /api/deal-bands/performance?compare=prior_quarter|yoy
  GET /api/deal-bands/insights
"""

import asyncio
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter

from query_loader import load_query
from services.databricks_connection import execute_query, token_available

router = APIRouter(prefix="/api/deal-bands", tags=["deal-bands"])

CATALOG = os.getenv("DATABRICKS_CATALOG", "datagroup_mdl")
SCHEMA  = os.getenv("DATABRICKS_SCHEMA",  "mdl_sales_analytics")
TABLE   = f"`{CATALOG}`.`{SCHEMA}`.`gaim_pipeline_daily_snapshot`"

_on_databricks = bool(os.getenv("DATABRICKS_HOST"))
_force_live    = os.getenv("FORCE_LIVE_DATA", "false").lower() == "true"
_AVAILABLE     = token_available() and (_on_databricks or _force_live)

BANDS = [
    {"label": "$0–$10K",      "min": 0,          "max": 10_000},
    {"label": "$10K–$25K",    "min": 10_000,      "max": 25_000},
    {"label": "$25K–$100K",   "min": 25_000,      "max": 100_000},
    {"label": "$100K–$500K",  "min": 100_000,     "max": 500_000},
    {"label": "$500K–$1M",    "min": 500_000,     "max": 1_000_000},
    {"label": "$1M+",         "min": 1_000_000,   "max": 999_999_999},
]

# Pre-computed from the static BANDS constant — not user input.
_BAND_CASES = " ".join(
    f"WHEN amount_towards_plan BETWEEN {b['min']} AND {b['max']} THEN '{b['label']}'"
    for b in BANDS
)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _prior_period_date(compare: str) -> str:
    today = datetime.now()
    if compare == "yoy":
        return today.replace(year=today.year - 1).strftime("%Y-%m-%d")
    # prior_quarter: subtract ~90 days
    from datetime import timedelta
    return (today - timedelta(days=90)).strftime("%Y-%m-%d")


# ── Demo fallback ─────────────────────────────────────────────────────────────

def _demo_bands(compare: str):
    import random
    random.seed(7)
    results = []
    for b in BANDS:
        vol      = random.randint(10, 150)
        val      = random.randint(500_000, 8_000_000)
        wr       = round(random.uniform(0.35, 0.75) * 100, 1)
        cycle    = random.randint(14, 90)
        p_vol    = int(vol * random.uniform(0.7, 1.3))
        p_val    = int(val * random.uniform(0.7, 1.3))
        p_wr     = round(random.uniform(0.35, 0.75) * 100, 1)
        results.append({
            "band":          b["label"],
            "volume":        vol,
            "value":         val,
            "win_rate":      wr,
            "avg_cycle_days": cycle,
            "prior_volume":  p_vol,
            "prior_value":   p_val,
            "prior_win_rate": p_wr,
            "volume_chg_pct": round((vol - p_vol) / p_vol * 100, 1),
            "value_chg_pct":  round((val - p_val) / p_val * 100, 1),
        })
    return results


# ── Live query ────────────────────────────────────────────────────────────────

def _query_bands(compare: str) -> list:
    today      = _today()
    prior_date = _prior_period_date(compare)
    sql = load_query(
        "deal_bands/performance",
        table=TABLE,
        today=today,
        prior_date=prior_date,
        band_cases=_BAND_CASES,
    )
    rows = execute_query(sql)
    return [
        {
            "band":            r.get("band"),
            "volume":          int(r.get("volume") or 0),
            "value":           float(r.get("value") or 0),
            "win_rate":        float(r.get("win_rate") or 0),
            "avg_cycle_days":  int(r.get("avg_cycle_days") or 0),
            "prior_volume":    int(r.get("prior_volume") or 0),
            "prior_value":     float(r.get("prior_value") or 0),
            "prior_win_rate":  float(r.get("prior_win_rate") or 0),
            "volume_chg_pct":  float(r.get("volume_chg_pct") or 0),
            "value_chg_pct":   float(r.get("value_chg_pct") or 0),
        }
        for r in rows
    ]


def _ai_band_insights(bands: list, compare: str) -> list:
    period = "YoY" if compare == "yoy" else "vs Prior Quarter"
    insights = []
    for b in bands:
        band_lbl = b.get("band", "Unknown")
        vol_chg  = b.get("volume_chg_pct", 0)
        val_chg  = b.get("value_chg_pct",  0)
        vol      = b.get("volume", 0)
        val      = b.get("value",  0)

        if vol_chg < -10:
            insights.append({
                "severity": "high",
                "band":     band_lbl,
                "message":  (
                    f"{band_lbl} deals are down {abs(vol_chg):.0f}% {period} in volume "
                    f"({vol:,} deals, ${val/1e6:.1f}M) — investigate pipeline generation for this deal size."
                ),
            })
        if vol_chg > 10 and val_chg < -10:
            insights.append({
                "severity": "medium",
                "band":     band_lbl,
                "message":  (
                    f"{band_lbl} volume is up {vol_chg:.0f}% {period} but deal value is down {abs(val_chg):.0f}% "
                    "— average deal size is shrinking in this band."
                ),
            })
        if vol_chg > 15 and val_chg > 10:
            insights.append({
                "severity": "opportunity",
                "band":     band_lbl,
                "message":  (
                    f"{band_lbl} is outperforming {period}: +{vol_chg:.0f}% volume, +{val_chg:.0f}% value. "
                    "Allocate more sales resources to this deal size."
                ),
            })
    return insights


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/performance")
async def get_deal_band_performance(compare: str = "yoy"):
    """Deal band performance — volume, value, win rate, cycle time vs prior period."""
    if _AVAILABLE:
        try:
            bands    = await asyncio.to_thread(_query_bands, compare)
            insights = _ai_band_insights(bands, compare)
            return {"data": bands, "insights": insights, "compare": compare, "source": "databricks"}
        except Exception as e:
            print(f"[deal-bands/performance] Databricks error: {e}")

    bands    = _demo_bands(compare)
    insights = _ai_band_insights(bands, compare)
    return {"data": bands, "insights": insights, "compare": compare, "source": "demo"}


@router.get("/insights")
async def get_deal_band_insights(compare: str = "yoy"):
    """AI-generated flags for lagging/leading deal bands (subset of /performance)."""
    resp = await get_deal_band_performance(compare=compare)
    return {"insights": resp["insights"], "source": resp["source"]}
