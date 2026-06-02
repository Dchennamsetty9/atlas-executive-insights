import { useMemo, useState, useEffect, useCallback } from 'react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import ForecastIntelligence from './ForecastIntelligence';

const MODELS = [
  { label: 'LightGBM', color: '#00BFFF' },
  { label: 'Prophet', color: '#FF6B6B' },
  { label: 'Ensemble (70/30)', color: '#00FF88' },
];

const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
};

const fmtCurrencyCompact = (v) => {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
};

const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#64748b', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color ?? '#94a3b8' }}>
          {p.name}: {typeof p.value === 'number' ? fmtCurrencyCompact(p.value) : p.value}
        </div>
      ))}
    </div>
  );
};

const ForecastChart = () => {
  const [selectedModel, setSelectedModel] = useState('Ensemble (70/30)');
  const [forecastData, setForecastData] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [source, setSource] = useState('demo');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [arrRes, leaderboardRes] = await Promise.all([
        fetch('/api/forecast/arr'),
        fetch('/api/forecast/leaderboard'),
      ]);
      if (!arrRes.ok) throw new Error(`ARR HTTP ${arrRes.status}`);
      if (!leaderboardRes.ok) throw new Error(`Leaderboard HTTP ${leaderboardRes.status}`);

      const arrJson = await arrRes.json();
      const lbJson = await leaderboardRes.json();

      setForecastData(arrJson.data ?? null);
      setLeaderboard(lbJson.data ?? []);
      setSource(arrJson.source ?? 'demo');
    } catch (e) {
      setError('Failed to load forecast data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const modelColor = MODELS.find((m) => m.label === selectedModel)?.color ?? '#00FF88';
  const selectedM = leaderboard.find((r) => r.model === selectedModel);

  const chartData = useMemo(() => {
    if (!forecastData) return [];

    const actualSeries = forecastData.actual?.actuals ?? [];
    const forecastSeries = forecastData[selectedModel]?.forecast ?? [];

    const byDate = new Map();

    for (const p of actualSeries) {
      const date = String(p.date || '').slice(0, 10);
      if (!date) continue;
      byDate.set(date, {
        date,
        actual: Number(p.value ?? 0),
        forecast: null,
        lower: null,
        upper: null,
      });
    }

    for (const p of forecastSeries) {
      const date = String(p.date || '').slice(0, 10);
      if (!date) continue;
      const row = byDate.get(date) ?? { date, actual: null, forecast: null, lower: null, upper: null };
      row.forecast = Number(p.value ?? 0);
      row.lower = Number(p.lower ?? p.value ?? 0);
      row.upper = Number(p.upper ?? p.value ?? 0);
      byDate.set(date, row);
    }

    return Array.from(byDate.values()).sort((a, b) => new Date(a.date) - new Date(b.date));
  }, [forecastData, selectedModel]);

  return (
    <div className="glass-card luxury-chart-card" style={{ padding: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', letterSpacing: -0.3 }}>Forecast</div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 4, lineHeight: 1.45 }}>
            Pre-computed 13-week ARR forecast from Delta tables
          </div>
        </div>

        {!loading && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <div style={{
              padding: '4px 9px', borderRadius: 999,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              fontSize: 10, color: '#94a3b8',
            }}>
              MAPE <span style={{ color: '#00FF88', fontWeight: 700 }}>
                {selectedM ? `${Number(selectedM.mape).toFixed(1)}%` : '—'}
              </span>
            </div>
            {source === 'live' && (
              <div style={{
                padding: '4px 9px', borderRadius: 999,
                background: 'rgba(16,185,129,0.1)',
                border: '1px solid rgba(16,185,129,0.25)',
                fontSize: 10, color: '#10b981', fontWeight: 700,
              }}>
                LIVE
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
        {MODELS.map((m) => (
          <button
            key={m.label}
            onClick={() => setSelectedModel(m.label)}
            style={{
              padding: '4px 10px',
              borderRadius: 999,
              fontSize: 10,
              fontWeight: 700,
              cursor: 'pointer',
              background: selectedModel === m.label ? `${m.color}22` : 'rgba(255,255,255,0.04)',
              border: `1px solid ${selectedModel === m.label ? m.color : 'rgba(255,255,255,0.08)'}`,
              color: selectedModel === m.label ? m.color : '#475569',
            }}
          >
            {m.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading live forecast…
        </div>
      ) : error ? (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ef4444', fontSize: 12 }}>
          {error}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={chartData} margin={{ left: 8, right: 8, top: 14, bottom: 0 }}>
            <defs>
              <linearGradient id="fcGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={modelColor} stopOpacity={0.2} />
                <stop offset="100%" stopColor={modelColor} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="date"
              tickFormatter={fmtDate}
              tick={{ fill: '#475569', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: '#475569', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={52}
              tickFormatter={fmtCurrencyCompact}
            />
            <Tooltip content={<DarkTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />

            <Area type="monotone" dataKey="upper" stroke="none" fill="url(#fcGrad)" connectNulls />
            <Area type="monotone" dataKey="lower" stroke="none" fill="white" fillOpacity={0} connectNulls />

            <Line
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke="#FFFFFF"
              strokeWidth={2.2}
              dot={false}
              connectNulls={false}
            />

            <Line
              type="monotone"
              dataKey="forecast"
              name={`${selectedModel} Forecast`}
              stroke={modelColor}
              strokeWidth={2.5}
              dot={false}
              strokeDasharray="6 3"
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      <div style={{ borderTop: '1px solid var(--border-glass)', marginTop: 20, paddingTop: 20 }}>
        <ForecastIntelligence
          selectedModel={selectedModel}
          onInsightsLoaded={(ins) => setLastUpdated(ins?.run_date ?? null)}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
        <span style={{ fontSize: 11, color: '#475569' }}>
          Last updated: {lastUpdated || '—'}
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

export default ForecastChart;
