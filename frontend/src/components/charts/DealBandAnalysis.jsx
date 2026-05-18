/**
 * DealBandAnalysis — Volume, value, win rate, and cycle time per deal size band.
 * Compares current period vs YoY or prior quarter.
 * AI flags lagging/leading/deal-size-shrinking bands.
 */

import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, CartesianGrid } from 'recharts';

const fmtM = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(0)}K`;
  return `$${Math.round(v)}`;
};

const SEV_COLORS = { high: '#ef4444', medium: '#f59e0b', opportunity: '#10b981' };

const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#94a3b8', fontWeight: 700, marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {p.value?.toLocaleString?.() ?? p.value}</div>
      ))}
    </div>
  );
};

const METRIC_OPTIONS = [
  { key: 'value',    label: '$ Value',   fmt: fmtM },
  { key: 'volume',   label: '# Deals',   fmt: (v) => v.toLocaleString() },
  { key: 'win_rate', label: 'Win Rate',  fmt: (v) => `${v?.toFixed(1)}%` },
  { key: 'avg_cycle_days', label: 'Avg Cycle', fmt: (v) => `${v}d` },
];

const DealBandAnalysis = () => {
  const [compare, setCompare] = useState('yoy');
  const [metric,  setMetric]  = useState('value');
  const [bands,   setBands]   = useState([]);
  const [insights, setInsights] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const res  = await fetch(`/api/deal-bands/performance?compare=${compare}`);
        const json = await res.json();
        if (cancelled) return;
        setBands(json.data ?? []);
        setInsights(json.insights ?? []);
      } catch (e) {
        console.error('DealBandAnalysis load error', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [compare]);

  const axisStyle = { fill: '#475569', fontSize: 9 };
  const gridStyle = { stroke: 'rgba(255,255,255,0.05)' };

  const metricMeta = METRIC_OPTIONS.find(m => m.key === metric) || METRIC_OPTIONS[0];
  const priorKey   = metric === 'value' ? 'prior_value' : metric === 'volume' ? 'prior_volume' : null;

  const chartData = bands.map(b => ({
    band:       b.band,
    current:    b[metric],
    prior:      priorKey ? b[priorKey] : null,
    chg_pct:    metric === 'value' ? b.value_chg_pct : metric === 'volume' ? b.volume_chg_pct : null,
  }));

  return (
    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>💼 Deal Band Analysis</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>Performance by deal size — volume, value, win rate, cycle time</div>
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {/* Compare toggle */}
          {['yoy', 'prior_quarter'].map(c => (
            <button key={c} onClick={() => setCompare(c)} style={{
              padding: '3px 9px', borderRadius: 16, fontSize: 10, fontWeight: 700, cursor: 'pointer',
              background: compare === c ? 'rgba(245,158,11,0.15)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${compare === c ? '#f59e0b' : 'rgba(255,255,255,0.08)'}`,
              color: compare === c ? '#f59e0b' : '#475569',
            }}>{c === 'yoy' ? 'vs YoY' : 'vs Prev Q'}</button>
          ))}
          {/* Metric toggle */}
          {METRIC_OPTIONS.map(m => (
            <button key={m.key} onClick={() => setMetric(m.key)} style={{
              padding: '3px 9px', borderRadius: 16, fontSize: 10, fontWeight: 700, cursor: 'pointer',
              background: metric === m.key ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${metric === m.key ? '#3b82f6' : 'rgba(255,255,255,0.08)'}`,
              color: metric === m.key ? '#3b82f6' : '#475569',
            }}>{m.label}</button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading deal band data…
        </div>
      ) : (
        <>
          {/* Bar chart */}
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData} margin={{ left: 4, right: 4, top: 4, bottom: 4 }} barCategoryGap="30%">
              <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
              <XAxis dataKey="band" tick={{ ...axisStyle, fontSize: 8 }} axisLine={false} tickLine={false} />
              <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={48}
                tickFormatter={metricMeta.fmt} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                formatter={(v) => [metricMeta.fmt(v)]} />
              <Bar dataKey="current" name="Current" radius={[3,3,0,0]}>
                {chartData.map((entry, i) => (
                  <Cell key={i}
                    fill={
                      entry.chg_pct !== null
                        ? entry.chg_pct < -10 ? '#ef4444'
                        : entry.chg_pct > 15  ? '#10b981'
                        : '#3b82f6'
                        : '#3b82f6'
                    }
                    fillOpacity={0.78}
                  />
                ))}
              </Bar>
              {priorKey && (
                <Bar dataKey="prior" name="Prior" fill="rgba(255,255,255,0.12)" radius={[3,3,0,0]} />
              )}
            </BarChart>
          </ResponsiveContainer>

          {/* Summary stats row */}
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${bands.length}, 1fr)`, gap: 4, marginTop: 8 }}>
            {bands.map((b, i) => (
              <div key={i} style={{
                textAlign: 'center', padding: '6px 4px', borderRadius: 6,
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.06)',
              }}>
                <div style={{ fontSize: 8, color: '#475569', marginBottom: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{b.band}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#f1f5f9' }}>{metricMeta.fmt(b[metric])}</div>
                {b.value_chg_pct !== undefined && (
                  <div style={{ fontSize: 9, fontWeight: 600, color: b.value_chg_pct < 0 ? '#f87171' : '#6ee7b7', marginTop: 1 }}>
                    {b.value_chg_pct > 0 ? '+' : ''}{b.value_chg_pct?.toFixed(0)}%
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* AI insights */}
          {insights.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {insights.map((ins, i) => (
                <div key={i} style={{
                  padding: '6px 10px', borderRadius: '0 6px 6px 0',
                  borderLeft: `3px solid ${SEV_COLORS[ins.severity] || '#3b82f6'}`,
                  background: `${SEV_COLORS[ins.severity] || '#3b82f6'}0f`,
                  fontSize: 11, color: '#cbd5e1',
                }}>
                  <span style={{ color: SEV_COLORS[ins.severity], marginRight: 6 }}>
                    {ins.severity === 'high' ? '⚠️' : ins.severity === 'opportunity' ? '✨' : '💡'}
                  </span>
                  {ins.message}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default DealBandAnalysis;
