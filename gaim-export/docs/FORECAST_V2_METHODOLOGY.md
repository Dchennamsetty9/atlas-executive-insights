# ARR Forecast v2 — Methodology & Deployment

*Companion to `notebooks/arr_forecast_v2.py`. Replaces the Prophet-only weekly job feeding the app's Forecast view.*

## Why v2 should beat the current 31.3% MAPE

The current numbers (LightGBM 34.9%, Prophet 34.7%, fixed 70/30 ensemble 31.3%) leave headroom because of five specific, verifiable issues in v1 — each addressed in v2:

| # | v1 issue | v2 fix | Expected effect |
|---|----------|--------|-----------------|
| 1 | No fiscal-calendar awareness — Won ARR spikes at quarter close, v1 only had `summer/winter/isweek1` regressors | Quarter-end / quarter-close-window / quarter-start / year-end week flags, weeks-to-quarter-end, month-of-quarter, US holiday weeks — fed to both models | Largest single gain; the quarter-close spike is the dominant non-trend signal in weekly Won ARR |
| 2 | `daily_seasonality=True` on weekly data (`forecasting.py:152` and notebook config) — Prophet fits noise components that can't exist in weekly buckets | Daily/weekly seasonality OFF; yearly (fourier 10) + custom quarterly (period 91.3125d) + monthly seasonalities | Less overfitting, smoother extrapolation |
| 3 | Accuracy measured in-sample (`forecasting.py:197-200`) or single holdout — overstates accuracy and misranks models | Rolling-origin backtest: 3 folds × 13 unseen weeks; every reported MAPE is out-of-sample | Honest numbers; correct model ranking; defensible to executives |
| 4 | Ensemble weights fixed at 70/30 | Weights learned each run from inverse out-of-sample MAPE | Adapts as regimes change; never worse than the components on average |
| 5 | Prediction intervals from symmetric residual std | LightGBM quantile models (q10/q50/q90) → real asymmetric 80% bands; Prophet keeps `interval_width=0.80` | Bands that actually cover ~80% — matters for the quarter-end range |

## Two accuracy targets, reported separately (per product decision)

- **Weekly trajectory** — the chart in the Forecast view. Tracked as `granularity='weekly'` rows in `arr_model_leaderboard`.
- **Quarter-end attainment** — "will we hit the quarter": QTD actuals + remaining-quarter forecast from whichever model wins on *monthly-aggregated* backtest MAPE. Lands in `arr_forecast_insights.forecast_most_likely/low/high`; its accuracy is `monthly_best_mape`. Weekly Won ARR is inherently spiky (single mega-deals), so the monthly/quarterly number is the one to commit to — the narrative says so explicitly.

## Architecture (unchanged from precomputed-first direction)

```
Weekly job (arr_forecast_v2.py, Mon 06:00 UTC)
  ├─ load weekly Won ARR (federated.sales.metis_won_opps_fact, latest data_date)
  ├─ rolling-origin backtest → out-of-sample MAPE per model (weekly + monthly)
  ├─ final fit → 26-week forecast: prophet, lightgbm, ensemble
  └─ write Delta:
       arr_forecast_output      (OVERWRITE — latest run only)
       arr_model_leaderboard    (append, idempotent per run_date)
       arr_forecast_insights    (append, idempotent per run_date)

FastAPI (backend/routes/forecast.py) — ZERO changes required
  /api/forecast/arr          ← arr_forecast_output
  /api/forecast/leaderboard  ← arr_model_leaderboard
  /api/forecast/insights     ← arr_forecast_insights (incl. quarter-end numbers)
```

Contract notes (important):
- The route reads `arr_forecast_output` **without a run_date filter** (`forecast.py:184-191`), so the job overwrites that table with the latest run only. Leaderboard/insights keep history.
- The in-repo v1 notebook wrote a *different* schema (`most_likely/worst_case/best_case`) than the route reads (`yhat/yhat_lower/yhat_upper`) — v2 closes that drift; the committed notebook is now the authoritative producer.
- Model keys are lowercase (`prophet`, `lightgbm`, `ensemble`, `actual`); the route's `_normalize_model_label` maps them to display labels.

## Validation performed

`python -m py_compile` passes. Core logic (calendar features, leak-free lag construction, recursive multi-step prediction with ordered bounds, monthly aggregation, inverse-MAPE weights, quarter boundary math, output row contract) was dry-run on 156 weeks of synthetic quarter-end-spiked data with stand-in models — all 7 checks passed. Prophet/LightGBM/Spark paths run only on Databricks; first production run should be eyeballed (Section 4 prints all backtest MAPEs before any table write, and the job **asserts** backtests succeeded before writing).

## Deployment

1. Import `notebooks/arr_forecast_v2.py` into the workspace (Repos or workspace import — it is Databricks notebook source format).
2. Run interactively once on the ML runtime cluster; review Section 4 printout (out-of-sample MAPEs + chosen ensemble weights) and Section 6 (quarter-end projection) before letting Section 8 write.
3. Point the weekly job at this notebook (replace the v1 notebook task in `databricks.yml` / job config; same Monday 06:00 UTC slot).
4. Open the app's Forecast view — it picks up the new run with no backend or frontend changes. The leaderboard will now show both `weekly` and `monthly` rows with `type='backtest_3x13w'`.
5. After 2–3 runs, compare `arr_model_leaderboard` history: v2's out-of-sample weekly MAPE vs. the 31.3% baseline. Note the baseline was measured differently (likely single holdout), so judge improvement on the *same* backtest protocol going forward.

## Honest caveats

- v1's "31.3%" and v2's numbers are not directly comparable until both are measured by the same rolling-origin protocol; expect the first v2 leaderboard to be the new baseline.
- 3 folds × 13 weeks is a pragmatic compromise (runtime vs. statistical power). If the cluster budget allows, raise `BACKTEST_FOLDS` to 5.
- Quantile models can cross in sparse regions; the code enforces `lower ≤ point ≤ upper` per step.
- The hardcoded MAPE strings in `routes/forecast.py:28-41` (`SUPPORTED_MODELS` descriptions) are static UI text — update or, better, have the frontend read live numbers from `/api/forecast/leaderboard`.

## Extensions (not in this version, by design)

- **Pipeline-conversion covariates** — created-pipeline and MQL series lead Won ARR; adding lagged covariates from `gaim_pipeline_daily_snapshot` is the next biggest accuracy lever (was offered as the "hybrid" option; revisit after v2 baselines are in).
- **Per-segment forecasts (Geo × Product)** — requires adding a segment column to `arr_forecast_output` and a route/UI change; the v2 functions take any `[ds, y]` frame, so the loop is trivial once the contract allows it.
- **Conformal calibration of intervals** — track empirical coverage of the 80% band in the leaderboard and widen/narrow via backtest residual quantiles.
