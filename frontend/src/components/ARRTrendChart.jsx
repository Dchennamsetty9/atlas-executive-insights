import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { apiService } from '../services/api';

const ARRTrendChart = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchARRData();
  }, []);

  const fetchARRData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiService.getARRHistory();
      
      if (response.history && response.history.length > 0) {
        const formattedData = response.history.map(item => ({
          date: new Date(item.ds).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          arr: item.y,
          growth: item.growth_pct || 0,
        }));
        setData(formattedData);
      } else {
        setData(getDemoData());
      }
    } catch (err) {
      console.error('Error fetching ARR data:', err);
      setError('Failed to load ARR data. Showing demo data.');
      setData(getDemoData());
    } finally {
      setLoading(false);
    }
  };

  const getDemoData = () => {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return months.map((month, i) => ({
      date: month,
      arr: 50000000 + i * 1000000 + Math.random() * 500000,
      growth: 1 + Math.random() * 3,
    }));
  };

  const formatCurrency = (value) => {
    return `$${(value / 1000000).toFixed(1)}M`;
  };

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-4 rounded-lg shadow-lg border border-gray-200">
          <p className="font-semibold text-gray-800">{payload[0].payload.date}</p>
          <p className="text-blue-600 font-medium">
            ARR: {formatCurrency(payload[0].value)}
          </p>
          {payload[0].payload.growth !== undefined && (
            <p className="text-green-600 text-sm">
              Growth: +{payload[0].payload.growth.toFixed(1)}%
            </p>
          )}
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
          <h2 className="text-xl font-bold text-gray-900">ARR Trend</h2>
          <p className="text-sm text-gray-600 mt-1">Annual Recurring Revenue over time</p>
        </div>
        {error && (
          <span className="text-sm text-yellow-600 bg-yellow-50 px-3 py-1 rounded">
            Demo Mode
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis 
            dataKey="date" 
            tick={{ fill: '#6b7280', fontSize: 12 }}
            tickLine={{ stroke: '#e5e7eb' }}
          />
          <YAxis 
            tickFormatter={formatCurrency}
            tick={{ fill: '#6b7280', fontSize: 12 }}
            tickLine={{ stroke: '#e5e7eb' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend 
            wrapperStyle={{ paddingTop: '20px' }}
            iconType="line"
          />
          <Line 
            type="monotone" 
            dataKey="arr" 
            stroke="#3b82f6" 
            strokeWidth={3}
            dot={{ fill: '#3b82f6', r: 4 }}
            activeDot={{ r: 6 }}
            name="ARR"
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="mt-4 grid grid-cols-3 gap-4 border-t pt-4">
        <div>
          <p className="text-sm text-gray-600">Current ARR</p>
          <p className="text-lg font-bold text-gray-900">
            {data.length > 0 && formatCurrency(data[data.length - 1].arr)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600">Avg Growth</p>
          <p className="text-lg font-bold text-green-600">
            +{data.length > 0 && (data.reduce((sum, d) => sum + (d.growth || 0), 0) / data.length).toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600">Trend</p>
          <p className="text-lg font-bold text-blue-600">
            {data.length >= 2 && data[data.length - 1].arr > data[0].arr ? '↗ Growing' : '→ Stable'}
          </p>
        </div>
      </div>
    </div>
  );
};

export default ARRTrendChart;
