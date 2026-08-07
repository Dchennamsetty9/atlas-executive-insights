import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import MultiYearChart from '../charts/MultiYearChart';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, Skeleton, YEAR_COLORS, DarkTip, fmtM } from '../common';

const MultiYearTab = ({ loading, historicalView, graphInsights, multiYearView, setMultiYearView, pill, runDate }) => {
  const latestYear = Math.max(...(historicalView || []).map((r) => Number(r.year || 0)));
  const priorYear = latestYear - 1;
  const latestWeek = Math.max(...(historicalView || []).filter((r) => Number(r.year) === latestYear).map((r) => Number(r.iso_week || 0)));
  const currVal = (historicalView || []).find((r) => Number(r.year) === latestYear && Number(r.iso_week) === latestWeek)?.arr ?? null;
  const prevVal = (historicalView || []).find((r) => Number(r.year) === priorYear && Number(r.iso_week) === latestWeek)?.arr ?? null;
  const delta = currVal != null && prevVal != null ? Number(currVal) - Number(prevVal) : null;
  const latestYearRows = (historicalView || []).filter((r) => Number(r.year) === latestYear);
  const peakWeek = latestYearRows.reduce((best, row) => (Number(row.arr || 0) > Number(best?.arr || 0) ? row : best), null);
  const years = [...new Set((historicalView || []).map((r) => Number(r.year || 0)))].filter((y) => y > 0).sort();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {[{ key: 'overlay', label: 'Seasonality Overlay' }, { key: 'timeline', label: 'Trend Timeline' }].map((v) => <button key={v.key} onClick={() => setMultiYearView(v.key)} style={pill(multiYearView === v.key, '#3b82f6')}>{v.label}</button>)}
        <span style={{ fontSize: 10, color: '#64748b', marginLeft: 8 }}>{years.join(', ')} · {historicalView?.length ?? 0} points</span>
        {delta != null && (
          <span style={{ marginLeft: 'auto', fontSize: 12, color: delta >= 0 ? '#10b981' : '#ef4444', fontWeight: 800 }}>
            Week {latestWeek}: {delta >= 0 ? '+' : '−'}{fmtM(Math.abs(delta))} vs {priorYear}
          </span>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(180px, 1fr))', gap: 10 }}>
        <div style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.24)', borderRadius: 10, padding: '10px 12px' }}>
          <div style={{ fontSize: 9, color: '#93c5fd', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>Current Year</div>
          <div style={{ fontSize: 13, fontWeight: 800, color: '#e2e8f0' }}>{latestYear}</div>
          <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>Primary comparison baseline</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '10px 12px' }}>
          <div style={{ fontSize: 9, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>YoY Pulse</div>
          <div style={{ fontSize: 13, fontWeight: 800, color: delta == null ? '#94a3b8' : delta >= 0 ? '#10b981' : '#ef4444' }}>
            {delta == null ? '—' : `${delta >= 0 ? '+' : '−'}${fmtM(Math.abs(delta))}`}
          </div>
          <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>Latest week vs prior year</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '10px 12px' }}>
          <div style={{ fontSize: 9, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>Peak Week ({latestYear})</div>
          <div style={{ fontSize: 13, fontWeight: 800, color: '#f1f5f9' }}>
            {peakWeek ? `W${peakWeek.iso_week} · ${fmtM(peakWeek.arr)}` : '—'}
          </div>
          <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>Highest seasonal point</div>
        </div>
      </div>

      {multiYearView === 'overlay' && (
        <CardWrap downloadName="historical_seasonality">
          <SectionTitle>Historical Seasonality — by ISO Week (1–52) {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
          <GraphInsight summary={graphInsights.seasonality} chartType="seasonality_overlay" metricName="Weekly Growth ARR by ISO week across years" dataPoints={historicalView} />
          <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {years.slice(-3).map((yr) => <span key={yr}><span style={{ color: YEAR_COLORS[yr] ?? '#94a3b8' }}>─</span> {yr}</span>)}
            <span style={{ color: '#64748b' }}>Showing latest 3 years for executive clarity</span>
          </div>
          {loading ? <Skeleton height={260} /> : historicalView && historicalView.length > 0 ? <MultiYearChart rows={historicalView} currentYear={latestYear} /> : <EmptyState />}
        </CardWrap>
      )}

      {multiYearView === 'timeline' && (
        <CardWrap downloadName="historical_trend_timeline">
          <SectionTitle>Historical Weekly Trend — Timeline {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
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
