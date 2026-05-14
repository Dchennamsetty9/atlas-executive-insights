/**
 * Time Period Filter - Select different time ranges for analysis
 */

import { Calendar } from 'lucide-react'
import { useState } from 'react'

const TimePeriodFilter = ({ onPeriodChange }) => {
  const [selectedPeriod, setSelectedPeriod] = useState('qtd')

  const periods = [
    { id: 'mtd', label: 'Month to Date', shortLabel: 'MTD' },
    { id: 'qtd', label: 'Quarter to Date', shortLabel: 'QTD' },
    { id: 'ytd', label: 'Year to Date', shortLabel: 'YTD' },
    { id: 'last30', label: 'Last 30 Days', shortLabel: 'L30D' },
    { id: 'last90', label: 'Last 90 Days', shortLabel: 'L90D' },
    { id: 'custom', label: 'Custom Range', shortLabel: 'Custom' }
  ]

  const handlePeriodChange = (periodId) => {
    setSelectedPeriod(periodId)
    if (onPeriodChange) {
      onPeriodChange(periodId)
    }
  }

  return (
    <div className="bg-white rounded-lg shadow-sm p-4">
      <div className="flex items-center gap-3 mb-3">
        <Calendar className="w-5 h-5 text-gray-600" />
        <h3 className="font-semibold text-gray-800">Time Period</h3>
      </div>

      <div className="flex flex-wrap gap-2">
        {periods.map(period => (
          <button
            key={period.id}
            onClick={() => handlePeriodChange(period.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              selectedPeriod === period.id
                ? 'bg-indigo-600 text-white shadow-md'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
            title={period.label}
          >
            {period.shortLabel}
          </button>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-gray-200">
        <p className="text-xs text-gray-500">
          {periods.find(p => p.id === selectedPeriod)?.label || 'Select a time period'}
        </p>
      </div>
    </div>
  )
}

export default TimePeriodFilter
