import { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/api';

export function useDashboardData(filters, play) {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const [kpis, setKpis] = useState([]);
  const [kpiInsights, setKpiInsights] = useState({});
  const [isLoadingKpis, setIsLoadingKpis] = useState(false);
  const [kpiError, setKpiError] = useState(null);

  const checkBackendHealth = useCallback(async () => {
    try {
      await apiService.healthCheck();
      setBackendStatus('connected');
    } catch {
      setBackendStatus('disconnected');
    }
  }, []);

  const loadKpis = useCallback(async (customFilters = null) => {
    const appliedFilters = customFilters || filters;
    try {
      setIsLoadingKpis(true);
      setKpiError(null);
      const kpiData = await apiService.getKPIs(null, null, appliedFilters);
      setKpis(kpiData);
      setLastRefreshed(new Date());
      play('load');
    } catch (error) {
      console.error('Failed to load KPIs:', error);
      const isTimeout = error?.code === 'ECONNABORTED' || error?.message?.includes('timeout');
      setKpiError(isTimeout ? 'timeout' : 'error');
    } finally {
      setIsLoadingKpis(false);
    }
  }, [filters, play]);

  const loadKpiInsights = useCallback(async () => {
    const insightsMap = {};
    for (const kpi of kpis) {
      try {
        const insights = await apiService.get(`/api/insights/kpi/${kpi.id}`);
        insightsMap[kpi.id] = insights;
      } catch {
        // non-critical
      }
    }
    setKpiInsights(insightsMap);
  }, [kpis]);

  useEffect(() => {
    checkBackendHealth();
    loadKpis();

    const interval = setInterval(async () => {
      try {
        await apiService.post('/api/cache/refresh', {});
      } catch {
        // ignore
      }
      loadKpis();
    }, 15 * 60 * 1000);

    return () => clearInterval(interval);
  }, [checkBackendHealth, loadKpis]);

  useEffect(() => {
    if (kpis.length > 0) {
      loadKpiInsights();
    }
  }, [kpis, loadKpiInsights]);

  const handleRefreshNow = useCallback(async () => {
    play('click');
    try {
      await apiService.post('/api/cache/refresh', {});
    } catch {
      // ignore
    }
    loadKpis();
  }, [loadKpis, play]);

  return {
    backendStatus,
    lastRefreshed,
    kpis,
    kpiInsights,
    isLoadingKpis,
    kpiError,
    loadKpis,
    handleRefreshNow,
  };
}
