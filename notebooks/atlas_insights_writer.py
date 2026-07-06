# Databricks notebook source
# MAGIC %md
# MAGIC # Atlas Executive Insights — Forecast Data Writer
# MAGIC
# MAGIC **Purpose:** Read UCC + ITSG production forecast outputs, combine with actuals,
# MAGIC and write to `arr_forecast_v2` and `arr_forecast_v2_leaderboard` so every
# MAGIC AI feature in the Atlas app has live data.
# MAGIC
# MAGIC **Run cadence:** Weekly on Monday morning, after UCC and ITSG forecast notebooks complete.
# MAGIC
# MAGIC **Writes to (append, partitioned by run_date):**
# MAGIC - `datagroup_mdl.mdl_sales_analytics.arr_forecast_v2`
# MAGIC - `datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard`
# MAGIC
# MAGIC **Reads from (read-only):**
# MAGIC - `datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5`
# MAGIC - `datagroup_mdl.mdl_sales_analytics.itsg_forecast_v5`
# MAGIC - `datagroup_mdl.mdl_sales_analytics.ucc_forecast_monitoring_baseline`
# MAGIC - `datagroup_mdl.mdl_sales_analytics.itsg_forecast_monitoring_baseline`
# MAGIC - `datagroup.datalake_transform.cds_sfdc_opp_products_latest`

# COMMAND ----------

# STEP 0: DEPENDENCIES
%pip install pandas numpy

# COMMAND ----------

# STEP 1: CONFIGURATION

import numpy as np
import pandas as pd

# ── Source tables (read-only) ────────────────────────────────────────────────
UCC_FORECAST_TABLE       = "datagroup_mdl.mdl_sales_analytics.ucc_forecast_v5"
ITSG_FORECAST_TABLE      = "datagroup_mdl.mdl_sales_analytics.itsg_forecast_v5"
UCC_MONITORING_TABLE     = "datagroup_mdl.mdl_sales_analytics.ucc_forecast_monitoring_baseline"
ITSG_MONITORING_TABLE    = "datagroup_mdl.mdl_sales_analytics.itsg_forecast_monitoring_baseline"
SFDC_TABLE               = "datagroup.datalake_transform.cds_sfdc_opp_products_latest"

# ── Target tables (write) ────────────────────────────────────────────────────
FORECAST_V2_TABLE        = "datagroup_mdl.mdl_sales_analytics.arr_forecast_v2"
LEADERBOARD_TABLE        = "datagroup_mdl.mdl_sales_analytics.arr_forecast_v2_leaderboard"

# ── Runtime constants ────────────────────────────────────────────────────────
RUN_DATE          = pd.Timestamp.today().normalize().date()
TODAY             = pd.Timestamp.today().normalize()
CURRENT_WEEK      = TODAY - pd.to_timedelta(TODAY.weekday(), unit="D")
LAST_CLOSED_WEEK  = CURRENT_WEEK - pd.Timedelta(weeks=1)
ACTUALS_START     = pd.Timestamp("2023-01-02")
YEAR_END          = pd.Timestamp(f"{TODAY.year}-12-28")  # last Monday of year

# Rolling quarter = next 13 Mondays from today
ROLLING_HORIZON = 13
ROY_END         = YEAR_END

# ── Model name mapping: production table model → app column ──────────────────
# UCC model names in ucc_forecast_v5
UCC_MODEL_MAP = {
    "ETS":                    "arr_ets",
    "Prophet_trend":          "arr_prophet",
    "Global_LGB_Q50_UCC":     "arr_lightgbm",
    "MSTL_v2":                "arr_chronos",     # MSTL used as Chronos proxy in app
    "DHR_ARIMA":              "_dhr",            # internal only — not surfaced as own model in app
    "Adaptive_Ensemble":      "_ensemble",
}
# ITSG model names in itsg_forecast_v5
ITSG_MODEL_MAP = {
    "ETS":                    "arr_ets",
    "Prophet_trend":          "arr_prophet",
    "Global_LGB_Q50_ITSG":    "arr_lightgbm",
    "MSTL_v2":                "arr_chronos",
    "DHR_ARIMA":              "_dhr",
    "Adaptive_Ensemble":      "_ensemble",
}

MARKET_MAP = {
    "AUS/ROW": "APAC",
    "INDIA":   "APAC",
    "UNKNOWN": "Unknown",
}

FORECAST_MARKETS = ["NA", "EMEA", "APAC", "LATAM", "Unknown"]

print(f"Run date : {RUN_DATE}")
print(f"Last closed week : {LAST_CLOSED_WEEK.date()}")
print(f"ROY end  : {ROY_END.date()}")
print(f"Writing  : {FORECAST_V2_TABLE}")

# COMMAND ----------

# STEP 2: LOAD ACTUALS FROM SFDC (UCC + ITSG)

def load_actuals(product_group: str, arr_col: str) -> pd.DataFrame:
    """
    Pull weekly closed-won ARR from SFDC.
    Returns: ds, sales_market, y (actuals ARR)
    """
    df = spark.sql(f"""
        SELECT
            DATE_TRUNC('WEEK', CAST(close_date AS DATE)) AS ds,
            COALESCE(UPPER(sales_market), 'UNKNOWN')     AS sales_market,
            SUM(CAST({arr_col} AS DOUBLE))               AS y
        FROM {SFDC_TABLE}
        WHERE COALESCE(is_won,    'False') = 'True'
          AND COALESCE(is_closed, 'False') = 'True'
          AND UPPER(COALESCE(product_group, '')) = '{product_group.upper()}'
          AND purchase_type_rollup = 'Growth'
          AND COALESCE(sales_channel, '') NOT IN ('Care', 'Sales Other')
          AND close_date >= DATE '{ACTUALS_START.date()}'
          AND close_date <= DATE '{LAST_CLOSED_WEEK.date()}'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).toPandas()
    df["ds"] = pd.to_datetime(df["ds"])
    df["sales_market"] = (
        df["sales_market"]
        .replace(MARKET_MAP)
        .replace({"UNKNOWN": "Unknown"})
        .fillna("Unknown")
    )
    df["y"] = pd.to_numeric(df["y"], errors="coerce").fillna(0.0)
    return df


ucc_actuals_by_mkt  = load_actuals("UCC",  "amount_towards_plan")
itsg_actuals_by_mkt = load_actuals("ITSG", "total_amount")

# Add Total market roll-up
def add_total_market(df: pd.DataFrame) -> pd.DataFrame:
    total = df.groupby("ds", as_index=False)["y"].sum()
    total["sales_market"] = "Total"
    return pd.concat([df, total], ignore_index=True)

ucc_actuals_by_mkt  = add_total_market(ucc_actuals_by_mkt)
itsg_actuals_by_mkt = add_total_market(itsg_actuals_by_mkt)

# Combined Total product
combined_actuals = (
    pd.concat([ucc_actuals_by_mkt, itsg_actuals_by_mkt], ignore_index=True)
    .groupby(["ds", "sales_market"], as_index=False)["y"].sum()
)

print(f"UCC actuals rows   : {len(ucc_actuals_by_mkt):,}")
print(f"ITSG actuals rows  : {len(itsg_actuals_by_mkt):,}")
print(f"Combined Total rows: {len(combined_actuals):,}")

# COMMAND ----------

# STEP 3: LOAD UCC PRODUCTION FORECASTS

def load_production_forecasts(table: str, model_map: dict) -> pd.DataFrame:
    """
    Load latest run from a production forecast table.
    Returns: ds, sales_market, model, p10, p50, p90
    Handles both 'p50'/'forecast' column naming variations.
    """
    schema = spark.sql(f"DESCRIBE TABLE {table}").toPandas()
    cols = [r["col_name"].lower() for r in schema.itertuples()]
    p50_col = "p50" if "p50" in cols else "forecast"

    df = spark.sql(f"""
        SELECT
            CAST(ds AS DATE)            AS ds,
            UPPER(COALESCE(sales_market, 'UNKNOWN')) AS sales_market,
            model,
            CAST(p10      AS DOUBLE)    AS p10,
            CAST({p50_col} AS DOUBLE)   AS p50,
            CAST(p90      AS DOUBLE)    AS p90
        FROM {table}
        WHERE CAST(run_date AS DATE) = (
            SELECT MAX(CAST(run_date AS DATE)) FROM {table}
        )
    """).toPandas()

    df["ds"] = pd.to_datetime(df["ds"])
    df["sales_market"] = (
        df["sales_market"]
        .replace(MARKET_MAP)
        .replace({"UNKNOWN": "Unknown"})
        .fillna("Unknown")
    )
    df["p10"] = pd.to_numeric(df["p10"], errors="coerce").clip(lower=0.0)
    df["p50"] = pd.to_numeric(df["p50"], errors="coerce").clip(lower=0.0)
    df["p90"] = pd.to_numeric(df["p90"], errors="coerce").clip(lower=0.0)

    # Keep only models in the map
    df = df[df["model"].isin(model_map)].copy()
    df["app_col"] = df["model"].map(model_map)

    # Add Total market roll-up for each model
    by_total = (
        df.groupby(["ds", "model", "app_col"], as_index=False)
        .agg(p10=("p10", "sum"), p50=("p50", "sum"), p90=("p90", "sum"))
    )
    by_total["sales_market"] = "Total"
    df = pd.concat([df, by_total], ignore_index=True)

    return df


ucc_forecasts  = load_production_forecasts(UCC_FORECAST_TABLE,  UCC_MODEL_MAP)
itsg_forecasts = load_production_forecasts(ITSG_FORECAST_TABLE, ITSG_MODEL_MAP)

print(f"UCC forecast rows  : {len(ucc_forecasts):,}")
print(f"ITSG forecast rows : {len(itsg_forecasts):,}")
print("UCC models present :", sorted(ucc_forecasts["model"].unique()))
print("ITSG models present:", sorted(itsg_forecasts["model"].unique()))

# COMMAND ----------

# STEP 4: LOAD MAPE METRICS FROM MONITORING BASELINES

def load_mape_from_monitoring(table: str, model_map: dict) -> dict:
    """
    Read holdout_wape_baseline per model from monitoring table.
    Returns dict: {app_col -> holdout_wape_pct}
    """
    try:
        df = spark.sql(f"""
            SELECT model, holdout_wape_baseline AS mape
            FROM {table}
            WHERE CAST(run_date_utc AS DATE) = (
                SELECT MAX(CAST(run_date_utc AS DATE)) FROM {table}
            )
        """).toPandas()
        result = {}
        for _, row in df.iterrows():
            app_col = model_map.get(row["model"])
            if app_col and app_col.startswith("arr_"):
                result[app_col] = float(row["mape"])
        return result
    except Exception as e:
        print(f"Warning: could not load MAPE from {table}: {e}")
        return {}


ucc_mape  = load_mape_from_monitoring(UCC_MONITORING_TABLE,  UCC_MODEL_MAP)
itsg_mape = load_mape_from_monitoring(ITSG_MONITORING_TABLE, ITSG_MODEL_MAP)

# Fallback defaults
DEFAULT_MAPE = {"arr_ets": 18.0, "arr_prophet": 20.0, "arr_lightgbm": 15.0, "arr_chronos": 19.0}
ucc_mape  = {**DEFAULT_MAPE, **ucc_mape}
itsg_mape = {**DEFAULT_MAPE, **itsg_mape}

print("UCC MAPE (holdout WAPE %):", ucc_mape)
print("ITSG MAPE (holdout WAPE %):", itsg_mape)

# COMMAND ----------

# STEP 5: PIVOT FORECASTS INTO WIDE FORMAT PER (ds, sales_market)

def pivot_forecasts(forecast_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert long (model, p10/p50/p90) to wide:
    ds, sales_market, Most_Likely, Worst_Case, Best_Case,
    arr_ets, arr_prophet, arr_lightgbm, arr_chronos
    """
    # Ensemble → Most_Likely / Worst_Case / Best_Case
    ensemble = forecast_df[forecast_df["app_col"] == "_ensemble"].copy()
    ensemble_wide = ensemble[["ds", "sales_market", "p10", "p50", "p90"]].rename(
        columns={"p50": "Most_Likely", "p10": "Worst_Case", "p90": "Best_Case"}
    )

    # Individual models → wide columns
    model_cols = [c for c in ["arr_ets", "arr_prophet", "arr_lightgbm", "arr_chronos"]]
    model_rows = forecast_df[forecast_df["app_col"].isin(model_cols)].copy()

    if model_rows.empty:
        wide = ensemble_wide.copy()
        for col in model_cols:
            wide[col] = np.nan
        return wide

    model_wide = model_rows.pivot_table(
        index=["ds", "sales_market"],
        columns="app_col",
        values="p50",
        aggfunc="first",
    ).reset_index()

    # Rename any missing model cols to NaN
    for col in model_cols:
        if col not in model_wide.columns:
            model_wide[col] = np.nan

    wide = ensemble_wide.merge(model_wide, on=["ds", "sales_market"], how="outer")
    return wide


ucc_wide  = pivot_forecasts(ucc_forecasts)
itsg_wide = pivot_forecasts(itsg_forecasts)

print(f"UCC wide rows   : {len(ucc_wide):,}  cols: {list(ucc_wide.columns)}")
print(f"ITSG wide rows  : {len(itsg_wide):,}  cols: {list(itsg_wide.columns)}")

# COMMAND ----------

# STEP 6: BUILD arr_forecast_v2 ROWS

FORECAST_COLS = ["Most_Likely", "Worst_Case", "Best_Case",
                 "arr_ets", "arr_prophet", "arr_lightgbm", "arr_chronos"]

def build_actuals_rows(actuals_df: pd.DataFrame, product: str, mape_dict: dict) -> pd.DataFrame:
    """
    Build forecast_type='actuals' rows from closed-won ARR.
    All forecast columns are null; Actuals column is filled.
    """
    rows = []
    for _, row in actuals_df.iterrows():
        r = {
            "ds":            row["ds"],
            "product":       product,
            "sales_market":  row["sales_market"],
            "Actuals":       row["y"],
            "forecast_type": "actuals",
        }
        for col in FORECAST_COLS:
            r[col] = np.nan
        # Attach MAPE values (constant per row)
        r["mape_ets"]       = mape_dict.get("arr_ets",       np.nan)
        r["mape_prophet"]   = mape_dict.get("arr_prophet",   np.nan)
        r["mape_lightgbm"]  = mape_dict.get("arr_lightgbm",  np.nan)
        r["mape_chronos"]   = mape_dict.get("arr_chronos",   np.nan)
        r["run_date"]       = RUN_DATE
        rows.append(r)
    return pd.DataFrame(rows)


def build_forecast_rows(wide_df: pd.DataFrame, product: str,
                        mape_dict: dict, actuals_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build forecast_type='rolling' and 'roy' rows from production forecasts.
    Weeks that have actuals: fill Actuals column.
    Future weeks: Actuals = null.
    Each future week written TWICE — as 'rolling' (first 13 weeks) AND 'roy'.
    """
    future_dates = wide_df["ds"].sort_values().unique()
    rolling_cutoff = pd.Timestamp(CURRENT_WEEK) + pd.Timedelta(weeks=ROLLING_HORIZON)

    # Build actuals lookup
    act_lookup = actuals_df.set_index(["ds", "sales_market"])["y"].to_dict()

    rows = []
    for _, row in wide_df.iterrows():
        ds           = pd.Timestamp(row["ds"])
        sales_market = row["sales_market"]
        actual_val   = act_lookup.get((ds, sales_market), np.nan)

        base = {
            "ds":           ds,
            "product":      product,
            "sales_market": sales_market,
            "Actuals":      actual_val,
            "mape_ets":     mape_dict.get("arr_ets",      np.nan),
            "mape_prophet": mape_dict.get("arr_prophet",  np.nan),
            "mape_lightgbm":mape_dict.get("arr_lightgbm", np.nan),
            "mape_chronos": mape_dict.get("arr_chronos",  np.nan),
            "run_date":     RUN_DATE,
        }
        for col in FORECAST_COLS:
            base[col] = row.get(col, np.nan)

        # Roy row — all forecast weeks
        if ds <= pd.Timestamp(ROY_END):
            rows.append({**base, "forecast_type": "roy"})

        # Rolling row — first 13 future weeks only
        if ds >= pd.Timestamp(CURRENT_WEEK) and ds < rolling_cutoff:
            rows.append({**base, "forecast_type": "rolling"})

    return pd.DataFrame(rows)


# UCC rows
ucc_act_rows  = build_actuals_rows(ucc_actuals_by_mkt,  "UCC",  ucc_mape)
ucc_fc_rows   = build_forecast_rows(ucc_wide, "UCC", ucc_mape, ucc_actuals_by_mkt)

# ITSG rows
itsg_act_rows = build_actuals_rows(itsg_actuals_by_mkt, "ITSG", itsg_mape)
itsg_fc_rows  = build_forecast_rows(itsg_wide, "ITSG", itsg_mape, itsg_actuals_by_mkt)

# Total (UCC + ITSG combined)
def combine_totals(ucc_df: pd.DataFrame, itsg_df: pd.DataFrame,
                   cols_to_sum: list) -> pd.DataFrame:
    """Sum UCC + ITSG numeric columns for product='Total'."""
    joined = pd.concat([ucc_df, itsg_df], ignore_index=True)
    grp_cols = ["ds", "sales_market", "forecast_type", "run_date"]
    # Keep MAPE as average
    mape_cols = ["mape_ets", "mape_prophet", "mape_lightgbm", "mape_chronos"]
    agg = {}
    for c in cols_to_sum:
        agg[c] = (c, "sum")
    for c in mape_cols:
        agg[c] = (c, "mean")
    total = joined.groupby(grp_cols, as_index=False).agg(**agg)
    total["product"] = "Total"
    return total


total_act_rows = combine_totals(ucc_act_rows,  itsg_act_rows,
                                ["Actuals"] + FORECAST_COLS)
total_fc_rows  = combine_totals(ucc_fc_rows,   itsg_fc_rows,
                                ["Actuals"] + FORECAST_COLS)

# ── Combine all rows ─────────────────────────────────────────────────────────
all_rows = pd.concat(
    [ucc_act_rows, ucc_fc_rows,
     itsg_act_rows, itsg_fc_rows,
     total_act_rows, total_fc_rows],
    ignore_index=True,
)

# Ensure column types
for col in FORECAST_COLS + ["Actuals"]:
    all_rows[col] = pd.to_numeric(all_rows[col], errors="coerce")
all_rows["run_date"] = pd.to_datetime(all_rows["run_date"]).dt.date

print(f"\narr_forecast_v2 rows to write: {len(all_rows):,}")
print(all_rows.groupby(["product", "forecast_type"]).size().reset_index(name="rows"))

# COMMAND ----------

# STEP 7: VALIDATION — SPOT-CHECK BEFORE WRITING

# Verify no negative forecasts
neg_check = all_rows[FORECAST_COLS + ["Actuals"]].lt(0).any()
assert not neg_check.any(), f"Negative values found: {neg_check[neg_check].index.tolist()}"

# Verify all products present
assert set(all_rows["product"].unique()) == {"UCC", "ITSG", "Total"}, \
    f"Missing products: {all_rows['product'].unique()}"

# Verify forecast types
assert set(all_rows["forecast_type"].unique()).issubset({"actuals", "rolling", "roy"}), \
    f"Unexpected forecast_type: {all_rows['forecast_type'].unique()}"

# Verify Best_Case >= Most_Likely >= Worst_Case (where not null)
fc_only = all_rows[all_rows["forecast_type"] != "actuals"].dropna(
    subset=["Most_Likely", "Worst_Case", "Best_Case"]
)
assert (fc_only["Best_Case"] >= fc_only["Most_Likely"]).all(), \
    "Best_Case < Most_Likely in some rows — check ensemble calibration"
assert (fc_only["Most_Likely"] >= fc_only["Worst_Case"]).all(), \
    "Most_Likely < Worst_Case in some rows — check ensemble calibration"

print("All validations passed.")
print("\nSample rows (UCC, Total market, first 3):")
display(
    all_rows[
        (all_rows["product"] == "UCC") & (all_rows["sales_market"] == "Total")
    ].sort_values("ds").head(3)
)

# COMMAND ----------

# STEP 8: WRITE arr_forecast_v2

spark.createDataFrame(all_rows).write \
    .mode("append") \
    .option("mergeSchema", "true") \
    .partitionBy("run_date") \
    .saveAsTable(FORECAST_V2_TABLE)

print(f"Written {len(all_rows):,} rows to {FORECAST_V2_TABLE} (run_date={RUN_DATE})")

# COMMAND ----------

# STEP 9: BUILD arr_forecast_v2_leaderboard

def build_leaderboard(ucc_mape: dict, itsg_mape: dict,
                      ucc_wide: pd.DataFrame, itsg_wide: pd.DataFrame) -> pd.DataFrame:
    """
    Build one row per (product, sales_market) with MAPE per model and best_model.
    """
    rows = []
    all_markets = ["Total"] + FORECAST_MARKETS

    for product, mape_dict, wide in [
        ("UCC",  ucc_mape,  ucc_wide),
        ("ITSG", itsg_mape, itsg_wide),
    ]:
        # Use mean combined MAPE for Total product
        combined_mape = {k: (ucc_mape.get(k, np.nan) + itsg_mape.get(k, np.nan)) / 2
                         for k in ["arr_ets", "arr_prophet", "arr_lightgbm", "arr_chronos"]}

        markets_in_data = wide["sales_market"].unique().tolist()

        for mkt in ["Total"] + [m for m in FORECAST_MARKETS if m in markets_in_data]:
            mape_ets      = mape_dict.get("arr_ets",       np.nan)
            mape_prophet  = mape_dict.get("arr_prophet",   np.nan)
            mape_lightgbm = mape_dict.get("arr_lightgbm",  np.nan)
            mape_chronos  = mape_dict.get("arr_chronos",   np.nan)

            candidates = {
                "ETS":       mape_ets,
                "Prophet":   mape_prophet,
                "LightGBM":  mape_lightgbm,
                "Chronos":   mape_chronos,
            }
            valid = {k: v for k, v in candidates.items() if not np.isnan(v)}
            best_model = min(valid, key=valid.get) if valid else "Ensemble"
            best_mape  = min(valid.values()) if valid else np.nan

            rows.append({
                "product":       product,
                "sales_market":  mkt,
                "mape_ets":      mape_ets,
                "mape_prophet":  mape_prophet,
                "mape_lightgbm": mape_lightgbm,
                "mape_chronos":  mape_chronos,
                "best_mape":     best_mape,
                "best_model":    best_model,
                "run_date":      RUN_DATE,
            })

    # Total product (UCC+ITSG combined)
    for mkt in ["Total"] + FORECAST_MARKETS:
        mape_ets      = np.nanmean([ucc_mape.get("arr_ets", np.nan),      itsg_mape.get("arr_ets", np.nan)])
        mape_prophet  = np.nanmean([ucc_mape.get("arr_prophet", np.nan),  itsg_mape.get("arr_prophet", np.nan)])
        mape_lightgbm = np.nanmean([ucc_mape.get("arr_lightgbm", np.nan), itsg_mape.get("arr_lightgbm", np.nan)])
        mape_chronos  = np.nanmean([ucc_mape.get("arr_chronos", np.nan),  itsg_mape.get("arr_chronos", np.nan)])
        candidates = {"ETS": mape_ets, "Prophet": mape_prophet,
                      "LightGBM": mape_lightgbm, "Chronos": mape_chronos}
        valid = {k: v for k, v in candidates.items() if not np.isnan(v)}
        rows.append({
            "product":       "Total",
            "sales_market":  mkt,
            "mape_ets":      mape_ets,
            "mape_prophet":  mape_prophet,
            "mape_lightgbm": mape_lightgbm,
            "mape_chronos":  mape_chronos,
            "best_mape":     min(valid.values()) if valid else np.nan,
            "best_model":    min(valid, key=valid.get) if valid else "Ensemble",
            "run_date":      RUN_DATE,
        })

    return pd.DataFrame(rows)


leaderboard_df = build_leaderboard(ucc_mape, itsg_mape, ucc_wide, itsg_wide)
leaderboard_df["run_date"] = pd.to_datetime(leaderboard_df["run_date"]).dt.date

print(f"Leaderboard rows: {len(leaderboard_df):,}")
display(leaderboard_df.sort_values(["product", "sales_market"]))

# COMMAND ----------

# STEP 10: WRITE arr_forecast_v2_leaderboard

spark.createDataFrame(leaderboard_df).write \
    .mode("append") \
    .option("mergeSchema", "true") \
    .partitionBy("run_date") \
    .saveAsTable(LEADERBOARD_TABLE)

print(f"Written {len(leaderboard_df):,} rows to {LEADERBOARD_TABLE} (run_date={RUN_DATE})")

# COMMAND ----------

# STEP 11: FINAL VALIDATION — QUERY BACK WRITTEN DATA

validation = spark.sql(f"""
    SELECT
        product,
        sales_market,
        forecast_type,
        COUNT(*)          AS rows,
        MIN(ds)           AS earliest_ds,
        MAX(ds)           AS latest_ds,
        ROUND(SUM(Most_Likely) / 1e6, 2) AS total_likely_m,
        ROUND(AVG(mape_ets), 2)           AS avg_mape_ets,
        ROUND(AVG(mape_prophet), 2)       AS avg_mape_prophet,
        ROUND(AVG(mape_lightgbm), 2)      AS avg_mape_lgb
    FROM {FORECAST_V2_TABLE}
    WHERE CAST(run_date AS DATE) = DATE '{RUN_DATE}'
    GROUP BY 1, 2, 3
    ORDER BY 1, 2, 3
""").toPandas()

print(f"\nValidation — rows written for run_date={RUN_DATE}:")
display(validation)

# COMMAND ----------

# STEP 12: ATLAS APP READINESS CHECK
# Verify the app's exact query patterns return data

print("\n--- Atlas App Readiness Check ---")

# Check 1: weekly endpoint pattern (product=UCC, sales_market=Total, forecast_type=rolling)
q1 = spark.sql(f"""
    SELECT COUNT(*) AS cnt, MIN(ds) AS ds_min, MAX(ds) AS ds_max
    FROM {FORECAST_V2_TABLE}
    WHERE product = 'UCC'
      AND sales_market = 'Total'
      AND forecast_type = 'rolling'
      AND CAST(run_date AS DATE) = (SELECT MAX(CAST(run_date AS DATE)) FROM {FORECAST_V2_TABLE})
""").toPandas()
print(f"Check 1 UCC rolling weekly : {q1.iloc[0].to_dict()}")

# Check 2: actuals pattern
q2 = spark.sql(f"""
    SELECT COUNT(*) AS cnt, SUM(Actuals)/1e6 AS actuals_m
    FROM {FORECAST_V2_TABLE}
    WHERE product = 'Total'
      AND sales_market = 'Total'
      AND forecast_type = 'actuals'
      AND CAST(run_date AS DATE) = (SELECT MAX(CAST(run_date AS DATE)) FROM {FORECAST_V2_TABLE})
""").toPandas()
print(f"Check 2 Total actuals      : {q2.iloc[0].to_dict()}")

# Check 3: leaderboard
q3 = spark.sql(f"""
    SELECT COUNT(*) AS cnt FROM {LEADERBOARD_TABLE}
    WHERE CAST(run_date AS DATE) = (SELECT MAX(CAST(run_date AS DATE)) FROM {LEADERBOARD_TABLE})
""").toPandas()
print(f"Check 3 leaderboard rows   : {q3.iloc[0]['cnt']}")

# Check 4: by-product endpoint needs product IN ('UCC','ITSG') AND sales_market='Total'
q4 = spark.sql(f"""
    SELECT product, SUM(Most_Likely)/1e6 AS likely_m, SUM(Worst_Case)/1e6 AS worst_m, SUM(Best_Case)/1e6 AS best_m
    FROM {FORECAST_V2_TABLE}
    WHERE product IN ('UCC','ITSG')
      AND sales_market = 'Total'
      AND forecast_type = 'rolling'
      AND CAST(run_date AS DATE) = (SELECT MAX(CAST(run_date AS DATE)) FROM {FORECAST_V2_TABLE})
    GROUP BY 1
""").toPandas()
print("Check 4 by-product rolling  :")
display(q4)

print("\nAll checks complete. Atlas app is ready to serve live data.")
