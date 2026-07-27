import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { DarkTip } from '../common';

const ByProductChart = ({ byProduct, byLine }) => {
  const lineData = (byLine || []).map((l) => ({
    name: l.product_line || l.product,
    worst: (l.arr_worst || 0) / 1e6,
    likely: (l.arr_likely || 0) / 1e6,
    best: (l.arr_best || 0) / 1e6,
  }));
  const prodData = (byProduct || []).map((p) => ({ name: p.product, likely: (p.arr_likely || 0) / 1e6 }));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>By Product Line</div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={lineData} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tickFormatter={(v) => `$${v.toFixed(1)}M`} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ fill: '#f1f5f9', fontSize: 10 }} axisLine={false} tickLine={false} width={44} />
            <Tooltip content={<DarkTip />} />
            <Bar dataKey="worst" name="Risk Floor" fill="#ef4444" opacity={0.5} radius={[0, 3, 3, 0]} barSize={14} isAnimationActive />
            <Bar dataKey="likely" name="Most Likely" fill="#ffffff" opacity={0.9} radius={[0, 3, 3, 0]} barSize={14} isAnimationActive />
            <Bar dataKey="best" name="Stretch Case" fill="#10b981" opacity={0.5} radius={[0, 3, 3, 0]} barSize={14} isAnimationActive />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>By Product (Most Likely)</div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={prodData} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tickFormatter={(v) => `$${v.toFixed(1)}M`} tick={{ fill: '#475569', fontSize: 9 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ fill: '#f1f5f9', fontSize: 9 }} axisLine={false} tickLine={false} width={72} />
            <Tooltip content={<DarkTip />} />
            <Bar dataKey="likely" name="Most Likely" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={12} isAnimationActive />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default ByProductChart;
