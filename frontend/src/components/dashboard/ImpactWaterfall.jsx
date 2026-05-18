/**
 * ImpactWaterfall — Revenue gap decomposition chart.
 * Fetches /api/insights/impact-decomposition and renders each KPI's
 * dollarized gap contribution as a horizontal bar chart.
 *
 * Only renders when revenue is below target (decomposition endpoint returns data).
 */

import { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  ResponsiveContainer, LabelList,
} from 'recharts';

const fmtDollar = (v) => {
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000)     return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  return `${sign}$${abs.toFixed(0)}`;
};

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{
      background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 6, padding: '8px 12px', fontSize: 12,
    }}>
      <div style={{ color: '#94a3b8', marginBottom: 3 }}>{d.name}</div>
      <div style={{ color: d.raw < 0 ? '#ef4444' : '#10b981', fontWeight: 700, fontSize: 14 }}>
        {fmtDollar(d.raw)}
      </div>
      <div style={{ color: '#64748b', marginTop: 2, fontSize: 11 }}>revenue impact</div>
    </div>
  );
};

const ImpactWaterfall = ({ filters }) => {
  const [bars,    setBars]    = useState([]);
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (filters?.product && filters.product !== 'All') params.set('product', filters.product);
        if (filters?.geo     && filters.geo     !== 'All') params.set('geo',     filters.geo);
        if (filters?.channel && filters.channel !== 'All') params.set('channel', filters.channel);

        const res  = await fetch(`/api/insights/impact-decomposition?${params}`);
        const json = await res.json();
        if (cancelled) return;

        const decomp = json.decomposition?.[0];
        if (!decomp?.impacts) return;

        const chartBars = Object.entries(decomp.impacts)
          .map(([name, raw]) => ({
            name,
            raw,
            value: Math.abs(raw),   // bar length
          }))
          .sort((a, b) => Math.abs(b.raw) - Math.abs(a.raw));

        setBars(chartBars);
        setSummary(decomp.description ?? '');
      } catch {
        if (!cancelled) setBars([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => { cancelled = true; };
  }, [filters]);

  // Only render when there are negative bars (revenue below target)
  const hasGap = bars.some(b => b.raw < 0);
  if (loading || !hasGap) return null;

  const chartHeight = Math.max(60, bars.length * 36 + 24);

  return (
    <div className="glass-card" style={{ padding: '14px 16px', marginBottom: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 16 }}>💰</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>
            Revenue Gap Decomposition
          </div>
          {summary && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2, lineHeight: 1.4 }}>
              {summary}
            </div>
          )}
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={bars}
          layout="vertical"
          margin={{ left: 100, right: 80, top: 0, bottom: 0 }}
          barSize={18}
        >
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={96}
            tick={{ fill: '#64748b', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {bars.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.raw < 0 ? '#ef4444' : '#10b981'}
                fillOpacity={0.75}
              />
            ))}
            <LabelList
              dataKey="raw"
              position="right"
              formatter={fmtDollar}
              style={{ fill: '#94a3b8', fontSize: 11, fontWeight: 600 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ImpactWaterfall;
