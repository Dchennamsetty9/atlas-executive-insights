import { Line } from 'react-chartjs-2'
import { Activity } from 'lucide-react'

function PredictiveAnalytics({ forecast }) {
  // Mock forecast data for development
  const mockForecast = {
    metric: 'revenue',
    historical: Array.from({ length: 30 }, (_, i) => ({
      date: new Date(Date.now() - (30 - i) * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
      value: 2000000 + i * 10000 + Math.random() * 50000
    })),
    forecast: Array.from({ length: 90 }, (_, i) => ({
      date: new Date(Date.now() + i * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
      value: 2300000 + i * 5000,
      lower_bound: 2200000 + i * 4500,
      upper_bound: 2400000 + i * 5500
    })),
    accuracy: 0.87,
    confidence_interval: 0.95
  }

  const data = forecast || mockForecast
  
  // Prepare chart data
  const allDates = [
    ...data.historical.map(p => p.date.split('-').slice(1).join('/')),
    ...data.forecast.slice(0, 30).map(p => p.date.split('-').slice(1).join('/'))
  ]
  
  const historicalValues = [
    ...data.historical.map(p => p.value),
    ...Array(Math.min(30, data.forecast.length)).fill(null)
  ]
  
  const forecastValues = [
    ...Array(data.historical.length).fill(null),
    ...data.forecast.slice(0, 30).map(p => p.value)
  ]
  
  const upperBound = [
    ...Array(data.historical.length).fill(null),
    ...data.forecast.slice(0, 30).map(p => p.upper_bound)
  ]
  
  const lowerBound = [
    ...Array(data.historical.length).fill(null),
    ...data.forecast.slice(0, 30).map(p => p.lower_bound)
  ]

  const chartData = {
    labels: allDates,
    datasets: [
      {
        label: 'Historical',
        data: historicalValues,
        borderColor: '#4F46E5',
        backgroundColor: 'rgba(79, 70, 229, 0.1)',
        borderWidth: 2,
        pointRadius: 0,
        fill: false
      },
      {
        label: 'Forecast',
        data: forecastValues,
        borderColor: '#8B5CF6',
        backgroundColor: 'rgba(139, 92, 246, 0.1)',
        borderWidth: 2,
        borderDash: [5, 5],
        pointRadius: 0,
        fill: false
      },
      {
        label: 'Upper Bound',
        data: upperBound,
        borderColor: 'rgba(139, 92, 246, 0.2)',
        backgroundColor: 'rgba(139, 92, 246, 0.05)',
        borderWidth: 1,
        pointRadius: 0,
        fill: '+1'
      },
      {
        label: 'Lower Bound',
        data: lowerBound,
        borderColor: 'rgba(139, 92, 246, 0.2)',
        backgroundColor: 'rgba(139, 92, 246, 0.05)',
        borderWidth: 1,
        pointRadius: 0,
        fill: false
      }
    ]
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: {
          usePointStyle: true,
          filter: (item) => item.text !== 'Upper Bound' && item.text !== 'Lower Bound'
        }
      },
      tooltip: {
        mode: 'index',
        intersect: false
      }
    },
    scales: {
      x: {
        display: true,
        ticks: {
          maxTicksLimit: 8
        }
      },
      y: {
        beginAtZero: false,
        ticks: {
          callback: function(value) {
            return '$' + (value / 1000000).toFixed(1) + 'M'
          }
        }
      }
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false
    }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <Activity className="w-5 h-5 text-purple-600" />
          <h2 className="text-lg font-semibold">C. Predictive Analytics</h2>
        </div>
        <div className="text-right">
          <div className="text-sm text-gray-600">Forecast (Next 3 Months)</div>
          <div className="text-xs text-gray-500">{Math.round(data.accuracy * 100)}% accuracy</div>
        </div>
      </div>
      
      <div className="h-80">
        <Line data={chartData} options={options} />
      </div>
      
      <div className="mt-4 p-3 bg-purple-50 rounded-lg">
        <div className="text-sm text-purple-900 font-medium">87% Forecast Accuracy</div>
        <div className="text-xs text-purple-700 mt-1">
          Based on historical data and trend analysis with {data.confidence_interval * 100}% confidence interval
        </div>
      </div>
    </div>
  )
}

export default PredictiveAnalytics
