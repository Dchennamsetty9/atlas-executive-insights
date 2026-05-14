import { BarChart3, TrendingUp } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';

export default function GraphOfTheDay({ kpis }) {
  if (!kpis || kpis.length === 0) {
    return (
      <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg shadow-sm border-2 border-blue-200 p-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-600" />
          <h2 className="text-lg font-bold text-slate-900">Performance Snapshot</h2>
        </div>
        <p className="text-sm text-slate-600 mt-2">Loading performance data...</p>
      </div>
    );
  }

  // Find top 5 performers
  const topPerformers = [...kpis]
    .filter(kpi => kpi.name && kpi.targetAchievement) // Filter out invalid KPIs
    .sort((a, b) => b.targetAchievement - a.targetAchievement)
    .slice(0, 5)
    .map(kpi => ({
      name: (kpi.name || 'Unknown').replace('Won Pipeline', 'Won ACV')
                   .replace('Created Pipeline', 'Created')
                   .replace('Active Pipeline', 'Active')
                   .replace('Opps Created', 'Opps'),
      achievement: Math.round(kpi.targetAchievement || 0),
      target: 100,
      status: kpi.targetAchievement > 110 ? 'Exceeding' : kpi.targetAchievement > 90 ? 'On Track' : 'At Risk'
    }));

  if (topPerformers.length === 0) {
    return (
      <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg shadow-sm border-2 border-blue-200 p-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-600" />
          <h2 className="text-lg font-bold text-slate-900">Performance Snapshot</h2>
        </div>
        <p className="text-sm text-slate-600 mt-2">Loading performance data...</p>
      </div>
    );
  }

  const topMetric = topPerformers[0];

  return (
    <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg shadow-sm border-2 border-blue-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-600" />
          <h2 className="text-lg font-bold text-slate-900">Performance Snapshot</h2>
        </div>
        <div className="flex items-center gap-2 bg-green-100 px-3 py-1 rounded-full border-2 border-green-400">
          <TrendingUp className="w-4 h-4 text-green-700" />
          <span className="text-sm font-bold text-green-800">
            {topMetric.name}: {topMetric.achievement}%
          </span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={topPerformers} margin={{ top: 10, right: 10, left: -20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis 
            dataKey="name" 
            tick={{ fill: '#475569', fontSize: 11 }}
            axisLine={{ stroke: '#cbd5e1' }}
          />
          <YAxis 
            tick={{ fill: '#475569', fontSize: 11 }}
            axisLine={{ stroke: '#cbd5e1' }}
            domain={[0, 130]}
          />
          <Tooltip 
            contentStyle={{ 
              backgroundColor: '#fff', 
              border: '2px solid #cbd5e1',
              borderRadius: '8px',
              fontSize: '12px'
            }}
            formatter={(value) => [`${value}%`, 'Achievement']}
          />
          <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: 'Target', position: 'right', fill: '#64748b', fontSize: 10 }} />
          <ReferenceLine y={110} stroke="#22c55e" strokeDasharray="3 3" strokeOpacity={0.5} />
          <ReferenceLine y={90} stroke="#ef4444" strokeDasharray="3 3" strokeOpacity={0.5} />
          <Bar 
            dataKey="achievement" 
            fill="#3b82f6"
            radius={[6, 6, 0, 0]}
            label={{ position: 'top', fill: '#1e40af', fontSize: 11, fontWeight: 'bold' }}
          />
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-2 text-xs text-slate-600 flex items-center justify-between">
        <span>🟢 Above 110% target | 🔵 90-110% on target | 🔴 Below 90% at risk</span>
        <span className="font-semibold">Top {topPerformers.length} KPIs</span>
      </div>
    </div>
  );
}
