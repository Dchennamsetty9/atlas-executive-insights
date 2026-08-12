import { useEffect, useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { apiService } from '../../services/api';
import { CardWrap, DarkTip, EmptyState, SectionTitle, Skeleton, fmtDate, fmtM, mapeColor } from './common';

const HORIZONS = [1, 4, 8, 13];

const BacktestSection = ({ model, prodLine, salesMarket }) => {
  const [horizon, setHorizon] = useState(4);
  const [data, setData] = useState(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setBtLoading(true);
      setBtError(null);
      try {
        const res = await apiService.getForecastV2Backtest(
          horizon,
          model,
          prodLine !== 'All' ? prodLine : null,
          salesMarket && salesMarket !== 'All' ? salesMarket : null,
        );
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setBtError(e.message || 'Failed to load backtest');
      } finally {
        if (!cancelled) setBtLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [horizon, model, prodLine, salesMarket]);

  const rows = (data?.rows || []).map((r) => ({ ...r, bandFloor: r.worst, bandRange: r.best != null && r.worst != null ? Math.max(0, r.best - r.worst) : null }));
  const s = data?.summary || {};
  const isLive = data?.source === 'live';
  const covColor = s.coverage_pct == null ? '#64748b' : s.coverage_pct >= 70 ? '#10b981' : s.coverage_pct >= 50 ? '#f59e0b' : '#ef4444';
  const biasStr = s.bias_pct == null ? '—' : `${s.bias_pct > 0 ? '+' : ''}${s.bias_pct}% ${s.bias_pct > 0 ? '(over-forecast)' : s.bias_pct < 0 ? '(under-forecast)' : ''}`;

  const chip = (label, value, color) => (
    <div style={{ padding: '10px 14px', borderRadius: 10, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', minWidth: 120 }}>
      <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
    </div>
  );

  return (
    <CardWrap downloadName="forecast_vs_reality">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <SectionTitle>Forecast vs Reality — What We Predicted, What Happened</SectionTitle>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 20, color: isLive ? '#10b981' : '#f59e0b', background: isLive ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.08)', border: `1px solid ${isLive ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.2)'}` }}>{isLive ? 'LIVE' : 'DEMO'}</span>
      </div>
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 12, lineHeight: 1.5 }}>Each point compares the forecast made <b style={{ color: '#94a3b8' }}>{horizon} week{horizon > 1 ? 's' : ''} in advance</b> against the actual that later closed. Band coverage should approach ~80% if the P10–P90 intervals are calibrated.</div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: '#475569', marginRight: 4 }}>Forecast horizon:</span>
        {HORIZONS.map((h) => <button key={h} onClick={() => setHorizon(h)} style={{ padding: '4px 11px', borderRadius: 999, fontSize: 10, fontWeight: 700, cursor: 'pointer', border: `1px solid ${horizon === h ? '#3b82f6' : 'rgba(255,255,255,0.08)'}`, background: horizon === h ? 'rgba(59,130,246,0.12)' : 'rgba(255,255,255,0.03)', color: horizon === h ? '#93c5fd' : '#475569' }}>{h} wk ahead</button>)}
      </div>

      {btError && <div style={{ padding: '14px', borderRadius: 8, color: '#ef4444', background: 'rgba(239,68,68,0.06)', fontSize: 12 }}>⚠ {btError}</div>}
      {btLoading ? <Skeleton height={260} /> : rows.length === 0 && !btError ? <EmptyState message="No closed weeks with retained forecasts at this horizon yet" /> : rows.length > 0 && (
        <>
          <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            {chip('Weeks scored', s.weeks_scored ?? '—', '#f1f5f9')}
            {chip('Band coverage (target ~80%)', s.coverage_pct != null ? `${s.coverage_pct}%` : '—', covColor)}
            {chip(`MAPE @ ${horizon}wk`, s.mape_pct != null ? `${s.mape_pct}%` : '—', s.mape_pct != null ? mapeColor(s.mape_pct) : '#64748b')}
            {chip('Bias', biasStr, s.bias_pct == null ? '#64748b' : Math.abs(s.bias_pct) < 5 ? '#10b981' : '#f59e0b')}
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginBottom: 8, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span><span style={{ color: '#f59e0b' }}>─</span> Actual (closed)</span>
            <span><span style={{ color: '#e2e8f0' }}>- -</span> Predicted {horizon}wk prior</span>
            <span style={{ color: '#3b82f6' }}>▒ Predicted 80% band</span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={rows} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
              <defs><linearGradient id="btBandFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3b82f6" stopOpacity={0.2} /><stop offset="100%" stopColor="#3b82f6" stopOpacity={0.04} /></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="ds" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={78} label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
              <Tooltip content={<DarkTip />} />
              <Area type="monotone" dataKey="bandFloor" stackId="bt" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} name="P10" isAnimationActive animationDuration={300} animationEasing="ease-out" />
              <Area type="monotone" dataKey="bandRange" stackId="bt" stroke="none" fill="url(#btBandFill)" legendType="none" connectNulls dot={false} name="P10–P90 range" isAnimationActive animationDuration={300} animationEasing="ease-out" />
              <Line type="monotone" dataKey="predicted" name={`Predicted (${horizon}wk prior)`} stroke="#e2e8f0" strokeWidth={2} strokeDasharray="6 4" dot={{ r: 2.5, fill: '#e2e8f0' }} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />
              <Line type="monotone" dataKey="actual" name="Actual" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3, fill: '#f59e0b' }} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}
    </CardWrap>
  );
};

export default BacktestSection;
