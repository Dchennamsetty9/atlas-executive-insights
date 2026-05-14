import { TrendingUp, TrendingDown, AlertTriangle, CheckCircle, Lightbulb, Target, Brain } from 'lucide-react';

const ForecastInsights = ({ insights, loading }) => {
  if (loading) {
    return (
      <div className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-lg border border-purple-200 p-6">
        <div className="animate-pulse">
          <div className="h-5 bg-gray-200 rounded w-48 mb-4"></div>
          <div className="h-4 bg-gray-200 rounded w-full mb-2"></div>
          <div className="h-4 bg-gray-200 rounded w-3/4"></div>
        </div>
      </div>
    );
  }

  if (!insights) return null;

  const getTrendIcon = (trend) => {
    switch (trend) {
      case 'accelerating':
        return <TrendingUp className="w-5 h-5 text-green-600" />;
      case 'decelerating':
        return <TrendingDown className="w-5 h-5 text-red-600" />;
      default:
        return <Target className="w-5 h-5 text-blue-600" />;
    }
  };

  const getRiskColor = (risk) => {
    switch (risk) {
      case 'low':
        return 'text-green-600 bg-green-50';
      case 'medium':
        return 'text-yellow-600 bg-yellow-50';
      case 'high':
        return 'text-red-600 bg-red-50';
      default:
        return 'text-gray-600 bg-gray-50';
    }
  };

  const getConfidenceColor = (confidence) => {
    if (confidence >= 90) return 'text-green-600';
    if (confidence >= 75) return 'text-blue-600';
    if (confidence >= 60) return 'text-yellow-600';
    return 'text-red-600';
  };

  // Calculate financial impact
  const calcFinancialImpact = () => {
    // Demo calculation - in production, use actual forecast numbers
    const currentARR = 61400000;
    const forecastGrowth = insights.trend === 'accelerating' ? 0.08 : insights.trend === 'stable' ? 0.035 : -0.02;
    const bestCase = currentARR * (1 + forecastGrowth * 1.5);
    const worstCase = currentARR * (1 + forecastGrowth * 0.5);
    const upside = bestCase - currentARR;
    const downside = currentARR - worstCase;
    return { upside, downside, bestCase, worstCase };
  };

  const impact = calcFinancialImpact();

  return (
    <div className="bg-gradient-to-br from-slate-50 to-blue-50 rounded-lg border-2 border-slate-300 p-6 shadow-lg">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-6 h-6 text-slate-700" />
          <h3 className="text-lg font-bold text-gray-900">Forecast Intelligence</h3>
        </div>
        <div className="flex gap-3">
          <div className="text-right">
            <div className="text-xs text-green-700 font-semibold">UPSIDE</div>
            <div className="text-sm font-bold text-green-600">${(impact.upside / 1000000).toFixed(1)}M</div>
          </div>
          <div className="text-right">
            <div className="text-xs text-red-700 font-semibold">DOWNSIDE</div>
            <div className="text-sm font-bold text-red-600">${(impact.downside / 1000000).toFixed(1)}M</div>
          </div>
        </div>
      </div>

      {/* Executive Summary */}
      <div className="bg-white rounded-lg p-4 mb-4 border-2 border-slate-200 shadow-sm">
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-2">
              {getTrendIcon(insights.trend)}
              <span className="text-sm font-bold text-gray-900 uppercase tracking-wide">
                {insights.trend} Trend
              </span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${getRiskColor(insights.risk)}`}>
                {insights.risk.toUpperCase()} RISK
              </span>
            </div>
            <p className="text-gray-800 font-medium leading-relaxed">{insights.summary}</p>
          </div>
          <div className="text-right ml-4">
            <div className="text-xs text-gray-600 font-semibold mb-1">MODEL CONFIDENCE</div>
            <div className={`text-2xl font-bold ${getConfidenceColor(insights.confidence)}`}>
              {insights.confidence}%
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-gray-200">
          <div className="bg-green-50 rounded p-2">
            <div className="text-xs text-green-700 font-semibold mb-1">BEST CASE (90 days)</div>
            <div className="text-lg font-bold text-green-600">${(impact.bestCase / 1000000).toFixed(1)}M</div>
          </div>
          <div className="bg-red-50 rounded p-2">
            <div className="text-xs text-red-700 font-semibold mb-1">WORST CASE (90 days)</div>
            <div className="text-lg font-bold text-red-600">${(impact.worstCase / 1000000).toFixed(1)}M</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Key Drivers */}
        <div className="bg-white rounded-lg p-4 border-2 border-slate-200 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle className="w-5 h-5 text-green-600" />
            <h4 className="font-bold text-gray-900 uppercase text-sm tracking-wide">Key Drivers</h4>
          </div>
          <ul className="space-y-2">
            {insights.drivers.map((driver, idx) => (
              <li key={idx} className="text-sm text-gray-700 flex items-start gap-2">
                <span className="text-purple-600 mt-1">•</span>
                <span>{driver}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Recommendations */}
        <div className="bg-white rounded-lg p-4 border-2 border-slate-200 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <Target className="w-5 h-5 text-blue-600" />
            <h4 className="font-bold text-gray-900 uppercase text-sm tracking-wide">Executive Actions</h4>
          </div>
          <ul className="space-y-2">
            {insights.recommendations.map((rec, idx) => (
              <li key={idx} className="text-sm text-gray-700 flex items-start gap-2">
                <span className="text-purple-600 mt-1">{idx + 1}.</span>
                <span>{rec}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Risks & Opportunities */}
      {(insights.risks?.length > 0 || insights.opportunities?.length > 0) && (
        <div className="grid grid-cols-2 gap-4 mt-4">
          {insights.risks?.length > 0 && (
            <div className="bg-red-50 rounded-lg p-4 border border-red-200">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-red-600" />
                <h4 className="font-semibold text-red-900 text-sm">Downside Risks</h4>
              </div>
              <ul className="space-y-1">
                {insights.risks.map((risk, idx) => (
                  <li key={idx} className="text-xs text-red-800">• {risk}</li>
                ))}
              </ul>
            </div>
          )}

          {insights.opportunities?.length > 0 && (
            <div className="bg-green-50 rounded-lg p-4 border border-green-200">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-4 h-4 text-green-600" />
                <h4 className="font-semibold text-green-900 text-sm">Upside Opportunities</h4>
              </div>
              <ul className="space-y-1">
                {insights.opportunities.map((opp, idx) => (
                  <li key={idx} className="text-xs text-green-800">• {opp}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ForecastInsights;
