"""Strict retained-vintage backtests. No demo, cross-product, or invented-band fallback."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import math


RETAINED_MODELS = {
    "ensemble": "Adaptive_Ensemble",
    "ets": "ETS",
    "lightgbm": "Global_LGB_Q50_{product}",
    "mstl_v2": "MSTL_v2",
    "dhr_arima": "DHR_ARIMA",
}

MESSAGES = {
    "source_unavailable": "Live retained history is unavailable. No demo values are substituted.",
    "combined_history_unverified": "A matched UCC + ITSG backtest is not available. Select a product to inspect its own history.",
    "region_history_unverified": "Closed actuals are verified at all-region total grain only. Select All regions.",
    "model_history_unverified": "Retained history for this model is not verified. Native Prophet is not the retained Prophet trend model.",
    "no_matched_history": "No closed weeks have a retained forecast at this horizon. Try a shorter horizon; no other product's history is substituted.",
    "invalid_history": "Retained rows have ambiguous or invalid forecast/actual pairs and cannot be scored safely.",
    "source_query_failed": "The retained-history source could not be read. No fallback values are substituted.",
}


def build_backtest_query(vintages_table, actuals_table, product, model, horizon_weeks):
    """Select one unambiguous publication per closed week inside the requested lead-time bin."""
    if product not in ("UCC", "ITSG") or model not in RETAINED_MODELS or not 1 <= horizon_weeks <= 13:
        raise ValueError("Unsupported retained backtest scope")
    source_model = RETAINED_MODELS[model].format(product=product)
    lo, hi = (horizon_weeks - 1) * 7 + 1, horizon_weeks * 7
    # Latest recorded publication timestamp is conservative if metadata stamps differ.
    # Do not infer a total by value, aggregate market rows, or use the latest-only compat view.
    return f"""
        WITH raw_vintages AS (
            SELECT DISTINCT CAST(ds AS DATE) AS ds,
                TRY_CAST(run_date_utc AS DATE) AS origin_date,
                GREATEST(TRY_CAST(run_timestamp_utc AS TIMESTAMP),
                         TRY_CAST(run_ts_utc AS TIMESTAMP),
                         TRY_CAST(run_date_utc AS TIMESTAMP)) AS origin_ts,
                CAST(p50 AS DOUBLE) AS predicted,
                CAST(p05 AS DOUBLE) AS worst, CAST(p95 AS DOUBLE) AS best
            FROM {vintages_table}
            WHERE model = '{source_model}'
              AND LOWER(TRIM(grain_level)) = 'total'
              AND UPPER(TRIM(sales_market)) IN ('ALL', 'TOTAL')
              AND (product_group IS NULL OR UPPER(TRIM(product_group)) = '{product}')
              AND DATE_ADD(CAST(ds AS DATE), 7) <= CURRENT_DATE()
        ), ranked_vintages AS (
            SELECT *, DENSE_RANK() OVER (PARTITION BY ds ORDER BY origin_ts DESC) AS origin_rank
            FROM raw_vintages
            WHERE origin_date = CAST(origin_ts AS DATE)
              AND origin_ts < CAST(ds AS TIMESTAMP)
              AND DATEDIFF(ds, origin_date) BETWEEN {lo} AND {hi}
        ), forecasts AS (
            SELECT ds, MIN(origin_date) AS run_date, MIN(origin_ts) AS origin_ts,
                   MIN(predicted) AS predicted, MIN(worst) AS worst, MIN(best) AS best,
                   COUNT(*) AS forecast_variants
            FROM ranked_vintages WHERE origin_rank = 1 GROUP BY ds
        ), raw_actuals AS (
            SELECT DISTINCT CAST(ds AS DATE) AS ds,
                   TRY_CAST(run_date_utc AS DATE) AS actual_run_date,
                   CAST(forecast AS DOUBLE) AS actual
            FROM {actuals_table}
            WHERE LOWER(TRIM(source)) = 'actual' AND model = 'Adaptive_Ensemble'
              AND LOWER(TRIM(grain_level)) = 'total'
              AND UPPER(TRIM(sales_market)) IN ('ALL', 'TOTAL')
              AND DATE_ADD(CAST(ds AS DATE), 7) <= CURRENT_DATE()
        ), ranked_actuals AS (
            SELECT *, DENSE_RANK() OVER (PARTITION BY ds ORDER BY actual_run_date DESC) AS actual_rank
            FROM raw_actuals WHERE actual_run_date IS NOT NULL
        ), actuals AS (
            SELECT ds, MIN(actual) AS actual, MIN(actual_run_date) AS actual_run_date,
                   COUNT(*) AS actual_variants
            FROM ranked_actuals WHERE actual_rank = 1 GROUP BY ds
        )
        SELECT CAST(f.ds AS STRING) AS ds, CAST(f.run_date AS STRING) AS run_date,
               CAST(f.origin_ts AS STRING) AS origin_ts,
               f.predicted, f.worst, f.best, a.actual,
               CAST(a.actual_run_date AS STRING) AS actual_run_date,
               f.forecast_variants, a.actual_variants
        FROM forecasts f JOIN actuals a ON f.ds = a.ds ORDER BY f.ds
    """


def _finite(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _timestamp(value):
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def valid_pairs(raw_rows, horizon_weeks, today=None):
    """Reject duplicate targets, horizon mismatches, conflicts, and non-finite values."""
    today = today or datetime.now(timezone.utc).date()
    counts = Counter(str(row.get("ds")) for row in raw_rows)
    pairs, rejected = [], 0
    lo, hi = (horizon_weeks - 1) * 7 + 1, horizon_weeks * 7
    for row in raw_rows:
        ds, origin = _date(row.get("ds")), _date(row.get("run_date"))
        actual_run = _date(row.get("actual_run_date"))
        stamp = _timestamp(row.get("origin_ts"))
        predicted, actual = _finite(row.get("predicted")), _finite(row.get("actual"))
        if (not ds or not origin or not actual_run or not stamp
                or stamp.date() != origin or not lo <= (ds - origin).days <= hi
                or ds + timedelta(days=7) > today or actual_run < ds + timedelta(days=7)
                or actual_run > today or counts[str(row.get("ds"))] != 1
                or row.get("forecast_variants") != 1 or row.get("actual_variants") != 1
                or predicted is None or actual is None):
            rejected += 1
            continue
        low, high = _finite(row.get("worst")), _finite(row.get("best"))
        if low is None or high is None or not low <= predicted <= high:
            low = high = None  # Preserve the point; never invent or repair an interval.
        pairs.append({"ds": ds.isoformat(), "run_date": origin.isoformat(),
                      "origin_ts": stamp.isoformat(), "lead_days": (ds - origin).days,
                      "actual_run_date": actual_run.isoformat(), "predicted": predicted,
                      "actual": actual, "worst": low, "best": high})
    return sorted(pairs, key=lambda row: row["ds"]), rejected


def backtest_summary(rows):
    scored = [row for row in rows if row["actual"] != 0]
    banded = [row for row in rows if row["worst"] is not None and row["best"] is not None]
    n, b = len(scored), len(banded)
    return {
        "weeks_scored": len(rows), "mape_weeks_scored": n, "band_weeks_scored": b,
        "zero_actual_weeks": len(rows) - n,
        "coverage_pct": round(sum(row["worst"] <= row["actual"] <= row["best"] for row in banded) / b * 100, 1) if b else None,
        "mape_pct": round(sum(abs(row["predicted"] - row["actual"]) / abs(row["actual"]) for row in scored) / n * 100, 1) if n else None,
        "bias_pct": round(sum((row["predicted"] - row["actual"]) / abs(row["actual"]) for row in scored) / n * 100, 1) if n else None,
    }


def backtest_response(product, market, model, horizon_weeks, raw_rows=(), reason=None, today=None):
    rows, rejected = valid_pairs(raw_rows, horizon_weeks, today) if reason is None else ([], 0)
    if not rows and reason is None:
        reason = "invalid_history" if rejected else "no_matched_history"
    return {
        "source": "live" if rows else "unavailable", "available": bool(rows),
        "reason": reason, "message": MESSAGES.get(reason),
        "product": product, "sales_market": market, "model": model,
        "source_model": RETAINED_MODELS.get(model, "").format(product=product) or None,
        "grain_level": "total", "horizon_weeks": horizon_weeks,
        "lead_days_min": (horizon_weeks - 1) * 7 + 1, "lead_days_max": horizon_weeks * 7,
        "basis": "latest_retained_publication_in_lead_time_bin_vs_latest_closed_actuals",
        "actuals_basis": "latest_published_actuals_may_include_revisions",
        "interval_basis": "published_bounds_not_assumed_calibrated",
        "small_sample": bool(rows) and len(rows) < 13,
        "rejected_pairs": rejected, "rows": rows, "summary": backtest_summary(rows),
    }