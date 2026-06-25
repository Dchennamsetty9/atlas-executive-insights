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

import { useState, useEffect, useCallback, useMemo, Component } from 'react';
import {
  ComposedChart, BarChart, LineChart,
  Area, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { apiService } from '../services/api';

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

// ── Colour constants ──────────────────────────────────────────────────────────
const YEAR_COLORS  = { 2022: '#64748b', 2023: '#06b6d4', 2024: '#3b82f6', 2025: '#f59e0b', 2026: '#ef4444' };
const MODEL_COLORS = { ETS: '#94a3b8', Prophet: '#f59e0b', LightGBM: '#3b82f6', Chronos: '#a78bfa', Ensemble: '#00FF88' };
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

const CardWrap = ({ children }) => (
  <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 12, padding: 16 }}>{children}</div>
);

const SectionTitle = ({ children }) => (
  <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase',
                letterSpacing: '0.06em', marginBottom: 10 }}>{children}</div>
);

// ── Chart sub-components ──────────────────────────────────────────────────────
const WeeklyChart = ({ rows }) => {
  const combined = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  // Find the split date where actuals end and forecast begins
  const lastActual = [...combined].reverse().find(r => r.arr_actual != null);
  const splitDate = lastActual?.date ?? null;

  // Build unified dataset — band uses stacking trick: floor (transparent) + range (colored)
  const data = combined.map(r => ({
    date: r.date,
    actual: r.arr_actual ?? null,
    likely: r.arr_likely ?? null,
    worst:  r.arr_worst  ?? null,
    best:   r.arr_best   ?? null,
    bandFloor: r.arr_worst ?? null,
    bandRange: (r.arr_best != null && r.arr_worst != null)
      ? Math.max(0, r.arr_best - r.arr_worst) : null,
  }));

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload || {};
    return (
      <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 10,
                    padding: '12px 16px', fontSize: 11, minWidth: 180 }}>
        <div style={{ color: '#64748b', marginBottom: 8, fontWeight: 600 }}>{label}</div>
        {d.actual  != null && <div style={{ color: '#f59e0b', marginBottom: 3 }}>● Actuals: <b>{fmtM(d.actual)}</b></div>}
        {d.likely  != null && <div style={{ color: '#e2e8f0', marginBottom: 3 }}>● Most Likely: <b>{fmtM(d.likely)}</b></div>}
        {d.best    != null && <div style={{ color: '#10b981', marginBottom: 3 }}>▲ Best Case: <b>{fmtM(d.best)}</b></div>}
        {d.worst   != null && <div style={{ color: '#ef4444', marginBottom: 3 }}>▼ Worst Case: <b>{fmtM(d.worst)}</b></div>}
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
            <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.04} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDate}
               tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false}
               interval="preserveStartEnd" />
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }}
               axisLine={false} tickLine={false} width={64} />
        <Tooltip content={<CustomTooltip />} />
        {splitDate && (
          <ReferenceLine x={splitDate} stroke="rgba(255,255,255,0.18)" strokeDasharray="4 4"
            label={{ value: 'Today →', position: 'insideTopLeft', fill: '#475569', fontSize: 10 }} />
        )}
        {/* Confidence band: transparent floor stacked under colored band */}
        <Area type="monotone" dataKey="bandFloor" stackId="conf" stroke="none" fill="transparent"
              legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="bandRange" stackId="conf" stroke="none" fill="url(#bandFill)"
              legendType="none" connectNulls dot={false} />
        {/* Actuals — gradient fill area */}
        <Area type="monotone" dataKey="actual" stroke="#f59e0b" strokeWidth={2.5}
              fill="url(#actualFill)" dot={false} connectNulls={false} name="Actuals" />
        {/* Forecast lines */}
        <Line type="monotone" dataKey="worst"  name="Worst Case"  stroke="#ef4444"
              strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls />
        <Line type="monotone" dataKey="likely" name="Most Likely" stroke="#e2e8f0"
              strokeWidth={3} dot={false} connectNulls />
        <Line type="monotone" dataKey="best"   name="Best Case"   stroke="#10b981"
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
               axisLine={false} tickLine={false} width={64} />
        <Tooltip content={<DarkTip />} />
        <Area type="monotone" dataKey="ytd_actual" name="Actuals YTD" stroke="#f59e0b"
              strokeWidth={2.5} fill="url(#ytdActualFill)" dot={false} connectNulls={false} />
        <Line type="monotone" dataKey="ytd_worst"  name="Worst Case"  stroke="#ef4444"
              strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_likely" name="Most Likely" stroke="#e2e8f0"
              strokeWidth={2.5} dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_best"   name="Best Case"   stroke="#10b981"
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
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} width={58} />
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
            <Bar dataKey="worst"  name="Worst"   fill="#ef4444" opacity={0.5} radius={[0,3,3,0]} barSize={14} isAnimationActive />
            <Bar dataKey="likely" name="Likely"  fill="#ffffff" opacity={0.9} radius={[0,3,3,0]} barSize={14} isAnimationActive />
            <Bar dataKey="best"   name="Best"    fill="#10b981" opacity={0.5} radius={[0,3,3,0]} barSize={14} isAnimationActive />
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
            {['Year','Qtr','Month','Actuals','Worst Case','Most Likely','Best Case'].map(h => (
              <th key={h} style={{ ...th, textAlign: ['Month','Year','Qtr'].includes(h) ? 'left' : 'right' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {quarters.map(q => {
            const qm = byQtr[q] || [];
            const tot = qm.reduce((a, m) => ({
              arr_actual: (a.arr_actual || 0) + (m.arr_actual || 0),
              arr_worst:  a.arr_worst  + m.arr_worst,
              arr_likely: a.arr_likely + m.arr_likely,
              arr_best:   a.arr_best   + m.arr_best,
            }), { arr_actual: 0, arr_worst: 0, arr_likely: 0, arr_best: 0 });
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

const AccuracyTable = ({ data }) => {
  const models = ['ETS', 'Prophet', 'LightGBM', 'Chronos'];
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            {['Product','Geo',...models,'Best Model','Best MAPE'].map(h => (
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
                <td key={m} style={{ padding: '6px 12px', textAlign: 'right', fontSize: 12,
                                     color: r[m]&&r[m]<999 ? mapeColor(r[m]) : '#334155',
                                     fontWeight: r.best_model===m ? 700 : 400 }}>
                  {r[m]&&r[m]<999 ? `${r[m].toFixed(1)}%` : '—'}
                  {r.best_model===m && <span style={{ marginLeft: 4, fontSize: 9 }}>★</span>}
                </td>
              ))}
              <td style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, color: '#f59e0b', fontWeight: 600 }}>{r.best_model}</td>
              <td style={{ padding: '6px 12px', textAlign: 'right', fontSize: 12, fontWeight: 700,
                           color: r.best_mape&&r.best_mape<999 ? mapeColor(r.best_mape) : '#334155' }}>
                {r.best_mape&&r.best_mape<999 ? `${r.best_mape.toFixed(1)}%` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ── AI Insights tab — calls /api/forecast/intelligence via apiService ─────────
const AiInsightsSection = ({ model, prodLine }) => {
  const [aiData,    setAiData]    = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError,   setAiError]   = useState(null);

  const loadAi = useCallback(async () => {
    setAiLoading(true); setAiError(null);
    try {
      const res = await apiService.getForecastIntelligence(
        'won_pipeline',
        model === 'ensemble' ? 'prophet' : model,
        prodLine !== 'All' ? prodLine : null
      );
      // Support both wrapped {source, data:{...}} and legacy flat shape
      const d = (res?.data && typeof res.data === 'object') ? res.data : res;
      setAiData({ ...d, _source: res?.source ?? d?.source });
    } catch (e) {
      setAiError(e.message || 'Failed to load AI insights');
    } finally {
      setAiLoading(false);
    }
  }, [model, prodLine]);

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
            : `🟢 Live · Prophet model${aiData?.history_days ? ` · ${aiData.history_days} days of history` : ''}`}
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

// ── Main panel ────────────────────────────────────────────────────────────────
const TABS       = ['Overview', 'Multi-Year', 'By Product', 'Monthly', 'Accuracy', 'AI Insights'];
const MODELS     = ['ensemble', 'prophet', 'lightgbm', 'ets', 'chronos'];
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

const _buildDemoLeaderboard = () => [
  { product: 'Total', sales_market: 'Total', ETS: 19.8, Prophet: 16.2, LightGBM: 12.7, Chronos: 23.1, best_mape: 12.7, best_model: 'LightGBM' },
  { product: 'UCC', sales_market: 'Total', ETS: 17.1, Prophet: 14.2, LightGBM: 11.1, Chronos: 22.4, best_mape: 11.1, best_model: 'LightGBM' },
  { product: 'ITSG', sales_market: 'Total', ETS: 18.4, Prophet: 15.3, LightGBM: 12.4, Chronos: 24.0, best_mape: 12.4, best_model: 'LightGBM' },
  { product: 'Total', sales_market: 'NA', ETS: 18.6, Prophet: 15.9, LightGBM: 12.5, Chronos: 22.3, best_mape: 12.5, best_model: 'LightGBM' },
  { product: 'Total', sales_market: 'EMEA', ETS: 20.2, Prophet: 16.4, LightGBM: 13.2, Chronos: 24.1, best_mape: 13.2, best_model: 'LightGBM' },
  { product: 'Total', sales_market: 'APAC', ETS: 21.3, Prophet: 17.9, LightGBM: 14.1, Chronos: 25.8, best_mape: 14.1, best_model: 'LightGBM' },
  { product: 'Total', sales_market: 'LATAM', ETS: 22.0, Prophet: 18.7, LightGBM: 15.0, Chronos: 26.5, best_mape: 15.0, best_model: 'LightGBM' },
  { product: 'UCC', sales_market: 'NA', ETS: 16.9, Prophet: 13.8, LightGBM: 10.8, Chronos: 21.9, best_mape: 10.8, best_model: 'LightGBM' },
];

const ForecastingPanel = () => {
  const [tab,         setTab]         = useState('Overview');
  const [model,       setModel]       = useState('ensemble');
  const [fcType,      setFcType]      = useState('rolling');
  const [prodLine,    setProdLine]    = useState('All');

  const [weekly,      setWeekly]      = useState(null);
  const [ytd,         setYtd]         = useState(null);
  const [historical,  setHistorical]  = useState(null);
  const [byProduct,   setByProduct]   = useState(null);
  const [monthly,     setMonthly]     = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [modelRegistry, setModelRegistry] = useState([]);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState(null);
  const [source,      setSource]      = useState(null);

  const activePl = prodLine !== 'All' ? prodLine : null;

  const fetchAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [wk, yt, hs, bp, mo, lb, modelsRes] = await Promise.allSettled([
        apiService.getForecastV2Weekly(model, fcType, null, activePl),
        apiService.getForecastV2YTD(fcType, null, activePl),
        apiService.getForecastV2Historical(null, activePl),
        apiService.getForecastV2ByProduct(fcType),
        apiService.getForecastV2Monthly(fcType, null, activePl),
        apiService.getForecastV2Leaderboard(),
        apiService.getForecastV2Models(),
      ]);
      if (wk.status === 'fulfilled') {
        setWeekly(wk.value?.rows ?? []);
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
  }, [model, fcType, activePl]);

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

  // Per-model MAPE for pill badges (Total/All slice)
  const modelMapes = useMemo(() => {
    const totalRow = (leaderboardView || []).find(r =>
      (r.product === 'Total' || r.product === 'All') &&
      (r.sales_market === 'Total' || r.sales_market === 'All')
    );
    return totalRow
      ? { ETS: totalRow.ETS, Prophet: totalRow.Prophet, LightGBM: totalRow.LightGBM, Chronos: totalRow.Chronos }
      : {};
  }, [leaderboardView]);

  const isEmpty = !loading && weeklyView !== null && weeklyView.length === 0;

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
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 3 }}>
            {activeModelDisplay} · {activeModelFreshness ? `Updated ${activeModelFreshness}` : 'Refresh date unavailable'} · Growth ARR
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
        <div style={{ display: 'flex', gap: 4 }}>
          {FC_TYPES.map(f => (
            <button key={f.key} onClick={() => setFcType(f.key)} style={pill(fcType === f.key, '#3b82f6')}>{f.label}</button>
          ))}
        </div>
        <div style={{ width: 1, height: 20, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />

        {/* Model pills with MAPE badges */}
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {MODELS.map(m => {
            const capM  = m.charAt(0).toUpperCase() + m.slice(1);
            const color = MODEL_COLORS[capM] ?? '#f1f5f9';
            const mape  = m !== 'ensemble' ? modelMapes[capM] : null;
            return (
              <button key={m} onClick={() => setModel(m)} style={pill(model === m, color)}>
                {capM}
                {mape != null && mape < 999 && (
                  <span style={{ fontSize: 9, color: model === m ? mapeColor(mape) : '#475569',
                                 background: 'rgba(0,0,0,0.2)', padding: '1px 4px', borderRadius: 8 }}>
                    {Number(mape).toFixed(1)}%
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div style={{ width: 1, height: 20, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />

        <div style={{ display: 'flex', gap: 4 }}>
          {PROD_LINES.map(pl => (
            <button key={pl} onClick={() => setProdLine(pl)}
              style={pill(prodLine === pl, pl === 'UCC' ? '#3b82f6' : pl === 'ITSG' ? '#10b981' : null)}>
              {pl}
            </button>
          ))}
        </div>
      </div>

      {/* ── Status banners ─────────────────────────────────────────────────── */}
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

      {/* ── Tabs ───────────────────────────────────────────────────────────── */}
      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.07)', overflowX: 'auto' }}>
        {TABS.map(t => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
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
                    const currentYear = new Date().getFullYear().toString();
                    const fc = weeklyView.filter(r => r.arr_likely != null);
                    const ytdActual = weeklyView
                      .filter(r => r.arr_actual != null && r.date?.startsWith(currentYear))
                      .reduce((s, r) => s + r.arr_actual, 0);
                    return (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
                        {[
                          { label: 'Most Likely', val: fc.reduce((s,r)=>s+r.arr_likely,0), color: '#f1f5f9', sub: 'Planning center'    },
                          { label: 'Best Case',   val: fc.reduce((s,r)=>s+r.arr_best,0),   color: '#10b981', sub: '~20% probability'  },
                          { label: 'Worst Case',  val: fc.reduce((s,r)=>s+r.arr_worst,0),  color: '#ef4444', sub: '~15% probability'  },
                          { label: 'Actuals YTD', val: weeklyView.filter(r=>r.arr_actual).reduce((s,r)=>s+r.arr_actual,0), color: '#f59e0b', sub: 'Realized YTD' },
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

              <CardWrap>
                <SectionTitle>Weekly Forecast vs Actuals</SectionTitle>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                  <span><span style={{ color: '#f59e0b' }}>─</span> Actuals</span>
                  <span><span style={{ color: '#ef4444' }}>- -</span> Worst Case</span>
                  <span><span style={{ color: '#ffffff' }}>─</span> Most Likely</span>
                  <span><span style={{ color: '#10b981' }}>- -</span> Best Case</span>
                  <span style={{ color: '#3b82f6' }}>▒ Confidence band</span>
                </div>
                {loading ? <Skeleton height={260} /> : weeklyView && weeklyView.length > 0 ? <WeeklyChart rows={weeklyView} /> : <EmptyState />}
              </CardWrap>

              <CardWrap>
                <SectionTitle>Running Totals — YTD Cumulative</SectionTitle>
                {loading ? <Skeleton height={200} /> : ytdView && ytdView.length > 0 ? <RunningTotalsChart rows={ytdView} /> : <EmptyState />}
              </CardWrap>
            </div>
          )}

          {tab === 'Multi-Year' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <CardWrap>
                <SectionTitle>Historical Seasonality — by ISO Week (1–52)</SectionTitle>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {Object.entries(YEAR_COLORS).map(([yr,c]) => <span key={yr}><span style={{ color: c }}>─</span> {yr}</span>)}
                </div>
                {loading ? <Skeleton height={260} /> : historicalView && historicalView.length > 0 ? <MultiYearChart rows={historicalView} /> : <EmptyState />}
              </CardWrap>
              <CardWrap>
                <SectionTitle>Historical Weekly Trend</SectionTitle>
                {loading ? <Skeleton height={220} /> : (
                  <ResponsiveContainer width="100%" height={220}>
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
            </div>
          )}

          {tab === 'By Product' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <CardWrap>
                <SectionTitle>Forecast by Product Line & Product</SectionTitle>
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
            </div>
          )}

          {tab === 'Monthly' && (
            <CardWrap>
              <SectionTitle>Monthly Actuals vs Forecast Scenarios</SectionTitle>
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
                {loading ? <Skeleton height={240} /> : leaderboardView && leaderboardView.length > 0 ? <AccuracyTable data={leaderboardView} /> : <EmptyState />}
              </CardWrap>
            </div>
          )}

          {tab === 'AI Insights' && <AiInsightsSection model={model} prodLine={prodLine} />}

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
