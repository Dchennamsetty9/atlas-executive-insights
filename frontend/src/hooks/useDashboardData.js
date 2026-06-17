import { useState, useEffect, useCallback, useRef } from 'react';
import { apiService } from '../services/api';

export function useDashboardData(filters, play) {
  const [backendStatus, setBackendStatus] = useState('checking');
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const [kpis, setKpis] = useState([]);
  const [kpiInsights, setKpiInsights] = useState({});
  const [isLoadingKpis, setIsLoadingKpis] = useState(false);
  const [kpiError, setKpiError] = useState(null);

  // WebSocket connection for live refresh pushes
  const wsRef = useRef(null);

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

  // ── Parallel insight fetching — Promise.all replaces sequential for-loop ──
  const loadKpiInsights = useCallback(async (kpiList) => {
    const list = kpiList || kpis;
    if (!list.length) return;

    const results = await Promise.allSettled(
      list.map(kpi =>
        apiService.get(`/api/insights/kpi/${kpi.id}`)
          .then(insights => ({ id: kpi.id, insights }))
          .catch(() => ({ id: kpi.id, insights: null }))
      )
    );

    const insightsMap = {};
    for (const result of results) {
      if (result.status === 'fulfilled' && result.value.insights) {
        insightsMap[result.value.id] = result.value.insights;
      }
    }
    setKpiInsights(insightsMap);
  }, [kpis]);

  // ── WebSocket: subscribe to gold-layer refresh events ─────────────────────
  const connectWS = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    try {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${protocol}://${window.location.host}/ws/refresh`);

      ws.onopen = () => console.debug('[Atlas WS] connected');

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'refresh') {
            loadKpis();
          } else if (msg.type === 'ping') {
            ws.send('ping'); // keepalive pong
          }
        } catch { /* ignore malformed */ }
      };

      ws.onclose = () => {
        // Reconnect after 10s if disconnected
        setTimeout(connectWS, 10_000);
      };

      ws.onerror = () => ws.close();
      wsRef.current = ws;
    } catch {
      // WebSocket unavailable — fall back to 15-min polling (existing interval)
    }
  }, [loadKpis]);

  useEffect(() => {
    checkBackendHealth();
    loadKpis();
    connectWS();

    // Fallback polling (15 min) in case WS is not available
    const interval = setInterval(async () => {
      try {
        await apiService.post('/api/cache/refresh', {});
      } catch { /* ignore */ }
      loadKpis();
    }, 15 * 60 * 1000);

    return () => {
      clearInterval(interval);
      wsRef.current?.close();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (kpis.length > 0) {
      loadKpiInsights(kpis);
    }
  }, [kpis]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefreshNow = useCallback(async () => {
    play('click');
    try {
      await apiService.post('/api/cache/refresh', {});
    } catch { /* ignore */ }
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
