import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { DarkTip, fmtM, YEAR_COLORS } from '../common';

const MultiYearChart = ({ rows, currentYear }) => {
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const visibleYears = years.slice(-3);
  const priorYear = currentYear - 1;
  const byIsoWeek = {};
  for (const r of rows) {
    if (!byIsoWeek[r.iso_week]) byIsoWeek[r.iso_week] = { iso_week: r.iso_week };
    byIsoWeek[r.iso_week][r.year] = (byIsoWeek[r.iso_week][r.year] || 0) + r.arr;
  }
  const data = Object.values(byIsoWeek).sort((a, b) => a.iso_week - b.iso_week);
  const qEndWeeks = [13, 26, 39, 52];

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        {qEndWeeks.map((w) => (
          <ReferenceArea key={w} x1={w - 1} x2={w} fill="rgba(148,163,184,0.08)" strokeOpacity={0} />
        ))}
        <XAxis dataKey="iso_week" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={(v) => fmtM(v)} tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} width={86} label={{ value: 'Weekly Growth ARR ($)', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11, style: { textAnchor: 'middle' } }} />
        <Tooltip content={<DarkTip />} />
        {visibleYears.map((yr) => (
          <Line
            key={yr}
            type="monotone"
            dataKey={yr}
            name={String(yr)}
            stroke={YEAR_COLORS[yr] ?? '#94a3b8'}
            strokeWidth={yr === currentYear ? 3.2 : yr === priorYear ? 2.2 : 1.4}
            strokeOpacity={yr === currentYear ? 1 : yr === priorYear ? 0.75 : 0.35}
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
