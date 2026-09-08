# Forecast accuracy publication and refresh

## Scope

Quarterly model pills and the Accuracy summary read `forecast_leaderboard_v2compat`.
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
- Backtest horizons are explicit lead-time bins: 1 = 1–7 days, 4 = 22–28 days,
  8 = 50–56 days, 13 = 85–91 days before the target week.
- Actuals are the latest published closed-week values and may include revisions.
- One unambiguous retained publication per target week is selected within the bin.
- Missing/invalid bounds do not erase point forecasts and are excluded from coverage.
- Zero actuals remain visible but are excluded from percentage-error denominators.
- Small samples are flagged. Observed bound coverage is not a calibration guarantee.
- All-products, unsupported regions/models, and insufficient history show unavailable.

## Validation limits

Focused backtest, quarterly-value, and refresh tests are included. The restored
baseline has two unrelated failing backend tests (monthly query count and by-product
forward-period assertion) and five unrelated React lint errors. Those broader fixes
are intentionally not part of this change.