import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { DarkTip, fmtM } from '../common';

const RunningTotalsChart = ({ rows }) => {
  const data = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 16, right: 20, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ytdActualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={(d) => d?.slice(0, 7)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={78} label={{ value: 'Cumulative Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<DarkTip />} />
        <Area type="monotone" dataKey="ytd_actual" name="Actuals YTD" stroke="#f59e0b" strokeWidth={2.5} fill="url(#ytdActualFill)" dot={false} connectNulls={false} />
        <Line type="monotone" dataKey="ytd_worst" name="Risk Floor" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_likely" name="Most Likely" stroke="#e2e8f0" strokeWidth={2.5} dot={false} connectNulls />
        <Line type="monotone" dataKey="ytd_best" name="Stretch Case" stroke="#10b981" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export default RunningTotalsChart;
