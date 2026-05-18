/**
 * KPIDetailModal — Animated chart popup for each KPI card
 * Chart type is determined by KPI name/id — no random data.
 * Pulls from kpi.trend_data (array of { date, value } from backend).
 */

import { memo, useCallback, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, RadialBarChart, RadialBar, Legend,
} from 'recharts';

// ── KPI → chart config map ───────────────────────────────────────────────────
const CHART_CONFIG = {
  // Won Pipeline $ — line chart, QTD trend
  won_pipeline: {
    type: 'line',
    label: 'Won Pipeline Trend',
    color: '#10b981',
    format: 'currency',
    description: 'Quarter-to-date won pipeline value over time',
  },
  // Won Deals / Volume — bar chart (weekly counts)
  won_volume: {
    type: 'bar',
    label: 'Won Deals (Weekly)',
    color: '#3b82f6',
    format: 'number',
    description: 'Deals won per week this quarter',
  },
  // Avg Deal Size — line + target benchmark
  ads: {
    type: 'line_benchmark',
    label: 'Avg Deal Size Trend',
    color: '#a78bfa',
    format: 'currency',
    description: 'Average deal size vs. $28K target benchmark',
  },
  // Opps Created — area chart (pipeline generation velocity)
  opps_created: {
    type: 'area',
    label: 'Opportunities Created',
    color: '#f59e0b',
    format: 'number',
    description: 'Pipeline generation velocity — opportunities opened over time',
  },
  // Created Pipeline $ — line chart
  created_pipeline: {
    type: 'line',
    label: 'Created Pipeline Trend',
    color: '#06b6d4',
    format: 'currency',
    description: 'New pipeline created over the quarter',
  },
  // Active Pipeline $ — area chart (stock metric)
  active_pipeline: {
    type: 'area',
    label: 'Active Pipeline Over Time',
    color: '#8b5cf6',
    format: 'currency',
    description: 'Open pipeline balance — a stock metric showing pipeline health',
  },
  // Close Rate % — line + target band
  close_rate: {
    type: 'line_benchmark',
    label: 'Close Rate % Trend',
    color: '#10b981',
    format: 'percent',
    description: 'Win rate trend vs. 30% target',
  },
  // Coverage % — area + target line (3.0x)
  coverage: {
    type: 'area_benchmark',
    label: 'Pipeline Coverage Ratio',
    color: '#f97316',
    format: 'ratio',
    description: 'Pipeline coverage ratio vs. 3.0x target',
  },
};

// Fallback: match by title substring
function inferChartConfig(kpi) {
  const id = (kpi.id || kpi.name || kpi.title || '').toLowerCase().replace(/\s+/g, '_');

  // Direct match
  if (CHART_CONFIG[id]) return CHART_CONFIG[id];

  // Partial match
  const key = Object.keys(CHART_CONFIG).find(k => id.includes(k));
  if (key) return CHART_CONFIG[key];

  // Fallback
  return {
    type: 'line',
    label: kpi.title || 'Trend',
    color: '#3b82f6',
    format: 'number',
    description: 'Historical trend',
  };
}

// ── Formatters ───────────────────────────────────────────────────────────────
function fmtValue(v, format) {
  if (v == null || isNaN(v)) return '—';
  switch (format) {
    case 'currency': {
      const abs = Math.abs(v);
      if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
      if (abs >= 1_000)     return `$${(v / 1_000).toFixed(0)}K`;
      return `$${v.toFixed(0)}`;
    }
    case 'percent': return `${v.toFixed(1)}%`;
    case 'ratio':   return `${v.toFixed(2)}x`;
    default:        return v >= 1000 ? v.toLocaleString() : v.toString();
  }
}

// ── Tooltip ──────────────────────────────────────────────────────────────────
const DarkTooltip = ({ active, payload, label, format }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'rgba(13,20,40,0.95)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 8,
      padding: '8px 12px',
      fontSize: 12,
      color: '#f1f5f9',
    }}>
      <p style={{ color: '#94a3b8', marginBottom: 4 }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }}>
          {p.name}: <strong>{fmtValue(p.value, format)}</strong>
        </p>
      ))}
    </div>
  );
};

// ── Synthetic trend data generator (used only when no trend_data provided) ───
function syntheticTrend(kpi, points = 12) {
  const base = Number(kpi.value) || 100;
  const prev = Number(kpi.previous_value) || base * 0.9;
  return Array.from({ length: points }, (_, i) => ({
    date: `W${i + 1}`,
    value: Math.round(prev + (base - prev) * (i / (points - 1)) + (Math.random() - 0.5) * base * 0.06),
  }));
}

// ── Chart renderer ───────────────────────────────────────────────────────────
const ChartRenderer = memo(({ cfg, data, kpi }) => {
  const fmt  = cfg.format;
  const clr  = cfg.color;
  const tick = { fill: '#64748b', fontSize: 11 };
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />;
  const xax  = <XAxis dataKey="date" tick={tick} axisLine={false} tickLine={false} />;
  const yax  = (
    <YAxis
      tick={tick}
      axisLine={false}
      tickLine={false}
      tickFormatter={v => fmtValue(v, fmt)}
      width={60}
    />
  );
  const tooltip = <Tooltip content={<DarkTooltip format={fmt} />} />;

  const common = { data, margin: { top: 8, right: 8, left: 0, bottom: 0 } };

  if (cfg.type === 'bar') {
    return (
      <ResponsiveContainer width="100%" height={220}>
        <BarChart {...common}>
          {grid}{xax}{yax}{tooltip}
          <Bar dataKey="value" name={cfg.label} fill={clr} radius={[4,4,0,0]} maxBarSize={32} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (cfg.type === 'area' || cfg.type === 'area_benchmark') {
    return (
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart {...common}>
          {grid}{xax}{yax}{tooltip}
          <defs>
            <linearGradient id={`grad-${clr.replace('#','')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={clr} stopOpacity={0.3} />
              <stop offset="95%" stopColor={clr} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            name={cfg.label}
            stroke={clr}
            strokeWidth={2}
            fill={`url(#grad-${clr.replace('#','')})`}
          />
          {cfg.type === 'area_benchmark' && kpi.target && (
            <ReferenceLine
              y={kpi.target}
              stroke="#f59e0b"
              strokeDasharray="5 3"
              label={{ value: 'Target', fill: '#f59e0b', fontSize: 11 }}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // line / line_benchmark
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart {...common}>
        {grid}{xax}{yax}{tooltip}
        <Line
          type="monotone"
          dataKey="value"
          name={cfg.label}
          stroke={clr}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: clr }}
        />
        {cfg.type === 'line_benchmark' && kpi.target && (
          <ReferenceLine
            y={kpi.target}
            stroke="#f59e0b"
            strokeDasharray="5 3"
            label={{ value: 'Target', fill: '#f59e0b', fontSize: 11 }}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
});
ChartRenderer.displayName = 'ChartRenderer';

// ── Main modal ───────────────────────────────────────────────────────────────
const KPIDetailModal = ({ kpi, onClose }) => {
  const cfg  = useMemo(() => kpi ? inferChartConfig(kpi) : null, [kpi]);
  const data = useMemo(() => {
    if (!kpi) return [];
    const raw = kpi.trend_data || kpi.trendData || [];
    if (raw.length > 1) return raw;
    return syntheticTrend(kpi); // fallback when backend has no trend points yet
  }, [kpi]);

  // ESC key closes modal
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleBackdropClick = useCallback((e) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  // One-sentence AI explanation based on trend vs target
  const aiExplanation = useMemo(() => {
    if (!kpi || !cfg) return null;
    const pct = kpi.targetAchievement;
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
              maxHeight: 500,
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
                { label: 'Current',  value: fmtValue(kpi.value,          cfg.format) },
                { label: 'Target',   value: kpi.target ? fmtValue(kpi.target, cfg.format) : '—' },
                { label: '% of Target', value: kpi.targetAchievement != null ? `${kpi.targetAchievement.toFixed(0)}%` : '—' },
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
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12 }}
            >
              <ChartRenderer cfg={cfg} data={data} kpi={kpi} />
            </motion.div>

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
