import { useState } from 'react';
import { TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp, AlertTriangle, CheckCircle, Info, Lightbulb, Users, MapPin, Package, Brain } from 'lucide-react';

const EnhancedKPICard = ({ kpi, insights, loading, compact = false }) => {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <div className={`bg-white rounded-lg shadow p-${compact ? '3' : '6'} animate-pulse`}>
        <div className={`h-${compact ? '3' : '4'} bg-gray-200 rounded w-${compact ? '16' : '24'} mb-${compact ? '2' : '4'}`}></div>
        <div className={`h-${compact ? '6' : '8'} bg-gray-200 rounded w-${compact ? '20' : '32'} mb-2`}></div>
        <div className={`h-${compact ? '3' : '4'} bg-gray-200 rounded w-${compact ? '12' : '20'}`}></div>
      </div>
    );
  }

  const {
    title,
    value,
    target,
    previous_value,
    unit = '',
  } = kpi;

  // Determine if this is a currency KPI (check for $ in unit)
  const isCurrency = unit === '$' || unit.includes('$');
  const isPercentage = unit === '%' || unit.includes('%');

  // Calculate metrics
  const changeValue = previous_value ? ((value - previous_value) / previous_value) * 100 : 0;
  const isPositive = changeValue > 0;
  const isNeutral = Math.abs(changeValue) < 0.1;
  const targetAchievement = target ? (value / target) * 100 : null;
  const metTarget = targetAchievement >= 100;
  const atRisk = targetAchievement && targetAchievement < 90;
  const exceeding = targetAchievement && targetAchievement > 110;

  // Calculate dollar impact (for currency KPIs)
  const dollarImpact = isCurrency && target ? value - target : null;
  const impactLabel = dollarImpact > 0 ? 'Above Target' : dollarImpact < 0 ? 'Below Target' : 'On Target';
  const impactColor = dollarImpact > 0 ? 'text-green-600' : dollarImpact < 0 ? 'text-red-600' : 'text-blue-600';

  // Format value
  const formatValue = (val) => {
    if (isCurrency) {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(val);
    } else if (isPercentage) {
      return `${val.toFixed(1)}%`;
    } else {
      return new Intl.NumberFormat('en-US').format(val);
    }
  };

  // Format dollar impact (always show decimal for values < 1M)
  const formatDollarImpact = (val) => {
    const absVal = Math.abs(val);
    if (absVal < 1) {
      // Values < $1M: show with 1 decimal place (e.g., "$0.5M" for $500K)
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }).format(val) + 'M';
    } else {
      // Values >= $1M: show without decimals (e.g., "$2M")
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(val) + 'M';
    }
  };

  // Get status icon and message
  const getStatusInfo = () => {
    if (exceeding) {
      return {
        icon: <CheckCircle className="w-5 h-5 text-green-600" />,
        message: 'Exceeding Target',
        color: 'bg-green-50 border-green-200 text-green-800'
      };
    } else if (metTarget) {
      return {
        icon: <CheckCircle className="w-5 h-5 text-blue-600" />,
        message: 'On Target',
        color: 'bg-blue-50 border-blue-200 text-blue-800'
      };
    } else if (atRisk) {
      return {
        icon: <AlertTriangle className="w-5 h-5 text-red-600" />,
        message: 'Action Required',
        color: 'bg-red-50 border-red-200 text-red-800'
      };
    } else {
      return {
        icon: <Info className="w-5 h-5 text-orange-600" />,
        message: 'Watch Closely',
        color: 'bg-orange-50 border-orange-200 text-orange-800'
      };
    }
  };

  const statusInfo = getStatusInfo();
  const trendColor = isNeutral ? 'text-gray-500' : isPositive ? 'text-green-600' : 'text-red-600';
  const getTrendIcon = () => {
    if (isNeutral) return <Minus className="w-4 h-4" />;
    return isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />;
  };

  return (
    <div className={`bg-white rounded-lg shadow hover:shadow-lg transition-all ${expanded ? (compact ? 'col-span-2' : 'col-span-2') : ''}`}>
      {/* Main KPI Display */}
      <div className={compact ? 'p-3' : 'p-6'}>
        <div className={`flex justify-between items-start ${compact ? 'mb-2' : 'mb-4'}`}>
          <div className="flex-1">
            <h3 className={`${compact ? 'text-sm' : 'text-base'} font-bold text-gray-900 mb-2`}>{title}</h3>
            <div className={`inline-flex items-center gap-1 ${compact ? 'px-2 py-0.5' : 'px-3 py-1'} rounded-full border ${compact ? 'text-xs' : 'text-xs'} font-medium ${statusInfo.color}`}>
              {!compact && statusInfo.icon}
              {statusInfo.message}
            </div>
          </div>
          <div className={`flex items-center ${trendColor}`}>
            {getTrendIcon()}
          </div>
        </div>

        <div className={compact ? 'space-y-2' : 'space-y-3'}>
          <div className={`${compact ? 'text-xl' : 'text-3xl'} font-bold text-gray-900`}>
            {formatValue(value)}
            {unit && <span className={`${compact ? 'text-xs' : 'text-lg'} font-normal text-gray-500 ml-1`}>{unit}</span>}
          </div>

          {target && (
            <>
              <div className={`flex items-center justify-between ${compact ? 'text-xs' : 'text-sm'}`}>
                <span className="text-gray-600">Target: {formatValue(target)}</span>
                <span className={`font-medium ${metTarget ? 'text-green-600' : 'text-orange-600'}`}>
                  {targetAchievement.toFixed(0)}%
                </span>
              </div>
              
              {/* Dollar Impact for currency KPIs - Hide in compact mode if < 1M */}
              {dollarImpact !== null && Math.abs(dollarImpact) > (compact ? 0.5 : 0) && (
                <div className={`flex items-center justify-between text-sm font-bold px-3 py-2 rounded-md border-2 ${dollarImpact > 0 ? 'bg-green-50 border-green-300 text-green-700' : 'bg-red-50 border-red-300 text-red-700'}`}>
                  <span className="uppercase text-xs tracking-wide font-extrabold">{impactLabel}</span>
                  <span className="text-lg font-bold">
                    {dollarImpact > 0 ? '+' : ''}{formatDollarImpact(dollarImpact)}
                  </span>
                </div>
              )}
            </>
          )}

          {previous_value && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600">vs Previous</span>
              <span className={`font-medium ${trendColor}`}>
                {isPositive && '+'}{changeValue.toFixed(1)}%
              </span>
            </div>
          )}

          {targetAchievement && (
            <div className="mt-3">
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    exceeding ? 'bg-green-500' : metTarget ? 'bg-blue-500' : atRisk ? 'bg-red-500' : 'bg-orange-500'
                  }`}
                  style={{ width: `${Math.min(targetAchievement, 100)}%` }}
                ></div>
              </div>
            </div>
          )}

          {/* Quick Insights Preview */}
          {insights && !compact && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <div className="flex items-start gap-2 text-sm">
                <Lightbulb className="w-4 h-4 text-yellow-500 mt-0.5 flex-shrink-0" />
                <p className="text-gray-700 line-clamp-2">{insights.summary}</p>
              </div>
            </div>
          )}

          {/* Expand/Collapse Button - Show in compact mode too */}
          {insights && (
            <button
              onClick={() => setExpanded(!expanded)}
              className={`w-full ${compact ? 'mt-2' : 'mt-4'} flex items-center justify-center gap-1 ${compact ? 'px-2 py-1' : 'px-4 py-2'} ${compact ? 'text-xs' : 'text-sm'} font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg transition-colors`}
            >
              {expanded ? (
                <>
                  <ChevronUp className={`${compact ? 'w-3 h-3' : 'w-4 h-4'}`} />
                  {compact ? 'Hide' : 'Hide Details'}
                </>
            ) : (
              <>
                <ChevronDown className={`${compact ? 'w-3 h-3' : 'w-4 h-4'}`} />
                {compact ? 'Insights' : 'Show AI Insights'}
              </>
            )}
          </button>
          )}
        </div>
      </div>

      {/* Expanded Insights Section - Always show when expanded */}
      {expanded && insights && (
        <div className="border-t border-gray-200 bg-gray-50 p-6 space-y-6">
          {/* KPI Description Banner */}
          {insights.kpiDescription && (
            <div className="bg-blue-50 border-l-4 border-blue-500 rounded-lg p-4">
              <div className="flex items-start gap-3">
                <Info className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-blue-900 leading-relaxed font-medium">
                  {insights.kpiDescription}
                </p>
              </div>
            </div>
          )}

          {/* Executive Summary */}
          {insights.summary && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
              <div className="flex items-start gap-3">
                <Brain className="w-5 h-5 text-slate-600 mt-0.5 flex-shrink-0" />
                <div>
                  <h4 className="font-semibold text-gray-900 mb-2">Executive Summary</h4>
                  <p className="text-sm text-gray-700 leading-relaxed">{insights.summary}</p>
                </div>
              </div>
            </div>
          )}

          {/* Critical Actions - Executive Focus */}
          <div className="bg-gradient-to-r from-red-50 to-orange-50 border-2 border-red-200 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-5 h-5 text-red-600" />
              <h4 className="font-bold text-red-900 uppercase text-sm tracking-wide">Critical Actions Required</h4>
            </div>
            <ul className="space-y-2">
              {insights.needsAttention.map((item, idx) => (
                <li key={idx} className="text-sm text-red-900 flex items-start gap-2 font-medium">
                  <span className="text-red-600 mt-1 font-bold">►</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Demographic Breakdown - Only show if data exists */}
          {insights.demographics && insights.demographics.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-4">
                <Users className="w-5 h-5 text-blue-600" />
                <h4 className="font-semibold text-gray-900">Performance by Segment</h4>
              </div>
              <div className="space-y-3">
                {insights.demographics.map((demo, idx) => (
                  <div key={idx} className="flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-1">
                      {demo.type === 'geo' && <MapPin className="w-4 h-4 text-gray-400" />}
                      {demo.type === 'product' && <Package className="w-4 h-4 text-gray-400" />}
                      <span className="text-sm font-medium text-gray-700">{demo.segment}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="w-32 bg-gray-200 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${demo.performance >= 100 ? 'bg-green-500' : demo.performance >= 90 ? 'bg-blue-500' : 'bg-red-500'}`}
                          style={{ width: `${Math.min(demo.performance, 100)}%` }}
                        ></div>
                      </div>
                      <span className={`text-sm font-semibold w-12 text-right ${demo.performance >= 100 ? 'text-green-600' : demo.performance >= 90 ? 'text-blue-600' : 'text-red-600'}`}>
                        {demo.performance}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommended Actions */}
          {insights.actions && insights.actions.length > 0 && (
            <div className="bg-gradient-to-r from-blue-50 to-slate-50 border-2 border-blue-200 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-4">
                <Lightbulb className="w-5 h-5 text-blue-600" />
                <h4 className="font-bold text-blue-900 uppercase text-sm tracking-wide">Executive Actions</h4>
              </div>
              <div className="space-y-3">
                {insights.actions.map((action, idx) => (
                  <div key={idx} className="bg-white rounded-lg p-3 border border-blue-200">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-blue-600 text-white text-sm font-bold flex items-center justify-center">
                        {idx + 1}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center justify-between mb-1">
                          <p className="text-sm font-bold text-blue-900">{action.title}</p>
                          {action.urgency === 'high' && (
                            <span className="px-2 py-0.5 bg-red-600 text-white text-xs font-bold rounded uppercase">
                              Urgent
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-700">{action.description}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Root Cause Analysis */}
          {insights.rootCause && (
            <div className="bg-slate-100 border border-slate-300 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <Info className="w-5 h-5 text-slate-700" />
                <h4 className="font-bold text-slate-900 uppercase text-sm tracking-wide">Context & Analysis</h4>
              </div>
              <p className="text-sm text-slate-800 leading-relaxed">{insights.rootCause}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default EnhancedKPICard;
