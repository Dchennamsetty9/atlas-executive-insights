import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fmtM } from '../common';

// CustomTooltip declared outside to avoid react-hooks/static-components warning
const RunningTotalsChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload || {};
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 10, padding: '12px 16px', fontSize: 11, minWidth: 180 }}>
      <div style={{ color: '#64748b', marginBottom: 8, fontWeight: 600 }}>{label}</div>
      {d.ytd_actual != null && <div style={{ color: '#f59e0b', marginBottom: 3 }}>● Actuals YTD: <b>{fmtM(d.ytd_actual)}</b></div>}
      {d.ytd_likely != null && <div style={{ color: '#e2e8f0', marginBottom: 3 }}>● Most Likely YTD: <b>{fmtM(d.ytd_likely)}</b></div>}
      {d.ytd_best != null && <div style={{ color: '#10b981', marginBottom: 3 }}>▲ Stretch Case — 1-in-5 upside: <b>{fmtM(d.ytd_best)}</b></div>}
      {d.ytd_worst != null && <div style={{ color: '#ef4444', marginBottom: 3 }}>▼ Risk Floor — 1-in-10 downside: <b>{fmtM(d.ytd_worst)}</b></div>}
    </div>
  );
};

const RunningTotalsChart = ({ rows }) => {
  const data = [...rows].sort((a, b) => a.date.localeCompare(b.date)).map((r) => {
    const likely = r.ytd_likely ?? null;
    const worst = r.ytd_worst ?? null;
    const best = r.ytd_best ?? null;
    const hasBand = likely != null && worst != null && best != null;
    const INNER_Z_RATIO = 0.6745 / 1.2816;
    const innerLo = hasBand ? likely - (likely - worst) * INNER_Z_RATIO : null;
    const innerHi = hasBand ? likely + (best - likely) * INNER_Z_RATIO : null;
    return {
      ...r,
      bandFloor: worst,
      bandRange: best != null && worst != null ? Math.max(0, best - worst) : null,
      innerFloor: innerLo,
      innerRange: innerHi != null && innerLo != null ? Math.max(0, innerHi - innerLo) : null,
    };
  });

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 16, right: 20, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ytdActualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="ytdBandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.18} />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.03} />
          </linearGradient>
          <linearGradient id="ytdInnerBandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.08} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={(d) => d?.slice(0, 7)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={78} label={{ value: 'Cumulative Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<RunningTotalsChartTooltip />} />
        <Area type="monotone" dataKey="bandFloor" stackId="conf" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="bandRange" stackId="conf" stroke="none" fill="url(#ytdBandFill)" legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="innerFloor" stackId="conf50" stroke="none" fill="transparent" legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="innerRange" stackId="conf50" stroke="none" fill="url(#ytdInnerBandFill)" legendType="none" connectNulls dot={false} />
        <Area type="monotone" dataKey="ytd_actual" name="Actuals YTD" stroke="#f59e0b" strokeWidth={2.5} fill="url(#ytdActualFill)" dot={false} connectNulls={false} />
        <Line type="monotone" dataKey="ytd_worst" name="Risk Floor" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_likely" name="Most Likely" stroke="#e2e8f0" strokeWidth={2.5} dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_best" name="Stretch Case" stroke="#10b981" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export default RunningTotalsChart;
