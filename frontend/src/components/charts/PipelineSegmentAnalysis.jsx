/**
 * PipelineSegmentAnalysis — Pipeline $ value and deal volume broken down by segment.
 * Dimension switcher: Channel | Geo | Fuel Mix | Product | Purchase Type
 * Comparison: YoY | QoQ
 * AI flags for lagging/leading/shrinking-deal-size segments.
 */

import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, CartesianGrid } from 'recharts';

const DIMENSIONS = [
  { value: 'channel',  label: 'Channel'  },
  { value: 'geo',      label: 'Geo'      },
  { value: 'fuel_mix', label: 'Fuel Mix' },
  { value: 'product',  label: 'Product'  },
  { value: 'purchase', label: 'Purchase' },
];

const COMPARES = [
  { value: 'yoy', label: 'vs YoY' },
  { value: 'qoq', label: 'vs QoQ' },
];

const SEV_COLORS = {
  high:        '#ef4444',
  medium:      '#f59e0b',
  opportunity: '#10b981',
};

const fmtM = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v}`;
};

const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#94a3b8', fontWeight: 700, marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {fmtM(p.value)}</div>
      ))}
    </div>
  );
};

const PipelineSegmentAnalysis = () => {
  const [dimension, setDimension] = useState('channel');
  const [compare,   setCompare]   = useState('yoy');
  const [data,      setData]      = useState([]);
  const [insights,  setInsights]  = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [view,      setView]      = useState('value');   // 'value' | 'volume'

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const res  = await fetch(`/api/pipeline/segments?dimension=${dimension}&compare=${compare}`);
        const json = await res.json();
        if (cancelled) return;
        setData(json.data ?? []);
        setInsights(json.insights ?? []);
      } catch (e) {
        console.error('PipelineSegmentAnalysis load error', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [dimension, compare]);

  const axisStyle = { fill: '#475569', fontSize: 10 };
  const gridStyle = { stroke: 'rgba(255,255,255,0.05)' };

  const chartData = data.map(d => ({
    segment:        d.segment,
    current_value:  d.current_value,
    prior_value:    d.prior_value,
    current_volume: d.current_volume,
    prior_volume:   d.prior_volume,
    chg_pct:        view === 'value' ? d.value_yoy_pct : d.volume_yoy_pct,
  }));

  return (
    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>🗂 Pipeline by Segment</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>Pipeline value and deal count, current vs prior period</div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {/* Dimension picker */}
          <div style={{ display: 'flex', gap: 3 }}>
            {DIMENSIONS.map(d => (
              <button key={d.value} onClick={() => setDimension(d.value)} style={{
                padding: '3px 9px', borderRadius: 16, fontSize: 10, fontWeight: 700, cursor: 'pointer',
                background: dimension === d.value ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${dimension === d.value ? '#3b82f6' : 'rgba(255,255,255,0.08)'}`,
                color: dimension === d.value ? '#3b82f6' : '#475569',
              }}>{d.label}</button>
            ))}
          </div>
          {/* Compare + view toggles */}
          <div style={{ display: 'flex', gap: 3 }}>
            {COMPARES.map(c => (
              <button key={c.value} onClick={() => setCompare(c.value)} style={{
                padding: '3px 9px', borderRadius: 16, fontSize: 10, fontWeight: 700, cursor: 'pointer',
                background: compare === c.value ? 'rgba(245,158,11,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${compare === c.value ? '#f59e0b' : 'rgba(255,255,255,0.08)'}`,
                color: compare === c.value ? '#f59e0b' : '#475569',
              }}>{c.label}</button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 3 }}>
            {['value', 'volume'].map(v => (
              <button key={v} onClick={() => setView(v)} style={{
                padding: '3px 9px', borderRadius: 16, fontSize: 10, fontWeight: 700, cursor: 'pointer',
                background: view === v ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${view === v ? '#10b981' : 'rgba(255,255,255,0.08)'}`,
                color: view === v ? '#10b981' : '#475569',
                textTransform: 'capitalize',
              }}>{v === 'value' ? '$ Value' : '# Deals'}</button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading segment data…
        </div>
      ) : (
        <>
          {/* Bar chart */}
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData} margin={{ left: 4, right: 4, top: 4, bottom: 4 }} barCategoryGap="35%">
              <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
              <XAxis dataKey="segment" tick={{ ...axisStyle, fontSize: 9 }} axisLine={false} tickLine={false} />
              <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={48}
                tickFormatter={view === 'value' ? fmtM : (v) => v.toLocaleString()} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
              <Bar dataKey={view === 'value' ? 'current_value' : 'current_volume'} name="Current" radius={[3,3,0,0]}>
                {chartData.map((entry, i) => (
                  <Cell key={i}
                    fill={entry.chg_pct < -10 ? '#ef4444' : entry.chg_pct > 15 ? '#10b981' : '#3b82f6'}
                    fillOpacity={0.75} />
                ))}
              </Bar>
              <Bar dataKey={view === 'value' ? 'prior_value' : 'prior_volume'} name="Prior" fill="rgba(255,255,255,0.12)" radius={[3,3,0,0]} />
            </BarChart>
          </ResponsiveContainer>

          {/* YoY/QoQ change row */}
          <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
            {chartData.map((d, i) => (
              <div key={i} style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                padding: '4px 8px', borderRadius: 6,
                background: d.chg_pct < -10 ? 'rgba(239,68,68,0.08)' : d.chg_pct > 15 ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${d.chg_pct < -10 ? 'rgba(239,68,68,0.2)' : d.chg_pct > 15 ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.06)'}`,
                minWidth: 60,
              }}>
                <span style={{ fontSize: 9, color: '#475569', marginBottom: 2 }}>{d.segment}</span>
                <span style={{
                  fontSize: 12, fontWeight: 800,
                  color: d.chg_pct < 0 ? '#ef4444' : '#10b981',
                }}>
                  {d.chg_pct > 0 ? '+' : ''}{d.chg_pct?.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>

          {/* AI Insights */}
          {insights.length > 0 && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 5 }}>
              {insights.map((ins, i) => (
                <div key={i} style={{
                  display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 10px',
                  borderLeft: `3px solid ${SEV_COLORS[ins.severity] || '#3b82f6'}`,
                  background: `${SEV_COLORS[ins.severity] || '#3b82f6'}11`,
                  borderRadius: '0 6px 6px 0', fontSize: 11, color: '#cbd5e1',
                }}>
                  <span style={{ color: SEV_COLORS[ins.severity], flexShrink: 0, fontSize: 14 }}>
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

export default PipelineSegmentAnalysis;
