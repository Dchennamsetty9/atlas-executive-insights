import { useEffect, useState } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'
import { fetchChartData } from '../services/api'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

function DescriptiveAnalytics() {
  const [revenueByRegion, setRevenueByRegion] = useState(null)
  const [monthlyTrend, setMonthlyTrend] = useState(null)

  useEffect(() => {
    loadChartData()
  }, [])

  const loadChartData = async () => {
    const regionData = await fetchChartData('revenue_by_region')
    const trendData = await fetchChartData('monthly_trend')
    
    if (regionData) setRevenueByRegion(regionData)
    if (trendData) setMonthlyTrend(trendData)
  }

  // Mock data for development
  const revenueData = revenueByRegion || {
    labels: ['North', 'South', 'East', 'West', 'Central'],
    datasets: [{
      label: 'Revenue',
      data: [1200000, 980000, 1500000, 1750000, 1100000],
      backgroundColor: '#4F46E5'
    }]
  }

  const trendData = monthlyTrend || {
    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
    datasets: [{
      label: 'Revenue',
      data: [1800000, 1950000, 2100000, 2050000, 2200000, 2300000],
      borderColor: '#4F46E5',
      backgroundColor: 'rgba(79, 70, 229, 0.1)',
      fill: true,
      tension: 0.4
    }]
  }

  const barOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false
      },
      title: {
        display: false
      }
    },
    scales: {
      y: {
        beginAtZero: true,
        ticks: {
          callback: function(value) {
            return '$' + (value / 1000000).toFixed(1) + 'M'
          }
        }
      }
    }
  }

  const lineOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false
      },
      title: {
        display: false
      }
    },
    scales: {
      y: {
        beginAtZero: false,
        ticks: {
          callback: function(value) {
            return '$' + (value / 1000000).toFixed(1) + 'M'
          }
        }
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">A. Descriptive Analytics</h2>
        
        <div className="mb-6">
          <h3 className="text-sm font-medium text-gray-600 mb-3">Revenue by Region</h3>
          <div className="h-64">
            <Bar data={revenueData} options={barOptions} />
          </div>
        </div>

        <div className="text-sm text-blue-700 bg-blue-50 p-3 rounded-lg flex items-start space-x-2">
          <svg className="w-5 h-5 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
          </svg>
          <span>Revenue declined 12% in Q3 due to lower West region performance.</span>
        </div>
      </div>

      <div className="card">
        <h3 className="text-sm font-medium text-gray-600 mb-3">Monthly Trend (Revenue)</h3>
        <div className="h-64">
          <Line data={trendData} options={lineOptions} />
        </div>
      </div>
    </div>
  )
}

export default DescriptiveAnalytics
