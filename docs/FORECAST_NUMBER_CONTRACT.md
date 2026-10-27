# Forecast Number Contract

- Actuals are published `forecast_type = 'actuals'` rows. Their latest non-null date is the close marker, including zero bookings. The publisher must confirm that this denotes a finalized week; the app cannot infer business finalization from today's date.
- Current forecasts use weeks strictly after that marker for the selected product and market. Overlapping rolling/ROY weeks prefer rolling. Duplicate rows within the same publication/type are rejected on the canonical snapshot path.
- Weekly KPIs are computed from displayed actual and forecast rows. Quarterly summaries and Monthly forward values use the same normalized weekly SQL.
- A current landing is actuals plus remaining P50, not an approved plan and not a historical issued forecast. Realized share is not plan attainment or an on-track assessment.
- Ensemble snapshot bands are P30/P70. Sums of weekly quantiles are scenario totals, not calibrated monthly/quarterly percentile intervals. Other model selections have no verified matching P30/P70 in this contract and therefore expose null bounds.
- Monthly historical estimates remain separate. The wide export contains native, hindcast and proxy points; its P25/P75 are never promoted into current P30/P70 columns. It is restricted to the snapshot run date. Historical accuracy stays unavailable until issued-before-outcome, same-week coverage is verified.
- Snapshot requests select the latest run and carry publication IDs. Mixed-publication responses are rejected. Native Prophet uses its existing `is_current` source, whose publication equivalence to the snapshot remains unverified.
- Confidence scores and plan variance bridges are unavailable without selection-matched evidence. Risk Radar honors product/region and actual cutoff. Meeting Mode exposes partial data without synthetic recommendations.
- AI narratives are restricted to the current Ensemble quarter, selected product, all-region scope and snapshot run date. No portfolio fallback is allowed for a missing selection.
- Frontend request handling rejects demo/unavailable responses and clears failed values. Missing weeks/months are null, not zero. Active-tab data refreshes on publication polling as well as manual refresh.

## Validation Limits

Local tests validate arithmetic, selection SQL, parsing, loading and error behavior. They do not establish production table coverage or percentile calibration. No configured Databricks credentials were available during this change. Before deployment, run read-only reconciliations for each product/market/model and confirm finalized-week policy, snapshot uniqueness, run alignment across publisher stages, and native Prophet publication lineage. No notebooks or warehouse tables were modified.