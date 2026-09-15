# Forecast Filter Loading

Forecast tab loading uses a per-panel request manager. Forecast API parameters,
model calculations, SQL, and the independent accuracy-publication refresh remain
unchanged.

## Behavior

- Identical URL/parameter requests within a load share one promise. Full Year
  Overview makes seven unique requests on its first load instead of eight.
- Models and freshness responses are reused for five minutes in panel memory.
  With these cached, a subsequent Full Year filter load makes five requests.
  No forecast result data is stored in localStorage or shared between sessions.
- Overview and Plan Tracking publish each section as its response arrives.
  Plan Tracking starts its driver bridge concurrently with Overview data.
  The quarterly summary waits for both full-year inputs before rendering.
  Exec Mode and AI Insights also publish independent responses progressively.
- Changing filters or tabs aborts the previous load. Late responses cannot
  update its successor. Filter-scoped state is cleared before the new selection
  is displayed; a pending selection is not treated as demo data.
- Completed main-tab loads are reused for five minutes within the current filter
  scope. Failed loads are not marked complete. Changing filters clears this
  loaded-tab tracking, while retaining valid filter-independent metadata.
- Manual Refresh bypasses the current tab's loaded state and clears metadata.
  Accuracy continues using its separate publication refresh lifecycle.

Cancellation stops obsolete browser requests and prevents stale UI updates. It
does not guarantee server-side cancellation of an already-running warehouse
query. Existing API timeout and retry settings are unchanged.

## Verification

Run from the repository root:

```powershell
node --test frontend/src/components/forecast/*.test.js
```

Browser checks with controlled, offline responses cover early Overview rendering,
Full Year duplicate sharing, metadata reuse, rapid product changes, all nine tab
render paths, completed-tab revisits, and manual metadata refresh. These checks
do not measure production latency or warehouse performance.

The source changes require a frontend build and app release to reach production.