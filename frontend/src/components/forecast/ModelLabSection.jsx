import { useEffect, useMemo, useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { apiService } from '../../services/api';
import { CardWrap, DarkTip, EmptyState, SectionTitle, Skeleton, fmtDate, fmtM } from './common';

const ML_COLORS = ['#00FF88', '#f59e0b', '#3b82f6', '#a78bfa', '#fb923c', '#22d3ee', '#f472b6'];

const pillStyle = (active, color) => ({
  padding: '4px 11px',
  borderRadius: 999,
  fontSize: 10,
  fontWeight: 700,
  cursor: 'pointer',
  transition: 'all 0.15s ease',
  display: 'flex',
  alignItems: 'center',
  gap: 5,
  border: `1px solid ${active ? (color ?? 'rgba(255,255,255,0.4)') : 'rgba(255,255,255,0.08)'}`,
  background: active ? `${(color ?? '#ffffff')}1a` : 'rgba(255,255,255,0.03)',
  color: active ? (color ?? '#f1f5f9') : '#475569',
});

const mlLabel = (m) => {
  if (!m) return '';
  if (m === 'Adaptive_Ensemble') return 'Ensemble ★';
  return m.replace(/_/g, ' ').replace(/\btrend\b/i, '').replace(/\bv2\b/i, '').trim();
};

const ModelLabSection = ({ product, salesMarket }) => {
  const [grain, setGrain] = useState('total');
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(null);
  const [mlLoading, setMlLoading] = useState(false);
  const [mlError, setMlError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setMlLoading(true);
      setMlError(null);
      try {
        const res = await apiService.getForecastV2ModelLab(product, grain, salesMarket);
        if (cancelled) return;
        setData(res);
        setSel((prev) => (res?.models?.includes(prev) ? prev : (res?.recommended_model || res?.models?.[0] || null)));
      } catch (e) {
        if (!cancelled) setMlError(e.message || 'Failed to load model forecasts');
      } finally {
        if (!cancelled) setMlLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [product, grain, salesMarket]);

  const rows = data?.rows || [];
  const models = data?.models || [];
  const isDemo = data?.source !== 'live';

  const colorOf = useMemo(() => {
    const map = {};
    models.forEach((m, i) => {
      map[m] = m === 'Adaptive_Ensemble' ? '#00FF88' : ML_COLORS[i % ML_COLORS.length];
    });
    return map;
  }, [models]);

  const fan = useMemo(() => {
    const r = rows.filter((x) => x.model === sel).sort((a, b) => a.ds.localeCompare(b.ds));
    return r.map((x) => ({ date: x.ds, p10: x.p10, p50: x.p50, p90: x.p90, bandFloor: x.p10, bandRange: x.p90 != null && x.p10 != null ? Math.max(0, x.p90 - x.p10) : null }));
  }, [rows, sel]);

  const compare = useMemo(() => {
    const byDate = {};
    for (const x of rows) {
      if (!byDate[x.ds]) byDate[x.ds] = { date: x.ds };
      byDate[x.ds][x.model] = x.p50;
    }
    return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
  }, [rows]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Model Lab — {product} · V5 forecast models</span>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 20, color: isDemo ? '#f59e0b' : '#10b981', background: isDemo ? 'rgba(245,158,11,0.08)' : 'rgba(16,185,129,0.1)', border: `1px solid ${isDemo ? 'rgba(245,158,11,0.2)' : 'rgba(16,185,129,0.3)'}` }}>{isDemo ? 'DEMO' : 'LIVE'}</span>
        {data?.run_date && <span style={{ fontSize: 10, color: '#475569' }}>run {String(data.run_date).slice(0, 10)}</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {[{ k: 'total', l: 'Total' }, { k: 'market', l: 'By Market' }].map((g) => <button key={g.k} onClick={() => setGrain(g.k)} style={pillStyle(grain === g.k, '#3b82f6')}>{g.l}</button>)}
        </div>
      </div>

      <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.5, marginTop: -6 }}>
        Sourced from the V5 notebooks' output tables (weekly run). Each model carries its <b style={{ color: '#94a3b8' }}>own</b> P10–P90
        band, so switching model changes the uncertainty range, not just the center line.
        {grain === 'market' && salesMarket && salesMarket !== 'All' ? ` Region: ${salesMarket}.` : ''}
      </div>

      {mlError && <div style={{ padding: '14px', borderRadius: 8, color: '#ef4444', background: 'rgba(239,68,68,0.06)', fontSize: 12 }}>⚠ {mlError}</div>}

      {models.length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{models.map((m) => <button key={m} onClick={() => setSel(m)} style={pillStyle(sel === m, colorOf[m])}>{mlLabel(m)}</button>)}</div>}

      <CardWrap downloadName={`model_lab_${product}_${sel || ''}`}>
        <SectionTitle>{mlLabel(sel)} — Forecast with its own confidence band</SectionTitle>
        {mlLoading ? <Skeleton height={300} /> : fan.length === 0 ? <EmptyState message="No model forecast for this selection yet" /> : (
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={fan} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
              <defs><linearGradient id="mlBand" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={colorOf[sel] || '#3b82f6'} stopOpacity={0.22} /><stop offset="100%" stopColor={colorOf[sel] || '#3b82f6'} stopOpacity={0.04} /></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={78} label={{ value: 'Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
              <Tooltip content={<DarkTip />} />
              <Area type="monotone" dataKey="bandFloor" stackId="mlb" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} name="P10" isAnimationActive animationDuration={300} animationEasing="ease-out" />
              <Area type="monotone" dataKey="bandRange" stackId="mlb" stroke="none" fill="url(#mlBand)" legendType="none" connectNulls dot={false} name="P10–P90 range" isAnimationActive animationDuration={300} animationEasing="ease-out" />
              <Line type="monotone" dataKey="p50" name="Most Likely (P50)" stroke={colorOf[sel] || '#e2e8f0'} strokeWidth={2.5} dot={false} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </CardWrap>

      <CardWrap downloadName={`model_lab_${product}_comparison`}>
        <SectionTitle>Model Comparison — where the models agree & disagree (P50)</SectionTitle>
        {mlLoading ? <Skeleton height={240} /> : compare.length === 0 ? <EmptyState message="No model data for this selection yet" /> : (
          <>
            <div style={{ fontSize: 10, color: '#475569', marginBottom: 8, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              {models.map((m) => <span key={m}><span style={{ color: colorOf[m] }}>─</span> {mlLabel(m)}</span>)}
            </div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={compare} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={72} />
                <Tooltip content={<DarkTip />} />
                {models.map((m) => <Line key={m} type="monotone" dataKey={m} name={mlLabel(m)} stroke={colorOf[m]} strokeWidth={m === 'Adaptive_Ensemble' ? 3 : 1.5} strokeDasharray={m === 'Adaptive_Ensemble' ? undefined : '4 3'} dot={false} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />)}
              </LineChart>
            </ResponsiveContainer>
          </>
        )}
      </CardWrap>
    </div>
  );
};

export default ModelLabSection;
