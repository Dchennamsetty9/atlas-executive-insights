import BacktestSection from '../BacktestSection';
import AccuracyTable from '../charts/AccuracyTable';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, TableSkeleton, mapeColor } from '../common';
import { useState } from 'react';

const AccuracyTab = ({ loading, leaderboardView, graphInsights, model, prodLine, salesMarket, runDate }) => {
  const [compareModel1, setCompareModel1] = useState('Ensemble');
  const [compareModel2, setCompareModel2] = useState('Prophet');
  
  const totalRow = (leaderboardView || []).find((r) => (r.product === 'Total' || r.product === 'All') && (r.sales_market === 'Total' || r.sales_market === 'All'));
  const rank = totalRow ? [
    { key: 'Ensemble', label: 'Ensemble', value: Number(totalRow.Ensemble) },
    { key: 'ETS', label: 'ETS', value: Number(totalRow.ETS) },
    { key: 'Prophet', label: 'Prophet', value: Number(totalRow.Prophet) },
    { key: 'LightGBM', label: 'LightGBM', value: Number(totalRow.LightGBM) },
    { key: 'MSTL_v2', label: 'MSTL v2', value: Number(totalRow.MSTL_v2) },
    { key: 'DHR_ARIMA', label: 'DHR-ARIMA', value: Number(totalRow.DHR_ARIMA) },
  ].filter((m) => Number.isFinite(m.value) && m.value < 999).sort((a, b) => a.value - b.value) : [];
  const best = rank[0];
  const worst = rank[rank.length - 1];

  const modelOptions = ['Ensemble', 'ETS', 'Prophet', 'LightGBM', 'MSTL_v2', 'DHR_ARIMA'];
  const comparisonData = (leaderboardView || []).filter(
    (r) => r.product !== 'Total' && r.product !== 'All' && r.sales_market !== 'Total' && r.sales_market !== 'All'
  );
  
  const compareRows = comparisonData.map((row) => ({
    product: row.product,
    geo: row.sales_market,
    m1_mape: Number(row[compareModel1]) || null,
    m2_mape: Number(row[compareModel2]) || null,
    m1_color: compareModel1,
    m2_color: compareModel2,
  })).filter((r) => r.m1_mape !== null && r.m2_mape !== null).sort((a, b) => {
    const diff_a = Math.abs(a.m1_mape - a.m2_mape);
    const diff_b = Math.abs(b.m1_mape - b.m2_mape);
    return diff_b - diff_a;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {rank.length > 0 && (
        <CardWrap downloadName="model_rank_by_mape">
          <SectionTitle>Model Rank by MAPE (Lower Is Better)</SectionTitle>
          <div style={{ display: 'grid', gap: 8 }}>
            {rank.map((m, idx) => {
              const width = worst?.value ? Math.max(12, ((worst.value - m.value) / Math.max(0.1, worst.value)) * 100) : 30;
              return (
                <div key={m.key} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 80px', gap: 10, alignItems: 'center' }}>
                  <div style={{ fontSize: 11, color: idx === 0 ? '#10b981' : '#cbd5e1', fontWeight: idx === 0 ? 800 : 600 }}>{idx + 1}. {m.label}</div>
                  <div style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${width}%`, background: idx === 0 ? '#10b981' : '#3b82f6', borderRadius: 999 }} />
                  </div>
                  <div style={{ textAlign: 'right', fontSize: 11, color: mapeColor(m.value), fontWeight: 700 }}>{m.value.toFixed(1)}%</div>
                </div>
              );
            })}
          </div>
          {best && <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8' }}>Best model this quarter is <span style={{ color: '#10b981', fontWeight: 700 }}>{best.label}</span> at {best.value.toFixed(1)}% MAPE; trust this model most for call-setting when scenario bands diverge.</div>}
        </CardWrap>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {[{ label: '< 15%', color: '#10b981' }, { label: '15–25%', color: '#f59e0b' }, { label: '> 25%', color: '#ef4444' }].map((b) => (
          <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#64748b' }}><div style={{ width: 10, height: 10, borderRadius: 2, background: b.color }} /> MAPE {b.label}</div>
        ))}
      </div>
      <CardWrap downloadName="model_comparison_tool">
        <SectionTitle>Model Comparison Tool</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '200px 200px 1fr', gap: 12, marginBottom: 12, alignItems: 'end' }}>
          <div>
            <label style={{ fontSize: 10, color: '#94a3b8', display: 'block', marginBottom: 4 }}>Model 1</label>
            <select value={compareModel1} onChange={(e) => setCompareModel1(e.target.value)} style={{ width: '100%', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }}>
              {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 10, color: '#94a3b8', display: 'block', marginBottom: 4 }}>Model 2</label>
            <select value={compareModel2} onChange={(e) => setCompareModel2(e.target.value)} style={{ width: '100%', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }}>
              {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div style={{ fontSize: 10, color: '#64748b' }}>Sorted by largest accuracy gap</div>
        </div>
        {compareRows.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: '#64748b' }}>Product</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: '#64748b' }}>Geography</th>
                  <th style={{ padding: '6px 10px', textAlign: 'right', color: '#64748b' }}>{compareModel1}</th>
                  <th style={{ padding: '6px 10px', textAlign: 'right', color: '#64748b' }}>{compareModel2}</th>
                  <th style={{ padding: '6px 10px', textAlign: 'right', color: '#64748b' }}>Gap</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: '#64748b' }}>Winner</th>
                </tr>
              </thead>
              <tbody>
                {compareRows.slice(0, 15).map((row, i) => {
                  const gap = Math.abs(row.m1_mape - row.m2_mape);
                  const winner = row.m1_mape < row.m2_mape ? compareModel1 : row.m2_mape < row.m1_mape ? compareModel2 : 'Tied';
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ padding: '6px 10px', color: '#e2e8f0' }}>{row.product}</td>
                      <td style={{ padding: '6px 10px', color: '#94a3b8' }}>{row.geo}</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: mapeColor(row.m1_mape), fontWeight: 700 }}>{row.m1_mape.toFixed(1)}%</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: mapeColor(row.m2_mape), fontWeight: 700 }}>{row.m2_mape.toFixed(1)}%</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: '#64748b' }}>{gap.toFixed(1)}%</td>
                      <td style={{ padding: '6px 10px', color: winner === 'Tied' ? '#94a3b8' : '#10b981', fontWeight: 700 }}>{winner === 'Tied' ? '—' : winner}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState />
        )}
      </CardWrap>
      <CardWrap>
        <SectionTitle>Model MAPE Leaderboard — 8-Week Holdout Validation {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
        <GraphInsight summary={graphInsights.accuracy} chartType="model_accuracy_leaderboard" metricName="Model MAPE by product and geo slice" dataPoints={leaderboardView} />
        {loading ? <TableSkeleton rowCount={8} columnCount={5} /> : leaderboardView && leaderboardView.length > 0 ? <AccuracyTable data={leaderboardView} /> : <EmptyState />}
      </CardWrap>
      <BacktestSection model={model} prodLine={prodLine} salesMarket={salesMarket} />
    </div>
  );
};

export default AccuracyTab;
