# ARR Forecasting - weekly job setup

Job name: `arr_forecasting_all_models` (Mondays)

| Task key | Notebook | Depends on |
|---|---|---|
| `ucc_forecast_foundation` | 01_ucc_forecast_foundation | - |
| `itsg_growth_arr_forecasting` | 02_itsg_growth_arr_forecasting | - (runs in parallel with UCC) |
| `forecast_unify_publish` | 03_forecast_unify_publish | both tasks above |
| `powerbi_wide_forecast_export` | 04_powerbi_wide_forecast_export | `forecast_unify_publish` |
| `pipeline_nowcast` (OPTIONAL) | 05_pipeline_nowcast | `forecast_unify_publish` |

Task 05 is an in-quarter nowcast from point-in-time stage-weighted pipeline. It is NOT part of the weekly job until its
backtest gate passes (nowcast MAPE < best baseline at as-of weeks >= 5 for both UCC and ITSG; printed by the notebook and
stored as `validated`). Before first use, confirm the OpportunityHistory table/columns (`HISTORY_TABLE`, `COLUMN_MAP`).
It writes only `pipeline_nowcast` and `pipeline_nowcast_backtest`.

`Hindcast_All_Models` is removed (nothing downstream needs it).

## Settings to review in the Jobs UI
- Run as: an identity with MODIFY on `datagroup_mdl.mdl_sales_analytics` and write access to `federated.sales`.
  The GRANT statements at the end of notebooks 03/04 need MANAGE on catalog `federated`; without it they log a
  warning and continue (the table writes themselves do not need it).
- Retries: 0 for tasks 01/02 (long, expensive); 1 for 03/04.
- Timeout: set one per task (UCC is the longest) so a hung run cannot block the Monday publish.
- Notifications: failure alert to the owning team. Notebook 03 now FAILS the task if the federated snapshot write fails.
- Cluster: notebooks 01/02 `%pip install` pinned packages then restart Python - use a cluster that allows it.
- No widgets or parameters are used.

## After deploying the app code (org/main)
- Check `/api/forecast/v2/health` returns `ok` and `latest_run_date` is the Monday run.

## Yearly maintenance (before the first January run)
- Hard-coded `2026-01-05` holdout/cutoff dates: notebook 03 (`CUTOFF`), notebook 04 (`holdout_start`),
  and `BACKTEST_START` in notebook 01 config.

## Changes vs the original notebooks
- 01: LGB Phase 5 tuning now runs (BACKTEST_RESULTS_TABLE defined early); variant-B KeyError guarded;
  MLflow experiment moved to `/Shared/atlas_forecasting/ucc_forecast_v5`.
- 03: UCC forward weeks come from the BOQ plan (current fiscal year only) for forecast_results and the snapshot;
  total-LGB blend and model-scenario fixes; federated write and grants reported separately.
- 04: UCC forward weeks from the BOQ plan (current fiscal year only).
