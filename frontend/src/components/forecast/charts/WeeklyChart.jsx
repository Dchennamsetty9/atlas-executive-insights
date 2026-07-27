import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fmtDate, fmtM } from '../common';

const WeeklyChart = ({ rows }) => {
  const combined = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  const lastActual = [...combined].reverse().find((r) => r.arr_actual != null);
  const splitDate = lastActual?.date ?? null;
  const todayIso = new Date().toISOString().slice(0, 10);
  const hasTodayInRange = combined.some((r) => r.date >= todayIso);
  const INNER_Z_RATIO = 0.6745 / 1.2816;

  const data = combined.map((r) => {
    const likely = r.arr_likely ?? null;
    const worst = r.arr_worst ?? null;
    const best = r.arr_best ?? null;
    const hasBand = likely != null && worst != null && best != null;
    const innerLo = hasBand ? likely - (likely - worst) * INNER_Z_RATIO : null;
    const innerHi = hasBand ? likely + (best - likely) * INNER_Z_RATIO : null;
    return {
      date: r.date,
      actual: r.arr_actual ?? null,
      likely,
      worst,
      best,
      innerLo,
      innerHi,
      bandFloor: worst,
      bandRange: best != null && worst != null ? Math.max(0, best - worst) : null,
      innerFloor: innerLo,
      innerRange: innerHi != null && innerLo != null ? Math.max(0, innerHi - innerLo) : null,
    };
  });

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload || {};
    return (
      <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 10, padding: '12px 16px', fontSize: 11, minWidth: 180 }}>
        <div style={{ color: '#64748b', marginBottom: 8, fontWeight: 600 }}>{label}</div>
        {d.actual != null && <div style={{ color: '#f59e0b', marginBottom: 3 }}>● Actuals: <b>{fmtM(d.actual)}</b></div>}
        {d.likely != null && <div style={{ color: '#e2e8f0', marginBottom: 3 }}>● Most Likely: <b>{fmtM(d.likely)}</b></div>}
        {d.best != null && <div style={{ color: '#10b981', marginBottom: 3 }}>▲ Stretch Case — 1-in-5 upside: <b>{fmtM(d.best)}</b></div>}
        {d.worst != null && <div style={{ color: '#ef4444', marginBottom: 3 }}>▼ Risk Floor — 1-in-10 downside: <b>{fmtM(d.worst)}</b></div>}
        {d.innerLo != null && d.innerHi != null && (
          <div style={{ color: '#22d3ee', marginTop: 5, paddingTop: 5, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
            ▒ 50% band: <b>{fmtM(d.innerLo)} – {fmtM(d.innerHi)}</b>
          </div>
        )}
        {d.worst != null && d.best != null && (
          <div style={{ color: '#60a5fa', marginTop: 2 }}>
            ▒ 80% band: <b>{fmtM(d.worst)} – {fmtM(d.best)}</b>
          </div>
        )}
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={360}>
      <ComposedChart data={data} margin={{ top: 20, right: 20, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="actualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.18} />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.03} />
          </linearGradient>
          <linearGradient id="innerBandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.08} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={78} label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<CustomTooltip />} />
        {hasTodayInRange && (
          <ReferenceLine
            x={todayIso}
            stroke="rgba(14,165,233,0.65)"
            strokeDasharray="2 3"
            label={{ value: 'TODAY', position: 'insideTop', fill: '#38bdf8', fontSize: 9, fontWeight: 700 }}
          />
        )}
        {splitDate && <ReferenceLine x={splitDate} stroke="rgba(59,130,246,0.45)" strokeDasharray="4 4" label={{ value: '◀ ACTUALS', position: 'insideTopRight', fill: '#f59e0b', fontSize: 10, fontWeight: 700 }} />}
        {splitDate && <ReferenceLine x={splitDate} stroke="none" label={{ value: 'FORECAST ▶', position: 'insideTopLeft', fill: '#3b82f6', fontSize: 10, fontWeight: 700 }} />}
        <Area type="monotone" dataKey="bandFloor" stackId="conf" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Area type="monotone" dataKey="bandRange" stackId="conf" stroke="none" fill="url(#bandFill)" legendType="none" connectNulls dot={false} isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Area type="monotone" dataKey="innerFloor" stackId="conf50" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Area type="monotone" dataKey="innerRange" stackId="conf50" stroke="none" fill="url(#innerBandFill)" legendType="none" connectNulls dot={false} isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Area type="monotone" dataKey="actual" stroke="#f59e0b" strokeWidth={2.5} fill="url(#actualFill)" dot={false} connectNulls={false} name="Actuals" isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Line type="monotone" dataKey="worst" name="Risk Floor" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Line type="monotone" dataKey="likely" name="Most Likely" stroke="#e2e8f0" strokeWidth={3} dot={false} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />
        <Line type="monotone" dataKey="best" name="Stretch Case" stroke="#10b981" strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive animationDuration={300} animationEasing="ease-out" />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export default WeeklyChart;
