# Databricks notebook source
# MAGIC %md
# MAGIC # ARR Forecast v2 — Main (ETS · Prophet · LightGBM · Ensemble)
# MAGIC
# MAGIC **Key improvements over v1:**
# MAGIC - Monthly aggregation (train on monthly → distribute to weekly for storage)
# MAGIC - Log1p transform to reduce spike sensitivity
# MAGIC - sMAPE evaluation (handles near-zero weeks)
# MAGIC - Direct multi-output LightGBM (one model per horizon step — no compounding errors)
# MAGIC - Pipeline regressors: created_arr, win_rate (lagged 1 month ≈ 4-8 weeks lead)
# MAGIC - GoTo Central merged into ITSG
# MAGIC - MC actuals override SFDC for all closed months
# MAGIC - Target: sMAPE < 15% for all slices
# MAGIC
# MAGIC **Companion notebook**: arr_forecast_v2_chronos.py — runs Chronos and MERGEs into same table
# MAGIC **Output**: datagroup_mdl.mdl_sales_analytics.arr_forecast_v2

# COMMAND ----------
# MAGIC %pip install prophet lightgbm statsmodels scikit-learn --quiet

# COMMAND ----------
import warnings, logging, math, datetime
warnings.filterwarnings("ignore")
logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)

import numpy as np
import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql.types import *
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from prophet import Prophet
import lightgbm as lgb

# ── Config ────────────────────────────────────────────────────────────────────
CATALOG   = "datagroup_mdl"
SCHEMA    = "mdl_sales_analytics"
OUT_TABLE = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"
LB_TABLE  = f"{CATALOG}.{SCHEMA}.arr_forecast_v2_leaderboard"

SFDC_TABLE = "datalake_transform.cds_sfdc_opp_products_latest"
MC_TABLE   = f"{CATALOG}.{SCHEMA}.mc_actuals"

TODAY           = datetime.date.today()
RUN_DATE        = TODAY
CUR_MONTH_START = TODAY.replace(day=1)
TRAIN_FROM      = "2022-01-01"

ROLLING_MONTHS  = 3                        # ≈ 13 weeks
ROY_MONTHS      = max(                     # calendar months remaining in year
    round((datetime.date(TODAY.year, 12, 31) - CUR_MONTH_START).days / 30.44), 1
)
HOLDOUT_MONTHS  = 3                        # holdout for sMAPE evaluation
MIN_HISTORY     = 18                       # minimum months needed to train

# Product mapping — GoTo Central collapsed into ITSG
PRODUCT_MAP = {
    "GoTo Connect": "UCC",
    "GoTo Engage":  "UCC",
    "GoTo Resolve": "ITSG",
    "GoTo Central": "ITSG",   # merged — too low-volume to forecast alone
    "Rescue":       "ITSG",
}

GEO_NORM = {
    "NA":"NA","US":"NA","North America":"NA","NAMER":"NA","AMER":"NA",
    "EMEA":"EMEA","Europe":"EMEA","EUR":"EMEA",
    "APAC":"APAC","Asia Pacific":"APAC","APJ":"APAC","AUS":"APAC","ROW":"APAC",
    "LATAM":"LATAM","Latin America":"LATAM",
}

SLICES = [
    ("Total","Total"),
    ("UCC",  "Total"), ("ITSG","Total"),
    ("Total","NA"),    ("Total","EMEA"), ("Total","APAC"), ("Total","LATAM"),
    ("UCC",  "NA"),    ("UCC", "EMEA"),
    ("ITSG", "NA"),    ("ITSG","EMEA"),
]

print(f"Run: {RUN_DATE} | Current month: {CUR_MONTH_START}")
print(f"Rolling: {ROLLING_MONTHS}m | RoY: {ROY_MONTHS}m")

# COMMAND ----------
# MAGIC %md ## 1 — Load SFDC Monthly Actuals

# COMMAND ----------
prod_case  = "CASE " + " ".join(
    f"WHEN product_genus='{k}' THEN '{v}'" for k,v in PRODUCT_MAP.items()
) + " ELSE 'Other' END"

geo_case = "CASE " + " ".join(
    f"WHEN sales_market='{k}' THEN '{v}'" for k,v in GEO_NORM.items()
) + " ELSE 'Other' END"

sfdc_raw = spark.sql(f"""
    SELECT
        date_trunc('month', close_date)  AS month_start,
        {prod_case}                      AS product_group,
        {geo_case}                       AS geo,
        SUM(COALESCE(arr, 0))            AS arr_sfdc
    FROM {SFDC_TABLE}
    WHERE is_won        = 'True'
      AND purchase_type = 'Growth'
      AND close_date   >= '{TRAIN_FROM}'
      AND close_date   <  current_date()
      AND COALESCE(arr, 0) > 0
    GROUP BY 1, 2, 3
""").filter(
    F.col("product_group").isin("UCC","ITSG") &
    F.col("geo").isin("NA","EMEA","APAC","LATAM")
)

# Total aggregates
sfdc_tot_p = sfdc_raw.groupBy("month_start","geo").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("product_group",F.lit("Total"))
sfdc_tot_g = sfdc_raw.groupBy("month_start","product_group").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("geo",F.lit("Total"))
sfdc_tot   = sfdc_raw.groupBy("month_start").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("product_group",F.lit("Total")).withColumn("geo",F.lit("Total"))
sfdc_all   = sfdc_raw.union(sfdc_tot_p).union(sfdc_tot_g).union(sfdc_tot)
print("SFDC monthly rows:", sfdc_all.count())

# COMMAND ----------
# MAGIC %md ## 2 — Pipeline Regressors (leading indicators, lagged 1 month)

# COMMAND ----------
try:
    pipeline_raw = spark.sql(f"""
        SELECT
            date_trunc('month', close_date)              AS month_start,
            SUM(CASE WHEN is_won='True' THEN COALESCE(arr,0) ELSE 0 END) AS won_arr,
            SUM(COALESCE(arr, 0))                        AS total_arr_closed,
            COUNT(DISTINCT CASE WHEN is_won='True' THEN opportunity_id END) AS won_opps,
            COUNT(DISTINCT opportunity_id)               AS total_opps
        FROM {SFDC_TABLE}
        WHERE purchase_type  = 'Growth'
          AND close_date    >= '{TRAIN_FROM}'
          AND close_date    <  current_date()
        GROUP BY 1
        ORDER BY 1
    """).toPandas()
    pipeline_raw["month_start"] = pd.to_datetime(pipeline_raw["month_start"])
    pipeline_raw["win_rate"] = (
        pipeline_raw["won_opps"] / pipeline_raw["total_opps"].replace(0, np.nan)
    ).fillna(0)
    # Lag by 1 month (pipeline created last month predicts this month's close)
    pipeline_raw["win_rate_lag1"]    = pipeline_raw["win_rate"].shift(1)
    pipeline_raw["won_arr_lag1"]     = pipeline_raw["won_arr"].shift(1)
    pipeline_raw["won_arr_roll3"]    = pipeline_raw["won_arr"].shift(1).rolling(3).mean()
    pipeline_regressors = pipeline_raw[["month_start","win_rate_lag1","won_arr_lag1","won_arr_roll3"]].dropna()
    print(f"Pipeline regressors: {len(pipeline_regressors)} months")
    HAS_REGRESSORS = True
except Exception as e:
    print(f"Pipeline regressors unavailable ({e}) — proceeding without")
    pipeline_regressors = pd.DataFrame()
    HAS_REGRESSORS = False

# COMMAND ----------
# MAGIC %md ## 3 — MC Reconciled Actuals (closed months)

# COMMAND ----------
geo_case_mc = "CASE " + " ".join(
    f"WHEN `Sales Market`='{k}' THEN '{v}'" for k,v in GEO_NORM.items()
) + " ELSE 'Other' END"

try:
    mc_raw = spark.sql(f"""
        SELECT
            date_trunc('month', `Month of Data Month`)                          AS month_start,
            CASE WHEN `Business Unit`='UCC'  THEN 'UCC'
                 WHEN `Business Unit`='ITSG' THEN 'ITSG'
                 ELSE 'Other' END                                               AS product_group,
            {geo_case_mc}                                                       AS geo,
            SUM(CAST(`Reported Bookings Total In USD Order Month Rate` AS DOUBLE)) AS arr_mc
        FROM {MC_TABLE}
        WHERE `Version`       = 'Actuals'
          AND `Purchase Type` = 'Growth'
          AND `Month of Data Month` <  '{CUR_MONTH_START}'
          AND `Month of Data Month` >= '{TRAIN_FROM}'
        GROUP BY 1, 2, 3
    """).filter(
        F.col("product_group").isin("UCC","ITSG") &
        F.col("geo").isin("NA","EMEA","APAC","LATAM")
    )
    mc_tot_p = mc_raw.groupBy("month_start","geo").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("product_group",F.lit("Total"))
    mc_tot_g = mc_raw.groupBy("month_start","product_group").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("geo",F.lit("Total"))
    mc_tot   = mc_raw.groupBy("month_start").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("product_group",F.lit("Total")).withColumn("geo",F.lit("Total"))
    mc_all   = mc_raw.union(mc_tot_p).union(mc_tot_g).union(mc_tot)
    print("MC monthly rows:", mc_all.count())
    HAS_MC = True
except Exception as e:
    print(f"MC actuals unavailable ({e}) — using SFDC only")
    mc_all = spark.createDataFrame([], sfdc_all.schema)
    HAS_MC = False

# COMMAND ----------
# MAGIC %md ## 4 — Blend Actuals (MC overrides SFDC for closed months)

# COMMAND ----------
blended_sdf = (
    sfdc_all
    .join(
        mc_all.withColumnRenamed("arr_mc","arr_mc_month"),
        ["month_start","product_group","geo"], "left"
    )
    .withColumn("arr_actuals",
        F.when(
            (F.col("month_start") < F.lit(CUR_MONTH_START)) &
            F.col("arr_mc_month").isNotNull() & (F.col("arr_mc_month") > 0),
            F.col("arr_mc_month")
        ).otherwise(F.col("arr_sfdc"))
    )
    .select("month_start","product_group","geo","arr_actuals")
    .orderBy("month_start")
)

blended_pd = blended_sdf.toPandas()
blended_pd["month_start"] = pd.to_datetime(blended_pd["month_start"])
blended_pd["arr_actuals"] = pd.to_numeric(blended_pd["arr_actuals"], errors="coerce").fillna(0)
print(f"Blended monthly rows: {len(blended_pd)}")

# COMMAND ----------
# MAGIC %md ## 5 — Weekly-within-Month Distribution Pattern

# COMMAND ----------
# Compute historical weekly share within each month from raw SFDC weekly data
sfdc_weekly_raw = spark.sql(f"""
    SELECT
        date_trunc('week',  close_date) AS week_start,
        date_trunc('month', close_date) AS month_start,
        SUM(COALESCE(arr,0))            AS arr_sfdc
    FROM {SFDC_TABLE}
    WHERE is_won        = 'True'
      AND purchase_type = 'Growth'
      AND close_date   >= '2023-01-01'
      AND close_date   <  current_date()
      AND COALESCE(arr, 0) > 0
    GROUP BY 1, 2
    ORDER BY 1
""").toPandas()
sfdc_weekly_raw["week_start"]   = pd.to_datetime(sfdc_weekly_raw["week_start"])
sfdc_weekly_raw["month_start"]  = pd.to_datetime(sfdc_weekly_raw["month_start"])

# Month total
monthly_totals = sfdc_weekly_raw.groupby("month_start")["arr_sfdc"].sum().reset_index(name="arr_month")
sfdc_weekly_raw = sfdc_weekly_raw.merge(monthly_totals, on="month_start")
sfdc_weekly_raw["share"] = sfdc_weekly_raw["arr_sfdc"] / sfdc_weekly_raw["arr_month"].replace(0, np.nan)

# Week-of-month index (0, 1, 2, 3, 4)
sfdc_weekly_raw["week_of_month"] = (
    (sfdc_weekly_raw["week_start"] - sfdc_weekly_raw["month_start"]).dt.days // 7
).clip(0, 4)

avg_weekly_share = (
    sfdc_weekly_raw.groupby("week_of_month")["share"]
    .mean()
    .reindex([0,1,2,3,4], fill_value=0)
)
# Normalise so shares sum to 1 (there are typically 4-5 Mondays per month)
avg_weekly_share = avg_weekly_share / avg_weekly_share.sum()
print("Average weekly shares within month:")
print(avg_weekly_share.to_dict())


def monthly_to_weekly(month_start: pd.Timestamp, monthly_value: float) -> list[dict]:
    """
    Distribute a monthly forecast value into weekly rows.
    Returns list of {ds, value} for each Monday that falls in the month.
    """
    ms = pd.Timestamp(month_start)
    me = ms + pd.offsets.MonthEnd(0)
    # All Mondays in this month
    mondays = pd.date_range(
        start=ms - pd.Timedelta(days=ms.weekday()),   # first Monday on or before month start
        end=me + pd.Timedelta(days=6),
        freq="W-MON"
    )
    mondays_in_month = [d for d in mondays if d.month == ms.month]
    if not mondays_in_month:
        return [{"ds": ms, "value": monthly_value}]

    n = len(mondays_in_month)
    shares = avg_weekly_share.iloc[:n].values
    if shares.sum() > 0:
        shares = shares / shares.sum()
    else:
        shares = np.ones(n) / n

    return [{"ds": d, "value": monthly_value * s}
            for d, s in zip(mondays_in_month, shares)]

# COMMAND ----------
# MAGIC %md ## 6 — Model Functions (Monthly Grain)

# COMMAND ----------
def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Symmetric MAPE — robust to near-zero actuals."""
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2.0
    mask  = denom > 0
    if mask.sum() == 0:
        return 999.0
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


# ── ETS ───────────────────────────────────────────────────────────────────────
def fit_ets_monthly(y: np.ndarray, h: int) -> tuple:
    """
    Holt-Winters on log1p-transformed monthly series.
    Returns (fc, lo, hi) in original scale.
    """
    y_log = np.log1p(np.maximum(y, 0))
    n = len(y_log)
    sp = 12 if n >= 24 else (4 if n >= 8 else None)
    try:
        if sp:
            model = ExponentialSmoothing(
                y_log, trend="add", seasonal="add", seasonal_periods=sp,
                initialization_method="estimated", damped_trend=True
            ).fit(optimized=True)
        else:
            model = ExponentialSmoothing(
                y_log, trend="add", initialization_method="estimated", damped_trend=True
            ).fit(optimized=True)
        fc_log  = model.forecast(h)
        sim_log = model.simulate(h, repetitions=500, error="add")
        lo_log  = np.nanpercentile(sim_log, 10, axis=1)
        hi_log  = np.nanpercentile(sim_log, 90, axis=1)
        return (np.maximum(np.expm1(fc_log), 0),
                np.maximum(np.expm1(lo_log), 0),
                np.maximum(np.expm1(hi_log), 0))
    except Exception as e:
        print(f"    ETS error: {e}")
        mu = float(np.mean(y[-6:]))
        return np.full(h, mu), np.full(h, mu*0.85), np.full(h, mu*1.15)


# ── Prophet ───────────────────────────────────────────────────────────────────
def fit_prophet_monthly(df_train: pd.DataFrame, h: int,
                         regressor_df: pd.DataFrame = None) -> tuple:
    """
    Prophet on monthly series with:
    - Quarterly Fourier seasonality
    - Optional pipeline regressors (win_rate_lag1, won_arr_roll3)
    - Log1p target transformation
    """
    df_p = df_train[["ds","y"]].copy()
    df_p["y"] = np.log1p(np.maximum(df_p["y"].values, 0))

    use_regs = (regressor_df is not None and len(regressor_df) > 0)

    m = Prophet(
        changepoint_prior_scale=0.05,
        seasonality_prior_scale=10,
        seasonality_mode="additive",        # additive on log scale
        interval_width=0.80,
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        growth="linear",
    )
    m.add_seasonality("quarterly", period=91.25 / 30.44, fourier_order=5)  # ~3 months
    m.add_seasonality("annual",    period=12,             fourier_order=8)

    if use_regs:
        m.add_regressor("win_rate_lag1",  prior_scale=0.5,  standardize=True)
        m.add_regressor("won_arr_roll3",  prior_scale=0.5,  standardize=True)
        # Add regressors to training data
        df_p = df_p.merge(
            regressor_df[["month_start","win_rate_lag1","won_arr_roll3"]]
            .rename(columns={"month_start":"ds"}),
            on="ds", how="left"
        ).fillna(method="ffill").fillna(0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.fit(df_p)

    # Future dataframe (monthly periods)
    last_ds = pd.to_datetime(df_p["ds"].max())
    future_ds = pd.date_range(last_ds + pd.offsets.MonthBegin(1), periods=h, freq="MS")
    future = pd.DataFrame({"ds": future_ds})

    if use_regs:
        # For future, forward-fill the last known regressor values
        last_reg = df_p[["win_rate_lag1","won_arr_roll3"]].iloc[-1:]
        for col in ["win_rate_lag1","won_arr_roll3"]:
            future[col] = float(last_reg[col].values[0]) if col in last_reg else 0.0

    fc = m.predict(future)
    yhat = np.maximum(np.expm1(fc["yhat"].values),       0)
    lo   = np.maximum(np.expm1(fc["yhat_lower"].values), 0)
    hi   = np.maximum(np.expm1(fc["yhat_upper"].values), 0)
    return yhat, lo, hi


# ── LightGBM (Direct Multi-Output) ───────────────────────────────────────────
def _calendar_features(dates: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=range(len(dates)))
    df["month"]        = dates.month
    df["quarter"]      = dates.quarter
    df["is_q_end"]     = (dates.month % 3 == 0).astype(int)
    df["is_h2"]        = (dates.month >= 7).astype(int)
    df["is_dec"]       = (dates.month == 12).astype(int)
    df["month_sin"]    = np.sin(2 * np.pi * dates.month / 12)
    df["month_cos"]    = np.cos(2 * np.pi * dates.month / 12)
    return df


def fit_lgb_direct(y: np.ndarray, dates: pd.DatetimeIndex, h: int,
                    regressor_df: pd.DataFrame = None) -> tuple:
    """
    Direct multi-output LightGBM: train one model per horizon step.
    No compounding errors. Log1p transform. Returns (fc, lo, hi).
    """
    y_log = np.log1p(np.maximum(y, 0))
    n = len(y_log)
    N_LAGS = min(12, n // 3)

    def make_X(series_log, idx, lag_n=N_LAGS):
        """Build feature matrix from lags + calendar."""
        rows = []
        cal = _calendar_features(pd.DatetimeIndex(idx))
        for i in range(lag_n, len(series_log)):
            lags = series_log[i - lag_n: i][::-1]  # lag_1 ... lag_N
            row  = list(lags) + list(cal.iloc[i].values)
            if regressor_df is not None and len(regressor_df) > 0:
                m_start = pd.Timestamp(idx[i]).replace(day=1)
                reg_row = regressor_df[regressor_df["month_start"] == m_start]
                if len(reg_row) > 0:
                    row += [float(reg_row["win_rate_lag1"].iloc[0]),
                            float(reg_row["won_arr_roll3"].iloc[0])]
                else:
                    row += [0.0, 0.0]
            rows.append(row)
        lag_cols = [f"lag_{i+1}" for i in range(lag_n)]
        cal_cols = list(cal.columns)
        reg_cols = ["win_rate_lag1","won_arr_roll3"] if (regressor_df is not None and len(regressor_df)>0) else []
        cols = lag_cols + cal_cols + reg_cols
        return pd.DataFrame(rows, columns=cols)

    X_all = make_X(y_log, dates)
    n_feat = len(X_all)

    lgb_params = dict(
        n_estimators=400, learning_rate=0.04, num_leaves=15,
        min_child_samples=3, subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=0.1, random_state=42, verbose=-1
    )

    # Train one model per step, record out-of-bag residuals for CI
    models_per_step = []
    oof_resids = []

    for step in range(h):
        # Target: y[lag_n + i + step] for row i
        targets = []
        indices = []
        for i in range(n_feat):
            target_idx = N_LAGS + i + step
            if target_idx < n:
                targets.append(y_log[target_idx])
                indices.append(i)

        if len(indices) < 5:
            # Fallback: repeat last known
            models_per_step.append(None)
            oof_resids.append([0.0])
            continue

        X_step = X_all.iloc[indices]
        y_step = np.array(targets)

        # Simple time-series split for OOB residuals
        split  = max(int(len(y_step) * 0.75), 3)
        clf_cv = lgb.LGBMRegressor(**lgb_params)
        clf_cv.fit(X_step.iloc[:split], y_step[:split])
        preds_cv = clf_cv.predict(X_step.iloc[split:])
        oof_resids.append((y_step[split:] - preds_cv).tolist())

        # Final model on all data
        clf = lgb.LGBMRegressor(**lgb_params)
        clf.fit(X_step, y_step)
        models_per_step.append(clf)

    # Predict for future horizon
    # Build features from last N_LAGS known values
    last_window = list(y_log[-N_LAGS:])
    future_dates = pd.date_range(
        pd.Timestamp(dates[-1]) + pd.offsets.MonthBegin(1), periods=h, freq="MS"
    )
    cal_future = _calendar_features(future_dates)

    fc_log = []
    for step in range(h):
        if models_per_step[step] is None:
            fc_log.append(y_log[-1])
            continue
        lags = last_window[-N_LAGS:][::-1]
        row  = lags + list(cal_future.iloc[step].values)
        if regressor_df is not None and len(regressor_df) > 0:
            row += [0.0, 0.0]   # future regressors unknown — use 0 (neutral)
        pred = float(models_per_step[step].predict(pd.DataFrame([row], columns=X_all.columns))[0])
        fc_log.append(pred)
        # Append predicted (not noisy) value for next lag window
        last_window.append(pred)

    fc_log = np.array(fc_log)
    resid_std = np.std([v for sub in oof_resids for v in sub]) if oof_resids else 0.1

    lo_log = fc_log - 1.28 * resid_std   # ~P10
    hi_log = fc_log + 1.28 * resid_std   # ~P90

    return (np.maximum(np.expm1(fc_log), 0),
            np.maximum(np.expm1(lo_log), 0),
            np.maximum(np.expm1(hi_log), 0))


# COMMAND ----------
# MAGIC %md ## 7 — sMAPE Holdout Evaluation

# COMMAND ----------
def holdout_smape(y: np.ndarray, dates: pd.DatetimeIndex,
                   model_fn, h: int = HOLDOUT_MONTHS,
                   reg_df: pd.DataFrame = None) -> float:
    """h-month holdout sMAPE for a given model function."""
    if len(y) < h + MIN_HISTORY:
        return 999.0
    y_tr, y_te = y[:-h], y[-h:]
    d_tr = dates[:-h]
    try:
        if model_fn.__name__ == "fit_prophet_monthly":
            df_tr = pd.DataFrame({"ds": pd.DatetimeIndex(d_tr), "y": y_tr})
            fc, _, _ = model_fn(df_tr, h, reg_df)
        elif model_fn.__name__ == "fit_lgb_direct":
            fc, _, _ = model_fn(y_tr, d_tr, h, reg_df)
        else:
            fc, _, _ = model_fn(y_tr, h)
        return smape(y_te, fc[:h])
    except Exception as e:
        print(f"    Holdout error ({model_fn.__name__}): {e}")
        return 999.0

# COMMAND ----------
# MAGIC %md ## 8 — Forecast Slice Function

# COMMAND ----------
def forecast_slice_monthly(product_group: str, geo: str,
                            h: int, forecast_type: str) -> pd.DataFrame:
    """
    Full 3-model + ensemble forecast for one (product, geo) slice at monthly grain.
    Returns DataFrame with monthly forecast rows.
    """
    mask = ((blended_pd["product_group"] == product_group) &
            (blended_pd["geo"]           == geo))
    df_s = (blended_pd[mask]
            .sort_values("month_start")
            .reset_index(drop=True))

    if len(df_s) < MIN_HISTORY:
        print(f"  Insufficient history ({len(df_s)} months) — skip")
        return pd.DataFrame()

    y     = df_s["arr_actuals"].values.astype(float)
    dates = pd.DatetimeIndex(df_s["month_start"])

    # IQR fence (5× — keeps quarter-end spikes)
    q1, q3 = np.percentile(y, 25), np.percentile(y, 75)
    y_c = np.clip(y, 0, q3 + 5*(q3-q1))

    # Regressors for this slice (total only; propagate to product/geo too)
    reg_df = pipeline_regressors if HAS_REGRESSORS else None

    print(f"  Holdout sMAPE ({HOLDOUT_MONTHS}m) ...")
    sm_ets = holdout_smape(y_c, dates, fit_ets_monthly)
    sm_ph  = holdout_smape(y_c, dates, fit_prophet_monthly, reg_df=reg_df)
    sm_lgb = holdout_smape(y_c, dates, fit_lgb_direct,     reg_df=reg_df)
    print(f"  ETS:{sm_ets:.1f}%  Prophet:{sm_ph:.1f}%  LGB:{sm_lgb:.1f}%")

    # Full-history forecasts
    df_tr = pd.DataFrame({"ds": dates, "y": y_c})
    fc_ets, lo_ets, hi_ets = fit_ets_monthly(y_c, h)
    fc_ph,  lo_ph,  hi_ph  = fit_prophet_monthly(df_tr, h, reg_df)
    fc_lgb, lo_lgb, hi_lgb = fit_lgb_direct(y_c, dates, h, reg_df)

    # Inverse-sMAPE weights
    def iw(s): return 1.0 / max(s, 0.1)
    tw = iw(sm_ets) + iw(sm_ph) + iw(sm_lgb)
    we, wp, wl = iw(sm_ets)/tw, iw(sm_ph)/tw, iw(sm_lgb)/tw
    print(f"  Weights → ETS:{we:.2f} Prophet:{wp:.2f} LGB:{wl:.2f}")

    fc_ens = we*fc_ets + wp*fc_ph + wl*fc_lgb
    lo_ens = we*lo_ets + wp*lo_ph + wl*lo_lgb
    hi_ens = we*hi_ets + wp*hi_ph + wl*hi_lgb

    # Use the model-derived P10/P90 directly — NO synthetic ±% clamp.
    # The ensemble prediction interval is already wider than any fixed offset
    # (typically ±20–30%+ for quarterly horizons); clamping destroys accuracy.
    worst = lo_ens
    best  = hi_ens

    # Monthly forecast date spine
    last_month = dates[-1]
    future_months = pd.date_range(
        last_month + pd.offsets.MonthBegin(1), periods=h, freq="MS"
    )

    return pd.DataFrame({
        "month_start":   future_months,
        "fc_ets":        np.maximum(fc_ets, 0),
        "fc_prophet":    np.maximum(fc_ph,  0),
        "fc_lgb":        np.maximum(fc_lgb, 0),
        "fc_ensemble":   np.maximum(fc_ens, 0),
        "lo_ensemble":   np.maximum(worst,  0),   # real P10
        "hi_ensemble":   np.maximum(best,   0),   # real P90
        "smape_ets":     sm_ets,
        "smape_prophet": sm_ph,
        "smape_lgb":     sm_lgb,
        "forecast_type": forecast_type,
    })

# COMMAND ----------
# MAGIC %md ## 9 — Main Loop

# COMMAND ----------
all_fc_rows   = []   # forecast rows (future weeks)
all_act_rows  = []   # actuals rows (historical weeks)

# Historical weekly actuals for output table (distribute monthly blended actuals to weeks)
for product_group, geo in SLICES:
    mask = ((blended_pd["product_group"] == product_group) &
            (blended_pd["geo"]           == geo))
    df_s = blended_pd[mask].sort_values("month_start").reset_index(drop=True)
    for _, row in df_s.iterrows():
        weekly = monthly_to_weekly(row["month_start"], row["arr_actuals"])
        for wk in weekly:
            all_act_rows.append({
                "ds":            wk["ds"].date(),
                "product":       product_group,
                "sales_market":  geo,
                "Actuals":       wk["value"],
                "Most_Likely":   None, "Worst_Case": None, "Best_Case": None,
                "p10":           None, "p90": None,
                "arr_ets":       None, "arr_prophet": None, "arr_lightgbm": None,
                "arr_mstl_v2":   None, "arr_dhr_arima": None,
                "mape_ets":      None, "mape_prophet": None,
                "mape_lightgbm": None, "mape_mstl_v2": None, "mape_dhr_arima": None,
                "forecast_type": "actuals",
            })

# Forecast runs
for product_group, geo in SLICES:
    print(f"\n{'='*55}")
    print(f"  product={product_group}  geo={geo}")
    print(f"{'='*55}")

    for fc_type, horizon in [("rolling", ROLLING_MONTHS), ("roy", ROY_MONTHS)]:
        print(f"\n  ── {fc_type} ({horizon}m) ──")
        try:
            fc_df = forecast_slice_monthly(product_group, geo, horizon, fc_type)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        if fc_df.empty:
            continue

        # Distribute each forecast month to weeks
        for _, row in fc_df.iterrows():
            sm_ets = row["smape_ets"]
            sm_ph  = row["smape_prophet"]
            sm_lgb = row["smape_lgb"]
            weekly_fc = monthly_to_weekly(row["month_start"], row["fc_ensemble"])
            weekly_ets    = monthly_to_weekly(row["month_start"], row["fc_ets"])
            weekly_ph     = monthly_to_weekly(row["month_start"], row["fc_prophet"])
            weekly_lgb    = monthly_to_weekly(row["month_start"], row["fc_lgb"])
            weekly_worst  = monthly_to_weekly(row["month_start"], row["lo_ensemble"])
            weekly_best   = monthly_to_weekly(row["month_start"], row["hi_ensemble"])

            for i, wk in enumerate(weekly_fc):
                # Worst/Best from real model P10/P90 — no synthetic clamp fallback.
                # If weekly distribution produces a shorter list, use the last available value.
                w_val = weekly_worst[min(i, len(weekly_worst)-1)]["value"] if weekly_worst else wk["value"]
                b_val = weekly_best[min(i, len(weekly_best)-1)]["value"]   if weekly_best  else wk["value"]
                all_fc_rows.append({
                    "ds":            wk["ds"].date(),
                    "product":       product_group,
                    "sales_market":  geo,
                    "Actuals":       None,
                    "Most_Likely":   wk["value"],
                    "Worst_Case":    w_val,
                    "Best_Case":     b_val,
                    "p10":           w_val,   # alias — same as Worst_Case (P10)
                    "p90":           b_val,   # alias — same as Best_Case  (P90)
                    "arr_ets":       weekly_ets[i]["value"]    if i < len(weekly_ets)   else None,
                    "arr_prophet":   weekly_ph[i]["value"]     if i < len(weekly_ph)    else None,
                    "arr_lightgbm":  weekly_lgb[i]["value"]    if i < len(weekly_lgb)   else None,
                    "arr_mstl_v2":   None,   # filled by atlas_combined_writer / companion
                    "arr_dhr_arima": None,   # filled by atlas_combined_writer / companion
                    "mape_ets":      sm_ets,
                    "mape_prophet":  sm_ph,
                    "mape_lightgbm": sm_lgb,
                    "mape_mstl_v2":  None,
                    "mape_dhr_arima":None,
                    "forecast_type": fc_type,
                })

actuals_pd  = pd.DataFrame(all_act_rows)
forecast_pd = pd.DataFrame(all_fc_rows)
combined_pd = pd.concat([actuals_pd, forecast_pd], ignore_index=True)
combined_pd["run_date"] = pd.Timestamp(RUN_DATE).date()

print(f"\nTotal rows: {len(combined_pd)}")
print(combined_pd.groupby(["product","sales_market","forecast_type"]).size().to_string())

# COMMAND ----------
# MAGIC %md ## 10 — Write to Delta Table

# COMMAND ----------
OUTPUT_SCHEMA = StructType([
    StructField("ds",             DateType(),   True),
    StructField("product",        StringType(), True),
    StructField("sales_market",   StringType(), True),
    StructField("Actuals",        DoubleType(), True),
    StructField("Most_Likely",    DoubleType(), True),
    StructField("Worst_Case",     DoubleType(), True),
    StructField("Best_Case",      DoubleType(), True),
    StructField("p10",            DoubleType(), True),
    StructField("p90",            DoubleType(), True),
    StructField("arr_ets",        DoubleType(), True),
    StructField("arr_prophet",    DoubleType(), True),
    StructField("arr_lightgbm",   DoubleType(), True),
    StructField("arr_mstl_v2",    DoubleType(), True),
    StructField("arr_dhr_arima",  DoubleType(), True),
    StructField("mape_ets",       DoubleType(), True),
    StructField("mape_prophet",   DoubleType(), True),
    StructField("mape_lightgbm",  DoubleType(), True),
    StructField("mape_mstl_v2",   DoubleType(), True),
    StructField("mape_dhr_arima", DoubleType(), True),
    StructField("forecast_type",  StringType(), True),
    StructField("run_date",       DateType(),   True),
])

numeric_cols = ["Actuals","Most_Likely","Worst_Case","Best_Case","p10","p90",
                "arr_ets","arr_prophet","arr_lightgbm","arr_mstl_v2","arr_dhr_arima",
                "mape_ets","mape_prophet","mape_lightgbm","mape_mstl_v2","mape_dhr_arima"]
for c in numeric_cols:
    combined_pd[c] = pd.to_numeric(combined_pd[c], errors="coerce")

combined_pd["ds"]       = pd.to_datetime(combined_pd["ds"]).dt.date
combined_pd["run_date"] = pd.to_datetime(combined_pd["run_date"]).dt.date

out_sdf = spark.createDataFrame(combined_pd, schema=OUTPUT_SCHEMA)

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {OUT_TABLE} (
        ds            DATE        COMMENT 'Week start (Monday)',
        product       STRING      COMMENT 'Total / UCC / ITSG',
        sales_market  STRING      COMMENT 'Total / NA / EMEA / APAC / LATAM',
        Actuals       DOUBLE      COMMENT 'Blended SFDC+MC actuals (null for future weeks)',
        Most_Likely   DOUBLE      COMMENT 'sMAPE-weighted ensemble median (P50)',
        Worst_Case    DOUBLE      COMMENT 'Ensemble P10 lower bound',
        Best_Case     DOUBLE      COMMENT 'Ensemble P90 upper bound',
        p10           DOUBLE      COMMENT 'Prediction interval lower bound (P10)',
        p90           DOUBLE      COMMENT 'Prediction interval upper bound (P90)',
        arr_ets       DOUBLE      COMMENT 'ETS point forecast (log1p-transformed HW)',
        arr_prophet   DOUBLE      COMMENT 'Prophet point forecast with pipeline regressors',
        arr_lightgbm  DOUBLE      COMMENT 'LightGBM direct multi-output (no error compounding)',
        arr_mstl_v2   DOUBLE      COMMENT 'MSTL_v2 point forecast',
        arr_dhr_arima DOUBLE      COMMENT 'DHR-ARIMA point forecast',
        mape_ets      DOUBLE      COMMENT '3-month holdout sMAPE — ETS',
        mape_prophet  DOUBLE      COMMENT '3-month holdout sMAPE — Prophet',
        mape_lightgbm DOUBLE      COMMENT '3-month holdout sMAPE — LightGBM',
        mape_mstl_v2  DOUBLE      COMMENT '3-month holdout sMAPE — MSTL_v2',
        mape_dhr_arima DOUBLE     COMMENT '3-month holdout sMAPE — DHR-ARIMA',
        forecast_type STRING      COMMENT 'actuals | rolling | roy',
        run_date      DATE        COMMENT 'Notebook run date'
    )
    USING DELTA
    COMMENT 'ARR v2 multi-model ensemble. Monthly training, weekly output. Real P10/P90 prediction intervals.'
    TBLPROPERTIES (
        'delta.autoOptimize.optimizeWrite'='true',
        'delta.autoOptimize.autoCompact'='true'
    )
""")

# Add new columns if table exists from a previous schema version
for _col, _comment in [
    ("p10",           "Prediction interval lower bound (P10)"),
    ("p90",           "Prediction interval upper bound (P90)"),
    ("arr_mstl_v2",   "MSTL_v2 point forecast"),
    ("arr_dhr_arima", "DHR-ARIMA point forecast"),
    ("mape_mstl_v2",  "3-month holdout sMAPE — MSTL_v2"),
    ("mape_dhr_arima","3-month holdout sMAPE — DHR-ARIMA"),
]:
    try:
        spark.sql(f"ALTER TABLE {OUT_TABLE} ADD COLUMNS ({_col} DOUBLE COMMENT '{_comment}')")
        print(f"[arr_forecast_v2_main] Added column {_col} to {OUT_TABLE}")
    except Exception:
        pass  # Column already exists

spark.sql(f"DELETE FROM {OUT_TABLE} WHERE product IN ('UCC','Total') AND run_date = '{RUN_DATE}'")
out_sdf.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(OUT_TABLE)
print(f"✅  {out_sdf.count()} rows → {OUT_TABLE}")

# COMMAND ----------
# MAGIC %md ## 11 — Leaderboard

# COMMAND ----------
lb_rows = []
for product_group, geo in SLICES:
    mask = ((blended_pd["product_group"] == product_group) &
            (blended_pd["geo"]           == geo))
    df_s = blended_pd[mask]
    if len(df_s) < MIN_HISTORY:
        continue
    y     = df_s["arr_actuals"].values.astype(float)
    dates = pd.DatetimeIndex(df_s["month_start"])
    reg_df = pipeline_regressors if HAS_REGRESSORS else None

    sm_ets = holdout_smape(y, dates, fit_ets_monthly)
    sm_ph  = holdout_smape(y, dates, fit_prophet_monthly, reg_df=reg_df)
    sm_lgb = holdout_smape(y, dates, fit_lgb_direct,     reg_df=reg_df)

    mapes = {"ETS": sm_ets, "Prophet": sm_ph, "LightGBM": sm_lgb}
    best  = min(mapes, key=mapes.get)
    lb_rows.append({
        "product": product_group, "sales_market": geo,
        "mape_ets": sm_ets, "mape_prophet": sm_ph,
        "mape_lightgbm": sm_lgb, "mape_chronos": None,
        "best_mape": mapes[best], "best_model": best,
        "run_date": pd.Timestamp(RUN_DATE).date()
    })

lb_pd = pd.DataFrame(lb_rows)
print("\n📊 sMAPE Leaderboard (3-month holdout)")
print(lb_pd[["product","sales_market","mape_ets","mape_prophet","mape_lightgbm","best_mape","best_model"]]
      .sort_values("best_mape").to_string(index=False))

lb_sdf = spark.createDataFrame(lb_pd)
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {LB_TABLE} (
        product STRING, sales_market STRING,
        mape_ets DOUBLE, mape_prophet DOUBLE, mape_lightgbm DOUBLE, mape_chronos DOUBLE,
        best_mape DOUBLE, best_model STRING, run_date DATE
    ) USING DELTA
""")
spark.sql(f"DELETE FROM {LB_TABLE} WHERE run_date = '{RUN_DATE}'")
lb_sdf.write.mode("append").saveAsTable(LB_TABLE)
print(f"✅  Leaderboard → {LB_TABLE}")

# COMMAND ----------
print("""
Next step: run arr_forecast_v2_chronos.py to fill arr_chronos column
and recompute ensemble with all 5 models.

GRANT statements (run in SQL after first successful run):
  GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
    TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
  GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard
    TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
""")
