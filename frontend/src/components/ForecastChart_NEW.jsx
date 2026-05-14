import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Area, ComposedChart } from 'recharts';
import { apiService } from '../services/api';
import { TrendingUp, Brain, BarChart3, Info } from 'lucide-react';

const ForecastChart = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedModel, setSelectedModel] = useState('ensemble');
  const [availableModels, setAvailableModels] = useState([]);
  const [modelAccuracy, setModelAccuracy] = useState(null);
  const [showComparison, setShowComparison] = useState(false);
  const [modelComparison, setModelComparison] = useState(null);
  const [metric, setMetric] = useState('arr');

  useEffect(() => {
    loadAvailableModels();
  }, []);

  useEffect(() => {
    if (selectedModel) {
      fetchForecastData();
    }
  }, [metric, selectedModel]);

  const loadAvailableModels = async () => {
    try {
      const models = await apiService.get('/api/forecast/models');
      const modelsList = Object.entries(models).map(([key, description]) => ({
        id: key,
        name: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '),
        description
      }));
      setAvailableModels(modelsList);
    } catch (err) {
      console.error('Error loading models:', err);
      setAvailableModels([
        { id: 'ensemble', name: 'Ensemble', description: 'Combines multiple models (recommended)' },
        { id: 'prophet', name: 'Prophet', description: 'Facebook AI - Best for seasonal data' },
        { id: 'arima', name: 'ARIMA', description: 'Statistical time series model' },
        { id: 'exponential', name: 'Exponential Smoothing', description: 'Holt-Winters smoothing' },
        { id: 'linear', name: 'Linear Regression', description: 'Simple baseline' }
      ]);
    }
  };

  const fetchForecastData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiService.get(`/api/forecast/advanced?metric=${metric}&periods=90&model=${selectedModel}`);
      
      const chartData = [];
      
      if (response.historical) {
        response.historical.forEach(point => {
          chartData.push({
            date: new Date(point.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            actual: point.value,
            isForecast: false
          });
        });
      }
      
      if (response.forecast) {
        response.forecast.forEach(point => {
          chartData.push({
            date: new Date(point.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            mostLikely: point.value,
            bestCase: point.upper_bound,
            worstCase: point.lower_bound,
            isForecast: true
          });
        });
      }
      
      setData(chartData);
      setModelAccuracy(response.accuracy);
    } catch (err) {
      console.error('Error fetching forecast:', err);
      setError('Failed to load forecast. Showing demo data.');
      const mockData = generateDemoData();
      setData(mockData);
    } finally {
      setLoading(false);
    }
  };

  const loadModelComparison = async () => {
    try {
      const comparison = await apiService.get(`/api/forecast/compare?metric=${metric}`);
      setModelComparison(comparison);
      setShowComparison(true);
    } catch (err) {
      console.error('Error loading model comparison:', err);
    }
  };

  const generateDemoData = () => {
    const data = [];
    const today = new Date();
    
    for (let i = 30; i > 0; i--) {
      const date = new Date(today);
      date.setDate(date.getDate() - i);
      data.push({
        date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        actual: 50000000 + i * 100000,
        isForecast: false
      });
    }
    
    for (let i = 1; i <= 30; i++) {
      const date = new Date(today);
      date.setDate(date.getDate() + i);
      const base = 53000000 + i * 120000;
      data.push({
        date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        mostLikely: base,
        bestCase: base * 1.15,
        worstCase: base * 0.85,
        isForecast: true
      });
    }
    return data;
  };

  const formatCurrency = (value) => {
    return `$${(value / 1000000).toFixed(1)}M`;
  };

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-white p-4 rounded-lg shadow-lg border border-gray-200">
          <p className="font-semibold text-gray-800 mb-2">{data.date}</p>
          {data.actual && (
            <p className="text-gray-900 font-medium">
              Actual: {formatCurrency(data.actual)}
            </p>
          )}
          {data.isForecast && (
            <>
              <p className="text-green-600">
                Best: {formatCurrency(data.bestCase)}
              </p>
              <p className="text-blue-600 font-medium">
                Most Likely: {formatCurrency(data.mostLikely)}
              </p>
              <p className="text-red-600">
                Worst: {formatCurrency(data.worstCase)}
              </p>
            </>
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
          <div className="h-96 bg-gray-100 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <TrendingUp className="h-6 w-6 text-blue-600" />
          <div>
            <h2 className="text-xl font-bold text-gray-900">Advanced Forecast</h2>
            <p className="text-sm text-gray-500">90-day ARR projection with multi-model selection</p>
          </div>
        </div>
        
        {/* Model Selector */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-blue-600" />
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white text-gray-900"
            >
              {availableModels.map(model => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
          </div>
          
          {/* Compare Models Button */}
          <button
            onClick={loadModelComparison}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
          >
            <BarChart3 className="h-4 w-4" />
            Compare Models
          </button>
        </div>
      </div>

      {/* Model Comparison Panel */}
      {showComparison && modelComparison && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-2">
              <Info className="h-5 w-5 text-blue-600" />
              <h3 className="font-semibold text-gray-900">Model Accuracy Comparison</h3>
            </div>
            <button
              onClick={() => setShowComparison(false)}
              className="text-gray-500 hover:text-gray-700"
            >
              ✕
            </button>
          </div>
          <div className="grid grid-cols-5 gap-3">
            {Object.entries(modelComparison).map(([modelName, metrics]) => (
              <div
                key={modelName}
                className={`p-3 rounded-lg ${
                  modelName.toLowerCase() === selectedModel
                    ? 'bg-blue-100 border-2 border-blue-400'
                    : 'bg-white border border-gray-200'
                }`}
              >
                <p className="font-semibold text-sm text-gray-900 mb-2">
                  {modelName.charAt(0).toUpperCase() + modelName.slice(1)}
                </p>
                <p className="text-xs text-gray-600">
                  MAPE: {metrics.mape ? metrics.mape.toFixed(2) : 'N/A'}%
                </p>
                <p className="text-xs text-gray-600">
                  Accuracy: {metrics.accuracy ? metrics.accuracy.toFixed(1) : 'N/A'}%
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Selected Model Info */}
      {availableModels.find(m => m.id === selectedModel) && (
        <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded-lg">
          <p className="text-sm text-gray-700">
            <span className="font-semibold">Selected Model:</span>{' '}
            {availableModels.find(m => m.id === selectedModel).description}
            {modelAccuracy && (
              <span className="ml-2 text-blue-600">
                (Accuracy: {modelAccuracy.toFixed(1)}%)
              </span>
            )}
          </p>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-sm text-yellow-800">{error}</p>
        </div>
      )}

      {/* Forecast Chart */}
      <ResponsiveContainer width="100%" height={400}>
        <ComposedChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis 
            dataKey="date" 
            tick={{ fill: '#6b7280', fontSize: 11 }}
            tickLine={{ stroke: '#e5e7eb' }}
            interval="preserveStartEnd"
          />
          <YAxis 
            tickFormatter={formatCurrency}
            tick={{ fill: '#6b7280', fontSize: 12 }}
            tickLine={{ stroke: '#e5e7eb' }}
          />
          <Tooltip 
            content={<CustomTooltip />}
            wrapperStyle={{ paddingTop: '20px' }}
            iconType="line"
          />
          <Legend 
            wrapperStyle={{ paddingTop: '20px' }}
            iconType="line"
          />

          {/* Confidence Interval (shaded area) */}
          <Area
            type="monotone"
            dataKey="bestCase"
            stroke="none"
            fill="#3b82f6"
            fillOpacity={0.1}
            name="Confidence Interval"
          />

          {/* Historical Actual */}
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#374151"
            strokeWidth={3}
            dot={false}
            name="Historical"
          />

          {/* Forecast Lines */}
          <Line
            type="monotone"
            dataKey="bestCase"
            stroke="#10b981"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            name="Best Case"
          />

          <Line
            type="monotone"
            dataKey="mostLikely"
            stroke="#3b82f6"
            strokeWidth={3}
            dot={false}
            name="Most Likely"
          />

          <Line
            type="monotone"
            dataKey="worstCase"
            stroke="#ef4444"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            name="Worst Case"
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Summary Stats */}
      <div className="mt-6 grid grid-cols-4 gap-4 border-t pt-4">
        <div>
          <p className="text-sm text-gray-600">Current (Last Actual)</p>
          <p className="text-lg font-bold text-gray-900">
            {data.filter(d => !d.isForecast && d.actual).length > 0 && 
             formatCurrency(data.filter(d => !d.isForecast).slice(-1)[0].actual)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600">90-Day Forecast</p>
          <p className="text-lg font-bold text-blue-600">
            {data.filter(d => d.isForecast).length > 0 && 
             formatCurrency(data.filter(d => d.isForecast).slice(-1)[0].mostLikely)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600">90-Day Best Case</p>
          <p className="text-lg font-bold text-green-600">
            {data.filter(d => d.isForecast).length > 0 && 
             formatCurrency(data.filter(d => d.isForecast).slice(-1)[0].bestCase)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600">90-Day Worst Case</p>
          <p className="text-lg font-bold text-red-600">
            {data.filter(d => d.isForecast).length > 0 && 
             formatCurrency(data.filter(d => d.isForecast).slice(-1)[0].worstCase)}
          </p>
        </div>
      </div>
    </div>
  );
};

export default ForecastChart;
