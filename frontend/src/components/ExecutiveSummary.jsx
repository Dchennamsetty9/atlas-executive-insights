/**
 * Executive Summary - High-level overview of business performance
 */

import { TrendingUp, TrendingDown, Target, AlertCircle, Filter as FilterIcon } from 'lucide-react'

const ExecutiveSummary = ({ kpis, filters = {} }) => {
  // Calculate summary metrics
  const calculateSummary = () => {
    if (!kpis || kpis.length === 0) {
      return {
        totalMetrics: 0,
        onTrack: 0,
        atRisk: 0,
        exceeding: 0,
        avgAchievement: 0
      }
    }

    const onTrack = kpis.filter(kpi => 
      kpi.targetAchievement >= 90 && kpi.targetAchievement <= 110
    ).length

    const atRisk = kpis.filter(kpi => 
      kpi.targetAchievement < 90
    ).length

    const exceeding = kpis.filter(kpi => 
      kpi.targetAchievement > 110
    ).length

    const avgAchievement = kpis.length > 0
      ? kpis.reduce((sum, kpi) => sum + (kpi.targetAchievement || 0), 0) / kpis.length
      : 0

    return {
      totalMetrics: kpis.length,
      onTrack,
      atRisk,
      exceeding,
      avgAchievement
    }
  }

  const summary = calculateSummary()

  const getStatusColor = (value) => {
    if (value >= 100) return 'text-green-600'
    if (value >= 90) return 'text-blue-600'
    if (value >= 80) return 'text-orange-600'
    return 'text-red-600'
  }

  const getStatusBg = (value) => {
    if (value >= 100) return 'bg-green-100'
    if (value >= 90) return 'bg-blue-100'
    if (value >= 80) return 'bg-orange-100'
    return 'bg-red-100'
  }

  const getBusinessHealth = (value) => {
    if (value >= 100) return { status: 'STRONG', color: 'bg-green-600', icon: '✓' }
    if (value >= 90) return { status: 'ON TRACK', color: 'bg-blue-600', icon: '→' }
    if (value >= 80) return { status: 'CAUTION', color: 'bg-amber-600', icon: '!' }
    return { status: 'AT RISK', color: 'bg-red-600', icon: '✕' }
  }

  const health = getBusinessHealth(summary.avgAchievement)

  // Check if filters are applied
  const hasFilters = filters && (filters.geo !== 'All' || filters.channel !== 'All' || filters.product !== 'All')
  
  const getFilterContext = () => {
    if (!hasFilters) return null
    const parts = []
    if (filters.geo !== 'All') parts.push(filters.geo)
    if (filters.channel !== 'All') parts.push(filters.channel)
    if (filters.product !== 'All') parts.push(filters.product)
    return parts.join(' • ')
  }

  return (
    <div className="bg-gradient-to-br from-slate-800 to-slate-900 rounded-lg shadow-xl p-6 text-white border border-slate-700">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-2xl font-bold">Business Performance</h1>
            <span className={`${health.color} text-white px-3 py-1 rounded-full text-sm font-bold`}>
              {health.icon} {health.status}
            </span>
          </div>
          <p className="text-slate-300 text-sm">
            Quarter-to-date performance vs. targets
            {hasFilters && (
              <span className="ml-3 inline-flex items-center gap-1.5 px-2.5 py-0.5 bg-blue-500/20 text-blue-300 border border-blue-400 rounded-full text-xs font-bold">
                <FilterIcon className="w-3 h-3" />
                {getFilterContext()}
              </span>
            )}
          </p>
        </div>
        <div className="text-right">
          <div className="text-4xl font-bold text-white mb-1">{summary.avgAchievement.toFixed(0)}%</div>
          <div className="text-xs text-slate-400 uppercase tracking-wide">Target Achievement</div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Total Metrics */}
        <div className="bg-white/10 backdrop-blur rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-5 h-5" />
            <span className="text-sm font-medium">Total Metrics</span>
          </div>
          <div className="text-3xl font-bold">{summary.totalMetrics}</div>
        </div>

        {/* On Track */}
        <div className="bg-white/10 backdrop-blur rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-5 h-5 text-green-300" />
            <span className="text-sm font-medium">On Track</span>
          </div>
          <div className="text-3xl font-bold text-green-300">{summary.onTrack}</div>
          <div className="text-xs text-white/70 mt-1">90-110% of target</div>
        </div>

        {/* Exceeding */}
        <div className="bg-white/10 backdrop-blur rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-5 h-5 text-emerald-300" />
            <span className="text-sm font-medium">Exceeding</span>
          </div>
          <div className="text-3xl font-bold text-emerald-300">{summary.exceeding}</div>
          <div className="text-xs text-white/70 mt-1">&gt;110% of target</div>
        </div>

        {/* At Risk */}
        <div className="bg-white/10 backdrop-blur rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="w-5 h-5 text-red-300" />
            <span className="text-sm font-medium">At Risk</span>
          </div>
          <div className="text-3xl font-bold text-red-300">{summary.atRisk}</div>
          <div className="text-xs text-white/70 mt-1">&lt;90% of target</div>
        </div>
      </div>

      {summary.atRisk > 0 && (
        <div className="mt-4 bg-red-500/20 border border-red-300/30 rounded-lg p-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-red-300" />
            <span className="text-sm font-medium">
              {summary.atRisk} metric{summary.atRisk > 1 ? 's' : ''} need{summary.atRisk === 1 ? 's' : ''} immediate attention
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

export default ExecutiveSummary
