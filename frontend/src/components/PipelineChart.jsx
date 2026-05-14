import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';
import { apiService } from '../services/api';

const PipelineChart = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchPipelineData();
  }, []);

  const fetchPipelineData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiService.getKPIs();
      
      // Extract pipeline metrics from backend API (uses 'id' field)
      const pipelineMetrics = ['won_pipeline', 'created_pipeline', 'active_pipeline'].map(metric => {
        const kpi = response.find(k => k.id === metric);
        return {
          name: formatName(metric),
          value: kpi ? (kpi.value * (kpi.unit === '$' ? 1000000 : 1)) : 0,
          target: kpi ? (kpi.target * (kpi.unit === '$' ? 1000000 : 1)) : 0,
          metTarget: kpi ? kpi.value >= kpi.target : false,
        };
      });

      setData(pipelineMetrics);
    } catch (err) {
      console.error('Error fetching pipeline data:', err);
      setError('Failed to load pipeline data. Showing demo data.');
      setData(getDemoData());
    } finally {
      setLoading(false);
    }
  };

  const formatName = (name) => {
    const nameMap = {
      'won_pipeline': 'Won',
      'created_pipeline': 'Created',
      'active_pipeline': 'Active',
    };
    return nameMap[name] || name;
  };

  const getDemoData = () => [
    { name: 'Won', value: 2450000, target: 2000000, metTarget: true },
    { name: 'Created', value: 8500000, target: 7500000, metTarget: true },
    { name: 'Active', value: 12000000, target: 10000000, metTarget: true },
  ];

  const formatCurrency = (value) => {
    return `$${(value / 1000000).toFixed(1)}M`;
  };

  const COLORS = {
    Won: '#10b981',
    Created: '#3b82f6',
    Active: '#8b5cf6',
  };

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-white p-4 rounded-lg shadow-lg border border-gray-200">
          <p className="font-semibold text-gray-800 mb-2">{data.name} Pipeline</p>
          <p className="text-blue-600 font-medium">
            Value: {formatCurrency(data.value)}
          </p>
          <p className="text-gray-600">
            Target: {formatCurrency(data.target)}
          </p>
          <p className={`text-sm mt-1 ${data.metTarget ? 'text-green-600' : 'text-orange-600'}`}>
            {data.metTarget ? '✓ Target Met' : '⚠ Below Target'}
          </p>
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 rounded w-48 mb-4"></div>
          <div className="h-64 bg-gray-100 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Pipeline Overview</h2>
          <p className="text-sm text-gray-600 mt-1">Performance Hub Metrics: Won, Created, and Active Pipeline</p>
        </div>
        {error && (
          <span className="text-sm text-yellow-600 bg-yellow-50 px-3 py-1 rounded">
            Demo Mode
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis 
            dataKey="name" 
            tick={{ fill: '#6b7280', fontSize: 14, fontWeight: 500 }}
            tickLine={{ stroke: '#e5e7eb' }}
          />
          <YAxis 
            tickFormatter={formatCurrency}
            tick={{ fill: '#6b7280', fontSize: 12 }}
            tickLine={{ stroke: '#e5e7eb' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ paddingTop: '20px' }} />
          <Bar dataKey="value" name="Actual" radius={[8, 8, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[entry.name]} />
            ))}
          </Bar>
          <Bar dataKey="target" name="Target" fill="#e5e7eb" radius={[8, 8, 0, 0]} opacity={0.4} />
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-4 grid grid-cols-3 gap-4 border-t pt-4">
        {data.map((item, index) => (
          <div key={index} className="text-center">
            <div className="flex items-center justify-center mb-1">
              <div 
                className="w-3 h-3 rounded-full mr-2" 
                style={{ backgroundColor: COLORS[item.name] }}
              ></div>
              <p className="text-sm text-gray-600">{item.name}</p>
            </div>
            <p className="text-lg font-bold text-gray-900">
              {formatCurrency(item.value)}
            </p>
            <p className={`text-xs ${item.metTarget ? 'text-green-600' : 'text-orange-600'}`}>
              {((item.value / item.target) * 100).toFixed(0)}% of target
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default PipelineChart;
