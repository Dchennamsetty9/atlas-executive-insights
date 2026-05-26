import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Volume2, VolumeX, Sun, Moon } from 'lucide-react';
import FilterPanel from './components/FilterPanel';
import EnhancedKPICard from './components/EnhancedKPICard';
import ARRTrendChart from './components/ARRTrendChart';
import PipelineChart from './components/PipelineChart';
import ForecastChart from './components/charts/ForecastChart';
import ForecastIntelligence from './components/charts/ForecastIntelligence';
import AIOrb from './components/ai/AIOrb';
import AIChatPanel from './components/ai/AIChatPanel';
import InsightPanel from './components/dashboard/InsightPanel';
import ImpactWaterfall from './components/dashboard/ImpactWaterfall';
import KPIDetailModal from './components/dashboard/KPIDetailModal';
import BusinessPerformancePanel from './components/dashboard/BusinessPerformancePanel';
import AnalyticsTabs from './components/dashboard/AnalyticsTabs';
import InsightBanner from './components/ai/InsightBanner';
import { useUISound } from './hooks/useUISound';
import { useDashboardData } from './hooks/useDashboardData';
import { FilterProvider, useFilters } from './contexts/FilterContext';
import NotificationBell from './components/NotificationBell';
import './styles/futuristic-theme.css';
import './App.css'

function AppInner() {
  const { filters, setFilters } = useFilters();
  const [isAnalyzing,   setIsAnalyzing]     = useState(false);
  const [selectedKpi,   setSelectedKpi]     = useState(null);
  const [activeInsightId, setActiveInsightId] = useState(null);
  const [theme,         setTheme]           = useState(() => localStorage.getItem('atlas-theme') || 'dark');
  const { enabled: soundEnabled, toggle: toggleSound, play } = useUISound();
  const {
    backendStatus,
    lastRefreshed,
    kpis,
    kpiInsights,
    isLoadingKpis,
    kpiError,
    loadKpis,
    handleRefreshNow,
  } = useDashboardData(filters, play);

  useEffect(() => { localStorage.setItem('atlas-theme', theme); }, [theme]);

  const handleFilterChange = async (newFilters) => {
    setFilters(newFilters);
    await loadKpis(newFilters);
  };

  // Accordion: close current card if same id clicked, otherwise open new one
  const handleInsightToggle = useCallback((kpiId) => {
    setActiveInsightId(prev => prev === kpiId ? null : kpiId);
  }, []);

  const handleKpiCardClick = (kpi) => {
    play('open');
    setSelectedKpi(kpi);
  };

  return (
    <div data-theme={theme} style={{ minHeight: '100vh', background: 'var(--bg-base)', color: 'var(--text-primary)' }}>

      {/* ── Header ───────────────────────────────────────────────────── */}
      <header style={{
        background: 'var(--bg-surface)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border-glass)',
        padding: '0 20px',
        height: 44,
        position: 'sticky',
        top: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        boxShadow: '0 2px 16px rgba(0,0,0,0.12)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, maxWidth: 1600, margin: '0 auto', width: '100%' }}>

          {/* Logo + Title */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            <div style={{
              width: 24, height: 24, borderRadius: 6,
              background: 'linear-gradient(135deg, #1d4ed8, #7c3aed)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, boxShadow: '0 0 10px rgba(59,130,246,0.35)',
            }}>⬡</div>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
              Atlas Executive Insights
            </span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>GAIM</span>
          </div>

          {/* Spacer */}
          <div style={{ flex: 1 }} />

          {/* Right controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>

            {/* Last refreshed — prominent data freshness indicator */}
            {lastRefreshed && (
              <span style={{
                fontSize: 10, color: '#64748b',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.07)',
                borderRadius: 6, padding: '3px 8px',
                fontVariantNumeric: 'tabular-nums',
              }}>
                Data as of {lastRefreshed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}

            {/* Notification bell */}
            <NotificationBell />

            {/* Refresh button */}
            <button
              onClick={handleRefreshNow}
              disabled={isLoadingKpis}
              title="Refresh data"
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '4px 10px',
                background: 'rgba(59,130,246,0.08)',
                border: '1px solid rgba(59,130,246,0.2)',
                borderRadius: 6, color: '#3b82f6',
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
                opacity: isLoadingKpis ? 0.5 : 1,
              }}
            >
              <RefreshCw size={11} style={{ animation: isLoadingKpis ? 'spin 1s linear infinite' : 'none' }} />
              Refresh
            </button>

            {/* Sound toggle */}
            <button
              onClick={toggleSound}
              title={soundEnabled ? 'Mute UI sounds' : 'Enable UI sounds'}
              style={{
                background: 'transparent', border: 'none',
                color: soundEnabled ? '#3b82f6' : '#334155',
                width: 28, height: 28, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                borderRadius: 6,
              }}
            >
              {soundEnabled ? <Volume2 size={13} /> : <VolumeX size={13} />}
            </button>

            {/* Theme toggle */}
            <button
              onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              style={{
                background: 'transparent', border: 'none',
                color: theme === 'dark' ? '#f59e0b' : '#334155',
                width: 28, height: 28, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                borderRadius: 6, transition: 'color 0.15s',
              }}
            >
              {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
            </button>

            {/* Status dot */}
            <span style={{
              width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
              background: backendStatus === 'connected' ? '#10b981'
                        : backendStatus === 'disconnected' ? '#ef4444' : '#f59e0b',
              boxShadow: backendStatus === 'connected' ? '0 0 5px #10b981' : 'none',
              animation: backendStatus === 'checking' ? 'pulse 1.5s ease-in-out infinite' : 'none',
            }} />

            {/* AIOrb */}
            <AIOrb kpis={kpis} backendStatus={backendStatus} isAnalyzing={isAnalyzing} />
          </div>
        </div>
      </header>

      {/* ── Body ─────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', maxWidth: 1600, margin: '0 auto', padding: '0 16px' }}>

        {/* Sidebar */}
        <aside style={{ width: 210, flexShrink: 0, paddingTop: 24 }}>
          <FilterPanel onFilterChange={handleFilterChange} appliedFilters={filters} />
        </aside>

        {/* Main */}
        <main style={{ flex: 1, padding: '24px 0 24px 20px', minWidth: 0 }}>

          {/* Business Performance summary — status, counts, alert bar */}
          <BusinessPerformancePanel kpis={kpis} filters={filters} />

          {/* AI narrative summary */}
          <InsightBanner filters={filters} />

          {/* AI Hidden Insights cards */}
          <InsightPanel kpis={kpis} filters={filters} />

          {/* KPI Section header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                Key Performance Indicators
              </h2>
              <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-secondary)' }}>
                Click{' '}
                <span style={{ fontSize: 12 }}>📊</span>
                {' '}on any card for detailed charts
                {(filters.geo !== 'All' || filters.channel !== 'All' || filters.product !== 'All') && (
                  <span style={{ marginLeft: 8, color: '#3b82f6', fontWeight: 600 }}>• Filtered</span>
                )}
              </p>
            </div>
            {isLoadingKpis && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#3b82f6' }}>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  border: '2px solid #3b82f6', borderTopColor: 'transparent',
                  animation: 'spin 0.7s linear infinite',
                }} />
                Updating…
              </div>
            )}
          </div>

          {/* KPI Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 12, marginBottom: 28,
          }}>
            {kpiError && kpis.length === 0 ? (
              <div style={{
                gridColumn: '1 / -1',
                padding: '28px 24px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-glass)',
                borderRadius: 12,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
              }}>
                <div>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {kpiError === 'timeout'
                      ? '⏳ Databricks warehouse is warming up…'
                      : '⚠️ Could not load KPI data'}
                  </p>
                  <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
                    {kpiError === 'timeout'
                      ? 'Cold starts can take 60–90 s. Data will appear once the warehouse is ready.'
                      : 'Check that the backend is running and DATABRICKS_TOKEN is set.'}
                  </p>
                </div>
                <button onClick={() => loadKpis()} style={{
                  padding: '7px 16px', fontSize: 12, fontWeight: 600,
                  background: 'rgba(59,130,246,0.12)', color: '#3b82f6',
                  border: '1px solid rgba(59,130,246,0.35)', borderRadius: 8, cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}>
                  Retry
                </button>
              </div>
            ) : (kpis.length > 0 ? kpis : Array.from({ length: 8 })).map((kpi, idx) => (
              <div key={kpi?.id ?? idx} style={{ position: 'relative' }}>
                <EnhancedKPICard
                  kpi={kpi}
                  insights={kpiInsights[kpi?.id]}
                  loading={!kpi}
                  compact
                  activeInsightId={activeInsightId}
                  onInsightToggle={handleInsightToggle}
                />
                {/* Detail modal trigger */}
                {kpi && (
                  <button
                    onClick={() => handleKpiCardClick(kpi)}
                    title="View detailed chart"
                    style={{
                      position: 'absolute', top: 8, right: 8,
                      background: 'rgba(59,130,246,0.15)',
                      border: '1px solid rgba(59,130,246,0.2)',
                      borderRadius: 6, padding: '2px 5px',
                      fontSize: 12, cursor: 'pointer', lineHeight: 1,
                      color: '#3b82f6',
                    }}
                  >📊</button>
                )}
              </div>
            ))}
          </div>

          {/* Revenue gap decomposition waterfall — only renders when gap exists */}
          <ImpactWaterfall filters={filters} />

          {/* Charts section */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div className="glass-card" style={{ padding: 16 }}>
              <ARRTrendChart kpis={kpis} />
            </div>
            <div className="glass-card" style={{ padding: 16 }}>
              <PipelineChart kpis={kpis} />
            </div>
          </div>
          {/* Forecast + Forecast Intelligence (embedded within ForecastChart) */}
          <ForecastChart />

          {/* ── Extended Analytics — 5 tabs ──────────────────────── */}
          <AnalyticsTabs />

          {/* Footer */}
          <div style={{
            borderTop: '1px solid var(--border-glass)',
            paddingTop: 16, marginTop: 8,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            fontSize: 11, color: 'var(--text-muted)',
          }}>
            <span>© 2026 Atlas Executive Insights · GAIM · Databricks</span>
            <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer"
               style={{ color: '#3b82f6', textDecoration: 'none' }}>
              API Docs
            </a>
          </div>
        </main>
      </div>

      {/* ── KPI Detail Modal ─────────────────────────────────────────── */}
      {selectedKpi && (
        <KPIDetailModal kpi={selectedKpi} onClose={() => setSelectedKpi(null)} />
      )}

      {/* ── Floating AI Chat Panel ───────────────────────────────────── */}
      <AIChatPanel onAnalyzingChange={setIsAnalyzing} />
    </div>
  );
}

function App() {
  return (
    <FilterProvider>
      <AppInner />
    </FilterProvider>
  );
}

export default App;
