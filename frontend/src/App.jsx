import { useState, useEffect } from 'react';
import { Activity } from 'lucide-react';
import ExecutiveSummary from './components/ExecutiveSummary'
import TimePeriodFilter from './components/TimePeriodFilter'
import FilterPanel from './components/FilterPanel'
import DailyInsights from './components/DailyInsights'
import GraphOfTheDay from './components/GraphOfTheDay'
import KPIGrid from './components/KPIGrid'
import InsightsPanel from './components/InsightsPanel'
import ActionableInsights from './components/ActionableInsights'
import EnhancedKPICard from './components/EnhancedKPICard'
import ARRTrendChart from './components/ARRTrendChart';
import PipelineChart from './components/PipelineChart';
import ForecastChart from './components/ForecastChart';
import { apiService } from './services/api';
import './App.css'

function App() {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [lastUpdated, setLastUpdated] = useState(new Date());  
  const [kpis, setKpis] = useState([])
  const [alerts, setAlerts] = useState([])
  const [kpiInsights, setKpiInsights] = useState({})
  const [selectedPeriod, setSelectedPeriod] = useState('qtd')
  const [filters, setFilters] = useState({ geo: 'All', channel: 'All', product: 'All' })
  const [isLoadingKpis, setIsLoadingKpis] = useState(false)
  
  useEffect(() => {
    checkBackendHealth();
    loadAlerts();
    loadKpis();
    const interval = setInterval(() => {
      setLastUpdated(new Date());
    }, 60000); // Update timestamp every minute

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Load insights for each KPI when KPIs are updated
    if (kpis.length > 0) {
      loadKpiInsights();
    }
  }, [kpis]);

  const checkBackendHealth = async () => {
    try {
      await apiService.healthCheck();
      setBackendStatus('connected');
    } catch (error) {
      console.error('Backend health check failed:', error);
      setBackendStatus('disconnected');
    }
  };

  const loadKpis = async (customFilters = null) => {
    const appliedFilters = customFilters || filters;
    try {
      setIsLoadingKpis(true);
      const kpiData = await apiService.getKPIs(null, null, appliedFilters);
      handleKpisLoaded(kpiData);
    } catch (error) {
      console.error('Failed to load KPIs:', error);
    } finally {
      setIsLoadingKpis(false);
    }
  };

  const handleFilterChange = async (newFilters) => {
    setFilters(newFilters);
    await loadKpis(newFilters);
  };

  const loadAlerts = async () => {
    try {
      const alertsData = await apiService.get('/api/insights/alerts');
      setAlerts(alertsData);
    } catch (error) {
      console.error('Failed to load alerts:', error);
    }
  };

  const loadKpiInsights = async () => {
    const insightsMap = {};
    for (const kpi of kpis) {
      try {
        const insights = await apiService.get(`/api/insights/kpi/${kpi.id}`);
        insightsMap[kpi.id] = insights;
      } catch (error) {
        console.error(`Failed to load insights for ${kpi.id}:`, error);
      }
    }
    setKpiInsights(insightsMap);
  };

  const handlePeriodChange = (period) => {
    setSelectedPeriod(period)
    console.log('Period changed to:', period)
    // In a real app, this would trigger data refetch with new date range
  }

  const handleKpisLoaded = (loadedKpis) => {
    setKpis(loadedKpis)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center space-x-3">
              <div className="bg-blue-600 p-2 rounded-lg">
                <Activity className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Atlas Executive Insights</h1>
                <p className="text-sm text-gray-600">AI-Powered Analytics Dashboard</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <div className="text-right">
                <p className="text-xs text-gray-500">Last updated</p>
                <p className="text-sm font-medium text-gray-700">
                  {lastUpdated.toLocaleTimeString()}
                </p>
              </div>
              <div className={`flex items-center space-x-2 px-3 py-2 rounded-lg ${
                backendStatus === 'connected' 
                  ? 'bg-green-50 text-green-700' 
                  : backendStatus === 'disconnected'
                  ? 'bg-red-50 text-red-700'
                  : 'bg-yellow-50 text-yellow-700'
              }`}>
                <div className={`w-2 h-2 rounded-full ${
                  backendStatus === 'connected' 
                    ? 'bg-green-500' 
                    : backendStatus === 'disconnected'
                    ? 'bg-red-500'
                    : 'bg-yellow-500 animate-pulse'
                }`}></div>
                <span className="text-sm font-medium">
                  {backendStatus === 'connected' ? 'Connected' : 
                   backendStatus === 'disconnected' ? 'Disconnected' : 'Checking...'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content with Sidebar */}
      <div className="flex">
        {/* Sidebar - Filters */}
        <aside className="w-56 flex-shrink-0 px-4 py-8">
          <FilterPanel onFilterChange={handleFilterChange} appliedFilters={filters} />
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-8 max-w-7xl">
          <div className="space-y-6">
            {/* Executive Summary - TOP */}
            <section>
              <ExecutiveSummary kpis={kpis} filters={filters} />
            </section>

            {/* Daily Insights - NEW */}
            <section>
              <DailyInsights kpis={kpis} />
            </section>

            {/* Graph of the Day - NEW */}
            <section>
              <GraphOfTheDay kpis={kpis} />
            </section>

            {/* Enhanced KPI Cards - SMALLER (6 columns) */}
            <section>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">Key Performance Indicators</h2>
                  <p className="text-xs text-gray-600">
                    AI-powered insights for each metric
                    {(filters.geo !== 'All' || filters.channel !== 'All' || filters.product !== 'All') && (
                      <span className="ml-2 text-blue-600 font-medium">• Filtered view</span>
                    )}
                  </p>
                </div>
                {isLoadingKpis && (
                  <div className="text-xs text-blue-600 font-medium flex items-center gap-2">
                    <div className="w-3 h-3 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
                    Updating...
                  </div>
                )}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {kpis.length > 0 ? (
                  kpis.map((kpi) => (
                    <EnhancedKPICard 
                      key={kpi.id} 
                      kpi={kpi} 
                      insights={kpiInsights[kpi.id]}
                      loading={false}
                      compact={true}
                    />
                  ))
                ) : (
                  // Loading placeholders
                  Array.from({ length: 8 }).map((_, idx) => (
                    <EnhancedKPICard key={idx} loading={true} compact={true} />
                  ))
                )}
              </div>
            </section>
          </div>

          {/* Charts and Other Content Below */}
          <div className="space-y-6 mt-8">

          {/* Performance Trends & Analytics */}
          <section>
            <InsightsPanel kpis={kpis} />
          </section>

          {/* Charts Section */}
          <section>
            <div className="mb-4">
              <h2 className="text-lg font-semibold text-gray-900">Performance Analytics</h2>
              <p className="text-sm text-gray-600">Historical trends and pipeline breakdown</p>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ARRTrendChart />
              <PipelineChart />
            </div>
          </section>

          {/* Forecast Section */}
          <section>
            <div className="mb-4">
              <h2 className="text-lg font-semibold text-gray-900">AI-Powered Forecast</h2>
              <p className="text-sm text-gray-600">Prophet ML model predictions with confidence intervals</p>
            </div>
            <ForecastChart />
          </section>

          {/* Footer Info */}
          <section className="bg-white rounded-lg shadow p-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-center">
              <div>
                <p className="text-sm text-gray-600 mb-1">Data Source</p>
                <p className="text-lg font-semibold text-gray-900">Databricks</p>
                <p className="text-xs text-gray-500 mt-1">goto-eureka-mdl-1</p>
              </div>
              <div>
                <p className="text-sm text-gray-600 mb-1">Forecast Model</p>
                <p className="text-lg font-semibold text-gray-900">Prophet AI</p>
                <p className="text-xs text-gray-500 mt-1">Facebook's time series forecasting</p>
              </div>
              <div>
                <p className="text-sm text-gray-600 mb-1">Refresh Frequency</p>
                <p className="text-lg font-semibold text-gray-900">Real-time</p>
                <p className="text-xs text-gray-500 mt-1">Auto-refresh every 5 minutes</p>
              </div>
            </div>
          </section>
        </div>
      </main>
      </div>

      {/* Footer */}
      <footer className="mt-12 bg-white border-t border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center">
            <p className="text-sm text-gray-600">
              © 2026 Atlas Executive Insights. Powered by Prophet AI & Databricks.
            </p>
            <div className="flex space-x-6">
              <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer" 
                 className="text-sm text-blue-600 hover:text-blue-700">
                API Documentation
              </a>
              <a href="#" className="text-sm text-gray-600 hover:text-gray-700">
                Help & Support
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
