import { Sparkles, AlertCircle, TrendingUp, Users } from 'lucide-react'

const iconMap = {
  'alert': AlertCircle,
  'opportunity': TrendingUp,
  'recommendation': Sparkles,
  'observation': Users
}

const colorMap = {
  'alert': {
    bg: 'bg-red-50',
    icon: 'text-red-600',
    border: 'border-red-100'
  },
  'opportunity': {
    bg: 'bg-blue-50',
    icon: 'text-blue-600',
    border: 'border-blue-100'
  },
  'recommendation': {
    bg: 'bg-purple-50',
    icon: 'text-purple-600',
    border: 'border-purple-100'
  },
  'observation': {
    bg: 'bg-gray-50',
    icon: 'text-gray-600',
    border: 'border-gray-100'
  }
}

function InsightCard({ insight }) {
  const Icon = iconMap[insight.type] || Sparkles
  const colors = colorMap[insight.type] || colorMap.observation
  
  return (
    <div className={`p-4 rounded-lg border ${colors.bg} ${colors.border}`}>
      <div className="flex items-start space-x-3">
        <div className={`p-2 rounded-lg bg-white ${colors.icon}`}>
          <Icon className="w-5 h-5" />
        </div>
        
        <div className="flex-1">
          <h3 className={`font-medium ${colors.icon}`}>{insight.title}</h3>
          <p className="text-sm text-gray-700 mt-1">{insight.description}</p>
          
          <div className="flex items-center justify-between mt-2">
            <span className="text-xs font-medium text-gray-500">
              Impact: {insight.impact}
            </span>
            {insight.confidence && (
              <span className="text-xs text-gray-500">
                {Math.round(insight.confidence * 100)}% confidence
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function AIInsights({ insights }) {
  // Mock data if no insights provided
  const displayInsights = insights?.length > 0 ? insights : [
    {
      id: '1',
      type: 'alert',
      title: 'Revenue declined 12% in Q3',
      description: 'Revenue dropped mainly due to lower performance in the West region.',
      impact: 'High',
      confidence: 0.92
    },
    {
      id: '2',
      type: 'opportunity',
      title: 'Focus on improving conversion',
      description: 'Conversion rates in the West region show potential for improvement with targeted marketing spend in high-performing channels.',
      impact: 'Medium',
      confidence: 0.85
    }
  ]

  return (
    <div className="card">
      <div className="flex items-center space-x-2 mb-4">
        <Sparkles className="w-5 h-5 text-blue-600" />
        <h2 className="text-lg font-semibold">B. AI Insight</h2>
      </div>
      
      <div className="space-y-4">
        {displayInsights.map(insight => (
          <InsightCard key={insight.id} insight={insight} />
        ))}
      </div>
    </div>
  )
}

export default AIInsights
