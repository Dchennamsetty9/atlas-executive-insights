import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import MultiYearChart from '../charts/MultiYearChart';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, Skeleton, YEAR_COLORS, DarkTip, fmtM } from '../common';

const MultiYearTab = ({ loading, historicalView, graphInsights, multiYearView, setMultiYearView, pill }) => {
  const latestYear = Math.max(...(historicalView || []).map((r) => Number(r.year || 0)));
  const priorYear = latestYear - 1;
  const latestWeek = Math.max(...(historicalView || []).filter((r) => Number(r.year) === latestYear).map((r) => Number(r.iso_week || 0)));
  const currVal = (historicalView || []).find((r) => Number(r.year) === latestYear && Number(r.iso_week) === latestWeek)?.arr ?? null;
  const prevVal = (historicalView || []).find((r) => Number(r.year) === priorYear && Number(r.iso_week) === latestWeek)?.arr ?? null;
  const delta = currVal != null && prevVal != null ? Number(currVal) - Number(prevVal) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {[{ key: 'overlay', label: 'Year Overlay (ISO Week)' }, { key: 'timeline', label: 'Timeline View' }].map((v) => <button key={v.key} onClick={() => setMultiYearView(v.key)} style={pill(multiYearView === v.key, '#3b82f6')}>{v.label}</button>)}
        <span style={{ fontSize: 10, color: '#475569', marginLeft: 8 }}>{[...new Set((historicalView || []).map((r) => r.year))].sort().join(', ')} · {historicalView?.length ?? 0} pts</span>
        {delta != null && (
          <span style={{ marginLeft: 'auto', fontSize: 11, color: delta >= 0 ? '#10b981' : '#ef4444', fontWeight: 700 }}>
            Week {latestWeek}: {delta >= 0 ? '+' : '−'}{fmtM(Math.abs(delta))} vs {priorYear}
          </span>
        )}
      </div>

      {multiYearView === 'overlay' && (
        <CardWrap downloadName="historical_seasonality">
          <SectionTitle>Historical Seasonality — by ISO Week (1–52)</SectionTitle>
          <GraphInsight summary={graphInsights.seasonality} chartType="seasonality_overlay" metricName="Weekly Growth ARR by ISO week across years" dataPoints={historicalView} />
          <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {[...new Set((historicalView || []).map((r) => r.year))].sort().map((yr) => <span key={yr}><span style={{ color: YEAR_COLORS[yr] ?? '#94a3b8' }}>─</span> {yr}</span>)}
          </div>
          {loading ? <Skeleton height={260} /> : historicalView && historicalView.length > 0 ? <MultiYearChart rows={historicalView} currentYear={latestYear} /> : <EmptyState />}
        </CardWrap>
      )}

      {multiYearView === 'timeline' && (
        <CardWrap downloadName="historical_trend_timeline">
          <SectionTitle>Historical Weekly Trend — Timeline</SectionTitle>
          <GraphInsight summary={graphInsights.trend} />
          {loading ? <Skeleton height={260} /> : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={historicalView || []} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="date" tickFormatter={(d) => d?.slice(0, 7)} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} interval={12} />
                <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} width={58} />
                <Tooltip content={<DarkTip />} />
                <Line type="monotone" dataKey="arr" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Weekly ARR" isAnimationActive />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardWrap>
      )}
    </div>
  );
};

export default MultiYearTab;
