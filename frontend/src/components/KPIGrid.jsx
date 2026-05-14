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
      'won_pipeline': 'Won Pipeline',
      'won_volume': 'Won Deals',
      'ads': 'Avg Deal Size',
      'opps_created': 'Opportunities Created',
      'created_pipeline': 'Created Pipeline',
      'active_pipeline': 'Active Pipeline',
      'close_rate': 'Close Rate',
      'coverage': 'Pipeline Coverage',
    };
    return nameMap[name] || name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const getKPIFormat = (name) => {
    if (['won_pipeline', 'created_pipeline', 'active_pipeline', 'ads'].includes(name)) {
      return 'currency';
    }
    if (['close_rate', 'coverage'].includes(name)) {
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
      { name: 'Won Pipeline', value: 2450000, target: 2000000, previous_value: 2145000, format: 'currency' },
      { name: 'Won Deals', value: 78, target: 70, previous_value: 72, format: 'number' },
      { name: 'Avg Deal Size', value: 24500, target: 28000, previous_value: 29790, format: 'currency' }, // Below target
      { name: 'Opportunities Created', value: 195, target: 220, previous_value: 230, format: 'number' }, // Below target, declining
      { name: 'Created Pipeline', value: 9200000, target: 7500000, previous_value: 7800000, format: 'currency' }, // Exceeding
      { name: 'Active Pipeline', value: 12000000, target: 10000000, previous_value: 11400000, format: 'currency' },
      { name: 'Close Rate', value: 31.8, target: 30.0, previous_value: 31.3, format: 'percentage' },
      { name: 'Pipeline Coverage', value: 2.7, target: 3.0, previous_value: 3.1, format: 'number', unit: 'x' }, // Below target, declining
    ];

    // Enrich with calculated fields
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
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {loading
          ? Array(8).fill(0).map((_, i) => <KPICard key={i} loading={true} />)
          : kpis.map((kpi, index) => <KPICard key={index} kpi={kpi} loading={false} />)
        }
      </div>
    </div>
  );
};

export default KPIGrid;
