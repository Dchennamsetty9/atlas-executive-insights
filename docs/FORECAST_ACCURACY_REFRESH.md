# Forecast accuracy publication and refresh

## Scope

Quarterly model pills and the Accuracy summary read `forecast_leaderboard_v2compat`.
The API also reads `forecast_quarterly_accuracy` for per-model evaluation evidence.
Forecast vs Reality reads each product's retained `*_forecast_vintages` and current
`*_forecast_cbe` actuals. It never substitutes UCC for ITSG/All, fabricates bands, or
shows demo backtests when history is missing. Native Prophet is not silently mapped
to the different retained Prophet trend model.

## Daily updates

The repository's `forecast_v5_daily` job is configured for 07:00 America/New_York.
Its publisher depends on the UCC and ITSG tasks. No schedule or notebook changes
are included in this update, and Git push alone does not deploy workspace notebooks
or app code.

Once this app revision is deployed and the jobs successfully publish their outputs:

- Opening Forecast immediately reads the latest published quarterly values.
- A visible Forecast panel rechecks every five minutes and on browser focus/return.
- Manual Refresh rechecks both the pills/summary and the mounted backtest.
- Hidden pages skip interval checks; returning triggers a new check.
- Leaderboard data/schema reads bypass the general 24-hour forecast cache.
- Backtests read retained sources directly, without shared-cache or unsafe fallback.
- Accuracy displays the last successful check time; read failures are explicit.

This is polling of published tables, not a job-completion webhook. Expect new
values within five minutes plus query latency on a visible page after publication.
No rebuild or redeployment is needed for subsequent daily data refreshes. A refresh
does not run training, write tables, or force values to change: closed-quarter error
can remain unchanged until a new evaluated quarter is published. Backtests grow only
when closed actuals and a matching earlier publication exist at the selected horizon.

## Metric interpretation

- Quarterly values are publisher outputs, which may include estimates or weighted
  blends; they are not automatically verified closed-quarter errors.
- Quarterly evidence is matched by product, model, publication date, and numeric
  value. A unique `holdout_closed_quarter` record with a closed quarter label and
  positive evaluation count is classified as measured. This describes the source
  evaluation, not independently certified model accuracy.
- Estimates and weighted blends are labeled explicitly. Missing, conflicting,
  stale, or inaccessible metadata leaves the published value visible as unverified,
  without a performance color. The source model and evaluated quarter are shown
  when supplied, separately from the leaderboard publication date.
- Backtest horizons are explicit lead-time bins: 1 = 1–7 days, 4 = 22–28 days,
  8 = 50–56 days, 13 = 85–91 days before the target week.
- Actuals are the latest published closed-week values and may include revisions.
- One unambiguous retained publication per target week is selected within the bin.
- Missing/invalid bounds do not erase point forecasts and are excluded from coverage.
- Zero actuals remain visible but are excluded from percentage-error denominators.
- Small samples are flagged. Observed bound coverage is not a calibration guarantee.
- All Products displays UCC and ITSG quarterly errors side by side, including on
  the model pills. No combined percentage is synthesized from product errors.
- Forecast vs Reality displays separate product panels with a shared horizon under
  All Products. One product's missing history does not hide the other's chart.
- A shorter-history action appears only after a successful, scope-matched 1-week
  history check; clicking explicitly changes the shared horizon for both panels.
- Unsupported regions/models, insufficient history, invalid pairs and read failures
  have distinct guidance. A daily run is not promised to resolve these conditions.
- Leaderboard source publication (run date) is shown separately from the browser's
  last check. Missing source dates remain explicitly unavailable. Backtest source
  dates are the latest publications among scored pairs, not the newest table run.
- Published quarterly error and weekly retained backtest MAPE have different bases.
  The UI explains this distinction without implying either is a substitute.

## Validation limits

Offline tests cover monthly Prophet/quarter selection, rolling forward-year periods,
credential-scoped forecast caching, quarterly evidence matching, backtests, and
refresh behavior. CI runs the dependency-free frontend contract tests before npm
installation. Existing frontend dependency and repository-wide lint findings still
need separate fixes; adding the contract step does not make the whole CI pipeline green.

Before production rollout, confirm that the effective SQL identities can SELECT
`forecast_quarterly_accuracy` and validate its latest metadata against the published
leaderboard. No grants, notebook execution, table writes, or deployment are performed
by these local changes. A missing grant produces unverified quarterly values.

Forecast query-cache keys now include a SHA-256 fingerprint of the effective SQL
credential and warehouse. Credential changes cannot reuse another scope's entries;
requests without a scope are not cached. Entries remain TTL-bound and capped at 512.
This change is limited to forecast query caching, not the separate KPI cache. Leaderboard
and quarterly evidence reads continue to bypass caching.

Release traceability remains a separate gate: scheduled jobs still refer to mutable
workspace notebooks. Record and verify the app and notebook revisions before release;
these fixes do not pin those job inputs or certify a live production forecast.
## Quarterly actual vs forecast (Accuracy tab)

`GET /api/forecast/v2/quarterly-actual-vs-forecast` backs the table at the top of the Accuracy tab.

- Closed quarters: realised actual vs each retained model's forecast **as first published** (earliest
  vintage per week from `{ucc,itsg}_forecast_vintages`, joined to `{ucc,itsg}_forecast_cbe` actuals), over the
  same weeks. Error is signed: positive = over-forecast. UCC or ITSG at total grain only; Total and region
  selections return the forward quarters with an explanatory note instead of mixed history.
- Current quarter: actual to date plus the snapshot forecast for the open weeks (projected landing with the
  P-low/P-high range). Future quarters: forecast only, out to the forward horizon.
- Horizon: `FORECAST_HORIZON_MONTHS` (18; was 12) in the notebooks and `FORECAST_HORIZON_MONTHS` in
  `forecast_v2_impl.py` (env override of the same name). Keep the two in step.
