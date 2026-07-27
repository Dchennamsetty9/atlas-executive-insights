import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { DarkTip, fmtM, YEAR_COLORS } from '../common';

const MultiYearChart = ({ rows, currentYear }) => {
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const byIsoWeek = {};
  for (const r of rows) {
    if (!byIsoWeek[r.iso_week]) byIsoWeek[r.iso_week] = { iso_week: r.iso_week };
    byIsoWeek[r.iso_week][r.year] = (byIsoWeek[r.iso_week][r.year] || 0) + r.arr;
  }
  const data = Object.values(byIsoWeek).sort((a, b) => a.iso_week - b.iso_week);
  const qEndWeeks = [13, 26, 39, 52];

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        {qEndWeeks.map((w) => (
          <ReferenceArea key={w} x1={w - 1} x2={w} fill="rgba(148,163,184,0.08)" strokeOpacity={0} />
        ))}
        <XAxis dataKey="iso_week" tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} width={72} label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 9, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<DarkTip />} />
        {years.map((yr) => (
          <Line
            key={yr}
            type="monotone"
            dataKey={yr}
            name={String(yr)}
            stroke={YEAR_COLORS[yr] ?? '#94a3b8'}
            strokeWidth={yr === currentYear ? 2.8 : 1.2}
            strokeOpacity={yr === currentYear ? 1 : 0.35}
            dot={false}
            connectNulls
            isAnimationActive
            animationDuration={300}
            animationEasing="ease-out"
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
};

export default MultiYearChart;
