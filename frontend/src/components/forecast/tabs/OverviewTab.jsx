import { CardWrap, EmptyState, GraphInsight, SectionTitle, Skeleton, fmtDate, fmtM } from '../common';
import WeeklyChart from '../charts/WeeklyChart';
import RunningTotalsChart from '../charts/RunningTotalsChart';

const OverviewTab = ({
  loading,
  weeklyView,
  ytdView,
  weeklyKpis,
  selectedYear,
  selectedQuarter,
  runDelta,
  trust,
  isDemo,
  graphInsights,
}) => {
  const todayIso = new Date().toISOString().slice(0, 10);
  const qtdRows = (weeklyView || []).filter((r) => r.date <= todayIso);
  const qtdActual = qtdRows.reduce((sum, r) => sum + Number(r.arr_actual || 0), 0);
  const qtdPacedTarget = qtdRows.reduce((sum, r) => sum + Number(r.arr_likely || 0), 0);
  const qtdDelta = qtdActual - qtdPacedTarget;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {loading ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} height={72} />)}</div> : weeklyView && weeklyView.length > 0 && (() => {
        const kp = weeklyKpis;
        const ml = kp?.most_likely ?? 0;
        const bc = kp?.best_case ?? 0;
        const wc = kp?.worst_case ?? 0;
        const ytdActual = kp?.ytd_actuals ?? [...(ytdView || [])].reverse().find((r) => r.ytd_actual != null)?.ytd_actual ?? 0;
        const periodShort = selectedQuarter ? `Q${selectedQuarter} ${selectedYear}` : `FY ${selectedYear}`;
        const isClosed = ml > 0 && ml === bc && ml === wc;

        if (isClosed) {
          return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}><div style={{ gridColumn: '1 / 3', background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.25)', borderRadius: 10, padding: '12px 14px' }}><div style={{ fontSize: 9, color: '#10b981', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Closed Quarter — Actuals</div><div style={{ fontSize: 22, fontWeight: 800, color: '#10b981', letterSpacing: -0.5, lineHeight: 1 }}>{fmtM(ml)}</div><div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>Q{selectedQuarter ?? ''} {selectedYear} final — scenario bands equal actuals</div></div><div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '12px 14px' }}><div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Actuals YTD</div><div style={{ fontSize: 22, fontWeight: 800, color: '#f59e0b', letterSpacing: -0.5, lineHeight: 1 }}>{fmtM(ytdActual)}</div><div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>Realized YTD</div></div><div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: 10, padding: '12px 14px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}><div style={{ fontSize: 10, color: '#475569', lineHeight: 1.5 }}>Forecast range not available — all {selectedQuarter ? `Q${selectedQuarter}` : 'selected'} weeks are closed actuals. Select a future quarter or <b style={{ color: '#f59e0b' }}>Rest of Year</b> to see scenario bands.</div></div></div>;
        }

        return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>{[
          { label: 'Most Likely', val: ml, color: '#f1f5f9', sub: `${periodShort} outlook — planning center` },
          { label: 'Stretch Case', val: bc, color: '#10b981', sub: `${periodShort} · 1-in-5 upside (P90)` },
          { label: 'Risk Floor', val: wc, color: '#ef4444', sub: `${periodShort} · 1-in-10 downside (P10)` },
          { label: 'Actuals YTD', val: ytdActual, color: '#f59e0b', sub: `Realized so far in ${selectedYear}` },
        ].map(({ label, val, color, sub }) => <div key={label} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '12px 14px' }}><div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div><div style={{ fontSize: 22, fontWeight: 800, color, letterSpacing: -0.5, lineHeight: 1 }}>{fmtM(val)}</div><div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>{sub}</div></div>)}</div>;
      })()}

      {runDelta?.available && runDelta?.total && (() => {
        const d = runDelta.total.delta ?? 0;
        const pct = runDelta.total.delta_pct;
        const isFlat = pct != null && Math.abs(pct) < 0.1;
        const dirColor = isFlat ? '#94a3b8' : d >= 0 ? '#10b981' : '#ef4444';
        const arrow = isFlat ? '→' : d >= 0 ? '▲' : '▼';
        return <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', padding: '10px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}><div><div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Since last forecast run{runDelta.previous_run && runDelta.latest_run && ` · ${fmtDate(runDelta.previous_run)} → ${fmtDate(runDelta.latest_run)}`}</div><div style={{ fontSize: 16, fontWeight: 800, color: dirColor }}>{arrow} {isFlat ? 'Essentially unchanged' : `${d >= 0 ? '+' : '−'}${fmtM(Math.abs(d))}`}{pct != null && !isFlat && <span style={{ fontSize: 11, fontWeight: 600, marginLeft: 6, opacity: 0.8 }}>({pct > 0 ? '+' : ''}{pct}%)</span>}</div><div style={{ fontSize: 9, color: '#334155', marginTop: 2 }}>Ensemble Most Likely · {runDelta.overlap_weeks} overlapping forecast week(s){runDelta.source === 'demo' && ' · demo'}</div></div>{(runDelta.drivers || []).length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginLeft: 'auto', alignItems: 'center' }}><span style={{ fontSize: 9, color: '#475569' }}>Biggest moves:</span>{runDelta.drivers.map((dr, i) => <span key={i} style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 14, color: dr.delta >= 0 ? '#10b981' : '#ef4444', background: dr.delta >= 0 ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)', border: `1px solid ${dr.delta >= 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)'}` }}>{dr.product}{dr.sales_market !== 'Total' ? `/${dr.sales_market}` : ''} {dr.delta >= 0 ? '+' : '−'}{fmtM(Math.abs(dr.delta))}</span>)}</div>}</div>;
      })()}

      <CardWrap downloadName="weekly_forecast_vs_actuals">
        {weeklyKpis && (
          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr', gap: 10, marginBottom: 12 }}>
            <div style={{ background: 'linear-gradient(135deg, rgba(59,130,246,0.18), rgba(59,130,246,0.04))', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 9, color: '#93c5fd', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>Quarter Hero Number</div>
              <div style={{ fontSize: 26, fontWeight: 900, lineHeight: 1, color: '#dbeafe' }}>{fmtM(weeklyKpis.most_likely)}</div>
              <div style={{ fontSize: 11, color: '#93c5fd', marginTop: 4 }}>Most Likely close for {selectedQuarter ? `Q${selectedQuarter}` : `FY ${selectedYear}`}</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 9, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>Planning Envelope</div>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#e2e8f0' }}>{fmtM(weeklyKpis.worst_case)} → {fmtM(weeklyKpis.best_case)}</div>
              <div style={{ fontSize: 10, marginTop: 4, color: '#64748b' }}>Risk floor to stretch case</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 9, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>QTD vs Paced Target</div>
              <div style={{ fontSize: 16, fontWeight: 800, color: qtdDelta >= 0 ? '#10b981' : '#ef4444' }}>{qtdDelta >= 0 ? '+' : '−'}{fmtM(Math.abs(qtdDelta))}</div>
              <div style={{ fontSize: 10, marginTop: 4, color: '#64748b' }}>{fmtM(qtdActual)} actual vs {fmtM(qtdPacedTarget)} paced</div>
            </div>
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <SectionTitle>Weekly Forecast vs Actuals</SectionTitle>
          {(() => {
            const cov = trust?.summary?.coverage_pct;
            const n = trust?.summary?.weeks_scored;
            if (cov == null || !n) return null;
            const covColor = cov >= 70 && cov <= 92 ? '#10b981' : cov >= 50 ? '#f59e0b' : '#ef4444';
            return <span title={`Over the last ${n} closed weeks, the actual landed inside the 80% band ${cov}% of the time (forecasts made 4 weeks ahead). Calibrated bands should be near ~80% — much higher means the bands are too wide, much lower means too narrow.`} style={{ fontSize: 10, fontWeight: 700, padding: '3px 10px', borderRadius: 20, marginBottom: 10, color: covColor, background: `${covColor}14`, border: `1px solid ${covColor}40`, cursor: 'help', display: 'inline-flex', alignItems: 'center', gap: 5 }}>🛡 Bands caught {cov}% of last {n} actuals<span style={{ fontWeight: 400, opacity: 0.75 }}>· target ~80%</span>{trust?.source === 'demo' && <span style={{ fontWeight: 400, opacity: 0.6 }}>· demo</span>}</span>;
          })()}
        </div>
        <GraphInsight summary={graphInsights.weekly} chartType="weekly_forecast" metricName="Weekly Growth ARR — actuals vs forecast scenarios" dataPoints={weeklyView} />
        <div style={{ fontSize: 10, color: '#475569', marginBottom: 10, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <span><span style={{ color: '#f59e0b' }}>─</span> Actuals</span>
          <span><span style={{ color: '#ef4444' }}>- -</span> Risk Floor (1-in-10 downside)</span>
          <span><span style={{ color: '#ffffff' }}>─</span> Most Likely</span>
          <span><span style={{ color: '#10b981' }}>- -</span> Stretch Case (1-in-5 upside)</span>
          <span style={{ color: '#22d3ee' }}>▒ 50% band (approx.)</span>
          <span style={{ color: '#3b82f6' }}>▒ 80% band (model P10–P90)</span>
        </div>
        {loading ? <Skeleton height={260} /> : weeklyView && weeklyView.length > 0 ? <WeeklyChart rows={weeklyView} /> : <EmptyState />}
      </CardWrap>

      <CardWrap downloadName="ytd_cumulative">
        <SectionTitle>Running Totals — YTD Cumulative</SectionTitle>
        <GraphInsight summary={graphInsights.ytd} chartType="ytd_cumulative" metricName="YTD cumulative Growth ARR — actual vs forecast path" dataPoints={ytdView} />
        {loading ? <Skeleton height={200} /> : ytdView && ytdView.length > 0 ? <RunningTotalsChart rows={ytdView} /> : <EmptyState />}
      </CardWrap>
    </div>
  );
};

export default OverviewTab;
