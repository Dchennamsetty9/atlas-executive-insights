import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Volume2, VolumeX, Sun, Moon, LayoutDashboard, BarChart3, TrendingUp, Sparkles, SlidersHorizontal, ChevronRight } from 'lucide-react';
import FilterPanel from './components/FilterPanel';
import EnhancedKPICard from './components/EnhancedKPICard';
import ARRTrendChart from './components/ARRTrendChart';
import PipelineChart from './components/PipelineChart';
import ForecastChart from './components/charts/ForecastChart';
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

const DASHBOARD_VIEWS = [
  {
    id: 'overview',
    label: 'Executive Overview',
    description: 'High-level business health, narrative summary, and the most important signals at a glance.',
    icon: LayoutDashboard,
    accent: '#cbd5e1',
    ambient: 'rgba(203,213,225,0.16)',
    glow: 'rgba(203,213,225,0.24)',
    takeawayTitle: 'What to notice now',
    takeawayBody: 'Executive performance, narrative insight, and the highest-value signals are grouped at the top so the story is immediate.',
  },
  {
    id: 'performance',
    label: 'KPI Cockpit',
    description: 'Core KPI cards, the revenue gap waterfall, and detailed performance checks.',
    icon: BarChart3,
    accent: '#f87171',
    ambient: 'rgba(248,113,113,0.16)',
    glow: 'rgba(248,113,113,0.26)',
    takeawayTitle: 'Key takeaway',
    takeawayBody: 'Watch the KPI mix first: if risk rises here, the waterfall below explains where the gap opened and how urgent it is.',
  },
  {
    id: 'forecast',
    label: 'Forecast View',
    description: 'ARR trend, pipeline movement, and the forecast model in one focused workspace.',
    icon: TrendingUp,
    accent: '#f6c453',
    ambient: 'rgba(246,196,83,0.18)',
    glow: 'rgba(246,196,83,0.28)',
    takeawayTitle: 'Key takeaway',
    takeawayBody: 'The forecast is strongest when ARR trend, pipeline movement, and the model point in the same direction.',
  },
  {
    id: 'analytics',
    label: 'Deep Analytics',
    description: 'Segment, coverage, deal band, and large-deal analysis for deeper investigation.',
    icon: Sparkles,
    accent: '#a8b3c5',
    ambient: 'rgba(168,179,197,0.15)',
    glow: 'rgba(168,179,197,0.24)',
    takeawayTitle: 'Key takeaway',
    takeawayBody: 'Use the deeper views to pinpoint where the next lift should come from, then move back to the executive summary.',
  },
];

function AppInner() {
  const { filters, setFilters } = useFilters();
  const [isAnalyzing,   setIsAnalyzing]     = useState(false);
  const [selectedKpi,   setSelectedKpi]     = useState(null);
  const [activeInsightId, setActiveInsightId] = useState(null);
  const [theme,         setTheme]           = useState(() => localStorage.getItem('atlas-theme') || 'dark');
  const [activeSection,  setActiveSection]   = useState(() => localStorage.getItem('atlas-active-section') || 'overview');
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
  useEffect(() => { localStorage.setItem('atlas-active-section', activeSection); }, [activeSection]);

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

  const currentView = DASHBOARD_VIEWS.find(view => view.id === activeSection) || DASHBOARD_VIEWS[0];

  const renderStage = (content) => (
    <div className="premium-stage premium-stage-hero fade-in" style={{ marginTop: 2 }}>
      <div className="premium-stage-shell">
        {content}
      </div>
    </div>
  );

  const renderTakeawayBanner = (view) => (
    <div
      className="premium-takeaway-banner"
      style={{
        '--banner-accent': view.accent,
        marginBottom: 16,
      }}
    >
      <div className="premium-takeaway-banner__rail" />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="premium-takeaway-banner__pill">Key takeaway</div>
        <div className="premium-takeaway-banner__title">{view.takeawayTitle}</div>
        <div className="premium-takeaway-banner__copy">{view.takeawayBody}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0 }}>
        <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.1, color: 'var(--text-muted)' }}>Current view</span>
        <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text-primary)' }}>{view.label}</span>
      </div>
    </div>
  );

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
      <div className="atlas-shell" style={{ display: 'flex', maxWidth: 1600, margin: '0 auto', padding: '0 16px', gap: 16, alignItems: 'flex-start' }}>

        {/* Sidebar rail */}
        <aside className="glass-command-rail" style={{ width: 316, flexShrink: 0, paddingTop: 20, position: 'sticky', top: 56, height: 'calc(100vh - 72px)', overflowY: 'auto', paddingBottom: 20 }}>
          <div className="glass-rail-card" style={{ padding: 14, marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.3, color: 'var(--text-secondary)', marginBottom: 4 }}>
                  Command Rail
                </div>
                <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.15 }}>
                  Pick your view
                </div>
                <div style={{ marginTop: 5, fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  A quick glass panel for switching between overview, KPIs, forecast, and deep analytics.
                </div>
              </div>
              <div style={{
                width: 40, height: 40, borderRadius: 14,
                background: 'linear-gradient(135deg, rgba(59,130,246,0.24), rgba(245,158,11,0.16))',
                border: '1px solid rgba(255,255,255,0.08)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 0 24px rgba(59,130,246,0.16)',
              }}>
                <SlidersHorizontal size={17} color="#dbeafe" />
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, position: 'relative', zIndex: 1 }}>
              {DASHBOARD_VIEWS.map(view => {
                const Icon = view.icon;
                const isActive = activeSection === view.id;
                return (
                  <button
                    key={view.id}
                    className="glass-nav-tile"
                    onClick={() => setActiveSection(view.id)}
                    style={{
                      width: '100%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                      padding: '16px 15px',
                      borderRadius: 20,
                      border: `1px solid ${isActive ? 'rgba(59,130,246,0.35)' : 'rgba(255,255,255,0.08)'}`,
                      background: isActive
                        ? `linear-gradient(135deg, ${view.ambient}, rgba(255,255,255,0.03))`
                        : 'rgba(255,255,255,0.03)',
                      color: 'var(--text-primary)',
                      cursor: 'pointer',
                      boxShadow: isActive ? `0 16px 36px ${view.glow}` : 'none',
                      transition: 'transform 160ms ease, border-color 160ms ease, background 160ms ease, box-shadow 160ms ease',
                      position: 'relative',
                      overflow: 'hidden',
                    }}
                  >
                    <span style={{
                      position: 'absolute', inset: 0,
                      background: `radial-gradient(circle at top right, ${view.ambient}, transparent 62%)`,
                      opacity: isActive ? 1 : 0.55,
                      pointerEvents: 'none',
                    }} />
                    <div style={{ display: 'flex', alignItems: 'center', gap: 11, minWidth: 0, textAlign: 'left' }}>
                      <div style={{
                        width: 40, height: 40, borderRadius: 14,
                        background: isActive ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.05)',
                        border: `1px solid ${isActive ? 'rgba(255,255,255,0.16)' : 'rgba(255,255,255,0.06)'}`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                        boxShadow: isActive ? `0 0 20px ${view.glow}` : 'none',
                      }}>
                        <Icon size={16} color={isActive ? view.accent : 'var(--text-secondary)'} />
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 14, fontWeight: 700, color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                          {view.label}
                        </div>
                        <div style={{ fontSize: 11, lineHeight: 1.45, color: 'var(--text-muted)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {view.description}
                        </div>
                      </div>
                    </div>
                    <ChevronRight size={15} color={isActive ? view.accent : 'var(--text-muted)'} style={{ flexShrink: 0, position: 'relative', zIndex: 1 }} />
                  </button>
                );
              })}
            </div>

            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: 11, color: 'var(--text-secondary)' }}>
              <span>Active view</span>
              <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{currentView.label}</span>
            </div>
          </div>

          <FilterPanel onFilterChange={handleFilterChange} appliedFilters={filters} />
        </aside>

        {/* Main */}
        <main style={{ flex: 1, padding: '20px 0 24px', minWidth: 0, '--view-accent': currentView.accent }}>

          <div className="premium-surface premium-surface-header premium-surface-header-compact" style={{ marginBottom: 12, paddingTop: 10, paddingBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14, flexWrap: 'wrap' }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.3, color: 'var(--text-muted)', marginBottom: 4 }}>
                  Focus mode
                </div>
                <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
                  {currentView.label}
                </h2>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  padding: '8px 12px', borderRadius: 999,
                  background: 'rgba(203,213,225,0.08)',
                  border: '1px solid rgba(203,213,225,0.18)',
                  color: '#e2e8f0', fontSize: 11, fontWeight: 700,
                }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: currentView.accent, boxShadow: `0 0 10px ${currentView.glow}` }} />
                  Live Databricks data
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600 }}>
                  Selected view: <span style={{ color: 'var(--text-primary)' }}>{currentView.label}</span>
                </div>
              </div>
            </div>
          </div>

          {activeSection === 'overview' && (
            renderStage(
              <>
                {renderTakeawayBanner(currentView)}
                <div className="premium-content-row" style={{ marginBottom: 16 }}>
                  <div className="premium-surface premium-surface-hero premium-surface-primary">
                    <BusinessPerformancePanel kpis={kpis} filters={filters} />
                  </div>
                </div>

                <div className="premium-content-row" style={{ marginBottom: 16 }}>
                  <div className="premium-surface premium-surface-banner premium-surface-secondary">
                    <InsightBanner filters={filters} />
                  </div>
                </div>

                <div className="premium-content-row">
                  <div className="premium-surface premium-surface-grid premium-surface-secondary">
                    <InsightPanel kpis={kpis} filters={filters} />
                  </div>
                </div>
              </>
            )
          )}

          {activeSection === 'performance' && (
            renderStage(
              <>
                {renderTakeawayBanner(currentView)}
                <div className="premium-surface premium-surface-header premium-surface-primary" style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.3, color: 'var(--text-muted)', marginBottom: 4 }}>
                        KPI cockpit
                      </div>
                      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>
                        Key Performance Indicators
                      </h2>
                      <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-secondary)' }}>
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
                </div>

                <div className="premium-surface premium-surface-grid premium-surface-primary">
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(212px, 1fr))',
                    gap: 14,
                  }}>
                    {kpiError && kpis.length === 0 ? (
                      <div style={{
                        gridColumn: '1 / -1',
                        padding: '28px 24px',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: 16,
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
                        boxShadow: '0 12px 28px rgba(0,0,0,0.16)',
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
                        <div className="premium-mini-card">
                          <EnhancedKPICard
                            kpi={kpi}
                            insights={kpiInsights[kpi?.id]}
                            loading={!kpi}
                            compact
                            activeInsightId={activeInsightId}
                            onInsightToggle={handleInsightToggle}
                          />
                        </div>
                        {kpi && (
                          <button
                            onClick={() => handleKpiCardClick(kpi)}
                            title="View detailed chart"
                            style={{
                              position: 'absolute', top: 10, right: 10,
                              background: 'rgba(59,130,246,0.15)',
                              border: '1px solid rgba(59,130,246,0.2)',
                              borderRadius: 8, padding: '3px 6px',
                              fontSize: 12, cursor: 'pointer', lineHeight: 1,
                              color: '#3b82f6',
                            }}
                          >📊</button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="premium-surface premium-surface-banner premium-surface-secondary" style={{ marginTop: 16 }}>
                  <ImpactWaterfall filters={filters} />
                </div>
              </>
            )
          )}

          {activeSection === 'forecast' && (
            renderStage(
              <>
                {renderTakeawayBanner(currentView)}
                <div className="premium-surface premium-surface-header premium-surface-secondary premium-surface-header-compact" style={{ marginBottom: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.3, color: 'var(--text-muted)', marginBottom: 4 }}>
                        Forecast view
                      </div>
                      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>
                        ARR Forecast Workspace
                      </h2>
                      <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-secondary)' }}>
                        Trend, pipeline, and forecast signals are organized as premium cards so the eye stays on the story.
                      </p>
                    </div>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 999, background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.16)', color: '#fde68a', fontSize: 11, fontWeight: 700 }}>
                      Forecast mode
                    </div>
                  </div>
                </div>

                <div className="premium-surface premium-surface-hero premium-surface-primary premium-surface-hero-expansive" style={{ marginBottom: 16 }}>
                  <ForecastChart />
                </div>

                <div className="premium-surface premium-surface-grid premium-surface-grid-forecast premium-surface-secondary" style={{ marginBottom: 16 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 16 }}>
                    <div className="premium-chart-card premium-chart-card-forecast premium-chart-card-forecast-wide">
                      <ARRTrendChart kpis={kpis} />
                    </div>
                    <div className="premium-chart-card premium-chart-card-forecast premium-chart-card-forecast-wide">
                      <PipelineChart kpis={kpis} />
                    </div>
                  </div>
                </div>
              </>
            )
          )}

          {activeSection === 'analytics' && (
            renderStage(
              <div className="premium-surface premium-surface-hero premium-surface-hero-expansive premium-surface-primary">
                {renderTakeawayBanner(currentView)}
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.3, color: 'var(--text-muted)', marginBottom: 4 }}>
                    Deep analytics
                  </div>
                  <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>
                    Multi-angle business analysis
                  </h2>
                  <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-secondary)' }}>
                    Explore segment, coverage, deal bands, and large deals in a cleaner editorial layout.
                  </p>
                </div>
                <AnalyticsTabs />
              </div>
            )
          )}

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
