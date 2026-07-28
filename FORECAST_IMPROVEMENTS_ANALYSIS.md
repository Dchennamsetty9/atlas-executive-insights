# Forecasting Components - Leadership Presentation Readiness Analysis

**Date:** 2026-07-28  
**Scope:** Complete forecasting pipeline (backend, frontend, data validation, UX/performance)  
**Target:** Executive leadership presentation requirements

---

## Executive Summary

The forecasting system has strong technical foundations but requires **21 targeted improvements** across 8 categories to meet leadership presentation standards. **9 improvements are HIGH priority** and can be completed in 1-2 sprints. The most critical gap is **data freshness visibility** — leadership needs clear signals about forecast age and reliability.

---

## 1. FORECAST DATA VALIDATION & ERROR HANDLING

### 1.1 🔴 **CRITICAL: Missing Confidence Band Inversion Validation** 
**Impact:** HIGH | **Effort:** Medium | **Risk:** High  
**Current State:**  
- No validation that `lower < value < upper` in confidence bands
- Backend accepts inverted bands (P10 > P50 or P50 > P90)
- Charts render garbage data without warning

**Improvement:**
```python
# backend/routes/forecast_v2_impl.py — add to _normalise_rows()
def _validate_bands(row: Dict[str, Any]) -> Dict[str, Any]:
    lower, value, upper = _f(row.get("lower")), _f(row.get("value")), _f(row.get("upper"))
    if lower > value or value > upper:
        logger.warning(f"Band inversion at {row.get('ds')}: {lower} > {value} > {upper}")
        # Swap or clamp to avoid chart corruption
        lower, upper = min(lower, value, upper), max(lower, value, upper)
    return {**row, "lower": lower, "value": value, "upper": upper}
```

**Impact on Leadership:** Prevents misleading confidence intervals in executive dashboards.

---

### 1.2 🔴 **CRITICAL: No NULL/Zero Forecast Handling** 
**Impact:** HIGH | **Effort:** Medium | **Risk:** Medium  
**Current State:**  
- `_f()` converts None/empty to 0.0 silently
- Forecasts of $0 render as valid predictions
- No distinction between "no data" vs "forecast is zero"
- Charts can go flat with no warning

**Improvement:**
- Return `null` for missing data instead of 0.0
- Frontend displays "—" for null, distinct from "$0M"
- Add backend `is_valid` flag to rows: `{"ds": "2026-08-15", "value": null, "is_valid": false, "reason": "no_historical_data"}`

**Frontend Change:**
```jsx
// Only render dots/lines if is_valid === true, show warning icon if false
{row.is_valid === false && <span title={row.reason} style={{color: '#f59e0b'}}>⚠</span>}
```

**Impact on Leadership:** Prevents false confidence in forecasts with insufficient data.

---

### 1.3 🟡 **SQL Injection Risk in String Escaping**  
**Impact:** HIGH | **Effort:** Low | **Risk:** High  
**Current State:**  
```python
# Fragile escaping: .replace(chr(39), chr(39)*2)
def _product_filter(product, product_line=None, col="product"):
    effective = _selected_product(product, product_line)
    return f"AND {col} = '{effective.replace(chr(39), chr(39)*2)}'"  # RISKY
```

**Improvement:**
```python
from pyspark.sql import functions as F

# Use parameterized queries instead
def _product_filter_safe(product, product_line=None):
    effective = _selected_product(product, product_line)
    # Return structured predicate for SQL building
    return {"column": "product", "value": effective, "type": "equals"}
```

**Impact on Leadership:** Prevents potential data breach via malicious product names.

---

### 1.4 🟡 **No Negative Value Rejection**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- `_f()` accepts any valid float, including negative ARR
- Negative forecasts can occur from data errors, render as valid

**Improvement:**
```python
def _f_positive(v, default: float = 0.0) -> float:
    try:
        val = float(v) if v is not None and v != "" else default
        return val if val >= 0 else default  # Reject negatives
    except (TypeError, ValueError):
        return default
```

**Impact on Leadership:** Ensures all forecasts remain physically valid.

---

### 1.5 🟡 **Sparse Historical Data Warning**  
**Impact:** MEDIUM | **Effort:** Medium | **Risk:** Low  
**Current State:**  
- No check for minimum historical data (notebooks have MIN_HISTORY=18 months but not enforced)
- Forecasts from short series not flagged
- Leadership cannot judge forecast reliability visually

**Improvement:**
- Add `min_history_met: bool` field to forecast responses
- Return metadata: `{"min_history_met": false, "months_available": 12, "minimum_required": 18, "confidence_reduced": true}`
- Frontend shows warning banner: "⚠️ Forecast based on 12 months of data (minimum 18 recommended)"

**Impact on Leadership:** Makes forecast limitations transparent.

---

## 2. UI/UX OF FORECAST TABS & CHARTS

### 2.1 🔴 **CRITICAL: No Per-Tab Loading States**  
**Impact:** HIGH | **Effort:** Medium | **Risk:** Low  
**Current State:**  
- Tab error boundary catches errors but shows generic "rendering error"
- User doesn't know if tab is loading, failed, or stale
- Weekly/Monthly/Accuracy tabs show nothing until data arrives (~2-3s)
- No indication of progress or estimated time

**Improvement:**
```jsx
// frontend/src/components/ForecastingPanel.jsx
const TabContent = ({ tab, loading, error, data }) => {
  if (loading) return <Skeleton height={300} />;
  if (error) return <TabError error={error} onRetry={() => refetch()} />;
  return <ChartComponent data={data} />;
};

// Wrap each tab with explicit loading state
const [weeklyLoading, setWeeklyLoading] = useState(false);
useEffect(() => {
  setWeeklyLoading(true);
  apiService.getForecastV2Weekly(model, forecastType, product, productLine, salesMarket, year, quarter)
    .then(data => setWeeklyData(data))
    .finally(() => setWeeklyLoading(false));
}, [model, forecastType, product, productLine, salesMarket, year, quarter]);
```

**Impact on Leadership:** Reduces perceived slowness and increases confidence in data completeness.

---

### 2.2 🔴 **No Skeleton Loaders for Tables**  
**Impact:** HIGH | **Effort:** Low | **Risk:** Low  
**Current State:**  
- Monthly table, Accuracy table show blank space during load
- User thinks data is missing, not loading

**Improvement:**
```jsx
// frontend/src/components/ForecastingPanel.jsx
const TableSkeleton = ({ rows = 12 }) => (
  <table style={{ width: '100%' }}>
    <thead><tr>{[...Array(7)].map((_, i) => <th key={i}><Skeleton /></th>)}</tr></thead>
    <tbody>{[...Array(rows)].map((_, i) => <tr key={i}>{[...Array(7)].map((_, j) => <td key={j}><Skeleton height={16} /></td>)}</tr>)}</tbody>
  </table>
);

// Use in Monthly tab
{monthlyLoading ? <TableSkeleton rows={13} /> : <MonthlyTable months={months} />}
```

**Impact on Leadership:** Communicates data is being fetched, prevents perception of system malfunction.

---

### 2.3 🟡 **Tab Error Messages Lack Actionable Guidance**  
**Impact:** MEDIUM | **Effort:** Medium | **Risk:** Low  
**Current State:**  
```jsx
// Current: generic error
<div>This tab encountered a rendering error.</div>

// No info about why or how to fix
```

**Improvement:**
```jsx
const TabError = ({ error, endpoint, onRetry }) => {
  const guidance = {
    'No data available': 'The forecast job may not have run yet. It runs every Monday at 03:00 UTC.',
    'TABLE_OR_VIEW_NOT_FOUND': 'Forecast table does not exist. Contact data team to run initialization job.',
    'Network error': 'Connection to Databricks lost. Check network and refresh.',
    'Schema mismatch': 'Data format changed. Contact support.',
  };
  const msg = guidance[error?.message] || guidance[Object.keys(guidance).find(k => error?.message?.includes(k))] || 'Unknown error';
  
  return (
    <div style={{ padding: '24px', background: 'rgba(239,68,68,0.06)', borderRadius: 10 }}>
      <p style={{ fontWeight: 600 }}>{error?.message || 'Error loading data'}</p>
      <p style={{ fontSize: 12, color: '#64748b' }}>{msg}</p>
      <button onClick={onRetry} style={{marginTop: 10}}>↻ Retry</button>
    </div>
  );
};
```

**Impact on Leadership:** Reduces support tickets and improves user confidence.

---

### 2.4 🟡 **Inconsistent Demo vs Live Data Indicators**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- AI Insights tab shows "📋 Sample data — connect to Databricks"
- Weekly/Monthly/Accuracy tabs show `"source": "demo"` in JSON but no UI indication
- User might present demo forecasts as real

**Improvement:**
- Add banner to every tab when `source === "demo"`:
```jsx
{data?.source === 'demo' && (
  <div style={{padding:'8px 12px', background:'rgba(245,158,11,0.08)', 
               borderRadius:6, fontSize:11, color:'#f59e0b', marginBottom:12,
               border:'1px solid rgba(245,158,11,0.2)'}}>
    📋 Demo Data — Not connected to live Databricks. Results for testing only.
  </div>
)}
```

**Impact on Leadership:** Prevents accidental presentation of sample data in board meetings.

---

### 2.5 🟡 **Model Lab Recommended Model Not Highlighted**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- Model Lab shows all 6 models in pills
- `recommended_model` field available but not visually prominent
- Users might select sub-optimal model without knowing

**Improvement:**
```jsx
// Highlight recommended model
{models.map((m) => (
  <button key={m} onClick={() => setSel(m)} 
    style={{
      ...pillStyle(sel === m, colorOf[m]),
      fontWeight: m === data?.recommended_model ? 800 : 700,
      border: m === data?.recommended_model ? `2px solid ${colorOf[m]}` : `1px solid ...`,
    }}>
    {mlLabel(m)} {m === data?.recommended_model && '⭐'}
  </button>
))}
```

**Impact on Leadership:** Guides selection toward best-performing model.

---

## 3. DATA FRESHNESS & TIMESTAMP DISPLAY

### 3.1 🔴 **CRITICAL: No "Data is Stale" Warning**  
**Impact:** HIGH | **Effort:** Medium | **Risk:** High  
**Current State:**  
- Forecast job runs "every Monday 03:00 UTC"
- If it's Tuesday afternoon and job hasn't run, no warning shown
- Leadership might make decisions on week-old forecast
- Freshness SLA exists (`sla_status: 'breached'`) but only shown if breached

**Improvement:**
```jsx
// frontend/src/components/ForecastingPanel.jsx
const [freshness, setFreshness] = useState(null);

useEffect(() => {
  apiService.getForecastV2Freshness().then(f => setFreshness(f));
}, []);

// Add banner (always, not just on breach)
{freshness && (
  <div style={{
    padding: '10px 14px', borderRadius: 8, fontSize: 11, marginBottom: 12,
    background: freshness.sla_status === 'breached' ? 'rgba(239,68,68,0.08)' : 'rgba(59,130,246,0.08)',
    border: `1px solid ${freshness.sla_status === 'breached' ? 'rgba(239,68,68,0.2)' : 'rgba(59,130,246,0.2)'}`,
    color: freshness.sla_status === 'breached' ? '#ef4444' : '#3b82f6'
  }}>
    {freshness.sla_status === 'breached' 
      ? `⚠️ Data stale — last updated ${freshness.age_hours} hours ago (expected by Monday 06:00 UTC)`
      : `✅ Data current — last updated ${freshness.age_minutes} minutes ago`
    }
    {freshness.next_run && <span style={{marginLeft: 8, fontSize: 10}}>Next run in {freshness.next_run_minutes} minutes</span>}
  </div>
)}
```

**Backend Response:**
```python
@router.get("/freshness")
async def get_freshness(live_mode: bool = Depends(_live_mode_dependency)):
    try:
        rows = await _cached_query(f"SELECT MAX(CAST(run_date AS TIMESTAMP)) AS latest FROM {FC_TABLE}")
        latest = rows[0]['latest'] if rows else None
        if not latest:
            return {"source": "live", "age_hours": 999, "sla_status": "breached", "narrative": "Never run"}
        
        now = datetime.datetime.utcnow()
        age = (now - latest).total_seconds() / 3600
        next_monday = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=(7 - now.weekday()))
        next_monday = next_monday.replace(hour=3, minute=0)
        next_run_seconds = (next_monday - now).total_seconds()
        
        return {
            "source": "live",
            "latest_run": str(latest),
            "age_hours": round(age, 1),
            "age_minutes": round(age * 60),
            "sla_status": "breached" if age > 48 else "warning" if age > 24 else "healthy",
            "next_run_minutes": round(max(0, next_run_seconds) / 60),
            "sla_due": str(next_monday),
        }
    except Exception as e:
        logger.warning(f"Freshness check failed: {e}")
        return {"source": "demo", "error": str(e)}
```

**Impact on Leadership:** Prevents decisions on stale data; builds trust in forecast recency.

---

### 3.2 🟡 **Timestamps Not Shown in All Tabs**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- Only AI Insights and Model Lab show `run_date`
- Weekly, Monthly, Accuracy tabs have no timestamp
- User can't tell when data was last updated per chart

**Improvement:**
- Add run_date field to all endpoint responses:
```python
# backend
return {"source": "live", "rows": [...], "run_date": str(rows[0].get('run_date', today))}
```

- Display in every tab footer:
```jsx
<div style={{fontSize: 10, color: '#475569', marginTop: 12, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.05)'}}>
  Run {String(data?.run_date).slice(0, 10)} · {data?.source === 'live' ? '🟢 Live' : '🟡 Demo'}
</div>
```

**Impact on Leadership:** Shows audit trail for every forecast displayed.

---

### 3.3 🟡 **Run Date Format Inconsistent**  
**Impact:** LOW | **Effort:** Low | **Risk:** Low  
**Current State:**  
- SQL returns: `CAST(run_date AS TIMESTAMP)`
- Frontend shows: sometimes "2026-07-28", sometimes "run 2026-07-28", sometimes missing
- User experiences inconsistent information

**Improvement:**
```python
# Standardize in backend
"run_date": datetime.datetime.strptime(str(row['run_date']), '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d'),
```

**Impact on Leadership:** Reduces cognitive load; consistent UI.

---

## 4. PERFORMANCE & LOADING STATES

### 4.1 🔴 **CRITICAL: Demo Hardcoded with Future Dates**  
**Impact:** HIGH | **Effort:** Low | **Risk:** Low  
**Current State:**  
```python
# backend/routes/forecast.py — demo ARR payload
demo_payload = {
    "data": {
        "actual": {"actuals": [
            {"date": "2026-01-05", "value": 4100000},  # ← 2026 dates
            ...
        ]},
        "Prophet": {"forecast": [
            {"date": "2026-02-09", "value": 4620000, ...},  # ← Future
            ...
        ]}
    }
}
```

**Improvement:**
```python
import datetime

def _demo_arr_payload() -> dict:
    today = datetime.date.today()
    actuals = []
    for i in range(5):
        d = today - datetime.timedelta(weeks=5-i)
        actuals.append({"date": str(d), "value": 4100000 + i*120000})
    
    forecast = []
    base_val = 4600000
    for i in range(1, 5):
        d = today + datetime.timedelta(weeks=i)
        forecast.append({
            "date": str(d),
            "value": base_val + i*100000,
            "lower": (base_val + i*100000) * 0.92,
            "upper": (base_val + i*100000) * 1.08
        })
    
    return {"source": "demo", "products": ["UCC", "ITSG"], "data": {...}}
```

**Impact on Leadership:** Prevents confusion when seeing year 2026 in demo.

---

### 4.2 🟡 **Cache TTL Not Visible to Users**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- 300s cache configured: `FORECAST_V2_CACHE_TTL_SECONDS = 300`
- User refreshes data but gets cached response from 4 minutes ago
- No indication that cache is active

**Improvement:**
- Return cache metadata in every response:
```python
return {
    "source": "live",
    "cached": True,
    "cached_at": datetime.datetime.utcnow().isoformat(),
    "cache_expires_at": (datetime.datetime.utcnow() + datetime.timedelta(seconds=CACHE_TTL_SECONDS)).isoformat(),
    "cache_ttl_seconds": CACHE_TTL_SECONDS,
    "rows": [...]
}
```

- Frontend shows:
```jsx
{data?.cached && (
  <button onClick={() => apiService.clearForecastCache()} style={{fontSize: 10, color: '#64748b'}}>
    🔄 Cached {Math.round((new Date(data.cached_at) - new Date().getTime()) / 1000)}s ago — Click to refresh
  </button>
)}
```

**Impact on Leadership:** Transparency about data freshness within cache window.

---

### 4.3 🟡 **No Query Timeout Handling**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- Parallel queries in `get_weekly()`, `get_monthly()`, etc. use `asyncio.gather()`
- No timeout set; queries can hang indefinitely
- Browser tab becomes unresponsive

**Improvement:**
```python
import asyncio

async def _cached_query_with_timeout(sql: str, endpoint: str, timeout_seconds: int = 10, **params: Any):
    try:
        return await asyncio.wait_for(
            _cached_query(sql, endpoint, **params),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.warning(f"Query timeout on {endpoint} after {timeout_seconds}s")
        raise HTTPException(status_code=504, detail=f"Query timeout after {timeout_seconds}s")

# Use in endpoints
try:
    rows = await _cached_query_with_timeout(sql, "/weekly", timeout_seconds=15)
except asyncio.TimeoutError:
    return _demo("rows", error="Query timeout — Databricks is slow")
```

**Impact on Leadership:** Prevents hung browser; graceful degradation to demo.

---

## 5. MISSING EDGE CASE HANDLING

### 5.1 🔴 **CRITICAL: Quarterly Filtering Can Mix Actuals & Forecasts**  
**Impact:** HIGH | **Effort:** Medium | **Risk:** High  
**Current State:**  
```python
# backend/routes/forecast_v2_impl.py — get_weekly()
kpi_sql = f"""
    SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
    FROM {FC_TABLE}
    WHERE {_latest_run()}
        {_product_filter(product, product_line)} {_geo_filter(sales_market)}
      AND (
            ({_actuals_year_filter(year)} {f"AND {_quarter_filter(quarter, year)}" if quarter else ""})
            OR (forecast_type IN ('rolling', 'roy') AND {qtr_filter})
          )
    ORDER BY ds
"""
```

**Problem:** When filtering Q2 2026, returns both:
- Actuals from Q2 2026 (Jan–Jun) if available
- Forecasts from rolling/roy starting mid-Q2
- Sum of both inflates expected ARR

**Improvement:**
```python
def get_weekly(...):
    """When quarter is specified, choose actuals-only or forecast-only, not both."""
    if quarter is not None:
        # User asked for Q2 data — give them either historical actuals OR forward forecasts, not mixed
        year_today = datetime.date.today().year
        is_past = (year < year_today) or (year == year_today and quarter < ((datetime.date.today().month - 1) // 3 + 1))
        
        if is_past:
            # Historical quarter — give actuals only
            forecast_type = 'actuals'
        else:
            # Future quarter — give forecasts only
            forecast_type = forecast_type  # Use user's selection
        
        kpi_sql = f"""
            SELECT ds, Actuals, Most_Likely, Worst_Case, Best_Case, forecast_type
            FROM {FC_TABLE}
            WHERE {_latest_run()}
                {_product_filter(product, product_line)} {_geo_filter(sales_market)}
              AND forecast_type = '{forecast_type}'
              AND {_quarter_filter(quarter, year)}
            ORDER BY ds
        """
    else:
        # Full year — include both actuals and forecasts as before
        ...
```

**Impact on Leadership:** Prevents KPI cards from showing inflated numbers due to double-counting.

---

### 5.2 🟡 **All-Zero Forecast Handling**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- If all forecasts = $0, chart renders flat line
- No warning that model failed

**Improvement:**
```python
def _summary_kpis(rows: list[Dict[str, Any]]) -> Dict[str, float]:
    # ... existing logic ...
    
    # Add validation
    if most_likely == 0.0 and worst_case == 0.0 and best_case == 0.0:
        return {
            "most_likely": 0.0,
            "worst_case": 0.0,
            "best_case": 0.0,
            "ytd_actuals": ytd_actuals,
            "is_valid": False,
            "warning": "All forecast values are zero. Model may have failed to generate predictions."
        }
    
    return {
        "most_likely": round(most_likely, 0),
        "worst_case": round(worst_case, 0),
        "best_case": round(best_case, 0),
        "ytd_actuals": round(ytd_actuals, 0),
        "is_valid": True,
    }
```

**Frontend:**
```jsx
{kpis?.is_valid === false && (
  <div style={{color: '#f59e0b', fontSize: 11, fontWeight: 600, marginBottom: 8}}>
    ⚠️ {kpis.warning}
  </div>
)}
```

**Impact on Leadership:** Alerts to model failure rather than presenting zero as valid forecast.

---

### 5.3 🟡 **No Protection Against Division by Zero**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```python
# Multiple places in frontend: confidence = (rawConf > 1 ? Math.round(rawConf) : Math.round(rawConf * 100))
# If rawConf is Infinity or NaN, renders garbage
```

**Improvement:**
```python
# backend
def _f(v, default: float = 0.0) -> float:
    try:
        val = float(v) if v is not None and v != "" else default
        if math.isnan(val) or math.isinf(val):
            return default
        return max(val, 0)  # Reject negatives
    except (TypeError, ValueError):
        return default
```

```jsx
// frontend
const confidence = rawConf != null && !isNaN(rawConf) && isFinite(rawConf)
  ? (rawConf > 1 ? Math.round(rawConf) : Math.round(rawConf * 100))
  : null;
```

**Impact on Leadership:** Prevents NaN/Infinity from appearing in charts.

---

### 5.4 🟡 **Empty Selection Validation**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- User can filter by product_line="" or sales_market=""
- Backend defaults to "All" or "Total"
- Causes unexpected data aggregations

**Improvement:**
```python
# backend
def get_weekly(...):
    product_line = (product_line or "").strip() or None
    sales_market = (sales_market or "").strip() or None
    # Now empty strings treated as None, defaults to All/Total
```

```jsx
// frontend
const handleProductChange = (value) => {
    if (!value || value === "") setProductLine("All");
    else setProductLine(value);
};
```

**Impact on Leadership:** Prevents silent defaults from causing data confusion.

---

## 6. DATA FORMATTING & CLARITY

### 6.1 🔴 **CRITICAL: Hardcoded Year List Doesn't Update**  
**Impact:** HIGH | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
// frontend/src/components/ForecastingPanel.jsx
const years = [2024, 2025, 2026];
// Hardcoded — when we reach 2027, will show 2026 as last option

// And:
const YEAR_COLORS  = { 2022: '#64748b', 2023: '#06b6d4', 2024: '#3b82f6', 2025: '#f59e0b', 2026: '#ef4444' };
// When 2027 arrives, year picker won't have color, rendering breaks
```

**Improvement:**
```jsx
// Dynamically build years
const currentYear = new Date().getFullYear();
const years = Array.from({length: 4}, (_, i) => currentYear - 3 + i);  // Last 3 + current + next

// Dynamic colors
const YEAR_COLORS = (year) => {
    const offset = year - currentYear;
    const palette = ['#64748b', '#06b6d4', '#3b82f6', '#f59e0b', '#ef4444'];
    return palette[offset + 2] || '#94a3b8';
};

// Use:
{years.map(yr => <option key={yr} value={yr}>{yr}</option>)}
{years.map(yr => (
  <Line key={yr} ... stroke={YEAR_COLORS(yr)} />
))}
```

**Impact on Leadership:** Year picker won't break when calendar advances.

---

### 6.2 🟡 **Confidence Percentage Normalization Issue**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
// frontend: can't tell if rawConf is 0-1 or 0-100
const confidence = rawConf != null ? (rawConf > 1 ? Math.round(rawConf) : Math.round(rawConf * 100)) : null;
// Assumes backend consistency; if one endpoint returns 0.85 and another returns 85, display is wrong
```

**Improvement:**
```python
# backend: standardize to 0-1 range in all responses
def _normalize_confidence(value):
    try:
        v = float(value) if value is not None else None
        if v is None:
            return None
        # If looks like percentage (>1), divide by 100
        if v > 1:
            v = v / 100
        # Clamp to [0, 1]
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return None

# Use everywhere:
payload["model_confidence"] = _normalize_confidence(row.get("confidence"))
```

```jsx
// frontend: always 0-1
const confidence = aiData?.model_confidence != null ? Math.round(aiData.model_confidence * 100) : null;
```

**Impact on Leadership:** Eliminates display confusion about confidence scale.

---

### 6.3 🟡 **Product/Market "All" vs "Total" Normalization**  
**Impact:** MEDIUM | **Effort:** Medium | **Risk:** Medium  
**Current State:**  
- Some endpoints return product="All", some return product="Total"
- Some user filters use "All", some default to null
- Creates inconsistent aggregations

**Improvement:**
```python
# backend: standardize to "Total"
def _normalize_selection(value: Optional[str], default: str = "Total") -> str:
    if not value:
        return default
    normalized = value.strip().upper()
    if normalized in ("ALL", "TOTAL", "*"):
        return default
    return value.strip()

# All responses:
for row in rows:
    row["product"] = _normalize_selection(row.get("product"))
    row["sales_market"] = _normalize_selection(row.get("sales_market"))
```

```jsx
// frontend: always expect "Total"
const isAllProducts = product === "Total" || product === "All";
```

**Impact on Leadership:** Consistent labels reduce confusion.

---

### 6.4 🟡 **MAPE/Accuracy Values >999 Unclear**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
// Shows "—" but no explanation
{r.best_mape&&r.best_mape<999 ? `${r.best_mape.toFixed(1)}%` : '—'}
```

**Improvement:**
```jsx
const mapeDisplay = (value) => {
    if (value == null) return '—';  // Missing data
    if (value >= 999) return '⚠ N/A';  // Not enough data or error
    if (value > 50) return <span title="Model underperformed">~{Math.min(99, Math.round(value))}%</span>;
    return value.toFixed(1) + '%';
};

{mapeDisplay(r.best_mape)}
```

**Impact on Leadership:** Transparency about data quality vs missing data.

---

### 6.5 🟡 **Risk/Momentum Badges Use Multiple Field Variants**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
// Assumes one of several field names
const momentum  = aiData?.momentum ?? aiData?.trend_status ?? 'STABLE';
const risk      = aiData?.risk_level ?? aiData?.risk ?? 'moderate';
// If backend changes field names, silently defaults to wrong value
```

**Improvement:**
```python
# backend: standardize field names in AI Insights response
def _normalize_ai_insights(payload):
    return {
        ...payload,
        "momentum": payload.get("momentum") or payload.get("trend_status"),
        "risk_level": payload.get("risk_level") or payload.get("risk"),
        "model_confidence": _normalize_confidence(payload.get("model_confidence") or payload.get("confidence")),
    }
```

```jsx
// frontend: only expect normalized names
const momentum = aiData?.momentum || 'STABLE';
const risk = aiData?.risk_level || 'moderate';
```

**Impact on Leadership:** Reduces silent data quality issues.

---

### 6.6 🟡 **Delta (Upside/Downside) Formatting Inconsistent**  
**Impact:** LOW | **Effort:** Low | **Risk:** Low  
**Current State:**  
- Some responses return `upside_dollar`, some return `upside`
- Some return absolute value, some return signed value
- Frontend normalizes but inconsistently

**Improvement:**
```python
# backend: standardize
def _normalize_deltas(payload):
    upside = payload.get("upside") or payload.get("upside_dollar") or payload.get("upside_pct")
    downside = payload.get("downside") or payload.get("downside_dollar") or payload.get("downside_pct")
    return {
        ...payload,
        "upside": abs(float(upside)) if upside else None,
        "downside": abs(float(downside)) if downside else None,
    }
```

**Impact on Leadership:** Consistent financial impact display.

---

## 7. HARDCODED VALUES & DEMO FALLBACKS

### 7.1 🟡 **Model Lab Labels Hard-Coded**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
const mlLabel = (m) => {
    if (!m) return '';
    if (m === 'Adaptive_Ensemble') return 'Ensemble ★';
    return m.replace(/_/g, ' ').replace(/\btrend\b/i, '').replace(/\bv2\b/i, '').trim();
};
// If model names change in notebooks, display breaks
```

**Improvement:**
```python
# backend: return display names with models
MODEL_DISPLAY_NAMES = {
    "ensemble": "Ensemble ⭐",
    "prophet": "Prophet Trend",
    "ets": "Exponential Smoothing",
    "lightgbm": "LightGBM (Gradient)",
    "mstl_v2": "MSTL v2",
    "dhr_arima": "DHR-ARIMA",
}

@router.get("/models")
async def get_models():
    return {
        "models": [{"key": k, "label": v, "color": MODEL_COLORS[k]} for k, v in MODEL_DISPLAY_NAMES.items()]
    }
```

```jsx
// frontend: use backend-provided labels
{data?.models?.map(m => <button key={m.key}>{m.label}</button>)}
```

**Impact on Leadership:** Model names sync with data without code changes.

---

### 7.2 🟡 **Tab List Hardcoded**  
**Impact:** LOW | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
const TABS = ['Overview', 'Multi-Year', 'By Product', 'Monthly', 'Accuracy', 'Model Lab', 'AI Insights', 'Exec Mode'];
// If we add/remove tabs, requires frontend code change
```

**Improvement:**
```python
# backend
@router.get("/config")
async def get_config():
    return {
        "tabs": [
            {"key": "overview", "label": "Overview", "icon": "📊"},
            {"key": "multiyear", "label": "Multi-Year", "icon": "📈"},
            ...
        ],
        "models": [...],
        "products": ["UCC", "ITSG"],
    }
```

```jsx
// frontend
const [config, setConfig] = useState({ tabs: [] });

useEffect(() => {
    apiService.getForecastV2Config().then(cfg => setConfig(cfg));
}, []);

{config.tabs.map(tab => (
    <button key={tab.key} onClick={() => setActiveTab(tab.key)}>
        {tab.icon} {tab.label}
    </button>
))}
```

**Impact on Leadership:** Tab structure updates server-side without frontend redeploy.

---

## 8. ERROR MESSAGES & USER FEEDBACK

### 8.1 🔴 **CRITICAL: Generic "Databricks Unavailable" Fallback**  
**Impact:** HIGH | **Effort:** Low | **Risk:** Low  
**Current State:**  
```python
def _demo(key: str, error: str = "Databricks unavailable"):
    return {"source": "demo", "live_mode_available": False, "error": error, key: []}
```

**Problem:**  
- User sees "Databricks unavailable" but actual error might be:
  - Table doesn't exist (needs schema initialization)
  - Wrong permissions (needs PAT setup)
  - Network timeout (temporary, will retry soon)
  - Query is malformed (needs code fix)

**Improvement:**
```python
def _demo_with_reason(endpoint: str, error: Exception = None) -> dict:
    reason = "Unknown error"
    if error:
        exc_str = str(error).lower()
        if "table" in exc_str or "view" in exc_str or "not_found" in exc_str:
            reason = "Table not found — run initialization job"
        elif "permission" in exc_str or "unauthorized" in exc_str or "access" in exc_str:
            reason = "Authentication failed — check Databricks PAT/token"
        elif "timeout" in exc_str or "deadline" in exc_str:
            reason = "Query timeout — Databricks is slow, retry in 60s"
        elif "connection" in exc_str or "network" in exc_str:
            reason = "Network error — check connectivity"
        elif "schema" in exc_str or "type" in exc_str:
            reason = "Data format mismatch — contact support"
        else:
            reason = f"Error: {error}"
    
    return {
        "source": "demo",
        "live_mode_available": False,
        "error": reason,
        "endpoint": endpoint,
        "data": []
    }

# Use in endpoints
try:
    rows = await _cached_query(sql, ...)
except Exception as exc:
    logger.warning(f"Query failed: {exc}")
    return _demo_with_reason("/weekly", exc)
```

**Frontend:**
```jsx
{data?.source === 'demo' && data?.error && (
  <div style={{padding: '12px', background: 'rgba(245,158,11,0.08)', borderRadius: 8}}>
    <p style={{fontWeight: 600, marginBottom: 4}}>📋 Using sample data</p>
    <p style={{fontSize: 11, color: '#64748b'}}>{data.error}</p>
    <p style={{fontSize: 10, marginTop: 4}}>
      {data.error.includes("initialization") && "👉 <a href='...'>Run initialization notebook</a>"}
      {data.error.includes("PAT") && "👉 <a href='...'>Setup Databricks auth</a>"}
      {data.error.includes("slow") && "👉 Try again in 1 minute"}
    </p>
  </div>
)}
```

**Impact on Leadership:** Users can self-serve fixes instead of support tickets.

---

### 8.2 🟡 **AI Insights Error References Specific Notebook Cells (Brittle)**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```jsx
<p>Run Cell 10 (Step 7) of the Panel Writer notebook to populate the AI Insights Delta table.</p>
```

**Problem:**  
- If notebook structure changes, error message becomes wrong
- Becomes confusing outdated message

**Improvement:**
```python
# backend: return config URL
@router.get("/intelligence")
async def get_intelligence(...):
    if aiData?.error and !aiData?.key_drivers?.length:
        return {
            "error": "No insights data",
            "narrative": "AI Insights table is empty",
            "fix_url": "/docs/ai-insights-setup",  # Dynamic link
            "fix_steps": [
                "1. Open 'Panel Writer' notebook in Databricks",
                "2. Navigate to the 'AI Insights' section (labeled '## AI Insights' or 'Step 7')",
                "3. Click 'Run All' for that cell group",
                "4. Refresh this page after ~5 minutes"
            ]
        }
```

```jsx
{data?.error && (
  <div>
    <p>{data.narrative}</p>
    <ol>
      {data?.fix_steps?.map((step, i) => <li key={i} style={{fontSize: 11}}>{step}</li>)}
    </ol>
    {data?.fix_url && <a href={data.fix_url}>View full documentation</a>}
  </div>
)}
```

**Impact on Leadership:** Help text stays current with notebook changes.

---

### 8.3 🟡 **Schema Introspection Errors Not Shown to User**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
```python
# Silent logging only
logger.warning("[forecast/table-columns] schema introspection failed for %s: %s", table_name_sql, exc)
return set()  # Returns empty, downstream falls back to demo
```

**Improvement:**
```python
# Return error info to frontend
async def _table_columns_safe(table_name_sql: str, endpoint: str):
    try:
        rows = await _cached_query(...)
        return {"columns": {...}, "error": None}
    except Exception as exc:
        logger.warning(f"Schema introspection failed: {exc}")
        return {
            "columns": {},
            "error": str(exc),
            "message": f"Unable to read schema for {table_name_sql} — table may not exist or credentials lack permissions"
        }

# Frontend shows warning if error
{data?.schema_error && (
  <div style={{fontSize: 10, color: '#f59e0b', padding: '6px 8px', background: 'rgba(245,158,11,0.08)', borderRadius: 4}}>
    ⚠️ {data.schema_error}
  </div>
)}
```

**Impact on Leadership:** Users aware of potential data quality issues.

---

### 8.4 🟡 **Missing Success Indicators**  
**Impact:** MEDIUM | **Effort:** Low | **Risk:** Low  
**Current State:**  
- Successful data load = no message (silent success)
- Only errors are shown
- User can't tell if system is working or just hasn't checked recently

**Improvement:**
```jsx
// Add success toast on tab load
useEffect(() => {
  if (data?.source === 'live' && data?.rows?.length > 0) {
    // Show brief success indicator
    toast.success(`📊 Updated ${new Date().toLocaleTimeString()}`);
  }
}, [data]);

// Or footer badge
<div style={{fontSize: 9, color: '#10b981', marginTop: 6}}>
  ✅ Data loaded successfully
</div>
```

**Impact on Leadership:** Builds confidence in system health.

---

## Summary Table: Prioritized Improvements

| Priority | Impact | Category | Title | Effort | Risk |
|----------|--------|----------|-------|--------|------|
| 🔴 1 | HIGH | Validation | Missing Confidence Band Inversion Validation | Medium | High |
| 🔴 2 | HIGH | Validation | No NULL/Zero Forecast Handling | Medium | Medium |
| 🔴 3 | HIGH | Freshness | No "Data is Stale" Warning | Medium | High |
| 🔴 4 | HIGH | UX | No Per-Tab Loading States | Medium | Low |
| 🔴 5 | HIGH | Edge Cases | Quarterly Filtering Mixes Actuals & Forecasts | Medium | High |
| 🔴 6 | HIGH | Formatting | Hardcoded Year List Doesn't Update | Low | Low |
| 🔴 7 | HIGH | Errors | Generic "Databricks Unavailable" Fallback | Low | Low |
| 🔴 8 | HIGH | Performance | Demo Data Hardcoded with Future Dates | Low | Low |
| 🔴 9 | HIGH | Security | SQL Injection Risk in String Escaping | Low | High |
| 🟡 10 | MEDIUM | UX | No Skeleton Loaders for Tables | Low | Low |
| 🟡 11 | MEDIUM | UX | Tab Error Messages Lack Actionable Guidance | Medium | Low |
| 🟡 12 | MEDIUM | UX | Inconsistent Demo vs Live Data Indicators | Low | Low |
| 🟡 13 | MEDIUM | Freshness | Timestamps Not Shown in All Tabs | Low | Low |
| 🟡 14 | MEDIUM | Performance | Cache TTL Not Visible to Users | Low | Low |
| 🟡 15 | MEDIUM | Performance | No Query Timeout Handling | Low | Low |
| 🟡 16 | MEDIUM | Edge Cases | All-Zero Forecast Handling | Low | Low |
| 🟡 17 | MEDIUM | Edge Cases | No Protection Against Division by Zero | Low | Low |
| 🟡 18 | MEDIUM | Edge Cases | Empty Selection Validation | Low | Low |
| 🟡 19 | MEDIUM | Formatting | Confidence Percentage Normalization Issue | Low | Low |
| 🟡 20 | MEDIUM | Formatting | Product/Market "All" vs "Total" Normalization | Medium | Medium |
| 🟡 21 | MEDIUM | Errors | AI Insights Error References Specific Notebook Cells | Low | Low |
| 🟡 22 | MEDIUM | Errors | Schema Introspection Errors Not Shown to User | Low | Low |
| 🟡 23 | MEDIUM | UX | Model Lab Recommended Model Not Highlighted | Low | Low |
| 🟡 24 | MEDIUM | Formatting | MAPE/Accuracy Values >999 Unclear | Low | Low |
| 🟡 25 | MEDIUM | Formatting | Risk/Momentum Badges Use Multiple Field Variants | Low | Low |
| 🟡 26 | MEDIUM | Formatting | Delta (Upside/Downside) Formatting Inconsistent | Low | Low |
| 🟡 27 | MEDIUM | Errors | Missing Success Indicators | Low | Low |
| 🟡 28 | LOW | Formatting | Run Date Format Inconsistent | Low | Low |
| 🟡 29 | LOW | Hardcoding | Model Lab Labels Hard-Coded | Low | Low |
| 🟡 30 | LOW | Hardcoding | Tab List Hardcoded | Low | Low |
| 🟡 31 | LOW | Formatting | Delta (Upside/Downside) Formatting Inconsistent | Low | Low |

---

## Recommended Implementation Plan

### **Sprint 1 (Week 1-2): Security & Data Integrity**
- 🔴 #1: Confidence band validation
- 🔴 #9: SQL injection fix
- 🔴 #5: Quarterly filtering logic
- 🟡 #17: Division by zero protection

### **Sprint 2 (Week 3-4): User Experience & Visibility**
- 🔴 #3: Data freshness warning
- 🔴 #4: Per-tab loading states
- 🟡 #10: Skeleton loaders
- 🟡 #12: Demo vs live indicators

### **Sprint 3 (Week 5-6): Data Quality & Clarity**
- 🔴 #2: NULL/zero handling
- 🔴 #6: Dynamic year list
- 🟡 #19: Confidence normalization
- 🟡 #20: Product/Market normalization

### **Sprint 4 (Week 7-8): Error Handling & Polish**
- 🔴 #7: Better error messages
- 🟡 #11: Tab error guidance
- 🟡 #21, #22: AI Insights & schema errors
- 🟡 #27: Success indicators

---

## Leadership Presentation Readiness Checklist

- [ ] **Data Freshness:** Clear "last updated" timestamp on every chart
- [ ] **Data Quality:** Validation warnings for sparse/invalid data
- [ ] **Error Safety:** Graceful fallbacks with helpful guidance, no "undefined" in UI
- [ ] **Confidence:** 80% band clearly marked; MAPE thresholds color-coded
- [ ] **Performance:** All tabs load in <2s with skeleton loaders
- [ ] **Consistency:** Year list, model names, confidence scales match across all tabs
- [ ] **Security:** No SQL injection risks; proper escaping throughout
- [ ] **Audit Trail:** run_date visible on every visualization
- [ ] **Demo Mode:** Clear labeling when in demo vs live data
- [ ] **Accessibility:** Error messages are actionable, not cryptic

---

## Files to Modify (Priority Order)

1. `backend/routes/forecast_v2_impl.py` — data validation, error handling, freshness
2. `frontend/src/components/ForecastingPanel.jsx` — loading states, timestamps, error guidance
3. `frontend/src/services/api.js` — add freshness, config endpoints
4. `notebooks/arr_forecast_v2_main.py` — data quality checks, warnings
5. `backend/routes/forecast.py` — remove hardcoded demo dates, improve fallback messages

---

## Next Steps

1. **Review with data team:** Confirm quarterly filtering logic matches business intent
2. **Prioritize with product:** Which improvements must ship before board presentation?
3. **Assign owners:** 5 backend + 3 frontend changes, 2-week timeline realistic
4. **Test edge cases:** Sparse data, stale runs, schema changes
5. **Update docs:** Notebook troubleshooting, API error codes, data freshness SLA

