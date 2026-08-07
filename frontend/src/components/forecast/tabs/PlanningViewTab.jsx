import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { CardWrap, EmptyState, SectionTitle, Skeleton, fmtM } from '../common';

const pill = (active, color) => ({
  padding: '4px 11px',
  borderRadius: 999,
  fontSize: 10,
  fontWeight: 700,
  cursor: 'pointer',
  border: `1px solid ${active ? color : 'rgba(255,255,255,0.08)'}`,
  background: active ? `${color}1a` : 'rgba(255,255,255,0.03)',
  color: active ? color : '#64748b',
});

const PlanningViewTab = ({ loading, monthlyView, byProductView, runDate }) => {
  const [productMode, setProductMode] = useState('all');

  const shares = useMemo(() => {
    const lines = byProductView?.by_product_line || byProductView?.by_product || [];
    const ucc = Number((lines.find((r) => (r.product_line || r.product) === 'UCC')?.arr_likely) || 0);
    const itsg = Number((lines.find((r) => (r.product_line || r.product) === 'ITSG')?.arr_likely) || 0);
    const total = ucc + itsg;
    if (!total) return { ucc: 0.5, itsg: 0.5 };
    return { ucc: ucc / total, itsg: itsg / total };
  }, [byProductView]);

  const quarterRows = useMemo(() => {
    const grouped = {};
    for (const m of monthlyView || []) {
      const key = `${m.year}-Q${m.quarter}`;
      if (!grouped[key]) {
        grouped[key] = {
          quarter: key,
          year: m.year,
          q: m.quarter,
          actual: 0,
          likely: 0,
          worst: 0,
          best: 0,
        };
      }
      grouped[key].actual += Number(m.arr_actual || 0);
      grouped[key].likely += Number(m.arr_likely || 0);
      grouped[key].worst += Number(m.arr_worst || 0);
      grouped[key].best += Number(m.arr_best || 0);
    }

    const rows = Object.values(grouped)
      .sort((a, b) => (a.year - b.year) || (a.q - b.q))
      .map((r) => {
        const boq = r.actual > 0 ? (r.actual / Math.max(r.likely, 1)) * 100 : 0;
        const pace = boq >= 95 ? 'On Pace' : boq >= 85 ? 'Watch' : 'At Risk';
        const mult = productMode === 'ucc' ? shares.ucc : productMode === 'itsg' ? shares.itsg : 1;
        return {
          ...r,
          actual: r.actual * mult,
          likely: r.likely * mult,
          worst: r.worst * mult,
          best: r.best * mult,
          boq,
          pace,
        };
      });

    return rows;
  }, [monthlyView, productMode, shares]);

  if (loading) return <Skeleton height={280} />;
  if (!quarterRows.length) return <EmptyState message="No planning rows for this selection" />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: 11, color: '#94a3b8' }}>
          Planning view consolidates monthly combined forecast into quarterly execution signals.
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => setProductMode('all')} style={pill(productMode === 'all', '#3b82f6')}>All</button>
          <button onClick={() => setProductMode('ucc')} style={pill(productMode === 'ucc', '#10b981')}>UCC</button>
          <button onClick={() => setProductMode('itsg')} style={pill(productMode === 'itsg', '#f59e0b')}>ITSG</button>
        </div>
      </div>

      <CardWrap downloadName="planning_quarterly_outlook">
        <SectionTitle>
          Quarterly Plan vs Actual {runDate && <span style={{ color: '#94a3b8', fontWeight: 400 }}>- as of {runDate}</span>}
        </SectionTitle>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={quarterRows} margin={{ top: 8, right: 18, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
            <XAxis dataKey="quarter" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} width={82} />
            <Tooltip formatter={(v) => fmtM(v)} />
            <Bar dataKey="actual" stackId="q" name="Actual" fill="#f59e0b" radius={[3, 3, 0, 0]} />
            <Bar dataKey="likely" stackId="q2" name="Likely" fill="#3b82f6" radius={[3, 3, 0, 0]} />
            <Line type="monotone" dataKey="best" name="BOQ Overlay" stroke="#10b981" strokeWidth={2.2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </CardWrap>

      <CardWrap>
        <SectionTitle>Pace Badges</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
          {quarterRows.map((r) => (
            <div key={r.quarter} style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: 10, background: 'rgba(255,255,255,0.02)' }}>
              <div style={{ fontSize: 11, color: '#cbd5e1', fontWeight: 700 }}>{r.quarter}</div>
              <div style={{ marginTop: 6, fontSize: 10, color: '#94a3b8' }}>BOQ: {r.boq.toFixed(1)}%</div>
              <div style={{ marginTop: 6, fontSize: 11, fontWeight: 700, color: r.pace === 'On Pace' ? '#10b981' : r.pace === 'Watch' ? '#f59e0b' : '#ef4444' }}>
                {r.pace}
              </div>
            </div>
          ))}
        </div>
      </CardWrap>
    </div>
  );
};

export default PlanningViewTab;
