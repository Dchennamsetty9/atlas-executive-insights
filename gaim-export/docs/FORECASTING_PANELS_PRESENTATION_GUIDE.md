# Forecasting Panels Presentation Guide

This guide is a plain-English walkthrough of the Forecast area in Atlas Executive Insights. It is written so you can present the page end-to-end: what each tab shows, what every chart means, where the data comes from, and how the backend feeds the UI.

## 1. What the Forecast area is for

The Forecast experience is the executive planning surface for ARR. It is designed to answer five questions:

1. What is the most likely quarter close?
2. How wide is the risk range around that number?
3. Which product lines and markets are driving the gap?
4. How accurate are the models and how calibrated are the bands?
5. What actions and decisions should leaders carry into the meeting?

The frontend renders the Forecast panel from the `frontend/src/components/forecast/` tree. The backend serves the data through the `/api/forecast/v2/*` endpoints.

## 2. How the data flows

The forecast panel is driven by these routes and tables:

- `/api/forecast/v2/weekly` → `arr_forecast_v2`
- `/api/forecast/v2/ytd` → `arr_forecast_v2`
- `/api/forecast/v2/by-product` → `arr_forecast_v2`
- `/api/forecast/v2/monthly` → `arr_forecast_v2`
- `/api/forecast/v2/historical` → `arr_forecast_v2`
- `/api/forecast/v2/leaderboard` → `arr_forecast_v2_leaderboard`
- `/api/forecast/v2/backtest` → `ucc_forecast_accuracy_history` fallback when retained-run rows are missing
- `/api/forecast/v2/confidence-bands` → `arr_forecast_v2`
- `/api/forecast/v2/confidence` → `arr_forecast_v2`
- `/api/forecast/v2/driver-bridge` → forecast bridge data from the forecast v2 implementation
- `/api/forecast/v2/risk-radar` → forecast v2 slice data
- `/api/forecast/v2/meeting-mode` → forecast v2 slice data
- `/api/forecast/v2/intelligence` → `arr_forecast_insights` and/or the AI insights JSON asset
- `/api/forecast/v2/governance/log` → forecast governance log storage
- `/api/forecast/v2/freshness` → forecast run freshness metadata
- `/api/forecast/v2/models` → forecast model registry metadata
- `/api/forecast/v2/run-delta` → latest run comparison metadata
- `/api/forecast/v2/model-lab` → `arr_forecast_app_latest`, `ucc_forecast_v5`, `itsg_forecast_v5`

At the UI level, `frontend/src/services/api.js` is the client that calls these routes. The panel loads data tab-by-tab and falls back to demo data when live Databricks access is not available.

## 3. Global controls at the top of Forecast

These controls affect most tabs:

- Product selector: All, UCC, ITSG
- Region selector: All Regions, NA, EMEA, APAC, LATAM
- Time period selector: 13-Week Quarter or Rest of Year
- Year selector
- Quarter selector
- Forecast model selector: Ensemble, Prophet, ETS, MSTL, DHR-ARIMA, LightGBM

What they mean:

- Product decides whether the panel is showing total forecast or one product line.
- Region limits the data to a geography slice.
- Time period changes whether the app is framing the forecast as the current quarter or the remainder of the year.
- Year and quarter narrow the slice for historical and current views.
- Model changes the forecast center line and, where available, the uncertainty band.

## 4. Tab-by-tab explanation

### Overview

File: `frontend/src/components/forecast/tabs/OverviewTab.jsx`

Charts and panels:

- Quarter hero cards
- Run-delta banner
- Weekly Forecast vs Actuals chart
- Running Totals YTD chart

How to explain it:

- The quarter hero cards show the headline planning number: Most Likely, Stretch Case, Risk Floor, and Actuals YTD.
- The run-delta banner shows how the latest forecast run changed versus the prior run, including the biggest movers by product and market.
- The weekly chart compares actual weekly ARR to the forecast center line and scenario bands.
- The YTD chart shows the cumulative realized path against the projected path.

What the graph tells you:

- If the actual line is above the most-likely line, the business is outperforming plan.
- If the orange actual line starts below the forecast, the quarter is slipping.
- The blue band is the 80% confidence interval. Narrower bands mean more certainty.
- The cyan inner band is the 50% central band, which shows where the model thinks the outcome is most concentrated.
- The vertical split marks where actual history ends and forecast begins.

Source fields used in the weekly chart:

- `date`
- `arr_actual`
- `arr_likely`
- `arr_worst`
- `arr_best`

Source fields used in the YTD chart:

- `date`
- `ytd_actual`
- `ytd_likely`
- `ytd_worst`
- `ytd_best`

### Multi-Year

File: `frontend/src/components/forecast/tabs/MultiYearTab.jsx`

Charts:

- Historical Seasonality — by ISO Week
- Historical Weekly Trend — Timeline

How to explain it:

- The overlay view compares multiple years week-by-week to show repeatable seasonal patterns.
- The timeline view shows the same weekly ARR as one continuous line so you can talk about trend direction and changes across time.

What the graph tells you:

- If the current year’s line sits above prior years, the business is tracking stronger than history.
- If specific weeks consistently spike or dip every year, those are seasonal quarter-close or holiday effects.
- The timeline view is useful for simple executive storytelling because it shows rise, flattening, or softening over time.

Source fields used:

- `year`
- `iso_week`
- `date`
- `arr`

### By Product

File: `frontend/src/components/forecast/tabs/ByProductTab.jsx`

Charts and tables:

- Product Trajectories small multiples
- Attainment Gap Ranking table
- Forecast by Geography bar chart

How to explain it:

- The small-multiples cards let you compare product lines at a glance.
- The ranking table sorts the product slices by gap versus likely forecast, so the biggest over/under performers appear first.
- The geography chart shows the same forecast split by region.

What the graph tells you:

- The small multiples show whether one product line is pulling ahead or falling behind.
- The gap ranking table shows which line deserves attention first.
- The geography chart shows if a specific market is outperforming or dragging the plan.

Source fields used:

- `product`
- `product_line`
- `sales_market`
- `arr_actual`
- `arr_likely`
- `arr_worst`
- `arr_best`
- `best_mape`

### Monthly

File: `frontend/src/components/forecast/tabs/MonthlyTab.jsx`

Table:

- Monthly Actuals vs Forecast Scenarios

How to explain it:

- This is the month-level execution view.
- It shows actuals, forecast, target, variance percentage, and a small sparkline for each month.
- Quarter totals are rolled up at the bottom of each quarter.

What the table tells you:

- It is the easiest place to explain quarter phasing.
- It shows whether the current quarter is building evenly or skewing toward late-quarter close.
- The in-progress month is called out directly.

Source fields used:

- `year`
- `quarter`
- `month`
- `month_name`
- `arr_actual`
- `arr_likely`
- `arr_worst`
- `arr_best`
- `arr_target`

### Accuracy

File: `frontend/src/components/forecast/tabs/AccuracyTab.jsx`

Charts and tables:

- Model Rank by MAPE bar chart
- Model MAPE Leaderboard table
- Backtest section with forecast-vs-reality chart

How to explain it:

- The MAPE rank chart shows the best model at the current slice.
- The leaderboard table compares models across product and geography slices.
- The backtest section answers the key question: if we had made this forecast weeks ago, how would it have held up when the week actually closed?

What the graph tells you:

- Lower MAPE is better.
- The ensemble row is the realized accuracy for closed weeks.
- The backtest coverage should land near 80% if the bands are calibrated well.
- The horizon switch lets you compare 1, 4, 8, and 13 week-ahead forecasts.

Source fields used in the leaderboard:

- `product`
- `sales_market`
- `Ensemble`
- `ETS`
- `Prophet`
- `LightGBM`
- `MSTL_v2`
- `DHR_ARIMA`
- `best_model`
- `best_mape`

Source fields used in backtest:

- `ds`
- `actual`
- `predicted`
- `worst`
- `best`
- summary values such as `weeks_scored`, `coverage_pct`, `mape_pct`, `bias_pct`

### Model Lab

File: `frontend/src/components/forecast/tabs/ModelLabTab.jsx`

Charts:

- Model-specific P10 / P50 / P90 forecast chart
- Model comparison chart across all models

How to explain it:

- This tab is a model-diagnostics view.
- It lets you choose one model and see its own uncertainty band.
- The second chart overlays all model center lines so you can compare agreement and disagreement.

What the graph tells you:

- If the model lines stay close, the models agree and the forecast is more stable.
- If one model diverges sharply, it is either seeing a different pattern or reacting to outliers.
- The P10 / P50 / P90 fan shows model-specific uncertainty, not just a global band.

Important note:

- When product is set to All, the UI explains that Model Lab is effectively per product line and defaults to UCC unless the user chooses UCC or ITSG.

Source fields used:

- `ds`
- `model`
- `p10`
- `p50`
- `p90`
- `run_date`

Backend tables used:

- `arr_forecast_app_latest`
- `ucc_forecast_v5`
- `itsg_forecast_v5`

### AI Insights

File: `frontend/src/components/forecast/tabs/AiInsightsTab.jsx`

What it shows:

- Momentum tag
- Risk tag
- MAPE tag
- Upside and downside values
- Confidence score
- Narrative summary
- Key drivers
- Downside and upside bullets
- One action recommendation

How to explain it:

- This tab is the executive narrative layer.
- It turns the forecast into a plain-English explanation with risk, momentum, and actions.
- Use it when the team asks, “What does the model think is going on?”

Source fields used:

- `momentum` or `trend_status`
- `risk_level`
- `model_confidence`
- `narrative` or `description`
- `best_mape` or `mape`
- `upside` / `upside_dollar`
- `downside` / `downside_dollar`
- `key_drivers`
- `downside_risks`
- `upside_opportunities`
- `executive_actions`

### Exec Mode

File: `frontend/src/components/forecast/tabs/ExecModeTab.jsx`

Panels:

- Executive Board Narrative
- Prediction Interval Fan
- Forecast Confidence Score
- Meeting Snapshot
- Driver Bridge
- Pipeline Sensitivity Simulator
- At-Risk ARR Radar
- Action Command Center
- Forecast Governance and Audit Trail

How to explain it:

- This is the boardroom view.
- It combines the forecast number, downside risk, key drivers, actions, and governance into one executive control room.

What each piece tells you:

- Executive Board Narrative: the hero number and top action summary.
- Prediction Interval Fan: P10, P50, and P90 with the spread between them.
- Forecast Confidence Score: a simple confidence summary and reasons.
- Meeting Snapshot: short top-moves list for live discussion.
- Driver Bridge: plan versus actual variance broken into drivers.
- Pipeline Sensitivity Simulator: what-if controls for conversion, cycle time, deal size, and coverage.
- At-Risk ARR Radar: the top 20 slices with likely, worst, and risk impact.
- Action Command Center: create and close follow-up actions.
- Governance and Audit Trail: log decisions and keep a record of why overrides were made.

Source fields used:

- `confidenceBands.most_likely`
- `confidenceBands.p10`
- `confidenceBands.p90`
- `weeklyKpis.most_likely`
- `weeklyKpis.worst_case`
- `driverBridge.plan_total`
- `driverBridge.actual_total`
- `driverBridge.variance`
- `driverBridge.components[]`
- `riskRadar[]`
- `actions[]`
- `governanceLog[]`

## 5. Forecast-specific backend tables and what each one is for

These are the tables you should name when someone asks “where is this coming from?”

### `arr_forecast_v2`

Primary forecast table for the UI.

Used by:

- Weekly chart
- YTD chart
- Historical overlay
- By-product view
- Monthly view
- Confidence bands
- Run delta
- Most of the forecast model selector logic

Typical columns:

- `ds`
- `product`
- `sales_market`
- `Actuals`
- `Most_Likely`
- `Worst_Case`
- `Best_Case`
- model-specific columns such as `arr_ets`, `arr_prophet`, `arr_lightgbm`, `arr_mstl_v2`, `arr_dhr_arima`
- MAPE columns such as `mape_ets`, `mape_prophet`, `mape_lightgbm`, `mape_mstl_v2`, `mape_dhr_arima`
- `forecast_type`
- `run_date`

### `arr_forecast_v2_leaderboard`

Model accuracy table.

Used by:

- Accuracy tab leaderboard
- Model ranking
- Accuracy narratives

### `ucc_forecast_accuracy_history`

Historical backtest source used as a fallback when retained run data is not enough.

Used by:

- Accuracy tab backtest section

### `arr_forecast_insights`

Insight and narrative table.

Used by:

- AI Insights tab

### `arr_forecast_app_latest`, `ucc_forecast_v5`, `itsg_forecast_v5`

Model-lab source tables for V5 notebook outputs.

Used by:

- Model Lab tab

### AI insights JSON asset

Path:

- `/Volumes/datagroup_mdl/mdl_sales_analytics/forecast_assets/ai_insights_latest.json`

Used when the backend loads the latest narrative asset directly from the volume.

## 6. What to say about live vs demo mode

The app is designed to stay usable even when Databricks is not connected.

- If Databricks auth is available, the panel should show live data.
- If auth is missing or the warehouse is unavailable, the panel falls back to demo data.
- The UI marks that state directly with LIVE or DEMO badges.

That means two different things can be true at once:

1. The panel is functioning correctly.
2. The data is not live because the backend is in mock mode or the external source is unavailable.

For a presentation, call this out explicitly so nobody confuses fallback data with a product defect.

## 7. Short presentation script

If you want a clean spoken summary, use this:

> The Forecast area is the executive planning surface for ARR. The Overview tab shows the headline forecast, the confidence envelope, and the run-to-run change. Multi-Year shows seasonality and trend. By Product breaks the forecast into product and market slices. Monthly shows quarterly phasing. Accuracy shows which models are performing best and how well the bands are calibrated. Model Lab lets us inspect each model’s center line and uncertainty band. AI Insights translates the numbers into a narrative. Exec Mode is the board view: confidence, drivers, actions, risk radar, and governance.

## 8. Quick demo checklist

Before presenting, confirm:

1. Dark mode is active.
2. Overview tab loads the hero numbers and run-delta banner.
3. Weekly and YTD charts render.
4. By Product and Monthly tabs load at least one populated table or chart.
5. Accuracy shows a leaderboard and backtest.
6. Model Lab works when UCC or ITSG is selected.
7. AI Insights shows narrative text, not just an error.
8. Exec Mode shows actions, confidence, and governance rows.

If something falls back to demo, that is usually a data access issue, not a frontend rendering issue.
