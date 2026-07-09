/**
 * API service for communicating with the backend
 */

import axios from 'axios'

// Auto-detect API URL:
// - Production (Databricks Apps): Use relative path (same origin)
// - Development: Use relative path (Vite proxy routes /api -> backend)
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,  // 15 s — backend falls back to demo data within 15 s; 120 s caused 2-min blank stalls
  headers: {
    'Content-Type': 'application/json',
  }
})

// Request interceptor for debugging
api.interceptors.request.use(
  config => {
    console.log(`API Request: ${config.method.toUpperCase()} ${config.url}`)
    return config
  },
  error => Promise.reject(error)
)

// Response interceptor for error handling
api.interceptors.response.use(
  response => response.data,
  error => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

/**
 * API Service Methods
 */
export const apiService = {
  // Generic methods
  get: (url, config) => api.get(url, config),
  post: (url, data, config) => api.post(url, data, config),
  put: (url, data, config) => api.put(url, data, config),
  delete: (url, config) => api.delete(url, config),

  // Health check
  healthCheck: () => api.get('/'),

  // Filter endpoints
  getFilters: () => api.get('/api/filters'),

  // KPI endpoints
  getKPIs: (startDate, endDate, filters = {}) => {
    const params = {}
    if (startDate) params.start_date = startDate
    if (endDate) params.end_date = endDate
    if (filters.geo && filters.geo !== 'All') params.geo = filters.geo
    if (filters.channel && filters.channel !== 'All') params.channel = filters.channel
    if (filters.product && filters.product !== 'All') params.product = filters.product
    if (filters.fuel && filters.fuel !== 'All') params.fuel = filters.fuel
    if (filters.purchaseType && filters.purchaseType !== 'All') params.purchase_type = filters.purchaseType
    if (filters.targetVersion && filters.targetVersion !== 'Plan') params.target_version = filters.targetVersion
    if (filters.period && filters.period !== 'QTD') params.period = filters.period
    if (filters.product && filters.product !== 'All') params.product = filters.product
    return api.get('/api/kpis', { params })
  },

  // Chart endpoints
  getChartData: (chartType, startDate, endDate) => {
    const params = {}
    if (startDate) params.start_date = startDate
    if (endDate) params.end_date = endDate
    return api.get(`/api/charts/${chartType}`, { params })
  },

  // ARR endpoints
  getARRForecast: (periods = 90) => 
    api.get('/api/arr/forecast', { params: { periods } }),

  getARRSegments: (segmentType = 'product_genus') =>
    api.get('/api/arr/segments', { params: { segment_type: segmentType } }),

  getARRHistory: () => api.get('/api/arr/history'),

  // Forecast endpoints
  getSingleForecast: (metric, periods = 90) =>
    api.get('/api/forecast', { params: { metric, periods } }),

  getAllForecasts: (periods = 90) =>
    api.get('/api/forecasts/all', { params: { periods } }),

  getProphetForecast: (segmentBy) => {
    const params = {}
    if (segmentBy) params.segment_by = segmentBy
    return api.get('/api/forecast/prophet', { params })
  },

  getForecastScenarios: (metric = 'arr', periods = 90) =>
    api.get('/api/forecast/scenarios', { params: { metric, periods } }),

  getWinProbability: () => api.get('/api/forecast/win-probability'),

  getForecastAccuracy: () => api.get('/api/forecast/accuracy'),

  // AI endpoints
  getInsights: () => api.get('/api/insights'),

  // ── Forecast V2 endpoints — arr_forecast_v2 table (scheduled Mondays 03:00 UTC) ──
  getForecastV2Weekly: (model = 'ensemble', forecastType = 'rolling', product = null, productLine = null, salesMarket = null, year = null, quarter = null) => {
    const params = { model, forecast_type: forecastType };
    if (product && product !== 'All') params.product = product;
    if (productLine && productLine !== 'All') params.product_line = productLine;
    if (salesMarket && salesMarket !== 'All') params.sales_market = salesMarket;
    if (year) params.year = year;
    if (quarter) params.quarter = quarter;
    return api.get('/api/forecast/v2/weekly', { params });
  },
  getForecastV2YTD: (forecastType = 'rolling', product = null, productLine = null, salesMarket = null, year = null, quarter = null, model = 'ensemble') => {
    const params = { forecast_type: forecastType, model };
    if (product && product !== 'All') params.product = product;
    if (productLine && productLine !== 'All') params.product_line = productLine;
    if (salesMarket && salesMarket !== 'All') params.sales_market = salesMarket;
    if (year) params.year = year;
    if (quarter) params.quarter = quarter;
    return api.get('/api/forecast/v2/ytd', { params });
  },
  getForecastV2Historical: (product = null, productLine = null, salesMarket = null, year = null) => {
    const params = {};
    if (product && product !== 'All') params.product = product;
    if (productLine && productLine !== 'All') params.product_line = productLine;
    if (salesMarket && salesMarket !== 'All') params.sales_market = salesMarket;
    // Omit year to get backend 3-year rolling window for Multi-Year charts;
    // pass year explicitly only when a specific year's trend is needed.
    if (year) params.year = year;
    return api.get('/api/forecast/v2/historical', { params });
  },
  getForecastV2ByProduct: (model = 'ensemble', forecastType = 'rolling', product = null, productLine = null, salesMarket = null, year = null, quarter = null) => {
    const params = { model, forecast_type: forecastType };
    if (product && product !== 'All') params.product = product;
    if (productLine && productLine !== 'All') params.product_line = productLine;
    if (salesMarket && salesMarket !== 'All') params.sales_market = salesMarket;
    if (year) params.year = year;
    if (quarter) params.quarter = quarter;
    return api.get('/api/forecast/v2/by-product', { params });
  },
  getForecastV2Monthly: (forecastType = 'rolling', product = null, productLine = null, salesMarket = null, year = null, quarter = null, model = 'ensemble') => {
    const params = { forecast_type: forecastType, model };
    if (product && product !== 'All') params.product = product;
    if (productLine && productLine !== 'All') params.product_line = productLine;
    if (salesMarket && salesMarket !== 'All') params.sales_market = salesMarket;
    if (year) params.year = year;
    if (quarter) params.quarter = quarter;
    return api.get('/api/forecast/v2/monthly', { params });
  },
  getForecastV2Leaderboard: () => api.get('/api/forecast/v2/leaderboard'),
  getForecastV2Models: () => api.get('/api/forecast/v2/models'),
  getForecastV2Freshness: () => api.get('/api/forecast/v2/freshness'),
  getForecastV2Confidence: (model = 'ensemble', year = null, quarter = null) => {
    const params = { model }
    if (year) params.year = year
    if (quarter) params.quarter = quarter
    return api.get('/api/forecast/v2/confidence', { params })
  },
  getForecastV2DriverBridge: (year = null, quarter = null, model = 'ensemble') => {
    const params = { model }
    if (year) params.year = year
    if (quarter) params.quarter = quarter
    return api.get('/api/forecast/v2/driver-bridge', { params })
  },
  getForecastV2RiskRadar: (forecastType = 'rolling', year = null, quarter = null, limit = 20, model = 'ensemble') => {
    const params = { forecast_type: forecastType, limit, model }
    if (year) params.year = year
    if (quarter) params.quarter = quarter
    return api.get('/api/forecast/v2/risk-radar', { params })
  },
  getForecastV2MeetingMode: (model = 'ensemble', year = null, quarter = null) => {
    const params = { model }
    if (year) params.year = year
    if (quarter) params.quarter = quarter
    return api.get('/api/forecast/v2/meeting-mode', { params })
  },
  getForecastV2GovernanceLog: () => api.get('/api/forecast/v2/governance/log'),
  createForecastV2GovernanceLog: (payload) => api.post('/api/forecast/v2/governance/log', payload),

  getForecastV2ConfidenceBands: (forecastType = 'rolling', productLine = null, year = null, quarter = null, model = 'ensemble') => {
    const params = { forecast_type: forecastType, model };
    if (productLine && productLine !== 'All') params.product_line = productLine;
    if (year) params.year = year;
    if (quarter) params.quarter = quarter;
    return api.get('/api/forecast/v2/confidence-bands', { params });
  },

  // Action command center
  getActions: (status = null) => {
    const params = {}
    if (status) params.status = status
    return api.get('/api/actions', { params })
  },
  createAction: (payload) => api.post('/api/actions', payload),
  updateActionStatus: (actionId, status, owner = null) => api.patch(`/api/actions/${actionId}/status`, { status, owner }),
  updateActionMeta: (actionId, payload) => api.patch(`/api/actions/${actionId}/meta`, payload),
  deleteAction: (actionId) => api.delete(`/api/actions/${actionId}`),

  getForecastIntelligence: (metric = 'won_pipeline', model = 'prophet', productLine = null) => {
    const params = { metric, model };
    if (productLine && productLine !== 'All') params.product_line = productLine;
    return api.get('/api/forecast/intelligence', { params });
  },

  // v2 intelligence — reads from Delta table arr_forecast_insights (SP-accessible via all_mdl_ro)
  getForecastV2Intelligence: () => api.get('/api/forecast/v2/intelligence'),

  getRecommendations: () => api.get('/api/recommendations'),
}

// Legacy function for backwards compatibility
export const fetchKPIs = async (startDate, endDate) => {
  try {
    return await apiService.getKPIs(startDate, endDate)
  } catch (error) {
    console.error('Failed to fetch KPIs:', error)
    return getMockKPIs()
  }
}

function getMockKPIs() {
  return [
    { metric_name: 'won_pipeline', metric_value: 2450000, target_value: 2000000, previous_period_value: 2145000 },
    { metric_name: 'won_volume', metric_value: 78, target_value: 70, previous_period_value: 72 },
    { metric_name: 'ads', metric_value: 31410, target_value: 28000, previous_period_value: 29790 },
    { metric_name: 'opps_created', metric_value: 245, target_value: 220, previous_period_value: 230 },
    { metric_name: 'created_pipeline', metric_value: 8500000, target_value: 7500000, previous_period_value: 7800000 },
    { metric_name: 'active_pipeline', metric_value: 12000000, target_value: 10000000, previous_period_value: 11400000 },
    { metric_name: 'close_rate', metric_value: 31.8, target_value: 30.0, previous_period_value: 31.3 },
    { metric_name: 'coverage', metric_value: 320, target_value: 300, previous_period_value: 310 },
  ]
}

export default api
