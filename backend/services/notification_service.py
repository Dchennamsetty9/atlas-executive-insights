"""
services/notification_service.py
==================================
Three-channel alerting:
  1. In-app   — stored in atlas_notifications Delta table, polled by the frontend
  2. Email    — SMTP (aiosmtplib async)
  3. Slack    — Incoming Webhook POST

All channels degrade gracefully: if not configured they log a warning and return
without raising so a missing Slack URL never breaks the main request path.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DDL_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.atlas_notifications (
  notification_id  STRING NOT NULL,
  user_id          STRING,           -- NULL = broadcast to all users
  title            STRING NOT NULL,
  body             STRING,
  level            STRING NOT NULL,  -- info | warning | critical
  metric           STRING,
  current_value    DOUBLE,
  threshold        DOUBLE,
  is_read          BOOLEAN NOT NULL DEFAULT false,
  created_at       TIMESTAMP
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'false')
"""


class NotificationService:
    """Send and store threshold-breach alerts across in-app, email, and Slack."""

    def __init__(self):
        from config.settings import settings
        from services.databricks_connection import get_connection

        self._get_connection = get_connection
        self._catalog = settings.user_prefs_catalog
        self._schema  = settings.user_prefs_schema
        self._table   = settings.notifications_table
        self._settings = settings
        self._bootstrapped = False

    # ── Bootstrap ──────────────────────────────────────────────────────────────

    def _bootstrap(self):
        if self._bootstrapped:
            return
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(_DDL_NOTIFICATIONS.format(
                    catalog=self._catalog, schema=self._schema))
            self._bootstrapped = True
        except Exception as exc:
            logger.warning("Could not bootstrap notifications table: %s", exc)

    def _fqn(self) -> str:
        return f"`{self._catalog}`.`{self._schema}`.`{self._table}`"

    def _exec(self, sql: str, params: tuple = ()):
        try:
            self._bootstrap()
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(sql, params)
                try:
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description] if cur.description else []
                    return [dict(zip(cols, row)) for row in rows]
                except Exception:
                    return []
        except Exception as exc:
            logger.warning("Notification SQL error: %s", exc)
            return []

    # ── In-app notifications ───────────────────────────────────────────────────

    def store_notification(self, title: str, body: str, level: str = "warning",
                           metric: Optional[str] = None,
                           current_value: Optional[float] = None,
                           threshold: Optional[float] = None,
                           user_id: Optional[str] = None) -> str:
        """Persist a notification for in-app display; returns notification_id."""
        notif_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self._exec(
            f"INSERT INTO {self._fqn()} "
            "(notification_id, user_id, title, body, level, metric, "
            " current_value, threshold, is_read, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, false, ?)",
            (notif_id, user_id, title, body, level, metric,
             current_value, threshold, now)
        )
        return notif_id

    def list_notifications(self, user_id: Optional[str] = None,
                           unread_only: bool = False,
                           limit: int = 50) -> List[Dict[str, Any]]:
        wheres, params = [], []
        if user_id:
            wheres.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        if unread_only:
            wheres.append("is_read = false")
        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        return self._exec(
            f"SELECT * FROM {self._fqn()} {where_clause} "
            f"ORDER BY created_at DESC LIMIT {limit}",
            tuple(params)
        )

    def mark_read(self, notification_id: str) -> bool:
        self._exec(
            f"UPDATE {self._fqn()} SET is_read = true WHERE notification_id = ?",
            (notification_id,)
        )
        return True

    def mark_all_read(self, user_id: Optional[str] = None) -> bool:
        if user_id:
            self._exec(
                f"UPDATE {self._fqn()} SET is_read = true "
                "WHERE user_id = ? OR user_id IS NULL",
                (user_id,)
            )
        else:
            self._exec(f"UPDATE {self._fqn()} SET is_read = true", ())
        return True

    def unread_count(self, user_id: Optional[str] = None) -> int:
        wheres, params = ["is_read = false"], []
        if user_id:
            wheres.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        rows = self._exec(
            f"SELECT COUNT(*) AS cnt FROM {self._fqn()} "
            f"WHERE {' AND '.join(wheres)}",
            tuple(params)
        )
        return int(rows[0]["cnt"]) if rows else 0

    # ── Email (SMTP or AWS SES) ────────────────────────────────────────────────

    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """Send email via AWS SES (preferred when ses_region is set) or SMTP."""
        s = self._settings
        # Prefer SES when configured
        if getattr(s, "ses_region", ""):
            return await self._send_ses(to, subject, body)
        return await self._send_smtp(to, subject, body)

    async def _send_ses(self, to: str, subject: str, body: str) -> bool:
        """Send via AWS SES using boto3 (thread-pool to avoid blocking the event loop)."""
        s = self._settings
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _ses_send():
            import boto3  # noqa: PLC0415
            client = boto3.client("ses", region_name=s.ses_region)
            recipients = [e.strip() for e in to.split(",") if e.strip()]
            if not recipients:
                return False
            client.send_email(
                Source=s.ses_from_email,
                Destination={"ToAddresses": recipients},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body":    {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            )
            return True

        try:
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(pool, _ses_send)
            logger.info("SES email sent to %s: %s", to, subject)
            return bool(result)
        except ImportError:
            logger.warning("boto3 not installed — pip install boto3")
            return False
        except Exception as exc:
            logger.warning("SES send error: %s", exc)
            return False

    async def _send_smtp(self, to: str, subject: str, body: str) -> bool:
        """Send via SMTP using aiosmtplib."""
        s = self._settings
        if not s.smtp_host or not s.smtp_user:
            logger.debug("SMTP not configured — skipping email to %s", to)
            return False
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["From"]    = s.smtp_from
            msg["To"]      = to
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_user,
                password=s.smtp_password,
                start_tls=s.smtp_tls,
            )
            logger.info("SMTP email sent to %s: %s", to, subject)
            return True
        except ImportError:
            logger.warning("aiosmtplib not installed — pip install aiosmtplib")
            return False
        except Exception as exc:
            logger.warning("SMTP send error: %s", exc)
            return False

    # ── Slack ──────────────────────────────────────────────────────────────────

    async def send_slack(self, title: str, body: str,
                         level: str = "warning") -> bool:
        webhook = self._settings.slack_webhook_url
        if not webhook:
            logger.debug("Slack webhook not configured — skipping Slack alert")
            return False
        color_map = {"info": "#3b82f6", "warning": "#f59e0b", "critical": "#ef4444"}
        color = color_map.get(level, "#94a3b8")
        payload = {
            "attachments": [{
                "color": color,
                "title": f"[Atlas] {title}",
                "text":  body,
                "footer": "Atlas Executive Insights",
                "ts":    int(datetime.utcnow().timestamp()),
            }]
        }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(webhook, json=payload)
                if resp.status_code == 200:
                    logger.info("Slack alert sent: %s", title)
                    return True
                logger.warning("Slack returned %s", resp.status_code)
                return False
        except ImportError:
            logger.warning("httpx not installed — pip install httpx")
            return False
        except Exception as exc:
            logger.warning("Slack send error: %s", exc)
            return False

    # ── Broadcast alert (all channels) ────────────────────────────────────────

    async def broadcast_alert(self, title: str, body: str,
                              level: str = "warning",
                              metric: Optional[str] = None,
                              current_value: Optional[float] = None,
                              threshold: Optional[float] = None,
                              email_to: Optional[str] = None,
                              user_id: Optional[str] = None) -> Dict[str, Any]:
        """Persist in-app notification AND send email + Slack if configured."""
        notif_id = self.store_notification(
            title=title, body=body, level=level,
            metric=metric, current_value=current_value,
            threshold=threshold, user_id=user_id
        )
        results = {"notification_id": notif_id, "email": False, "slack": False}

        tasks = [self.send_slack(title, body, level)]
        if email_to:
            tasks.append(self.send_email(email_to, f"[Atlas Alert] {title}", body))

        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        results["slack"] = outcomes[0] is True
        if email_to:
            results["email"] = outcomes[1] is True

        return results

    # ── Threshold checker (called after KPI load) ─────────────────────────────

    async def check_thresholds(self, kpis: List[Dict[str, Any]]) -> int:
        """
        Scan KPIs; fire alerts when attainment drops below configured thresholds.
        Returns count of new alerts fired.
        """
        s = self._settings
        fired = 0
        for kpi in kpis:
            att = kpi.get("targetAchievement") or kpi.get("target_achievement") or 0
            title = kpi.get("title", "Unknown KPI")
            value = kpi.get("value", 0)
            target = kpi.get("target", 0)

            if att <= s.alert_threshold_critical * 100:
                level = "critical"
                msg   = (f"{title} is CRITICAL at {att:.0f}% of target "
                         f"(actual: {value:,.0f}, target: {target:,.0f}).")
            elif att <= s.alert_threshold_at_risk * 100:
                level = "warning"
                msg   = (f"{title} is AT RISK at {att:.0f}% of target "
                         f"(actual: {value:,.0f}, target: {target:,.0f}).")
            else:
                continue

            await self.broadcast_alert(
                title=f"{title} — {level.upper()}",
                body=msg,
                level=level,
                metric=kpi.get("id"),
                current_value=float(att),
                threshold=s.alert_threshold_at_risk * 100,
            )
            fired += 1

        return fired


# Singleton
notification_service = NotificationService()
