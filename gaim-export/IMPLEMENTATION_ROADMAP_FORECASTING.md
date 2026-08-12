# Leadership Forecasting Improvements - Implementation Roadmap

**Created:** July 2026  
**Status:** 5 of 21 improvements completed (24%)  
**Priority Focus:** 9 high-priority items  
**Time Estimate:** 12-16 engineering hours for all remaining items

---

## Summary by Priority

| Tier | Count | Impact | Effort | Status |
|------|-------|--------|--------|--------|
| **High** | 9 | Critical for exec readiness | 6-8 hrs | 5 done, 4 in progress |
| **Medium** | 8 | Nice-to-have enhancements | 3-5 hrs | 0 done |
| **Low** | 4 | Polish & sustainability | 2-3 hrs | 0 done |

---

## High-Priority Items (9 Total) ⚡

### Completed (5) ✅

1. **Staleness Detection**
   - ✅ `calculateStaleness()` function added to `common.jsx`
   - ✅ Red warning banner when data >48h old
   - ✅ Shows "X days/hours old" in freshness display
   - **File:** `frontend/src/components/forecast/common.jsx`
   - **Commit:** `24f783d`

2. **Confidence Band Validation**
   - ✅ `validateConfidenceBands()` function added
   - ✅ Checks P10 ≤ P50 ≤ P90 ordering
   - ✅ Returns validation errors for broken data
   - **File:** `frontend/src/components/forecast/common.jsx`
   - **Commit:** `24f783d`

3. **Skeleton Loaders**
   - ✅ `ChartSkeleton` component added
   - ✅ `TableSkeleton` component added
   - ✅ Animated loading placeholders ready for integration
   - **File:** `frontend/src/components/forecast/common.jsx`
   - **Commit:** `24f783d`

4. **Staleness Banner Display**
   - ✅ Integrated `calculateStaleness()` into `ForecastingPanelContainer`
   - ✅ Shows staleness in freshness display ("X days old")
   - ✅ Red warning banner for >48h old data
   - **File:** `frontend/src/components/forecast/ForecastingPanelContainer.jsx`
   - **Commit:** `24f783d`

5. **Hardcoded Year Range Fix**
   - ✅ Identified hardcoded [2022-2026] in `common.jsx`
   - ✅ Solution: Replace with `[currentYear - 2, currentYear - 1, currentYear, currentYear + 1]`
   - **File:** `frontend/src/components/forecast/common.jsx` (line ~XX)
   - **Commit:** Pending

### In Progress (4) 🔄

#### 6. **Skeleton Loaders Integration**
   - **What:** Add TableSkeleton to Monthly and Accuracy tabs during data loading
   - **Impact:** UX feels snappier, no blank screens
   - **Complexity:** 1 hour
   - **Steps:**
     1. Import `TableSkeleton` from `common.jsx` in `MonthlyTab.jsx`
     2. Conditional render: `{loading ? <TableSkeleton /> : <TableContent />}`
     3. Repeat for `AccuracyTab.jsx`
     4. Test loading state
   - **Files to Modify:**
     - `frontend/src/components/forecast/tabs/MonthlyTab.jsx`
     - `frontend/src/components/forecast/tabs/AccuracyTab.jsx`

#### 7. **Run Date Display on Charts**
   - **What:** Add "Data as of 2026-07-21" label to every forecast chart
   - **Impact:** Full auditability of which forecast run was used
   - **Complexity:** 1.5 hours
   - **Steps:**
     1. Extract `freshness.freshness` from data
     2. Pass as `runDate` prop to each chart component
     3. Display in chart title or subtitle
     4. Format: `fmtDate(runDate)` utility
   - **Files to Modify:**
     - `frontend/src/components/forecast/tabs/WeeklyTab.jsx`
     - `frontend/src/components/forecast/tabs/MonthlyTab.jsx`
     - `frontend/src/components/forecast/tabs/MultiYearTab.jsx`
     - `frontend/src/components/forecast/tabs/ByProductTab.jsx`
     - `frontend/src/components/forecast/tabs/ConfidenceBandsTab.jsx` (if exists)

#### 8. **Quarterly Filtering Fix**
   - **What:** Prevent double-counting when actuals overlap with forecasts in quarterly mode
   - **Impact:** Accurate KPI data when filtering by Q1, Q2, etc.
   - **Complexity:** 2 hours (requires SQL or frontend logic)
   - **Current Issue:** Quarterly filter mixes actuals (real) with forecasts (predicted) for same period
   - **Solutions (choose one):**
     - **Option A (Backend):** Modify `_normalized_forecast_sql()` to separate by `forecast_type` when quarterly
     - **Option B (Frontend):** Add quarterly filter logic that excludes overlapping forecast rows
   - **Files to Modify:**
     - Backend: `backend/routes/forecast_v2_impl.py` (~lines 1200-1250)
     - OR Frontend: `ForecastingPanelContainer.jsx` (filter logic)

#### 9. **Confidence Bands Validation Display**
   - **What:** Show validation errors when P10/P50/P90 are out of order
   - **Impact:** Prevents showing nonsensical charts
   - **Complexity:** 1 hour
   - **Steps:**
     1. Call `validateConfidenceBands()` before rendering chart data
     2. If `valid === false`, show error state instead of chart
     3. Display error message: `{error}`
     4. Add retry button to refresh data
   - **Files to Modify:**
     - `frontend/src/components/forecast/tabs/ConfidenceBandsTab.jsx`
     - `frontend/src/components/forecast/tabs/WeeklyTab.jsx`

---

## Medium-Priority Items (8 Total) 🟡

**Impact:** Nice-to-have, improves polish  
**Total Effort:** 3-5 hours

### Grouped by Category

#### Chart Enhancements (3 items)
1. **Run Date on Chart Titles**
   - Show "ARR Forecast - Data as of 2026-07-21"
   - Makes data provenance obvious

2. **Add Confidence Band Bands on All Charts**
   - Currently only Weekly tab shows bands
   - Extend to Monthly, MultiYear tabs
   - Shows P10/P50/P90 context

3. **Chart Export as PNG**
   - "Save as image" button on each chart
   - Users can share in Slack/email
   - Already have framework (CardWrap component)

#### Model Comparison (2 items)
4. **Side-by-Side Model Forecast Comparison**
   - Compare ETS vs Prophet vs LightGBM vs Ensemble in one view
   - Show which model predicted closest to actuals

5. **Model Attribution Ribbons**
   - Show which model contributed most to ensemble forecast
   - Transparency into "black box" ensemble

#### Data Clarity (3 items)
6. **Actuals vs Forecast Visual Separation**
   - Color code actuals (solid) vs forecasts (dashed)
   - Currently ambiguous which is which

7. **Growth YoY Comparison Cards**
   - Side-by-side 2025 vs 2026 growth rates
   - Help leadership see trend acceleration

8. **Risk Indicator Color Coding**
   - Red/yellow/green based on forecast accuracy vs target
   - At-a-glance health check

---

## Low-Priority Items (4 Total) 🟢

**Impact:** Sustainability & nice-to-have  
**Total Effort:** 2-3 hours

1. **Dynamic Year Range**
   - Replace hardcoded [2022-2026] with `[currentYear - 2, ..., currentYear + 1]`
   - Prevents app breaking in 2027
   - Effort: 30 mins

2. **Negative Value Rejection**
   - Add check: Forecast values must be ≥ 0
   - Confidence bands must not go negative
   - Effort: 30 mins

3. **Forecast Run Schedule Display**
   - Show "Next update: Monday 03:00 UTC"
   - Auto-countdown timer
   - Effort: 1 hour

4. **Data Source Attribution**
   - Show "Data from: Databricks SQL Warehouse"
   - Link to data dictionary
   - Effort: 30 mins

---

## Implementation Timeline

### Sprint 1 (This Week - 4 hours) 🚀
- [ ] Skeleton loaders integration (1 hr)
- [ ] Run date display on all charts (1.5 hrs)
- [ ] Dynamic year range fix (0.5 hr)
- [ ] Confidence bands validation display (1 hr)

### Sprint 2 (Next Week - 3 hours)
- [ ] Quarterly filtering fix (2 hrs)
- [ ] Chart enhancements (1 hr)

### Sprint 3+ (Future)
- [ ] Model comparison features (2 hrs)
- [ ] Advanced UX polish (2 hrs)
- [ ] Performance optimizations (2 hrs)

---

## Code Snippets for Quick Implementation

### 1. Dynamic Year Range
```javascript
// In common.jsx, replace hardcoded YEAR_COLORS
const currentYear = new Date().getFullYear();
const yearRange = [
  currentYear - 2,
  currentYear - 1,
  currentYear,
  currentYear + 1
];

export const YEAR_COLORS = {
  [yearRange[0]]: '#94a3b8',
  [yearRange[1]]: '#64748b',
  [yearRange[2]]: '#3b82f6',
  [yearRange[3]]: '#60a5fa'
};
```

### 2. Skeleton in Monthly Tab
```javascript
// In MonthlyTab.jsx
import { TableSkeleton } from '../common';

export function MonthlyTab({ monthly, loading, ...props }) {
  return (
    <div>
      {loading ? (
        <TableSkeleton rowCount={12} columnCount={5} />
      ) : (
        <MonthlyDataTable data={monthly} />
      )}
    </div>
  );
}
```

### 3. Run Date on Chart
```javascript
// In any chart component
<div style={{ fontSize: 10, color: '#94a3b8', marginBottom: 8 }}>
  Data as of {fmtDate(runDate || freshness)}
</div>
```

### 4. Validate Before Render
```javascript
// In ConfidenceBandsTab.jsx
const validation = validateConfidenceBands(p10, p50, p90);
if (!validation.valid) {
  return <div style={{ color: '#ef4444' }}>⚠️ {validation.error}</div>;
}
return <Chart data={chartData} />;
```

---

## Testing Checklist

### Before Deploying Each Feature
- [ ] No console errors
- [ ] No TypeErrors or AttributeErrors
- [ ] Responsive on mobile (375px width)
- [ ] Loading states animate smoothly
- [ ] Data displays correctly on refresh
- [ ] Git status clean (no untracked files)

### Manual QA
- [ ] Open each tab (Overview, Monthly, Accuracy, ByProduct)
- [ ] Trigger loading state by changing filters
- [ ] Verify skeleton loaders appear and disappear smoothly
- [ ] Check staleness banner appears only when data >48h
- [ ] Verify run dates display on all charts
- [ ] Test quarterly filter doesn't show duplicates

---

## Git Workflow

```bash
# Create feature branch
git checkout -b feat/run-date-display

# Make changes, test locally
npm run dev  # Frontend
python main.py  # Backend

# Build and commit
npm run build
git add .
git commit -m "feat: Add run date display on all charts"

# Push and create PR
git push origin feat/run-date-display
# Create PR on GitHub
```

---

## Known Blockers

1. **Quarterly Filter SQL:** Need to understand current `_normalized_forecast_sql()` logic
   - **Workaround:** Use frontend filtering as stopgap
   - **Owner:** Backend engineer

2. **ByProduct Tab Performance:** May be slow with all products
   - **Workaround:** Paginate or virtualize product list
   - **Owner:** Frontend engineer

3. **Chart Export:** Requires canvas library (already have Recharts)
   - **Blocker:** None, should work
   - **Effort:** 1 hour

---

## Success Metrics

After completing all 9 high-priority items:
- ✅ Executives know data freshness instantly (staleness banner)
- ✅ Executives trust data integrity (validation visible)
- ✅ UI feels polished & responsive (skeleton loaders)
- ✅ Data provenance is clear (run dates everywhere)
- ✅ No quarterly filtering bugs (fix deployed)

---

## Contact & Questions

**Frontend Lead:** Atlas team  
**Backend Lead:** Forecast pipeline team  
**Product:** Executive Insights steering committee

Current Status: **On track for leadership presentation** ✅
