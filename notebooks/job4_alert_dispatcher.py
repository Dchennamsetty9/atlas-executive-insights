# Databricks notebook source
# Atlas Executive Insights — Job 4: Alert Dispatcher
# Schedule: every 4 hours at :30 (after Job 1 at :00)
# Writes: atlas.alerts_queue, datagroup_mdl.mdl_sales_analytics.atlas_notifications
# Reads:  atlas.metrics_summary, atlas.alert_rules
# Sends:  Slack webhook (httpx) + AWS SES (boto3)

# COMMAND ----------
# MAGIC %md ## Atlas Job 4 — Alert Dispatcher
# MAGIC
# MAGIC 1. Load current metric values from `atlas.metrics_summary`
# MAGIC 2. Evaluate each `atlas.alert_rules` threshold against live values
# MAGIC 3. Check cooldown window — suppress if same metric already alerted recently
# MAGIC 4. Fire Slack webhook and/or AWS SES email for each un-suppressed breach
# MAGIC 5. Write to `atlas.alerts_queue` (for audit) and `atlas_notifications` (for in-app bell)

# COMMAND ----------
# %pip install httpx boto3 --quiet

# COMMAND ----------

import uuid, json, os
from datetime import datetime, timedelta
import httpx

CATALOG    = "datagroup_mdl"
GOLD       = f"{CATALOG}.atlas"
MDL        = f"{CATALOG}.mdl_sales_analytics"
RUN_ID     = str(uuid.uuid4())
NOW        = datetime.utcnow()

# External config from environment / Databricks secrets
SLACK_WEBHOOK_URL  = dbutils.secrets.get(scope="atlas", key="slack_webhook_url") if hasattr(dbutils, "secrets") else os.getenv("SLACK_WEBHOOK_URL", "")
SES_REGION         = os.getenv("AWS_SES_REGION", "us-east-1")
SES_FROM_EMAIL     = os.getenv("SES_FROM_EMAIL", "atlas-alerts@goto.com")
DEFAULT_EMAIL_TO   = os.getenv("NOTIFICATION_EMAIL", "dchennamsetty@goto.com")

print(f"[Job4] Starting Alert Dispatcher — {NOW.isoformat()} | run_id={RUN_ID}")
print(f"[Job4] Slack: {'configured' if SLACK_WEBHOOK_URL else 'NOT configured'}")
print(f"[Job4] SES region: {SES_REGION} | from: {SES_FROM_EMAIL}")

# COMMAND ----------
# MAGIC %md ### Step 1 — Load rules and current metric values

# COMMAND ----------

from pyspark.sql import functions as F

rules = (
    spark.table(f"{GOLD}.alert_rules")
    .filter(F.col("is_active") == True)
    .collect()
)
print(f"[Job4] Loaded {len(rules)} active alert rules")

metrics = (
    spark.table(f"{GOLD}.metrics_summary")
    .filter(F.col("geo") == "All")
    .filter(F.col("channel") == "All")
    .filter(F.col("product") == "All")
    .collect()
)
metrics_dict = {row["metric_key"]: dict(row.asDict()) for row in metrics}
print(f"[Job4] Loaded {len(metrics_dict)} metrics from metrics_summary")

# COMMAND ----------
# MAGIC %md ### Step 2 — Check cooldown windows

# COMMAND ----------

# Find alerts dispatched in the cooldown window for each rule
dispatched_rules = {}
try:
    recent_alerts = (
        spark.table(f"{GOLD}.alerts_queue")
        .filter(F.col("status").isin(["dispatched"]))
        .filter(F.col("dispatched_at") >= F.lit(NOW - timedelta(hours=48)))
        .select("rule_id", "dispatched_at")
        .collect()
    )
    for row in recent_alerts:
        dispatched_rules[row["rule_id"]] = row["dispatched_at"]
except Exception as e:
    print(f"[Job4] Could not load recent alerts (first run?): {e}")

def is_in_cooldown(rule_id, cooldown_hours):
    if rule_id not in dispatched_rules:
        return False
    last_dispatch = dispatched_rules[rule_id]
    if isinstance(last_dispatch, datetime):
        elapsed = (NOW - last_dispatch).total_seconds() / 3600
    else:
        # pyspark Timestamp
        elapsed = (NOW - last_dispatch.toPandas() if hasattr(last_dispatch, 'toPandas') else NOW).total_seconds() / 3600
    return elapsed < cooldown_hours

# COMMAND ----------
# MAGIC %md ### Step 3 — Evaluate rules and build breach list

# COMMAND ----------

breaches = []

for rule in rules:
    rule_id    = rule["rule_id"]
    m_key      = rule["metric_key"]
    rule_type  = rule["rule_type"]
    threshold  = float(rule["threshold_value"] or 0)
    severity   = rule["severity"]
    cooldown   = int(rule["cooldown_hours"] or 4)

    m = metrics_dict.get(m_key)
    if not m:
        continue

    actual  = float(m["metric_value"] or 0)
    paced   = float(m["target_value"] or 0)
    annual  = float(m["annual_target"] or 0)
    att_pct = float(m["attainment_pct"] or 0)

    breached = False
    if rule_type == "below_pct_of_target" and paced > 0:
        ratio = actual / paced
        if ratio < threshold:
            breached = True

    if not breached:
        continue

    if is_in_cooldown(rule_id, cooldown):
        print(f"[Job4] SUPPRESSED (cooldown): rule={rule_id} metric={m_key}")
        continue

    def fmt(v):
        if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
        if v >= 1_000:     return f"${v/1_000:.0f}K"
        return str(round(v, 1))

    gap = paced - actual
    title = f"{'⚠️' if severity=='warning' else '🚨'} {m_key.replace('_',' ').title()} Alert — {att_pct:.0f}% of pace"
    body  = (
        f"**{m_key.replace('_',' ').title()}** is at {fmt(actual)} "
        f"vs paced target of {fmt(paced)} — gap of {fmt(gap)}.\n"
        f"Attainment: {att_pct:.1f}% | Severity: {severity.upper()}"
    )

    breaches.append({
        "alert_id":       str(uuid.uuid4()),
        "rule_id":        rule_id,
        "metric_key":     m_key,
        "alert_type":     "threshold_breach",
        "severity":       severity,
        "title":          title,
        "body":           body,
        "current_value":  actual,
        "threshold_value": paced * threshold,
        "attainment_pct": att_pct,
        "geo":            m.get("geo", "All"),
        "channel":        m.get("channel", "All"),
        "notify_slack":   bool(rule["notify_slack"]),
        "notify_email":   bool(rule["notify_email"]),
        "notify_in_app":  bool(rule["notify_in_app"]),
        "email_to":       str(rule["email_recipients"] or DEFAULT_EMAIL_TO),
        "slack_channel":  str(rule["slack_channel"] or "#atlas-alerts"),
        "created_at":     NOW,
    })

print(f"[Job4] {len(breaches)} breaches to dispatch (after cooldown check)")

# COMMAND ----------
# MAGIC %md ### Step 4 — Send Slack notifications

# COMMAND ----------

def send_slack(title: str, body: str, severity: str, channel: str = "#atlas-alerts"):
    if not SLACK_WEBHOOK_URL:
        print("[Job4] Slack: no webhook URL — skipping")
        return False
    color = "#FF0000" if severity == "critical" else "#FFA500"
    payload = {
        "channel": channel,
        "attachments": [{
            "color":    color,
            "title":    title,
            "text":     body,
            "footer":   "Atlas Executive Insights",
            "ts":       int(NOW.timestamp()),
        }]
    }
    try:
        r = httpx.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[Job4] Slack send failed: {e}")
        return False


def send_ses_email(to_emails: str, subject: str, body_text: str):
    """Send via AWS SES using boto3 (credentials from instance profile or env vars)."""
    import boto3
    try:
        ses = boto3.client("ses", region_name=SES_REGION)
        recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
        if not recipients:
            return False
        ses.send_email(
            Source=SES_FROM_EMAIL,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body":    {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            },
        )
        return True
    except Exception as e:
        print(f"[Job4] SES send failed: {e}")
        return False

# COMMAND ----------
# MAGIC %md ### Step 5 — Dispatch, write to alerts_queue and atlas_notifications

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType, DoubleType, BooleanType, TimestampType

queue_rows        = []
notification_rows = []

for breach in breaches:
    slack_sent = False
    email_sent = False

    if breach["notify_slack"]:
        slack_sent = send_slack(breach["title"], breach["body"], breach["severity"], breach["slack_channel"])

    if breach["notify_email"]:
        email_sent = send_ses_email(
            breach["email_to"],
            breach["title"],
            breach["body"],
        )

    dispatched_at = NOW if (slack_sent or email_sent) else None
    status        = "dispatched" if (slack_sent or email_sent) else "pending"

    print(f"[Job4] {breach['metric_key']}: slack={slack_sent} email={email_sent} status={status}")

    queue_rows.append({
        "alert_id":         breach["alert_id"],
        "rule_id":          breach["rule_id"],
        "metric_key":       breach["metric_key"],
        "alert_type":       breach["alert_type"],
        "severity":         breach["severity"],
        "title":            breach["title"],
        "body":             breach["body"],
        "current_value":    breach["current_value"],
        "threshold_value":  breach["threshold_value"],
        "attainment_pct":   breach["attainment_pct"],
        "geo":              breach["geo"],
        "channel":          breach["channel"],
        "notified_slack":   slack_sent,
        "notified_email":   email_sent,
        "notified_in_app":  False,  # set after notification table write
        "created_at":       NOW,
        "dispatched_at":    dispatched_at,
        "status":           status,
    })

    if breach["notify_in_app"]:
        notification_rows.append({
            "notification_id":  breach["alert_id"],
            "user_id":          "broadcast",  # all users see threshold alerts
            "title":            breach["title"],
            "body":             breach["body"],
            "category":         "threshold_breach",
            "severity":         breach["severity"],
            "metric_key":       breach["metric_key"],
            "is_read":          False,
            "created_at":       NOW,
            "expires_at":       NOW + timedelta(hours=48),
        })

# Write to alerts_queue
if queue_rows:
    queue_df = spark.createDataFrame(queue_rows)
    queue_df.write.mode("append").saveAsTable(f"{GOLD}.alerts_queue")
    print(f"[Job4] Written {len(queue_rows)} rows to {GOLD}.alerts_queue")

    # Flip notified_in_app = TRUE in queue for rows we're about to write to notifications
    if notification_rows:
        ids = [r["notification_id"] for r in notification_rows]
        ids_sql = ", ".join(f"'{i}'" for i in ids)
        spark.sql(f"""
            UPDATE {GOLD}.alerts_queue
            SET notified_in_app = TRUE
            WHERE alert_id IN ({ids_sql})
        """)

# Write in-app notifications
if notification_rows:
    notif_df = spark.createDataFrame(notification_rows)
    notif_df.write.mode("append").saveAsTable(f"{MDL}.atlas_notifications")
    print(f"[Job4] Written {len(notification_rows)} rows to {MDL}.atlas_notifications")

print(f"[Job4] Alert Dispatcher COMPLETE ✓ — {len(breaches)} breaches processed")
