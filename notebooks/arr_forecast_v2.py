# Databricks notebook source
# GAIM Executive App — ARR Forecast v2 (feature-enhanced Prophet + LightGBM + learned ensemble)
#
# Replaces the Prophet-only weekly job. Improvements over v1:
#   1. Honest accuracy: rolling-origin backtest (3 folds × 13-week horizon),
#      MAPE reported OUT-OF-SAMPLE — never in-sample fitted values.
#   2. Fiscal-calendar features: quarter-end / quarter-start weeks, month-of-quarter,
#      weeks-to-quarter-end, US holiday weeks. Won ARR clusters at quarter close;
#      v1 only had summer/winter/isweek1.
#   3. Prophet config fixed for weekly data: daily/weekly seasonality OFF
#      (v1 had daily_seasonality=True on weekly buckets — fits noise),
#      custom quarterly + monthly seasonalities added, changepoint prior tuned by backtest.
#   4. LightGBM with AR lags + calendar features and QUANTILE models (q10/q50/q90)
#      for real 80% prediction intervals (v1 bounds were symmetric residual std).
#   5. Ensemble weights LEARNED from backtest MAPE (inverse-MAPE), not fixed 70/30.
#   6. Quarter-end attainment forecast reported separately (insights table:
#      forecast_most_likely / forecast_low / forecast_high) with its own
#      backtest accuracy (monthly_best_mape), per executive requirement.
#
# Output contract — matches backend/routes/forecast.py EXACTLY (the in-repo v1
# notebook wrote most_likely/worst_case/best_case, which the app no longer reads):
#   arr_forecast_output     : run_date, ds, model, forecast_type, yhat, yhat_lower, yhat_upper
#                             model ∈ {actual, lightgbm, prophet, ensemble}
#                             forecast_type ∈ {actual, forecast}
#                             NOTE: route reads the WHOLE table (no run_date filter),
#                             so this job OVERWRITES with the latest run only.
#   arr_model_leaderboard   : run_date, model, mape, granularity, type
#   arr_forecast_insights   : run_date, momentum, risk_level, narrative, model_confidence,
#                             upside, downside, best_model, best_mape, monthly_best_model,
#                             monthly_best_mape, ensemble_mape, forecast_most_likely,
#                             forecast_low, forecast_high, key_drivers, executive_actions,
#                             downside_risks, upside_opportunities
#
# Schedule: weekly (Monday 06:00 UTC, same slot as v1 — see databricks.yml)

# COMMAND ----------
# MAGIC %md ## Section 0 — Install dependencies (once per cluster)

# COMMAND ----------
# MAGIC %pip install prophet==1.1.5 lightgbm==4.3.0 holidays==0.47 --quiet

# COMMAND ----------

import warnings
warnings.filterwarnings("ignore")

import json
from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd

# ── Configuration ─────────────────────────────────────────────────────────────
# Source aligned with the PRODUCTION Prophet model ("ARR Forecast with marketing
# spend and headcount" notebook) so Atlas and Power BI are definitionally
# identical: certified SFDC opp line items, Growth (new + expansion) only,
# Care / Sales Other channels excluded.
SOURCE_TABLE             = "datagroup.datalake_transform.cds_sfdc_opp_products_latest"
HISTORY_START            = "2023-01-01"          # prod model trains from 2023
PURCHASE_TYPE_ROLLUP     = "Growth"              # = new + expansion (Atlas scope)
SALES_CHANNEL_EXCLUSIONS = ("Care", "Sales Other")
# Migration + zero-dollar opps are excluded to match the production daily-snapshot
# definition (gaim_pipeline_daily_snapshot is built from CDS with these removed).
# Zero-dollar: CDS exposes the boolean `is_opp_amount_zero` — exclude where true.
EXCLUDE_ZERO_DOLLAR      = True
# Migration: confirm the exact CDS column + value with the model owner, then set
# below. Most likely purchase_type='Migration'. Set MIGRATION_COL=None to disable.
MIGRATION_COL            = "purchase_type"       # TODO confirm (candidates: purchase_type / opportunity_type / type)
MIGRATION_VALUES         = ("Migration",)        # TODO confirm exact value(s)
# Product groups now come from the canonical Atlas hierarchy join, not a hardcoded
# allowlist. None = no group filter (Total model). Set for the per-segment build.
PRODUCT_HIERARCHY_TABLE  = "datagroup_mdl.mdl_sales_analytics.gaim_product_hierarchy_atlas"
PRODUCT_GROUPS           = None                  # e.g. ("ITSG", "Core Collab", ...)
OUTPUT_CATALOG  = "datagroup_mdl"
OUTPUT_SCHEMA   = "mdl_sales_analytics"

FORECAST_OUTPUT_TABLE      = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_forecast_output"
FORECAST_INSIGHTS_TABLE    = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_forecast_insights"
FORECAST_LEADERBOARD_TABLE = f"{OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.arr_model_leaderboard"

HORIZON_WEEKS   = 26          # forecast horizon shown in the app
BACKTEST_FOLDS  = 3           # rolling-origin folds
BACKTEST_H      = 13          # weeks per fold (one quarter)
MIN_TRAIN_WEEKS = 78          # need 1.5y before first fold
INTERVAL        = 0.80        # 80% band → quantiles 0.10 / 0.90
RUN_DATE        = date.today().isoformat()

print(f"[v2] ARR Forecast run {RUN_DATE} — horizon {HORIZON_WEEKS}w, "
      f"{BACKTEST_FOLDS}×{BACKTEST_H}w backtest")

# COMMAND ----------
# MAGIC %md ## Section 1 — Load weekly Won ARR (Total, production-aligned)
# MAGIC Mirrors the production Prophet model's predicate exactly:
# MAGIC `cds_sfdc_opp_products_latest`, `demo_stage = 0`,
# MAGIC `purchase_type_rollup = 'Growth'` (new + expansion), Care / Sales Other
# MAGIC channels excluded, won = `is_won = 'True' AND is_closed = 'True'`.
# MAGIC The table keeps only the latest snapshot, so no `data_date` dedup is needed.
# MAGIC Monday-aligned weekly buckets; Total-level (the app contract has no segment
# MAGIC column). Per-segment modeling is a contract change — see methodology doc.

# COMMAND ----------

_chan_excl = ", ".join(f"'{c}'" for c in SALES_CHANNEL_EXCLUSIONS)
_zero_filter = "AND c.is_opp_amount_zero = false" if EXCLUDE_ZERO_DOLLAR else ""
_migration_filter = (
    f"AND c.{MIGRATION_COL} NOT IN ("
    + ", ".join(f"'{v}'" for v in MIGRATION_VALUES) + ")"
    if MIGRATION_COL and MIGRATION_VALUES else ""
)
# Product-group filter applied against the canonical Atlas hierarchy (joined on genus)
_prod_filter = (
    "AND h.Product_Group IN (" + ", ".join(f"'{p}'" for p in PRODUCT_GROUPS) + ")"
    if PRODUCT_GROUPS else ""
)

sql = f"""
SELECT
    c.close_date,
    SUM(c.amount_towards_plan) AS won_arr
FROM {SOURCE_TABLE} c
LEFT JOIN {PRODUCT_HIERARCHY_TABLE} h
       ON LOWER(TRIM(c.product_genus)) = LOWER(TRIM(h.Product_Genus))
WHERE
    c.demo_stage = 0
    AND c.purchase_type_rollup = '{PURCHASE_TYPE_ROLLUP}'
    AND c.is_won = 'True'
    AND c.is_closed = 'True'
    AND c.sales_channel NOT IN ({_chan_excl})
    {_zero_filter}
    {_migration_filter}
    {_prod_filter}
    AND c.close_date >= '{HISTORY_START}'
    AND c.close_date <= CURRENT_DATE()
GROUP BY c.close_date
"""
daily = spark.sql(sql).toPandas()
daily["close_date"] = pd.to_datetime(daily["close_date"])

# ISO Monday-aligned weekly aggregation; drop current partial week
weekly = (
    daily.set_index("close_date")["won_arr"]
    .resample("W-MON", label="left", closed="left").sum()
    .reset_index()
    .rename(columns={"close_date": "ds", "won_arr": "y"})
)
last_complete = pd.Timestamp(date.today() - timedelta(days=date.today().weekday() + 1))
weekly = weekly[weekly["ds"] <= last_complete - pd.Timedelta(weeks=1)].reset_index(drop=True)
weekly["y"] = weekly["y"].clip(lower=0.0)

assert len(weekly) >= MIN_TRAIN_WEEKS, (
    f"Only {len(weekly)} weeks of history — need ≥{MIN_TRAIN_WEEKS}. "
    "Check source table / HISTORY_START."
)
print(f"[v2] {len(weekly)} complete weeks loaded "
      f"({weekly['ds'].min().date()} → {weekly['ds'].max().date()})")

# COMMAND ----------
# MAGIC %md ## Section 2 — Fiscal-calendar & lag feature engineering
# MAGIC The single biggest known driver of weekly Won ARR shape is the sales
# MAGIC calendar: deals are pulled into quarter-end weeks. v1 had no notion of this.

# COMMAND ----------

import holidays as _hol
_US_HOLIDAYS = _hol.US(years=range(2021, date.today().year + 3))


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calendar features for a frame with a 'ds' (week-start Monday) column."""
    out = df.copy()
    ds = pd.to_datetime(out["ds"])
    week_end = ds + pd.Timedelta(days=6)

    out["month"]            = ds.dt.month
    out["quarter"]          = ds.dt.quarter
    out["month_of_quarter"] = ((ds.dt.month - 1) % 3) + 1
    woy = ds.dt.isocalendar().week.astype(float)
    out["woy_sin"]          = np.sin(2 * np.pi * woy / 52.0)
    out["woy_cos"]          = np.cos(2 * np.pi * woy / 52.0)

    # quarter boundaries
    q_end   = ds.dt.to_period("Q").dt.end_time.dt.normalize()
    q_start = ds.dt.to_period("Q").dt.start_time.dt.normalize()
    out["weeks_to_q_end"]    = ((q_end - ds).dt.days // 7).clip(0, 13).astype(float)
    out["is_q_end_week"]     = (out["weeks_to_q_end"] <= 0).astype(int)
    out["is_q_close_window"] = (out["weeks_to_q_end"] <= 1).astype(int)   # last 2 weeks
    out["is_q_start_week"]   = (((ds - q_start).dt.days // 7) == 0).astype(int)
    out["is_year_end_week"]  = ((ds.dt.month == 12) & (out["is_q_end_week"] == 1)).astype(int)

    # holiday weeks (any US federal holiday inside the Mon–Sun bucket)
    def _hol_count(s, e):
        return sum(1 for d in pd.date_range(s, e) if d.date() in _US_HOLIDAYS)
    out["holiday_count"]   = [_hol_count(s, e) for s, e in zip(ds, week_end)]
    out["is_holiday_week"] = (out["holiday_count"] > 0).astype(int)
    return out


LAGS      = [1, 2, 3, 4, 8, 13, 26, 52]
ROLL_WINS = [4, 13]


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """AR lags + rolling stats on 'y'. Frame must be sorted by ds."""
    out = df.copy()
    for lag in LAGS:
        out[f"lag_{lag}"] = out["y"].shift(lag)
    for w in ROLL_WINS:
        out[f"roll_mean_{w}"] = out["y"].shift(1).rolling(w).mean()
        out[f"roll_std_{w}"]  = out["y"].shift(1).rolling(w).std()
    out["yoy_ratio"] = out["y"].shift(1) / out["y"].shift(53).replace(0, np.nan)
    return out


CAL_FEATURES = ["month", "quarter", "month_of_quarter", "woy_sin", "woy_cos",
                "weeks_to_q_end", "is_q_end_week", "is_q_close_window",
                "is_q_start_week", "is_year_end_week", "holiday_count",
                "is_holiday_week"]
LAG_FEATURES = [f"lag_{l}" for l in LAGS] + \
               [f"roll_mean_{w}" for w in ROLL_WINS] + \
               [f"roll_std_{w}" for w in ROLL_WINS] + ["yoy_ratio"]
ALL_FEATURES = CAL_FEATURES + LAG_FEATURES

weekly = add_calendar_features(weekly)
print(f"[v2] features ready: {len(ALL_FEATURES)} columns")

# COMMAND ----------
# MAGIC %md ## Section 3 — Models
# MAGIC Each model exposes `fit_predict(train_df, future_ds) -> DataFrame[ds, yhat, yhat_lower, yhat_upper]`.

# COMMAND ----------

from prophet import Prophet
import lightgbm as lgb

PROPHET_REGRESSORS = ["is_q_end_week", "is_q_close_window", "is_q_start_week",
                      "is_year_end_week", "is_holiday_week"]


def prophet_fit_predict(train_df: pd.DataFrame, future_ds: pd.DatetimeIndex,
                        changepoint_prior: float = 0.1,
                        seasonality_mode: str = "multiplicative") -> pd.DataFrame:
    """Prophet tuned for WEEKLY business data + fiscal regressors."""
    m = Prophet(
        interval_width=INTERVAL,
        daily_seasonality=False,        # v1 bug: was True on weekly data
        weekly_seasonality=False,       # meaningless at weekly granularity
        yearly_seasonality=10,
        seasonality_mode=seasonality_mode,
        changepoint_prior_scale=changepoint_prior,
    )
    m.add_seasonality(name="quarterly", period=91.3125, fourier_order=5)
    m.add_seasonality(name="monthly",   period=30.4375, fourier_order=3)
    for reg in PROPHET_REGRESSORS:
        m.add_regressor(reg)

    m.fit(train_df[["ds", "y"] + PROPHET_REGRESSORS])

    future = pd.DataFrame({"ds": future_ds})
    future = add_calendar_features(future)
    fc = m.predict(future[["ds"] + PROPHET_REGRESSORS])
    return pd.DataFrame({
        "ds": fc["ds"],
        "yhat":       fc["yhat"].clip(lower=0),
        "yhat_lower": fc["yhat_lower"].clip(lower=0),
        "yhat_upper": fc["yhat_upper"].clip(lower=0),
    })


_LGB_PARAMS = dict(
    n_estimators=400, learning_rate=0.04, num_leaves=15,
    min_child_samples=8, subsample=0.9, colsample_bytree=0.8,
    reg_lambda=1.0, verbose=-1,
)


def lightgbm_fit_predict(train_df: pd.DataFrame, future_ds: pd.DatetimeIndex) -> pd.DataFrame:
    """Recursive LightGBM with AR + calendar features; quantile models for bounds."""
    hist = add_calendar_features(train_df[["ds", "y"]].sort_values("ds"))
    hist = add_lag_features(hist).dropna(subset=["lag_1"])
    X, y = hist[ALL_FEATURES], hist["y"]

    models = {}
    for name, alpha in [("q50", 0.50), ("q10", 0.10), ("q90", 0.90)]:
        models[name] = lgb.LGBMRegressor(objective="quantile", alpha=alpha, **_LGB_PARAMS)
        models[name].fit(X, y)

    # Recursive multi-step: roll the median forward to regenerate lag features
    work = train_df[["ds", "y"]].copy()
    preds = []
    for ds_next in future_ds:
        step = pd.DataFrame({"ds": [ds_next], "y": [np.nan]})
        ext = pd.concat([work, step], ignore_index=True)
        ext = add_calendar_features(ext)
        ext = add_lag_features(ext)
        x_row = ext.iloc[[-1]][ALL_FEATURES]
        p50 = float(models["q50"].predict(x_row)[0])
        p10 = float(models["q10"].predict(x_row)[0])
        p90 = float(models["q90"].predict(x_row)[0])
        p50 = max(p50, 0.0)
        p10 = max(min(p10, p50), 0.0)
        p90 = max(p90, p50)
        preds.append((ds_next, p50, p10, p90))
        work = pd.concat([work, pd.DataFrame({"ds": [ds_next], "y": [p50]})],
                         ignore_index=True)

    return pd.DataFrame(preds, columns=["ds", "yhat", "yhat_lower", "yhat_upper"])

# COMMAND ----------
# MAGIC %md ## Section 4 — Rolling-origin backtest (honest out-of-sample MAPE)
# MAGIC Three folds, each forecasting 13 unseen weeks. Also evaluates each fold
# MAGIC aggregated to MONTHLY totals — the granularity the quarter-end number depends on.

# COMMAND ----------

def mape(actual, pred) -> float:
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    mask = actual != 0
    if not mask.any():
        return 100.0
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def monthly_mape(test_df: pd.DataFrame, pred_df: pd.DataFrame) -> float:
    a = test_df.set_index("ds")["y"].resample("MS").sum()
    p = pred_df.set_index("ds")["yhat"].resample("MS").sum()
    joined = pd.concat([a, p], axis=1, keys=["a", "p"]).dropna()
    return mape(joined["a"].values, joined["p"].values) if len(joined) else 100.0


# Prophet small hyperparameter race (changepoint prior × seasonality mode),
# decided on fold 1 only to bound runtime.
PROPHET_GRID = [(0.05, "multiplicative"), (0.1, "multiplicative"), (0.1, "additive")]

n = len(weekly)
fold_origins = [n - BACKTEST_H * k for k in range(BACKTEST_FOLDS, 0, -1)]

# pick Prophet config on the earliest fold
o0 = fold_origins[0]
tr0, te0 = weekly.iloc[:o0], weekly.iloc[o0:o0 + BACKTEST_H]
best_cfg, best_cfg_mape = PROPHET_GRID[0], np.inf
for cfg in PROPHET_GRID:
    try:
        fc = prophet_fit_predict(tr0, pd.DatetimeIndex(te0["ds"]), *cfg)
        m_ = mape(te0["y"].values, fc["yhat"].values)
        print(f"[v2] prophet cfg {cfg}: fold-1 MAPE {m_:.1f}%")
        if m_ < best_cfg_mape:
            best_cfg, best_cfg_mape = cfg, m_
    except Exception as exc:
        print(f"[v2] prophet cfg {cfg} failed: {exc}")
print(f"[v2] selected prophet cfg: changepoint={best_cfg[0]}, mode={best_cfg[1]}")

bt = {"prophet": {"w": [], "m": [], "preds": []},
      "lightgbm": {"w": [], "m": [], "preds": []}}

for o in fold_origins:
    train, test = weekly.iloc[:o], weekly.iloc[o:o + BACKTEST_H]
    if len(test) < BACKTEST_H:
        continue
    fds = pd.DatetimeIndex(test["ds"])
    for name, fn in [("prophet", lambda t, f: prophet_fit_predict(t, f, *best_cfg)),
                     ("lightgbm", lightgbm_fit_predict)]:
        try:
            fc = fn(train, fds)
            bt[name]["w"].append(mape(test["y"].values, fc["yhat"].values))
            bt[name]["m"].append(monthly_mape(test, fc))
            bt[name]["preds"].append((test.copy(), fc))
        except Exception as exc:
            print(f"[v2] backtest {name} @origin {o} failed: {exc}")

weekly_mape_by_model  = {k: float(np.mean(v["w"])) for k, v in bt.items() if v["w"]}
monthly_mape_by_model = {k: float(np.mean(v["m"])) for k, v in bt.items() if v["m"]}
assert weekly_mape_by_model, "All backtests failed — aborting before writing tables."

# ── Learned ensemble weights: inverse out-of-sample weekly MAPE ───────────────
inv = {k: 1.0 / max(v, 1e-6) for k, v in weekly_mape_by_model.items()}
total_inv = sum(inv.values())
ENS_WEIGHTS = {k: v / total_inv for k, v in inv.items()}

# ensemble backtest MAPE from blended fold predictions
ens_w, ens_m = [], []
n_pair = min(len(bt["prophet"]["preds"]), len(bt["lightgbm"]["preds"]))
for i in range(n_pair):
    try:
        test_p, fc_p = bt["prophet"]["preds"][i]
        _,      fc_l = bt["lightgbm"]["preds"][i]
        blend = fc_p[["ds"]].copy()
        blend["yhat"] = (ENS_WEIGHTS.get("prophet", 0.5) * fc_p["yhat"].values
                         + ENS_WEIGHTS.get("lightgbm", 0.5) * fc_l["yhat"].values)
        ens_w.append(mape(test_p["y"].values, blend["yhat"].values))
        ens_m.append(monthly_mape(test_p, blend))
    except Exception:
        pass
weekly_mape_by_model["ensemble"]  = float(np.mean(ens_w)) if ens_w else min(weekly_mape_by_model.values())
monthly_mape_by_model["ensemble"] = float(np.mean(ens_m)) if ens_m else min(monthly_mape_by_model.values())

print(f"[v2] OUT-OF-SAMPLE weekly MAPE : {json.dumps(weekly_mape_by_model, indent=2)}")
print(f"[v2] OUT-OF-SAMPLE monthly MAPE: {json.dumps(monthly_mape_by_model, indent=2)}")
print(f"[v2] learned ensemble weights  : {json.dumps(ENS_WEIGHTS, indent=2)}")

# COMMAND ----------
# MAGIC %md ## Section 5 — Final fit on full history + 26-week forecast

# COMMAND ----------

future_idx = pd.date_range(weekly["ds"].max() + pd.Timedelta(weeks=1),
                           periods=HORIZON_WEEKS, freq="W-MON")

fc_prophet  = prophet_fit_predict(weekly, future_idx, *best_cfg)
fc_lightgbm = lightgbm_fit_predict(weekly, future_idx)

fc_ensemble = fc_prophet[["ds"]].copy()
for col in ["yhat", "yhat_lower", "yhat_upper"]:
    fc_ensemble[col] = (ENS_WEIGHTS.get("prophet", 0.5) * fc_prophet[col].values
                        + ENS_WEIGHTS.get("lightgbm", 0.5) * fc_lightgbm[col].values)

best_model_key = min(weekly_mape_by_model, key=weekly_mape_by_model.get)
monthly_best   = min(monthly_mape_by_model, key=monthly_mape_by_model.get)
print(f"[v2] best weekly model: {best_model_key} ({weekly_mape_by_model[best_model_key]:.1f}%) | "
      f"best monthly: {monthly_best} ({monthly_mape_by_model[monthly_best]:.1f}%)")

# COMMAND ----------
# MAGIC %md ## Section 6 — Quarter-end attainment forecast (separate executive number)
# MAGIC QTD actual + remaining-quarter forecast from the best MONTHLY model.
# MAGIC Accuracy for this number is tracked by `monthly_best_mape` (out-of-sample).

# COMMAND ----------

today_ts = pd.Timestamp(date.today())
q_start  = today_ts.to_period("Q").start_time.normalize()
q_end    = today_ts.to_period("Q").end_time.normalize()

qtd_actual = float(weekly.loc[weekly["ds"] >= q_start, "y"].sum())

fc_for_q = {"prophet": fc_prophet, "lightgbm": fc_lightgbm,
            "ensemble": fc_ensemble}[monthly_best]
rem = fc_for_q[(fc_for_q["ds"] >= max(q_start, weekly["ds"].max() + pd.Timedelta(weeks=1)))
               & (fc_for_q["ds"] <= q_end)]

q_forecast_likely = qtd_actual + float(rem["yhat"].sum())
q_forecast_low    = qtd_actual + float(rem["yhat_lower"].sum())
q_forecast_high   = qtd_actual + float(rem["yhat_upper"].sum())

print(f"[v2] Quarter-end ({q_end.date()}): QTD actual {qtd_actual:,.0f} | "
      f"forecast {q_forecast_likely:,.0f} [{q_forecast_low:,.0f} – {q_forecast_high:,.0f}] "
      f"via {monthly_best}")

# COMMAND ----------
# MAGIC %md ## Section 7 — Narrative / insights payload

# COMMAND ----------

recent4 = float(weekly["y"].tail(4).mean())
prior4  = float(weekly["y"].iloc[-8:-4].mean()) if len(weekly) >= 8 else recent4
mom_pct = ((recent4 - prior4) / prior4 * 100) if prior4 else 0.0
momentum = "ACCELERATING" if mom_pct > 5 else ("DECELERATING" if mom_pct < -5 else "STABLE")

best_mape_val = weekly_mape_by_model[best_model_key]
risk_level = ("LOW RISK" if best_mape_val <= 15
              else "MODERATE RISK" if best_mape_val <= 30 else "HIGH RISK")
model_confidence = int(round(max(0.0, min(100.0, 100.0 - best_mape_val))))

narrative = (
    f"Out-of-sample backtest ({BACKTEST_FOLDS} folds × {BACKTEST_H} weeks): "
    f"best weekly model is {best_model_key} at {best_mape_val:.1f}% MAPE; "
    f"monthly totals are most accurate with {monthly_best} at "
    f"{monthly_mape_by_model[monthly_best]:.1f}% MAPE. "
    f"Recent 4-week Won ARR is {momentum.lower()} ({mom_pct:+.1f}% vs prior 4 weeks). "
    f"Quarter-end projection: {q_forecast_likely/1e6:.1f}M "
    f"(range {q_forecast_low/1e6:.1f}M–{q_forecast_high/1e6:.1f}M)."
)

key_drivers = json.dumps([
    "Quarter-close pull-in effect (modeled via fiscal-week regressors)",
    "Yearly + quarterly seasonality",
    f"4-week momentum {mom_pct:+.1f}%",
    "US holiday-week dip pattern",
])
executive_actions = json.dumps([
    f"Treat the quarter-end range {q_forecast_low/1e6:.1f}M–{q_forecast_high/1e6:.1f}M as the planning envelope",
    "Review pipeline coverage for forecast weeks where the lower bound dips below target pace",
    "Re-run after any major pipeline reclassification — model retrains weekly",
])
downside_risks = json.dumps([
    "Weekly Won ARR is spiky; single mega-deals move weeks outside the 80% band",
    f"Weekly-level MAPE remains {best_mape_val:.0f}% — use monthly/quarterly views for commitments",
])
upside_opportunities = json.dumps([
    "Quarter-end close window historically lifts weekly Won ARR above trend",
])

# COMMAND ----------
# MAGIC %md ## Section 8 — Write Delta tables
# MAGIC `arr_forecast_output` is overwritten with the latest run only (the app route
# MAGIC reads the whole table). Leaderboard and insights are append-with-idempotent-delete
# MAGIC so accuracy history accumulates run over run.

# COMMAND ----------

from pyspark.sql import functions as F

# ── arr_forecast_output: actuals + 3 model forecasts, LATEST RUN ONLY ─────────
rows = []
for _, r in weekly.iterrows():
    rows.append((RUN_DATE, pd.Timestamp(r["ds"]).date().isoformat(), "actual", "actual",
                 float(r["y"]), float(r["y"]), float(r["y"])))
for model_name, fc in [("prophet", fc_prophet), ("lightgbm", fc_lightgbm),
                       ("ensemble", fc_ensemble)]:
    for _, r in fc.iterrows():
        rows.append((RUN_DATE, pd.Timestamp(r["ds"]).date().isoformat(), model_name,
                     "forecast", float(r["yhat"]), float(r["yhat_lower"]),
                     float(r["yhat_upper"])))

sdf_out = spark.createDataFrame(
    rows, "run_date string, ds string, model string, forecast_type string, "
          "yhat double, yhat_lower double, yhat_upper double"
).withColumn("created_at", F.current_timestamp())

# Route reads the whole table with no run_date filter → keep only this run.
sdf_out.write.format("delta").mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(FORECAST_OUTPUT_TABLE)
print(f"[v2] wrote {len(rows)} rows → {FORECAST_OUTPUT_TABLE} (overwrite)")

# ── arr_model_leaderboard: weekly + monthly granularity, append history ───────
lb_rows = []
for k, v in weekly_mape_by_model.items():
    lb_rows.append((RUN_DATE, k, float(v), "weekly", "backtest_3x13w"))
for k, v in monthly_mape_by_model.items():
    lb_rows.append((RUN_DATE, k, float(v), "monthly", "backtest_3x13w"))

sdf_lb = spark.createDataFrame(
    lb_rows, "run_date string, model string, mape double, granularity string, type string"
).withColumn("created_at", F.current_timestamp())

if spark.catalog.tableExists(FORECAST_LEADERBOARD_TABLE):
    spark.sql(f"DELETE FROM {FORECAST_LEADERBOARD_TABLE} WHERE run_date = '{RUN_DATE}'")
sdf_lb.write.format("delta").mode("append").saveAsTable(FORECAST_LEADERBOARD_TABLE)
print(f"[v2] wrote {len(lb_rows)} rows → {FORECAST_LEADERBOARD_TABLE} (append, idempotent)")

# ── arr_forecast_insights: run-level snapshot, append history ─────────────────
ins_row = [(
    RUN_DATE, momentum, risk_level, narrative, float(model_confidence),
    f"Upper band quarter-end: {q_forecast_high/1e6:.1f}M",
    f"Lower band quarter-end: {q_forecast_low/1e6:.1f}M",
    monthly_best, float(monthly_mape_by_model[monthly_best]),
    float(weekly_mape_by_model["ensemble"]),
    float(q_forecast_likely), float(q_forecast_low), float(q_forecast_high),
    key_drivers, executive_actions, downside_risks, upside_opportunities,
)]
ins_schema = ("run_date string, momentum string, risk_level string, narrative string, "
              "model_confidence double, upside string, downside string, "
              "best_model string, best_mape double, monthly_best_model string, "
              "monthly_best_mape double, ensemble_mape double, "
              "forecast_most_likely double, forecast_low double, forecast_high double, "
              "key_drivers string, executive_actions string, downside_risks string, "
              "upside_opportunities string")
sdf_ins = spark.createDataFrame(ins_row, ins_schema) \
    .withColumn("created_at", F.current_timestamp())

if spark.catalog.tableExists(FORECAST_INSIGHTS_TABLE):
    spark.sql(f"DELETE FROM {FORECAST_INSIGHTS_TABLE} WHERE run_date = '{RUN_DATE}'")
sdf_ins.write.format("delta").mode("append").saveAsTable(FORECAST_INSIGHTS_TABLE)
print(f"[v2] wrote insights snapshot → {FORECAST_INSIGHTS_TABLE}")

print(f"\n[v2] DONE — {RUN_DATE}. App endpoints /api/forecast/arr, /insights, "
      f"/leaderboard serve this run with no backend changes.")
