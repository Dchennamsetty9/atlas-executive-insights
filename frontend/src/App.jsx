import { useState, useEffect, useCallback, useRef } from 'react';
import { RefreshCw, Volume2, VolumeX, Sun, Moon, Share2 } from 'lucide-react';
import FilterPanel from './components/FilterPanel';
import EnhancedKPICard from './components/EnhancedKPICard';
import ARRTrendChart from './components/ARRTrendChart';
import PipelineChart from './components/PipelineChart';
// TODO(M1.1 V1 retired): ForecastChart removed — replaced by ForecastingPanel (V2 path).
// Deprecated files: frontend/src/components/charts/ForecastChart.jsx, backend/routes/forecast.py
// import ForecastChart from './components/charts/ForecastChart';
import ForecastingPanel from './components/ForecastingPanel';
import AIOrb from './components/ai/AIOrb';
import AIChatPanel from './components/ai/AIChatPanel';
import InsightPanel from './components/dashboard/InsightPanel';
import ImpactWaterfall from './components/dashboard/ImpactWaterfall';
import KPIDetailModal from './components/dashboard/KPIDetailModal';
import BusinessPerformancePanel from './components/dashboard/BusinessPerformancePanel';
import AnalyticsTabs from './components/dashboard/AnalyticsTabs';
import InsightBanner from './components/ai/InsightBanner';
import OnboardingTour from './components/OnboardingTour';
import { useUISound } from './hooks/useUISound';
import { useDashboardData } from './hooks/useDashboardData';
import { useUrlFilters } from './hooks/useUrlFilters';
import { FilterProvider, useFilters } from './contexts/FilterContext';
import NotificationBell from './components/NotificationBell';
import './styles/futuristic-theme.css';
import './App.css'

const MAIN_VIEWS = [
  { id: 'business', label: 'Business Performance', icon: '📈' },
  { id: 'kpi', label: 'Key Performance Indicators', icon: '🎯' },
  { id: 'forecast', label: 'Forecast', icon: '📊' },
  { id: 'extended', label: 'Extended Analysis', icon: '✨' },
];

// ── Quarter-end countdown helper ──────────────────────────────────────────────
function getQuarterCountdown() {
  const now = new Date();
  const month = now.getMonth(); // 0-based
  const quarterEnds = [
    new Date(now.getFullYear(), 2, 31, 23, 59, 59),   // Q1: Mar 31
    new Date(now.getFullYear(), 5, 30, 23, 59, 59),   // Q2: Jun 30
    new Date(now.getFullYear(), 8, 30, 23, 59, 59),   // Q3: Sep 30
    new Date(now.getFullYear(), 11, 31, 23, 59, 59),  // Q4: Dec 31
  ];
  const qIndex = Math.floor(month / 3);
  const qEnd = quarterEnds[qIndex];
  const diffMs = qEnd - now;
  const days = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  const qLabel = `Q${qIndex + 1}`;
  return { days, qLabel, urgent: days <= 14 };
}

function AppInner() {
  const { filters, setFilters } = useFilters();
  const [isAnalyzing,   setIsAnalyzing]     = useState(false);
  const [selectedKpi,   setSelectedKpi]     = useState(null);
  const [activeInsightId, setActiveInsightId] = useState(null);
  const [theme,         setTheme]           = useState(() => localStorage.getItem('atlas-theme') || 'dark');
  const [aiOpen,        setAiOpen]          = useState(false);
  const [activeView,    setActiveView]      = useState('business');
  const [countdown,     setCountdown]       = useState(getQuarterCountdown);
  const [shareCopied,   setShareCopied]     = useState(false);
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

  // URL ↔ filter sync
  useUrlFilters();

  useEffect(() => { localStorage.setItem('atlas-theme', theme); }, [theme]);

  // Refresh countdown every minute
  useEffect(() => {
    const t = setInterval(() => setCountdown(getQuarterCountdown()), 60_000);
    return () => clearInterval(t);
  }, []);

  // Cmd+K / Ctrl+K → open Ask AI
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setAiOpen(o => !o);
        play('open');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [play]);

  const handleShareUrl = () => {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    });
  };

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
            {/* GoTo brand logo SVG */}
            <svg width="22" height="22" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }}>
              <rect width="32" height="32" rx="7" fill="url(#logoGrad)"/>
              <path d="M16 8C11.6 8 8 11.6 8 16s3.6 8 8 8 8-3.6 8-8h-8v-3h11c0 6.1-4.9 11-11 11S5 22.1 5 16 9.9 5 16 5c3 0 5.7 1.2 7.7 3.1l-2.1 2.1C20.2 8.8 18.2 8 16 8z" fill="white"/>
              <defs>
                <linearGradient id="logoGrad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#0066FF"/>
                  <stop offset="1" stopColor="#7c3aed"/>
                </linearGradient>
              </defs>
            </svg>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
              Atlas Executive Insights
            </span>
            <span style={{
              fontSize: 9, fontWeight: 700, color: '#0066FF',
              background: 'rgba(0,102,255,0.1)', border: '1px solid rgba(0,102,255,0.25)',
              borderRadius: 4, padding: '1px 5px', letterSpacing: 0.5,
            }}>GAIM</span>
          </div>

          {/* Quarter-end countdown */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5,
            padding: '3px 10px',
            background: countdown.urgent ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.04)',
            border: `1px solid ${countdown.urgent ? 'rgba(239,68,68,0.35)' : 'rgba(255,255,255,0.07)'}`,
            borderRadius: 6,
            animation: countdown.urgent ? 'borderPulse 2.5s ease-in-out infinite' : 'none',
          }}>
            <span style={{ fontSize: 10, color: countdown.urgent ? '#ef4444' : '#64748b' }}>
              {countdown.urgent ? '🔥' : '⏱'}
            </span>
            <span style={{ fontSize: 10, fontWeight: 700, color: countdown.urgent ? '#ef4444' : '#64748b', fontVariantNumeric: 'tabular-nums' }}>
              {countdown.qLabel} ends in {countdown.days}d
            </span>
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

            {/* Share current filter view */}
            <button
              onClick={handleShareUrl}
              title="Copy link to this filtered view"
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '4px 10px',
                background: shareCopied ? 'rgba(16,185,129,0.1)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${shareCopied ? 'rgba(16,185,129,0.4)' : 'rgba(255,255,255,0.08)'}`,
                borderRadius: 6,
                color: shareCopied ? '#10b981' : '#64748b',
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <Share2 size={11} />
              {shareCopied ? 'Copied!' : 'Share'}
            </button>

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

          {/* Top-level dashboard tabs */}
          <div style={{
            display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16,
            padding: 8, borderRadius: 14,
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            backdropFilter: 'blur(12px)',
          }}>
            {MAIN_VIEWS.map(view => {
              const isActive = activeView === view.id;
              return (
                <button
                  key={view.id}
                  onClick={() => setActiveView(view.id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 7,
                    padding: '10px 14px',
                    borderRadius: 10,
                    border: `1px solid ${isActive ? 'rgba(0,255,136,0.45)' : 'rgba(255,255,255,0.08)'}`,
                    background: isActive
                      ? 'linear-gradient(135deg, rgba(0,255,136,0.15), rgba(59,130,246,0.14))'
                      : 'rgba(255,255,255,0.03)',
                    color: isActive ? '#d1fae5' : '#94a3b8',
                    boxShadow: isActive
                      ? '0 0 14px rgba(0,255,136,0.18), 0 10px 24px rgba(0,0,0,0.18)'
                      : 'none',
                    fontSize: 12,
                    fontWeight: isActive ? 700 : 600,
                    cursor: 'pointer',
                    transition: 'all 0.16s ease',
                  }}
                >
                  <span style={{ fontSize: 13 }}>{view.icon}</span>
                  {view.label}
                </button>
              );
            })}
          </div>

          {activeView === 'business' && (
            <>
              {/* Business Performance summary — status, counts, alert bar */}
              <BusinessPerformancePanel kpis={kpis} filters={filters} />

              {/* AI narrative summary */}
              <InsightBanner filters={filters} />

              {/* AI Hidden Insights cards */}
              <InsightPanel kpis={kpis} filters={filters} />

              {/* Charts section */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                <div className="glass-card" style={{ padding: 16 }}>
                  <ARRTrendChart kpis={kpis} />
                </div>
                <div className="glass-card" style={{ padding: 16 }}>
                  <PipelineChart kpis={kpis} />
                </div>
              </div>
            </>
          )}

          {activeView === 'kpi' && (
            <>
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
            </>
          )}

          {activeView === 'forecast' && (
            <>
              {/* V2 Forecast panel — reads arr_forecast_v2 (scheduled Mondays 03:00 UTC) */}
              <ForecastingPanel />
            </>
          )}

          {activeView === 'extended' && (
            <>
              {/* ── Extended Analytics — 5 tabs ──────────────────────── */}
              <AnalyticsTabs />
            </>
          )}

          {/* Footer */}
          <div style={{
            borderTop: '1px solid var(--border-glass)',
            paddingTop: 16, marginTop: 8,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            fontSize: 11, color: 'var(--text-muted)',
          }}>
            <span>© 2026 Atlas Executive Insights · GAIM · Databricks</span>
            <a href="/docs" target="_blank" rel="noopener noreferrer"
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
      <AIChatPanel
        onAnalyzingChange={setIsAnalyzing}
        externalOpen={aiOpen}
        onOpenChange={setAiOpen}
      />

      {/* ── First-visit onboarding tour ──────────────────────────────── */}
      <OnboardingTour onOpenAI={() => { setAiOpen(true); play('open'); }} />
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
