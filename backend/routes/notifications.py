"""
routes/notifications.py
========================
In-app notifications + threshold alert management.

  GET  /api/notifications           → list notifications for the current user
  GET  /api/notifications/count     → unread count (for the bell badge)
  POST /api/notifications/read/{id} → mark one notification as read
  POST /api/notifications/read-all  → mark all as read
  POST /api/notifications/check     → trigger a manual threshold check against current KPIs
  POST /api/notifications/test      → send a test alert across all configured channels
"""

import logging
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from services.notification_service import notification_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _user(token: str = "") -> str:
    return token[:64] if token else "anonymous"


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_id = _user(x_forwarded_access_token)
    notifs = notification_service.list_notifications(
        user_id=user_id, unread_only=unread_only, limit=limit
    )
    return {"notifications": notifs}


@router.get("/count")
async def unread_count(
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_id = _user(x_forwarded_access_token)
    count = notification_service.unread_count(user_id=user_id)
    return {"unread_count": count}


@router.post("/read/{notification_id}")
async def mark_read(
    notification_id: str,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    notification_service.mark_read(notification_id)
    return {"success": True}


@router.post("/read-all")
async def mark_all_read(
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_id = _user(x_forwarded_access_token)
    notification_service.mark_all_read(user_id=user_id)
    return {"success": True}


# ── POST /api/notifications/check ─────────────────────────────────────────────

@router.post("/check")
async def check_thresholds(
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    """
    Pull the latest KPI data and fire alerts for any metric below its threshold.
    Returns how many new alerts were dispatched.
    """
    try:
        # Import lazily to avoid circular imports at module load time
        from services.gaim_data_service import GAIMDataService
        gaim = GAIMDataService()
        kpi_rows = await gaim.fetch_kpis()
        # fetch_kpis returns raw rows; convert to the shape check_thresholds expects
        kpis_for_check = [
            {
                "id":               r.get("metric_key", r.get("id", "")),
                "title":            r.get("metric_label", r.get("title", "KPI")),
                "value":            float(r.get("metric_value", r.get("value", 0)) or 0),
                "target":           float(r.get("target_value", r.get("target", 0)) or 0),
                "targetAchievement": float(r.get("attainment_pct", r.get("targetAchievement", 100)) or 100),
            }
            for r in (kpi_rows or [])
        ]
        fired = await notification_service.check_thresholds(kpis_for_check)
        return {"success": True, "alerts_fired": fired}
    except Exception as exc:
        logger.warning("Threshold check error: %s", exc)
        return {"success": False, "alerts_fired": 0, "error": str(exc)}


# ── POST /api/notifications/test ──────────────────────────────────────────────

class TestAlertBody(BaseModel):
    email_to: Optional[str] = None
    message:  Optional[str] = "This is a test alert from Atlas Executive Insights."
    level:    Optional[str] = "warning"


@router.post("/test")
async def send_test_alert(
    body: TestAlertBody,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    """
    Send a test notification to verify email and Slack are configured correctly.
    Fires across all three channels (in-app, email if email_to provided, Slack if webhook set).
    """
    results = await notification_service.broadcast_alert(
        title="Atlas Test Alert",
        body=body.message,
        level=body.level,
        email_to=body.email_to,
    )
    return {"success": True, "channels": results}
