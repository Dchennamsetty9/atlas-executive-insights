/**
 * ForecastIntelligence — Executive-level AI forecast intelligence panel.
 *
 * Layout:
 *   Header: metric selector · model selector | Upside $ · Downside $
 *   Trend card: trend badge · risk badge · confidence · best/worst case
 *   Description paragraph
 *   2×2 grid: Key Drivers · Executive Actions · Downside Risks · Upside Opportunities
 *
 * Calls GET /api/forecast/intelligence?metric=&model=
 * Respects data-theme (dark / light) via CSS variables.
 */

import { useState, useEffect, useCallback } from 'react';

// ── Constants ─────────────────────────────────────────────────────────────────
const METRICS = [
  { key: 'won_pipeline',     label: 'Won Pipeline' },
  { key: 'active_pipeline',  label: 'Active Pipeline' },
  { key: 'created_pipeline', label: 'Created Pipeline' },
  { key: 'win_rate',         label: 'Win Rate' },
];

const MODEL_OPTIONS = [
  { key: 'auto',             label: 'Auto (Best Fit)' },
  { key: 'holt_winters',     label: 'Holt-Winters' },
  { key: 'prophet',          label: 'Prophet' },
  { key: 'arima',            label: 'ARIMA' },
  { key: 'triple_smoothing', label: 'Triple Smoothing' },
  { key: 'linear_seasonal',  label: 'Linear + Seasonal' },
  { key: 'databricks_ai',    label: 'Databricks AI' },
];

const TREND_META = {
  stable:       { label: 'STABLE',       color: '#3b82f6', bg: 'rgba(59,130,246,0.12)'  },
  accelerating: { label: 'ACCELERATING', color: '#10b981', bg: 'rgba(16,185,129,0.12)'  },
  decelerating: { label: 'DECELERATING', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
  volatile:     { label: 'VOLATILE',     color: '#ef4444', bg: 'rgba(239,68,68,0.12)'   },
};

const RISK_META = {
  low:      { label: 'LOW RISK',      color: '#10b981', bg: 'rgba(16,185,129,0.1)'  },
  moderate: { label: 'MODERATE RISK', color: '#f59e0b', bg: 'rgba(245,158,11,0.1)'  },
  high:     { label: 'HIGH RISK',     color: '#ef4444', bg: 'rgba(239,68,68,0.1)'   },
};

const fmtUSD = (v) => {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
};

const fmtDelta = (v) => {
  if (v == null) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${fmtUSD(v)}`;
};

// ── Sub-components ─────────────────────────────────────────────────────────────

const SectionCard = ({ title, icon, children, accentColor = '#3b82f6', tint = false }) => (
  <div style={{
    background:    tint ? `rgba(${accentColor.replace('#','').match(/.{2}/g).map(h=>parseInt(h,16)).join(',')},0.05)` : 'var(--bg-surface)',
    border:        `1px solid var(--border-glass)`,
    borderRadius:  10,
    padding:       '16px 18px',
    display:       'flex',
    flexDirection: 'column',
    gap:           10,
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

const NumberedItem = ({ n, children }) => (
  <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
    <span style={{
      minWidth: 20, height: 20, borderRadius: 4,
      background: 'rgba(59,130,246,0.15)', color: '#3b82f6',
      fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>{n}</span>
    <span style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{children}</span>
  </div>
);

const SkeletonRow = () => (
  <div style={{ height: 14, borderRadius: 6, background: 'var(--bg-glass)', animation: 'pulse 1.5s ease-in-out infinite', marginBottom: 8 }} />
);

// ── Main component ─────────────────────────────────────────────────────────────

const ForecastIntelligence = ({ className, model: modelProp, metric: metricProp }) => {
  // Controlled mode: use props from parent (ForecastChart).
  // Standalone mode: own internal selectors when props are undefined.
  const isControlled = modelProp !== undefined && metricProp !== undefined;

  const [metric,  setMetric]  = useState(metricProp  ?? 'won_pipeline');
  const [model,   setModel]   = useState(modelProp   ?? 'auto');
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  // Sync with parent props in controlled mode
  useEffect(() => { if (metricProp !== undefined) setMetric(metricProp); }, [metricProp]);
  useEffect(() => { if (modelProp  !== undefined) setModel(modelProp);  }, [modelProp]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/forecast/intelligence?metric=${metric}&model=${model}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [metric, model]);

  useEffect(() => { load(); }, [load]);

  // Derived display values
  const trendMeta = TREND_META[data?.trend_status]  || TREND_META.stable;
  const riskMeta  = RISK_META[data?.risk_level]      || RISK_META.moderate;

  const confidencePct  = data ? Math.round(data.model_confidence * 100) : null;
  const confidenceColor = confidencePct == null ? '#94a3b8'
                        : confidencePct >= 90 ? '#10b981'
                        : confidencePct >= 70 ? '#f59e0b' : '#ef4444';

  const isWinRate = metric === 'win_rate';
  const fmtVal    = isWinRate
    ? (v) => (v != null ? `${v.toFixed(1)}%` : '—')
    : fmtUSD;
  const fmtDeltaFn = isWinRate
    ? (v) => { if (v == null) return '—'; const s = v >= 0 ? '+' : ''; return `${s}${v.toFixed(2)}pp`; }
    : fmtDelta;

  const sel = (setter) => (e) => setter(e.target.value);

  const selectStyle = {
    background:   'var(--bg-glass)',
    border:       '1px solid var(--border-glass)',
    borderRadius: 6,
    color:        'var(--text-primary)',
    fontSize:     12,
    padding:      '4px 8px',
    cursor:       'pointer',
    outline:      'none',
  };

  return (
    <div className={className} style={{
      fontFamily: 'Inter, system-ui, sans-serif',
      display:    'flex',
      flexDirection: 'column',
      gap:        16,
    }}>
      {/* ── Panel Header ─────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        {/* Left: title + selectors (selectors hidden in controlled/embedded mode) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
              Forecast Intelligence
            </span>
            <span style={{
              fontSize: 10, fontWeight: 600, letterSpacing: '0.08em',
              color: '#3b82f6', background: 'rgba(59,130,246,0.1)',
              padding: '2px 7px', borderRadius: 20,
            }}>AI</span>
          </div>
          {!isControlled && (
            <>
              <select style={selectStyle} value={metric} onChange={sel(setMetric)}>
                {METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
              <select style={selectStyle} value={model} onChange={sel(setModel)}>
                {MODEL_OPTIONS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </>
          )}
          {data?.model_used && (
            <span style={{ fontSize: 11, color: '#64748b' }}>
              using <span style={{ color: '#94a3b8' }}>{data.model_name}</span>
            </span>
          )}
        </div>

        {/* Right: upside / downside */}
        <div style={{ display: 'flex', gap: 20 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981', letterSpacing: '0.06em', marginBottom: 2 }}>UPSIDE</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: '#10b981', lineHeight: 1 }}>
              {loading ? '—' : fmtDeltaFn(data?.upside_dollar)}
            </div>
          </div>
          <div style={{ width: 1, background: 'var(--border-glass)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', letterSpacing: '0.06em', marginBottom: 2 }}>DOWNSIDE</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: '#ef4444', lineHeight: 1 }}>
              {loading ? '—' : fmtDeltaFn(data?.downside_dollar)}
            </div>
          </div>
        </div>
      </div>

      {/* ── Error ─────────────────────────────────────────────────────────── */}
      {error && (
        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#ef4444' }}>
          Failed to load intelligence: {error} — <button onClick={load} style={{ background: 'none', border: 'none', color: '#ef4444', textDecoration: 'underline', cursor: 'pointer', fontSize: 13 }}>retry</button>
        </div>
      )}

      {/* ── Trend Summary Card ────────────────────────────────────────────── */}
      <div style={{
        background:    'var(--bg-surface)',
        border:        '1px solid var(--border-glass)',
        borderRadius:  12,
        padding:       '18px 20px',
        display:       'flex',
        flexDirection: 'column',
        gap:           14,
      }}>
        {/* Row 1: badges + confidence */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {loading ? (
              <div style={{ width: 100, height: 26, borderRadius: 20, background: 'var(--bg-glass)', animation: 'pulse 1.5s infinite' }} />
            ) : (
              <>
                <span style={{
                  fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
                  color: trendMeta.color, background: trendMeta.bg,
                  padding: '4px 12px', borderRadius: 20, border: `1px solid ${trendMeta.color}40`,
                }}>{trendMeta.label}</span>
                <span style={{
                  fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
                  color: riskMeta.color, background: riskMeta.bg,
                  padding: '4px 12px', borderRadius: 20, border: `1px solid ${riskMeta.color}40`,
                }}>{riskMeta.label}</span>
              </>
            )}
          </div>
          {/* Confidence */}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: '#64748b', letterSpacing: '0.06em', marginBottom: 1 }}>MODEL CONFIDENCE</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: confidenceColor, lineHeight: 1 }}>
              {loading ? '—' : confidencePct != null ? `${confidencePct}%` : '—'}
            </div>
          </div>
        </div>

        {/* Row 2: description */}
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {loading ? <><SkeletonRow /><SkeletonRow /></> : data?.description}
        </div>

        {/* Row 3: best case / worst case cards */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div style={{
            background:   'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)',
            borderRadius: 8, padding: '12px 14px',
          }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981', letterSpacing: '0.06em', marginBottom: 4 }}>BEST CASE (90d)</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#10b981' }}>
              {loading ? '—' : fmtVal(data?.forecast_90d?.best_case)}
            </div>
          </div>
          <div style={{
            background:   'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)',
            borderRadius: 8, padding: '12px 14px',
          }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', letterSpacing: '0.06em', marginBottom: 4 }}>WORST CASE (90d)</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#ef4444' }}>
              {loading ? '—' : fmtVal(data?.forecast_90d?.worst_case)}
            </div>
          </div>
        </div>

        {/* Row 4: most likely */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '8px 0', borderTop: '1px solid var(--border-glass)' }}>
          <span style={{ fontSize: 11, color: '#64748b', letterSpacing: '0.06em' }}>MOST LIKELY (90d)</span>
          <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)' }}>
            {loading ? '—' : fmtVal(data?.forecast_90d?.most_likely)}
          </span>
          {data?.mape > 0 && (
            <span style={{ fontSize: 11, color: '#64748b', background: 'var(--bg-glass)', padding: '2px 8px', borderRadius: 10 }}>
              MAPE {data.mape.toFixed(1)}%
            </span>
          )}
        </div>
      </div>

      {/* ── 2×2 Intelligence Grid ────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
        {/* Key Drivers */}
        <SectionCard title="Key Drivers" icon="✅" accentColor="#10b981">
          {loading
            ? [1,2,3].map(i => <SkeletonRow key={i} />)
            : (data?.key_drivers || []).map((d, i) => <Bullet key={i} color="#10b981">{d}</Bullet>)
          }
        </SectionCard>

        {/* Executive Actions */}
        <SectionCard title="Executive Actions" icon="⚙️" accentColor="#3b82f6">
          {loading
            ? [1,2,3].map(i => <SkeletonRow key={i} />)
            : (data?.executive_actions || []).map((a, i) => <NumberedItem key={i} n={i + 1}>{a}</NumberedItem>)
          }
        </SectionCard>

        {/* Downside Risks */}
        <SectionCard title="Downside Risks" icon="⚠️" accentColor="#ef4444">
          {loading
            ? [1,2,3].map(i => <SkeletonRow key={i} />)
            : (data?.downside_risks || []).map((r, i) => <Bullet key={i} color="#ef4444">{r}</Bullet>)
          }
        </SectionCard>

        {/* Upside Opportunities */}
        <SectionCard title="Upside Opportunities" icon="📈" accentColor="#10b981">
          {loading
            ? [1,2,3].map(i => <SkeletonRow key={i} />)
            : (data?.upside_opportunities || []).map((o, i) => <Bullet key={i} color="#10b981">{o}</Bullet>)
          }
        </SectionCard>
      </div>

      {/* ── Footer: source + refresh ─────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0' }}>
        <span style={{ fontSize: 11, color: '#475569' }}>
          {data?.source === 'databricks' ? '🟢 Live data from Databricks' : '🔵 Demo data — connect to Databricks for live insights'}
          {data?.history_days ? ` · ${data.history_days} days of history` : ''}
        </span>
        <button onClick={load} disabled={loading} style={{
          background:   'var(--bg-glass)',
          border:       '1px solid var(--border-glass)',
          borderRadius: 6,
          color:        'var(--text-secondary)',
          fontSize:     11,
          padding:      '4px 12px',
          cursor:       loading ? 'default' : 'pointer',
          opacity:      loading ? 0.5 : 1,
        }}>
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>
    </div>
  );
};

export default ForecastIntelligence;
