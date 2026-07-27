import BacktestSection from '../BacktestSection';
import AccuracyTable from '../charts/AccuracyTable';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, Skeleton } from '../common';

const AccuracyTab = ({ loading, leaderboardView, graphInsights, model, prodLine, salesMarket }) => {
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {rank.length > 0 && (
        <CardWrap>
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
      <CardWrap>
        <SectionTitle>Model MAPE Leaderboard — 8-Week Holdout Validation</SectionTitle>
        <GraphInsight summary={graphInsights.accuracy} chartType="model_accuracy_leaderboard" metricName="Model MAPE by product and geo slice" dataPoints={leaderboardView} />
        {loading ? <Skeleton height={240} /> : leaderboardView && leaderboardView.length > 0 ? <AccuracyTable data={leaderboardView} /> : <EmptyState />}
      </CardWrap>
      <BacktestSection model={model} prodLine={prodLine} salesMarket={salesMarket} />
    </div>
  );
};

export default AccuracyTab;
