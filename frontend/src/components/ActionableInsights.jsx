import { AlertTriangle, TrendingUp, Zap, Mail, Phone, Calendar, Target, ArrowRight } from 'lucide-react';

const ActionableInsights = ({ alerts }) => {
  if (!alerts || alerts.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <div className="animate-pulse">
          <div className="h-5 bg-gray-200 rounded w-32 mb-3"></div>
          <div className="h-3 bg-gray-200 rounded w-full mb-2"></div>
          <div className="h-3 bg-gray-200 rounded w-3/4"></div>
        </div>
      </div>
    );
  }

  const getActionIcon = (type) => {
    switch (type) {
      case 'email':
        return <Mail className="w-4 h-4" />;
      case 'call':
        return <Phone className="w-4 h-4" />;
      case 'meeting':
        return <Calendar className="w-4 h-4" />;
      case 'review':
        return <Target className="w-4 h-4" />;
      default:
        return <Zap className="w-4 h-4" />;
    }
  };

  const getPriorityColor = (priority) => {
    switch (priority) {
      case 'critical':
        return 'border-l-4 border-red-500 bg-red-50';
      case 'high':
        return 'border-l-4 border-orange-500 bg-orange-50';
      case 'medium':
        return 'border-l-4 border-yellow-500 bg-yellow-50';
      default:
        return 'border-l-4 border-blue-500 bg-blue-50';
    }
  };

  const getPriorityDot = (priority) => {
    const colors = {
      critical: 'bg-red-500',
      high: 'bg-orange-500',
      medium: 'bg-yellow-500',
      low: 'bg-blue-500',
    };
    return <div className={`w-2 h-2 rounded-full ${colors[priority]}`} />;
  };

  const criticalAlerts = alerts.filter(a => a.priority === 'critical' || a.priority === 'high');
  const otherAlerts = alerts.filter(a => a.priority !== 'critical' && a.priority !== 'high');

  return (
    <div className="space-y-4">
      {/* Sidebar Header */}
      <div className="bg-gradient-to-br from-blue-600 to-purple-600 rounded-lg p-4 text-white">
        <div className="flex items-center gap-2 mb-1">
          <Zap className="w-5 h-5" />
          <h2 className="text-lg font-bold">Action Center</h2>
        </div>
        <p className="text-sm text-blue-100">
          {criticalAlerts.length} critical, {otherAlerts.length} watching
        </p>
      </div>

      {/* Critical Alerts */}
      {criticalAlerts.length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-5 h-5 text-red-600" />
            <h3 className="text-sm font-bold text-gray-900">Needs Attention</h3>
          </div>

          <div className="space-y-2">
            {criticalAlerts.map((alert, idx) => (
              <div
                key={idx}
                className={`${getPriorityColor(alert.priority)} rounded-lg p-3`}
              >
                <div className="flex items-start gap-2 mb-2">
                  {getPriorityDot(alert.priority)}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-gray-900 mb-1">{alert.kpi}</p>
                    <p className="text-xs text-gray-700 leading-relaxed">{alert.message}</p>
                  </div>
                </div>

                <button className="w-full mt-2 px-3 py-1.5 bg-white rounded text-xs font-semibold text-gray-900 hover:bg-gray-50 transition-colors flex items-center justify-center gap-1">
                  {getActionIcon(alert.actionType)}
                  <span>Take Action</span>
                  <ArrowRight className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Other Insights */}
      {otherAlerts.length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-5 h-5 text-blue-600" />
            <h3 className="text-sm font-bold text-gray-900">Watching</h3>
          </div>

          <div className="space-y-2">
            {otherAlerts.map((alert, idx) => (
              <div
                key={idx}
                className={`${getPriorityColor(alert.priority)} rounded-lg p-3`}
              >
                <div className="flex items-start gap-2">
                  {getPriorityDot(alert.priority)}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-gray-900 mb-1">{alert.kpi}</p>
                    <p className="text-xs text-gray-600 leading-relaxed">{alert.message}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ActionableInsights;
