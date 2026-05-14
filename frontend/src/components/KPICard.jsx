import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

const KPICard = ({ kpi, loading }) => {
  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6 animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-24 mb-4"></div>
        <div className="h-8 bg-gray-200 rounded w-32 mb-2"></div>
        <div className="h-4 bg-gray-200 rounded w-20"></div>
      </div>
    );
  }

  const {
    name,
    value,
    target,
    previous_value,
    format = 'number',
    unit = '',
  } = kpi;

  // Calculate percentage change
  const changeValue = previous_value ? ((value - previous_value) / previous_value) * 100 : 0;
  const isPositive = changeValue > 0;
  const isNeutral = Math.abs(changeValue) < 0.1;

  // Calculate target achievement
  const targetAchievement = target ? (value / target) * 100 : null;
  const metTarget = targetAchievement >= 100;

  // Format value
  const formatValue = (val) => {
    if (format === 'currency') {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(val);
    } else if (format === 'percentage') {
      return `${val.toFixed(1)}%`;
    } else {
      return new Intl.NumberFormat('en-US').format(val);
    }
  };

  // Get trend icon and color
  const getTrendIcon = () => {
    if (isNeutral) return <Minus className="w-4 h-4" />;
    return isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />;
  };

  const trendColor = isNeutral ? 'text-gray-500' : isPositive ? 'text-green-600' : 'text-red-600';

  return (
    <div className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow p-6">
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-medium text-gray-600">{name}</h3>
        <div className={`flex items-center ${trendColor}`}>
          {getTrendIcon()}
        </div>
      </div>

      <div className="space-y-2">
        <div className="text-3xl font-bold text-gray-900">
          {formatValue(value)}
          {unit && <span className="text-lg font-normal text-gray-500 ml-1">{unit}</span>}
        </div>

        {target && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">Target: {formatValue(target)}</span>
            <span className={`font-medium ${metTarget ? 'text-green-600' : 'text-orange-600'}`}>
              {targetAchievement.toFixed(0)}%
            </span>
          </div>
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
                  metTarget ? 'bg-green-500' : 'bg-blue-500'
                }`}
                style={{ width: `${Math.min(targetAchievement, 100)}%` }}
              ></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default KPICard;
