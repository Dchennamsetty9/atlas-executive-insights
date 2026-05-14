# Atlas Executive Insights - Component Architecture

## Component Hierarchy

```
App.jsx
├── Header (inline)
│   ├── Logo (Activity icon)
│   ├── Title & Subtitle
│   ├── Last Updated timestamp
│   └── Connection Status indicator
│
├── Main Content
│   ├── KPI Section
│   │   └── KPIGrid
│   │       └── KPICard (×8)
│   │           ├── Metric name & value
│   │           ├── Target comparison
│   │           ├── Trend indicator (TrendingUp/Down/Minus icons)
│   │           └── Progress bar
│   │
│   ├── Performance Analytics Section
│   │   ├── ARRTrendChart
│   │   │   ├── LineChart (Recharts)
│   │   │   ├── Custom tooltip
│   │   │   └── Summary stats
│   │   │
│   │   └── PipelineChart
│   │       ├── BarChart (Recharts)
│   │       ├── Custom tooltip
│   │       └── Summary cards
│   │
│   ├── Forecast Section
│   │   └── ForecastChart
│   │       ├── Scenario toggle buttons (Best/Most Likely/Worst)
│   │       ├── Confidence interval toggle
│   │       ├── ComposedChart (Lines + Area)
│   │       ├── Custom tooltip
│   │       └── Summary stats (4 values)
│   │
│   └── Footer Info (inline)
│       ├── Data Source info
│       ├── Forecast Model info
│       └── Refresh Frequency info
│
└── Footer (inline)
    ├── Copyright
    └── Links (API docs, Help)
```

## Data Flow

### 1. KPI Data Flow
```
User visits page
    ↓
App.jsx useEffect runs
    ↓
checkBackendHealth() called
    ↓
apiService.healthCheck()
    ↓
[GET /] endpoint
    ↓
Updates backendStatus state
    ↓
KPIGrid mounts
    ↓
fetchKPIs() called
    ↓
apiService.getKPIs()
    ↓
[GET /api/kpis] endpoint
    ↓
Returns 8 KPI objects:
  {
    metric_name: string,
    metric_value: number,
    target_value: number,
    previous_period_value: number
  }
    ↓
transformedKPIs mapped with:
  - formatKPIName() (e.g., 'won_pipeline' → 'Won Pipeline')
  - getKPIFormat() ('currency', 'percentage', 'number')
  - getKPIUnit() ('$', '%', '#')
    ↓
Rendered as 8 KPICard components
    ↓
Each card shows:
  - Name
  - Formatted value
  - Trend icon + % change
  - Progress bar (actual/target)
```

### 2. ARR Trend Data Flow
```
ARRTrendChart mounts
    ↓
fetchARRData() called
    ↓
apiService.getARRHistory()
    ↓
[GET /api/arr/history] endpoint
    ↓
Returns:
  {
    history: [
      { ds: date, y: value, growth_pct: number }
    ],
    current_arr: number
  }
    ↓
Format dates: new Date().toLocaleDateString()
    ↓
Map to chart data:
  [{ date, arr, growth }]
    ↓
Recharts LineChart renders
    ↓
Shows:
  - X-axis: dates
  - Y-axis: ARR values ($XXM)
  - Line: blue (#3b82f6), 3px width
  - Tooltips: custom with currency + growth
```

### 3. Pipeline Data Flow
```
PipelineChart mounts
    ↓
fetchPipelineData() called
    ↓
apiService.getKPIs()
    ↓
[GET /api/kpis] endpoint
    ↓
Filter for pipeline metrics:
  ['won_pipeline', 'created_pipeline', 'active_pipeline']
    ↓
Map to chart data:
  [{
    name: 'Won' | 'Created' | 'Active',
    value: metric_value,
    target: target_value,
    metTarget: boolean
  }]
    ↓
Recharts BarChart renders
    ↓
Shows:
  - 3 bars: Won (green), Created (blue), Active (purple)
  - Target bars (gray, 40% opacity)
  - Custom tooltip with achievement %
```

### 4. Forecast Data Flow
```
ForecastChart mounts
    ↓
fetchForecastData() called
    ↓
apiService.getForecastScenarios(metric='arr', periods=90)
    ↓
[GET /api/forecast/scenarios?metric=arr&periods=90] endpoint
    ↓
Returns:
  {
    most_likely: [{ date, value }],
    best_case: [{ date, value }],
    worst_case: [{ date, value }]
  }
    ↓
Generate mock historical (last 30 days)
    ↓
Combine historical + forecast:
  [
    // Historical
    { date, isForecast: false, actual: value },
    ...
    // Forecast
    { date, isForecast: true, mostLikely, bestCase, worstCase },
    ...
  ]
    ↓
Recharts ComposedChart renders
    ↓
Shows:
  - Historical line (gray, solid)
  - Most Likely line (blue, solid, 3px)
  - Best Case line (green, dashed if not selected)
  - Worst Case line (red, dashed if not selected)
  - Confidence area (blue fill, 10% opacity)
  - Scenario buttons control visibility
```

## State Management

### App.jsx State
```javascript
{
  backendStatus: 'checking' | 'connected' | 'disconnected',
  lastUpdated: Date
}
```

### KPIGrid State
```javascript
{
  kpis: Array<KPI>,  // Transformed KPI objects
  loading: boolean,
  error: string | null
}
```

### ARRTrendChart State
```javascript
{
  data: Array<{ date, arr, growth }>,
  loading: boolean,
  error: string | null
}
```

### PipelineChart State
```javascript
{
  data: Array<{ name, value, target, metTarget }>,
  loading: boolean,
  error: string | null
}
```

### ForecastChart State
```javascript
{
  data: Array<{ date, isForecast, actual?, mostLikely?, bestCase?, worstCase? }>,
  loading: boolean,
  error: string | null,
  activeScenario: 'best_case' | 'most_likely' | 'worst_case',
  showConfidence: boolean,
  metric: 'arr' | 'pipeline' | ...
}
```

## API Service Methods

```javascript
apiService = {
  // Core
  healthCheck: () => GET /
  
  // KPIs
  getKPIs: (startDate?, endDate?) => GET /api/kpis
  
  // Charts
  getChartData: (chartType, startDate?, endDate?) => GET /api/charts/:chartType
  
  // ARR
  getARRForecast: (periods=90) => GET /api/arr/forecast
  getARRSegments: (segmentType='product_genus') => GET /api/arr/segments
  getARRHistory: () => GET /api/arr/history
  
  // Forecasts
  getSingleForecast: (metric, periods=90) => GET /api/forecast
  getAllForecasts: (periods=90) => GET /api/forecasts/all
  getProphetForecast: (segmentBy?) => GET /api/forecast/prophet
  getForecastScenarios: (metric='arr', periods=90) => GET /api/forecast/scenarios
  getWinProbability: () => GET /api/forecast/win-probability
  getForecastAccuracy: () => GET /api/forecast/accuracy
  
  // AI
  getInsights: () => GET /api/insights
  getRecommendations: () => GET /api/recommendations
}
```

## Styling System

### Colors
```javascript
Blue (#3b82f6):   Primary, Most Likely scenario, links
Green (#10b981):  Positive trends, Best Case, success
Red (#ef4444):    Negative trends, Worst Case, errors
Purple (#8b5cf6): Active pipeline
Gray (#6b7280):   Neutral, secondary text
Yellow (#eab308): Warnings, demo mode
```

### Spacing
```javascript
Gap between components:     gap-6 (1.5rem = 24px)
Section spacing:            space-y-8 (2rem = 32px)
Card padding:               p-6 (1.5rem = 24px)
Component margins:          mb-4, mt-4 (1rem = 16px)
```

### Typography
```javascript
H1 (Dashboard title):       text-2xl font-bold
H2 (Section headers):       text-lg font-semibold
H3 (Card titles):           text-xl font-bold
Body text:                  text-sm, text-gray-600
Small text (labels):        text-xs text-gray-500
Values (KPIs, stats):       text-lg font-bold
```

### Responsive Breakpoints
```javascript
Mobile:     < 640px   (sm:)
Tablet:     < 768px   (md:)
Desktop:    < 1024px  (lg:)
Wide:       < 1280px  (xl:)
```

## Component Props

### KPICard
```typescript
interface KPICardProps {
  kpi: {
    name: string;
    value: number;
    target: number;
    previous_value: number;
    format: 'currency' | 'percentage' | 'number';
    unit: '$' | '%' | '#';
  };
  loading?: boolean;
}
```

### KPIGrid
```typescript
// No props - self-contained
```

### ARRTrendChart
```typescript
// No props - self-contained
```

### PipelineChart
```typescript
// No props - self-contained
```

### ForecastChart
```typescript
// No props - self-contained
// Future: Could add props for metric selection
```

## Error Handling Strategy

### Level 1: API Service
- Try API call
- Catch errors, log to console
- Return error to component

### Level 2: Component
- Receive error from API
- Set error state
- Display error message to user
- Provide fallback demo data
- Show "Demo Mode" badge

### Level 3: User Experience
- Error banner with yellow background
- Retry button available
- Graceful degradation (show demo data)
- Clear messaging ("Failed to load, showing demo")

## Performance Optimizations

1. **Lazy Loading**: Could add React.lazy for code splitting
2. **Memoization**: Could use useMemo for expensive calculations
3. **Debouncing**: Could add for date range selectors
4. **Caching**: API responses could be cached (future)
5. **Virtual Scrolling**: If KPI list grows beyond 8 items
6. **Throttling**: Limit API calls on rapid interactions

## Testing Strategy (Future)

### Unit Tests
- Format functions (formatCurrency, formatKPIName)
- Data transformation logic
- State updates

### Integration Tests
- API service methods
- Component data fetching
- Error handling flows

### E2E Tests
- Full dashboard load
- Scenario toggle interactions
- Chart rendering
- Demo mode fallback

---

**Last Updated**: 2026-05-08
**Version**: 1.0.0
