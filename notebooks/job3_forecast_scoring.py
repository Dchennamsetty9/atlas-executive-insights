# Databricks notebook source
# Atlas Executive Insights — Job 3: Forecast Scoring
# Schedule: nightly 3 AM Eastern
# Writes: atlas.forecast_results
# Reads:  atlas.metrics_history (gold)
# Models: Holt-Winters, ARIMA (ARMA via numpy), Triple Smoothing, Linear+Seasonal
# No MLflow — results written directly to Delta

# COMMAND ----------
# MAGIC %md ## Atlas Job 3 — Forecast Scoring
# MAGIC
# MAGIC For each of 4 core metrics, runs 4 forecasting models across 30/60/90 day horizons.
# MAGIC Selects the best model by 30-day holdout MAPE. Generates 90-day scenarios (best, worst,
# MAGIC most likely) and calls the LLM to produce 4-box intelligence text.

# COMMAND ----------
# %pip install scipy statsmodels --quiet

# COMMAND ----------

import uuid, json, re
from datetime import datetime, date, timedelta
from math import sqrt, exp, log
import numpy as np

from pyspark.sql import functions as F

CATALOG     = "datagroup_mdl"
GOLD_SCHEMA = "atlas"
GOLD        = f"{CATALOG}.{GOLD_SCHEMA}"
RUN_ID      = str(uuid.uuid4())
NOW         = datetime.utcnow()
TODAY       = date.today()

METRICS     = ["won_pipeline", "active_pipeline", "win_rate", "created_pipeline"]
HORIZONS    = [30, 60, 90]
HISTORY_DAYS = 180     # training window
HOLDOUT_DAYS = 30      # held out for MAPE

print(f"[Job3] Starting Forecast Scoring — {TODAY} | run_id={RUN_ID}")

# COMMAND ----------
# MAGIC %md ### Step 1 — Load history from gold layer

# COMMAND ----------

history_df = spark.table(f"{GOLD}.metrics_history").filter(
    (F.col("geo") == "All") &
    (F.col("channel") == "All") &
    (F.col("metric_key").isin(METRICS))
)

history_by_metric = {}
for m_key in METRICS:
    rows = (
        history_df.filter(F.col("metric_key") == m_key)
        .orderBy("metric_date")
        .select("metric_date", "metric_value")
        .collect()
    )
    if rows:
        dates  = [r["metric_date"] for r in rows]
        values = [float(r["metric_value"] or 0) for r in rows]
        history_by_metric[m_key] = (dates, values)
        print(f"[Job3] {m_key}: {len(values)} historical data points")
    else:
        print(f"[Job3] {m_key}: NO HISTORY — skipping")

# COMMAND ----------
# MAGIC %md ### Step 2 — Forecasting model implementations

# COMMAND ----------

def mape(actual, predicted):
    """Mean Absolute Percentage Error (ignores zeros in actuals)."""
    if len(actual) == 0: return 100.0
    errors = [abs((a - p) / a) * 100 for a, p in zip(actual, predicted) if a != 0]
    return float(np.mean(errors)) if errors else 100.0

def rmse(actual, predicted):
    diffs = [(a - p)**2 for a, p in zip(actual, predicted)]
    return float(sqrt(np.mean(diffs))) if diffs else 0.0


# ── Holt-Winters (double exponential smoothing with level + trend) ────────────
def holt_winters_forecast(values, horizon=90, alpha=0.3, beta=0.2):
    """Returns (forecast_list, alpha, beta)."""
    n = len(values)
    if n < 2:
        return [values[-1]] * horizon, alpha, beta
    level  = values[0]
    trend  = values[1] - values[0]
    result = []
    for v in values[1:]:
        prev_l, prev_t = level, trend
        level = alpha * v + (1 - alpha) * (prev_l + prev_t)
        trend = beta  * (level - prev_l) + (1 - beta) * prev_t
    for h in range(1, horizon + 1):
        result.append(level + h * trend)
    return result, alpha, beta


# ── Triple Smoothing (Holt-Winters with additive seasonality, period=13 weeks) ─
def triple_smoothing_forecast(values, horizon=90, alpha=0.3, beta=0.1, gamma=0.1, season=13):
    n = len(values)
    if n < 2 * season:
        return holt_winters_forecast(values, horizon)[0], alpha, beta
    # Initialise
    level = np.mean(values[:season])
    trend = (np.mean(values[season:2*season]) - np.mean(values[:season])) / season
    seasonal = [values[i] - level for i in range(season)]
    forecast = []
    lvl, trnd, seas = level, trend, seasonal[:]
    for i, v in enumerate(values):
        s_idx = i % season
        prev_l = lvl
        lvl   = alpha * (v - seas[s_idx]) + (1 - alpha) * (prev_l + trnd)
        trnd  = beta  * (lvl - prev_l)   + (1 - beta)  * trnd
        seas[s_idx] = gamma * (v - lvl) + (1 - gamma) * seas[s_idx]
    for h in range(1, horizon + 1):
        s_idx = (len(values) + h - 1) % season
        forecast.append(lvl + h * trnd + seas[s_idx])
    return forecast, alpha, beta


# ── ARMA (via statsmodels AR(2)MA(1), no seasonal) ───────────────────────────
def arma_forecast(values, horizon=90):
    try:
        from statsmodels.tsa.arima.model import ARIMA
        model  = ARIMA(values, order=(2, 0, 1)).fit()
        fc     = model.forecast(steps=horizon).tolist()
        return fc
    except Exception as e:
        print(f"[Job3] ARMA fallback: {e}")
        return holt_winters_forecast(values, horizon)[0]


# ── Linear + Seasonal (OLS regression with quarter-of-year indicator) ─────────
def linear_seasonal_forecast(values, horizon=90):
    n = len(values)
    if n < 10:
        return holt_winters_forecast(values, horizon)[0]
    x = np.arange(n)
    # Quarter-seasonal dummy (13-week periods)
    q = np.array([i // 13 % 4 for i in range(n)])
    X = np.column_stack([x, (q == 0).astype(float), (q == 1).astype(float), (q == 2).astype(float)])
    y = np.array(values)
    try:
        coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        forecast = []
        for h in range(1, horizon + 1):
            xi = n + h - 1
            qi = xi // 13 % 4
            xrow = np.array([xi, float(qi == 0), float(qi == 1), float(qi == 2)])
            forecast.append(float(np.dot(coeffs, xrow)))
        return forecast
    except Exception as e:
        print(f"[Job3] Linear-seasonal fallback: {e}")
        return holt_winters_forecast(values, horizon)[0]


def compute_trend_status(values, window=30):
    """Compare last 30 days slope to prior 30 days slope."""
    if len(values) < 60:
        return "stable"
    recent = np.polyfit(range(window), values[-window:], 1)[0]
    prior  = np.polyfit(range(window), values[-2*window:-window], 1)[0]
    if abs(recent) < 0.01 * (abs(values[-1]) + 1e-9):
        return "stable"
    if abs(recent - prior) < 0.05 * (abs(prior) + 1e-9):
        return "stable"
    if recent > 0 and recent > prior * 1.05:
        return "accelerating"
    if recent > 0 and recent < prior * 0.95:
        return "decelerating"
    if recent < 0 and abs(recent) > abs(prior) * 1.05:
        return "decelerating"
    if abs(recent) > abs(prior) * 2:
        return "volatile"
    return "stable"


def compute_risk_level(m: float) -> str:
    if m > 20: return "high"
    if m > 10: return "moderate"
    return "low"

# COMMAND ----------
# MAGIC %md ### Step 3 — Run models and select best by MAPE

# COMMAND ----------

MODELS = {
    "holt_winters":     lambda v, h: holt_winters_forecast(v, h)[0],
    "triple_smoothing": lambda v, h: triple_smoothing_forecast(v, h)[0],
    "arima":            lambda v, h: arma_forecast(v, h),
    "linear_seasonal":  lambda v, h: linear_seasonal_forecast(v, h),
}

try:
    from databricks.sdk import WorkspaceClient
    llm_client    = WorkspaceClient()
    LLM_AVAILABLE = True
except Exception:
    llm_client    = None
    LLM_AVAILABLE = False

SYSTEM_PROMPT = (
    "You are an enterprise sales analytics assistant. Given forecast data, produce "
    "concise executive-level analysis. Respond ONLY with valid JSON — no markdown, no code fences. "
    "Keys required: key_drivers (list of 3 strings), executive_actions (list of 3 strings), "
    "downside_risks (list of 3 strings), upside_opportunities (list of 3 strings), "
    "description (1-2 sentence narrative)."
)

all_result_rows = []

for m_key in METRICS:
    if m_key not in history_by_metric:
        continue

    dates, values = history_by_metric[m_key]

    # Use last HISTORY_DAYS + HOLDOUT_DAYS; if not enough data use what we have
    total_avail = len(values)
    if total_avail < 14:
        print(f"[Job3] {m_key}: insufficient data ({total_avail} pts) — skipping")
        continue

    train_end  = max(0, total_avail - HOLDOUT_DAYS)
    train_vals = values[:train_end]
    hold_vals  = values[train_end:]
    hdays      = min(HISTORY_DAYS, train_end)
    train_vals = train_vals[-hdays:]  # keep at most HISTORY_DAYS

    trend_status = compute_trend_status(values)

    # ── Evaluate each model ──────────────────────────────────────────────────
    best_model_name  = None
    best_mape        = 999.0
    best_forecast_90 = None

    for model_name, model_fn in MODELS.items():
        try:
            # Holdout MAPE
            hold_fc = model_fn(train_vals, len(hold_vals))
            m_val   = mape(hold_vals, hold_fc[:len(hold_vals)])

            # Full 90-day forecast using all available data
            fc_90   = model_fn(values, 90)

            print(f"[Job3] {m_key} | {model_name}: MAPE={m_val:.1f}%")

            if m_val < best_mape:
                best_mape       = m_val
                best_model_name = model_name
                best_forecast_90 = fc_90
        except Exception as e:
            print(f"[Job3] {m_key} | {model_name}: ERROR — {e}")
            continue

    if best_forecast_90 is None:
        print(f"[Job3] {m_key}: all models failed — skipping")
        continue

    risk_level    = compute_risk_level(best_mape)
    model_conf    = max(0.0, min(1.0, 1.0 - best_mape / 100.0))

    # Confidence intervals (±1.5σ for worst/best based on last 30-day std dev)
    std_dev       = float(np.std(values[-30:] if len(values) >= 30 else values))
    scale         = 1.5

    most_likely_90 = float(best_forecast_90[89] if len(best_forecast_90) >= 90 else best_forecast_90[-1])
    best_case_90   = most_likely_90 + scale * std_dev
    worst_case_90  = most_likely_90 - scale * std_dev
    upside_dollar  = best_case_90 - most_likely_90
    downside_dollar = most_likely_90 - worst_case_90

    # ── LLM 4-box text ────────────────────────────────────────────────────────
    if LLM_AVAILABLE and llm_client:
        prompt = (
            f"Metric: {m_key.replace('_', ' ').title()}\n"
            f"Current value: {values[-1]:,.0f}\n"
            f"90-day most likely forecast: {most_likely_90:,.0f}\n"
            f"90-day best case: {best_case_90:,.0f}\n"
            f"90-day worst case: {worst_case_90:,.0f}\n"
            f"Trend: {trend_status}\n"
            f"Risk level: {risk_level}\n"
            f"Best model: {best_model_name} (MAPE {best_mape:.1f}%)\n"
            "Generate the forecast intelligence JSON."
        )
        try:
            resp = llm_client.serving_endpoints.query(
                name="databricks-claude-sonnet-4-6",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=500,
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```json?\n?", "", raw).rstrip("`").strip()
            intel = json.loads(raw)
        except Exception as e:
            print(f"[Job3] LLM call failed for {m_key}: {e}")
            intel = {}
    else:
        intel = {}

    key_drivers     = intel.get("key_drivers",     [f"Trend is {trend_status}", f"MAPE {best_mape:.0f}%", f"Model: {best_model_name}"])
    exec_actions    = intel.get("executive_actions",[f"Review {m_key} pipeline",  "Accelerate top deals", "Schedule exec check-in"])
    down_risks      = intel.get("downside_risks",   ["Market softness", "Deal slippage", "Reduced conversion"])
    upside_opps     = intel.get("upside_opportunities", ["Accelerated close cycles", "Expanded deal sizes", "New channel momentum"])
    description     = intel.get("description",      f"{m_key.replace('_',' ').title()} is trending {trend_status} with {risk_level} risk.")

    # ── Write a row per horizon per model ─────────────────────────────────────
    for horizon in HORIZONS:
        fc_val = float(best_forecast_90[horizon - 1] if len(best_forecast_90) >= horizon else best_forecast_90[-1])
        # Simple proportional CI scaling
        h_scale = (horizon / 90) ** 0.5
        lb = fc_val - scale * std_dev * h_scale
        ub = fc_val + scale * std_dev * h_scale

        all_result_rows.append({
            "forecast_run_id":    RUN_ID,
            "metric_key":         m_key,
            "model_name":         best_model_name,
            "horizon_days":       horizon,
            "forecast_date":      (TODAY + timedelta(days=horizon)),
            "forecast_value":     fc_val,
            "lower_bound":        lb,
            "upper_bound":        ub,
            "mape":               best_mape,
            "rmse":               rmse(hold_vals, best_forecast_90[:len(hold_vals)]),
            "model_confidence":   model_conf,
            "trend_status":       trend_status,
            "risk_level":         risk_level,
            "best_case_90d":      best_case_90,
            "worst_case_90d":     worst_case_90,
            "most_likely_90d":    most_likely_90,
            "upside_dollar":      upside_dollar,
            "downside_dollar":    downside_dollar,
            "description":        description,
            "key_drivers":        json.dumps(key_drivers),
            "executive_actions":  json.dumps(exec_actions),
            "downside_risks":     json.dumps(down_risks),
            "upside_opportunities": json.dumps(upside_opps),
            "history_days":       len(values),
            "geo":                "All",
            "generated_at":       NOW,
            "model_version":      1,
        })

print(f"[Job3] Built {len(all_result_rows)} forecast rows")

# COMMAND ----------
# MAGIC %md ### Step 4 — Write to atlas.forecast_results

# COMMAND ----------

if all_result_rows:
    result_df = spark.createDataFrame(all_result_rows)
    result_view = f"atlas_forecast_stage_{RUN_ID[:8]}"
    result_df.createOrReplaceTempView(result_view)

    spark.sql(f"""
        MERGE INTO {GOLD}.forecast_results AS t
        USING {result_view} AS s
        ON  t.metric_key   = s.metric_key
        AND t.model_name   = s.model_name
        AND t.horizon_days = s.horizon_days
        AND t.geo          = s.geo
        AND CAST(t.generated_at AS DATE) = CAST(s.generated_at AS DATE)
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    print(f"[Job3] Written {len(all_result_rows)} rows to {GOLD}.forecast_results")
else:
    print("[Job3] No forecast rows produced")

print("[Job3] Forecast Scoring COMPLETE ✓")
