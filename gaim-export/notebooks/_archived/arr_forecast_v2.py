# Databricks notebook source
# MAGIC %md
# MAGIC # ARR Forecast v2 — Total · Product · Geo Ensemble
# MAGIC
# MAGIC **5-model ensemble**: ETS · Prophet · LightGBM · Chronos · Ensemble
# MAGIC **Output**: `datagroup_mdl.mdl_sales_analytics.arr_forecast_v2`
# MAGIC **Grain**: (week × product × sales_market) + Total aggregates
# MAGIC **Actuals**: SFDC for in-flight month · MC reconciled for all closed months
# MAGIC **Forecast types**: Rolling 13-week AND Rest-of-Year (RoY)
# MAGIC **Target**: MAPE < 15% per slice via quarter-end spike features

# COMMAND ----------
# MAGIC %pip install prophet lightgbm statsmodels transformers torch --quiet

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
from sklearn.model_selection import TimeSeriesSplit

# ── Config ────────────────────────────────────────────────────────────────────
CATALOG      = "datagroup_mdl"
SCHEMA       = "mdl_sales_analytics"
OUT_TABLE    = f"{CATALOG}.{SCHEMA}.arr_forecast_v2"
LB_TABLE     = f"{CATALOG}.{SCHEMA}.arr_forecast_v2_leaderboard"

SFDC_TABLE   = "datalake_transform.cds_sfdc_opp_products_latest"
MC_TABLE     = f"{CATALOG}.{SCHEMA}.mc_actuals"

TODAY            = datetime.date.today()
RUN_DATE         = TODAY
CUR_MONTH_START  = TODAY.replace(day=1)

ROLLING_WEEKS    = 13
ROY_WEEKS        = max(math.ceil((datetime.date(TODAY.year, 12, 28) - TODAY).days / 7), 4)
TRAIN_FROM       = "2022-01-01"

# product_genus → product_group
PRODUCT_MAP = {
    "GoTo Connect": "UCC",  "GoTo Engage":  "UCC",
    "GoTo Resolve": "ITSG", "GoTo Central": "ITSG", "Rescue": "ITSG",
}

# raw sales_market → canonical geo
GEO_NORM = {
    "NA":"NA","US":"NA","North America":"NA","NAMER":"NA","AMER":"NA",
    "EMEA":"EMEA","Europe":"EMEA","EUR":"EMEA",
    "APAC":"APAC","Asia Pacific":"APAC","APJ":"APAC","AUS":"APAC","ROW":"APAC",
    "LATAM":"LATAM","Latin America":"LATAM",
}

print(f"Run: {RUN_DATE}  closed-month cutoff: {CUR_MONTH_START}")
print(f"Rolling: {ROLLING_WEEKS}w  RoY: {ROY_WEEKS}w")

# COMMAND ----------
# MAGIC %md ## 1 — SFDC Weekly Actuals

# COMMAND ----------
prod_case  = "CASE " + " ".join(f"WHEN product_genus='{k}' THEN '{v}'" for k,v in PRODUCT_MAP.items()) + " ELSE 'Other' END"
geo_case_s = "CASE " + " ".join(f"WHEN sales_market='{k}'  THEN '{v}'" for k,v in GEO_NORM.items())  + " ELSE 'Other' END"

sfdc_raw = spark.sql(f"""
    SELECT
        date_trunc('week', close_date)    AS week_start,
        {prod_case}                       AS product_group,
        {geo_case_s}                      AS geo,
        SUM(COALESCE(arr, 0))             AS arr_sfdc
    FROM {SFDC_TABLE}
    WHERE is_won       = 'True'
      AND purchase_type = 'Growth'
      AND close_date   >= '{TRAIN_FROM}'
      AND close_date   <  current_date()
      AND COALESCE(arr, 0) > 0
    GROUP BY 1, 2, 3
""").filter(
    F.col("product_group").isin("UCC","ITSG") &
    F.col("geo").isin("NA","EMEA","APAC","LATAM")
)

# Add Total aggregates
sfdc_tot_p = sfdc_raw.groupBy("week_start","geo").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("product_group",F.lit("Total"))
sfdc_tot_g = sfdc_raw.groupBy("week_start","product_group").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("geo",F.lit("Total"))
sfdc_tot   = sfdc_raw.groupBy("week_start").agg(F.sum("arr_sfdc").alias("arr_sfdc")).withColumn("product_group",F.lit("Total")).withColumn("geo",F.lit("Total"))
sfdc_all   = sfdc_raw.union(sfdc_tot_p).union(sfdc_tot_g).union(sfdc_tot)

print("SFDC rows:", sfdc_all.count())

# COMMAND ----------
# MAGIC %md ## 2 — MC Reconciled Actuals (closed months only)

# COMMAND ----------
geo_case_mc = "CASE " + " ".join(f"WHEN `Sales Market`='{k}' THEN '{v}'" for k,v in GEO_NORM.items()) + " ELSE 'Other' END"

mc_raw = spark.sql(f"""
    SELECT
        date_trunc('month', `Month of Data Month`)                                         AS data_month,
        CASE WHEN `Business Unit`='UCC'  THEN 'UCC'
             WHEN `Business Unit`='ITSG' THEN 'ITSG'
             ELSE 'Other' END                                                              AS product_group,
        {geo_case_mc}                                                                      AS geo,
        SUM(CAST(`Reported Bookings Total In USD Order Month Rate` AS DOUBLE))             AS arr_mc
    FROM {MC_TABLE}
    WHERE `Version`       = 'Actuals'
      AND `Purchase Type` = 'Growth'
      AND `Month of Data Month` < '{CUR_MONTH_START}'
      AND `Month of Data Month` >= '{TRAIN_FROM}'
    GROUP BY 1, 2, 3
""").filter(
    F.col("product_group").isin("UCC","ITSG") &
    F.col("geo").isin("NA","EMEA","APAC","LATAM")
)

mc_tot_p = mc_raw.groupBy("data_month","geo").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("product_group",F.lit("Total"))
mc_tot_g = mc_raw.groupBy("data_month","product_group").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("geo",F.lit("Total"))
mc_tot   = mc_raw.groupBy("data_month").agg(F.sum("arr_mc").alias("arr_mc")).withColumn("product_group",F.lit("Total")).withColumn("geo",F.lit("Total"))
mc_all   = mc_raw.union(mc_tot_p).union(mc_tot_g).union(mc_tot)

print("MC rows:", mc_all.count())

# COMMAND ----------
# MAGIC %md ## 3 — Blend: MC overrides SFDC for closed months

# COMMAND ----------
sfdc_with_month = sfdc_all.withColumn("data_month", F.date_trunc("month", F.col("week_start")))

sfdc_month_sum = sfdc_with_month.groupBy("data_month","product_group","geo").agg(
    F.sum("arr_sfdc").alias("arr_sfdc_month")
)

blended = (
    sfdc_with_month
    .join(sfdc_month_sum, ["data_month","product_group","geo"], "left")
    .join(mc_all.withColumnRenamed("arr_mc","arr_mc_month"), ["data_month","product_group","geo"], "left")
    .withColumn("arr_actuals",
        F.when(
            (F.col("data_month") < F.lit(CUR_MONTH_START)) &
            F.col("arr_mc_month").isNotNull() &
            (F.col("arr_sfdc_month") > 0),
            F.col("arr_sfdc") * (F.col("arr_mc_month") / F.col("arr_sfdc_month"))
        ).otherwise(F.col("arr_sfdc"))
    )
    .select("week_start","product_group","geo","arr_actuals")
    .orderBy("week_start")
)

blended_pd = blended.toPandas()
blended_pd["week_start"] = pd.to_datetime(blended_pd["week_start"])
print("Blended rows:", len(blended_pd))

# COMMAND ----------
# MAGIC %md ## 4 — Feature Engineering

# COMMAND ----------
def add_calendar_features(df: pd.DataFrame, date_col: str = "ds") -> pd.DataFrame:
    df = df.copy()
    dt = pd.to_datetime(df[date_col])
    df["year"]                = dt.dt.year
    df["month"]               = dt.dt.month
    df["iso_week"]            = dt.dt.isocalendar().week.astype(int)
    df["quarter"]             = dt.dt.quarter
    q_start = dt.dt.to_period("Q").dt.start_time
    df["week_of_quarter"]     = ((dt - q_start).dt.days // 7 + 1).clip(1, 13)
    # Quarter-end spike flags — critical for MAPE < 15%
    df["is_quarter_end_week"] = (df["week_of_quarter"] >= 12).astype(int)
    df["is_quarter_last_week"]= (df["week_of_quarter"] == 13).astype(int)
    df["is_summer"]           = dt.dt.month.isin([6,7,8]).astype(int)
    df["is_year_end"]         = dt.dt.month.isin([11,12]).astype(int)
    df["is_week1"]            = (df["iso_week"] == 1).astype(int)
    return df

# COMMAND ----------
# MAGIC %md ## 5 — Model Functions

# COMMAND ----------
# ── ETS ───────────────────────────────────────────────────────────────────────
def fit_ets(y, h):
    try:
        model = ExponentialSmoothing(
            y, trend="add", seasonal="mul", seasonal_periods=13,
            initialization_method="estimated"
        ).fit(optimized=True)
        fc  = model.forecast(h)
        sim = model.simulate(h, repetitions=300, error="mul")
        lo  = np.nanpercentile(sim, 10, axis=1)
        hi  = np.nanpercentile(sim, 90, axis=1)
        return np.maximum(fc,0), np.maximum(lo,0), np.maximum(hi,0)
    except Exception:
        mu = y[-4:].mean()
        return np.full(h,mu), np.full(h,mu*0.85), np.full(h,mu*1.15)

# ── Prophet ───────────────────────────────────────────────────────────────────
def _qe_flag(dt_series):
    q_start = dt_series.dt.to_period("Q").dt.start_time
    wq = ((dt_series - q_start).dt.days // 7 + 1).clip(1, 13)
    return (wq >= 12).astype(float)

def fit_prophet(df_train, h):
    """Prophet with quarterly/monthly seasonality + quarter-end regressor."""
    df_p = df_train[["ds","y"]].copy()
    df_p["is_quarter_end_week"] = _qe_flag(pd.to_datetime(df_p["ds"]))

    m = Prophet(
        changepoint_prior_scale=0.08, seasonality_prior_scale=15,
        seasonality_mode="multiplicative", interval_width=0.80,
        yearly_seasonality=False, weekly_seasonality=False, daily_seasonality=False,
    )
    m.add_seasonality("quarterly",        period=91.25, fourier_order=8)
    m.add_seasonality("monthly",          period=30.44, fourier_order=5)
    m.add_seasonality("quarter_end_spike",period=91.25, fourier_order=3,
                       condition_name="is_quarter_end_week")
    m.add_regressor("is_quarter_end_week", prior_scale=15, standardize=False)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.fit(df_p)

    future = m.make_future_dataframe(periods=h, freq="W-MON", include_history=False)
    future["is_quarter_end_week"] = _qe_flag(pd.to_datetime(future["ds"]))
    fc = m.predict(future)
    return (np.maximum(fc["yhat"].values,0),
            np.maximum(fc["yhat_lower"].values,0),
            np.maximum(fc["yhat_upper"].values,0))

# ── LightGBM ──────────────────────────────────────────────────────────────────
N_LAGS = 8

def _make_features(y, dates):
    df = pd.DataFrame({"y": y, "ds": pd.to_datetime(dates)})
    df = add_calendar_features(df, "ds")
    for lag in range(1, N_LAGS+1):
        df[f"lag_{lag}"] = df["y"].shift(lag)
    df["rolling_4"]  = df["y"].shift(1).rolling(4).mean()
    df["rolling_13"] = df["y"].shift(1).rolling(13).mean()
    return df.dropna()

FEAT_COLS = None  # set lazily

def fit_lgb(y, dates, h):
    global FEAT_COLS
    n_lags = N_LAGS
    df_full = _make_features(y, dates)
    FEAT_COLS = [c for c in df_full.columns if c not in ("y","ds")]
    X, Y = df_full[FEAT_COLS].values, df_full["y"].values

    # Estimate residual std via 4-fold TSCV
    tscv = TimeSeriesSplit(n_splits=4)
    resids = []
    for tr, va in tscv.split(X):
        clf = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.04,
                                 num_leaves=20, min_child_samples=5,
                                 subsample=0.8, colsample_bytree=0.8,
                                 random_state=42, verbose=-1)
        clf.fit(X[tr], Y[tr])
        resids.extend((Y[va] - clf.predict(X[va])).tolist())

    resid_std = np.std(resids) if resids else Y.std()*0.1

    clf_final = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.04,
                                   num_leaves=20, min_child_samples=5,
                                   subsample=0.8, colsample_bytree=0.8,
                                   random_state=42, verbose=-1)
    clf_final.fit(X, Y)

    # 50-path Monte Carlo
    N_PATHS = 50
    paths = np.zeros((N_PATHS, h))
    last_ds = pd.to_datetime(dates.iloc[-1])

    for pi in range(N_PATHS):
        y_buf  = list(y.copy())
        d_buf  = list(pd.to_datetime(dates))
        fc_p   = []
        for step in range(h):
            nd = last_ds + pd.Timedelta(weeks=step+1)
            row_df = _make_features(np.array(y_buf), pd.Series(d_buf + [nd]))
            if len(row_df) == 0:
                fc_p.append(float(np.mean(y_buf[-4:])))
                y_buf.append(y_buf[-1]); d_buf.append(nd)
                continue
            row = row_df[FEAT_COLS].iloc[-1:].values
            pred = float(clf_final.predict(row)[0])
            noise = np.random.normal(0, resid_std)
            val = max(pred + noise, 0)
            fc_p.append(val)
            y_buf.append(pred); d_buf.append(nd)
        paths[pi] = fc_p

    return (np.maximum(paths.mean(0),0),
            np.maximum(np.percentile(paths,10,axis=0),0),
            np.maximum(np.percentile(paths,90,axis=0),0))

# ── Chronos ───────────────────────────────────────────────────────────────────
def fit_chronos(y, h):
    try:
        import torch
        from transformers import pipeline as hf_pipeline
        pipe = hf_pipeline(
            "text-generation", model="amazon/chronos-t5-small",
            device="cpu", torch_dtype=torch.float32,
        )
        ctx = torch.tensor(y, dtype=torch.float32).unsqueeze(0)
        out = pipe(ctx, prediction_length=h, num_samples=50)
        samples = np.array(out[0]["generated_text"])
        if samples.ndim == 1:
            samples = samples.reshape(1,-1)
        return (np.maximum(np.median(samples,0),0),
                np.maximum(np.percentile(samples,10,0),0),
                np.maximum(np.percentile(samples,90,0),0))
    except Exception as e:
        print(f"  Chronos fallback ({e})")
        mu = float(np.nanmean(y[-13:]))
        return np.full(h,mu), np.full(h,mu*0.85), np.full(h,mu*1.15)

# COMMAND ----------
# MAGIC %md ## 6 — MAPE & Holdout Evaluation

# COMMAND ----------
def compute_mape(y_true, y_pred):
    mask = y_true > 0
    if mask.sum() == 0: return 999.0
    return float(np.mean(np.abs((y_true[mask]-y_pred[mask])/y_true[mask]))*100)

def holdout_mape(y, dates, fn, h=8):
    if len(y) < h+26: return 999.0
    y_tr, y_te = y[:-h], y[-h:]
    d_tr = dates.iloc[:-h]
    try:
        if fn.__name__ == "fit_prophet":
            fc,_,_ = fn(pd.DataFrame({"ds":d_tr,"y":y_tr}), h)
        elif fn.__name__ == "fit_lgb":
            fc,_,_ = fn(y_tr, d_tr, h)
        else:
            fc,_,_ = fn(y_tr, h)
        return compute_mape(y_te, fc)
    except Exception:
        return 999.0

# COMMAND ----------
# MAGIC %md ## 7 — Forecast Slice Function

# COMMAND ----------
def forecast_slice(df_hist, h, forecast_type):
    """
    Full 5-model ensemble forecast for one (product, geo) slice.
    Returns DataFrame with forecast rows.
    """
    df_hist = df_hist.sort_values("ds").reset_index(drop=True)
    y       = df_hist["y"].values.astype(float)
    dates   = df_hist["ds"]

    if len(y) < 30:
        print(f"  Skipping — only {len(y)} rows")
        return pd.DataFrame()

    # Clip outliers but preserve quarter-end spikes (wide 4.5× IQR fence)
    q1, q3 = np.percentile(y,25), np.percentile(y,75)
    y_c = np.clip(y, 0, q3 + 4.5*(q3-q1))

    print(f"  Holdout MAPE evaluation (8-week)...")
    m_ets = holdout_mape(y_c, dates, fit_ets)
    m_ph  = holdout_mape(y_c, dates, fit_prophet)
    m_lgb = holdout_mape(y_c, dates, fit_lgb)
    m_chr = holdout_mape(y_c, dates, fit_chronos)
    print(f"  ETS:{m_ets:.1f}%  Prophet:{m_ph:.1f}%  LGB:{m_lgb:.1f}%  Chronos:{m_chr:.1f}%")

    df_tr = pd.DataFrame({"ds": dates, "y": y_c})

    fc_ets, lo_ets, hi_ets = fit_ets(y_c, h)
    fc_ph,  lo_ph,  hi_ph  = fit_prophet(df_tr, h)
    fc_lgb, lo_lgb, hi_lgb = fit_lgb(y_c, dates, h)
    fc_chr, lo_chr, hi_chr = fit_chronos(y_c, h)

    # Inverse-MAPE weighted ensemble
    def iw(m): return 1.0 / max(m, 0.1)
    tw = sum(iw(x) for x in [m_ets, m_ph, m_lgb, m_chr])
    we, wp, wl, wc = iw(m_ets)/tw, iw(m_ph)/tw, iw(m_lgb)/tw, iw(m_chr)/tw
    print(f"  Weights → ETS:{we:.2f} Prophet:{wp:.2f} LGB:{wl:.2f} Chr:{wc:.2f}")

    fc_ens = we*fc_ets + wp*fc_ph + wl*fc_lgb + wc*fc_chr
    lo_ens = we*lo_ets + wp*lo_ph + wl*lo_lgb + wc*lo_chr
    hi_ens = we*hi_ets + wp*hi_ph + wl*hi_lgb + wc*hi_chr

    worst = np.minimum(lo_ens, fc_ens*0.88)
    best  = np.maximum(hi_ens, fc_ens*1.12)

    future_dates = pd.date_range(
        pd.to_datetime(dates.max()) + pd.Timedelta(weeks=1),
        periods=h, freq="W-MON"
    )

    return pd.DataFrame({
        "ds":            future_dates,
        "Most_Likely":   np.maximum(fc_ens,0),
        "Worst_Case":    np.maximum(worst, 0),
        "Best_Case":     np.maximum(best,  0),
        "arr_ets":       np.maximum(fc_ets,0),
        "arr_prophet":   np.maximum(fc_ph, 0),
        "arr_lightgbm":  np.maximum(fc_lgb,0),
        "arr_chronos":   np.maximum(fc_chr,0),
        "mape_ets":      m_ets,
        "mape_prophet":  m_ph,
        "mape_lightgbm": m_lgb,
        "mape_chronos":  m_chr,
        "forecast_type": forecast_type,
    })

# COMMAND ----------
# MAGIC %md ## 8 — Main Loop

# COMMAND ----------
SLICES = [
    ("Total","Total"),
    ("UCC",  "Total"), ("ITSG","Total"),
    ("Total","NA"),    ("Total","EMEA"), ("Total","APAC"), ("Total","LATAM"),
    ("UCC",  "NA"),    ("UCC", "EMEA"),
    ("ITSG", "NA"),    ("ITSG","EMEA"),
]

all_fc, all_actuals = [], []

for product_group, geo in SLICES:
    print(f"\n{'='*55}")
    print(f"  product={product_group}  geo={geo}")
    print(f"{'='*55}")

    mask = (
        (blended_pd["product_group"] == product_group) &
        (blended_pd["geo"]           == geo)
    )
    df_s = (blended_pd[mask]
            .rename(columns={"week_start":"ds","arr_actuals":"y"})
            [["ds","y"]]
            .dropna(subset=["y"])
            .reset_index(drop=True))

    # Historical actuals rows
    act = df_s.copy()
    act["product"]      = product_group
    act["sales_market"] = geo
    act["Actuals"]      = act["y"]
    act["Most_Likely"]  = None; act["Worst_Case"]    = None; act["Best_Case"]     = None
    act["arr_ets"]      = None; act["arr_prophet"]   = None; act["arr_lightgbm"]  = None
    act["arr_chronos"]  = None
    act["mape_ets"]     = None; act["mape_prophet"]  = None; act["mape_lightgbm"] = None
    act["mape_chronos"] = None
    act["forecast_type"]= "actuals"
    all_actuals.append(act.drop(columns=["y"]))

    if len(df_s) < 30:
        print(f"  Insufficient history — skipping forecasts")
        continue

    for fc_type, horizon in [("rolling", ROLLING_WEEKS), ("roy", ROY_WEEKS)]:
        print(f"\n  ── {fc_type} ({horizon}w) ──")
        try:
            fc_df = forecast_slice(df_s, horizon, fc_type)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        if fc_df.empty:
            continue
        fc_df["product"]      = product_group
        fc_df["sales_market"] = geo
        fc_df["Actuals"]      = None
        all_fc.append(fc_df)

actuals_pd  = pd.concat(all_actuals,  ignore_index=True) if all_actuals  else pd.DataFrame()
forecast_pd = pd.concat(all_fc,       ignore_index=True) if all_fc       else pd.DataFrame()
combined_pd = pd.concat([actuals_pd, forecast_pd], ignore_index=True)
combined_pd["run_date"] = pd.Timestamp(RUN_DATE)
combined_pd["ds"]       = pd.to_datetime(combined_pd["ds"]).dt.date

print(f"\nTotal output rows: {len(combined_pd)}")
print(combined_pd.groupby(["product","sales_market","forecast_type"]).size().to_string())

# COMMAND ----------
# MAGIC %md ## 9 — Write arr_forecast_v2

# COMMAND ----------
SCHEMA_FIELDS = StructType([
    StructField("ds",            DateType(),   True),
    StructField("product",       StringType(), True),
    StructField("sales_market",  StringType(), True),
    StructField("Actuals",       DoubleType(), True),
    StructField("Most_Likely",   DoubleType(), True),
    StructField("Worst_Case",    DoubleType(), True),
    StructField("Best_Case",     DoubleType(), True),
    StructField("arr_ets",       DoubleType(), True),
    StructField("arr_prophet",   DoubleType(), True),
    StructField("arr_lightgbm",  DoubleType(), True),
    StructField("arr_chronos",   DoubleType(), True),
    StructField("mape_ets",      DoubleType(), True),
    StructField("mape_prophet",  DoubleType(), True),
    StructField("mape_lightgbm", DoubleType(), True),
    StructField("mape_chronos",  DoubleType(), True),
    StructField("forecast_type", StringType(), True),
    StructField("run_date",      DateType(),   True),
])

for col in ["Actuals","Most_Likely","Worst_Case","Best_Case",
            "arr_ets","arr_prophet","arr_lightgbm","arr_chronos",
            "mape_ets","mape_prophet","mape_lightgbm","mape_chronos"]:
    if col in combined_pd.columns:
        combined_pd[col] = pd.to_numeric(combined_pd[col], errors="coerce")

out_sdf = spark.createDataFrame(combined_pd, schema=SCHEMA_FIELDS)

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {OUT_TABLE} (
        ds            DATE,
        product       STRING    COMMENT 'Total / UCC / ITSG',
        sales_market  STRING    COMMENT 'Total / NA / EMEA / APAC / LATAM',
        Actuals       DOUBLE    COMMENT 'Blended SFDC+MC actuals (null for future weeks)',
        Most_Likely   DOUBLE    COMMENT 'MAPE-weighted ensemble median',
        Worst_Case    DOUBLE    COMMENT 'Ensemble P20 lower bound',
        Best_Case     DOUBLE    COMMENT 'Ensemble P80 upper bound',
        arr_ets       DOUBLE    COMMENT 'ETS point forecast',
        arr_prophet   DOUBLE    COMMENT 'Prophet point forecast',
        arr_lightgbm  DOUBLE    COMMENT 'LightGBM Monte Carlo mean',
        arr_chronos   DOUBLE    COMMENT 'Chronos-T5-Small median',
        mape_ets      DOUBLE    COMMENT '8-week holdout MAPE — ETS',
        mape_prophet  DOUBLE    COMMENT '8-week holdout MAPE — Prophet',
        mape_lightgbm DOUBLE    COMMENT '8-week holdout MAPE — LightGBM',
        mape_chronos  DOUBLE    COMMENT '8-week holdout MAPE — Chronos',
        forecast_type STRING    COMMENT 'actuals | rolling | roy',
        run_date      DATE      COMMENT 'Notebook run date'
    )
    USING DELTA
    COMMENT 'ARR v2 5-model ensemble forecast. Sources: SFDC (in-flight month) + MC actuals (closed months). MAPE target < 15%.'
    TBLPROPERTIES (
        'delta.autoOptimize.optimizeWrite'='true',
        'delta.autoOptimize.autoCompact'='true'
    )
""")

spark.sql(f"DELETE FROM {OUT_TABLE} WHERE run_date = '{RUN_DATE}'")
out_sdf.write.mode("append").saveAsTable(OUT_TABLE)
print(f"✅  {out_sdf.count()} rows → {OUT_TABLE}")

# COMMAND ----------
# MAGIC %md ## 10 — Leaderboard

# COMMAND ----------
lb_pd = (
    combined_pd[combined_pd["forecast_type"] != "actuals"]
    .groupby(["product","sales_market"])
    [["mape_ets","mape_prophet","mape_lightgbm","mape_chronos"]]
    .first()
    .reset_index()
)
lb_pd["best_mape"]  = lb_pd[["mape_ets","mape_prophet","mape_lightgbm","mape_chronos"]].min(axis=1)
lb_pd["best_model"] = (lb_pd[["mape_ets","mape_prophet","mape_lightgbm","mape_chronos"]]
                       .idxmin(axis=1).str.replace("mape_","").str.title())
lb_pd["run_date"]   = pd.Timestamp(RUN_DATE)

print("\n📊 MAPE Leaderboard")
print(lb_pd.sort_values("best_mape").to_string(index=False))

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
# MAGIC %md ## 11 — Update v2 Backend Routes to Read New Table

# COMMAND ----------
# The backend route forecast_v2.py reads from:
#   datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
#   filter: forecast_type IN ('rolling','roy') for forecast rows
#           forecast_type = 'actuals'          for historical rows
#   columns: ds → date, product, sales_market, Actuals, Most_Likely, Worst_Case, Best_Case
#            arr_ets, arr_prophet, arr_lightgbm, arr_chronos
#            mape_ets, mape_prophet, mape_lightgbm, mape_chronos, forecast_type
#
# GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_v2
#   TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
# GRANT SELECT ON TABLE datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard
#   TO `324a6ec7-e988-42c7-8a7f-55465f5bea37`;
print("Done. Run the GRANT statements above in a SQL cell after first job run.")
