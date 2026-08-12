# Prophet Handoff — Question Checklist for Atlas Forecast v2

*Meeting prep: questions for the owner of the production Prophet model (Power BI ARR Forecast). Goal: extract everything needed to build the Atlas 5-model engine (Prophet, LightGBM, SARIMAX, Theta/ETS, Chronos) with honest, low MAPE. Items marked ⭐ are the must-asks if time runs short.*

---

## 1. Data sources & lineage

1. ⭐ **What is the exact training input?** `metis_won_opps_fact`, raw `gaim_pipeline_daily_snapshot`, or `prophet_training_data`? (I found `prophet_training_data` is a static file upload from Aug 2025 — is the real pipeline elsewhere, and what notebook/job produces it?)
2. ⭐ **What's excluded from "won bookings"?** Renewal-type deals? $0 / negative amounts / credits? Which `category` / `revenue_type` / `contract_type` values count as New vs Expansion vs Renewal? (Atlas scope = new + expansion only.)
3. **Dedup/snapshot rule:** do you take `data_date = MAX(data_date)` only? How do you handle restatements — deals whose `close_date` or amount changes after the week was already "actualized"? Does history get rewritten?
4. **Amount definition:** `amount_towards_plan` — is that FX-adjusted? Budget rate vs latest rate? Same definition Finance uses for quarter attainment?
5. **Why does training start where it does (2022)?** Any known regime breaks — channel redefinitions (`smoothed_channel` vs `2024_channel` suggests remapping), product hierarchy changes, M&A, COVID-era data you deliberately cut?
6. **Salesforce current-month anchor:** how exactly does the in-progress month get anchored to SFDC Closed Won — overwrite, blend, or floor?

## 2. Series construction & cleaning

7. ⭐ **Weekly bucketing:** ISO Monday-start? How is the current partial week handled (dropped, scaled, included)? Any timezone gotchas on `close_date`?
8. **Outliers:** are mega-deals capped/winsorized/removed, or kept? Is there a manual cleaning step anywhere (this is the "cleaned data" I want to see)?
9. **Zero weeks / gaps:** are holiday-dead weeks kept as zeros or imputed?
10. **Calendar:** strictly calendar quarters (Jan/Apr/Jul/Oct) for quarter-end behavior — no fiscal offset, correct?

## 3. Prophet configuration (the production model)

11. ⭐ **Exact hyperparameters:** `interval_width`, `changepoint_prior_scale`, `seasonality_mode` (additive/multiplicative), enabled seasonalities + fourier orders, holiday calendar? (Repo copy says 0.80 interval, daily+weekly+yearly on weekly data — is that really what runs in prod?)
12. ⭐ **Regressors:** confirmed summer/winter/isweek1? And **marketing spend** — what's the source table, refresh cadence, and critically: how do you supply *future* values of spend for the forecast horizon (plan numbers? last-known? naive hold)?
13. **Segmentation:** one model per Geo × Product? Minimum-history rule per segment? Is "Total" its own model or the sum of segments — and if both exist, do they reconcile?
14. **Retraining:** full refit weekly? Any pinned/frozen parameters vs auto-fit each run?

## 4. Scenario bands & blending

15. ⭐ **Best/Worst case:** straight from Prophet's `yhat_upper/lower`, or from `monte_carlo_model` (ADS distributions)? If Monte Carlo: how is it parameterized and combined with Prophet?
16. **Human blend:** how exactly are `weekly_forecast` (VP forecasts) blended with the statistical output — fixed weights, override, or judgment-on-top? Where does that math live?
17. **Has band coverage ever been checked** — do ~80% of actual weeks land inside the 80% band?

## 5. Accuracy measurement (so old vs new MAPE is comparable)

18. ⭐ **How is the current MAPE computed?** In-sample, single holdout, or rolling origin? At weekly, monthly, or quarterly granularity? Per segment or Total? (Atlas v2 uses rolling-origin 3×13w out-of-sample — I need to know if the numbers will be apples-to-apples.)
19. ⭐ **Known failure modes:** where does Prophet miss most — quarter-end spike weeks, specific segments, post-holiday weeks? Which segments are flagged weak today?
20. **Bias:** is the model systematically over/under forecasting (signed error), not just MAPE?
21. **Is there any accuracy history stored** (run-over-run), or only the latest?

## 6. Storage, jobs & ops

22. ⭐ **Canonical output tables:** `forecast_prophet`, `forecast_prophet_2024`, `arr_forecast_prophet` — which is live, which is dead, what's the schema and grain? Which one does Power BI actually read?
23. **Where does the job run?** Workspace notebook, Repo, or DAB job? Cluster type, schedule, runtime, cost? Link to the notebook.
24. **Failure handling:** what happens when a run fails — alerting, stale-data flagging in the dashboard, manual rerun?
25. **Permissions:** any UC grants, masked columns, or service-principal quirks I'll hit reading the same sources from the Atlas app's principal?

## 7. Handoff & collaboration for Atlas v2

26. ⭐ **Can Atlas reuse your cleaned weekly series as the canonical training table** (one shared source of truth), instead of me re-deriving it from `metis_won_opps_fact`? If yes — can we publish it as a maintained Delta table with a contract?
27. **Marketing spend & other exogenous feeds:** can I get the maintained source for SARIMAX/LightGBM covariates (spend, MQLs, created pipeline)?
28. **Backtest protocol agreement:** can we adopt one shared rolling-origin protocol so Prophet-prod and Atlas models race on identical folds? (Otherwise leaderboard comparisons are meaningless.)
29. **What would you do differently** if rebuilding today — known dead ends, things tried and abandoned (ARIMA? other regressors?), data quirks that burned you?
30. **Sign-off path:** anything needed (Finance/RevOps blessing) before Atlas numbers appear next to the Power BI forecast for the same executives?

---

## Why these map to the 5 Atlas models

- **Q1–10** (clean series) → every model; garbage-in dominates model choice.
- **Q11–14** (Prophet config) → reproduce prod Prophet faithfully as the baseline contender.
- **Q12, 27** (exog feeds) → SARIMAX + LightGBM covariates.
- **Q18–21** (eval protocol) → the leaderboard that auto-selects per-segment winners.
- **Q8, 19** (outliers, spike misses) → where LightGBM-quantile and Chronos earn their keep.
- **Q26** (shared cleaned table) → fastest path to parity + the single biggest de-risking item.
