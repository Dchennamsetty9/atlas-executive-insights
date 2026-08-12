import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { DarkTip, EmptyState } from '../common';

const GeoBarChart = ({ rows }) => {
  if (!rows || rows.length === 0) return <EmptyState message="No geo breakdown available" />;

  const data = rows.map((r) => ({
    name: r.sales_market,
    likely: (r.arr_likely || 0) / 1e6,
  }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
        <XAxis type="number" tickFormatter={(v) => `$${v.toFixed(1)}M`} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="name" tick={{ fill: '#f1f5f9', fontSize: 10 }} axisLine={false} tickLine={false} width={52} />
        <Tooltip content={<DarkTip />} />
        <Bar dataKey="likely" name="Most Likely" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={14} isAnimationActive />
      </BarChart>
    </ResponsiveContainer>
  );
};

export default GeoBarChart;
