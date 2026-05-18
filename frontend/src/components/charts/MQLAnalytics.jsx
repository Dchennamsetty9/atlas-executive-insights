/**
 * MQLAnalytics — MQL volume over time, MQL-to-Opp conversion, vs-target comparison.
 * Three Recharts line charts in a dark glass panel.
 */

import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid, Legend,
} from 'recharts';

const PERIODS = ['daily', 'weekly', 'monthly'];

const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
};

const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#64748b', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, fontWeight: 600 }}>{p.name}: {typeof p.value === 'number' ? p.value.toLocaleString() : p.value}</div>
      ))}
    </div>
  );
};

const MQLAnalytics = () => {
  const [period,     setPeriod]     = useState('daily');
  const [volume,     setVolume]     = useState([]);
  const [conversion, setConversion] = useState({ data: [], insight: '', trend: '' });
  const [vsTarget,   setVsTarget]   = useState([]);
  const [loading,    setLoading]    = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const [volRes, convRes, targetRes] = await Promise.all([
          fetch(`/api/mql/volume?period=${period}`).then(r => r.json()),
          fetch('/api/mql/conversion').then(r => r.json()),
          fetch('/api/mql/vs-target').then(r => r.json()),
        ]);
        if (cancelled) return;
        setVolume(volRes.data ?? []);
        setConversion({ data: convRes.data ?? [], insight: convRes.insight ?? '', trend: convRes.trend ?? 'stable' });
        setVsTarget(targetRes.data ?? []);
      } catch (e) {
        console.error('MQLAnalytics load error', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [period]);

  const axisStyle = { fill: '#475569', fontSize: 10 };
  const gridStyle = { stroke: 'rgba(255,255,255,0.05)' };

  return (
    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>📈 MQL Analytics</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
            Marketing Qualified Leads — volume, conversion, and pacing
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {PERIODS.map(p => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: '3px 10px', borderRadius: 16, fontSize: 10, fontWeight: 700, cursor: 'pointer',
              background: period === p ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${period === p ? '#3b82f6' : 'rgba(255,255,255,0.08)'}`,
              color: period === p ? '#3b82f6' : '#475569',
              textTransform: 'capitalize',
            }}>{p}</button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading MQL data…
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>

          {/* Chart 1 — Volume over time */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>
              MQL Volume
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={volume} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={axisStyle} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={36} />
                <Tooltip content={<DarkTooltip />} />
                <Line type="monotone" dataKey="mql_count"   name="MQLs"   stroke="#3b82f6" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="trial_count" name="Trials" stroke="#8b5cf6" dot={false} strokeWidth={1.5} strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Chart 2 — Conversion rate */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>
              MQL → Opp Conversion %
            </div>
            {conversion.insight && (
              <div style={{
                fontSize: 10, color: conversion.trend === 'declining' ? '#f87171' : '#6ee7b7',
                marginBottom: 6, lineHeight: 1.4,
                borderLeft: `2px solid ${conversion.trend === 'declining' ? '#ef4444' : '#10b981'}`,
                paddingLeft: 6,
              }}>
                {conversion.insight}
              </div>
            )}
            <ResponsiveContainer width="100%" height={conversion.insight ? 130 : 160}>
              <LineChart data={conversion.data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={axisStyle} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={36} tickFormatter={v => `${(v * 100).toFixed(0)}%`} />
                <Tooltip content={<DarkTooltip />} formatter={(v) => [`${(v * 100).toFixed(1)}%`]} />
                <ReferenceLine y={0.18} stroke="#f59e0b" strokeDasharray="4 2" label={{ value: 'Benchmark 18%', fill: '#f59e0b', fontSize: 9, position: 'right' }} />
                <Line type="monotone" dataKey="conversion_rate" name="Conv. Rate" stroke="#10b981" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Chart 3 — Actual vs Target */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>
              Actual vs Daily Target
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={vsTarget} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={axisStyle} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={36} />
                <Tooltip content={<DarkTooltip />} />
                <Line type="monotone" dataKey="actual" name="Actual" stroke="#3b82f6" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="target" name="Target" stroke="#f59e0b" dot={false} strokeWidth={1.5} strokeDasharray="5 3" />
              </LineChart>
            </ResponsiveContainer>
          </div>

        </div>
      )}
    </div>
  );
};

export default MQLAnalytics;
