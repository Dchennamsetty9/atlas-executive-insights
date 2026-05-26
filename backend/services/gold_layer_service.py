"""
Atlas — Gold Layer Service
Reads pre-computed Delta tables in datagroup_mdl.atlas.
Falls back gracefully to empty results if the gold schema doesn't exist yet.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .databricks_connection import execute_query

logger = logging.getLogger(__name__)

# Fully-qualified gold table names
_G = "datagroup_mdl.atlas"

# Whitelist for filter dimensions that can be injected into SQL
_ALLOWED_DIMS = frozenset({"geo", "channel", "product"})


def _dim_clause(filters: dict[str, str]) -> tuple[str, list]:
    """Build a safe WHERE clause fragment from a filter dict.
    Only keys in _ALLOWED_DIMS are accepted; values are parameterised.
    Returns (clause_fragment, params_list).
    """
    parts, params = [], []
    for key, val in (filters or {}).items():
        if key not in _ALLOWED_DIMS:
            continue
        if val and val.lower() != "all":
            parts.append(f"t.{key} = ?")
            params.append(val)
        else:
            parts.append(f"t.{key} = 'All'")
    return (" AND ".join(parts) if parts else "t.geo = 'All' AND t.channel = 'All' AND t.product = 'All'"), params


def _safe_query(sql: str, params: list | None = None) -> list[dict]:
    """Execute a query against the gold layer; return [] on any error
    (e.g. table not yet created during first-deploy window)."""
    try:
        return execute_query(sql, params or [])
    except Exception as exc:
        # Log once at DEBUG so we don't flood logs during the bootstrap window
        logger.debug("Gold layer query failed (table may not exist yet): %s — %s", sql[:120], exc)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_kpi_summary(filters: dict[str, str] | None = None) -> list[dict]:
    """
    Return current KPI values + targets for all 9 metrics.
    Applies dimension filters (geo / channel / product).
    """
    clause, params = _dim_clause(filters or {})
    sql = f"""
        SELECT
            t.metric_key,
            t.metric_label,
            t.metric_value,
            t.target_value,
            t.annual_target,
            t.previous_value,
            t.attainment_pct,
            t.status,
            t.delta_pct,
            t.period_start,
            t.period_end,
            t.geo,
            t.channel,
            t.product,
            t.refreshed_at
        FROM {_G}.metrics_summary t
        WHERE {clause}
        ORDER BY t.metric_key
    """
    return _safe_query(sql, params)


def get_metrics_history(
    metric: str,
    days: int = 90,
    filters: dict[str, str] | None = None,
) -> list[dict]:
    """
    Return daily time-series for a single metric, up to *days* days of history.
    """
    if metric not in {
        "won_pipeline", "win_rate", "won_volume", "ads", "created_pipeline",
        "opps_created", "active_pipeline", "coverage", "mql",
    }:
        logger.warning("get_metrics_history: unknown metric_key '%s'", metric)
        return []

    days = max(7, min(days, 540))  # clamp to reasonable window
    clause, params = _dim_clause(filters or {})
    sql = f"""
        SELECT
            t.metric_key,
            t.metric_date,
            t.metric_value,
            t.geo,
            t.channel
        FROM {_G}.metrics_history t
        WHERE t.metric_key = ?
          AND t.metric_date >= DATEADD(DAY, -{days}, CURRENT_DATE())
          AND {clause}
        ORDER BY t.metric_date ASC
    """
    return _safe_query(sql, [metric] + params)


def get_insights(
    filters: dict[str, str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Return active AI insights (not expired, is_active=TRUE).
    """
    limit = max(1, min(limit, 50))
    sql = f"""
        SELECT
            insight_id,
            title,
            description,
            recommendation,
            why_text,
            severity,
            category,
            icon,
            metric,
            geo,
            channel,
            model_used,
            generated_at,
            expires_at
        FROM {_G}.insights_cache
        WHERE is_active = TRUE
          AND expires_at > CURRENT_TIMESTAMP()
        ORDER BY
            CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
            generated_at DESC
        LIMIT {limit}
    """
    return _safe_query(sql)


def get_forecast(
    metric: str,
    model: str = "auto",
    horizon: int = 90,
) -> dict | None:
    """
    Return the latest forecast result for a metric.
    model='auto' → selects the row with lowest MAPE.
    Returns None if no forecast exists yet.
    """
    if metric not in {"won_pipeline", "active_pipeline", "win_rate", "created_pipeline"}:
        return None
    horizon = horizon if horizon in (30, 60, 90) else 90

    if model == "auto":
        sql = f"""
            SELECT *
            FROM {_G}.forecast_results
            WHERE metric_key   = ?
              AND horizon_days = ?
              AND geo          = 'All'
            ORDER BY generated_at DESC, mape ASC
            LIMIT 1
        """
        params = [metric, horizon]
    else:
        # Validate model name against whitelist
        allowed_models = {"holt_winters", "triple_smoothing", "arima", "linear_seasonal"}
        if model not in allowed_models:
            logger.warning("get_forecast: unknown model '%s'", model)
            return None
        sql = f"""
            SELECT *
            FROM {_G}.forecast_results
            WHERE metric_key   = ?
              AND model_name   = ?
              AND horizon_days = ?
              AND geo          = 'All'
            ORDER BY generated_at DESC
            LIMIT 1
        """
        params = [metric, model, horizon]

    rows = _safe_query(sql, params)
    if not rows:
        return None
    row = rows[0]

    # Deserialise JSON columns
    for col in ("key_drivers", "executive_actions", "downside_risks", "upside_opportunities"):
        val = row.get(col)
        if isinstance(val, str):
            try:
                row[col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                row[col] = []
    return row


def get_revenue_gap(filters: dict[str, str] | None = None) -> dict | None:
    """Return the most recent revenue gap decomposition."""
    clause, params = _dim_clause(filters or {})
    sql = f"""
        SELECT *
        FROM {_G}.revenue_gap_decomposition t
        WHERE {clause}
        ORDER BY t.period_end DESC
        LIMIT 1
    """
    rows = _safe_query(sql, params)
    return rows[0] if rows else None


def get_extended_analytics(
    tab: str,
    filters: dict[str, str] | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Return pre-aggregated analytics for one of the 5 extended tabs.
    """
    allowed_tabs = {"mql", "pipeline_segments", "deal_bands", "coverage", "largest_deals"}
    if tab not in allowed_tabs:
        logger.warning("get_extended_analytics: unknown tab '%s'", tab)
        return []

    limit = max(1, min(limit, 500))
    dim_clause, dim_params = _dim_clause(filters or {})

    sql = f"""
        SELECT
            dimension_key,
            dimension_value,
            metric_key,
            metric_value,
            secondary_value,
            period_start,
            geo,
            channel,
            metadata_json
        FROM {_G}.extended_analytics
        WHERE tab_name = ?
          AND {dim_clause}
        ORDER BY metric_value DESC
        LIMIT {limit}
    """
    rows = _safe_query(sql, [tab] + dim_params)

    # Parse metadata_json in Python (avoids extra Spark overhead)
    for row in rows:
        meta = row.get("metadata_json")
        if meta and isinstance(meta, str):
            try:
                row["metadata"] = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                row["metadata"] = {}
        row.pop("metadata_json", None)
    return rows


def get_alerts_count() -> int:
    """Return count of unread/un-dispatched alerts (used by notification badge)."""
    sql = f"""
        SELECT COUNT(*) AS cnt
        FROM {_G}.alerts_queue
        WHERE status = 'pending'
    """
    rows = _safe_query(sql)
    return int(rows[0]["cnt"]) if rows else 0


# Singleton-style export (matches pattern of other services in this codebase)
gold_layer_service = type(
    "GoldLayerService",
    (),
    {
        "get_kpi_summary":         staticmethod(get_kpi_summary),
        "get_metrics_history":     staticmethod(get_metrics_history),
        "get_insights":            staticmethod(get_insights),
        "get_forecast":            staticmethod(get_forecast),
        "get_revenue_gap":         staticmethod(get_revenue_gap),
        "get_extended_analytics":  staticmethod(get_extended_analytics),
        "get_alerts_count":        staticmethod(get_alerts_count),
    },
)()
