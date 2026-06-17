# Databricks notebook source
# MAGIC %md
# MAGIC # ARR Forecast — 4-Model Ensemble
# MAGIC **ETS · Prophet · LightGBM · Chronos**
# MAGIC
# MAGIC - **Target**: Weekly new ARR bookings per product
# MAGIC - **Horizon**: 13 weeks (1 quarter)
# MAGIC - **No external regressors** — pure univariate time series
# MAGIC - **Ensemble**: MAPE-weighted blend of all 4 models
# MAGIC - **Output**: `datagroup_mdl.mdl_sales_analytics.arr_forecast_ensemble` Delta table

# COMMAND ----------
import subprocess
subprocess.check_call(["pip", "install", "prophet", "lightgbm", "chronos-forecasting", "statsmodels", "-q"])

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
# ── 0. CONFIGURATION ─────────────────────────────────────────────────────────
import warnings
warnings.filterwarnings("ignore")

# Catalog / schema
CATALOG        = "datalake_transform"
SCHEMA         = "default"
OPP_TABLE      = f"{CATALOG}.cds_sfdc_opp_products_latest"

GOLD_CATALOG   = "datagroup_mdl"
GOLD_SCHEMA    = "mdl_sales_analytics"
OUTPUT_TABLE   = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.arr_forecast_ensemble"
LEADERBOARD_TABLE = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.arr_forecast_leaderboard"

# Forecast config
FORECAST_WEEKS = 13          # 1-quarter horizon
TRAIN_START    = "2022-01-01"
MIN_HISTORY_WK = 26          # minimum weeks of history to fit a model

# Sales channels to include
CHANNEL_EXCLUSIONS = ["Care", "Sales Other"]
PURCHASE_TYPE      = "Growth"

# Products to forecast (map raw product_genus → display)
PRODUCT_MAP = {
    "GoToConnect":   "GoTo Connect",
    "GoTo Resolve":  "GoTo Resolve",
    "GoToWebinar":   "GoTo Engage",
    "Central":       "GoTo Central",
    "Rescue":        "Rescue",
}

print("✓ Configuration loaded")

# COMMAND ----------
# ── 1. DATA LOADING ───────────────────────────────────────────────────────────
import pyspark.sql.functions as F
from pyspark.sql.window import Window

sql = f"""
SELECT
    salesforce_opportunity_line_item_id,
    is_closed,
    is_won,
    close_date,
    pipeline_entered_date,
    sales_market,
    sales_channel,
    owner_id,
    amount_towards_plan,
    product_genus,
    product_group,
    product_family,
    purchase_type,
    demo_stage
FROM {OPP_TABLE}
WHERE sales_channel NOT IN ({",".join([f"'{c}'" for c in CHANNEL_EXCLUSIONS])})
  AND purchase_type_rollup = '{PURCHASE_TYPE}'
  AND is_won = 'True'
  AND is_closed = 'True'
  AND year(close_date) BETWEEN 2022 AND 2026
  AND product_genus IN ({",".join([f"'{p}'" for p in PRODUCT_MAP.keys()])})
"""

raw = spark.sql(sql)

# Fix date types and normalize fields
raw = (raw
    .withColumn("close_date", F.to_date("close_date"))
    .withColumn("pipeline_entered_date", F.to_date("pipeline_entered_date"))
    # Normalize product_genus to display name
    .replace(PRODUCT_MAP, subset=["product_genus"])
    # Normalize sales_market
    .withColumn("sales_market", F.when(
        F.col("sales_market").isin(["AUS/ROW", "APAC"]), "AUS/APAC"
    ).otherwise(F.col("sales_market")))
    # Week start (Monday)
    .withColumn("week_start", F.date_trunc("week", F.col("close_date")))
)

print(f"✓ Raw rows loaded: {raw.count():,}")
raw.printSchema()

# COMMAND ----------
# ── 2. WEEKLY AGGREGATION ─────────────────────────────────────────────────────
weekly = (raw
    .filter(F.col("close_date") >= TRAIN_START)
    .groupBy("week_start", "product_genus")
    .agg(
        F.sum("amount_towards_plan").alias("arr"),
        F.countDistinct("salesforce_opportunity_line_item_id").alias("deal_count"),
        F.avg("amount_towards_plan").alias("avg_deal_size"),
        F.countDistinct("owner_id").alias("rep_count"),
    )
    .orderBy("product_genus", "week_start")
)

print(f"✓ Weekly rows: {weekly.count():,}")
weekly.show(5)

# COMMAND ----------
# ── 3. DATA CLEANING ─────────────────────────────────────────────────────────
import pandas as pd
import numpy as np

def clean_product_series(df_product: pd.DataFrame) -> pd.DataFrame:
    """
    Full data cleaning pipeline for one product's weekly ARR series.
    Steps:
      1. Build a complete weekly date spine (no gaps)
      2. Fill missing weeks with 0 (no deals closed = $0 ARR)
      3. Remove future dates
      4. Clip extreme outliers (>4 IQR from Q3) — replace with rolling median
      5. Floor at 0 (ARR can't be negative)
    """
    df = df_product.copy()
    df["week_start"] = pd.to_datetime(df["week_start"])
    df = df.set_index("week_start").sort_index()

    # 1. Complete date spine
    full_idx = pd.date_range(
        start=df.index.min(),
        end=pd.Timestamp.today().normalize() - pd.offsets.Week(weekday=0),
        freq="W-MON",
    )
    df = df.reindex(full_idx)

    # 2. Fill missing weeks with 0
    df["arr"]          = df["arr"].fillna(0.0)
    df["deal_count"]   = df["deal_count"].fillna(0).astype(int)
    df["avg_deal_size"]= df["avg_deal_size"].fillna(0.0)
    df["rep_count"]    = df["rep_count"].fillna(0).astype(int)

    # 3. Remove future
    df = df[df.index <= pd.Timestamp.today()]

    # 4. Outlier clipping — IQR-based
    q1, q3     = df["arr"].quantile(0.25), df["arr"].quantile(0.75)
    iqr        = q3 - q1
    upper_fence= q3 + 4 * iqr
    rolling_med= df["arr"].rolling(13, min_periods=4, center=True).median()
    df["arr"]  = np.where(
        (df["arr"] > upper_fence) & (df["arr"] > 0),
        rolling_med,
        df["arr"],
    )
    df["arr"]  = df["arr"].fillna(0.0)

    # 5. Floor at 0
    df["arr"]  = df["arr"].clip(lower=0)

    df.index.name = "ds"
    df = df.reset_index()
    return df


weekly_pd = weekly.toPandas()
weekly_pd["week_start"] = pd.to_datetime(weekly_pd["week_start"])

products = weekly_pd["product_genus"].unique().tolist()
cleaned  = {}

for product in products:
    sub = weekly_pd[weekly_pd["product_genus"] == product].copy()
    sub = clean_product_series(sub)
    cleaned[product] = sub
    print(f"  {product}: {len(sub)} weeks  |  ARR ${sub['arr'].min():,.0f} – ${sub['arr'].max():,.0f}")

print(f"\n✓ Cleaning done — {len(products)} products")

# COMMAND ----------
# ── 4. TRAIN / EVAL SPLIT ────────────────────────────────────────────────────
HOLDOUT_WEEKS = 8

def split(df: pd.DataFrame):
    return df.iloc[:-HOLDOUT_WEEKS].copy(), df.iloc[-HOLDOUT_WEEKS:].copy()

def mape(actual: np.ndarray, predicted: np.ndarray, eps: float = 1.0) -> float:
    """MAPE — floors denominator at `eps` to avoid div/0 on zero-revenue weeks."""
    actual    = np.array(actual,    dtype=float)
    predicted = np.array(predicted, dtype=float)
    return float(np.mean(np.abs((actual - predicted) / np.maximum(np.abs(actual), eps))) * 100)

# COMMAND ----------
# ── 5. MODEL 1 — ETS (Exponential Smoothing) ─────────────────────────────────
from statsmodels.tsa.holtwinters import ExponentialSmoothing

def fit_ets(train: np.ndarray, horizon: int) -> np.ndarray:
    n = len(train)
    if n >= 104:
        model = ExponentialSmoothing(train, trend="add", seasonal="add",
                                     seasonal_periods=52, damped_trend=True)
    elif n >= 52:
        model = ExponentialSmoothing(train, trend="add", seasonal="add",
                                     seasonal_periods=52)
    else:
        model = ExponentialSmoothing(train, trend="add", damped_trend=True)

    fitted = model.fit(optimized=True, use_brute=False)
    return np.maximum(fitted.forecast(horizon), 0)


ets_forecasts = {}
ets_mapes     = {}

for product, df in cleaned.items():
    if len(df) < MIN_HISTORY_WK:
        print(f"  [{product}] Skipped ETS — not enough history")
        continue
    train_df, test_df = split(df)
    series = train_df["arr"].values.astype(float)

    val_fc = fit_ets(series, HOLDOUT_WEEKS)
    ets_mapes[product] = mape(test_df["arr"].values, val_fc)

    full_fc = fit_ets(df["arr"].values.astype(float), FORECAST_WEEKS)
    ets_forecasts[product] = full_fc

    print(f"  [{product}] ETS MAPE = {ets_mapes[product]:.1f}%")

print("\n✓ ETS done")

# COMMAND ----------
# ── 6. MODEL 2 — PROPHET ─────────────────────────────────────────────────────
from prophet import Prophet
import logging
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

def fit_prophet(train: pd.DataFrame, horizon: int) -> np.ndarray:
    df_p = train[["ds", "arr"]].rename(columns={"arr": "y"}).copy()
    df_p["y"] = df_p["y"].clip(lower=0)

    m = Prophet(
        growth="linear",
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode="additive",
        changepoint_prior_scale=0.05,
        seasonality_prior_scale=10.0,
        interval_width=0.80,
    )
    m.add_seasonality(name="quarterly", period=91.25, fourier_order=5)
    m.fit(df_p)

    future   = m.make_future_dataframe(periods=horizon, freq="W")
    forecast = m.predict(future)
    return np.maximum(forecast["yhat"].values[-horizon:], 0)


prophet_forecasts = {}
prophet_mapes     = {}

for product, df in cleaned.items():
    if len(df) < MIN_HISTORY_WK:
        print(f"  [{product}] Skipped Prophet — not enough history")
        continue
    train_df, test_df = split(df)

    val_fc  = fit_prophet(train_df, HOLDOUT_WEEKS)
    prophet_mapes[product] = mape(test_df["arr"].values, val_fc)

    full_fc = fit_prophet(df, FORECAST_WEEKS)
    prophet_forecasts[product] = full_fc

    print(f"  [{product}] Prophet MAPE = {prophet_mapes[product]:.1f}%")

print("\n✓ Prophet done")

# COMMAND ----------
# ── 7. MODEL 3 — LIGHTGBM ────────────────────────────────────────────────────
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit

LAG_WEEKS    = [1, 2, 3, 4, 6, 8, 13, 26]
ROLL_WINDOWS = [4, 8, 13, 26]

def make_lgb_features(series: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"arr": series.values}, index=series.index)
    for lag in LAG_WEEKS:
        df[f"lag_{lag}"] = df["arr"].shift(lag)
    for w in ROLL_WINDOWS:
        roll = df["arr"].shift(1).rolling(w, min_periods=2)
        df[f"roll_mean_{w}"] = roll.mean()
        df[f"roll_std_{w}"]  = roll.std().fillna(0)
        df[f"roll_max_{w}"]  = roll.max()
    if isinstance(series.index, pd.DatetimeIndex):
        df["week_of_year"] = series.index.isocalendar().week.astype(int)
        df["quarter"]      = series.index.quarter
        df["month"]        = series.index.month
    df["target"] = df["arr"].shift(-1)
    return df.dropna()


def fit_lgb_step(train_series: pd.Series) -> float:
    feat_df = make_lgb_features(train_series)
    feature_cols = [c for c in feat_df.columns if c not in ("arr", "target")]
    X, y = feat_df[feature_cols].values, feat_df["target"].values

    params = dict(objective="regression_l1", learning_rate=0.05, num_leaves=15,
                  min_data_in_leaf=5, feature_fraction=0.8, bagging_fraction=0.8,
                  bagging_freq=5, lambda_l1=0.1, lambda_l2=0.1,
                  n_estimators=300, verbosity=-1)

    tscv   = TimeSeriesSplit(n_splits=3)
    models = []
    for tr_idx, _ in tscv.split(X):
        m = lgb.LGBMRegressor(**params)
        m.fit(X[tr_idx], y[tr_idx])
        models.append(m)

    preds = np.array([m.predict(X[[-1]])[0] for m in models])
    return max(float(preds.mean()), 0.0)


def lgb_multi_step(series: pd.Series, horizon: int) -> np.ndarray:
    s = series.copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.date_range(end=pd.Timestamp.today(), periods=len(s), freq="W-MON")
    forecasts = []
    for _ in range(horizon):
        pred = fit_lgb_step(s)
        forecasts.append(pred)
        next_date = s.index[-1] + pd.offsets.Week(1)
        s = pd.concat([s, pd.Series([pred], index=[next_date])])
    return np.array(forecasts)


lgb_forecasts = {}
lgb_mapes     = {}

for product, df in cleaned.items():
    if len(df) < MIN_HISTORY_WK + HOLDOUT_WEEKS:
        print(f"  [{product}] Skipped LightGBM — not enough history")
        continue

    s = df.set_index("ds")["arr"]
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)

    val_fc  = lgb_multi_step(s.iloc[:-HOLDOUT_WEEKS], HOLDOUT_WEEKS)
    lgb_mapes[product] = mape(s.iloc[-HOLDOUT_WEEKS:].values, val_fc)

    full_fc = lgb_multi_step(s, FORECAST_WEEKS)
    lgb_forecasts[product] = full_fc

    print(f"  [{product}] LightGBM MAPE = {lgb_mapes[product]:.1f}%")

print("\n✓ LightGBM done")

# COMMAND ----------
# ── 8. MODEL 4 — CHRONOS (Foundation, Zero-Shot) ─────────────────────────────
import torch

try:
    from chronos import ChronosPipeline
    chronos_pipeline = ChronosPipeline.from_pretrained(
        "amazon/chronos-t5-small",
        device_map="cpu",
        torch_dtype=torch.float32,
    )
    print("✓ Chronos model loaded")
except Exception as e:
    print(f"⚠ Chronos unavailable: {e}")
    chronos_pipeline = None


def chronos_forecast(series: np.ndarray, horizon: int, num_samples: int = 20) -> np.ndarray:
    ctx = torch.tensor(series.astype(float), dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        samples = chronos_pipeline.predict(ctx, prediction_length=horizon, num_samples=num_samples)
    return np.maximum(np.median(samples[0].numpy(), axis=0), 0)


chronos_forecasts = {}
chronos_mapes     = {}

if chronos_pipeline is None:
    print("  Skipping Chronos — model not loaded")
else:
    for product, df in cleaned.items():
        if len(df) < MIN_HISTORY_WK:
            print(f"  [{product}] Skipped Chronos — not enough history")
            continue
        arr = df["arr"].values.astype(float)

        val_fc  = chronos_forecast(arr[:-HOLDOUT_WEEKS], HOLDOUT_WEEKS)
        chronos_mapes[product] = mape(arr[-HOLDOUT_WEEKS:], val_fc)

        full_fc = chronos_forecast(arr, FORECAST_WEEKS)
        chronos_forecasts[product] = full_fc

        print(f"  [{product}] Chronos MAPE = {chronos_mapes[product]:.1f}%")

    print("\n✓ Chronos done")

# COMMAND ----------
# ── 9. MAPE LEADERBOARD ───────────────────────────────────────────────────────
leaderboard_rows = []
all_products = set(ets_mapes) | set(prophet_mapes) | set(lgb_mapes) | set(chronos_mapes)

for product in sorted(all_products):
    row = {
        "product":  product,
        "ETS":      round(ets_mapes.get(product, np.nan), 2),
        "Prophet":  round(prophet_mapes.get(product, np.nan), 2),
        "LightGBM": round(lgb_mapes.get(product, np.nan), 2),
        "Chronos":  round(chronos_mapes.get(product, np.nan), 2),
    }
    scores = {k: v for k, v in row.items() if k != "product" and not np.isnan(v)}
    row["best_model"] = min(scores, key=scores.get) if scores else "N/A"
    row["best_mape"]  = round(min(scores.values()), 2) if scores else np.nan
    leaderboard_rows.append(row)

lb_df = pd.DataFrame(leaderboard_rows)
print("\n── MAPE Leaderboard (8-week holdout) ───────────────")
print(lb_df.to_string(index=False))

# COMMAND ----------
# ── 10. WEIGHTED ENSEMBLE ────────────────────────────────────────────────────
def inverse_mape_weights(*mapes) -> np.ndarray:
    scores = np.array([m if not np.isnan(m) else 999.0 for m in mapes], dtype=float)
    inv = 1.0 / (scores + 0.1)
    return inv / inv.sum()


ensemble_forecasts = {}
ensemble_meta      = {}

for product in all_products:
    model_fcs    = {}
    model_mapes_ = {}

    for name, fcs, mps in [
        ("ETS",      ets_forecasts,      ets_mapes),
        ("Prophet",  prophet_forecasts,  prophet_mapes),
        ("LightGBM", lgb_forecasts,      lgb_mapes),
        ("Chronos",  chronos_forecasts,  chronos_mapes),
    ]:
        if product in fcs:
            model_fcs[name]    = fcs[product]
            model_mapes_[name] = mps.get(product, np.nan)

    if not model_fcs:
        print(f"  [{product}] No models available — skipping")
        continue

    names   = list(model_fcs.keys())
    mapes_  = [model_mapes_[n] for n in names]
    weights = inverse_mape_weights(*mapes_)

    stacked = np.stack([model_fcs[n] for n in names], axis=0)
    blended = np.maximum(np.sum(weights[:, None] * stacked, axis=0), 0)

    ensemble_forecasts[product] = blended
    ensemble_meta[product] = {
        n: {"mape": round(mapes_[i], 2), "weight": round(float(weights[i]), 4)}
        for i, n in enumerate(names)
    }
    wstr = ", ".join(f"{n}={w['weight']:.2f}" for n, w in ensemble_meta[product].items())
    print(f"  [{product}] {wstr}")

print("\n✓ Ensemble done")

# COMMAND ----------
# ── 11. BUILD OUTPUT DATAFRAME ────────────────────────────────────────────────
import json

output_rows = []
run_ts = pd.Timestamp.now()

for product, fc_arr in ensemble_forecasts.items():
    df_prod   = cleaned[product]
    last_date = pd.to_datetime(df_prod["ds"].max())

    for step, fc_val in enumerate(fc_arr):
        forecast_date = last_date + pd.offsets.Week(step + 1)
        output_rows.append({
            "run_timestamp":       run_ts,
            "product":             product,
            "forecast_week_start": forecast_date,
            "forecast_step":       step + 1,
            "horizon_weeks":       FORECAST_WEEKS,
            "arr_ensemble":        round(float(fc_val), 2),
            "arr_ets":             round(float(ets_forecasts[product][step]), 2)       if product in ets_forecasts      else None,
            "arr_prophet":         round(float(prophet_forecasts[product][step]), 2)  if product in prophet_forecasts  else None,
            "arr_lightgbm":        round(float(lgb_forecasts[product][step]), 2)      if product in lgb_forecasts      else None,
            "arr_chronos":         round(float(chronos_forecasts[product][step]), 2)  if product in chronos_forecasts  else None,
            "mape_ets":            ets_mapes.get(product),
            "mape_prophet":        prophet_mapes.get(product),
            "mape_lightgbm":       lgb_mapes.get(product),
            "mape_chronos":        chronos_mapes.get(product),
            "ensemble_weights":    json.dumps(ensemble_meta.get(product, {})),
        })

output_pd = pd.DataFrame(output_rows)
print(f"✓ Output rows: {len(output_pd):,}")
if not output_pd.empty:
    print(output_pd.groupby("product")[["arr_ensemble"]].agg(["min", "max"]))
else:
    print("⚠ No forecasts generated — check source data and model fitting above")

# COMMAND ----------
# ── 12. SAVE TO DELTA GOLD LAYER ─────────────────────────────────────────────
if output_pd.empty:
    print("⚠ No rows to write — skipping Delta save")
else:
    output_sdf = spark.createDataFrame(output_pd)
    (output_sdf
        .write.format("delta").mode("overwrite")
        .option("mergeSchema", "true")
        .option("overwriteSchema", "true")
        .saveAsTable(OUTPUT_TABLE)
    )
    print(f"✓ Saved to {OUTPUT_TABLE}")
    spark.sql(f"OPTIMIZE {OUTPUT_TABLE} ZORDER BY (product, forecast_week_start)")
    print("✓ OPTIMIZE + ZORDER done")

# COMMAND ----------
# ── 13. SAVE LEADERBOARD ─────────────────────────────────────────────────────
if not lb_df.empty:
    lb_sdf = spark.createDataFrame(lb_df)
    (lb_sdf
        .write.format("delta").mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(LEADERBOARD_TABLE)
    )
    print(f"✓ Leaderboard saved to {LEADERBOARD_TABLE}")

# COMMAND ----------
# ── 14. VALIDATION CHART ─────────────────────────────────────────────────────
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

n_products = len(ensemble_forecasts)
fig, axes  = plt.subplots(n_products, 1, figsize=(14, 4.5 * n_products))
if n_products == 1:
    axes = [axes]

MODEL_COLORS = {
    "ETS": "#94a3b8", "Prophet": "#f59e0b",
    "LightGBM": "#3b82f6", "Chronos": "#10b981", "Ensemble": "#ffffff",
}

for ax, (product, fc_arr) in zip(axes, ensemble_forecasts.items()):
    df_prod   = cleaned[product]
    history   = df_prod.set_index("ds")["arr"].tail(52)
    fc_dates  = pd.date_range(
        start=pd.to_datetime(df_prod["ds"].max()) + pd.offsets.Week(1),
        periods=FORECAST_WEEKS, freq="W-MON",
    )

    ax.set_facecolor("#0a0f1e")
    fig.patch.set_facecolor("#0a0f1e")

    ax.plot(history.index, history.values / 1e6,
            color="#64748b", linewidth=1.5, label="Actual", alpha=0.8)

    for model_name, fcs in [("ETS", ets_forecasts), ("Prophet", prophet_forecasts),
                              ("LightGBM", lgb_forecasts), ("Chronos", chronos_forecasts)]:
        if product in fcs:
            w = ensemble_meta.get(product, {}).get(model_name, {}).get("weight", 0)
            ax.plot(fc_dates, fcs[product] / 1e6, color=MODEL_COLORS[model_name],
                    linewidth=1, alpha=0.45, linestyle="--", label=f"{model_name} (w={w:.2f})")

    ax.plot(fc_dates, fc_arr / 1e6, color="#ffffff", linewidth=2.5, label="Ensemble", zorder=5)
    ax.axvspan(fc_dates[0], fc_dates[-1], alpha=0.06, color="#3b82f6")
    ax.axvline(fc_dates[0], color="#3b82f6", linewidth=0.8, linestyle=":", alpha=0.6)

    ax.set_title(f"{product} — 13-Week ARR Forecast", color="#f1f5f9", fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel("ARR ($M)", color="#64748b", fontsize=10)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x:.1f}M"))
    ax.tick_params(colors="#475569", labelsize=9)
    ax.spines[:].set_visible(False)
    ax.grid(axis="y", color=(1.0, 1.0, 1.0, 0.05), linewidth=0.5)
    ax.legend(fontsize=8, loc="upper left", framealpha=0.15,
              labelcolor="#94a3b8", facecolor="#0d1428")

plt.tight_layout(pad=2.5)
plt.savefig("/tmp/arr_forecast_ensemble.png", dpi=150, bbox_inches="tight", facecolor="#0a0f1e")
plt.show()
print("✓ Chart saved to /tmp/arr_forecast_ensemble.png")

# COMMAND ----------
# ── 15. GRANTS (run manually in a SQL cell as an admin) ──────────────────────
# %sql
# GRANT USE CATALOG ON CATALOG datagroup_mdl TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# GRANT USE SCHEMA ON SCHEMA datagroup_mdl.mdl_sales_analytics TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_ensemble TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_leaderboard TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
print("ℹ Run the GRANT statements above as a SQL cell (admin account required)")
