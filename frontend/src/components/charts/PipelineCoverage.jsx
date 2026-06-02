/**
 * PipelineCoverage — Coverage gauge, trend line, YoY comparison.
 * Coverage = In-quarter open pipeline ÷ (Plan target - QTD booked)
 * Healthy: 2–4x | Risk: <2x | Excess: >4x
 */

import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine,
  ResponsiveContainer, CartesianGrid, BarChart, Bar, Cell,
} from 'recharts';

const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
};

const fmtM = (v) => v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : `$${(v / 1_000).toFixed(0)}K`;

const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#64748b', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}x</div>
      ))}
    </div>
  );
};

/** Simple SVG gauge arc for the coverage ratio */
const CoverageGauge = ({ value }) => {
  const min = 0, max = 6;
  const pct = Math.min((value - min) / (max - min), 1);
  const angle = -180 + pct * 180;
  const r = 60, cx = 80, cy = 80;
  const toXY = (deg) => ({
    x: cx + r * Math.cos((deg * Math.PI) / 180),
    y: cy + r * Math.sin((deg * Math.PI) / 180),
  });
  const start    = toXY(-180);
  const healthy1 = toXY(-180 + (2 / 6) * 180);
  const healthy2 = toXY(-180 + (4 / 6) * 180);
  const end      = toXY(0);
  const needle   = toXY(-180 + pct * 180);
  const color    = value < 2 ? '#ef4444' : value <= 4 ? '#10b981' : '#f59e0b';

  return (
    <svg width={160} height={95} viewBox="0 0 160 95">
      {/* Background arc */}
      <path d={`M ${start.x} ${start.y} A ${r} ${r} 0 0 1 ${end.x} ${end.y}`}
        fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={14} strokeLinecap="round" />
      {/* Risk zone <2x */}
      <path d={`M ${start.x} ${start.y} A ${r} ${r} 0 0 1 ${healthy1.x} ${healthy1.y}`}
        fill="none" stroke="rgba(239,68,68,0.25)" strokeWidth={14} />
      {/* Healthy zone 2–4x */}
      <path d={`M ${healthy1.x} ${healthy1.y} A ${r} ${r} 0 0 1 ${healthy2.x} ${healthy2.y}`}
        fill="none" stroke="rgba(16,185,129,0.25)" strokeWidth={14} />
      {/* Excess zone >4x */}
      <path d={`M ${healthy2.x} ${healthy2.y} A ${r} ${r} 0 0 1 ${end.x} ${end.y}`}
        fill="none" stroke="rgba(245,158,11,0.25)" strokeWidth={14} />
      {/* Value arc */}
      <path d={`M ${start.x} ${start.y} A ${r} ${r} 0 0 1 ${needle.x} ${needle.y}`}
        fill="none" stroke={color} strokeWidth={14} strokeLinecap="round" />
      {/* Value label */}
      <text x={cx} y={cy + 12} textAnchor="middle" fill={color} fontSize={22} fontWeight={800}>{value.toFixed(1)}x</text>
      <text x={cx} y={cy + 26} textAnchor="middle" fill="#475569" fontSize={9}>coverage</text>
      {/* Zone labels */}
      <text x={18}  y={90} fill="rgba(239,68,68,0.6)"  fontSize={8}>Risk</text>
      <text x={66}  y={18} fill="rgba(16,185,129,0.6)" fontSize={8}>Healthy</text>
      <text x={125} y={90} fill="rgba(245,158,11,0.6)" fontSize={8}>Excess</text>
    </svg>
  );
};

const PipelineCoverage = () => {
  const [current, setCurrent] = useState(null);
  const [yoy,     setYoy]     = useState(null);
  const [trend,   setTrend]   = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const [curRes, yoyRes, trendRes] = await Promise.all([
          fetch('/api/coverage/current').then(r => r.json()),
          fetch('/api/coverage/yoy').then(r => r.json()),
          fetch('/api/coverage/trend').then(r => r.json()),
        ]);
        if (cancelled) return;
        setCurrent(curRes);
        setYoy(yoyRes);
        setTrend(trendRes.data ?? []);
      } catch (e) {
        console.error('PipelineCoverage load error', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const axisStyle = { fill: '#475569', fontSize: 10 };
  const gridStyle = { stroke: 'rgba(255,255,255,0.05)' };
  const coverageColor = !current ? '#3b82f6'
    : current.coverage_ratio < 2 ? '#ef4444'
    : current.coverage_ratio <= 4 ? '#10b981'
    : '#f59e0b';

  // YoY bar data
  const yoyBars = !yoy ? [] : [
    { label: 'Last Year', value: yoy.prior_year?.coverage_ratio ?? 0 },
    { label: 'This Year',  value: yoy.current?.coverage_ratio   ?? 0 },
  ];

  return (
    <div className="glass-card luxury-chart-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', letterSpacing: -0.3 }}>🎯 Pipeline Coverage</div>
        <div style={{ fontSize: 10, color: '#475569', marginTop: 4, lineHeight: 1.45 }}>
          In-quarter open pipeline ÷ remaining target — healthy range: 2–4x
        </div>
      </div>

      {loading ? (
        <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading coverage data…
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr 140px', gap: 16, alignItems: 'start' }}>

          {/* Gauge */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            {current && <CoverageGauge value={current.coverage_ratio} />}
            {current?.insight && (
              <div style={{
                marginTop: 6, fontSize: 10, color: '#94a3b8', lineHeight: 1.4, textAlign: 'center',
                borderLeft: `2px solid ${coverageColor}`, paddingLeft: 6,
              }}>
                {current.insight}
              </div>
            )}
          </div>

          {/* Trend line */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
              Coverage this quarter
            </div>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={trend} margin={{ left: 0, right: 8, top: 14, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={axisStyle} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={32} domain={[0, 6]} tickFormatter={(v) => `${v}x`} />
                <Tooltip content={<DarkTooltip />} />
                <ReferenceLine y={2} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '2x', fill: '#ef4444', fontSize: 9, position: 'left' }} />
                <ReferenceLine y={4} stroke="#f59e0b" strokeDasharray="4 2" label={{ value: '4x', fill: '#f59e0b', fontSize: 9, position: 'left' }} />
                <Line type="monotone" dataKey="coverage_ratio" name="Coverage" stroke={coverageColor} dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* YoY comparison */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
              vs Last Year
            </div>
            <ResponsiveContainer width="100%" height={100}>
              <BarChart data={yoyBars} margin={{ left: 4, right: 4, top: 4, bottom: 0 }} barCategoryGap="30%">
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={28} domain={[0, 6]} tickFormatter={(v) => `${v}x`} />
                <XAxis dataKey="label" tick={{ ...axisStyle, fontSize: 8 }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v) => [`${v.toFixed(2)}x`, 'Coverage']} contentStyle={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }} />
                <Bar dataKey="value" radius={[3,3,0,0]}>
                  {yoyBars.map((b, i) => (
                    <Cell key={i} fill={b.value < 2 ? '#ef4444' : b.value <= 4 ? '#10b981' : '#f59e0b'} fillOpacity={0.75} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            {yoy && (
              <div style={{ textAlign: 'center', marginTop: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: yoy.coverage_yoy_delta >= 0 ? '#10b981' : '#ef4444' }}>
                  {yoy.coverage_yoy_delta >= 0 ? '+' : ''}{yoy.coverage_yoy_delta?.toFixed(2)}x YoY
                </span>
              </div>
            )}
          </div>

        </div>
      )}
    </div>
  );
};

export default PipelineCoverage;
