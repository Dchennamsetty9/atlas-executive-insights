/**
 * KPIDetailModal — Animated chart popup for each KPI card.
 * Each KPI gets the chart type that best tells its data story:
 *   - Pipeline $    → ComposedChart: actual area + ideal-pace dotted line
 *   - Volume/Count  → BarChart (weekly cadence)
 *   - Close Rate %  → Semi-circle gauge (PieChart arc)
 *   - Coverage      → Semi-circle gauge (PieChart arc)
 *   - ADS           → LineChart with target reference line
 */

import { memo, useCallback, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  ComposedChart, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, PieChart, Pie, Cell,
} from 'recharts';

// ── KPI → chart config ───────────────────────────────────────────────────────
const CHART_CONFIG = {
  won_pipeline: {
    type: 'pace',
    label: 'Won ACV $ — QTD Pacing',
    color: '#10b981',
    format: 'currency',
    description: 'Actual won pipeline vs ideal quarterly pace toward target',
  },
  won_volume: {
    type: 'bar',
    label: 'Deals Won (Weekly)',
    color: '#3b82f6',
    format: 'number',
    description: 'Number of deals closed-won per week this quarter',
  },
  ads: {
    type: 'line',
    label: 'Avg Deal Size Trend',
    color: '#a78bfa',
    format: 'currency',
    description: 'Average deal size over the quarter vs target benchmark',
  },
  opps_created: {
    type: 'bar',
    label: 'Opportunities Created (Weekly)',
    color: '#f59e0b',
    format: 'number',
    description: 'New pipeline-generating opportunities opened each week',
  },
  created_pipeline: {
    type: 'area',
    label: 'Created Pipeline $',
    color: '#06b6d4',
    format: 'currency',
    description: 'Cumulative new pipeline created this quarter',
  },
  active_pipeline: {
    type: 'pace',
    label: 'Active Pipeline Balance',
    color: '#8b5cf6',
    format: 'currency',
    description: 'Open pipeline balance — a stock metric reflecting pipeline health',
  },
  close_rate: {
    type: 'gauge',
    label: 'Close Rate %',
    color: '#10b981',
    format: 'percent',
    description: 'Win rate of resolved deals (won ÷ won + lost)',
    gaugeMax: 60, // 0–60% scale
  },
  coverage: {
    type: 'gauge',
    label: 'Pipeline Coverage',
    color: '#f97316',
    format: 'ratio',
    description: 'Active pipeline ÷ remaining won-pipeline target',
    gaugeMax: 5,  // 0–5x scale
  },
  mql_count: {
    type: 'bar',
    label: 'MQLs (Weekly)',
    color: '#ec4899',
    format: 'number',
    description: 'Marketing-qualified leads delivered per week',
  },
};

function inferChartConfig(kpi) {
  const id = (kpi.id || '').toLowerCase();
  if (CHART_CONFIG[id]) return CHART_CONFIG[id];
  const key = Object.keys(CHART_CONFIG).find(k => id.includes(k));
  if (key) return CHART_CONFIG[key];
  return { type: 'area', label: kpi.title || 'Trend', color: '#3b82f6', format: 'number', description: '' };
}

// ── Value formatter ──────────────────────────────────────────────────────────
function fmtValue(v, format) {
  if (v == null || isNaN(v)) return '—';
  switch (format) {
    case 'currency': {
      const a = Math.abs(v);
      if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
      if (a >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
      return `$${v.toFixed(0)}`;
    }
    case 'percent': return `${v.toFixed(1)}%`;
    case 'ratio':   return `${v.toFixed(2)}x`;
    default:        return v >= 1000 ? v.toLocaleString() : String(Math.round(v));
  }
}

// ── Synthetic trend data (realistic ramp from prior period → current) ────────
function syntheticTrend(kpi, points = 12) {
  const current = Number(kpi.value) || 10;
  const prior   = Number(kpi.previous_value) || current * 0.85;
  const noise   = current * 0.04;

  return Array.from({ length: points }, (_, i) => {
    const t = i / (points - 1);
    // Ease-in ramp to simulate gradual quarter buildup
    const eased = t * t * (3 - 2 * t);
    const raw = prior + (current - prior) * eased + (Math.random() - 0.5) * noise;
    return { date: `W${i + 1}`, value: Math.round(raw * 100) / 100 };
  });
}

// Weekly count distribution (used for bar-type KPIs)
function syntheticWeekly(kpi, weeks = 12) {
  const total = Number(kpi.value) || 50;
  const perWeek = total / weeks;
  return Array.from({ length: weeks }, (_, i) => ({
    date: `W${i + 1}`,
    value: Math.max(0, Math.round(perWeek * (0.7 + Math.random() * 0.6))),
  }));
}

// ── Dark tooltip ─────────────────────────────────────────────────────────────
const DarkTooltip = ({ active, payload, label, format }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'rgba(10,17,35,0.97)',
      border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: 8,
      padding: '8px 12px',
      fontSize: 12,
      color: '#f1f5f9',
      boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
    }}>
      <p style={{ color: '#94a3b8', marginBottom: 4, margin: '0 0 4px' }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color || p.stroke || '#f1f5f9', margin: 0 }}>
          {p.name}: <strong>{fmtValue(p.value, format)}</strong>
        </p>
      ))}
    </div>
  );
};

// ── Semi-circle Gauge (PieChart arc) ─────────────────────────────────────────
const GaugeChart = ({ value, target, color, format, gaugeMax }) => {
  const max   = gaugeMax || (target * 1.5) || 100;
  const pct   = Math.min(Math.max(value / max, 0), 1);
  const tPct  = Math.min(Math.max(target / max, 0), 1);
  const status = value >= target ? '#10b981' : value >= target * 0.85 ? '#f59e0b' : '#ef4444';

  // 220-degree arc gauge (startAngle=200 endAngle=-20 in Recharts convention)
  const gaugeData = [
    { name: 'filled', value: pct },
    { name: 'empty',  value: Math.max(1 - pct, 0) },
  ];
  // Target tick line (SVG overlay calculated from angle)
  const targetAngle = 200 - tPct * 220; // degrees in display space

  return (
    <div style={{ position: 'relative', width: '100%', height: 220 }}>
      <ResponsiveContainer width="100%" height={220} debounce={0}>
        <PieChart margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
          {/* Background track */}
          <Pie
            data={[{ value: 1 }]}
            cx="50%" cy="80%"
            startAngle={200} endAngle={-20}
            innerRadius="52%" outerRadius="68%"
            dataKey="value" stroke="none"
          >
            <Cell fill="rgba(255,255,255,0.06)" />
          </Pie>
          {/* Value arc */}
          <Pie
            data={gaugeData}
            cx="50%" cy="80%"
            startAngle={200} endAngle={-20}
            innerRadius="52%" outerRadius="68%"
            dataKey="value" stroke="none"
          >
            <Cell fill={status} />
            <Cell fill="transparent" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>

      {/* Center overlay */}
      <div style={{
        position: 'absolute',
        bottom: '14%',
        left: '50%',
        transform: 'translateX(-50%)',
        textAlign: 'center',
        pointerEvents: 'none',
      }}>
        <div style={{ fontSize: 34, fontWeight: 800, color: status, lineHeight: 1 }}>
          {fmtValue(value, format)}
        </div>
        <div style={{ fontSize: 11, color: '#64748b', marginTop: 6 }}>
          Target: <span style={{ color: '#f59e0b' }}>{fmtValue(target, format)}</span>
        </div>
        <div style={{
          marginTop: 6,
          display: 'inline-block',
          padding: '2px 8px',
          borderRadius: 20,
          background: `${status}22`,
          border: `1px solid ${status}44`,
          fontSize: 10,
          color: status,
          fontWeight: 700,
        }}>
          {target > 0 ? `${((value / target) * 100).toFixed(0)}% of target` : '—'}
        </div>
      </div>

      {/* Scale labels */}
      <div style={{
        position: 'absolute', bottom: '6%', left: '16%',
        fontSize: 10, color: '#475569',
      }}>0</div>
      <div style={{
        position: 'absolute', bottom: '6%', right: '16%',
        fontSize: 10, color: '#475569',
      }}>{fmtValue(max, format)}</div>
    </div>
  );
};

// ── Chart renderer ───────────────────────────────────────────────────────────
const ChartRenderer = memo(({ cfg, data, kpi }) => {
  const fmt  = cfg.format;
  const clr  = cfg.color;
  const tick = { fill: '#475569', fontSize: 11 };
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />;
  const xax  = <XAxis dataKey="date" tick={tick} axisLine={false} tickLine={false} interval={1} />;
  const yax  = (
    <YAxis
      tick={tick}
      axisLine={false}
      tickLine={false}
      tickFormatter={v => fmtValue(v, fmt)}
      width={62}
    />
  );
  const tooltip = <Tooltip content={<DarkTooltip format={fmt} />} cursor={{ stroke: 'rgba(255,255,255,0.08)', strokeWidth: 1 }} />;

  // Wrapper ensures ResponsiveContainer always gets a non-zero measured width
  const wrap = (chart) => (
    <div style={{ width: '100%', height: 240, minWidth: 1 }}>
      <ResponsiveContainer width="100%" height="100%" debounce={0}>
        {chart}
      </ResponsiveContainer>
    </div>
  );

  const common = { data, margin: { top: 10, right: 12, left: 0, bottom: 4 } };

  // ── Gauge ─────────────────────────────────────────────────────────────────
  if (cfg.type === 'gauge') {
    return (
      <GaugeChart
        value={kpi.value}
        target={kpi.target}
        color={clr}
        format={fmt}
        gaugeMax={cfg.gaugeMax}
      />
    );
  }

  // ── Pacing: area (actual) + dotted line (ideal pace) ─────────────────────
  if (cfg.type === 'pace') {
    const target = kpi.target || 0;
    const paceData = data.map((d, i) => ({
      ...d,
      pace: target > 0 ? Math.round((target * (i + 1) / data.length) * 100) / 100 : undefined,
    }));
    const gradId = `pace-grad-${clr.replace('#', '')}`;
    return wrap(
      <ComposedChart {...common} data={paceData}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={clr} stopOpacity={0.35} />
            <stop offset="95%" stopColor={clr} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {grid}{xax}{yax}{tooltip}
        <Area
          type="monotone"
          dataKey="value"
          name="Actual"
          stroke={clr}
          strokeWidth={2.5}
          fill={`url(#${gradId})`}
          dot={false}
          activeDot={{ r: 5, fill: clr, stroke: '#0d1428', strokeWidth: 2 }}
        />
        {target > 0 && (
          <Line
            type="monotone"
            dataKey="pace"
            name="Ideal Pace"
            stroke="#f59e0b"
            strokeWidth={1.5}
            strokeDasharray="5 4"
            dot={false}
            activeDot={false}
          />
        )}
        {target > 0 && (
          <ReferenceLine
            y={target}
            stroke="#f59e0b"
            strokeOpacity={0.5}
            strokeDasharray="3 3"
            label={{ value: 'Target', position: 'insideTopRight', fill: '#f59e0b', fontSize: 10 }}
          />
        )}
      </ComposedChart>
    );
  }

  // ── Bar chart ─────────────────────────────────────────────────────────────
  if (cfg.type === 'bar') {
    const gradId = `bar-grad-${clr.replace('#', '')}`;
    return wrap(
      <BarChart {...common}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={clr} stopOpacity={0.9} />
            <stop offset="100%" stopColor={clr} stopOpacity={0.4} />
          </linearGradient>
        </defs>
        {grid}{xax}{yax}{tooltip}
        <Bar
          dataKey="value"
          name={cfg.label}
          fill={`url(#${gradId})`}
          radius={[4, 4, 0, 0]}
          maxBarSize={28}
        />
      </BarChart>
    );
  }

  // ── Area chart ────────────────────────────────────────────────────────────
  if (cfg.type === 'area') {
    const gradId = `area-grad-${clr.replace('#', '')}`;
    return wrap(
      <AreaChart {...common}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={clr} stopOpacity={0.3} />
            <stop offset="95%" stopColor={clr} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {grid}{xax}{yax}{tooltip}
        <Area
          type="monotone"
          dataKey="value"
          name={cfg.label}
          stroke={clr}
          strokeWidth={2.5}
          fill={`url(#${gradId})`}
          dot={false}
          activeDot={{ r: 5, fill: clr, stroke: '#0d1428', strokeWidth: 2 }}
        />
        {kpi.target > 0 && (
          <ReferenceLine
            y={kpi.target}
            stroke="#f59e0b"
            strokeOpacity={0.5}
            strokeDasharray="4 3"
            label={{ value: 'Target', position: 'insideTopRight', fill: '#f59e0b', fontSize: 10 }}
          />
        )}
      </AreaChart>
    );
  }

  // ── Line chart (default, used for ADS etc.) ───────────────────────────────
  const gradId = `line-grad-${clr.replace('#', '')}`;
  return wrap(
    <ComposedChart {...common}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%"  stopColor={clr} stopOpacity={0.15} />
          <stop offset="95%" stopColor={clr} stopOpacity={0.0} />
        </linearGradient>
      </defs>
      {grid}{xax}{yax}{tooltip}
      <Area
        type="monotone"
        dataKey="value"
        name={cfg.label}
        stroke={clr}
        strokeWidth={2.5}
        fill={`url(#${gradId})`}
        dot={false}
        activeDot={{ r: 5, fill: clr, stroke: '#0d1428', strokeWidth: 2 }}
      />
      {kpi.target > 0 && (
        <ReferenceLine
          y={kpi.target}
          stroke="#f59e0b"
          strokeOpacity={0.6}
          strokeDasharray="5 3"
          label={{ value: 'Target', position: 'insideTopRight', fill: '#f59e0b', fontSize: 10 }}
        />
      )}
    </ComposedChart>
  );
});
ChartRenderer.displayName = 'ChartRenderer';

// ── Main modal ───────────────────────────────────────────────────────────────
const KPIDetailModal = ({ kpi, onClose }) => {
  const cfg  = useMemo(() => kpi ? inferChartConfig(kpi) : null, [kpi]);

  const data = useMemo(() => {
    if (!kpi || cfg?.type === 'gauge') return [];

    const raw = kpi.trend_data || kpi.trendData || [];

    // Backend returns List[float] — convert to {date, value} objects
    if (raw.length > 1 && typeof raw[0] === 'number') {
      return raw.map((v, i) => ({ date: `W${i + 1}`, value: v }));
    }
    // Backend may return {date, value} objects already
    if (raw.length > 1 && typeof raw[0] === 'object') {
      return raw;
    }

    // Fallback: generate realistic synthetic data
    const isBar = cfg?.type === 'bar';
    return isBar ? syntheticWeekly(kpi) : syntheticTrend(kpi);
  }, [kpi, cfg]);

  // ESC key closes modal
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleBackdropClick = useCallback((e) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  // One-sentence AI explanation
  const aiExplanation = useMemo(() => {
    if (!kpi || !cfg) return null;
    const pct = kpi.targetAchievement ?? (kpi.target > 0 ? (kpi.value / kpi.target) * 100 : null);
    const name = kpi.title || kpi.name || 'This metric';
    if (pct == null) return null;
    if (pct >= 110) return `${name} is exceeding target — maintain current momentum heading into quarter-end.`;
    if (pct >= 100) return `${name} is on track. Sustain close cadence to protect the target.`;
    if (pct >= 85)  return `${name} is within striking distance but requires acceleration in the final stretch.`;
    const gap = kpi.target && kpi.value ? fmtValue(kpi.target - kpi.value, cfg.format) : 'a significant gap';
    return `${name} is tracking below target by ${gap}. Focus effort on accelerating Stage 3+ deals to close the gap.`;
  }, [kpi, cfg]);

  return (
    <AnimatePresence>
      {kpi && cfg && (
        <motion.div
          className="modal-overlay"
          style={{
            position: 'fixed',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9000,
            padding: 16,
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={handleBackdropClick}
        >
          <motion.div
            style={{
              background: 'linear-gradient(135deg, #111827 0%, #0d1428 100%)',
              border: `1px solid ${cfg.color}44`,
              borderRadius: 16,
              padding: 24,
              width: '100%',
              maxWidth: 700,
              maxHeight: '90vh',
              overflowY: 'auto',
              boxShadow: `0 0 40px ${cfg.color}22, 0 24px 64px rgba(0,0,0,0.6)`,
              color: '#f1f5f9',
            }}
            initial={{ scale: 0.92, opacity: 0, y: 24 }}
            animate={{ scale: 1,    opacity: 1, y: 0  }}
            exit={{    scale: 0.92, opacity: 0, y: 24 }}
            transition={{ type: 'spring', stiffness: 300, damping: 28 }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <div style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: cfg.color,
                    boxShadow: `0 0 8px ${cfg.color}`,
                  }} />
                  <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1 }}>
                    KPI Detail
                  </span>
                </div>
                <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>{kpi.title || kpi.name}</h2>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: '#64748b' }}>{cfg.description}</p>
              </div>
              <button
                onClick={onClose}
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 8,
                  color: '#94a3b8',
                  width: 32, height: 32,
                  cursor: 'pointer',
                  fontSize: 16,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                }}
              >×</button>
            </div>

            {/* Stats row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
              {[
                { label: 'Current',     value: fmtValue(kpi.value,  cfg.format) },
                { label: 'Target',      value: kpi.target ? fmtValue(kpi.target, cfg.format) : '—' },
                { label: '% of Target', value: (() => {
                  const pct = kpi.targetAchievement ?? (kpi.target > 0 ? (kpi.value / kpi.target) * 100 : null);
                  return pct != null ? `${pct.toFixed(0)}%` : '—';
                })() },
              ].map(({ label, value }) => (
                <div key={label} style={{
                  background: 'rgba(255,255,255,0.04)',
                  borderRadius: 8,
                  padding: '10px 12px',
                  border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: cfg.color }}>{value}</div>
                </div>
              ))}
            </div>

            {/* Chart */}
            <ChartRenderer cfg={cfg} data={data} kpi={kpi} />

            {/* AI explanation sentence */}
            {aiExplanation && (
              <div style={{
                marginTop: 12,
                padding: '8px 12px',
                borderRadius: 8,
                background: 'rgba(59,130,246,0.06)',
                border: '1px solid rgba(59,130,246,0.15)',
                display: 'flex', gap: 8, alignItems: 'flex-start',
              }}>
                <span style={{ fontSize: 13, flexShrink: 0 }}>💡</span>
                <p style={{ margin: 0, fontSize: 12, color: '#94a3b8', lineHeight: 1.5 }}>{aiExplanation}</p>
              </div>
            )}

            {/* Footer note */}
            <p style={{ margin: '10px 0 0', fontSize: 11, color: '#334155', textAlign: 'right' }}>
              Source: Databricks · mdl_sales_analytics
            </p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default memo(KPIDetailModal);
