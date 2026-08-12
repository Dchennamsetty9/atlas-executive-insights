import { useState, useEffect, useCallback } from 'react';

// ── Demo/fallback payload — shown when backend is unavailable ─────────────────
const _demoPayload = () => ({
  run_date:             '—',
  momentum:             'STABLE',
  risk_level:           'MODERATE RISK',
  model_confidence:     72,
  best_model:           'Prophet',
  best_mape:            19.4,
  forecast_most_likely: 17_200_000,
  forecast_low:         14_620_000,
  forecast_high:        19_780_000,
  upside:               '+$2.6M',
  downside:             '-$2.6M',
  narrative: 'Prophet projects ~$17.2M in Growth ARR over the next 13 weeks (UCC + ITSG). ' +
             'Scenario range: $14.6M–$19.8M. Connect to Databricks to see live figures.',
  key_drivers: [
    'Q2 QE surge (weeks 11–13) drives ~35% of quarterly ARR',
    'UCC accounts for ~60% of Growth bookings by value',
    'Pipeline created 4–8 weeks ago is the strongest leading indicator',
  ],
  executive_actions: [
    'Prioritize QE pipeline velocity — week 11–13 close rates are 2× early-quarter',
    'Review ITSG deals with push_counter > 2 (high slippage risk)',
    'Refresh forecast after each week closes for latest Prophet output',
  ],
  downside_risks: [
    'Q3 seasonal decline typically follows Q2 QE surge — plan for -15% reversion',
    'High deal slippage in ITSG segment may compress Q2 close',
    'Growth-only filter; renewal uplift not included in these figures',
  ],
  upside_opportunities: [
    'Best-case scenario: $19.8M (+$2.6M vs most likely)',
    'Marketing-influenced pipeline lag ~4–8 weeks — strong creation = near-term upside',
    'APAC/EMEA expansion may outperform NA trend if headcount ramp holds',
  ],
});

const TREND_META = {
  STABLE: { label: 'STABLE', color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  ACCELERATING: { label: 'ACCELERATING', color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  DECELERATING: { label: 'DECELERATING', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
};

const RISK_META = {
  'LOW RISK': { label: 'LOW RISK', color: '#10b981', bg: 'rgba(16,185,129,0.1)' },
  'MODERATE RISK': { label: 'MODERATE RISK', color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
  'HIGH RISK': { label: 'HIGH RISK', color: '#ef4444', bg: 'rgba(239,68,68,0.1)' },
};

const fmtUSD = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
};

const listOrEmpty = (v) => (Array.isArray(v) ? v : []);

const SectionCard = ({ title, icon, children, accentColor = '#3b82f6' }) => (
  <div style={{
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-glass)',
    borderRadius: 10,
    padding: '16px 18px',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontSize: 16 }}>{icon}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color: accentColor, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
        {title}
      </span>
    </div>
    {children}
  </div>
);

const Bullet = ({ children, color = '#94a3b8' }) => (
  <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
    <span style={{ color, marginTop: 2, flexShrink: 0 }}>▸</span>
    <span style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{children}</span>
  </div>
);

const SkeletonRow = () => (
  <div style={{ height: 14, borderRadius: 6, background: 'var(--bg-glass)', animation: 'pulse 1.5s ease-in-out infinite', marginBottom: 8 }} />
);

const ForecastIntelligence = ({ selectedModel, onInsightsLoaded }) => {
  // Pre-populate with demo so the UI never shows blank cards on mount
  const [data, setData] = useState(_demoPayload);
  const [source, setSource] = useState('demo');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/forecast/insights');
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try { const j = await res.json(); msg = j?.detail || j?.error || msg; } catch (_) {}
        throw new Error(msg);
      }
      const json = await res.json();
      const src  = json.source ?? 'demo';
      // Backend wraps payload in {source, data:{...}}.
      // If data key is missing (flat response from older deploy), use top-level object
      // but remap legacy field names to what this component reads.
      let d = json.data ?? null;
      if (!d && json.forecast_most_likely != null) {
        // Flat legacy shape — remap to expected shape
        d = {
          run_date:             json.run_date,
          momentum:             json.momentum ?? (json.trend_status ? json.trend_status.toUpperCase() : 'STABLE'),
          risk_level:           json.risk_level ?? 'MODERATE RISK',
          model_confidence:     json.model_confidence != null
                                  ? (json.model_confidence <= 1 ? Math.round(json.model_confidence * 100) : json.model_confidence)
                                  : 72,
          best_model:           json.best_model ?? json.model_name ?? 'Prophet',
          best_mape:            json.best_mape ?? json.mape ?? 19.4,
          forecast_most_likely: json.forecast_most_likely ?? json.forecast_90d?.most_likely,
          forecast_low:         json.forecast_low ?? json.forecast_90d?.worst_case,
          forecast_high:        json.forecast_high ?? json.forecast_90d?.best_case,
          upside:               json.upside ?? (json.upside_dollar != null ? `+$${(json.upside_dollar/1e6).toFixed(1)}M` : '—'),
          downside:             json.downside ?? (json.downside_dollar != null ? `$${(json.downside_dollar/1e6).toFixed(1)}M` : '—'),
          narrative:            json.narrative ?? json.description ?? '',
          key_drivers:          json.key_drivers ?? [],
          executive_actions:    json.executive_actions ?? [],
          downside_risks:       json.downside_risks ?? [],
          upside_opportunities: json.upside_opportunities ?? [],
        };
      }
      d = d ?? _demoPayload();
      setSource(src);
      setData(d);
      if (onInsightsLoaded) onInsightsLoaded(d);
    } catch (e) {
      // Network / parse error — show error banner but still render demo data
      setError(e.message);
      const demo = _demoPayload();
      setData(demo);
      setSource('demo');
      if (onInsightsLoaded) onInsightsLoaded(demo);
    } finally {
      setLoading(false);
    }
  }, [onInsightsLoaded]);

  useEffect(() => {
    load();
  }, [load]);

  const trendMeta = TREND_META[String(data?.momentum || 'STABLE').toUpperCase()] || TREND_META.STABLE;
  const riskMeta = RISK_META[String(data?.risk_level || 'MODERATE RISK').toUpperCase()] || RISK_META['MODERATE RISK'];

  const confidencePct = data?.model_confidence != null ? Number(data.model_confidence) : null;
  const confidenceColor = confidencePct == null ? '#94a3b8' : confidencePct >= 80 ? '#10b981' : confidencePct >= 60 ? '#f59e0b' : '#ef4444';

  return (
    <div style={{ fontFamily: 'Inter, system-ui, sans-serif', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Forecast Intelligence</span>
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.08em',
              color: '#3b82f6',
              background: 'rgba(59,130,246,0.1)',
              padding: '2px 7px',
              borderRadius: 20,
            }}>
              AI
            </span>
          </div>
          <span style={{ fontSize: 11, color: '#64748b' }}>
            using <span style={{ color: '#94a3b8' }}>{data?.best_model || selectedModel || 'Ensemble (70/30)'}</span>
          </span>
        </div>

        <div style={{ display: 'flex', gap: 20 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981', letterSpacing: '0.06em', marginBottom: 2 }}>UPSIDE</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: '#10b981', lineHeight: 1 }}>
              {loading ? '—' : (data?.upside || '—')}
            </div>
          </div>
          <div style={{ width: 1, background: 'var(--border-glass)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', letterSpacing: '0.06em', marginBottom: 2 }}>DOWNSIDE</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: '#ef4444', lineHeight: 1 }}>
              {loading ? '—' : (data?.downside || '—')}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div style={{
          background: 'rgba(245,158,11,0.08)',
          border: '1px solid rgba(245,158,11,0.2)',
          borderRadius: 8,
          padding: '8px 14px',
          fontSize: 11,
          color: '#f59e0b',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}>
          <span>⚠</span>
          <span>Live data unavailable — showing demo forecast. ({error})</span>
        </div>
      )}

      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-glass)',
        borderRadius: 12,
        padding: '18px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {loading ? (
              <div style={{ width: 100, height: 26, borderRadius: 20, background: 'var(--bg-glass)', animation: 'pulse 1.5s infinite' }} />
            ) : (
              <>
                <span style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: '0.08em',
                  color: trendMeta.color,
                  background: trendMeta.bg,
                  padding: '4px 12px',
                  borderRadius: 20,
                  border: `1px solid ${trendMeta.color}40`,
                }}>
                  {trendMeta.label}
                </span>
                <span style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: '0.08em',
                  color: riskMeta.color,
                  background: riskMeta.bg,
                  padding: '4px 12px',
                  borderRadius: 20,
                  border: `1px solid ${riskMeta.color}40`,
                }}>
                  {riskMeta.label}
                </span>
              </>
            )}
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: '#64748b', letterSpacing: '0.06em', marginBottom: 1 }}>MODEL CONFIDENCE</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: confidenceColor, lineHeight: 1 }}>
              {loading ? '—' : confidencePct != null ? `${confidencePct}%` : '—'}
            </div>
          </div>
        </div>

        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {loading ? <><SkeletonRow /><SkeletonRow /></> : data?.narrative}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div style={{
            background: 'rgba(16,185,129,0.06)',
            border: '1px solid rgba(16,185,129,0.2)',
            borderRadius: 8,
            padding: '12px 14px',
          }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981', letterSpacing: '0.06em', marginBottom: 4 }}>BEST CASE</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#10b981' }}>
              {loading ? '—' : fmtUSD(data?.forecast_high)}
            </div>
          </div>
          <div style={{
            background: 'rgba(239,68,68,0.06)',
            border: '1px solid rgba(239,68,68,0.2)',
            borderRadius: 8,
            padding: '12px 14px',
          }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', letterSpacing: '0.06em', marginBottom: 4 }}>WORST CASE</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#ef4444' }}>
              {loading ? '—' : fmtUSD(data?.forecast_low)}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '8px 0', borderTop: '1px solid var(--border-glass)' }}>
          <span style={{ fontSize: 11, color: '#64748b', letterSpacing: '0.06em' }}>MOST LIKELY</span>
          <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)' }}>
            {loading ? '—' : fmtUSD(data?.forecast_most_likely)}
          </span>
          <span style={{ fontSize: 11, color: '#64748b', background: 'var(--bg-glass)', padding: '2px 8px', borderRadius: 10 }}>
            MAPE {data?.best_mape != null ? `${Number(data.best_mape).toFixed(1)}%` : '—'}
          </span>
          {source === 'live' ? (
            <span style={{ fontSize: 11, color: '#10b981', background: 'rgba(16,185,129,0.1)', padding: '2px 8px', borderRadius: 10 }}>
              LIVE
            </span>
          ) : (
            <span style={{ fontSize: 11, color: '#f59e0b', background: 'rgba(245,158,11,0.1)', padding: '2px 8px', borderRadius: 10 }}>
              DEMO
            </span>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
        <SectionCard title="Key Drivers" icon="✅" accentColor="#10b981">
          {loading
            ? [1, 2, 3].map((i) => <SkeletonRow key={i} />)
            : listOrEmpty(data?.key_drivers).map((d, i) => <Bullet key={i} color="#10b981">{d}</Bullet>)}
        </SectionCard>

        <SectionCard title="Executive Actions" icon="⚙️" accentColor="#3b82f6">
          {loading
            ? [1, 2, 3].map((i) => <SkeletonRow key={i} />)
            : listOrEmpty(data?.executive_actions).map((a, i) => <Bullet key={i} color="#3b82f6">{a}</Bullet>)}
        </SectionCard>

        <SectionCard title="Downside Risks" icon="⚠️" accentColor="#ef4444">
          {loading
            ? [1, 2, 3].map((i) => <SkeletonRow key={i} />)
            : listOrEmpty(data?.downside_risks).map((r, i) => <Bullet key={i} color="#ef4444">{r}</Bullet>)}
        </SectionCard>

        <SectionCard title="Upside Opportunities" icon="📈" accentColor="#10b981">
          {loading
            ? [1, 2, 3].map((i) => <SkeletonRow key={i} />)
            : listOrEmpty(data?.upside_opportunities).map((o, i) => <Bullet key={i} color="#10b981">{o}</Bullet>)}
        </SectionCard>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0' }}>
        <span style={{ fontSize: 11, color: '#475569' }}>
          Last updated: {data?.run_date || '—'}
        </span>
        <button
          onClick={load}
          disabled={loading}
          style={{
            background: 'var(--bg-glass)',
            border: '1px solid var(--border-glass)',
            borderRadius: 6,
            color: 'var(--text-secondary)',
            fontSize: 11,
            padding: '4px 12px',
            cursor: loading ? 'default' : 'pointer',
            opacity: loading ? 0.5 : 1,
          }}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
    </div>
  );
};

export default ForecastIntelligence;
