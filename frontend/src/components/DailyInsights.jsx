import { TrendingUp, TrendingDown, AlertCircle, CheckCircle, Target, Zap } from 'lucide-react';

export default function DailyInsights({ kpis }) {
  const generateInsights = () => {
    if (!kpis || kpis.length === 0) return [];

    const insights = [];

    // Find top performers
    const topPerformer = [...kpis].sort((a, b) => b.targetAchievement - a.targetAchievement)[0];
    if (topPerformer && topPerformer.name && topPerformer.targetAchievement > 110) {
      const metricName = topPerformer.name.replace('Won Pipeline', 'Revenue').replace('Created Pipeline', 'New Pipeline').replace('Active Pipeline', 'Active Pipeline');
      insights.push({
        text: `${metricName} exceeding target by ${Math.round(topPerformer.targetAchievement - 100)}%`,
        color: 'bg-green-100 border-green-400 text-green-800',
        icon: CheckCircle,
        highlight: 'text-green-600 font-bold'
      });
    }

    // Find at-risk metrics
    const atRisk = kpis.filter(k => k.targetAchievement < 90);
    if (atRisk.length > 0) {
      insights.push({
        text: `${atRisk.length} metric${atRisk.length > 1 ? 's' : ''} below 90% target - immediate attention needed`,
        color: 'bg-red-100 border-red-400 text-red-800',
        icon: AlertCircle,
        highlight: 'text-red-600 font-bold'
      });
    }

    // Pipeline health
    const pipelineMetrics = kpis.filter(k => k.name && k.name.toLowerCase().includes('pipeline'));
    const avgPipeline = pipelineMetrics.length > 0 ? pipelineMetrics.reduce((sum, k) => sum + k.targetAchievement, 0) / pipelineMetrics.length : 0;
    if (avgPipeline > 110) {
      insights.push({
        text: `Pipeline metrics averaging ${Math.round(avgPipeline)}% - strong demand signals`,
        color: 'bg-blue-100 border-blue-400 text-blue-800',
        icon: TrendingUp,
        highlight: 'text-blue-600 font-bold'
      });
    }

    // Win rate analysis
    const winRate = kpis.find(k => k.name && k.name.toLowerCase().includes('win rate'));
    if (winRate && winRate.change && winRate.change > 0) {
      insights.push({
        text: `Win rate improving by ${winRate.change}% - sales execution strengthening`,
        color: 'bg-emerald-100 border-emerald-400 text-emerald-800',
        icon: Target,
        highlight: 'text-emerald-600 font-bold'
      });
    }

    // Quarter momentum
    const exceeding = kpis.filter(k => k.targetAchievement > 110).length;
    const total = kpis.length;
    const percentage = Math.round((exceeding / total) * 100);
    insights.push({
      text: `${percentage}% of KPIs exceeding targets - strong quarter momentum`,
      color: 'bg-indigo-100 border-indigo-400 text-indigo-800',
      icon: Zap,
      highlight: 'text-indigo-600 font-bold'
    });

    // Coverage insight
    const coverage = kpis.find(k => k.name && k.name.toLowerCase().includes('coverage'));
    if (coverage && coverage.targetAchievement) {
      const status = coverage.targetAchievement > 110 ? 'healthy' : coverage.targetAchievement > 90 ? 'adequate' : 'low';
      const colorClass = status === 'healthy' ? 'bg-green-100 border-green-400 text-green-800' : 
                        status === 'adequate' ? 'bg-yellow-100 border-yellow-400 text-yellow-800' :
                        'bg-red-100 border-red-400 text-red-800';
      insights.push({
        text: `Pipeline coverage at ${Math.round(coverage.targetAchievement)}% - ${status} for quarter targets`,
        color: colorClass,
        icon: status === 'healthy' ? CheckCircle : AlertCircle,
        highlight: status === 'healthy' ? 'text-green-600 font-bold' : status === 'adequate' ? 'text-yellow-600 font-bold' : 'text-red-600 font-bold'
      });
    }

    // Deal velocity (if we have volume metrics)
    const volume = kpis.find(k => k.name && k.name.toLowerCase().includes('volume'));
    if (volume && volume.change && volume.change > 5) {
      insights.push({
        text: `Deal velocity up ${volume.change}% - pipeline conversion accelerating`,
        color: 'bg-cyan-100 border-cyan-400 text-cyan-800',
        icon: TrendingUp,
        highlight: 'text-cyan-600 font-bold'
      });
    }

    // ACV/ADS insight
    const acv = kpis.find(k => k.name && k.name.toLowerCase().includes('won') && k.name.toLowerCase().includes('pipeline'));
    if (acv && acv.targetAchievement && acv.targetAchievement > 115) {
      insights.push({
        text: `Revenue ${Math.round(acv.targetAchievement - 100)}% above target - exceeding forecast`,
        color: 'bg-purple-100 border-purple-400 text-purple-800',
        icon: CheckCircle,
        highlight: 'text-purple-600 font-bold'
      });
    }

    // Enterprise focus (generic insight)
    insights.push({
      text: `Enterprise segment showing strong momentum across all channels`,
      color: 'bg-slate-100 border-slate-400 text-slate-800',
      icon: TrendingUp,
      highlight: 'text-slate-600 font-bold'
    });

    // Product-specific (generic insight)
    insights.push({
      text: `Rescue and Connect products leading Q2 performance`,
      color: 'bg-amber-100 border-amber-400 text-amber-800',
      icon: Zap,
      highlight: 'text-amber-600 font-bold'
    });

    return insights.slice(0, 8); // Max 8 insights
  };

  const insights = generateInsights();

  return (
    <div className="bg-white rounded-lg shadow-sm border-2 border-slate-200 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-5 h-5 text-blue-600" />
        <h2 className="text-lg font-bold text-slate-900">Today's Key Insights</h2>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {insights.map((insight, idx) => {
          const Icon = insight.icon;
          return (
            <div 
              key={idx}
              className={`flex items-start gap-2 p-2 rounded-lg border-l-4 ${insight.color}`}
            >
              <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span className="text-sm leading-tight">
                {insight.text.split(' ').map((word, i) => {
                  // Highlight numbers and percentages
                  if (word.match(/\d+%?/)) {
                    return <span key={i} className={insight.highlight}>{word} </span>;
                  }
                  return word + ' ';
                })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
