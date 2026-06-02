/**
 * ForecastChart — Multi-model pipeline forecast with confidence intervals.
 * Models: Prophet | Holt-Winters | ARIMA | Triple Smoothing
 * Metrics: Won Pipeline | Active Pipeline | Win Rate | Created Pipeline
 * Shows: history (90d actual), forecast (90d forward), shaded CI area, MAPE/RMSE badges.
 */

import { useState, useEffect } from 'react';
import {
  ComposedChart, Line, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import ForecastIntelligence from './ForecastIntelligence';

const MODELS = [
  { key: 'holt_winters',     label: 'Holt-Winters',     color: '#3b82f6' },
  { key: 'prophet',          label: 'Prophet',           color: '#8b5cf6' },
  { key: 'arima',            label: 'ARIMA',             color: '#f59e0b' },
  { key: 'triple_smoothing', label: 'Triple Smoothing',  color: '#10b981' },
  { key: 'linear_seasonal',  label: 'Linear+Seasonal',   color: '#06b6d4' },
  { key: 'databricks_ai',    label: 'Databricks AI',     color: '#a855f7' },
];

const METRICS = [
  { key: 'won_pipeline',     label: 'Won Pipeline',     fmt: (v) => `$${(v / 1e6).toFixed(1)}M` },
  { key: 'active_pipeline',  label: 'Active Pipeline',  fmt: (v) => `$${(v / 1e6).toFixed(1)}M` },
  { key: 'win_rate',         label: 'Win Rate',         fmt: (v) => `${v?.toFixed(1)}%` },
  { key: 'created_pipeline', label: 'Created Pipeline', fmt: (v) => `$${(v / 1e6).toFixed(1)}M` },
];

const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
};

const DarkTooltip = ({ active, payload, label, fmt }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#64748b', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color ?? '#94a3b8' }}>
          {p.name}: {typeof p.value === 'number' ? fmt(p.value) : p.value}
        </div>
      ))}
    </div>
  );
};

const ForecastChart = () => {
  const [model,   setModel]   = useState('holt_winters');
  const [metric,  setMetric]  = useState('won_pipeline');
  const [periods, setPeriods] = useState(90);
  const [data,    setData]    = useState({ history: [], forecast: [], mape: 0, rmse: 0 });
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res  = await fetch(`/api/forecast/run?model=${model}&metric=${metric}&periods=${periods}`);
        const json = await res.json();
        if (cancelled) return;
        setData({
          history:  json.history  ?? [],
          forecast: json.forecast ?? [],
          mape:     json.mape     ?? 0,
          rmse:     json.rmse     ?? 0,
          source:   json.source   ?? 'demo',
        });
      } catch (e) {
        if (!cancelled) setError('Failed to load forecast data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [model, metric, periods]);

  const metricMeta  = METRICS.find(m => m.key === metric) || METRICS[0];
  const modelMeta   = MODELS.find(m => m.key === model)   || MODELS[0];

  // Merge history + forecast into one series for the chart
  // history items have no CI; forecast items have lower/upper
  const chartData = [
    ...data.history.map(d => ({ date: d.date, actual: d.value, forecast: null, lower: null, upper: null })),
    ...(data.forecast.length
      ? [{ date: data.history[data.history.length - 1]?.date, actual: null, forecast: data.history[data.history.length - 1]?.value, lower: data.history[data.history.length - 1]?.value, upper: data.history[data.history.length - 1]?.value }]
      : []),
    ...data.forecast.map(d => ({ date: d.date, actual: null, forecast: d.value, lower: d.lower, upper: d.upper })),
  ];

  const axisStyle  = { fill: '#475569', fontSize: 10 };
  const gridStyle  = { stroke: 'rgba(255,255,255,0.05)' };
  const ci_fill    = `${modelMeta.color}22`;

  const today = new Date().toISOString().split('T')[0];

  return (
    <div className="glass-card luxury-chart-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', letterSpacing: -0.3 }}>🔮 Forecast</div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 4, lineHeight: 1.45 }}>Multi-model forward projection with confidence intervals</div>
        </div>

        {/* Accuracy badges */}
        {!loading && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <div style={{
              padding: '4px 9px', borderRadius: 999,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              fontSize: 10, color: '#94a3b8',
            }}>
              MAPE <span style={{ color: data.mape < 10 ? '#10b981' : data.mape < 20 ? '#f59e0b' : '#ef4444', fontWeight: 700 }}>
                {data.mape?.toFixed(1)}%
              </span>
            </div>
            <div style={{
              padding: '4px 9px', borderRadius: 999,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              fontSize: 10, color: '#94a3b8',
            }}>
              RMSE <span style={{ color: '#3b82f6', fontWeight: 700 }}>
                {data.rmse >= 1e6 ? `$${(data.rmse / 1e6).toFixed(1)}M` : data.rmse?.toFixed(0)}
              </span>
            </div>
            {data.source === 'demo' && (
              <div style={{ padding: '4px 9px', borderRadius: 999, background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.2)', fontSize: 9, color: '#f59e0b' }}>
                DEMO DATA
              </div>
            )}
          </div>
        )}
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
        {/* Model selector */}
        <div style={{ display: 'flex', gap: 3 }}>
          {MODELS.map(m => (
            <button key={m.key} onClick={() => setModel(m.key)} style={{
              padding: '4px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, cursor: 'pointer',
              background: model === m.key ? `${m.color}22` : 'rgba(255,255,255,0.04)',
              border: `1px solid ${model === m.key ? m.color : 'rgba(255,255,255,0.08)'}`,
              color: model === m.key ? m.color : '#475569',
            }}>{m.label}</button>
          ))}
        </div>
        {/* Metric selector */}
        <div style={{ display: 'flex', gap: 3 }}>
          {METRICS.map(m => (
            <button key={m.key} onClick={() => setMetric(m.key)} style={{
              padding: '4px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, cursor: 'pointer',
              background: metric === m.key ? 'rgba(139,92,246,0.15)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${metric === m.key ? '#8b5cf6' : 'rgba(255,255,255,0.08)'}`,
              color: metric === m.key ? '#8b5cf6' : '#475569',
            }}>{m.label}</button>
          ))}
        </div>
        {/* Periods */}
        <div style={{ display: 'flex', gap: 3 }}>
          {[30, 60, 90].map(p => (
            <button key={p} onClick={() => setPeriods(p)} style={{
              padding: '4px 9px', borderRadius: 999, fontSize: 10, fontWeight: 700, cursor: 'pointer',
              background: periods === p ? 'rgba(16,185,129,0.12)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${periods === p ? '#10b981' : 'rgba(255,255,255,0.08)'}`,
              color: periods === p ? '#10b981' : '#475569',
            }}>{p}d</button>
          ))}
        </div>
      </div>

      {/* Chart */}
      {loading ? (
        <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Running {modelMeta.label} forecast…
        </div>
      ) : error ? (
        <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ef4444', fontSize: 12 }}>
          {error}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={chartData} margin={{ left: 8, right: 8, top: 14, bottom: 0 }}>
            <defs>
              <linearGradient id="fcGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={modelMeta.color} stopOpacity={0.15} />
                <stop offset="100%" stopColor={modelMeta.color} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
            <XAxis dataKey="date" tickFormatter={fmtDate} tick={axisStyle} axisLine={false} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={52} tickFormatter={metricMeta.fmt} />
            <Tooltip content={<DarkTooltip fmt={metricMeta.fmt} />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />

            {/* Reference line: today */}
            <ReferenceLine x={today} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 2" />

            {/* CI shaded area (lower to upper) */}
            <Area
              type="monotone" dataKey="upper" stroke="none" fill="url(#fcGrad)"
              name="CI Upper" legendType="none" connectNulls />
            <Area
              type="monotone" dataKey="lower" stroke="none" fill="white" fillOpacity={0}
              name="CI Lower" legendType="none" connectNulls />

            {/* Actuals */}
            <Line
              type="monotone" dataKey="actual" name="Actual"
              stroke="#94a3b8" strokeWidth={2} dot={false}
              connectNulls={false} />

            {/* Forecast line */}
            <Line
              type="monotone" dataKey="forecast" name={`${modelMeta.label} Forecast`}
              stroke={modelMeta.color} strokeWidth={2.5} dot={false}
              strokeDasharray="6 3" connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* ── Forecast Intelligence — always in sync with the chart above ── */}
      <div style={{
        borderTop: '1px solid var(--border-glass)',
        marginTop: 20, paddingTop: 20,
      }}>
        <ForecastIntelligence model={model} metric={metric} />
      </div>
    </div>
  );
};

export default ForecastChart;
