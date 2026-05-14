import { TrendingUp, TrendingDown, DollarSign, Target, Percent, Activity } from 'lucide-react'

const iconMap = {
  'dollar': DollarSign,
  'trending-up': TrendingUp,
  'percent': Percent,
  'target': Target,
  'activity': Activity
}

function KPICard({ kpi }) {
  const Icon = iconMap[kpi.icon] || Activity
  const isPositive = kpi.change_direction === 'up'
  const isNegative = kpi.change_direction === 'down'
  
  return (
    <div className="metric-card">
      <div className="flex items-start justify-between mb-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
          isPositive ? 'bg-green-100' : isNegative ? 'bg-red-100' : 'bg-gray-100'
        }`}>
          <Icon className={`w-5 h-5 ${
            isPositive ? 'text-green-600' : isNegative ? 'text-red-600' : 'text-gray-600'
          }`} />
        </div>
        
        {/* Trend indicator */}
        <div className={`flex items-center space-x-1 text-sm font-medium ${
          isPositive ? 'text-green-600' : isNegative ? 'text-red-600' : 'text-gray-600'
        }`}>
          {isPositive && <TrendingUp className="w-4 h-4" />}
          {isNegative && <TrendingDown className="w-4 h-4" />}
          <span>{Math.abs(kpi.change_percent)}%</span>
        </div>
      </div>
      
      <div className="mb-1">
        <h3 className="text-sm font-medium text-gray-600">{kpi.title}</h3>
      </div>
      
      <div className="flex items-baseline space-x-2 mb-2">
        <span className="text-3xl font-bold text-gray-900">
          {kpi.unit === '$' && '$'}
          {kpi.value}
          {kpi.unit === 'M' && 'M'}
          {kpi.unit === '%' && '%'}
        </span>
      </div>
      
      <div className="text-xs text-gray-500">{kpi.vs_last_period}</div>
      
      {/* Mini sparkline */}
      <div className="mt-3 h-8">
        <svg width="100%" height="100%" className="sparkline">
          <polyline
            fill="none"
            stroke={isPositive ? '#10b981' : isNegative ? '#ef4444' : '#6b7280'}
            strokeWidth="2"
            points={kpi.trend_data.map((val, idx) => {
              const x = (idx / (kpi.trend_data.length - 1)) * 100
              const min = Math.min(...kpi.trend_data)
              const max = Math.max(...kpi.trend_data)
              const y = 100 - ((val - min) / (max - min)) * 100
              return `${x},${y}`
            }).join(' ')}
          />
        </svg>
      </div>
    </div>
  )
}

function KPICards({ kpis }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
      {kpis.map(kpi => (
        <KPICard key={kpi.id} kpi={kpi} />
      ))}
    </div>
  )
}

export default KPICards
