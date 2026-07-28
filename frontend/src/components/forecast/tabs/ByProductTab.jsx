import GeoBarChart from '../charts/GeoBarChart';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, Skeleton, fmtM, mapeColor } from '../common';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const ByProductTab = ({ loading, byProductView, graphInsights, runDate }) => {
  const products = byProductView?.by_product || [];
  const ranked = [...products]
    .map((p) => {
      const likely = Number(p.arr_likely || 0);
      const actual = Number(p.arr_actual || 0);
      const gapPct = likely > 0 ? ((actual - likely) / likely) * 100 : null;
      return { ...p, gapPct };
    })
    .sort((a, b) => {
      const av = a.gapPct == null ? -Infinity : a.gapPct;
      const bv = b.gapPct == null ? -Infinity : b.gapPct;
      return bv - av;
    });

  const railColor = (gapPct) => {
    if (gapPct == null) return '#64748b';
    if (gapPct >= 0) return '#10b981';
    if (gapPct >= -8) return '#f59e0b';
    return '#ef4444';
  };

  const miniData = (p) => ([
    { step: 'Risk', value: Number(p.arr_worst || 0) },
    { step: 'Likely', value: Number(p.arr_likely || 0) },
    { step: 'Stretch', value: Number(p.arr_best || 0) },
  ]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <CardWrap downloadName="forecast_by_product">
        <SectionTitle>Product Trajectories (Small Multiples) {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
        <GraphInsight summary={graphInsights.byProduct} chartType="by_product_forecast" metricName="Forecast Growth ARR by product line and geo" dataPoints={byProductView?.by_product} />
        {loading ? <Skeleton height={200} /> : !byProductView ? <EmptyState /> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
            {products.map((p) => (
              <div key={`${p.product}-${p.product_line || ''}`} style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: 10, background: 'rgba(255,255,255,0.02)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 11, color: '#e2e8f0', fontWeight: 700 }}>{p.product_line || p.product}</span>
                  <span style={{ fontSize: 10, color: '#94a3b8' }}>Likely {fmtM(p.arr_likely)}</span>
                </div>
                <ResponsiveContainer width="100%" height={90}>
                  <LineChart data={miniData(p)} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
                    <XAxis dataKey="step" hide />
                    <YAxis hide />
                    <Tooltip formatter={(v) => fmtM(v)} />
                    <Line type="monotone" dataKey="value" stroke="#93c5fd" strokeWidth={2} dot={{ r: 2 }} isAnimationActive animationDuration={300} animationEasing="ease-out" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        )}
      </CardWrap>

      {!loading && byProductView?.by_product && (
        <CardWrap>
          <SectionTitle>Attainment Gap Ranking {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                {['Rank', 'Product', 'Line', 'Worst', 'Most Likely', 'Best', 'Gap vs Likely', 'Best MAPE'].map((h) => (
                  <th key={h} style={{ padding: '6px 12px', textAlign: ['Product', 'Line'].includes(h) ? 'left' : 'right', fontSize: 10, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ranked.map((p, i) => (
                <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', background: i % 2 === 0 ? 'rgba(255,255,255,0.01)' : 'transparent' }}>
                  <td style={{ padding: '6px 12px', textAlign: 'right', color: '#93c5fd', fontWeight: 700 }}>{i + 1}</td>
                  <td style={{ padding: '6px 12px', color: '#f1f5f9' }}>{p.product}</td>
                  <td style={{ padding: '6px 12px', color: p.product_line === 'UCC' ? '#3b82f6' : '#10b981', fontWeight: 600 }}>{p.product_line}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', color: '#ef4444' }}>{fmtM(p.arr_worst)}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', color: '#f1f5f9', fontWeight: 700 }}>{fmtM(p.arr_likely)}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', color: '#10b981' }}>{fmtM(p.arr_best)}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right' }}>
                    <span style={{ color: railColor(p.gapPct), fontWeight: 700 }}>
                      {p.gapPct == null ? '—' : `${p.gapPct >= 0 ? '+' : ''}${p.gapPct.toFixed(1)}%`}
                    </span>
                    <div style={{ marginTop: 3, height: 4, width: 90, marginLeft: 'auto', background: 'rgba(255,255,255,0.08)', borderRadius: 999 }}>
                      <div style={{ height: '100%', width: `${Math.min(100, Math.max(8, Math.abs(p.gapPct || 0) * 4))}%`, background: railColor(p.gapPct), borderRadius: 999 }} />
                    </div>
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', color: p.best_mape && p.best_mape < 999 ? mapeColor(p.best_mape) : '#334155', fontWeight: 600 }}>{p.best_mape && p.best_mape < 999 ? `${p.best_mape.toFixed(1)}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardWrap>
      )}

      {!loading && byProductView?.by_geo?.length > 0 && (
        <CardWrap downloadName="forecast_by_geography">
          <SectionTitle>Forecast by Geography {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
          <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span><span style={{ color: '#ef4444' }}>■</span> Risk Floor</span>
            <span><span style={{ color: '#ffffff' }}>■</span> Most Likely</span>
            <span><span style={{ color: '#10b981' }}>■</span> Stretch Case</span>
          </div>
          <GeoBarChart rows={byProductView.by_geo} />
        </CardWrap>
      )}
    </div>
  );
};

export default ByProductTab;
