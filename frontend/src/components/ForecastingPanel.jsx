/**
 * ForecastingPanel — full-screen slide-in forecasting view.
 *
 * Tabs:
 *   Overview    — Weekly Forecast vs Actuals (scenarios) + Running Totals YTD
 *   Multi-Year  — Forecast vs Actuals over 2022–2026 (seasonality overlay)
 *   By Product  — per-product + ITSG/UCC bar breakdown
 *   Monthly     — Monthly Actuals vs Forecast table
 *   Accuracy    — MAPE leaderboard per product
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ComposedChart, AreaChart, BarChart, LineChart,
  Area, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmtM = (v) => {
  if (v == null || isNaN(Number(v))) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
};
const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  return `${dt.toLocaleString('default', { month: 'short' })} ${dt.getDate()}`;
};
const YEAR_COLORS = { 2022:'#64748b', 2023:'#06b6d4', 2024:'#3b82f6', 2025:'#f59e0b', 2026:'#ef4444' };
const MODEL_COLORS = { ETS:'#94a3b8', Prophet:'#f59e0b', LightGBM:'#3b82f6', Chronos:'#a78bfa', Ensemble:'#00FF88' };

const DarkTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8, padding: '10px 14px', fontSize: 11 }}>
      <div style={{ color: '#64748b', marginBottom: 6, fontWeight: 600 }}>{label}</div>
      {payload.map((p, i) => p.value != null && (
        <div key={i} style={{ color: p.color ?? '#94a3b8', margin: '2px 0' }}>
          <span style={{ marginRight: 6 }}>{p.name}:</span>
          <span style={{ fontWeight: 700 }}>{fmtM(p.value)}</span>
        </div>
      ))}
    </div>
  );
};

// ── Sub-charts ────────────────────────────────────────────────────────────────
const WeeklyChart = ({ rows, model }) => {
  const actuals  = rows.filter(r => r.arr_actual != null);
  const forecast = rows.filter(r => r.arr_likely  != null);
  const combined = [...actuals.map(r => ({ ...r, isActual: true })),
                    ...forecast.map(r => ({ ...r, isActual: false }))];
  combined.sort((a, b) => a.date.localeCompare(b.date));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={combined} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
        <XAxis dataKey="date" tickFormatter={fmtDate}
               tick={{ fill:'#475569', fontSize:9 }} axisLine={false} tickLine={false}
               interval="preserveStartEnd" />
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill:'#475569', fontSize:9 }}
               axisLine={false} tickLine={false} width={55} />
        <Tooltip content={<DarkTip />} />
        {/* Confidence band */}
        <Area type="monotone" dataKey="arr_worst"  stackId="band" stroke="none"
              fill="transparent" fillOpacity={0} name="Worst Case" connectNulls />
        <Area type="monotone" dataKey="arr_best" stroke="rgba(59,130,246,0.5)"
              strokeWidth={0.5} fill="rgba(59,130,246,0.12)" name="Best Case" connectNulls />
        {/* Scenarios */}
        <Line type="monotone" dataKey="arr_worst"  stroke="#ef4444" strokeWidth={1}
              strokeDasharray="4 3" dot={false} name="Worst Case" connectNulls />
        <Line type="monotone" dataKey="arr_likely" stroke="#ffffff" strokeWidth={2.5}
              dot={false} name="Most Likely" connectNulls />
        <Line type="monotone" dataKey="arr_best"   stroke="#10b981" strokeWidth={1}
              strokeDasharray="4 3" dot={false} name="Best Case" connectNulls />
        {/* Actuals */}
        <Line type="monotone" dataKey="arr_actual" stroke="#f59e0b" strokeWidth={2}
              dot={false} name="Actuals YTD" connectNulls={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

const RunningTotalsChart = ({ rows }) => (
  <ResponsiveContainer width="100%" height={200}>
    <ComposedChart data={rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
      <XAxis dataKey="date" tickFormatter={fmtDate}
             tick={{ fill:'#475569', fontSize:9 }} axisLine={false} tickLine={false}
             interval="preserveStartEnd" />
      <YAxis tickFormatter={v => fmtM(v)} tick={{ fill:'#475569', fontSize:9 }}
             axisLine={false} tickLine={false} width={55} />
      <Tooltip content={<DarkTip />} />
      <Line type="monotone" dataKey="ytd_worst"  stroke="#ef4444" strokeWidth={1}
            strokeDasharray="5 3" dot={false} name="Worst Case" connectNulls />
      <Line type="monotone" dataKey="ytd_likely" stroke="#ffffff" strokeWidth={2}
            dot={false} name="Most Likely" connectNulls />
      <Line type="monotone" dataKey="ytd_best"   stroke="#10b981" strokeWidth={1}
            strokeDasharray="5 3" dot={false} name="Best Case" connectNulls />
      <Line type="monotone" dataKey="ytd_actual" stroke="#f59e0b" strokeWidth={2}
            dot={false} name="Actuals YTD" connectNulls={false} />
    </ComposedChart>
  </ResponsiveContainer>
);

const MultiYearChart = ({ rows }) => {
  const years = [...new Set(rows.map(r => r.year))].sort();
  const byIsoWeek = {};
  for (const r of rows) {
    const key = r.iso_week;
    if (!byIsoWeek[key]) byIsoWeek[key] = { iso_week: key };
    byIsoWeek[key][r.year] = (byIsoWeek[key][r.year] || 0) + r.arr;
  }
  const data = Object.values(byIsoWeek).sort((a, b) => a.iso_week - b.iso_week);

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        <XAxis dataKey="iso_week" tick={{ fill:'#475569', fontSize:9 }}
               axisLine={false} tickLine={false} label={{ value:'ISO Week', position:'insideBottom', fill:'#475569', fontSize:9, dy:8 }} />
        <YAxis tickFormatter={v => fmtM(v)} tick={{ fill:'#475569', fontSize:9 }}
               axisLine={false} tickLine={false} width={55} />
        <Tooltip content={<DarkTip />} />
        <Legend wrapperStyle={{ fontSize: 10, color:'#64748b' }} />
        {years.map(yr => (
          <Line key={yr} type="monotone" dataKey={yr} name={String(yr)}
                stroke={YEAR_COLORS[yr] ?? '#94a3b8'} strokeWidth={1.5}
                dot={false} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
};

const ByProductChart = ({ byProduct, byLine }) => {
  const lineData = (byLine || []).map(l => ({
    name: l.product_line,
    worst:  l.arr_worst  / 1e6,
    likely: l.arr_likely / 1e6,
    best:   l.arr_best   / 1e6,
  }));
  const prodData = (byProduct || []).map(p => ({
    name: p.product,
    line: p.product_line,
    worst:  p.arr_worst  / 1e6,
    likely: p.arr_likely / 1e6,
    best:   p.arr_best   / 1e6,
    mape:   p.best_mape,
  }));

  const LINE_COLORS = { UCC:'#3b82f6', ITSG:'#10b981', Other:'#94a3b8' };

  return (
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
      {/* ITSG / UCC rollup */}
      <div>
        <div style={{ fontSize:11, color:'#64748b', marginBottom:8, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.05em' }}>
          By Product Line
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={lineData} layout="vertical" margin={{ left:8, right:16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tickFormatter={v=>`$${v.toFixed(1)}M`}
                   tick={{ fill:'#475569', fontSize:9 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ fill:'#f1f5f9', fontSize:10 }} axisLine={false} tickLine={false} width={40} />
            <Tooltip content={<DarkTip />} />
            <Bar dataKey="worst"  name="Worst"  fill="#ef4444" opacity={0.5} radius={[0,3,3,0]} barSize={14} />
            <Bar dataKey="likely" name="Likely" fill="#ffffff" opacity={0.9} radius={[0,3,3,0]} barSize={14} />
            <Bar dataKey="best"   name="Best"   fill="#10b981" opacity={0.5} radius={[0,3,3,0]} barSize={14} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* Per product */}
      <div>
        <div style={{ fontSize:11, color:'#64748b', marginBottom:8, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.05em' }}>
          By Product
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={prodData} layout="vertical" margin={{ left:8, right:16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tickFormatter={v=>`$${v.toFixed(1)}M`}
                   tick={{ fill:'#475569', fontSize:9 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ fill:'#f1f5f9', fontSize:9 }} axisLine={false} tickLine={false} width={72} />
            <Tooltip content={<DarkTip />} />
            <Bar dataKey="likely" name="Most Likely" fill="#3b82f6" radius={[0,4,4,0]} barSize={12} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

const MonthlyTable = ({ months }) => {
  const quarters = [...new Set((months||[]).map(m => m.quarter))].sort();
  const byQtr = {};
  for (const m of (months||[])) {
    if (!byQtr[m.quarter]) byQtr[m.quarter] = [];
    byQtr[m.quarter].push(m);
  }

  const tdStyle = { padding:'6px 12px', textAlign:'right', fontSize:12, color:'#94a3b8', borderBottom:'1px solid rgba(255,255,255,0.04)' };
  const thStyle = { padding:'6px 12px', textAlign:'right', fontSize:10, color:'#475569', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.04em' };

  return (
    <div style={{ overflowX:'auto' }}>
      <table style={{ width:'100%', borderCollapse:'collapse' }}>
        <thead>
          <tr style={{ borderBottom:'1px solid rgba(255,255,255,0.08)' }}>
            {['Year','Qtr','Month','Actuals','Worst Case','Most Likely','Best Case'].map(h => (
              <th key={h} style={{ ...thStyle, textAlign: h==='Month'||h==='Year'||h==='Qtr' ? 'left' : 'right' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {quarters.map(q => {
            const qMonths = byQtr[q] || [];
            const qTotals = qMonths.reduce((acc, m) => ({
              arr_actual: (acc.arr_actual||0) + (m.arr_actual||0),
              arr_worst:  acc.arr_worst  + m.arr_worst,
              arr_likely: acc.arr_likely + m.arr_likely,
              arr_best:   acc.arr_best   + m.arr_best,
            }), { arr_actual:0, arr_worst:0, arr_likely:0, arr_best:0 });

            return [
              ...qMonths.map((m, i) => (
                <tr key={`${q}-${m.month}`} style={{ background: i%2===0 ? 'rgba(255,255,255,0.01)' : 'transparent' }}>
                  <td style={{ ...tdStyle, textAlign:'left', color:'#64748b' }}>{i===0 ? m.year : ''}</td>
                  <td style={{ ...tdStyle, textAlign:'left', color:'#64748b' }}>{i===0 ? `Q${q}` : ''}</td>
                  <td style={{ ...tdStyle, textAlign:'left', color:'#f1f5f9', fontWeight:500 }}>{m.month_name}</td>
                  <td style={{ ...tdStyle, color: m.arr_actual ? '#f59e0b' : '#334155' }}>{fmtM(m.arr_actual)}</td>
                  <td style={{ ...tdStyle, color:'#ef4444' }}>{fmtM(m.arr_worst)}</td>
                  <td style={{ ...tdStyle, color:'#f1f5f9', fontWeight:600 }}>{fmtM(m.arr_likely)}</td>
                  <td style={{ ...tdStyle, color:'#10b981' }}>{fmtM(m.arr_best)}</td>
                </tr>
              )),
              <tr key={`qtot-${q}`} style={{ background:'rgba(59,130,246,0.06)', borderTop:'1px solid rgba(59,130,246,0.2)' }}>
                <td style={{ ...tdStyle, textAlign:'left', color:'#64748b' }} />
                <td style={{ ...tdStyle, textAlign:'left', color:'#3b82f6', fontWeight:700 }}>Total</td>
                <td style={{ ...tdStyle, textAlign:'left', color:'#3b82f6', fontWeight:700 }}>{`Q${q} Total`}</td>
                <td style={{ ...tdStyle, color:'#f59e0b', fontWeight:700 }}>{fmtM(qTotals.arr_actual)}</td>
                <td style={{ ...tdStyle, color:'#ef4444', fontWeight:700 }}>{fmtM(qTotals.arr_worst)}</td>
                <td style={{ ...tdStyle, color:'#f1f5f9', fontWeight:700 }}>{fmtM(qTotals.arr_likely)}</td>
                <td style={{ ...tdStyle, color:'#10b981', fontWeight:700 }}>{fmtM(qTotals.arr_best)}</td>
              </tr>,
            ];
          })}
        </tbody>
      </table>
    </div>
  );
};

const AccuracyTable = ({ data }) => {
  const models = ['ETS', 'Prophet', 'LightGBM', 'Chronos'];
  const mapeColor = (v) => v < 15 ? '#10b981' : v < 25 ? '#f59e0b' : '#ef4444';

  return (
    <div style={{ overflowX:'auto' }}>
      <table style={{ width:'100%', borderCollapse:'collapse' }}>
        <thead>
          <tr style={{ borderBottom:'1px solid rgba(255,255,255,0.08)' }}>
            {['Product','Line',...models,'Best Model','Best MAPE'].map(h => (
              <th key={h} style={{ padding:'6px 12px', textAlign: ['Product','Line','Best Model'].includes(h)?'left':'right',
                                   fontSize:10, color:'#475569', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.04em' }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(data||[]).map((r, i) => (
            <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.03)', background: i%2===0?'rgba(255,255,255,0.01)':'transparent' }}>
              <td style={{ padding:'6px 12px', fontSize:12, color:'#f1f5f9' }}>{r.product}</td>
              <td style={{ padding:'6px 12px', fontSize:11, color: r.product_line==='UCC'?'#3b82f6':'#10b981' }}>{r.product_line}</td>
              {models.map(m => (
                <td key={m} style={{ padding:'6px 12px', textAlign:'right', fontSize:12,
                                     color: r[m] ? mapeColor(r[m]) : '#334155', fontWeight: r.best_model===m?700:400 }}>
                  {r[m] ? `${r[m].toFixed(1)}%` : '—'}
                  {r.best_model === m && <span style={{ marginLeft:4, fontSize:9 }}>★</span>}
                </td>
              ))}
              <td style={{ padding:'6px 12px', textAlign:'left', fontSize:11, color:'#f59e0b', fontWeight:600 }}>{r.best_model}</td>
              <td style={{ padding:'6px 12px', textAlign:'right', fontSize:12, fontWeight:700,
                           color: r.best_mape ? mapeColor(r.best_mape) : '#334155' }}>
                {r.best_mape ? `${r.best_mape.toFixed(1)}%` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ── Main Panel ────────────────────────────────────────────────────────────────
const TABS = ['Overview', 'Multi-Year', 'By Product', 'Monthly', 'Accuracy'];
const MODELS = ['ensemble', 'prophet', 'lightgbm', 'ets', 'chronos'];
const PRODUCTS = ['All', 'GoTo Connect', 'GoTo Resolve', 'GoTo Engage', 'GoTo Central', 'Rescue'];
const PRODUCT_LINES = ['All', 'UCC', 'ITSG'];
const FC_TYPES = [{ key:'rolling', label:'13-Week Quarter' }, { key:'roy', label:'Rest of Year' }];

const BASE = '/api/forecast/v2';

const ForecastingPanel = ({ open, onClose }) => {
  const [tab,        setTab]        = useState('Overview');
  const [model,      setModel]      = useState('ensemble');
  const [fcType,     setFcType]     = useState('rolling');
  const [product,    setProduct]    = useState('All');
  const [prodLine,   setProdLine]   = useState('All');

  // Data state
  const [weekly,     setWeekly]     = useState(null);
  const [ytd,        setYtd]        = useState(null);
  const [historical, setHistorical] = useState(null);
  const [byProduct,  setByProduct]  = useState(null);
  const [monthly,    setMonthly]    = useState(null);
  const [leaderboard,setLeaderboard]= useState(null);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState(null);

  const productParam    = product  !== 'All' ? `&product=${encodeURIComponent(product)}` : '';
  const prodLineParam   = prodLine !== 'All' ? `&product_line=${encodeURIComponent(prodLine)}` : '';
  const commonParams    = `forecast_type=${fcType}${productParam}${prodLineParam}`;

  const fetchAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [wk, yt, hs, bp, mo, lb] = await Promise.allSettled([
        fetch(`${BASE}/weekly?model=${model}&${commonParams}`).then(r=>r.json()),
        fetch(`${BASE}/ytd?${commonParams}`).then(r=>r.json()),
        fetch(`${BASE}/historical?${productParam}${prodLineParam}`).then(r=>r.json()),
        fetch(`${BASE}/by-product?forecast_type=${fcType}`).then(r=>r.json()),
        fetch(`${BASE}/monthly?${commonParams}`).then(r=>r.json()),
        fetch(`${BASE}/leaderboard`).then(r=>r.json()),
      ]);
      if (wk.status==='fulfilled') setWeekly(wk.value?.rows ?? []);
      if (yt.status==='fulfilled') setYtd(yt.value?.rows ?? []);
      if (hs.status==='fulfilled') setHistorical(hs.value?.rows ?? []);
      if (bp.status==='fulfilled') setByProduct(bp.value ?? null);
      if (mo.status==='fulfilled') setMonthly(mo.value?.months ?? []);
      if (lb.status==='fulfilled') setLeaderboard(lb.value?.data ?? []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [model, fcType, product, prodLine]);

  useEffect(() => { if (open) fetchAll(); }, [open, fetchAll]);

  if (!open) return null;

  const pillStyle = (active) => ({
    padding: '4px 12px', borderRadius: 999, fontSize: 10, fontWeight: 700,
    cursor: 'pointer', border: `1px solid ${active ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.08)'}`,
    background: active ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.03)',
    color: active ? '#f1f5f9' : '#475569',
  });

  const sectionTitle = (t) => (
    <div style={{ fontSize:12, fontWeight:700, color:'#64748b', textTransform:'uppercase',
                  letterSpacing:'0.06em', marginBottom:10, marginTop:6 }}>{t}</div>
  );

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 900,
      display: 'flex', justifyContent: 'flex-end',
    }}>
      {/* Backdrop */}
      <div onClick={onClose} style={{ position:'absolute', inset:0, background:'rgba(0,0,0,0.6)', backdropFilter:'blur(4px)' }} />

      {/* Panel */}
      <div style={{
        position: 'relative', zIndex: 1,
        width: 'min(1100px, 92vw)', height: '100vh',
        background: '#080d1a',
        borderLeft: '1px solid rgba(255,255,255,0.08)',
        display: 'flex', flexDirection: 'column',
        boxShadow: '-8px 0 40px rgba(0,0,0,0.5)',
        animation: 'slideInRight 0.25s ease-out',
        overflow: 'hidden',
      }}>
        {/* ── Header ── */}
        <div style={{ padding:'18px 24px 14px', borderBottom:'1px solid rgba(255,255,255,0.07)',
                      display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <span style={{ fontSize:20, fontWeight:800, color:'#f1f5f9', letterSpacing:-0.5 }}>
                ARR Forecast
              </span>
              <span style={{
                fontSize:10, fontWeight:700, color:'#10b981',
                background:'rgba(16,185,129,0.1)', border:'1px solid rgba(16,185,129,0.3)',
                padding:'2px 8px', borderRadius:20, letterSpacing:'0.05em',
              }}>LIVE</span>
            </div>
            <div style={{ fontSize:10, color:'#475569', marginTop:3 }}>
              5-Model Ensemble · ETS · Prophet · LightGBM · Chronos · Growth ARR only
            </div>
          </div>
          <button onClick={onClose} style={{
            background:'rgba(255,255,255,0.05)', border:'1px solid rgba(255,255,255,0.1)',
            borderRadius:8, color:'#64748b', fontSize:18, lineHeight:1,
            padding:'6px 12px', cursor:'pointer',
          }}>✕</button>
        </div>

        {/* ── Controls ── */}
        <div style={{ padding:'12px 24px', borderBottom:'1px solid rgba(255,255,255,0.05)',
                      display:'flex', flexWrap:'wrap', gap:12, alignItems:'center', flexShrink:0 }}>
          {/* Forecast type */}
          <div style={{ display:'flex', gap:4 }}>
            {FC_TYPES.map(f => (
              <button key={f.key} onClick={()=>setFcType(f.key)} style={pillStyle(fcType===f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <div style={{ width:1, height:20, background:'rgba(255,255,255,0.07)' }} />
          {/* Model */}
          <div style={{ display:'flex', gap:4 }}>
            {MODELS.map(m => (
              <button key={m} onClick={()=>setModel(m)} style={{
                ...pillStyle(model===m),
                color: model===m ? (MODEL_COLORS[m.charAt(0).toUpperCase()+m.slice(1)] ?? '#f1f5f9') : '#475569',
                borderColor: model===m ? (MODEL_COLORS[m.charAt(0).toUpperCase()+m.slice(1)] ?? 'rgba(255,255,255,0.4)') : 'rgba(255,255,255,0.08)',
              }}>
                {m.charAt(0).toUpperCase()+m.slice(1)}
              </button>
            ))}
          </div>
          <div style={{ width:1, height:20, background:'rgba(255,255,255,0.07)' }} />
          {/* Product line */}
          <div style={{ display:'flex', gap:4 }}>
            {PRODUCT_LINES.map(pl => (
              <button key={pl} onClick={()=>setProdLine(pl)} style={{
                ...pillStyle(prodLine===pl),
                color: prodLine===pl ? (pl==='UCC'?'#3b82f6':pl==='ITSG'?'#10b981':'#f1f5f9') : '#475569',
              }}>{pl}</button>
            ))}
          </div>
          {/* Product */}
          <select
            value={product}
            onChange={e => setProduct(e.target.value)}
            style={{
              background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.1)',
              borderRadius:8, color:'#94a3b8', fontSize:11, padding:'4px 10px', cursor:'pointer',
            }}
          >
            {PRODUCTS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>

          <button onClick={fetchAll} disabled={loading} style={{
            marginLeft:'auto', padding:'4px 14px', borderRadius:8, fontSize:11, fontWeight:600,
            background:'rgba(59,130,246,0.12)', border:'1px solid rgba(59,130,246,0.3)',
            color:'#3b82f6', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.5 : 1,
          }}>
            {loading ? 'Loading…' : '⟳ Refresh'}
          </button>
        </div>

        {/* ── Tabs ── */}
        <div style={{ display:'flex', gap:0, borderBottom:'1px solid rgba(255,255,255,0.07)', flexShrink:0 }}>
          {TABS.map(t => (
            <button key={t} onClick={()=>setTab(t)} style={{
              padding:'10px 20px', fontSize:12, fontWeight: tab===t ? 700 : 500,
              color: tab===t ? '#f1f5f9' : '#475569',
              background:'transparent', border:'none',
              borderBottom: tab===t ? '2px solid #3b82f6' : '2px solid transparent',
              cursor:'pointer', transition:'all 0.15s',
            }}>{t}</button>
          ))}
        </div>

        {/* ── Content ── */}
        <div style={{ flex:1, overflowY:'auto', padding:'20px 24px' }}>
          {error && (
            <div style={{ background:'rgba(239,68,68,0.1)', border:'1px solid rgba(239,68,68,0.2)',
                          borderRadius:8, padding:'10px 14px', color:'#ef4444', fontSize:12, marginBottom:12 }}>
              {error} — showing demo data
            </div>
          )}

          {/* OVERVIEW ─────────────────────────────────────────────────────── */}
          {tab === 'Overview' && (
            <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
              {/* KPI row */}
              {weekly && weekly.length > 0 && (() => {
                const fcRows = weekly.filter(r => r.arr_likely != null);
                const total  = fcRows.reduce((s, r) => s + r.arr_likely, 0);
                const worst  = fcRows.reduce((s, r) => s + r.arr_worst,  0);
                const best   = fcRows.reduce((s, r) => s + r.arr_best,   0);
                const actYTD = weekly.filter(r=>r.arr_actual).reduce((s,r)=>s+r.arr_actual,0);
                return (
                  <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:10 }}>
                    {[
                      { label:'Most Likely', val:total,   color:'#ffffff' },
                      { label:'Best Case',   val:best,    color:'#10b981' },
                      { label:'Worst Case',  val:worst,   color:'#ef4444' },
                      { label:'Actuals YTD', val:actYTD,  color:'#f59e0b' },
                    ].map(({ label, val, color }) => (
                      <div key={label} style={{
                        background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.06)',
                        borderRadius:10, padding:'12px 14px',
                      }}>
                        <div style={{ fontSize:9, color:'#475569', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:4 }}>{label}</div>
                        <div style={{ fontSize:20, fontWeight:800, color, letterSpacing:-0.5 }}>{fmtM(val)}</div>
                      </div>
                    ))}
                  </div>
                );
              })()}

              <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                {sectionTitle('Weekly Forecast vs Actuals')}
                <div style={{ fontSize:10, color:'#334155', marginBottom:10 }}>
                  <span style={{ color:'#f59e0b' }}>─</span> Actuals YTD &nbsp;
                  <span style={{ color:'#ef4444' }}>- -</span> Worst &nbsp;
                  <span style={{ color:'#ffffff' }}>─</span> Most Likely &nbsp;
                  <span style={{ color:'#10b981' }}>- -</span> Best
                </div>
                {weekly ? <WeeklyChart rows={weekly} model={model} /> :
                  <div style={{ height:260, display:'flex', alignItems:'center', justifyContent:'center', color:'#475569' }}>Loading…</div>}
              </div>

              <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                {sectionTitle('Running Totals (YTD)')}
                {ytd ? <RunningTotalsChart rows={ytd} /> :
                  <div style={{ height:200, display:'flex', alignItems:'center', justifyContent:'center', color:'#475569' }}>Loading…</div>}
              </div>
            </div>
          )}

          {/* MULTI-YEAR ────────────────────────────────────────────────────── */}
          {tab === 'Multi-Year' && (
            <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
              <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                {sectionTitle('Historical Seasonality (Weekly by ISO Week)')}
                <div style={{ fontSize:10, color:'#334155', marginBottom:10 }}>
                  {Object.entries(YEAR_COLORS).map(([yr,c]) => (
                    <span key={yr} style={{ marginRight:12 }}>
                      <span style={{ color:c }}>─</span> {yr}
                    </span>
                  ))}
                </div>
                {historical ? <MultiYearChart rows={historical} /> :
                  <div style={{ height:260, display:'flex', alignItems:'center', justifyContent:'center', color:'#475569' }}>Loading…</div>}
              </div>

              <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                {sectionTitle('Historical Weekly Trend')}
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={(historical||[]).map(r=>({ ...r, date: r.date }))}
                             margin={{ top:6, right:8, left:0, bottom:0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="date" tickFormatter={d => d?.slice(0,7)}
                           tick={{ fill:'#475569', fontSize:9 }} axisLine={false} tickLine={false}
                           interval={12} />
                    <YAxis tickFormatter={v=>fmtM(v)} tick={{ fill:'#475569', fontSize:9 }}
                           axisLine={false} tickLine={false} width={55} />
                    <Tooltip content={<DarkTip />} />
                    <Line type="monotone" dataKey="arr" stroke="#3b82f6" strokeWidth={1.5}
                          dot={false} name="Weekly ARR" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* BY PRODUCT ────────────────────────────────────────────────────── */}
          {tab === 'By Product' && (
            <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
              <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                {sectionTitle('Forecast by Product & Product Line')}
                {byProduct
                  ? <ByProductChart byProduct={byProduct.by_product} byLine={byProduct.by_product_line} />
                  : <div style={{ height:200, display:'flex', alignItems:'center', justifyContent:'center', color:'#475569' }}>Loading…</div>}
              </div>

              {byProduct?.by_product && (
                <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                  {sectionTitle('Forecast Summary Table')}
                  <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
                    <thead>
                      <tr style={{ borderBottom:'1px solid rgba(255,255,255,0.08)' }}>
                        {['Product','Line','Worst','Most Likely','Best','Best MAPE'].map(h=>(
                          <th key={h} style={{ padding:'6px 12px', textAlign:['Product','Line'].includes(h)?'left':'right',
                                               fontSize:10, color:'#475569', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {byProduct.by_product.map((p, i) => (
                        <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.03)', background:i%2===0?'rgba(255,255,255,0.01)':'transparent' }}>
                          <td style={{ padding:'6px 12px', color:'#f1f5f9' }}>{p.product}</td>
                          <td style={{ padding:'6px 12px', color:p.product_line==='UCC'?'#3b82f6':'#10b981', fontWeight:600 }}>{p.product_line}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:'#ef4444' }}>{fmtM(p.arr_worst)}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:'#f1f5f9', fontWeight:700 }}>{fmtM(p.arr_likely)}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color:'#10b981' }}>{fmtM(p.arr_best)}</td>
                          <td style={{ padding:'6px 12px', textAlign:'right', color: p.best_mape<15?'#10b981':p.best_mape<25?'#f59e0b':'#ef4444', fontWeight:600 }}>
                            {p.best_mape < 999 ? `${p.best_mape.toFixed(1)}%` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* MONTHLY ───────────────────────────────────────────────────────── */}
          {tab === 'Monthly' && (
            <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
              {sectionTitle('Monthly Actuals vs Forecast (incl. Worst / Most Likely / Best)')}
              {monthly
                ? <MonthlyTable months={monthly} />
                : <div style={{ height:200, display:'flex', alignItems:'center', justifyContent:'center', color:'#475569' }}>Loading…</div>}
            </div>
          )}

          {/* ACCURACY ──────────────────────────────────────────────────────── */}
          {tab === 'Accuracy' && (
            <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
              <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
                {[{label:'< 15%', color:'#10b981'},{label:'15–25%', color:'#f59e0b'},{label:'> 25%', color:'#ef4444'}].map(b=>(
                  <div key={b.label} style={{ display:'flex', alignItems:'center', gap:6, fontSize:11, color:'#64748b' }}>
                    <div style={{ width:10, height:10, borderRadius:2, background:b.color }} />
                    MAPE {b.label}
                  </div>
                ))}
              </div>
              <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:12, padding:16 }}>
                {sectionTitle('Model MAPE Leaderboard (8-Week Holdout Validation)')}
                {leaderboard
                  ? <AccuracyTable data={leaderboard} />
                  : <div style={{ height:200, display:'flex', alignItems:'center', justifyContent:'center', color:'#475569' }}>Loading…</div>}
              </div>
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </div>
  );
};

export default ForecastingPanel;
