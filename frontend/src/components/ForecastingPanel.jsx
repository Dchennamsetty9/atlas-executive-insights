/**
 * ForecastingPanel — V2 inline ARR forecast experience (replaces ForecastChart).
 *
 * Tabs: Overview · Multi-Year · By Product · Monthly · Accuracy · AI Insights
 *
 * Data source : arr_forecast_v2 + arr_forecast_v2_leaderboard
 *               Databricks job "arr_forecast_v2" — every Monday 03:00 UTC.
 * API calls   : all go through apiService — zero raw fetch().
 * Error safety: TabErrorBoundary wraps each tab body; one tab cannot blank another.
 */

import { useState, useEffect, useCallback, useMemo, useRef, Component } from 'react';
import {
  ComposedChart, BarChart, LineChart,
  Area, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { apiService } from '../services/api';
import { exportCardPng } from '../utils/chartExport';

// ── Inline error boundary ─────────────────────────────────────────────────────
class TabErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { hasError: false }; }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(err) { console.error('[ForecastingPanel] tab error:', err); }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: '#ef4444' }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>⚠</div>
        <p style={{ fontSize: 14, margin: 0 }}>This tab encountered a rendering error.</p>
        <button onClick={() => this.setState({ hasError: false })}
          style={{ marginTop: 12, padding: '6px 20px', borderRadius: 8, cursor: 'pointer',
                   background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                   border: '1px solid rgba(239,68,68,0.3)', fontSize: 12 }}>Retry</button>
      </div>
    );
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────
const fmtM = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  if (n === 0) return '—';
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
};
const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.toLocaleString('default', { month: 'short' })} ${dt.getDate()}`;
};
const mapeColor = (v) => (v < 15 ? '#10b981' : v < 25 ? '#f59e0b' : '#ef4444');
const MODEL_LABELS = {
  ETS:      'ETS',
  Prophet:  'Prophet',
  LightGBM: 'LightGBM',
  Mstl_v2:  'MSTL',
  MSTL_v2:  'MSTL',
  Dhr_arima:'DHR-ARIMA',
  DHR_ARIMA:'DHR-ARIMA',
  Ensemble: 'Ensemble',
};
const formatModelLabel = (name) => MODEL_LABELS[name] || (name ? name.replace(/_/g,' ') : 'Unknown');

// ── Colour constants ──────────────────────────────────────────────────────────
const YEAR_COLORS  = { 2022: '#64748b', 2023: '#06b6d4', 2024: '#3b82f6', 2025: '#f59e0b', 2026: '#ef4444' };
// 6 notebook models: ensemble, prophet, ets, lightgbm, mstl_v2, dhr_arima
const MODEL_COLORS = { ETS: '#94a3b8', Prophet: '#f59e0b', LightGBM: '#3b82f6', Mstl_v2: '#a78bfa', Dhr_arima: '#fb923c', Ensemble: '#00FF88' };
// Keyed by lowercase model key (matches MODELS array and API params) — fixes pill color lookup for ets/lightgbm
const MODEL_KEY_META = {
  ensemble:  { label: 'Ensemble',  color: '#00FF88' },
  prophet:   { label: 'Prophet',   color: '#f59e0b' },
  ets:       { label: 'ETS',       color: '#94a3b8' },
  mstl_v2:   { label: 'MSTL',      color: '#a78bfa' },
  dhr_arima: { label: 'DHR-ARIMA', color: '#fb923c' },
  lightgbm:  { label: 'LightGBM',  color: '#3b82f6' },
};
// Maps model key → leaderboard column name for MAPE badge on pill
const MODEL_LB_KEY = {
  ensemble:  'Ensemble',
  prophet:   'Prophet',
  ets:       'ETS',
  mstl_v2:   'MSTL_v2',
  dhr_arima: 'DHR_ARIMA',
  lightgbm:  'LightGBM',
};
const MOMENTUM_META = {
  STABLE:       { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  ACCELERATING: { color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  DECELERATING: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
  VOLATILE:     { color: '#ef4444', bg: 'rgba(239,68,68,0.12)'   },
  stable:       { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  accelerating: { color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  decelerating: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
  volatile:     { color: '#ef4444', bg: 'rgba(239,68,68,0.12)'   },
};
const RISK_META = {
  'LOW RISK':      { color: '#10b981', bg: 'rgba(16,185,129,0.1)' },
  'MODERATE RISK': { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
  'HIGH RISK':     { color: '#ef4444', bg: 'rgba(239,68,68,0.1)'  },
  low:             { color: '#10b981', bg: 'rgba(16,185,129,0.1)' },
  moderate:        { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
  high:            { color: '#ef4444', bg: 'rgba(239,68,68,0.1)'  },
};

// ── Shared primitives ─────────────────────────────────────────────────────────
const DarkTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8, padding: '10px 14px', fontSize: 11 }}>
      <div style={{ color: '#64748b', marginBottom: 6, fontWeight: 600 }}>{label}</div>
      {payload.map((p, i) => p.value != null && (
        <div key={i} style={{ color: p.color ?? '#94a3b8', margin: '2px 0' }}>
          <span style={{ marginRight: 6 }}>{p.name}:</span>
          <span style={{ fontWeight: 700 }}>{typeof p.value === 'number' ? fmtM(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
};

const Skeleton = ({ height = 14 }) => (
  <div style={{ height, borderRadius: 6, background: 'rgba(255,255,255,0.06)',
                animation: 'fp-pulse 1.5s ease-in-out infinite', marginBottom: 8 }} />
);

const EmptyState = ({ message = 'Awaiting next forecast run' }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                minHeight: 150, gap: 10, color: '#475569', padding: '24px' }}>
    <div style={{ fontSize: 28 }}>🕐</div>
    <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b' }}>{message}</div>
    <div style={{ fontSize: 11, color: '#334155', textAlign: 'center', maxWidth: 380 }}>
      The forecast job runs every Monday at 03:00 UTC. Check back after the next run.
    </div>
  </div>
);

// CardWrap — optional downloadName renders a sleek ⬇ PNG button (captures the card's chart SVG)
const CardWrap = ({ children, downloadName }) => {
  const ref = useRef(null);
  return (
    <div ref={ref} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: 12, padding: 16, position: 'relative' }}>
      {downloadName && (
        <button onClick={() => exportCardPng(ref, downloadName)} title="Download chart as PNG"
          aria-label="Download chart as PNG" data-export-hide
          style={{ position: 'absolute', top: 10, right: 12, width: 26, height: 24, display: 'flex',
                   alignItems: 'center', justifyContent: 'center', borderRadius: 6, cursor: 'pointer',
                   background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                   color: '#64748b', fontSize: 12, lineHeight: 1, padding: 0, zIndex: 2 }}>
          ⬇
        </button>
      )}
      {children}
    </div>
  );
};

const SectionTitle = ({ children }) => (
  <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase',
                letterSpacing: '0.06em', marginBottom: 10 }}>{children}</div>
);

// Downsample chart rows to a compact payload for the LLM (≤ maxPoints, nulls stripped)
const _compactDataPoints = (rows, maxPoints = 40) => {
  const clean = (rows || []).filter(r => r && typeof r === 'object');
  if (clean.length <= maxPoints) return clean;
  const step = Math.ceil(clean.length / maxPoints);
  return clean.filter((_, i) => i % step === 0 || i === clean.length - 1);
};

/**
 * GraphInsight — collapsible insight popup on a chart card.
 * Always shows the deterministic client-side summary immediately.
 * If chartType/metricName/dataPoints are provided, lazily fetches a live LLM
 * annotation (POST /api/ai/chart-annotation) on first expand and caches it;
 * on failure the deterministic summary simply stands alone (no regression).
 */
const GraphInsight = ({ summary, chartType, metricName, dataPoints }) => {
  const [open, setOpen] = useState(false);
  const [ai, setAi] = useState(null);          // { annotation } once fetched
  const [aiLoading, setAiLoading] = useState(false);
  const [aiTried, setAiTried] = useState(false);
  const aiCapable = Boolean(chartType && metricName && dataPoints?.length);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    // Lazy-fetch the LLM annotation once, on first expand only
    if (next && aiCapable && !aiTried) {
      setAiTried(true);
      setAiLoading(true);
      apiService.getAIChartAnnotation(chartType, _compactDataPoints(dataPoints), metricName)
        .then((res) => { if (res?.annotation) setAi(res); })
        .catch(() => { /* deterministic summary stands alone */ })
        .finally(() => setAiLoading(false));
    }
  };

  if (!summary && !aiCapable) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <button
        onClick={toggle}
        style={{
          border: '1px solid rgba(59,130,246,0.22)',
          background: 'rgba(59,130,246,0.08)',
          color: '#93c5fd',
          borderRadius: 8,
          padding: '4px 10px',
          fontSize: 11,
          fontWeight: 700,
          cursor: 'pointer',
          letterSpacing: '0.02em',
        }}
      >
        {open ? '▾' : '▸'} {aiCapable ? '✨ AI Insight' : 'AI Insight'}
      </button>
      {open && (
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            color: '#cbd5e1',
            lineHeight: 1.6,
            background: 'rgba(30,41,59,0.45)',
            border: '1px solid rgba(148,163,184,0.2)',
            borderRadius: 8,
            padding: '8px 10px',
          }}
        >
          {summary && <div>{summary}</div>}
          {aiCapable && (
            <div style={{ marginTop: summary ? 8 : 0, paddingTop: summary ? 8 : 0,
                          borderTop: summary ? '1px solid rgba(148,163,184,0.15)' : 'none' }}>
              {aiLoading && (
                <span style={{ color: '#64748b', fontStyle: 'italic' }}>✨ Asking AI about this chart…</span>
              )}
              {!aiLoading && ai?.annotation && (
                <span>
                  <span style={{ color: '#a78bfa', fontWeight: 700, marginRight: 6 }}>✨ AI:</span>
                  {ai.annotation}
                </span>
              )}
              {!aiLoading && aiTried && !ai?.annotation && (
                <span style={{ color: '#475569', fontSize: 11 }}>AI annotation unavailable — showing rule-based summary.</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Chart sub-components ──────────────────────────────────────────────────────
const WeeklyChart = ({ rows }) => {
  const combined = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  // Find the split date where actuals end and forecast begins
  const lastActual = [...combined].reverse().find(r => r.arr_actual != null);
  const splitDate = lastActual?.date ?? null;

  // Build unified dataset — bands use stacking trick: floor (transparent) + range (colored).
  // Stored Worst_Case/Best_Case are the model's P10/P90 → an 80% prediction interval.
  // The inner ~50% band (≈P25–P75) is derived by z-score scaling of the P10/P90 spread
  // around Most Likely (z25/z10 = 0.6745/1.2816 ≈ 0.526) assuming symmetric-ish residuals.
  const INNER_Z_RATIO = 0.6745 / 1.2816;
  const data = combined.map(r => {
    const likely = r.arr_likely ?? null;
    const worst  = r.arr_worst  ?? null;
    const best   = r.arr_best   ?? null;
    const hasBand = likely != null && worst != null && best != null;
    const innerLo = hasBand ? likely - (likely - worst) * INNER_Z_RATIO : null;
    const innerHi = hasBand ? likely + (best - likely) * INNER_Z_RATIO : null;
    return {
      date: r.date,
      actual: r.arr_actual ?? null,
      likely, worst, best,
      innerLo, innerHi,
      bandFloor: worst,
      bandRange: (best != null && worst != null) ? Math.max(0, best - worst) : null,
      innerFloor: innerLo,
      innerRange: (innerHi != null && innerLo != null) ? Math.max(0, innerHi - innerLo) : null,
    };
  });

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload || {};
    return (
      <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 10,
                    padding: '12px 16px', fontSize: 11, minWidth: 180 }}>
        <div style={{ color: '#64748b', marginBottom: 8, fontWeight: 600 }}>{label}</div>
        {d.actual  != null && <div style={{ color: '#f59e0b', marginBottom: 3 }}>● Actuals: <b>{fmtM(d.actual)}</b></div>}
        {d.likely  != null && <div style={{ color: '#e2e8f0', marginBottom: 3 }}>● Most Likely: <b>{fmtM(d.likely)}</b></div>}
        {d.best    != null && <div style={{ color: '#10b981', marginBottom: 3 }}>▲ Stretch Case — 1-in-5 upside: <b>{fmtM(d.best)}</b></div>}
        {d.worst   != null && <div style={{ color: '#ef4444', marginBottom: 3 }}>▼ Risk Floor — 1-in-10 downside: <b>{fmtM(d.worst)}</b></div>}
        {d.innerLo != null && d.innerHi != null && (
          <div style={{ color: '#22d3ee', marginTop: 5, paddingTop: 5, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
            ▒ 50% band: <b>{fmtM(d.innerLo)} – {fmtM(d.innerHi)}</b>
          </div>
        )}
        {d.worst != null && d.best != null && (
          <div style={{ color: '#60a5fa', marginTop: 2 }}>
            ▒ 80% band: <b>{fmtM(d.worst)} – {fmtM(d.best)}</b>
          </div>
        )}
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={360}>
      <ComposedChart data={data} margin={{ top: 20, right: 20, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="actualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.18} />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.03} />
          </linearGradient>
          <linearGradient id="innerBandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.30} />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.08} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDate}
               tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false}
               interval="preserveStartEnd" />
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }}
               axisLine={false} tickLine={false} width={78}
               label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<CustomTooltip />} />
        {splitDate && (
          <ReferenceLine x={splitDate} stroke="rgba(59,130,246,0.45)" strokeDasharray="4 4"
            label={{ value: '◀ ACTUALS', position: 'insideTopRight', fill: '#f59e0b', fontSize: 10, fontWeight: 700 }} />
        )}
        {splitDate && (
          <ReferenceLine x={splitDate} stroke="none"
            label={{ value: 'FORECAST ▶', position: 'insideTopLeft', fill: '#3b82f6', fontSize: 10, fontWeight: 700 }} />
        )}
        {/* Outer 80% band (P10–P90): transparent floor stacked under colored band */}
        <Area type="monotone" dataKey="bandFloor" stackId="conf" stroke="none" fill="transparent"
              legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="bandRange" stackId="conf" stroke="none" fill="url(#bandFill)"
              legendType="none" connectNulls dot={false} />
        {/* Inner ~50% band (≈P25–P75, z-scaled from P10/P90) drawn on top for nested effect */}
        <Area type="monotone" dataKey="innerFloor" stackId="conf50" stroke="none" fill="transparent"
              legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="innerRange" stackId="conf50" stroke="none" fill="url(#innerBandFill)"
              legendType="none" connectNulls dot={false} />
        {/* Actuals — gradient fill area */}
        <Area type="monotone" dataKey="actual" stroke="#f59e0b" strokeWidth={2.5}
              fill="url(#actualFill)" dot={false} connectNulls={false} name="Actuals" />
        {/* Forecast lines */}
        <Line type="monotone" dataKey="worst"  name="Risk Floor"   stroke="#ef4444"
              strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls />
        <Line type="monotone" dataKey="likely" name="Most Likely"  stroke="#e2e8f0"
              strokeWidth={3} dot={false} connectNulls />
        <Line type="monotone" dataKey="best"   name="Stretch Case" stroke="#10b981"
              strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

const RunningTotalsChart = ({ rows }) => {
  const data = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 16, right: 20, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ytdActualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={d => d?.slice(0,7)} tick={{ fill: '#475569', fontSize: 10 }}
               axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }}
               axisLine={false} tickLine={false} width={78}
               label={{ value: 'Cumulative Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<DarkTip />} />
        <Area type="monotone" dataKey="ytd_actual" name="Actuals YTD" stroke="#f59e0b"
              strokeWidth={2.5} fill="url(#ytdActualFill)" dot={false} connectNulls={false} />
        <Line type="monotone" dataKey="ytd_worst"  name="Risk Floor"   stroke="#ef4444"
              strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_likely" name="Most Likely"  stroke="#e2e8f0"
              strokeWidth={2.5} dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_best"   name="Stretch Case" stroke="#10b981"
              strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  );
};


const MultiYearChart = ({ rows }) => {
  const years = [...new Set(rows.map(r => r.year))].sort();
  const byIsoWeek = {};
  for (const r of rows) {
    if (!byIsoWeek[r.iso_week]) byIsoWeek[r.iso_week] = { iso_week: r.iso_week };
    byIsoWeek[r.iso_week][r.year] = (byIsoWeek[r.iso_week][r.year] || 0) + r.arr;
  }
  const data = Object.values(byIsoWeek).sort((a, b) => a.iso_week - b.iso_week);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        <XAxis dataKey="iso_week" tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} width={72}
               label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 9, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<DarkTip />} />
        {years.map(yr => (
          <Line key={yr} type="monotone" dataKey={yr} name={String(yr)}
                stroke={YEAR_COLORS[yr] ?? '#94a3b8'} strokeWidth={1.5} dot={false} connectNulls isAnimationActive />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
};

const ByProductChart = ({ byProduct, byLine }) => {
  const lineData = (byLine || []).map(l => ({
    name: l.product_line || l.product,
    worst: (l.arr_worst || 0) / 1e6, likely: (l.arr_likely || 0) / 1e6, best: (l.arr_best || 0) / 1e6,
  }));
  const prodData = (byProduct || []).map(p => ({ name: p.product, likely: (p.arr_likely || 0) / 1e6 }));
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>By Product Line</div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={lineData} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tickFormatter={v => `$${v.toFixed(1)}M`} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ fill: '#f1f5f9', fontSize: 10 }} axisLine={false} tickLine={false} width={44} />
            <Tooltip content={<DarkTip />} />
            <Bar dataKey="worst"  name="Risk Floor"   fill="#ef4444" opacity={0.5} radius={[0,3,3,0]} barSize={14} isAnimationActive />
            <Bar dataKey="likely" name="Most Likely"  fill="#ffffff" opacity={0.9} radius={[0,3,3,0]} barSize={14} isAnimationActive />
            <Bar dataKey="best"   name="Stretch Case" fill="#10b981" opacity={0.5} radius={[0,3,3,0]} barSize={14} isAnimationActive />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>By Product (Most Likely)</div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={prodData} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tickFormatter={v => `$${v.toFixed(1)}M`} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ fill: '#f1f5f9', fontSize: 9 }} axisLine={false} tickLine={false} width={72} />
            <Tooltip content={<DarkTip />} />
            <Bar dataKey="likely" name="Most Likely" fill="#3b82f6" radius={[0,4,4,0]} barSize={12} isAnimationActive />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

const MonthlyTable = ({ months }) => {
  const quarters = [...new Set((months || []).map(m => m.quarter))].sort();
  const byQtr = {};
  for (const m of (months || [])) { if (!byQtr[m.quarter]) byQtr[m.quarter] = []; byQtr[m.quarter].push(m); }
  const td = { padding: '6px 12px', textAlign: 'right', fontSize: 12, color: '#94a3b8', borderBottom: '1px solid rgba(255,255,255,0.04)' };
  const th = { padding: '6px 12px', textAlign: 'right', fontSize: 10, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' };
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            {['Year','Qtr','Month','Actuals','Risk Floor','Most Likely','Stretch Case'].map(h => (
              <th key={h} style={{ ...th, textAlign: ['Month','Year','Qtr'].includes(h) ? 'left' : 'right' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {quarters.map(q => {
            const qm = byQtr[q] || [];
            // Only sum non-null actuals; leave null so fmtM renders — for fully-open quarters
            const tot = qm.reduce((a, m) => ({
              arr_actual: m.arr_actual != null ? (a.arr_actual ?? 0) + m.arr_actual : a.arr_actual,
              arr_worst:  a.arr_worst  + m.arr_worst,
              arr_likely: a.arr_likely + m.arr_likely,
              arr_best:   a.arr_best   + m.arr_best,
            }), { arr_actual: null, arr_worst: 0, arr_likely: 0, arr_best: 0 });
            return [
              ...qm.map((m, i) => (
                <tr key={`${q}-${m.month}`} style={{ background: i%2===0 ? 'rgba(255,255,255,0.01)' : 'transparent' }}>
                  <td style={{ ...td, textAlign: 'left', color: '#64748b' }}>{i===0?m.year:''}</td>
                  <td style={{ ...td, textAlign: 'left', color: '#64748b' }}>{i===0?`Q${q}`:''}</td>
                  <td style={{ ...td, textAlign: 'left', color: '#f1f5f9', fontWeight: 500 }}>{m.month_name}</td>
                  <td style={{ ...td, color: m.arr_actual?'#f59e0b':'#334155' }}>{fmtM(m.arr_actual)}</td>
                  <td style={{ ...td, color: '#ef4444' }}>{fmtM(m.arr_worst)}</td>
                  <td style={{ ...td, color: '#f1f5f9', fontWeight: 600 }}>{fmtM(m.arr_likely)}</td>
                  <td style={{ ...td, color: '#10b981' }}>{fmtM(m.arr_best)}</td>
                </tr>
              )),
              <tr key={`qtot-${q}`} style={{ background: 'rgba(59,130,246,0.06)', borderTop: '1px solid rgba(59,130,246,0.2)' }}>
                <td style={{ ...td, textAlign: 'left', color: '#64748b' }} />
                <td style={{ ...td, textAlign: 'left', color: '#3b82f6', fontWeight: 700 }}>Total</td>
                <td style={{ ...td, textAlign: 'left', color: '#3b82f6', fontWeight: 700 }}>{`Q${q} Total`}</td>
                <td style={{ ...td, color: '#f59e0b', fontWeight: 700 }}>{fmtM(tot.arr_actual)}</td>
                <td style={{ ...td, color: '#ef4444', fontWeight: 700 }}>{fmtM(tot.arr_worst)}</td>
                <td style={{ ...td, color: '#f1f5f9', fontWeight: 700 }}>{fmtM(tot.arr_likely)}</td>
                <td style={{ ...td, color: '#10b981', fontWeight: 700 }}>{fmtM(tot.arr_best)}</td>
              </tr>,
            ];
          })}
        </tbody>
      </table>
    </div>
  );
};

const GeoBarChart = ({ rows }) => {
  if (!rows || rows.length === 0) return <EmptyState message="No geo breakdown available" />;
  const data = rows.map(r => ({
    name:   r.sales_market,
    worst:  (r.arr_worst  || 0) / 1e6,
    likely: (r.arr_likely || 0) / 1e6,
    best:   (r.arr_best   || 0) / 1e6,
  }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
        <XAxis type="number" tickFormatter={v => `$${v.toFixed(1)}M`} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="name" tick={{ fill: '#f1f5f9', fontSize: 10 }} axisLine={false} tickLine={false} width={52} />
        <Tooltip content={<DarkTip />} />
        <Bar dataKey="worst"  name="Risk Floor"   fill="#ef4444" opacity={0.5} radius={[0,3,3,0]} barSize={14} isAnimationActive />
        <Bar dataKey="likely" name="Most Likely"  fill="#ffffff" opacity={0.9} radius={[0,3,3,0]} barSize={14} isAnimationActive />
        <Bar dataKey="best"   name="Stretch Case" fill="#10b981" opacity={0.5} radius={[0,3,3,0]} barSize={14} isAnimationActive />
      </BarChart>
    </ResponsiveContainer>
  );
};

const AccuracyTable = ({ data }) => {
  // Notebook models: Prophet_trend (→Prophet), MSTL_v2, ETS, DHR_ARIMA (→DHR_ARIMA), LightGBM
  // Chronos NOT in model suite — filter it out if value is null / ≥999
  const ALL_MODELS = [
    { key: 'ETS', label: formatModelLabel('ETS') },
    { key: 'Prophet', label: formatModelLabel('Prophet') },
    { key: 'LightGBM', label: formatModelLabel('LightGBM') },
  ];
  // Also show MSTL_v2 / DHR_ARIMA / Ensemble when leaderboard contains those columns
  const hasMstl = data?.some(r => r['MSTL_v2'] != null && r['MSTL_v2'] < 999);
  const hasDhr  = data?.some(r => r['DHR_ARIMA'] != null && r['DHR_ARIMA'] < 999);
  const hasEns  = data?.some(r => r['Ensemble'] != null && r['Ensemble'] < 999);
  const models = [
    ...(hasEns ? [{ key: 'Ensemble', label: 'Ensemble ★' }] : []),
    ...ALL_MODELS,
    ...(hasMstl ? [{ key: 'MSTL_v2', label: formatModelLabel('MSTL_v2') }] : []),
    ...(hasDhr ? [{ key: 'DHR_ARIMA', label: formatModelLabel('DHR_ARIMA') }] : []),
  ];
  const hiddenModels = [!hasMstl && 'MSTL', !hasDhr && 'DHR-ARIMA'].filter(Boolean).join(', ');
  return (
    <div>
      {hasEns && (
        <div style={{ fontSize: 10, color: '#64748b', marginBottom: 8 }}>
          ★ Ensemble MAPE is realized accuracy — past forecasts vs weeks that later closed as actuals.
          Individual models are scored on holdout validation.
        </div>
      )}
      {hiddenModels && (
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, padding: '6px 10px',
                      background: 'rgba(255,255,255,0.02)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)' }}>
          ℹ️ {hiddenModels} — columns hidden; leaderboard data unavailable for these models.
        </div>
      )}
      <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            {['Product','Geo',...models.map(m => m.label),'Best Model','Best MAPE'].map(h => (
              <th key={h} style={{ padding: '6px 12px', textAlign: ['Product','Geo','Best Model'].includes(h)?'left':'right',
                                   fontSize: 10, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(data || []).map((r, i) => (
            <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', background: i%2===0?'rgba(255,255,255,0.01)':'transparent' }}>
              <td style={{ padding: '6px 12px', fontSize: 12, color: '#f1f5f9' }}>{r.product}</td>
              <td style={{ padding: '6px 12px', fontSize: 11, color: '#64748b' }}>{r.sales_market}</td>
              {models.map(m => (
                <td key={m.key} style={{ padding: '6px 12px', textAlign: 'right', fontSize: 12,
                                     color: r[m.key]&&r[m.key]<999 ? mapeColor(r[m.key]) : '#334155',
                                     fontWeight: r.best_model===m.key ? 700 : 400 }}>
                  {r[m.key]&&r[m.key]<999 ? `${r[m.key].toFixed(1)}%` : '—'}
                  {r.best_model===m.key && <span style={{ marginLeft: 4, fontSize: 9 }}>★</span>}
                </td>
              ))}
              <td style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, color: '#f59e0b', fontWeight: 600 }}>{formatModelLabel(r.best_model)}</td>
              <td style={{ padding: '6px 12px', textAlign: 'right', fontSize: 12, fontWeight: 700,
                           color: r.best_mape&&r.best_mape<999 ? mapeColor(r.best_mape) : '#334155' }}>
                {r.best_mape&&r.best_mape<999 ? `${r.best_mape.toFixed(1)}%` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
};

// ── AI Insights tab — calls /api/forecast/v2/intelligence (Delta table) ───────
const AiInsightsSection = ({ model, prodLine }) => {
  const [aiData,    setAiData]    = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError,   setAiError]   = useState(null);

  const loadAi = useCallback(async () => {
    setAiLoading(true); setAiError(null);
    try {
      // AI Insights are pre-computed in Delta table — not model/product-specific;
      // call v2 endpoint which reads from arr_forecast_insights Delta table.
      const res = await apiService.getForecastV2Intelligence();
      // Support both wrapped {source, data:{...}} and legacy flat shape
      const d = (res?.data && typeof res.data === 'object') ? res.data : res;
      setAiData({ ...d, _source: res?.source ?? d?.source });
    } catch (e) {
      setAiError(e.message || 'Failed to load AI insights');
    } finally {
      setAiLoading(false);
    }
  // Pre-computed Delta table: not model/product-specific — no deps needed;
  // remove model/prodLine to avoid background refetches on filter changes.
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { loadAi(); }, [loadAi]);

  // Normalise field names across backend shape variants
  const momentum  = aiData?.momentum ?? aiData?.trend_status;
  const risk      = aiData?.risk_level;
  const momMeta   = MOMENTUM_META[momentum] ?? MOMENTUM_META.STABLE;
  const riskMeta  = RISK_META[risk] ?? RISK_META.moderate;

  const rawConf   = aiData?.model_confidence;
  const confidence = rawConf != null ? (rawConf > 1 ? Math.round(rawConf) : Math.round(rawConf * 100)) : null;
  const confColor = confidence == null ? '#94a3b8' : confidence >= 90 ? '#10b981' : confidence >= 70 ? '#f59e0b' : '#ef4444';

  const narrative = aiData?.narrative ?? aiData?.description;
  const mape      = aiData?.best_mape ?? aiData?.mape;
  const isDemo    = aiData?._source === 'demo';

  const fmtDelta = (v) => {
    if (v == null) return null;
    if (typeof v === 'string') return v;
    return fmtM(Math.abs(Number(v)));
  };
  const upsideStr   = fmtDelta(aiData?.upside   ?? aiData?.upside_dollar);
  const downsideStr = fmtDelta(aiData?.downside  ?? aiData?.downside_dollar);

  if (aiLoading) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Skeleton height={80} /><Skeleton height={60} /><Skeleton height={48} /><Skeleton height={48} />
    </div>
  );

  if (aiError) return (
    <div style={{ padding: '24px', background: 'rgba(239,68,68,0.06)', borderRadius: 10, color: '#ef4444', textAlign: 'center' }}>
      <p style={{ margin: 0 }}>{aiError}</p>
      <button onClick={loadAi} style={{ marginTop: 10, padding: '4px 16px', borderRadius: 6, cursor: 'pointer',
                                        background: 'transparent', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)', fontSize: 12 }}>Retry</button>
    </div>
  );

  // Show actionable empty state when backend returns an error object (table not yet populated)
  if (aiData?.error && !aiData?.key_drivers?.length) return (
    <div style={{ padding: '24px', background: 'rgba(245,158,11,0.06)', borderRadius: 10, color: '#f59e0b', textAlign: 'center' }}>
      <div style={{ fontSize: 24, marginBottom: 8 }}>💭</div>
      <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{aiData.narrative || aiData.error}</p>
      <p style={{ margin: '8px 0 0', fontSize: 12, color: '#64748b' }}>
        Run Cell 10 (Step 7) of the Panel Writer notebook to populate the AI Insights Delta table.
      </p>
      <button onClick={loadAi} style={{ marginTop: 10, padding: '4px 16px', borderRadius: 6, cursor: 'pointer',
                                        background: 'transparent', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)', fontSize: 12 }}>
        ↻ Retry
      </button>
    </div>
  );

  const SECTIONS = [
    { key: 'key_drivers',         title: 'Key Drivers',          icon: '✅', color: '#10b981' },
    { key: 'downside_risks',       title: 'Downside Risks',       icon: '⚠️', color: '#ef4444' },
    { key: 'upside_opportunities', title: 'Upside Opportunities', icon: '📈', color: '#10b981' },
    { key: 'executive_actions',    title: 'Executive Actions',    icon: '⚙️', color: '#3b82f6' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {isDemo && (
        <div style={{ padding: '8px 14px', borderRadius: 8, fontSize: 12, color: '#f59e0b',
                      background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)' }}>
          📋 Sample data — connect to Databricks for live AI insights
        </div>
      )}

      {/* Hero: badges · confidence · deltas */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {momentum && (
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', padding: '4px 12px',
                           borderRadius: 20, color: momMeta.color, background: momMeta.bg,
                           border: `1px solid ${momMeta.color}40` }}>
              {String(momentum).toUpperCase()}
            </span>
          )}
          {risk && (
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', padding: '4px 12px',
                           borderRadius: 20, color: riskMeta.color, background: riskMeta.bg,
                           border: `1px solid ${riskMeta.color}40` }}>
              {String(risk).toUpperCase().replace('_', ' ')}
            </span>
          )}
          {mape != null && (
            <span style={{ fontSize: 10, padding: '4px 10px', borderRadius: 16,
                           color: mapeColor(Number(mape)), background: 'rgba(255,255,255,0.04)',
                           border: `1px solid ${mapeColor(Number(mape))}40` }}>
              MAPE {Number(mape).toFixed ? Number(mape).toFixed(1) : mape}%
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end' }}>
          {upsideStr && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981', letterSpacing: '0.06em', marginBottom: 2 }}>UPSIDE</div>
              <div style={{ fontSize: 18, fontWeight: 800, color: '#10b981', lineHeight: 1 }}>{upsideStr}</div>
            </div>
          )}
          {confidence != null && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 10, color: '#64748b', letterSpacing: '0.06em', marginBottom: 1 }}>CONFIDENCE</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: confColor, lineHeight: 1 }}>{confidence}%</div>
            </div>
          )}
          {downsideStr && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', letterSpacing: '0.06em', marginBottom: 2 }}>DOWNSIDE</div>
              <div style={{ fontSize: 18, fontWeight: 800, color: '#ef4444', lineHeight: 1 }}>−{downsideStr}</div>
            </div>
          )}
        </div>
      </div>

      {/* Narrative */}
      {narrative && (
        <div style={{ fontSize: 14, color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.7,
                      padding: '14px 18px', background: 'rgba(255,255,255,0.02)',
                      border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10 }}>
          {narrative}
        </div>
      )}

      {/* 2×2 intelligence grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(255px, 1fr))', gap: 12 }}>
        {SECTIONS.map(sec => {
          const items = aiData?.[sec.key];
          if (!items?.length) return null;
          return (
            <div key={sec.key} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
                                        borderRadius: 10, padding: '14px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
                <span style={{ fontSize: 14 }}>{sec.icon}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: sec.color, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{sec.title}</span>
              </div>
              {items.map((item, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 6 }}>
                  <span style={{ color: sec.color, marginTop: 2, flexShrink: 0 }}>▸</span>
                  <span style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.5 }}>{item}</span>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 4 }}>
        <span style={{ fontSize: 11, color: '#334155' }}>
          {isDemo
            ? '🔵 Demo — connect to Databricks for live insights'
            : `🟢 Live · Pre-computed insights${aiData?.run_date ? ` · Run ${aiData.run_date}` : ''}`}
        </span>
        <button onClick={loadAi} disabled={aiLoading}
          style={{ padding: '4px 12px', borderRadius: 6, cursor: aiLoading ? 'default' : 'pointer',
                   background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                   color: '#64748b', fontSize: 11, opacity: aiLoading ? 0.5 : 1 }}>
          {aiLoading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>
    </div>
  );
};

// ── Backtest: Forecast vs Reality (trust view) — /api/forecast/v2/backtest ────
const HORIZONS = [1, 4, 8, 13];

const BacktestSection = ({ model, prodLine, salesMarket }) => {
  const [horizon, setHorizon] = useState(4);
  const [data, setData]       = useState(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError]     = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setBtLoading(true); setBtError(null);
      try {
        const res = await apiService.getForecastV2Backtest(
          horizon, model,
          prodLine !== 'All' ? prodLine : null,
          salesMarket && salesMarket !== 'All' ? salesMarket : null,
        );
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setBtError(e.message || 'Failed to load backtest');
      } finally {
        if (!cancelled) setBtLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [horizon, model, prodLine, salesMarket]);

  const rows = (data?.rows || []).map(r => ({
    ...r,
    bandFloor: r.worst,
    bandRange: (r.best != null && r.worst != null) ? Math.max(0, r.best - r.worst) : null,
  }));
  const s = data?.summary || {};
  const isLive = data?.source === 'live';

  // Coverage semantics: band is P10–P90 → calibrated intervals catch ~80% of actuals
  const covColor = s.coverage_pct == null ? '#64748b'
    : s.coverage_pct >= 70 ? '#10b981' : s.coverage_pct >= 50 ? '#f59e0b' : '#ef4444';
  const biasStr = s.bias_pct == null ? '—'
    : `${s.bias_pct > 0 ? '+' : ''}${s.bias_pct}% ${s.bias_pct > 0 ? '(over-forecast)' : s.bias_pct < 0 ? '(under-forecast)' : ''}`;

  const chip = (label, value, color) => (
    <div style={{ padding: '10px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.07)', minWidth: 120 }}>
      <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
    </div>
  );

  return (
    <CardWrap downloadName="forecast_vs_reality">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <SectionTitle>Forecast vs Reality — What We Predicted, What Happened</SectionTitle>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 20,
                       color: isLive ? '#10b981' : '#f59e0b',
                       background: isLive ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.08)',
                       border: `1px solid ${isLive ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.2)'}` }}>
          {isLive ? 'LIVE' : 'DEMO'}
        </span>
      </div>
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 12, lineHeight: 1.5 }}>
        Each point compares the forecast made <b style={{ color: '#94a3b8' }}>{horizon} week{horizon > 1 ? 's' : ''} in advance</b> against
        the actual that later closed. Band coverage should approach ~80% if the P10–P90 intervals are calibrated.
      </div>

      {/* Horizon pills */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: '#475569', marginRight: 4 }}>Forecast horizon:</span>
        {HORIZONS.map(h => (
          <button key={h} onClick={() => setHorizon(h)}
            style={{ padding: '4px 11px', borderRadius: 999, fontSize: 10, fontWeight: 700, cursor: 'pointer',
                     border: `1px solid ${horizon === h ? '#3b82f6' : 'rgba(255,255,255,0.08)'}`,
                     background: horizon === h ? 'rgba(59,130,246,0.12)' : 'rgba(255,255,255,0.03)',
                     color: horizon === h ? '#93c5fd' : '#475569' }}>
            {h} wk ahead
          </button>
        ))}
      </div>

      {btError && (
        <div style={{ padding: '14px', borderRadius: 8, color: '#ef4444', background: 'rgba(239,68,68,0.06)', fontSize: 12 }}>
          ⚠ {btError}
        </div>
      )}

      {btLoading ? <Skeleton height={260} /> : rows.length === 0 && !btError ? (
        <EmptyState message="No closed weeks with retained forecasts at this horizon yet" />
      ) : rows.length > 0 && (
        <>
          {/* Stat chips */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            {chip('Weeks scored', s.weeks_scored ?? '—', '#f1f5f9')}
            {chip('Band coverage (target ~80%)', s.coverage_pct != null ? `${s.coverage_pct}%` : '—', covColor)}
            {chip(`MAPE @ ${horizon}wk`, s.mape_pct != null ? `${s.mape_pct}%` : '—', s.mape_pct != null ? mapeColor(s.mape_pct) : '#64748b')}
            {chip('Bias', biasStr, s.bias_pct == null ? '#64748b' : Math.abs(s.bias_pct) < 5 ? '#10b981' : '#f59e0b')}
          </div>

          <div style={{ fontSize: 10, color: '#475569', marginBottom: 8, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span><span style={{ color: '#f59e0b' }}>─</span> Actual (closed)</span>
            <span><span style={{ color: '#e2e8f0' }}>- -</span> Predicted {horizon}wk prior</span>
            <span style={{ color: '#3b82f6' }}>▒ Predicted 80% band</span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={rows} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="btBandFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.20} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="ds" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }}
                     axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }}
                     axisLine={false} tickLine={false} width={78}
                     label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
              <Tooltip content={<DarkTip />} />
              <Area type="monotone" dataKey="bandFloor" stackId="bt" stroke="none" fill="transparent"
                    legendType="none" connectNulls dot={false} name="P10" />
              <Area type="monotone" dataKey="bandRange" stackId="bt" stroke="none" fill="url(#btBandFill)"
                    legendType="none" connectNulls dot={false} name="P10–P90 range" />
              <Line type="monotone" dataKey="predicted" name={`Predicted (${horizon}wk prior)`} stroke="#e2e8f0"
                    strokeWidth={2} strokeDasharray="6 4" dot={{ r: 2.5, fill: '#e2e8f0' }} connectNulls />
              <Line type="monotone" dataKey="actual" name="Actual" stroke="#f59e0b"
                    strokeWidth={2.5} dot={{ r: 3, fill: '#f59e0b' }} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}
    </CardWrap>
  );
};

// ── Model Lab: per-model P10/P50/P90 from V5 notebook tables ──────────────────
// Module-level pill style (the main panel has its own identical local copy;
// module-level components like ModelLabSection can't see that closure).
const pillStyle = (active, color) => ({
  padding: '4px 11px', borderRadius: 999, fontSize: 10, fontWeight: 700,
  cursor: 'pointer', transition: 'all 0.15s ease', display: 'flex', alignItems: 'center', gap: 5,
  border:      `1px solid ${active ? (color ?? 'rgba(255,255,255,0.4)') : 'rgba(255,255,255,0.08)'}`,
  background:  active ? `${(color ?? '#ffffff')}1a` : 'rgba(255,255,255,0.03)',
  color:       active ? (color ?? '#f1f5f9') : '#475569',
});
const ML_COLORS = ['#00FF88', '#f59e0b', '#3b82f6', '#a78bfa', '#fb923c', '#22d3ee', '#f472b6'];
const mlLabel = (m) => {
  if (!m) return '';
  if (m === 'Adaptive_Ensemble') return 'Ensemble ★';
  return m.replace(/_/g, ' ').replace(/\btrend\b/i, '').replace(/\bv2\b/i, '').trim();
};

const ModelLabSection = ({ product, salesMarket }) => {
  const [grain, setGrain]     = useState('total');
  const [data, setData]       = useState(null);
  const [sel, setSel]         = useState(null);
  const [mlLoading, setMlLoading] = useState(false);
  const [mlError, setMlError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setMlLoading(true); setMlError(null);
      try {
        const res = await apiService.getForecastV2ModelLab(product, grain, salesMarket);
        if (cancelled) return;
        setData(res);
        setSel((prev) => (res?.models?.includes(prev) ? prev : (res?.recommended_model || res?.models?.[0] || null)));
      } catch (e) {
        if (!cancelled) setMlError(e.message || 'Failed to load model forecasts');
      } finally {
        if (!cancelled) setMlLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [product, grain, salesMarket]);

  const rows = data?.rows || [];
  const models = data?.models || [];
  const isDemo = data?.source !== 'live';
  const colorOf = useMemo(() => {
    const map = {};
    models.forEach((m, i) => { map[m] = m === 'Adaptive_Ensemble' ? '#00FF88' : ML_COLORS[(i % ML_COLORS.length)]; });
    return map;
  }, [models]);

  // Fan for the selected model (its own P10/P50/P90)
  const fan = useMemo(() => {
    const r = rows.filter((x) => x.model === sel).sort((a, b) => a.ds.localeCompare(b.ds));
    return r.map((x) => ({
      date: x.ds, p10: x.p10, p50: x.p50, p90: x.p90,
      bandFloor: x.p10,
      bandRange: (x.p90 != null && x.p10 != null) ? Math.max(0, x.p90 - x.p10) : null,
    }));
  }, [rows, sel]);

  // All-model P50 overlay (disagreement view)
  const compare = useMemo(() => {
    const byDate = {};
    for (const x of rows) {
      if (!byDate[x.ds]) byDate[x.ds] = { date: x.ds };
      byDate[x.ds][x.model] = x.p50;
    }
    return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
  }, [rows]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Model Lab — {product} · V5 forecast models
        </span>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 20,
                       color: isDemo ? '#f59e0b' : '#10b981',
                       background: isDemo ? 'rgba(245,158,11,0.08)' : 'rgba(16,185,129,0.1)',
                       border: `1px solid ${isDemo ? 'rgba(245,158,11,0.2)' : 'rgba(16,185,129,0.3)'}` }}>
          {isDemo ? 'DEMO' : 'LIVE'}
        </span>
        {data?.run_date && <span style={{ fontSize: 10, color: '#475569' }}>run {String(data.run_date).slice(0,10)}</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {[{k:'total',l:'Total'},{k:'market',l:'By Market'}].map(g => (
            <button key={g.k} onClick={() => setGrain(g.k)} style={pillStyle(grain === g.k, '#3b82f6')}>{g.l}</button>
          ))}
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.5, marginTop: -6 }}>
        Sourced from the V5 notebooks' output tables (weekly run). Each model carries its <b style={{color:'#94a3b8'}}>own</b> P10–P90
        band, so switching model changes the uncertainty range, not just the center line.
        {grain === 'market' && salesMarket && salesMarket !== 'All' ? ` Region: ${salesMarket}.` : ''}
      </div>

      {mlError && (
        <div style={{ padding: '14px', borderRadius: 8, color: '#ef4444', background: 'rgba(239,68,68,0.06)', fontSize: 12 }}>⚠ {mlError}</div>
      )}

      {/* Model selector pills */}
      {models.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {models.map((m) => (
            <button key={m} onClick={() => setSel(m)} style={pillStyle(sel === m, colorOf[m])}>{mlLabel(m)}</button>
          ))}
        </div>
      )}

      <CardWrap downloadName={`model_lab_${product}_${sel || ''}`}>
        <SectionTitle>{mlLabel(sel)} — Forecast with its own confidence band</SectionTitle>
        {mlLoading ? <Skeleton height={300} /> : fan.length === 0 ? (
          <EmptyState message="No model forecast for this selection yet" />
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={fan} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="mlBand" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={colorOf[sel] || '#3b82f6'} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={colorOf[sel] || '#3b82f6'} stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={78}
                     label={{ value: 'Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
              <Tooltip content={<DarkTip />} />
              <Area type="monotone" dataKey="bandFloor" stackId="mlb" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} name="P10" />
              <Area type="monotone" dataKey="bandRange" stackId="mlb" stroke="none" fill="url(#mlBand)" legendType="none" connectNulls dot={false} name="P10–P90 range" />
              <Line type="monotone" dataKey="p50" name="Most Likely (P50)" stroke={colorOf[sel] || '#e2e8f0'} strokeWidth={2.5} dot={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </CardWrap>

      <CardWrap downloadName={`model_lab_${product}_comparison`}>
        <SectionTitle>Model Comparison — where the models agree & disagree (P50)</SectionTitle>
        {mlLoading ? <Skeleton height={240} /> : compare.length === 0 ? (
          <EmptyState message="No model data for this selection yet" />
        ) : (
          <>
            <div style={{ fontSize: 10, color: '#475569', marginBottom: 8, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              {models.map((m) => (
                <span key={m}><span style={{ color: colorOf[m] }}>─</span> {mlLabel(m)}</span>
              ))}
            </div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={compare} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={72} />
                <Tooltip content={<DarkTip />} />
                {models.map((m) => (
                  <Line key={m} type="monotone" dataKey={m} name={mlLabel(m)} stroke={colorOf[m]}
                        strokeWidth={m === 'Adaptive_Ensemble' ? 3 : 1.5}
                        strokeDasharray={m === 'Adaptive_Ensemble' ? undefined : '4 3'} dot={false} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </>
        )}
      </CardWrap>
    </div>
  );
};

// ── Main panel ────────────────────────────────────────────────────────────────
const TABS       = ['Overview', 'Multi-Year', 'By Product', 'Monthly', 'Accuracy', 'Model Lab', 'AI Insights', 'Exec Mode'];
// 6 notebook models: Adaptive_Ensemble, Prophet_trend, ETS, LightGBM (Global_LGB_Q50), MSTL_v2, DHR_ARIMA
// Chronos removed — not in model suite (arr_chronos / mape_chronos are NULL in live data)
const MODELS     = ['ensemble', 'prophet', 'ets', 'mstl_v2', 'dhr_arima', 'lightgbm'];
const PROD_LINES = ['All', 'UCC', 'ITSG'];
const FC_TYPES   = [{ key: 'rolling', label: '13-Week Quarter' }, { key: 'roy', label: 'Rest of Year' }];

const _toIsoDate = (d) => {
  const dt = new Date(d);
  const y = dt.getUTCFullYear();
  const m = String(dt.getUTCMonth() + 1).padStart(2, '0');
  const day = String(dt.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const _buildDemoWeekly = (forecastType) => {
  const now = new Date();
  const rows = [];
  const actualWeeks = 14;
  const forecastWeeks = forecastType === 'roy' ? 18 : 13;
  const base = 11_500_000;

  for (let i = actualWeeks - 1; i >= 0; i -= 1) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - i * 7);
    const val = base + (actualWeeks - i) * 110_000 + (Math.sin(i / 2) * 150_000);
    rows.push({
      date: _toIsoDate(d),
      arr_actual: Math.round(val),
      arr_worst: null,
      arr_likely: null,
      arr_best: null,
    });
  }

  const fcBase = rows.length ? rows[rows.length - 1].arr_actual : base;
  for (let i = 1; i <= forecastWeeks; i += 1) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() + i * 7);
    const likely = fcBase + i * 130_000 + (Math.sin(i / 3) * 120_000);
    rows.push({
      date: _toIsoDate(d),
      arr_actual: null,
      arr_worst: Math.round(likely * 0.93),
      arr_likely: Math.round(likely),
      arr_best: Math.round(likely * 1.08),
    });
  }

  return rows;
};

const _buildDemoYtd = (weeklyRows) => {
  let ytdActual = 0;
  let ytdWorst = 0;
  let ytdLikely = 0;
  let ytdBest = 0;

  return weeklyRows.map((r) => {
    if (r.arr_actual != null) ytdActual += r.arr_actual;
    if (r.arr_worst != null) ytdWorst += r.arr_worst;
    if (r.arr_likely != null) ytdLikely += r.arr_likely;
    if (r.arr_best != null) ytdBest += r.arr_best;
    return {
      date: r.date,
      ytd_actual: r.arr_actual != null ? Math.round(ytdActual) : null,
      ytd_worst: r.arr_worst != null ? Math.round(ytdWorst) : null,
      ytd_likely: r.arr_likely != null ? Math.round(ytdLikely) : null,
      ytd_best: r.arr_best != null ? Math.round(ytdBest) : null,
    };
  });
};

const _buildDemoMonthly = () => {
  const months = [
    { year: 2026, quarter: 2, month: 6, month_name: 'June' },
    { year: 2026, quarter: 3, month: 7, month_name: 'July' },
    { year: 2026, quarter: 3, month: 8, month_name: 'August' },
    { year: 2026, quarter: 3, month: 9, month_name: 'September' },
  ];
  return months.map((m, idx) => ({
    ...m,
    arr_actual: idx === 0 ? 44_200_000 : null,
    arr_worst: 40_500_000 + idx * 1_050_000,
    arr_likely: 43_100_000 + idx * 1_180_000,
    arr_best: 46_000_000 + idx * 1_260_000,
  }));
};

const _buildDemoHistorical = () => {
  const rows = [];
  const years = [2024, 2025, 2026];
  years.forEach((y, yi) => {
    for (let w = 1; w <= 52; w += 1) {
      const seasonal = Math.sin((w / 52) * Math.PI * 2) * 1_400_000;
      const trend = yi * 900_000;
      rows.push({
        date: `${y}-${String(Math.min(12, Math.ceil(w / 4))).padStart(2, '0')}-01`,
        year: y,
        iso_week: w,
        quarter: Math.ceil(w / 13),
        arr: Math.round(31_000_000 + seasonal + trend),
      });
    }
  });
  return rows;
};

const _buildDemoByProduct = () => ({
  by_product: [
    { product: 'ITSG', product_line: 'ITSG', arr_worst: 122_000_000, arr_likely: 136_000_000, arr_best: 147_000_000, best_mape: 12.4 },
    { product: 'UCC', product_line: 'UCC', arr_worst: 108_000_000, arr_likely: 121_000_000, arr_best: 133_000_000, best_mape: 11.1 },
  ],
  by_product_line: [
    { product: 'ITSG', product_line: 'ITSG', arr_worst: 122_000_000, arr_likely: 136_000_000, arr_best: 147_000_000, best_mape: 12.4 },
    { product: 'UCC', product_line: 'UCC', arr_worst: 108_000_000, arr_likely: 121_000_000, arr_best: 133_000_000, best_mape: 11.1 },
  ],
  by_geo: [
    { sales_market: 'NA', arr_worst: 88_000_000, arr_likely: 99_000_000, arr_best: 109_000_000 },
    { sales_market: 'EMEA', arr_worst: 55_000_000, arr_likely: 63_000_000, arr_best: 70_000_000 },
    { sales_market: 'APAC', arr_worst: 44_000_000, arr_likely: 49_000_000, arr_best: 55_000_000 },
    { sales_market: 'LATAM', arr_worst: 29_000_000, arr_likely: 33_000_000, arr_best: 38_000_000 },
  ],
});

// Demo leaderboard mirrors the exact holdout WAPE values from UCC Foundation V8 + ITSG Growth V4
// Models: Prophet (→Prophet_trend), MSTL_v2, ETS, DHR_ARIMA, LightGBM (→Global_LGB_Q50)
// Chronos column removed — not in model suite; best_model uses Prophet for UCC (14.4% WAPE)
const _buildDemoLeaderboard = () => [
  { product: 'Total', sales_market: 'Total', Ensemble: 14.8, ETS: 17.1, Prophet: 16.2, MSTL_v2: 19.8, DHR_ARIMA: 23.6, LightGBM: 18.3, best_mape: 16.2, best_model: 'Prophet' },
  { product: 'UCC',   sales_market: 'Total', ETS: 15.6, Prophet: 14.4, MSTL_v2: 17.0, DHR_ARIMA: 22.5, LightGBM: 20.7, best_mape: 14.4, best_model: 'Prophet' },
  { product: 'ITSG',  sales_market: 'Total', ETS: 34.1, Prophet: 35.3, MSTL_v2: 40.8, DHR_ARIMA: 40.0, LightGBM: 117.0, best_mape: 34.1, best_model: 'ETS' },
  { product: 'Total', sales_market: 'NA',   ETS: 17.5, Prophet: 16.7, MSTL_v2: 20.1, DHR_ARIMA: 24.0, LightGBM: 18.8, best_mape: 16.7, best_model: 'Prophet' },
  { product: 'Total', sales_market: 'EMEA', ETS: 18.2, Prophet: 17.1, MSTL_v2: 21.3, DHR_ARIMA: 25.1, LightGBM: 19.4, best_mape: 17.1, best_model: 'Prophet' },
  { product: 'Total', sales_market: 'APAC', ETS: 19.4, Prophet: 18.3, MSTL_v2: 22.6, DHR_ARIMA: 26.7, LightGBM: 20.9, best_mape: 18.3, best_model: 'Prophet' },
  { product: 'Total', sales_market: 'LATAM', ETS: 20.1, Prophet: 19.0, MSTL_v2: 23.4, DHR_ARIMA: 27.5, LightGBM: 21.7, best_mape: 19.0, best_model: 'Prophet' },
  { product: 'UCC',   sales_market: 'NA',   ETS: 15.1, Prophet: 13.9, MSTL_v2: 16.4, DHR_ARIMA: 21.8, LightGBM: 19.9, best_mape: 13.9, best_model: 'Prophet' },
];

const ForecastingPanel = () => {
  const [tab,         setTab]         = useState('Overview');
  const [model,       setModel]       = useState('ensemble');
  const [fcType,      setFcType]      = useState('rolling');
  const [prodLine,    setProdLine]    = useState('All');
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [selectedQuarter, setSelectedQuarter] = useState(null);
  const [multiYearView, setMultiYearView] = useState('overlay'); // 'overlay' | 'timeline'
  const [modelsOpen, setModelsOpen] = useState(false); // non-ensemble model pills expanded
  const [salesMarket, setSalesMarket] = useState('All'); // region filter (All/NA/EMEA/APAC/LATAM)

  const [weekly,      setWeekly]      = useState(null);
  const [weeklyKpis,  setWeeklyKpis]  = useState(null);
  const [ytd,         setYtd]         = useState(null);
  const [historical,  setHistorical]  = useState(null);
  const [byProduct,   setByProduct]   = useState(null);
  const [monthly,     setMonthly]     = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [modelRegistry, setModelRegistry] = useState([]);
  const [freshness,   setFreshness]   = useState(null);
  const [confidence,  setConfidence]  = useState(null);
  const [driverBridge, setDriverBridge] = useState(null);
  const [riskRadar,   setRiskRadar]   = useState([]);
  const [meetingMode, setMeetingMode] = useState(null);
  const [confidenceBands, setConfidenceBands] = useState(null);
  const [trust,       setTrust]       = useState(null);   // band-coverage stats (backtest @4wk)
  const [runDelta,    setRunDelta]    = useState(null);   // what changed since last run
  const [actions,     setActions]     = useState([]);
  const [governanceLog, setGovernanceLog] = useState([]);
  const [actionDraft, setActionDraft] = useState({ text: '', owner: '', due_date: '', playbook_action: '', priority: 'medium' });
  const [decisionDraft, setDecisionDraft] = useState({ decision: '', owner: '', expected_impact: '', reason: '' });
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState(null);
  const [source,      setSource]      = useState(null);

  const [simWinRate, setSimWinRate] = useState(31.8);
  const [simCycle, setSimCycle] = useState(45);
  const [simDealSize, setSimDealSize] = useState(1.0);
  const [simCoverage, setSimCoverage] = useState(3.2);

  const activePl = prodLine !== 'All' ? prodLine : null;
  const activeGeo = salesMarket !== 'All' ? salesMarket : null;

  const fetchAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [wk, yt, hs, bp, mo, lb, modelsRes, fr, conf, bridge, radar, meeting, act, gov, cb, bt, rd] = await Promise.allSettled([
        apiService.getForecastV2Weekly(model, fcType, null, activePl, activeGeo, selectedYear, selectedQuarter),
        apiService.getForecastV2YTD(fcType, null, activePl, activeGeo, selectedYear, selectedQuarter, model),
        apiService.getForecastV2Historical(null, activePl, activeGeo),     // omit year → backend returns 3-year window
        apiService.getForecastV2ByProduct(model, fcType, null, activePl, activeGeo, selectedYear, selectedQuarter),
        apiService.getForecastV2Monthly(fcType, null, activePl, activeGeo, selectedYear, selectedQuarter, model),
        apiService.getForecastV2Leaderboard(),
        apiService.getForecastV2Models(),
        apiService.getForecastV2Freshness(),
        apiService.getForecastV2Confidence(model, selectedYear, selectedQuarter),
        apiService.getForecastV2DriverBridge(selectedYear, selectedQuarter, model),
        apiService.getForecastV2RiskRadar(fcType, selectedYear, selectedQuarter, 20, model),
        apiService.getForecastV2MeetingMode(model, selectedYear, selectedQuarter),
        apiService.getActions('pending'),
        apiService.getForecastV2GovernanceLog(),
        apiService.getForecastV2ConfidenceBands(fcType, activePl, selectedYear, selectedQuarter, model),
        apiService.getForecastV2Backtest(4, model, activePl, activeGeo),
        apiService.getForecastV2RunDelta(activePl, activeGeo),
      ]);
      if (wk.status === 'fulfilled') {
        setWeekly(wk.value?.rows ?? []);
        setWeeklyKpis(wk.value?.kpis ?? null);
        setSource(wk.value?.source ?? null);
        if ((wk.value?.source ?? null) === 'demo' && wk.value?.error) {
          setError(`Forecast data fallback: ${wk.value.error}`);
        }
      }
      if (yt.status === 'fulfilled') setYtd(yt.value?.rows ?? []);
      if (hs.status === 'fulfilled') setHistorical(hs.value?.rows ?? []);
      if (bp.status === 'fulfilled') setByProduct(bp.value ?? null);
      if (mo.status === 'fulfilled') setMonthly(mo.value?.months ?? []);
      if (lb.status === 'fulfilled') setLeaderboard(lb.value?.data ?? []);
      if (modelsRes.status === 'fulfilled') setModelRegistry(modelsRes.value?.models ?? []);
      if (fr.status === 'fulfilled') setFreshness(fr.value ?? null);
      if (conf.status === 'fulfilled') setConfidence(conf.value ?? null);
      if (bridge.status === 'fulfilled') setDriverBridge(bridge.value ?? null);
      if (radar.status === 'fulfilled') setRiskRadar(radar.value?.items ?? []);
      if (meeting.status === 'fulfilled') setMeetingMode(meeting.value ?? null);
      if (act.status === 'fulfilled') setActions(act.value?.data ?? []);
      if (gov.status === 'fulfilled') setGovernanceLog(gov.value?.data ?? []);
      if (cb.status === 'fulfilled') setConfidenceBands(cb.value ?? null);
      if (bt.status === 'fulfilled') setTrust(bt.value ?? null);
      if (rd.status === 'fulfilled') setRunDelta(rd.value ?? null);

      const firstReject = [wk, yt].find(r => r.status === 'rejected');
      if (firstReject) {
        setSource('demo');
        setError(firstReject.reason?.message || 'Some endpoints failed to load');
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, fcType, activePl, activeGeo, selectedYear, selectedQuarter]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const activeModelMeta = useMemo(() => (
    (modelRegistry || []).find((entry) => entry.key === model) || null
  ), [modelRegistry, model]);

  const activeModelDisplay = activeModelMeta?.display_name || (model.charAt(0).toUpperCase() + model.slice(1));
  const activeModelFreshness = activeModelMeta?.freshness || activeModelMeta?.latest_refresh || null;

  const pill = (active, color) => ({
    padding: '4px 11px', borderRadius: 999, fontSize: 10, fontWeight: 700,
    cursor: 'pointer', transition: 'all 0.15s ease', display: 'flex', alignItems: 'center', gap: 5,
    border:      `1px solid ${active ? (color ?? 'rgba(255,255,255,0.4)') : 'rgba(255,255,255,0.08)'}`,
    background:  active ? `${(color ?? '#ffffff')}1a` : 'rgba(255,255,255,0.03)',
    color:       active ? (color ?? '#f1f5f9') : '#475569',
  });

  const isDemo  = source !== 'live';
  const demoPayload = useMemo(() => {
    const dWeekly = _buildDemoWeekly(fcType);
    return {
      weekly: dWeekly,
      ytd: _buildDemoYtd(dWeekly),
      monthly: _buildDemoMonthly(),
      historical: _buildDemoHistorical(),
      byProduct: _buildDemoByProduct(),
      leaderboard: _buildDemoLeaderboard(),
    };
  }, [fcType]);

  const weeklyView = (weekly && weekly.length > 0) ? weekly : (isDemo ? demoPayload.weekly : []);
  const ytdView = (ytd && ytd.length > 0) ? ytd : (isDemo ? demoPayload.ytd : []);
  const monthlyView = (monthly && monthly.length > 0) ? monthly : (isDemo ? demoPayload.monthly : []);
  const historicalView = (historical && historical.length > 0) ? historical : (isDemo ? demoPayload.historical : []);
  const byProductView = (byProduct && byProduct.by_product?.length > 0) ? byProduct : (isDemo ? demoPayload.byProduct : null);
  const leaderboardView = (leaderboard && leaderboard.length > 0) ? leaderboard : demoPayload.leaderboard;

  const graphInsights = useMemo(() => {
    const insight = {
      weekly: null,
      ytd: null,
      seasonality: null,
      trend: null,
      byProduct: null,
      monthly: null,
      accuracy: null,
    };

    const actuals = (weeklyView || []).filter((r) => r.arr_actual != null);
    const forecast = (weeklyView || []).filter((r) => r.arr_likely != null);
    if (actuals.length && forecast.length) {
      const first = Number(actuals[0].arr_actual || 0);
      const last = Number(actuals[actuals.length - 1].arr_actual || 0);
      const trendPct = first > 0 ? ((last - first) / first) * 100 : 0;
      const avgBandPct = forecast.length
        ? forecast.reduce((s, r) => {
            const likely = Number(r.arr_likely || 0);
            const spread = Number(r.arr_best || 0) - Number(r.arr_worst || 0);
            return s + (likely > 0 ? (spread / likely) * 100 : 0);
          }, 0) / forecast.length
        : 0;
      const quarterText = selectedQuarter ? `Q${selectedQuarter}` : 'all quarters';
      insight.weekly = `Actuals trend ${trendPct >= 0 ? 'up' : 'down'} ${Math.abs(trendPct).toFixed(1)}% through ${quarterText} ${selectedYear}. Most-likely forecast sits inside an average confidence band of ${Math.max(0, avgBandPct).toFixed(1)}%.`;
    }

    const ytdRows = (ytdView || []).filter((r) => r.ytd_actual != null || r.ytd_likely != null);
    if (ytdRows.length) {
      const lastActual = [...ytdRows].reverse().find((r) => r.ytd_actual != null)?.ytd_actual ?? null;
      const lastLikely = [...ytdRows].reverse().find((r) => r.ytd_likely != null)?.ytd_likely ?? null;
      const gap = (lastLikely != null && lastActual != null) ? Number(lastLikely) - Number(lastActual) : null;
      insight.ytd = gap == null
        ? `YTD curve is tracking with current selection (${selectedYear}${selectedQuarter ? `, Q${selectedQuarter}` : ''}).`
        : `YTD actual is ${fmtM(lastActual)} versus likely path ${fmtM(lastLikely)}, a ${gap >= 0 ? 'remaining upside' : 'shortfall'} of ${fmtM(Math.abs(gap))}.`;
    }

    const histRows = historicalView || [];
    if (histRows.length) {
      const totalsByYear = histRows.reduce((acc, r) => {
        const y = Number(r.year);
        acc[y] = (acc[y] || 0) + Number(r.arr || 0);
        return acc;
      }, {});
      const years = Object.keys(totalsByYear).map(Number).sort((a, b) => a - b);
      const curr = totalsByYear[selectedYear] || null;
      const prevYear = years.filter((y) => y < selectedYear).slice(-1)[0];
      const prev = prevYear ? totalsByYear[prevYear] : null;
      if (curr != null && prev != null && prev > 0) {
        const yoy = ((curr - prev) / prev) * 100;
        insight.seasonality = `${selectedYear} seasonal run-rate is ${yoy >= 0 ? 'above' : 'below'} prior year by ${Math.abs(yoy).toFixed(1)}%, showing where weekly demand is accelerating or flattening.`;
      } else {
        insight.seasonality = `Seasonality chart highlights recurring weekly peaks and troughs for ${selectedYear} to guide quarter pacing.`;
      }

      const vals = histRows.map((r) => Number(r.arr || 0)).filter((v) => Number.isFinite(v));
      if (vals.length > 5) {
        const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
        const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length;
        const cv = mean > 0 ? (Math.sqrt(variance) / mean) * 100 : 0;
        insight.trend = `Weekly trend volatility is ${cv.toFixed(1)}% of the mean, which indicates ${cv > 18 ? 'higher forecasting risk' : 'stable execution'} across the selected horizon.`;
      }
    }

    const lines = byProductView?.by_product_line || byProductView?.by_product || [];
    if (lines.length) {
      const sorted = [...lines].sort((a, b) => Number(b.arr_likely || 0) - Number(a.arr_likely || 0));
      const lead = sorted[0];
      const second = sorted[1];
      const gap = second ? Number(lead.arr_likely || 0) - Number(second.arr_likely || 0) : null;
      insight.byProduct = gap == null
        ? `${lead.product_line || lead.product} is the primary contributor in the current forecast mix.`
        : `${lead.product_line || lead.product} leads forecast mix at ${fmtM(lead.arr_likely)}, ahead of ${second.product_line || second.product} by ${fmtM(Math.abs(gap))}.`;
    }

    const monthRows = monthlyView || [];
    if (monthRows.length) {
      const totalLikely = monthRows.reduce((s, m) => s + Number(m.arr_likely || 0), 0);
      const totalActual = monthRows.reduce((s, m) => s + Number(m.arr_actual || 0), 0);
      const openMonths = monthRows.filter((m) => !m.arr_actual).length;
      insight.monthly = `Monthly view shows ${fmtM(totalActual)} realized and ${fmtM(totalLikely)} likely for ${selectedYear}${selectedQuarter ? ` Q${selectedQuarter}` : ''}, with ${openMonths} month(s) still forecast-driven.`;
    }

    const totalRow = (leaderboardView || []).find((r) =>
      (r.product === 'Total' || r.product === 'All') &&
      (r.sales_market === 'Total' || r.sales_market === 'All')
    );
    if (totalRow) {
      const models = [
        { name: 'ETS',      val: Number(totalRow.ETS      || Infinity) },
        { name: 'Prophet',  val: Number(totalRow.Prophet  || Infinity) },
        { name: 'LightGBM', val: Number(totalRow.LightGBM || Infinity) },
        { name: 'MSTL_v2',  val: Number(totalRow.MSTL_v2  || Infinity) },
        { name: 'DHR_ARIMA',val: Number(totalRow.DHR_ARIMA|| Infinity) },
        // Chronos excluded — not in notebook model suite
      ].filter((m) => Number.isFinite(m.val) && m.val < 999);
      const best = [...models].sort((a, b) => a.val - b.val)[0];
      if (best) {
        insight.accuracy = `${formatModelLabel(best.name)} is currently the most accurate model at ${best.val.toFixed(1)}% MAPE on the total slice; use it as the tie-breaker when scenario ranges are wide.`;
      }
    }

    return insight;
  }, [weeklyView, ytdView, historicalView, byProductView, monthlyView, leaderboardView, selectedYear, selectedQuarter]);

  // Per-model MAPE for pill badges (Total/All slice)
  const modelMapes = useMemo(() => {
    const totalRow = (leaderboardView || []).find(r =>
      (r.product === 'Total' || r.product === 'All') &&
      (r.sales_market === 'Total' || r.sales_market === 'All')
    );
    return totalRow
      ? { ETS: totalRow.ETS, Prophet: totalRow.Prophet, LightGBM: totalRow.LightGBM, MSTL_v2: totalRow.MSTL_v2, DHR_ARIMA: totalRow.DHR_ARIMA, Ensemble: totalRow.Ensemble }
      : {};
  }, [leaderboardView]);

  const isEmpty = !loading && weeklyView !== null && weeklyView.length === 0;

  const simulatedScenario = useMemo(() => {
    const baseLikely = (weeklyView || []).filter((r) => r.arr_likely != null).reduce((s, r) => s + Number(r.arr_likely || 0), 0);
    if (!baseLikely) return { base: 0, worst: 0, best: 0 };
    const winFactor = simWinRate / 31.8;
    const cycleFactor = 45 / Math.max(20, simCycle);
    const dealFactor = simDealSize;
    const covFactor = simCoverage / 3.2;
    const multiplier = winFactor * cycleFactor * dealFactor * covFactor;
    const base = baseLikely * multiplier;
    return {
      base,
      worst: base * 0.92,
      best: base * 1.08,
    };
  }, [weeklyView, simWinRate, simCycle, simDealSize, simCoverage]);

  const refreshActionData = useCallback(async () => {
    try {
      const [act, gov] = await Promise.allSettled([
        apiService.getActions('pending'),
        apiService.getForecastV2GovernanceLog(),
      ]);
      if (act.status === 'fulfilled') setActions(act.value?.data ?? []);
      if (gov.status === 'fulfilled') setGovernanceLog(gov.value?.data ?? []);
    } catch (_e) {
      // noop — keep existing state for unauthenticated contexts
    }
  }, []);

  const submitAction = useCallback(async () => {
    if (!actionDraft.text?.trim()) return;
    try {
      await apiService.createAction({
        text: actionDraft.text.trim(),
        owner: actionDraft.owner || null,
        priority: actionDraft.priority || 'medium',
        source: 'forecast',
        due_date: actionDraft.due_date || null,
        playbook_action: actionDraft.playbook_action || null,
      });
      setActionDraft({ text: '', owner: '', due_date: '', playbook_action: '', priority: 'medium' });
      refreshActionData();
    } catch (_e) {
      setError('Unable to create action. Please verify authentication context.');
    }
  }, [actionDraft, refreshActionData]);

  const markActionDone = useCallback(async (actionId) => {
    try {
      await apiService.updateActionStatus(actionId, 'done');
      refreshActionData();
    } catch (_e) {
      setError('Unable to update action status.');
    }
  }, [refreshActionData]);

  const submitDecisionLog = useCallback(async () => {
    if (!decisionDraft.decision?.trim()) return;
    try {
      await apiService.createForecastV2GovernanceLog({
        decision: decisionDraft.decision.trim(),
        owner: decisionDraft.owner || null,
        expected_impact: decisionDraft.expected_impact ? Number(decisionDraft.expected_impact) : null,
        reason: decisionDraft.reason || null,
        scenario_name: `${selectedYear}${selectedQuarter ? `-Q${selectedQuarter}` : '-All'}`,
      });
      setDecisionDraft({ decision: '', owner: '', expected_impact: '', reason: '' });
      refreshActionData();
    } catch (_e) {
      setError('Unable to write governance log. Please verify authentication context.');
    }
  }, [decisionDraft, refreshActionData, selectedQuarter, selectedYear]);

  return (
    <div style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    marginBottom: 14, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary, #f1f5f9)', letterSpacing: -0.5 }}>
              ARR Forecast
            </span>
            <span style={{
              fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', padding: '2px 8px', borderRadius: 20,
              color:      source === 'live' ? '#10b981' : source === 'demo' ? '#f59e0b' : '#475569',
              background: source === 'live' ? 'rgba(16,185,129,0.1)' : source === 'demo' ? 'rgba(245,158,11,0.08)' : 'rgba(255,255,255,0.04)',
              border:     source === 'live' ? '1px solid rgba(16,185,129,0.3)' : source === 'demo' ? '1px solid rgba(245,158,11,0.2)' : '1px solid rgba(255,255,255,0.08)',
            }}>
              {source === 'live' ? 'LIVE' : source === 'demo' ? 'DEMO' : '—'}
            </span>
            {(freshness?.freshness || activeModelFreshness) && (
              <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>
                as of {freshness?.freshness || activeModelFreshness}
              </span>
            )}
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 3 }}>
            {activeModelDisplay} · Growth ARR
          </div>
        </div>
        <button onClick={fetchAll} disabled={loading}
          style={{ padding: '5px 14px', borderRadius: 8, fontSize: 11, fontWeight: 600,
                   background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.25)',
                   color: '#3b82f6', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.5 : 1 }}>
          {loading ? '⟳ Loading…' : '⟳ Refresh'}
        </button>
      </div>

      {/* ── Controls ───────────────────────────────────────────────────────── */}
      <div style={{ padding: '10px 14px', marginBottom: 10, borderRadius: 10,
                    background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
                    display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        {/* ── Group 1: PRODUCT (leftmost — the first thing leadership scans) ── */}
        <div>
          <div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>PRODUCT</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {PROD_LINES.map(pl => (
              <button key={pl} onClick={() => setProdLine(pl)}
                style={pill(prodLine === pl, pl === 'UCC' ? '#3b82f6' : pl === 'ITSG' ? '#10b981' : null)}>
                {pl}
              </button>
            ))}
          </div>
        </div>
        <div style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />

        {/* ── Group 1b: REGION (sales_market slice from the forecast table) ── */}
        <div>
          <div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>REGION</div>
          <select value={salesMarket} onChange={(e) => setSalesMarket(e.target.value)}
            style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                     color: '#f1f5f9', fontSize: 11, cursor: 'pointer' }}>
            <option value="All">All Regions</option>
            <option value="NA">NA</option>
            <option value="EMEA">EMEA</option>
            <option value="APAC">APAC</option>
            <option value="LATAM">LATAM</option>
          </select>
        </div>
        <div style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />

        {/* ── Group 2: TIME PERIOD (window + year + quarter together) ── */}
        <div>
          <div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>TIME PERIOD</div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            {FC_TYPES.map(f => (
              <button key={f.key} onClick={() => setFcType(f.key)} style={pill(fcType === f.key, '#3b82f6')}>{f.label}</button>
            ))}
            <select value={selectedYear} onChange={(e) => setSelectedYear(Number(e.target.value))}
              style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                       color: '#f1f5f9', fontSize: 11, cursor: 'pointer' }}>
              {[2026, 2025, 2024, 2023].map(yr => <option key={yr} value={yr}>{yr}</option>)}
            </select>
            <select value={selectedQuarter || ''} onChange={(e) => setSelectedQuarter(e.target.value ? Number(e.target.value) : null)}
              style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                       color: '#f1f5f9', fontSize: 11, cursor: 'pointer' }}>
              <option value="">Full Year</option>
              <option value="1">Q1 (Jan–Mar)</option>
              <option value="2">Q2 (Apr–Jun)</option>
              <option value="3">Q3 (Jul–Sep)</option>
              <option value="4">Q4 (Oct–Dec)</option>
            </select>
          </div>
        </div>
        <div style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />

        {/* ── Group 3: MODEL — Ensemble recommended; others expand on hover/click ── */}
        <div>
          <div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>FORECAST MODEL</div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}
               onMouseLeave={() => setModelsOpen(false)}>
            <button onClick={() => setModel('ensemble')} style={pill(model === 'ensemble', '#00FF88')}>
              Ensemble ★
              <span style={{ fontSize: 8, fontWeight: 600, opacity: 0.8 }}>recommended</span>
              {modelMapes.Ensemble != null && modelMapes.Ensemble < 999 && (
                <span style={{ fontSize: 9, color: model === 'ensemble' ? mapeColor(modelMapes.Ensemble) : '#475569',
                               background: 'rgba(0,0,0,0.2)', padding: '1px 4px', borderRadius: 8 }}>
                  {Number(modelMapes.Ensemble).toFixed(1)}%
                </span>
              )}
            </button>
            {/* Symmetric hover: expands on hover/click, collapses when the pointer
                leaves the group. Stays pinned open while a non-ensemble model is
                selected so the active choice is never hidden. */}
            {(modelsOpen || model !== 'ensemble') ? (
              MODELS.filter(m => m !== 'ensemble').map(m => {
                const meta  = MODEL_KEY_META[m] ?? { label: m, color: '#f1f5f9' };
                const lbKey = MODEL_LB_KEY[m];
                const mape  = lbKey ? modelMapes[lbKey] : null;
                return (
                  <button key={m} onClick={() => setModel(m)} style={pill(model === m, meta.color)}>
                    {meta.label}
                    {mape != null && mape < 999 && (
                      <span style={{ fontSize: 9, color: model === m ? mapeColor(mape) : '#475569',
                                     background: 'rgba(0,0,0,0.2)', padding: '1px 4px', borderRadius: 8 }}>
                        {Number(mape).toFixed(1)}%
                      </span>
                    )}
                  </button>
                );
              })
            ) : (
              <button onClick={() => setModelsOpen(true)} onMouseEnter={() => setModelsOpen(true)}
                title="Show individual models"
                style={{ ...pill(false), color: '#64748b', fontStyle: 'italic' }}>
                other models ▸
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Status banners ─────────────────────────────────────────────────── */}
      {/* Freshness banner only when stale — the healthy-case "as of" date lives in the header */}
      {freshness && freshness.sla_status === 'breached' && (
        <div style={{ padding: '8px 14px', marginBottom: 8, borderRadius: 8, fontSize: 12,
                      color: '#ef4444', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
          ⏱ Forecast data is {freshness.days_stale ?? '—'} day(s) old (last run {freshness.freshness || 'unknown'}) — expected weekly refresh has been missed.
        </div>
      )}
      {isDemo && !loading && (
        <div style={{ padding: '8px 14px', marginBottom: 8, borderRadius: 8, fontSize: 12, color: '#f59e0b',
                      background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)' }}>
          📋 Sample data — forecast job runs Mondays 03:00 UTC. Numbers below are illustrative only.
        </div>
      )}
      {isEmpty && !isDemo && !loading && (
        <div style={{ padding: '8px 14px', marginBottom: 8, borderRadius: 8, fontSize: 12, color: '#64748b',
                      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
          🕐 No forecast data yet — awaiting next scheduled run (Mondays 03:00 UTC).
        </div>
      )}
      {error && (
        <div style={{ padding: '8px 14px', marginBottom: 8, borderRadius: 8, fontSize: 12, color: '#ef4444',
                      background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)' }}>
          ⚠ {error}
        </div>
      )}

      {/* ── Context banner — persistent on every tab ───────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                    padding: '8px 14px', borderRadius: 10, marginBottom: 10,
                    background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.18)' }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: '0.08em' }}>SHOWING</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>
          {prodLine === 'All' ? 'All Products' : prodLine}
        </span>
        <span style={{ color: '#334155' }}>·</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>
          {salesMarket === 'All' ? 'All Regions' : salesMarket}
        </span>
        <span style={{ color: '#334155' }}>·</span>
        <span style={{ fontSize: 12, fontWeight: 800, color: '#93c5fd' }}>
          {selectedQuarter ? `Q${selectedQuarter} ${selectedYear}` : `Full Year ${selectedYear}`}
        </span>
        <span style={{ color: '#334155' }}>·</span>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>
          {FC_TYPES.find(f => f.key === fcType)?.label}
        </span>
        <span style={{ color: '#334155' }}>·</span>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>{activeModelDisplay} model</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: '#475569' }}>
          change via Product / Time Period selectors above
        </span>
      </div>

      {/* ── Tabs ───────────────────────────────────────────────────────────── */}
      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.07)', overflowX: 'auto' }}>
        {TABS.map((t, i) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            tabIndex={tab === t ? 0 : -1}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') { e.preventDefault(); setTab(TABS[(i + 1) % TABS.length]); }
              else if (e.key === 'ArrowLeft') { e.preventDefault(); setTab(TABS[(i - 1 + TABS.length) % TABS.length]); }
              else if (e.key === 'Home') { e.preventDefault(); setTab(TABS[0]); }
              else if (e.key === 'End') { e.preventDefault(); setTab(TABS[TABS.length - 1]); }
            }}
            style={{
              padding: '10px 18px', fontSize: 12, fontWeight: tab === t ? 700 : 500,
              color: tab === t ? '#f1f5f9' : '#475569',
              background: 'transparent', border: 'none', whiteSpace: 'nowrap',
              borderBottom: tab === t ? '2px solid #3b82f6' : '2px solid transparent',
              cursor: 'pointer', transition: 'color 0.15s, border-color 0.15s', outline: 'none',
            }}>
            {t === 'AI Insights'
              ? <>{t} <span style={{ fontSize: 9, color: '#3b82f6', background: 'rgba(59,130,246,0.1)', padding: '1px 5px', borderRadius: 8, marginLeft: 3 }}>AI</span></>
              : t}
          </button>
        ))}
      </div>

      {/* ── Tab content ────────────────────────────────────────────────────── */}
      <div style={{ paddingTop: 16 }}>
        <TabErrorBoundary key={tab}>

          {tab === 'Overview' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Hero KPI cards */}
              {loading
                ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
                    {[0,1,2,3].map(i => <Skeleton key={i} height={72} />)}
                  </div>
                : weeklyView && weeklyView.length > 0 && (() => {
                      // Most Likely = per-model forecast sum from chart rows (arr_likely changes per model pill).
                      // Best/Worst Case = ensemble P10/P90 from backend kpis (constant across models).
                      const kp = weeklyKpis;
                      // Use authoritative backend KPI totals (pre-aggregated server-side,
                      // not summed from weekly chart rows which would over-count ARR weeks)
                      const ml  = kp?.most_likely ?? 0;
                      const bc  = kp?.best_case   ?? 0;
                      const wc  = kp?.worst_case  ?? 0;
                      const ytdActual = kp?.ytd_actuals
                        ?? [...(ytdView || [])].reverse().find(r => r.ytd_actual != null)?.ytd_actual
                        ?? 0;

                      // Period label so each card states what window it covers
                      const periodShort = selectedQuarter ? `Q${selectedQuarter} ${selectedYear}` : `FY ${selectedYear}`;

                      // Detect a fully-closed quarter: Panel Writer sets ML=BC=WC=Actuals
                      // when there are no open forecast weeks in the selection.
                      const isClosed = ml > 0 && ml === bc && ml === wc;

                      if (isClosed) {
                        // Closed quarter — scenario bands are identical to actuals; show a
                        // single consolidated card rather than 4 duplicate tiles.
                        return (
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
                            <div style={{ gridColumn: '1 / 3', background: 'rgba(16,185,129,0.06)',
                                          border: '1px solid rgba(16,185,129,0.25)', borderRadius: 10, padding: '12px 14px' }}>
                              <div style={{ fontSize: 9, color: '#10b981', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Closed Quarter — Actuals</div>
                              <div style={{ fontSize: 22, fontWeight: 800, color: '#10b981', letterSpacing: -0.5, lineHeight: 1 }}>{fmtM(ml)}</div>
                              <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>Q{selectedQuarter ?? ''} {selectedYear} final — scenario bands equal actuals</div>
                            </div>
                            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '12px 14px' }}>
                              <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Actuals YTD</div>
                              <div style={{ fontSize: 22, fontWeight: 800, color: '#f59e0b', letterSpacing: -0.5, lineHeight: 1 }}>{fmtM(ytdActual)}</div>
                              <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>Realized YTD</div>
                            </div>
                            <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: 10, padding: '12px 14px',
                                          display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                              <div style={{ fontSize: 10, color: '#475569', lineHeight: 1.5 }}>
                                Forecast range not available — all {selectedQuarter ? `Q${selectedQuarter}` : 'selected'} weeks are closed actuals.
                                Select a future quarter or <b style={{color:'#f59e0b'}}>Rest of Year</b> to see scenario bands.
                              </div>
                            </div>
                          </div>
                        );
                      }

                      return (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
                          {[
                            { label: 'Most Likely',  val: ml,         color: '#f1f5f9', sub: `${periodShort} outlook — planning center` },
                            { label: 'Stretch Case', val: bc,         color: '#10b981', sub: `${periodShort} · 1-in-5 upside (P90)` },
                            { label: 'Risk Floor',   val: wc,         color: '#ef4444', sub: `${periodShort} · 1-in-10 downside (P10)` },
                            { label: 'Actuals YTD',  val: ytdActual,  color: '#f59e0b', sub: `Realized so far in ${selectedYear}` },
                          ].map(({ label, val, color, sub }) => (
                            <div key={label} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '12px 14px' }}>
                              <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
                              <div style={{ fontSize: 22, fontWeight: 800, color, letterSpacing: -0.5, lineHeight: 1 }}>{fmtM(val)}</div>
                              <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>{sub}</div>
                            </div>
                          ))}
                        </div>
                      );
                  })()
              }

              {/* What changed since last run — compares the two latest retained vintages */}
              {runDelta?.available && runDelta?.total && (() => {
                const d = runDelta.total.delta ?? 0;
                const pct = runDelta.total.delta_pct;
                const isFlat = pct != null && Math.abs(pct) < 0.1;
                const dirColor = isFlat ? '#94a3b8' : d >= 0 ? '#10b981' : '#ef4444';
                const arrow = isFlat ? '→' : d >= 0 ? '▲' : '▼';
                return (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
                                padding: '10px 16px', borderRadius: 10,
                                background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}>
                    <div>
                      <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                        Since last forecast run
                        {runDelta.previous_run && runDelta.latest_run &&
                          ` · ${fmtDate(runDelta.previous_run)} → ${fmtDate(runDelta.latest_run)}`}
                      </div>
                      <div style={{ fontSize: 16, fontWeight: 800, color: dirColor }}>
                        {arrow} {isFlat ? 'Essentially unchanged' : `${d >= 0 ? '+' : '−'}${fmtM(Math.abs(d))}`}
                        {pct != null && !isFlat && (
                          <span style={{ fontSize: 11, fontWeight: 600, marginLeft: 6, opacity: 0.8 }}>
                            ({pct > 0 ? '+' : ''}{pct}%)
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 9, color: '#334155', marginTop: 2 }}>
                        Ensemble Most Likely · {runDelta.overlap_weeks} overlapping forecast week(s)
                        {runDelta.source === 'demo' && ' · demo'}
                      </div>
                    </div>
                    {(runDelta.drivers || []).length > 0 && (
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginLeft: 'auto', alignItems: 'center' }}>
                        <span style={{ fontSize: 9, color: '#475569' }}>Biggest moves:</span>
                        {runDelta.drivers.map((dr, i) => (
                          <span key={i} style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 14,
                                                 color: dr.delta >= 0 ? '#10b981' : '#ef4444',
                                                 background: dr.delta >= 0 ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
                                                 border: `1px solid ${dr.delta >= 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)'}` }}>
                            {dr.product}{dr.sales_market !== 'Total' ? `/${dr.sales_market}` : ''} {dr.delta >= 0 ? '+' : '−'}{fmtM(Math.abs(dr.delta))}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })()}

              <CardWrap downloadName="weekly_forecast_vs_actuals">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <SectionTitle>Weekly Forecast vs Actuals</SectionTitle>
                  {(() => {
                    // Interval trust badge — empirical band coverage from /backtest @4wk horizon
                    const cov = trust?.summary?.coverage_pct;
                    const n   = trust?.summary?.weeks_scored;
                    if (cov == null || !n) return null;
                    const covColor = cov >= 70 && cov <= 92 ? '#10b981' : cov >= 50 ? '#f59e0b' : '#ef4444';
                    return (
                      <span title={`Over the last ${n} closed weeks, the actual landed inside the 80% band ${cov}% of the time (forecasts made 4 weeks ahead). Calibrated bands should be near ~80% — much higher means the bands are too wide, much lower means too narrow.`}
                        style={{ fontSize: 10, fontWeight: 700, padding: '3px 10px', borderRadius: 20, marginBottom: 10,
                                 color: covColor, background: `${covColor}14`, border: `1px solid ${covColor}40`,
                                 cursor: 'help', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                        🛡 Bands caught {cov}% of last {n} actuals
                        <span style={{ fontWeight: 400, opacity: 0.75 }}>· target ~80%</span>
                        {trust?.source === 'demo' && <span style={{ fontWeight: 400, opacity: 0.6 }}>· demo</span>}
                      </span>
                    );
                  })()}
                </div>
                <GraphInsight summary={graphInsights.weekly}
                  chartType="weekly_forecast" metricName="Weekly Growth ARR — actuals vs forecast scenarios"
                  dataPoints={weeklyView} />
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                  <span><span style={{ color: '#f59e0b' }}>─</span> Actuals</span>
                  <span><span style={{ color: '#ef4444' }}>- -</span> Risk Floor (1-in-10 downside)</span>
                  <span><span style={{ color: '#ffffff' }}>─</span> Most Likely</span>
                  <span><span style={{ color: '#10b981' }}>- -</span> Stretch Case (1-in-5 upside)</span>
                  <span style={{ color: '#22d3ee' }}>▒ 50% band (approx.)</span>
                  <span style={{ color: '#3b82f6' }}>▒ 80% band (model P10–P90)</span>
                </div>
                {loading ? <Skeleton height={260} /> : weeklyView && weeklyView.length > 0 ? <WeeklyChart rows={weeklyView} /> : <EmptyState />}
              </CardWrap>

              <CardWrap downloadName="ytd_cumulative">
                <SectionTitle>Running Totals — YTD Cumulative</SectionTitle>
                <GraphInsight summary={graphInsights.ytd}
                  chartType="ytd_cumulative" metricName="YTD cumulative Growth ARR — actual vs forecast path"
                  dataPoints={ytdView} />
                {loading ? <Skeleton height={200} /> : ytdView && ytdView.length > 0 ? <RunningTotalsChart rows={ytdView} /> : <EmptyState />}
              </CardWrap>
            </div>
          )}

          {tab === 'Multi-Year' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* View mode toggle */}
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                {[{key:'overlay',label:'Year Overlay (ISO Week)'},{key:'timeline',label:'Timeline View'}].map(v => (
                  <button key={v.key} onClick={() => setMultiYearView(v.key)} style={pill(multiYearView === v.key, '#3b82f6')}>
                    {v.label}
                  </button>
                ))}
                <span style={{ fontSize: 10, color: '#475569', marginLeft: 8 }}>
                  {[...new Set((historicalView||[]).map(r=>r.year))].sort().join(', ')} · {historicalView?.length ?? 0} pts
                </span>
              </div>

              {multiYearView === 'overlay' && (
                <CardWrap downloadName="historical_seasonality">
                  <SectionTitle>Historical Seasonality — by ISO Week (1–52)</SectionTitle>
                  <GraphInsight summary={graphInsights.seasonality}
                    chartType="seasonality_overlay" metricName="Weekly Growth ARR by ISO week across years"
                    dataPoints={historicalView} />
                  <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    {[...new Set((historicalView||[]).map(r=>r.year))].sort().map(yr => (
                      <span key={yr}><span style={{ color: YEAR_COLORS[yr] ?? '#94a3b8' }}>─</span> {yr}</span>
                    ))}
                  </div>
                  {loading ? <Skeleton height={260} /> : historicalView && historicalView.length > 0 ? <MultiYearChart rows={historicalView} /> : <EmptyState />}
                </CardWrap>
              )}

              {multiYearView === 'timeline' && (
                <CardWrap downloadName="historical_trend_timeline">
                  <SectionTitle>Historical Weekly Trend — Timeline</SectionTitle>
                  <GraphInsight summary={graphInsights.trend} />
                  {loading ? <Skeleton height={260} /> : (
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart data={historicalView || []} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                        <XAxis dataKey="date" tickFormatter={d=>d?.slice(0,7)} tick={{ fill:'#475569',fontSize:9 }} axisLine={false} tickLine={false} interval={12} />
                        <YAxis tickFormatter={v=>fmtM(v)} tick={{ fill:'#475569',fontSize:9 }} axisLine={false} tickLine={false} width={58} />
                        <Tooltip content={<DarkTip />} />
                        <Line type="monotone" dataKey="arr" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Weekly ARR" isAnimationActive />
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </CardWrap>
              )}
            </div>
          )}

          {tab === 'By Product' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <CardWrap downloadName="forecast_by_product">
                <SectionTitle>Forecast by Product Line & Product</SectionTitle>
                <GraphInsight summary={graphInsights.byProduct}
                  chartType="by_product_forecast" metricName="Forecast Growth ARR by product line and geo"
                  dataPoints={byProductView?.by_product} />
                {loading ? <Skeleton height={200} /> : byProductView ? <ByProductChart byProduct={byProductView.by_product} byLine={byProductView.by_product_line} /> : <EmptyState />}
              </CardWrap>
              {!loading && byProductView?.by_product && (
                <CardWrap>
                  <SectionTitle>Product Forecast Summary</SectionTitle>
                  <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
                    <thead>
                      <tr style={{ borderBottom:'1px solid rgba(255,255,255,0.08)' }}>
                        {['Product','Line','Worst','Most Likely','Best','Best MAPE'].map(h=>(
                          <th key={h} style={{ padding:'6px 12px', textAlign:['Product','Line'].includes(h)?'left':'right',
                                               fontSize:10, color:'#475569', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {byProductView.by_product.map((p,i)=>(
                        <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.03)', background:i%2===0?'rgba(255,255,255,0.01)':'transparent' }}>
                          <td style={{ padding:'6px 12px', color:'#f1f5f9' }}>{p.product}</td>
                          <td style={{ padding:'6px 12px', color:p.product_line==='UCC'?'#3b82f6':'#10b981', fontWeight:600 }}>{p.product_line}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:'#ef4444' }}>{fmtM(p.arr_worst)}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:'#f1f5f9', fontWeight:700 }}>{fmtM(p.arr_likely)}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:'#10b981' }}>{fmtM(p.arr_best)}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:p.best_mape&&p.best_mape<999?mapeColor(p.best_mape):'#334155', fontWeight:600 }}>
                            {p.best_mape&&p.best_mape<999?`${p.best_mape.toFixed(1)}%`:'—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardWrap>
              )}
              {!loading && byProductView?.by_geo?.length > 0 && (
                <CardWrap downloadName="forecast_by_geography">
                  <SectionTitle>Forecast by Geography</SectionTitle>
                  <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                    <span><span style={{ color: '#ef4444' }}>■</span> Risk Floor</span>
                    <span><span style={{ color: '#ffffff' }}>■</span> Most Likely</span>
                    <span><span style={{ color: '#10b981' }}>■</span> Stretch Case</span>
                  </div>
                  <GeoBarChart rows={byProductView.by_geo} />
                </CardWrap>
              )}
            </div>
          )}

          {tab === 'Monthly' && (
            <CardWrap>
              <SectionTitle>Monthly Actuals vs Forecast Scenarios</SectionTitle>
              <GraphInsight summary={graphInsights.monthly}
                chartType="monthly_forecast" metricName="Monthly Growth ARR — actuals vs forecast scenarios"
                dataPoints={monthlyView} />
              {loading ? <Skeleton height={300} /> : monthlyView && monthlyView.length > 0 ? <MonthlyTable months={monthlyView} /> : <EmptyState />}
            </CardWrap>
          )}

          {tab === 'Accuracy' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[{label:'< 15%',color:'#10b981'},{label:'15–25%',color:'#f59e0b'},{label:'> 25%',color:'#ef4444'}].map(b=>(
                  <div key={b.label} style={{ display:'flex', alignItems:'center', gap:6, fontSize:11, color:'#64748b' }}>
                    <div style={{ width:10, height:10, borderRadius:2, background:b.color }} /> MAPE {b.label}
                  </div>
                ))}
              </div>
              <CardWrap>
                <SectionTitle>Model MAPE Leaderboard — 8-Week Holdout Validation</SectionTitle>
                <GraphInsight summary={graphInsights.accuracy}
                  chartType="model_accuracy_leaderboard" metricName="Model MAPE by product and geo slice"
                  dataPoints={leaderboardView} />
                {loading ? <Skeleton height={240} /> : leaderboardView && leaderboardView.length > 0 ? <AccuracyTable data={leaderboardView} /> : <EmptyState />}
              </CardWrap>
              <BacktestSection model={model} prodLine={prodLine} salesMarket={salesMarket} />
            </div>
          )}

          {tab === 'Model Lab' && (
            <>
              {prodLine === 'All' && (
                <div style={{ padding: '8px 14px', marginBottom: 12, borderRadius: 8, fontSize: 12, color: '#93c5fd',
                              background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}>
                  ℹ Model Lab is per product line (the V5 models run separately for UCC and ITSG).
                  Showing <b>UCC</b> — pick UCC or ITSG in the PRODUCT selector to switch.
                </div>
              )}
              <ModelLabSection product={prodLine === 'ITSG' ? 'ITSG' : 'UCC'} salesMarket={salesMarket} />
            </>
          )}

          {tab === 'AI Insights' && <AiInsightsSection model={model} prodLine={prodLine} />}

          {tab === 'Exec Mode' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

              {/* CI Fan Chart — source: real model P10/P90 from arr_forecast_v2 p10/p90 columns */}
              <CardWrap>
                <SectionTitle>Prediction Interval Fan — Source Model P10 / P50 / P90</SectionTitle>
                {(() => {
                  const cb = confidenceBands;
                  const p10 = cb?.p10  ?? weeklyKpis?.worst_case ?? 0;
                  const p50 = cb?.most_likely ?? weeklyKpis?.most_likely ?? 0;
                  const p90 = cb?.p90  ?? weeklyKpis?.best_case  ?? 0;
                  const isDemo = cb?.source === 'demo' || !cb;
                  const hasData = p50 > 0;
                  const spread = p90 - p10;
                  const maxVal = p90 * 1.08;
                  const bar = (val, color, label, pct) => (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                      <div style={{ width: 96, fontSize: 10, color: '#64748b', textAlign: 'right', flexShrink: 0 }}>{label}</div>
                      <div style={{ flex: 1, height: 24, background: 'rgba(255,255,255,0.04)', borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.4s ease' }} />
                      </div>
                      <div style={{ width: 72, fontSize: 12, fontWeight: 700, color, textAlign: 'right', flexShrink: 0 }}>{fmtM(val)}</div>
                    </div>
                  );
                  return (
                    <div>
                      {isDemo && <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 10, padding: '6px 10px', background: 'rgba(245,158,11,0.08)', borderRadius: 6, border: '1px solid rgba(245,158,11,0.2)' }}>⚠ Demo — run Panel Writer to populate real P10/P90 columns</div>}
                      {!hasData && <div style={{ fontSize: 11, color: '#64748b' }}>No confidence-band data for current selection.</div>}
                      {hasData && (
                        <div>
                          {bar(p10, '#ef4444', 'Risk Floor (P10)',  maxVal > 0 ? (p10 / maxVal) * 100 : 0)}
                          {bar(p50, '#f1f5f9', 'Most Likely (P50)', maxVal > 0 ? (p50 / maxVal) * 100 : 0)}
                          {bar(p90, '#10b981', 'Stretch (P90)',     maxVal > 0 ? (p90 / maxVal) * 100 : 0)}
                          <div style={{ display: 'flex', gap: 20, marginTop: 12, padding: '10px 14px', background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
                            <div style={{ fontSize: 11, color: '#94a3b8' }}>Spread (P10→P90): <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtM(spread)}</span></div>
                            <div style={{ fontSize: 11, color: '#94a3b8' }}>Spread / P50: <span style={{ color: p50 > 0 ? (spread/p50 > 0.3 ? '#ef4444' : spread/p50 > 0.15 ? '#f59e0b' : '#10b981') : '#64748b', fontWeight: 700 }}>{p50 > 0 ? `${((spread/p50)*100).toFixed(1)}%` : '—'}</span></div>
                            <div style={{ fontSize: 11, color: '#94a3b8' }}>Source: <span style={{ color: cb?.source === 'live' ? '#10b981' : '#f59e0b', fontWeight: 700 }}>{cb?.source === 'live' ? 'Live (model P10/P90)' : 'Demo'}</span></div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </CardWrap>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                <CardWrap>
                  <SectionTitle>Forecast Confidence Score</SectionTitle>
                  <div style={{ fontSize: 30, fontWeight: 800, color: confidence?.confidence_score >= 85 ? '#10b981' : confidence?.confidence_score >= 65 ? '#f59e0b' : '#ef4444' }}>
                    {confidence?.confidence_score ?? '—'}
                  </div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{confidence?.confidence_label || 'Unknown'} confidence</div>
                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {(confidence?.reasons || []).slice(0, 3).map((r, i) => (
                      <div key={i} style={{ fontSize: 11, color: '#cbd5e1', lineHeight: 1.5 }}>• {r}</div>
                    ))}
                  </div>
                </CardWrap>

                <CardWrap>
                  <SectionTitle>Meeting Snapshot</SectionTitle>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>Top Moves This Quarter</div>
                  {(meetingMode?.top_moves || []).slice(0, 3).map((m, i) => (
                    <div key={i} style={{ fontSize: 11, color: '#e2e8f0', marginBottom: 6, lineHeight: 1.5 }}>{i + 1}. {m}</div>
                  ))}
                </CardWrap>
              </div>

              <CardWrap>
                <SectionTitle>Driver Bridge (Plan vs Actual)
                  <span style={{ fontSize: 9, color: '#f59e0b', fontWeight: 400, letterSpacing: 0, textTransform: 'none', marginLeft: 8 }}>— Illustrative breakdown; driver attribution requires source data</span>
                </SectionTitle>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginBottom: 10 }}>
                  <div style={{ fontSize: 11, color: '#94a3b8' }}>Plan: <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtM(driverBridge?.plan_total)}</span></div>
                  <div style={{ fontSize: 11, color: '#94a3b8' }}>Actual: <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtM(driverBridge?.actual_total)}</span></div>
                  <div style={{ fontSize: 11, color: '#94a3b8' }}>Variance: <span style={{ color: (driverBridge?.variance || 0) >= 0 ? '#10b981' : '#ef4444', fontWeight: 700 }}>{fmtM(driverBridge?.variance)}</span></div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(driverBridge?.components || []).map((c, i) => {
                    const positive = (c.value || 0) >= 0;
                    const widthPct = Math.min(100, Math.max(4, Math.abs(c.value || 0) / Math.max(1, Math.abs(driverBridge?.variance || 1)) * 100));
                    return (
                      <div key={i} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 100px', gap: 8, alignItems: 'center' }}>
                        <div style={{ fontSize: 11, color: '#cbd5e1' }}>{c.name}</div>
                        <div style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                          <div style={{ width: `${widthPct}%`, height: '100%', background: positive ? '#10b981' : '#ef4444' }} />
                        </div>
                        <div style={{ textAlign: 'right', fontSize: 11, color: positive ? '#10b981' : '#ef4444' }}>{fmtM(c.value)}</div>
                      </div>
                    );
                  })}
                </div>
              </CardWrap>

              <CardWrap>
                <SectionTitle>Pipeline Sensitivity Simulator</SectionTitle>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10 }}>
                  Adjusts pipeline conversion factors relative to baseline — not a direct ARR override. Use as directional sensitivity, not a forecast number.
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Win Rate %: {simWinRate.toFixed(1)}</div>
                    <input type="range" min="15" max="60" step="0.1" value={simWinRate} onChange={(e) => setSimWinRate(Number(e.target.value))} style={{ width: '100%' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Cycle Time Days: {simCycle}</div>
                    <input type="range" min="20" max="120" step="1" value={simCycle} onChange={(e) => setSimCycle(Number(e.target.value))} style={{ width: '100%' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Avg Deal Size Multiplier: {simDealSize.toFixed(2)}x</div>
                    <input type="range" min="0.7" max="1.4" step="0.01" value={simDealSize} onChange={(e) => setSimDealSize(Number(e.target.value))} style={{ width: '100%' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Coverage: {simCoverage.toFixed(1)}x</div>
                    <input type="range" min="1.5" max="5" step="0.1" value={simCoverage} onChange={(e) => setSimCoverage(Number(e.target.value))} style={{ width: '100%' }} />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(120px, 1fr))', gap: 10, marginTop: 12 }}>
                  <div style={{ padding: '10px', borderRadius: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
                    <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 3 }}>Worst</div>
                    <div style={{ fontSize: 17, fontWeight: 700, color: '#ef4444' }}>{fmtM(simulatedScenario.worst)}</div>
                  </div>
                  <div style={{ padding: '10px', borderRadius: 8, background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}>
                    <div style={{ fontSize: 10, color: '#3b82f6', marginBottom: 3 }}>Base</div>
                    <div style={{ fontSize: 17, fontWeight: 700, color: '#93c5fd' }}>{fmtM(simulatedScenario.base)}</div>
                  </div>
                  <div style={{ padding: '10px', borderRadius: 8, background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}>
                    <div style={{ fontSize: 10, color: '#10b981', marginBottom: 3 }}>Best</div>
                    <div style={{ fontSize: 17, fontWeight: 700, color: '#10b981' }}>{fmtM(simulatedScenario.best)}</div>
                  </div>
                </div>
              </CardWrap>

              <CardWrap>
                <SectionTitle>At-Risk ARR Radar (Top 20)</SectionTitle>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                        {['Product', 'Geo', 'Likely', 'Worst', 'Risk Impact', 'Spread %', 'Risk Level'].map((h) => (
                          <th key={h} style={{ padding: '6px 10px', textAlign: ['Product', 'Geo', 'Risk Level'].includes(h) ? 'left' : 'right', fontSize: 10, color: '#64748b' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(riskRadar || []).slice(0, 20).map((r, i) => (
                        <tr key={`${r.product}-${r.sales_market}-${i}`} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={{ padding: '6px 10px', fontSize: 11, color: '#f1f5f9' }}>{r.product}</td>
                          <td style={{ padding: '6px 10px', fontSize: 11, color: '#94a3b8' }}>{r.sales_market}</td>
                          <td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#e2e8f0' }}>{fmtM(r.likely)}</td>
                          <td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#f87171' }}>{fmtM(r.worst)}</td>
                          <td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#ef4444', fontWeight: 700 }}>{fmtM(r.risk_dollar_impact)}</td>
                          <td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#94a3b8' }}>
                            {r.confidence_spread_pct != null ? `${Number(r.confidence_spread_pct).toFixed(1)}%` : '—'}
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 10, color: r.risk_level === 'high' ? '#ef4444' : r.risk_level === 'moderate' ? '#f59e0b' : '#10b981' }}>{String(r.risk_level || '').toUpperCase()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardWrap>

              <CardWrap>
                <SectionTitle>Action Command Center</SectionTitle>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: 8, marginBottom: 10 }}>
                  <input value={actionDraft.text} onChange={(e) => setActionDraft((d) => ({ ...d, text: e.target.value }))} placeholder="Action item" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <input value={actionDraft.owner} onChange={(e) => setActionDraft((d) => ({ ...d, owner: e.target.value }))} placeholder="Owner" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <input type="date" value={actionDraft.due_date} onChange={(e) => setActionDraft((d) => ({ ...d, due_date: e.target.value }))} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <select value={actionDraft.priority} onChange={(e) => setActionDraft((d) => ({ ...d, priority: e.target.value }))} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }}>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                  <button onClick={submitAction} style={{ background: 'rgba(59,130,246,0.16)', border: '1px solid rgba(59,130,246,0.35)', color: '#93c5fd', borderRadius: 6, padding: '6px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>Add</button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(actions || []).slice(0, 12).map((a) => (
                    <div key={a.action_id} style={{ display: 'grid', gridTemplateColumns: '1fr 110px 100px 72px', gap: 8, alignItems: 'center', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ fontSize: 11, color: '#e2e8f0' }}>{a.text}</div>
                      <div style={{ fontSize: 10, color: '#94a3b8' }}>{a.owner || 'Unassigned'}</div>
                      <div style={{ fontSize: 10, color: '#f59e0b' }}>{a.due_date || 'No due date'}</div>
                      <button onClick={() => markActionDone(a.action_id)} style={{ background: 'rgba(16,185,129,0.14)', border: '1px solid rgba(16,185,129,0.35)', color: '#10b981', borderRadius: 6, padding: '5px 8px', fontSize: 10, fontWeight: 700, cursor: 'pointer' }}>Done</button>
                    </div>
                  ))}
                  {(!actions || actions.length === 0) && <div style={{ fontSize: 11, color: '#64748b' }}>No pending actions. Add one above.</div>}
                </div>
              </CardWrap>

              <CardWrap>
                <SectionTitle>Forecast Governance and Audit Trail</SectionTitle>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 2fr auto', gap: 8, marginBottom: 10 }}>
                  <input value={decisionDraft.decision} onChange={(e) => setDecisionDraft((d) => ({ ...d, decision: e.target.value }))} placeholder="Decision / override" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <input value={decisionDraft.owner} onChange={(e) => setDecisionDraft((d) => ({ ...d, owner: e.target.value }))} placeholder="Owner" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <input type="number" value={decisionDraft.expected_impact} onChange={(e) => setDecisionDraft((d) => ({ ...d, expected_impact: e.target.value }))} placeholder="Expected impact" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <input value={decisionDraft.reason} onChange={(e) => setDecisionDraft((d) => ({ ...d, reason: e.target.value }))} placeholder="Reason" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
                  <button onClick={submitDecisionLog} style={{ background: 'rgba(168,85,247,0.16)', border: '1px solid rgba(168,85,247,0.35)', color: '#c4b5fd', borderRadius: 6, padding: '6px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>Log</button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(governanceLog || []).slice(0, 12).map((g) => (
                    <div key={g.id} style={{ border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ fontSize: 11, color: '#f1f5f9', marginBottom: 3 }}>{g.decision}</div>
                      <div style={{ fontSize: 10, color: '#94a3b8' }}>
                        {g.owner || 'Unknown owner'} · {g.created_at ? String(g.created_at).slice(0, 10) : '—'} · Impact {g.expected_impact != null ? fmtM(g.expected_impact) : '—'}
                      </div>
                      {g.reason && <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>{g.reason}</div>}
                    </div>
                  ))}
                  {(!governanceLog || governanceLog.length === 0) && <div style={{ fontSize: 11, color: '#64748b' }}>No governance entries yet.</div>}
                </div>
              </CardWrap>
            </div>
          )}

        </TabErrorBoundary>
      </div>

      <style>{`
        @keyframes fp-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
        [role="tab"]:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }
      `}</style>
    </div>
  );
};

export default ForecastingPanel;
