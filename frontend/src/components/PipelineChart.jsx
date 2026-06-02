import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';
import { apiService } from '../services/api';
import { useTheme } from '../hooks/useTheme';

const PipelineChart = () => {
  const isDark = useTheme();
  const C = isDark ? {
    title:      '#f1f5f9',
    subtitle:   '#64748b',
    label:      '#475569',
    value:      '#f1f5f9',
    grid:       'rgba(255,255,255,0.05)',
    tick:       '#475569',
    border:     'rgba(255,255,255,0.06)',
    targetBar:  'rgba(255,255,255,0.08)',
    tooltipBg:  'rgba(15,23,42,0.95)',
    tooltipBdr: 'rgba(255,255,255,0.1)',
    tooltipTtl: '#f1f5f9',
    tooltipSub: '#64748b',
    legend:     '#64748b',
  } : {
    title:      '#0f172a',
    subtitle:   '#475569',
    label:      '#64748b',
    value:      '#0f172a',
    grid:       'rgba(0,0,0,0.06)',
    tick:       '#64748b',
    border:     'rgba(0,0,0,0.08)',
    targetBar:  'rgba(0,0,0,0.08)',
    tooltipBg:  'rgba(255,255,255,0.98)',
    tooltipBdr: 'rgba(0,0,0,0.1)',
    tooltipTtl: '#0f172a',
    tooltipSub: '#475569',
    legend:     '#334155',
  };

  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchPipelineData();
  }, []);

  const fetchPipelineData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiService.getKPIs();
      const pipelineMetrics = ['won_pipeline', 'created_pipeline', 'active_pipeline'].map(metric => {
        const kpi = response.find(k => k.id === metric);
        return {
          name: formatName(metric),
          value: kpi ? (kpi.value * (kpi.unit === 'M' ? 1000000 : 1)) : 0,
          target: kpi ? (kpi.target * (kpi.unit === 'M' ? 1000000 : 1)) : 0,
          metTarget: kpi ? kpi.value >= kpi.target : false,
          pct: kpi ? Math.round((kpi.value / kpi.target) * 100) : 0,
        };
      });
      setData(pipelineMetrics);
    } catch (err) {
      console.error('Error fetching pipeline data:', err);
      setError('demo');
      setData(getDemoData());
    } finally {
      setLoading(false);
    }
  };

  const formatName = (n) => ({ won_pipeline: 'Won', created_pipeline: 'Created', active_pipeline: 'Active' }[n] || n);

  const getDemoData = () => [
    { name: 'Won',     value: 2450000, target: 2000000, metTarget: true,  pct: 123 },
    { name: 'Created', value: 8500000, target: 7500000, metTarget: true,  pct: 113 },
    { name: 'Active',  value: 12000000,target: 10000000,metTarget: true,  pct: 120 },
  ];

  const formatCurrency = (value) => `$${(value / 1000000).toFixed(1)}M`;
  const COLORS = { Won: '#10b981', Created: '#3b82f6', Active: '#8b5cf6' };

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div style={{
          background: C.tooltipBg, border: `1px solid ${C.tooltipBdr}`,
          borderRadius: 8, padding: '10px 14px',
          boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        }}>
          <p style={{ fontSize: 12, fontWeight: 700, color: C.tooltipTtl, marginBottom: 6 }}>{d.name} Pipeline</p>
          <p style={{ fontSize: 11, color: COLORS[d.name] || '#3b82f6', margin: '2px 0' }}>Actual: {formatCurrency(d.value)}</p>
          <p style={{ fontSize: 11, color: C.tooltipSub, margin: '2px 0' }}>Target: {formatCurrency(d.target)}</p>
          <p style={{ fontSize: 10, color: d.metTarget ? '#10b981' : '#f59e0b', marginTop: 4 }}>
            {d.metTarget ? '✓ Target Met' : '⚠ Below Target'}
          </p>
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div style={{ height: 380, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 20, height: 20, borderRadius: '50%', border: '2px solid #8b5cf6', borderTopColor: 'transparent', animation: 'spin 0.7s linear infinite' }} />
      </div>
    );
  }

  return (
    <div className="luxury-chart-card" style={{ padding: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 18, gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: C.title, letterSpacing: -0.3 }}>Pipeline Overview</h2>
          <p style={{ margin: '4px 0 0', fontSize: 10, color: C.subtitle, lineHeight: 1.45 }}>Performance Hub Metrics: Won, Created, and Active Pipeline</p>
        </div>
        {error === 'demo' && (
          <span style={{ fontSize: 9, color: '#f59e0b', background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)', padding: '3px 8px', borderRadius: 999 }}>
            Demo Mode
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 14, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
          <XAxis dataKey="name" tick={{ fill: C.tick, fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} />
          <YAxis tickFormatter={formatCurrency} tick={{ fill: C.tick, fontSize: 11 }} tickLine={false} axisLine={false} width={52} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="value" name="Actual" radius={[6, 6, 0, 0]} maxBarSize={60}>
            {data.map((entry, i) => (
              <Cell key={`c-${i}`} fill={COLORS[entry.name] || '#3b82f6'} />
            ))}
          </Bar>
          <Bar dataKey="target" name="Target" fill={C.targetBar} radius={[6, 6, 0, 0]} maxBarSize={60} />
        </BarChart>
      </ResponsiveContainer>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginTop: 14, paddingTop: 12, borderTop: `1px solid ${C.border}` }}>
        {data.map((item, i) => (
          <div key={i} style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5, marginBottom: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: COLORS[item.name] || '#3b82f6' }} />
              <span style={{ fontSize: 11, color: C.label }}>{item.name}</span>
            </div>
            <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: C.value }}>{formatCurrency(item.value)}</p>
            <p style={{ margin: '2px 0 0', fontSize: 10, color: item.metTarget ? '#10b981' : '#f59e0b' }}>
              {item.pct}% of target
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default PipelineChart;

