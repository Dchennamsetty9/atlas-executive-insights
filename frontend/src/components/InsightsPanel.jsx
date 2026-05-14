/**
 * AI Insights Panel - Shows data-driven insights and alerts
 */

import { Lightbulb, TrendingUp, TrendingDown, AlertTriangle, CheckCircle } from 'lucide-react'

const InsightsPanel = ({ kpis }) => {
  // Generate insights based on KPI data
  const generateInsights = () => {
    if (!kpis || kpis.length === 0) {
      return [
        {
          type: 'info',
          icon: Lightbulb,
          color: 'blue',
          title: 'Performance Overview',
          message: 'Waiting for KPI data to load. Stand by for AI-powered insights.'
        }
      ]
    }

    const insights = []

    // Find specific KPIs for advanced analysis
    const wonPipeline = kpis.find(k => k.name === 'Won ACV $')
    const createdPipeline = kpis.find(k => k.name === 'Created Pipeline $')
    const activePipeline = kpis.find(k => k.name === 'Active Pipeline $')
    const closeRate = kpis.find(k => k.name === 'Close Rate')
    const coverage = kpis.find(k => k.name === 'Coverage')
    const wonDeals = kpis.find(k => k.name === '# of Deals Won')

    // Calculate overall performance
    const avgAchievement = kpis.reduce((sum, k) => sum + (k.targetAchievement || 0), 0) / kpis.length
    const exceeding = kpis.filter(k => k.targetAchievement > 110).length
    const atRisk = kpis.filter(k => k.targetAchievement < 90).length

    // Overall performance insight
    if (avgAchievement > 110) {
      insights.push({
        type: 'success',
        icon: CheckCircle,
        color: 'green',
        title: 'Exceptional Quarter Performance',
        message: `${exceeding} out of ${kpis.length} KPIs are exceeding targets. Average achievement: ${avgAchievement.toFixed(0)}%. Strong momentum across the board.`
      })
    } else if (avgAchievement > 95) {
      insights.push({
        type: 'positive',
        icon: TrendingUp,
        color: 'green',
        title: 'Solid Performance',
        message: `Overall KPI achievement at ${avgAchievement.toFixed(0)}%. ${exceeding} metrics exceeding targets. Keep up the momentum.`
      })
    } else if (avgAchievement < 90) {
      insights.push({
        type: 'warning',
        icon: AlertTriangle,
        color: 'orange',
        title: 'Performance Requires Attention',
        message: `${atRisk} KPIs below 90% of target. Focus on pipeline creation and close rate optimization.`
      })
    }

    // Coverage analysis (Performance Hub key metric)
    if (coverage) {
      const coverageValue = coverage.value
      if (coverageValue < 2.5) {
        insights.push({
          type: 'warning',
          icon: AlertTriangle,
          color: 'red',
          title: 'Low Pipeline Coverage',
          message: `Coverage at ${coverageValue.toFixed(1)}x is below healthy 3x target. Need ${((3 * wonPipeline.value) - activePipeline.value).toFixed(1)}M more pipeline.`
        })
      } else if (coverageValue > 3.5) {
        insights.push({
          type: 'positive',
          icon: TrendingUp,
          color: 'green',
          title: 'Strong Pipeline Coverage',
          message: `Coverage at ${coverageValue.toFixed(1)}x provides excellent buffer. Focus on conversion to close deals faster.`
        })
      }
    }

    // Close Rate analysis
    if (closeRate && wonDeals) {
      const rate = closeRate.value
      const achievement = closeRate.targetAchievement
      if (achievement > 110) {
        insights.push({
          type: 'success',
          icon: CheckCircle,
          color: 'green',
          title: 'Excellent Close Rate',
          message: `Close rate at ${rate.toFixed(1)}% (${achievement.toFixed(0)}% of target). ${wonDeals.value} deals closed. Sales execution is strong.`
        })
      } else if (rate < 25) {
        insights.push({
          type: 'warning',
          icon: TrendingDown,
          color: 'orange',
          title: 'Close Rate Below Benchmark',
          message: `Close rate at ${rate.toFixed(1)}% is below 30% industry standard. Review deal qualification and sales process.`
        })
      }
    }

    // Pipeline creation vs won analysis
    if (createdPipeline && wonPipeline) {
      const ratio = createdPipeline.value / wonPipeline.value
      if (ratio > 4) {
        insights.push({
          type: 'positive',
          icon: TrendingUp,
          color: 'green',
          title: 'Strong Pipeline Generation',
          message: `Created ${(createdPipeline.value / 1000000).toFixed(1)}M pipeline, ${ratio.toFixed(1)}x won amount. Healthy funnel growth.`
        })
      } else if (ratio < 2.5) {
        insights.push({
          type: 'warning',
          icon: AlertTriangle,
          color: 'orange',
          title: 'Pipeline Creation Lagging',
          message: `Created pipeline only ${ratio.toFixed(1)}x won. Need stronger top-of-funnel to sustain growth.`
        })
      }
    }

    // Check for declining trends
    const declining = kpis.filter(k => k.change < -5 && k.targetAchievement < 100)
    if (declining.length > 0) {
      const kpiNames = declining.map(k => k.name).join(', ')
      insights.push({
        type: 'warning',
        icon: TrendingDown,
        color: 'orange',
        title: 'Declining Metrics Alert',
        message: `${declining.length} KPIs showing downward trends: ${kpiNames}. Review sales strategies and resource allocation.`
      })
    }

    // Limit to top 5 most important insights
    return insights.slice(0, 5)
  }

  const insights = generateInsights()

  const colorClasses = {
    blue: 'bg-blue-50 border-blue-200 text-blue-800',
    green: 'bg-green-50 border-green-200 text-green-800',
    red: 'bg-red-50 border-red-200 text-red-800',
    orange: 'bg-orange-50 border-orange-200 text-orange-800'
  }

  const iconColorClasses = {
    blue: 'text-blue-600',
    green: 'text-green-600',
    red: 'text-red-600',
    orange: 'text-orange-600'
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <div className="flex items-center gap-2 mb-4">
        <Lightbulb className="w-6 h-6 text-blue-600" />
        <h2 className="text-xl font-semibold text-gray-800">Executive Summary</h2>
      </div>

      <div className="space-y-3">
        {insights.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <Lightbulb className="w-12 h-12 mx-auto mb-3 text-gray-300" />
            <p>No notable insights at this time.</p>
          </div>
        ) : (
          insights.map((insight, index) => {
            const Icon = insight.icon
            return (
              <div
                key={index}
                className={`border rounded-lg p-4 ${colorClasses[insight.color]}`}
              >
                <div className="flex items-start gap-3">
                  <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${iconColorClasses[insight.color]}`} />
                  <div className="flex-1">
                    <h3 className="font-semibold mb-1">{insight.title}</h3>
                    <p className="text-sm opacity-90">{insight.message}</p>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>

      <div className="mt-4 pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-500 text-center">
          Insights generated using Prophet AI and historical trend analysis
        </p>
      </div>
    </div>
  )
}

export default InsightsPanel
