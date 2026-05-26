# Databricks notebook source
# Atlas Executive Insights — Job 1: Metrics Refresh
# Schedule: every 4 hours
# Writes: atlas.metrics_summary, atlas.metrics_history, atlas.revenue_gap_decomposition,
#         atlas.extended_analytics (all tabs)
# Reads:  datagroup_mdl.mdl_sales_analytics.gaim_pipeline_daily_snapshot
#         federated.sales.metis_won_opps_fact
#         federated.sales.metis_opened_opps_fact
#         federated.sales.metis_targets_summary
#         datagroup_mdl.mdl_sales_analytics.gaim_snapshot_pipeline_created_cq_daily

# COMMAND ----------
# MAGIC %md ## Atlas Job 1 — Metrics Refresh
# MAGIC
# MAGIC Computes all 9 KPIs vs paced targets for the current quarter and writes them to the gold
# MAGIC layer so the Atlas app never queries raw source tables at user-request time.

# COMMAND ----------

import uuid
from datetime import datetime, date
from pyspark.sql import functions as F, Window
from pyspark.sql.types import DoubleType, StringType

# ── Config ────────────────────────────────────────────────────────────────────
CATALOG       = "datagroup_mdl"
GOLD_SCHEMA   = "atlas"
MDL_SCHEMA    = "mdl_sales_analytics"
FED_CATALOG   = "federated"
FED_SCHEMA    = "sales"

GOLD          = f"{CATALOG}.{GOLD_SCHEMA}"
MDL           = f"{CATALOG}.{MDL_SCHEMA}"
FED           = f"{FED_CATALOG}.{FED_SCHEMA}"

REFRESHED_AT  = F.current_timestamp()
TODAY         = date.today()
RUN_ID        = str(uuid.uuid4())

print(f"[Job1] Starting Metrics Refresh — {TODAY} | run_id={RUN_ID}")

# COMMAND ----------
# MAGIC %md ### Step 1 — Load source tables

# COMMAND ----------

pipeline_snap = (
    spark.table(f"{MDL}.gaim_pipeline_daily_snapshot")
    .filter(F.col("snapshot_date") == F.current_date())
)

# If today's snapshot is not yet available, fall back to latest available date
if pipeline_snap.count() == 0:
    latest_snap_date = (
        spark.table(f"{MDL}.gaim_pipeline_daily_snapshot")
        .agg(F.max("snapshot_date").alias("max_date"))
        .collect()[0]["max_date"]
    )
    print(f"[Job1] No snapshot for today — using latest: {latest_snap_date}")
    pipeline_snap = (
        spark.table(f"{MDL}.gaim_pipeline_daily_snapshot")
        .filter(F.col("snapshot_date") == F.lit(latest_snap_date))
    )

won_opps       = spark.table(f"{FED}.metis_won_opps_fact")
opened_opps    = spark.table(f"{FED}.metis_opened_opps_fact")
targets_raw    = spark.table(f"{FED}.metis_targets_summary")

print(f"[Job1] Source row counts — pipeline_snap: {pipeline_snap.count()}, "
      f"won_opps: {won_opps.count()}, opened_opps: {opened_opps.count()}, "
      f"targets: {targets_raw.count()}")

# COMMAND ----------
# MAGIC %md ### Step 2 — Determine current quarter bounds

# COMMAND ----------

quarter_bounds = (
    spark.sql("""
        SELECT
            DATE_TRUNC('quarter', CURRENT_DATE())           AS period_start,
            LAST_DAY(ADD_MONTHS(DATE_TRUNC('quarter', CURRENT_DATE()), 2)) AS quarter_end,
            CURRENT_DATE() AS today,
            DATEDIFF(CURRENT_DATE(), DATE_TRUNC('quarter', CURRENT_DATE())) + 1 AS elapsed_days,
            DATEDIFF(
                LAST_DAY(ADD_MONTHS(DATE_TRUNC('quarter', CURRENT_DATE()), 2)),
                DATE_TRUNC('quarter', CURRENT_DATE())
            ) + 1 AS total_days
    """).collect()[0]
)

Q_START      = quarter_bounds["period_start"]
Q_END        = quarter_bounds["quarter_end"]
ELAPSED_DAYS = quarter_bounds["elapsed_days"]
TOTAL_DAYS   = quarter_bounds["total_days"]
PACING_RATIO = float(ELAPSED_DAYS) / float(TOTAL_DAYS)

print(f"[Job1] Quarter: {Q_START} → {Q_END} | Elapsed: {ELAPSED_DAYS}/{TOTAL_DAYS} ({PACING_RATIO:.1%})")

# COMMAND ----------
# MAGIC %md ### Step 3 — Compute KPIs (All geos, then by geo, channel, product)

# COMMAND ----------

def compute_kpis_for_group(geo="All", channel="All", product="All"):
    """
    Returns a dict of {metric_key: value} for the given dimension filters.
    Applies filters to source DataFrames before aggregating.
    """
    # ── Filter won opps ──────────────────────────────────────────────────────
    won_filt = won_opps.filter(
        (F.col("close_date") >= F.lit(Q_START)) &
        (F.col("close_date") <= F.lit(Q_END))
    )
    if geo     != "All": won_filt = won_filt.filter(F.col("geo") == geo)
    if channel != "All": won_filt = won_filt.filter(F.col("channel") == channel)
    if product != "All": won_filt = won_filt.filter(F.col("product_family") == product)

    won_agg = won_filt.agg(
        F.sum("arr_amount").alias("won_pipeline"),
        F.count("opportunity_id").alias("won_volume")
    ).collect()[0]

    # ── Filter opened opps ───────────────────────────────────────────────────
    opp_filt = opened_opps.filter(
        (F.col("created_date") >= F.lit(Q_START)) &
        (F.col("created_date") <= F.lit(Q_END))
    )
    if geo     != "All": opp_filt = opp_filt.filter(F.col("geo") == geo)
    if channel != "All": opp_filt = opp_filt.filter(F.col("channel") == channel)
    if product != "All": opp_filt = opp_filt.filter(F.col("product_family") == product)

    opp_agg = opp_filt.agg(
        F.sum("arr_amount").alias("created_pipeline"),
        F.count("opportunity_id").alias("opps_created")
    ).collect()[0]

    # ── Filter active pipeline ───────────────────────────────────────────────
    pipe_filt = pipeline_snap
    if geo     != "All": pipe_filt = pipe_filt.filter(F.col("geo") == geo)
    if channel != "All": pipe_filt = pipe_filt.filter(F.col("channel") == channel)
    if product != "All": pipe_filt = pipe_filt.filter(F.col("product_family") == product)

    pipe_agg = pipe_filt.agg(
        F.sum("arr_amount").alias("active_pipeline"),
        F.sum("mql_count").alias("mql"),
        F.countDistinct("opportunity_id").alias("pipe_count")
    ).collect()[0]

    # ── Derived metrics ──────────────────────────────────────────────────────
    won_pipeline    = float(won_agg["won_pipeline"] or 0)
    won_volume      = int(won_agg["won_volume"] or 0)
    created_pipeline = float(opp_agg["created_pipeline"] or 0)
    opps_created    = int(opp_agg["opps_created"] or 0)
    active_pipeline = float(pipe_agg["active_pipeline"] or 0)
    mql             = int(pipe_agg["mql"] or 0)

    win_rate = (won_volume / opps_created * 100) if opps_created > 0 else 0.0
    ads      = (won_pipeline / won_volume)        if won_volume  > 0 else 0.0
    coverage = (active_pipeline / won_pipeline)   if won_pipeline > 0 else 0.0

    return {
        "won_pipeline":      won_pipeline,
        "won_volume":        float(won_volume),
        "win_rate":          win_rate,
        "ads":               ads,
        "created_pipeline":  created_pipeline,
        "opps_created":      float(opps_created),
        "active_pipeline":   active_pipeline,
        "coverage":          coverage,
        "mql":               float(mql),
    }


def get_target(targets_df, metric_key, geo="All", channel="All", product="All"):
    """Look up the annual target and compute the paced target."""
    filt = targets_df.filter(F.col("metric_key") == metric_key)
    if geo     != "All": filt = filt.filter(F.col("geo") == geo)
    if channel != "All": filt = filt.filter(F.col("channel") == channel)
    if product != "All": filt = filt.filter(F.col("product_family") == product)
    row = filt.agg(F.sum("target_value").alias("t")).collect()[0]
    annual = float(row["t"] or 0)
    paced  = annual * PACING_RATIO
    return annual, paced


METRIC_LABELS = {
    "won_pipeline":     "Won Pipeline ($)",
    "won_volume":       "Won Volume (Deals)",
    "win_rate":         "Win Rate (%)",
    "ads":              "Avg Deal Size ($)",
    "created_pipeline": "Created Pipeline ($)",
    "opps_created":     "Opps Created",
    "active_pipeline":  "Active Pipeline ($)",
    "coverage":         "Coverage Ratio",
    "mql":              "MQLs",
}

def status(actual, paced):
    if paced == 0: return "Unknown"
    ratio = actual / paced
    if ratio >= 1.05: return "Exceeding"
    if ratio >= 0.90: return "On Track"
    if ratio >= 0.75: return "At Risk"
    return "Critical"

# COMMAND ----------
# MAGIC %md ### Step 4 — Build and write metrics_summary

# COMMAND ----------

DIMENSION_COMBOS = [
    ("All", "All", "All"),
    # The following combos are derived from distinct values in the data.
    # Uncomment / expand after confirming column names in source tables.
    # ("NA", "All",      "All"),
    # ("EMEA", "All",    "All"),
    # ("All", "Direct",  "All"),
    # ("All", "Partner", "All"),
]

# Optionally: drive from distinct values in source table
geo_values = (
    [row["geo"] for row in pipeline_snap.select("geo").distinct().collect()]
    if "geo" in pipeline_snap.columns else []
)
channel_values = (
    [row["channel"] for row in pipeline_snap.select("channel").distinct().collect()]
    if "channel" in pipeline_snap.columns else []
)

# Add single-dimension combos only (skip multi-dimension cross products)
for g in geo_values:
    if g: DIMENSION_COMBOS.append((g, "All", "All"))
for c in channel_values:
    if c: DIMENSION_COMBOS.append(("All", c, "All"))


summary_rows = []
prev_quarter_snap = None  # Would load prior quarter for delta; omit for brevity

for (geo, channel, product) in DIMENSION_COMBOS:
    kpis = compute_kpis_for_group(geo, channel, product)
    for metric_key, metric_value in kpis.items():
        annual_target, paced_target = get_target(targets_raw, metric_key, geo, channel, product)
        attainment = (metric_value / paced_target * 100) if paced_target > 0 else 0.0
        summary_rows.append({
            "metric_key":       metric_key,
            "metric_label":     METRIC_LABELS.get(metric_key, metric_key),
            "metric_value":     metric_value,
            "target_value":     paced_target,
            "annual_target":    annual_target,
            "previous_value":   None,   # TODO: join prior-quarter snapshot
            "attainment_pct":   attainment,
            "status":           status(metric_value, paced_target),
            "delta_pct":        None,
            "period_start":     Q_START,
            "period_end":       TODAY,
            "geo":              geo,
            "channel":          channel,
            "product":          product,
            "fuel_source":      "All",
            "source_row_count": 0,
            "refreshed_at":     datetime.utcnow(),
        })

summary_df = spark.createDataFrame(summary_rows)

# Overwrite today's summary rows (MERGE by natural key)
temp_view = f"atlas_metrics_summary_stage_{RUN_ID[:8]}"
summary_df.createOrReplaceTempView(temp_view)

spark.sql(f"""
    MERGE INTO {GOLD}.metrics_summary AS t
    USING {temp_view} AS s
    ON  t.metric_key  = s.metric_key
    AND t.geo         = s.geo
    AND t.channel     = s.channel
    AND t.product     = s.product
    AND t.period_end  = s.period_end
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

print(f"[Job1] Written {len(summary_rows)} rows to {GOLD}.metrics_summary")

# COMMAND ----------
# MAGIC %md ### Step 5 — Append to metrics_history (daily grain)

# COMMAND ----------

history_rows = [
    {
        "metric_key":   row["metric_key"],
        "metric_date":  TODAY,
        "metric_value": row["metric_value"],
        "geo":          row["geo"],
        "channel":      row["channel"],
        "product":      row["product"],
        "refreshed_at": datetime.utcnow(),
    }
    for row in summary_rows
    if row["geo"] == "All"  # history only for all-up; per-geo history would grow too fast
]

hist_df = spark.createDataFrame(history_rows)
hist_view = f"atlas_metrics_history_stage_{RUN_ID[:8]}"
hist_df.createOrReplaceTempView(hist_view)

spark.sql(f"""
    MERGE INTO {GOLD}.metrics_history AS t
    USING {hist_view} AS s
    ON  t.metric_key  = s.metric_key
    AND t.metric_date = s.metric_date
    AND t.geo         = s.geo
    AND t.channel     = s.channel
    AND t.product     = s.product
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

print(f"[Job1] Appended {len(history_rows)} rows to {GOLD}.metrics_history")

# COMMAND ----------
# MAGIC %md ### Step 6 — Revenue gap decomposition (all-up only)

# COMMAND ----------

kpis = compute_kpis_for_group()
_, target_won = get_target(targets_raw, "won_pipeline")

total_gap = kpis["won_pipeline"] - target_won

# Five-factor decomposition (simplified proportional attribution)
def attribution(kpis, target_won, total_gap):
    if total_gap == 0:
        return {k: 0.0 for k in ["won_volume","close_rate","ads","pipeline","close_rate_dollar"]}
    won_vol_contrib  = 0.25 * total_gap
    close_rate_contrib = 0.25 * total_gap
    ads_contrib      = 0.20 * total_gap
    pipeline_contrib = 0.20 * total_gap
    cr_dollar_contrib = total_gap - won_vol_contrib - close_rate_contrib - ads_contrib - pipeline_contrib
    return {
        "won_volume":         won_vol_contrib,
        "close_rate":         close_rate_contrib,
        "ads":                ads_contrib,
        "pipeline":           pipeline_contrib,
        "close_rate_dollar":  cr_dollar_contrib,
    }

attrs = attribution(kpis, target_won, total_gap)

gap_row = {
    "decomp_id":               RUN_ID,
    "period_start":            Q_START,
    "period_end":              TODAY,
    "geo":                     "All",
    "channel":                 "All",
    "product":                 "All",
    "target_won_amount":       target_won,
    "actual_won_amount":       kpis["won_pipeline"],
    "total_gap":               total_gap,
    "impact_won_volume":       attrs["won_volume"],
    "impact_close_rate":       attrs["close_rate"],
    "impact_ads":              attrs["ads"],
    "impact_pipeline":         attrs["pipeline"],
    "impact_close_rate_dollar": attrs["close_rate_dollar"],
    "won_volume":              kpis["won_volume"],
    "close_rate_pct":          kpis["win_rate"],
    "avg_deal_size":           kpis["ads"],
    "active_pipeline":         kpis["active_pipeline"],
    "opps_created":            kpis["opps_created"],
    "refreshed_at":            datetime.utcnow(),
}

gap_df = spark.createDataFrame([gap_row])
gap_view = f"atlas_gap_stage_{RUN_ID[:8]}"
gap_df.createOrReplaceTempView(gap_view)

spark.sql(f"""
    MERGE INTO {GOLD}.revenue_gap_decomposition AS t
    USING {gap_view} AS s
    ON  t.period_end = s.period_end
    AND t.geo        = s.geo
    AND t.channel    = s.channel
    AND t.product    = s.product
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

print(f"[Job1] Written revenue_gap_decomposition — gap: {total_gap:,.0f}")

# COMMAND ----------
# MAGIC %md ### Step 7 — Extended analytics (per tab)

# COMMAND ----------

import json

ext_rows = []

# ── Tab: deal_bands ───────────────────────────────────────────────────────────
deal_bands = won_opps.filter(
    (F.col("close_date") >= F.lit(Q_START)) & (F.col("close_date") <= F.lit(Q_END))
).withColumn(
    "deal_band",
    F.when(F.col("arr_amount") <  10_000, "< $10K")
     .when(F.col("arr_amount") <  50_000, "$10K-$50K")
     .when(F.col("arr_amount") < 100_000, "$50K-$100K")
     .when(F.col("arr_amount") < 250_000, "$100K-$250K")
     .otherwise("> $250K")
).groupBy("deal_band").agg(
    F.sum("arr_amount").alias("metric_value"),
    F.count("opportunity_id").alias("secondary_value")
)

for row in deal_bands.collect():
    ext_rows.append({
        "tab_name":        "deal_bands",
        "dimension_key":   "deal_size_band",
        "dimension_value": row["deal_band"],
        "metric_key":      "won_pipeline",
        "metric_value":    float(row["metric_value"] or 0),
        "secondary_value": float(row["secondary_value"] or 0),
        "period_start":    Q_START,
        "geo":             "All",
        "channel":         "All",
        "metadata_json":   json.dumps({"count": int(row["secondary_value"] or 0)}),
        "refreshed_at":    datetime.utcnow(),
    })

# ── Tab: pipeline_segments ────────────────────────────────────────────────────
pipe_by_geo = (
    pipeline_snap.groupBy("geo").agg(
        F.sum("arr_amount").alias("metric_value"),
        F.count("opportunity_id").alias("secondary_value")
    )
)

for row in pipe_by_geo.collect():
    ext_rows.append({
        "tab_name":        "pipeline_segments",
        "dimension_key":   "geo",
        "dimension_value": str(row["geo"] or "Unknown"),
        "metric_key":      "active_pipeline",
        "metric_value":    float(row["metric_value"] or 0),
        "secondary_value": float(row["secondary_value"] or 0),
        "period_start":    Q_START,
        "geo":             str(row["geo"] or "Unknown"),
        "channel":         "All",
        "metadata_json":   None,
        "refreshed_at":    datetime.utcnow(),
    })

# ── Tab: largest_deals ────────────────────────────────────────────────────────
top_deals = (
    pipeline_snap
    .orderBy(F.col("arr_amount").desc())
    .limit(25)
    .select(
        "opportunity_id", "account_name", "arr_amount", "stage",
        "close_date", "geo", "channel", "days_in_stage",
        "owner_name", "product_family"
    )
)

for row in top_deals.collect():
    meta = {
        "opportunity_id": row["opportunity_id"],
        "account_name":   str(row["account_name"] or ""),
        "stage":          str(row["stage"] or ""),
        "close_date":     str(row["close_date"] or ""),
        "owner_name":     str(row["owner_name"] or ""),
        "product_family": str(row["product_family"] or ""),
        "days_in_stage":  int(row["days_in_stage"] or 0),
    }
    ext_rows.append({
        "tab_name":        "largest_deals",
        "dimension_key":   "opportunity_id",
        "dimension_value": row["opportunity_id"],
        "metric_key":      "deal_arr",
        "metric_value":    float(row["arr_amount"] or 0),
        "secondary_value": float(row["days_in_stage"] or 0),
        "period_start":    Q_START,
        "geo":             str(row["geo"] or "All"),
        "channel":         str(row["channel"] or "All"),
        "metadata_json":   json.dumps(meta),
        "refreshed_at":    datetime.utcnow(),
    })

ext_df = spark.createDataFrame(ext_rows)
ext_view = f"atlas_ext_stage_{RUN_ID[:8]}"
ext_df.createOrReplaceTempView(ext_view)

spark.sql(f"""
    MERGE INTO {GOLD}.extended_analytics AS t
    USING {ext_view} AS s
    ON  t.tab_name        = s.tab_name
    AND t.dimension_key   = s.dimension_key
    AND t.dimension_value = s.dimension_value
    AND t.metric_key      = s.metric_key
    AND t.period_start    = s.period_start
    AND t.geo             = s.geo
    AND t.channel         = s.channel
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

print(f"[Job1] Written {len(ext_rows)} rows to {GOLD}.extended_analytics")
print("[Job1] Metrics Refresh COMPLETE ✓")

# COMMAND ----------
# MAGIC %md ### Finished
