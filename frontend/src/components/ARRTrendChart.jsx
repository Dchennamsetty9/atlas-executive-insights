import { useState, useEffect, useMemo } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { apiService } from '../services/api';
import { useTheme } from '../hooks/useTheme';

const PERIODS = [
  { label: '3M',  months: 3  },
  { label: '6M',  months: 6  },
  { label: '12M', months: 12 },
  { label: 'All', months: 0  },
];

const ARRTrendChart = () => {
  const isDark = useTheme();
  const C = isDark ? {
    title:      '#f1f5f9',
    subtitle:   '#64748b',
    label:      '#475569',
    value:      '#f1f5f9',
    valueSecondary: '#94a3b8',
    grid:       'rgba(255,255,255,0.04)',
    tick:       '#475569',
    border:     'rgba(255,255,255,0.06)',
    cardBg:     'rgba(255,255,255,0.03)',
    cardBorder: 'rgba(255,255,255,0.06)',
    pillBg:     'rgba(255,255,255,0.06)',
    pillActive: 'rgba(59,130,246,0.18)',
    pillActiveBorder: 'rgba(59,130,246,0.45)',
    tooltipBg:  'rgba(10,15,30,0.97)',
    tooltipBdr: 'rgba(59,130,246,0.3)',
    refLine:    'rgba(99,102,241,0.25)',
  } : {
    title:      '#0f172a',
    subtitle:   '#475569',
    label:      '#64748b',
    value:      '#0f172a',
    valueSecondary: '#334155',
    grid:       'rgba(0,0,0,0.05)',
    tick:       '#94a3b8',
    border:     'rgba(0,0,0,0.08)',
    cardBg:     '#f8fafc',
    cardBorder: 'rgba(0,0,0,0.07)',
    pillBg:     '#f1f5f9',
    pillActive: 'rgba(59,130,246,0.1)',
    pillActiveBorder: 'rgba(59,130,246,0.4)',
    tooltipBg:  'rgba(255,255,255,0.99)',
    tooltipBdr: 'rgba(59,130,246,0.25)',
    refLine:    'rgba(99,102,241,0.2)',
  };

  const [allData, setAllData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isDemo, setIsDemo] = useState(false);
  const [dataSource, setDataSource] = useState(null);
  const [period, setPeriod] = useState('12M');

  useEffect(() => { fetchARRData(); }, []);

  const fetchARRData = async () => {
    try {
      setLoading(true);
      setIsDemo(false);
      const response = await apiService.getARRHistory();
      if (response.history && response.history.length > 0) {
        const formatted = response.history.map(item => ({
          date: new Date(item.ds).toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
          arr:  item.y,
          growth: item.growth_pct || 0,
        }));
        setAllData(formatted);
        setIsDemo(response.demo_mode === true);
        setDataSource(response.source || null);
      } else {
        setAllData(getDemoData());
        setIsDemo(true);
        setDataSource(null);
      }
    } catch (err) {
      console.error('ARR fetch error:', err);
      setAllData(getDemoData());
      setIsDemo(true);
      setDataSource(null);
    } finally {
      setLoading(false);
    }
  };

  const getDemoData = () => {
    const labels = ['Jun\'24','Jul\'24','Aug\'24','Sep\'24','Oct\'24','Nov\'24','Dec\'24',
                    'Jan\'25','Feb\'25','Mar\'25','Apr\'25','May\'25','Jun\'25','Jul\'25',
                    'Aug\'25','Sep\'25','Oct\'25','Nov\'25','Dec\'25','Jan\'26','Feb\'26',
                    'Mar\'26','Apr\'26','May\'26'];
    let base = 48_000_000;
    return labels.map((date, i) => {
      const bump = 400_000 + Math.sin(i * 0.7) * 200_000;
      base += bump;
      return { date, arr: Math.round(base), growth: (bump / (base - bump)) * 100 };
    });
  };

  // Slice to selected period
  const data = useMemo(() => {
    const p = PERIODS.find(p => p.label === period);
    if (!p || p.months === 0) return allData;
    return allData.slice(-p.months);
  }, [allData, period]);

  // Derived stats
  const stats = useMemo(() => {
    if (!data.length) return null;
    const current  = data[data.length - 1].arr;
    const start    = data[0].arr;
    const netChange = current - start;
    const netPct   = start > 0 ? (netChange / start) * 100 : 0;
    const growthVals = data.filter(d => d.growth !== 0).map(d => d.growth);
    const avgGrowth  = growthVals.length ? growthVals.reduce((s, v) => s + v, 0) / growthVals.length : 0;
    const peakArr    = Math.max(...data.map(d => d.arr));
    return { current, start, netChange, netPct, avgGrowth, peakArr };
  }, [data]);

  const fmt = (v) => v >= 1e9 ? `$${(v/1e9).toFixed(2)}B` : `$${(v/1e6).toFixed(1)}M`;
  const fmtShort = (v) => v >= 1e9 ? `$${(v/1e9).toFixed(1)}B` : `$${(v/1e6).toFixed(0)}M`;

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    const up = d.growth >= 0;
    return (
      <div style={{
        background: C.tooltipBg, border: `1px solid ${C.tooltipBdr}`,
        borderRadius: 10, padding: '12px 16px', minWidth: 160,
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      }}>
        <p style={{ fontSize: 11, color: C.label, margin: '0 0 8px', fontWeight: 600, letterSpacing: 0.3 }}>{d.date}</p>
        <p style={{ fontSize: 18, fontWeight: 800, color: '#3b82f6', margin: '0 0 6px', letterSpacing: -0.5 }}>
          {fmt(d.arr)}
        </p>
        {d.growth !== 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{
              fontSize: 10, fontWeight: 700,
              color: up ? '#10b981' : '#f87171',
              background: up ? 'rgba(16,185,129,0.1)' : 'rgba(248,113,113,0.1)',
              border: `1px solid ${up ? 'rgba(16,185,129,0.25)' : 'rgba(248,113,113,0.25)'}`,
              borderRadius: 4, padding: '1px 6px',
            }}>
              {up ? '▲' : '▼'} {Math.abs(d.growth).toFixed(2)}% MoM
            </span>
          </div>
        )}
      </div>
    );
  };

  // Tick formatter: show every 3rd label to avoid crowding
  const tickFormatter = (val, idx) => idx % 3 === 0 ? val : '';

  if (loading) {
    return (
      <div style={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 22, height: 22, borderRadius: '50%', border: '2.5px solid #3b82f6', borderTopColor: 'transparent', animation: 'spin 0.7s linear infinite' }} />
      </div>
    );
  }

  return (
    <div className="luxury-chart-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: C.title, letterSpacing: -0.4 }}>ARR Trend</h2>
          <p style={{ margin: '4px 0 0', fontSize: 10, color: C.subtitle, lineHeight: 1.45 }}>
            Annual Recurring Revenue
            {!isDemo && dataSource && (
              <span style={{ marginLeft: 6, color: C.label, opacity: 0.7 }}>
                · {dataSource === 'kpi_active_mrr_arr' ? 'Active MRR/ARR' : 'Partner ARR'}
              </span>
            )}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {/* Period pills */}
          {PERIODS.map(p => {
            const active = period === p.label;
            return (
              <button key={p.label} onClick={() => setPeriod(p.label)} style={{
                fontSize: 10, fontWeight: active ? 700 : 600,
                color: active ? '#3b82f6' : C.label,
                background: active ? C.pillActive : C.pillBg,
                border: `1px solid ${active ? C.pillActiveBorder : 'transparent'}`,
                borderRadius: 999, padding: '4px 10px', cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}>{p.label}</button>
            );
          })}
          {isDemo && (
            <span style={{ fontSize: 9, color: '#f59e0b', background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)', padding: '3px 8px', borderRadius: 999, marginLeft: 2 }}>
              Demo Mode
            </span>
          )}
        </div>
      </div>

      {/* ── Chart ── */}
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={data} margin={{ top: 14, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="arrGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"  stopColor="#3b82f6" stopOpacity={isDark ? 0.28 : 0.18} />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="arrStroke" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="#6366f1" />
              <stop offset="100%" stopColor="#3b82f6" />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: C.tick, fontSize: 10 }}
            tickLine={false} axisLine={false}
            tickFormatter={tickFormatter}
          />
          <YAxis
            tickFormatter={fmtShort}
            tick={{ fill: C.tick, fontSize: 10 }}
            tickLine={false} axisLine={false}
            width={50}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'rgba(59,130,246,0.2)', strokeWidth: 1, strokeDasharray: '4 4' }} />
          {stats && data.length > 1 && (
            <ReferenceLine
              y={stats.start}
              stroke={C.refLine}
              strokeDasharray="5 4"
              label={{ value: `Start: ${fmt(stats.start)}`, position: 'insideTopRight', fill: C.label, fontSize: 9, opacity: 0.7 }}
            />
          )}
          <Area
            type="monotone"
            dataKey="arr"
            stroke="url(#arrStroke)"
            strokeWidth={2.5}
            fill="url(#arrGradient)"
            dot={false}
            activeDot={{ r: 6, fill: '#3b82f6', stroke: isDark ? 'rgba(59,130,246,0.3)' : 'rgba(59,130,246,0.2)', strokeWidth: 8 }}
            name="ARR"
            isAnimationActive={true}
            animationDuration={800}
            animationEasing="ease-out"
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* ── Stats row ── */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginTop: 16 }}>
          {/* Current ARR */}
          <div style={{ background: C.cardBg, border: `1px solid ${C.cardBorder}`, borderRadius: 8, padding: '10px 12px' }}>
            <p style={{ fontSize: 9, color: C.label, textTransform: 'uppercase', letterSpacing: 0.6, margin: '0 0 4px', fontWeight: 600 }}>Current ARR</p>
            <p style={{ margin: 0, fontSize: 17, fontWeight: 800, color: C.value, letterSpacing: -0.5 }}>{fmt(stats.current)}</p>
            <p style={{ margin: '3px 0 0', fontSize: 10, color: stats.netChange >= 0 ? '#10b981' : '#f87171', fontWeight: 600 }}>
              {stats.netChange >= 0 ? '+' : ''}{fmt(stats.netChange)} {period !== 'All' ? `(${period})` : ''}
            </p>
          </div>
          {/* Period growth */}
          <div style={{ background: C.cardBg, border: `1px solid ${C.cardBorder}`, borderRadius: 8, padding: '10px 12px' }}>
            <p style={{ fontSize: 9, color: C.label, textTransform: 'uppercase', letterSpacing: 0.6, margin: '0 0 4px', fontWeight: 600 }}>{period} Growth</p>
            <p style={{ margin: 0, fontSize: 17, fontWeight: 800, color: stats.netPct >= 0 ? '#10b981' : '#f87171', letterSpacing: -0.5 }}>
              {stats.netPct >= 0 ? '+' : ''}{stats.netPct.toFixed(1)}%
            </p>
            <p style={{ margin: '3px 0 0', fontSize: 10, color: C.valueSecondary }}>from {fmt(stats.start)}</p>
          </div>
          {/* Avg monthly growth */}
          <div style={{ background: C.cardBg, border: `1px solid ${C.cardBorder}`, borderRadius: 8, padding: '10px 12px' }}>
            <p style={{ fontSize: 9, color: C.label, textTransform: 'uppercase', letterSpacing: 0.6, margin: '0 0 4px', fontWeight: 600 }}>Avg MoM</p>
            <p style={{ margin: 0, fontSize: 17, fontWeight: 800, color: stats.avgGrowth >= 0 ? '#10b981' : '#f87171', letterSpacing: -0.5 }}>
              {stats.avgGrowth >= 0 ? '+' : ''}{stats.avgGrowth.toFixed(2)}%
            </p>
            <p style={{ margin: '3px 0 0', fontSize: 10, color: C.valueSecondary }}>monthly avg</p>
          </div>
          {/* Period high */}
          <div style={{ background: C.cardBg, border: `1px solid ${C.cardBorder}`, borderRadius: 8, padding: '10px 12px' }}>
            <p style={{ fontSize: 9, color: C.label, textTransform: 'uppercase', letterSpacing: 0.6, margin: '0 0 4px', fontWeight: 600 }}>Period High</p>
            <p style={{ margin: 0, fontSize: 17, fontWeight: 800, color: '#3b82f6', letterSpacing: -0.5 }}>{fmt(stats.peakArr)}</p>
            <p style={{ margin: '3px 0 0', fontSize: 10, color: C.valueSecondary }}>
              {stats.peakArr === stats.current ? 'all-time high ↑' : `${((stats.peakArr - stats.current)/stats.peakArr*100).toFixed(1)}% below peak`}
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

export default ARRTrendChart;

