import { useMemo, useState, useEffect, useCallback, useRef } from 'react';
// ╔══════════════════════════════════════════════════════════════════════╗
// ║  DEPRECATED — V1 forecast chart (forecast_prophet table, no scheduled
// ║  writer). Superseded by ForecastingPanel (V2) wired in App.jsx.
// ║  Do NOT delete until ForecastingPanel is confirmed stable in prod.
// ║  TODO: delete after confirming V2 is working in production.
// ╚══════════════════════════════════════════════════════════════════════╝
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
import { ChartExportBar } from '../../utils/chartExport';

// Primary model sourced from forecast_prophet (read-only).
// Other models shown as "planned" — wired in once their tables are ready.
const MODELS = [
  { label: 'Prophet',  color: '#FF6B6B', primary: true  },
  { label: 'Ensemble', color: '#00FF88', primary: false },
  { label: 'LightGBM', color: '#00BFFF', primary: false },
  { label: 'ETS',      color: '#f59e0b', primary: false },
];

const MODEL_TO_API = {
  Prophet: 'prophet',
  Ensemble: 'ensemble',
  LightGBM: 'lightgbm',
  ETS: 'ets',
};

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
  const chartRef = useRef(null);
  const [selectedModel, setSelectedModel] = useState('Prophet');
  const [selectedProduct, setSelectedProduct] = useState('All');
  const [forecastData, setForecastData] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [products, setProducts] = useState([]);
  const [source, setSource] = useState('demo');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const productParam = selectedProduct && selectedProduct !== 'All'
        ? `?product=${encodeURIComponent(selectedProduct)}`
        : '';
      // Leaderboard is optional — don't fail the whole load if it errors
      const [arrRes, lbRes] = await Promise.allSettled([
        fetch(`/api/forecast/arr${productParam}`),
        fetch('/api/forecast/leaderboard'),
      ]);

      if (arrRes.status === 'rejected' || !arrRes.value?.ok) {
        throw new Error(arrRes.reason?.message ?? `ARR HTTP ${arrRes.value?.status}`);
      }

      const arrJson = await arrRes.value.json();
      const lbJson  = lbRes.status === 'fulfilled' && lbRes.value?.ok
        ? await lbRes.value.json()
        : { data: [] };

      setForecastData(arrJson.data ?? null);
      setLeaderboard(lbJson.data ?? []);
      setProducts(arrJson.products ?? []);
      setSource(arrJson.source ?? 'demo');
      setLastUpdated(new Date().toLocaleString());

      // Auto-select Prophet when live data loads — it's the only model in forecast_prophet
      if ((arrJson.source ?? 'demo') === 'live') {
        setSelectedModel('Prophet');
      }
    } catch (e) {
      setError(e.message || 'Failed to load forecast data');
    } finally {
      setLoading(false);
    }
  }, [selectedProduct]);

  useEffect(() => {
    load();
  }, [load]);

  const prophetColor = '#FF6B6B';
  // When live, always render the Prophet line regardless of selectedModel (only Prophet has data)
  const effectiveModel = (source === 'live' && (forecastData?.[selectedModel]?.forecast ?? []).length === 0)
    ? 'Prophet'
    : selectedModel;
  const effectiveColor = MODELS.find((m) => m.label === effectiveModel)?.color ?? prophetColor;
  const selectedM = leaderboard.find(
    (r) => r.model === selectedModel &&
           (selectedProduct === 'All' || r.product === selectedProduct)
  );

  const chartData = useMemo(() => {
    if (!forecastData) return [];

    const actualSeries = forecastData.actual?.actuals ?? [];
    // Use effectiveModel so chart always shows data (falls back to Prophet when live)
    const forecastSeries = forecastData[effectiveModel]?.forecast ?? [];

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
      // For stacked confidence band: lowerBound + bandwidth = full range
      row.lowerBound = row.lower;
      row.bandwidth = Math.max(0, row.upper - row.lower);
      byDate.set(date, row);
    }

    return Array.from(byDate.values()).sort((a, b) => new Date(a.date) - new Date(b.date));
  }, [forecastData, effectiveModel]);

  return (
    <div className="glass-card luxury-chart-card" style={{ padding: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', letterSpacing: -0.3 }}>
            Forecast
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 4, lineHeight: 1.45 }}>
            Weekly ARR · Most Likely / Best Case / Worst Case ·{' '}
            <span style={{ color: '#64748b' }}>mdl_sales_analytics.forecast_prophet</span>
          </div>
        </div>

        {!loading && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {/* MAPE badge: display live leaderboard value when available */}
            <div style={{
              padding: '4px 9px', borderRadius: 999,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              fontSize: 10, color: '#94a3b8',
            }}>
              MAPE{' '}
              <span style={{ color: '#FF6B6B', fontWeight: 700 }}>
                {selectedM
                  ? `${Number(selectedM.mape).toFixed(1)}%`
                  : '—'}
              </span>
            </div>
            <div style={{
              padding: '4px 9px', borderRadius: 999,
              background: source === 'live' ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.08)',
              border: `1px solid ${source === 'live' ? 'rgba(16,185,129,0.25)' : 'rgba(245,158,11,0.2)'}`,
              fontSize: 10,
              color: source === 'live' ? '#10b981' : '#f59e0b',
              fontWeight: 700,
            }}>
              {source === 'live' ? 'LIVE' : 'DEMO'}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8, alignItems: 'center' }}>
        {MODELS.map((m) => {
          const isActive   = selectedModel === m.label;
          const hasFcData  = (forecastData?.[m.label]?.forecast ?? []).length > 0;
          // Show as available if: demo mode OR it's Prophet OR it genuinely has data
          const available  = !forecastData || source !== 'live' || hasFcData;
          return (
            <button
              key={m.label}
              onClick={() => available ? setSelectedModel(m.label) : undefined}
              title={!available ? `${m.label} data not yet available — add ${m.label} table to enable` : ''}
              style={{
                padding: '4px 10px',
                borderRadius: 999,
                fontSize: 10,
                fontWeight: 700,
                cursor: available ? 'pointer' : 'not-allowed',
                opacity: available ? 1 : 0.35,
                background: isActive ? `${m.color}22` : 'rgba(255,255,255,0.04)',
                border: `1px solid ${isActive ? m.color : 'rgba(255,255,255,0.08)'}`,
                color: isActive ? m.color : available ? '#64748b' : '#374151',
                position: 'relative',
              }}
            >
              {m.label}
              {!available && (
                <span style={{ marginLeft: 4, fontSize: 8, color: '#374151', fontWeight: 400 }}>
                  soon
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Product filter */}
      {products.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
          {['All', ...products].map((p) => (
            <button
              key={p}
              onClick={() => setSelectedProduct(p)}
              style={{
                padding: '3px 9px',
                borderRadius: 999,
                fontSize: 9,
                fontWeight: 600,
                cursor: 'pointer',
                background: selectedProduct === p ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${selectedProduct === p ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.07)'}`,
                color: selectedProduct === p ? '#f1f5f9' : '#475569',
              }}
            >
              {p}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading live forecast…
        </div>
      ) : error ? (
        <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ef4444', fontSize: 12 }}>
          {error}
        </div>
      ) : (
        <>
          <ChartExportBar
            containerRef={chartRef}
            data={chartData}
            columns={['date', 'actual', 'forecast', 'lower', 'upper']}
            filename={`forecast-${selectedModel.toLowerCase().replace(/\s+/g,'-')}`}
          />
          <div ref={chartRef}>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={chartData} margin={{ left: 8, right: 8, top: 14, bottom: 0 }}>
                <defs>
                  <linearGradient id="fcBandGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={effectiveColor} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={effectiveColor} stopOpacity={0.05} />
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

                {/* Confidence band: stacked approach — lowerBound transparent, bandwidth colored */}
                <Area
                  type="monotone"
                  dataKey="lowerBound"
                  stackId="confidence"
                  stroke="none"
                  fill="transparent"
                  fillOpacity={0}
                  connectNulls
                  legendType="none"
                  name=""
                />
                <Area
                  type="monotone"
                  dataKey="bandwidth"
                  stackId="confidence"
                  stroke={effectiveColor}
                  strokeWidth={0.5}
                  strokeDasharray="2 4"
                  strokeOpacity={0.4}
                  fill="url(#fcBandGrad)"
                  connectNulls
                  name="Confidence Band"
                />

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
                  name={`${effectiveModel} Forecast`}
                  stroke={effectiveColor}
                  strokeWidth={2.5}
                  dot={false}
                  strokeDasharray="6 3"
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      <div style={{ borderTop: '1px solid var(--border-glass)', marginTop: 20, paddingTop: 20 }}>
        <ForecastIntelligence
          model={MODEL_TO_API[selectedModel] ?? 'prophet'}
          metric="won_pipeline"
          productLine={selectedProduct}
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
