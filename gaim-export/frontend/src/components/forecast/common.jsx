import { useState, useRef } from 'react';
import { apiService } from '../../services/api';
import { exportCardPng } from '../../utils/chartExport';

export const fmtM = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  if (n === 0) return '—';
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
};

export const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.toLocaleString('default', { month: 'short' })} ${dt.getDate()}`;
};

export const calculateStaleness = (dateStr) => {
  if (!dateStr) return null;
  try {
    const runDate = new Date(dateStr + 'T00:00:00Z');
    const now = new Date();
    const diffMs = now - runDate;
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);
    if (days > 0) return { value: days, unit: 'day', plural: days > 1 ? 's' : '', isStale: days > 7 };
    return { value: Math.max(0, hours), unit: 'hour', plural: hours !== 1 ? 's' : '', isStale: hours > 48 };
  } catch { return null; }
};

export const validateConfidenceBands = (lower, middle, upper) => {
  if (lower == null || middle == null || upper == null) return { valid: true };
  const l = Number(lower), m = Number(middle), u = Number(upper);
  if (isNaN(l) || isNaN(m) || isNaN(u)) return { valid: false, error: 'Invalid numbers' };
  if (!(l <= m && m <= u)) return { valid: false, error: `Bands out of order (${fmtM(l)} > ${fmtM(m)} > ${fmtM(u)})` };
  return { valid: true };
};

export const mapeColor = (v) => (v < 15 ? '#10b981' : v < 25 ? '#f59e0b' : '#ef4444');

export const MODEL_LABELS = {
  ETS: 'ETS',
  Prophet: 'Prophet',
  LightGBM: 'LightGBM',
  Mstl_v2: 'MSTL',
  MSTL_v2: 'MSTL',
  Dhr_arima: 'DHR-ARIMA',
  DHR_ARIMA: 'DHR-ARIMA',
  Ensemble: 'Ensemble',
};

export const formatModelLabel = (name) => MODEL_LABELS[name] || (name ? name.replace(/_/g, ' ') : 'Unknown');

// Dynamic year range: current year - 2 to current year + 1 (future-proof to 2027+)
const currentYear = new Date().getFullYear();
const yearRange = [currentYear - 2, currentYear - 1, currentYear, currentYear + 1];
const yearColorPalette = ['#64748b', '#06b6d4', '#3b82f6', '#f59e0b'];
export const YEAR_COLORS = Object.fromEntries(
  yearRange.map((year, idx) => [year, yearColorPalette[idx]])
);
export const MODEL_COLORS = { ETS: '#94a3b8', Prophet: '#f59e0b', LightGBM: '#3b82f6', Mstl_v2: '#a78bfa', Dhr_arima: '#fb923c', Ensemble: '#00FF88' };
export const MODEL_KEY_META = {
  ensemble: { label: 'Ensemble', color: '#00FF88' },
  prophet: { label: 'Prophet', color: '#f59e0b' },
  ets: { label: 'ETS', color: '#94a3b8' },
  mstl_v2: { label: 'MSTL', color: '#a78bfa' },
  dhr_arima: { label: 'DHR-ARIMA', color: '#fb923c' },
  lightgbm: { label: 'LightGBM', color: '#3b82f6' },
};
export const MODEL_LB_KEY = {
  ensemble: 'Ensemble',
  prophet: 'Prophet',
  ets: 'ETS',
  mstl_v2: 'MSTL_v2',
  dhr_arima: 'DHR_ARIMA',
  lightgbm: 'LightGBM',
};
export const MOMENTUM_META = {
  STABLE: { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  ACCELERATING: { color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  DECELERATING: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  VOLATILE: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  stable: { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  accelerating: { color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  decelerating: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  volatile: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
};
export const RISK_META = {
  'LOW RISK': { color: '#10b981', bg: 'rgba(16,185,129,0.1)' },
  'MODERATE RISK': { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
  'HIGH RISK': { color: '#ef4444', bg: 'rgba(239,68,68,0.1)' },
  low: { color: '#10b981', bg: 'rgba(16,185,129,0.1)' },
  moderate: { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
  high: { color: '#ef4444', bg: 'rgba(239,68,68,0.1)' },
};

export const DarkTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, padding: '10px 14px', fontSize: 11 }}>
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

export const Skeleton = ({ height = 14 }) => (
  <div style={{ height, borderRadius: 6, background: 'rgba(255,255,255,0.06)', animation: 'fp-pulse 1.5s ease-in-out infinite', marginBottom: 8 }} />
);

export const TableSkeleton = () => (
  <div style={{ padding: '16px' }}>
    <Skeleton height={24} />
    {[...Array(5)].map((_, i) => <Skeleton key={i} height={16} />)}
  </div>
);

export const ChartSkeleton = ({ height = 300 }) => (
  <div style={{ height, borderRadius: 12, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'fp-pulse 1.5s ease-in-out infinite' }}>
    <div style={{ color: '#475569', fontSize: 12 }}>Loading chart...</div>
  </div>
);

export const EmptyState = ({ message = 'Awaiting next forecast run' }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 150, gap: 10, color: '#475569', padding: '24px' }}>
    <div style={{ fontSize: 28 }}>🕐</div>
    <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b' }}>{message}</div>
    <div style={{ fontSize: 11, color: '#334155', textAlign: 'center', maxWidth: 380 }}>
      The forecast job runs every Monday at 03:00 UTC. Check back after the next run.
    </div>
  </div>
);

export const CardWrap = ({ children, downloadName }) => {
  const ref = useRef(null);
  return (
    <div ref={ref} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 12, padding: 16, position: 'relative' }}>
      {downloadName && (
        <button
          onClick={() => exportCardPng(ref, downloadName)}
          title="Download chart as PNG"
          aria-label="Download chart as PNG"
          data-export-hide
          style={{ position: 'absolute', top: 10, right: 12, width: 26, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, cursor: 'pointer', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: '#64748b', fontSize: 12, lineHeight: 1, padding: 0, zIndex: 2 }}
        >
          ⬇
        </button>
      )}
      {children}
    </div>
  );
};

export const SectionTitle = ({ children }) => (
  <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>{children}</div>
);

const compactDataPoints = (rows, maxPoints = 40) => {
  const clean = (rows || []).filter((r) => r && typeof r === 'object');
  if (clean.length <= maxPoints) return clean;
  const step = Math.ceil(clean.length / maxPoints);
  return clean.filter((_, i) => i % step === 0 || i === clean.length - 1);
};

export const GraphInsight = ({ summary, chartType, metricName, dataPoints }) => {
  const [open, setOpen] = useState(false);
  const [ai, setAi] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiTried, setAiTried] = useState(false);
  const aiCapable = Boolean(chartType && metricName && dataPoints?.length);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && aiCapable && !aiTried) {
      setAiTried(true);
      setAiLoading(true);
      apiService.getAIChartAnnotation(chartType, compactDataPoints(dataPoints), metricName)
        .then((res) => { if (res?.annotation) setAi(res); })
        .catch(() => {})
        .finally(() => setAiLoading(false));
    }
  };

  if (!summary && !aiCapable) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <button
        onClick={toggle}
        style={{ border: '1px solid rgba(59,130,246,0.22)', background: 'rgba(59,130,246,0.08)', color: '#93c5fd', borderRadius: 8, padding: '4px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer', letterSpacing: '0.02em' }}
      >
        {open ? '▾' : '▸'} {aiCapable ? '✨ AI Insight' : 'AI Insight'}
      </button>
      {open && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#cbd5e1', lineHeight: 1.6, background: 'rgba(30,41,59,0.45)', border: '1px solid rgba(148,163,184,0.2)', borderRadius: 8, padding: '8px 10px' }}>
          {summary && <div>{summary}</div>}
          {aiCapable && (
            <div style={{ marginTop: summary ? 8 : 0, paddingTop: summary ? 8 : 0, borderTop: summary ? '1px solid rgba(148,163,184,0.15)' : 'none' }}>
              {aiLoading && <span style={{ color: '#64748b', fontStyle: 'italic' }}>✨ Asking AI about this chart…</span>}
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
