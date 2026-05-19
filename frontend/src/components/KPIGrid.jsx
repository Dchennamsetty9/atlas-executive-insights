import { useState, useEffect } from 'react';
import KPICard from './KPICard';
import { apiService } from '../services/api';

const KPIGrid = ({ onKpisLoaded }) => {
  const [kpis, setKpis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchKPIs();
  }, []);

  useEffect(() => {
    // Notify parent when KPIs are loaded
    if (kpis.length > 0 && onKpisLoaded) {
      onKpisLoaded(kpis);
    }
  }, [kpis, onKpisLoaded]);

  const fetchKPIs = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getKPIs();
      
      // Backend already returns correctly formatted KPI data
      // Calculate target achievement for Executive Summary
      const transformedKPIs = data.map(kpi => ({
        name: kpi.title,
        value: kpi.value,
        target: kpi.target || 0,
        targetAchievement: kpi.target > 0 ? (kpi.value / kpi.target * 100) : 100,
        change: kpi.change_percent,
        trend: kpi.change_direction,
        trendData: kpi.trend_data || [],
        unit: kpi.unit,
        icon: kpi.icon
      }));
      
      setKpis(transformedKPIs);
      
      // Notify parent component (App.jsx) so ExecutiveSummary can update
      if (onKpisLoaded) {
        onKpisLoaded(transformedKPIs);
      }
    } catch (err) {
      console.error('Error fetching KPIs:', err);
      setError('Failed to load KPIs. Using demo data.');
      // Use demo data on error
      setKpis(getDemoKPIs());
    } finally {
      setLoading(false);
    }
  };

  const formatKPIName = (name) => {
    const nameMap = {
      'won_pipeline':           'Won Pipeline',
      'won_volume':             'Won Deals',
      'ads':                    'Avg Deal Size',
      'aos':                    'Avg Opp Size',
      'opps_created':           'Opportunities Created',
      'created_pipeline':       'Created Pipeline',
      'active_pipeline':        'Active Pipeline',
      'close_rate':             'Close Rate (Vol)',
      'close_rate_dollar':      'Close Rate ($)',
      'win_rate':               'Win Rate',
      'coverage':               'Pipeline Coverage',
      'won_attainment_pct':     'Won Attainment',
      'pipeline_attainment_pct':'Pipeline Attainment',
      'mql_count':              'MQL Count',
    };
    return nameMap[name] || name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const getKPIFormat = (name) => {
    if (['won_pipeline', 'created_pipeline', 'active_pipeline', 'ads', 'aos'].includes(name)) {
      return 'currency';
    }
    if (['close_rate', 'close_rate_dollar', 'win_rate', 'won_attainment_pct', 'pipeline_attainment_pct'].includes(name)) {
      return 'percentage';
    }
    return 'number';
  };

  const getKPIUnit = (name) => {
    if (['coverage'].includes(name)) return 'x';
    return '';
  };

  const getDemoKPIs = () => {
    const rawKpis = [
      // Dollar funnel
      { name: 'Won Pipeline',          metric_name: 'won_pipeline',           value: 12_450_000, target: 15_000_000, previous_value: 11_200_000, format: 'currency' },
      { name: 'Created Pipeline',      metric_name: 'created_pipeline',       value: 52_000_000, target: 58_000_000, previous_value: 48_000_000, format: 'currency' },
      { name: 'Close Rate ($)',         metric_name: 'close_rate_dollar',      value: 23.9,       target: 30.0,       previous_value: 25.1,       format: 'percentage' },
      // Volume funnel
      { name: 'Won Deals',             metric_name: 'won_volume',             value: 78,         target: 90,         previous_value: 72,         format: 'number' },
      { name: 'Opportunities Created', metric_name: 'opps_created',           value: 312,        target: 350,        previous_value: 285,        format: 'number' },
      { name: 'Close Rate (Vol)',       metric_name: 'close_rate',             value: 25.0,       target: 30.0,       previous_value: 28.0,       format: 'percentage' },
      // Size KPIs
      { name: 'Avg Deal Size',         metric_name: 'ads',                    value: 159_615,    target: 166_667,    previous_value: 155_556,    format: 'currency' },
      { name: 'Avg Opp Size',          metric_name: 'aos',                    value: 166_667,    target: 175_000,    previous_value: 160_000,    format: 'currency' },
      // Health KPIs
      { name: 'Active Pipeline',       metric_name: 'active_pipeline',        value: 38_500_000, target: 45_000_000, previous_value: 36_800_000, format: 'currency' },
      { name: 'Pipeline Coverage',     metric_name: 'coverage',               value: 2.57,       target: 3.0,        previous_value: 3.1,        format: 'number',  unit: 'x' },
      { name: 'Won Attainment',        metric_name: 'won_attainment_pct',     value: 83.0,       target: 100.0,      previous_value: 79.0,       format: 'percentage' },
      { name: 'Pipeline Attainment',   metric_name: 'pipeline_attainment_pct',value: 89.7,       target: 100.0,      previous_value: 85.0,       format: 'percentage' },
      // Demand gen
      { name: 'Win Rate',              metric_name: 'win_rate',               value: 38.5,       target: 35.0,       previous_value: 36.2,       format: 'percentage' },
      { name: 'MQL Count',             metric_name: 'mql_count',              value: 1_240,      target: 1_400,      previous_value: 1_100,      format: 'number' },
    ];

    return rawKpis.map(kpi => ({
      ...kpi,
      title: kpi.name,
      targetAchievement: kpi.target ? (kpi.value / kpi.target) * 100 : null,
      trend: kpi.previous_value ? ((kpi.value - kpi.previous_value) / kpi.previous_value) * 100 : 0,
    }));
  };

  if (error && kpis.length === 0) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">{error}</p>
        <button
          onClick={fetchKPIs}
          className="mt-2 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <p className="text-yellow-800 text-sm">{error}</p>
        </div>
      )}
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4 gap-6">
        {loading
          ? Array(14).fill(0).map((_, i) => <KPICard key={i} loading={true} />)
          : kpis.map((kpi, index) => <KPICard key={index} kpi={kpi} loading={false} />)
        }
      </div>
    </div>
  );
};

export default KPIGrid;
