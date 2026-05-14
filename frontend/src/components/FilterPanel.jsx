import { useState, useEffect } from 'react';
import { Filter, X, ChevronDown } from 'lucide-react';
import { apiService } from '../services/api';

export default function FilterPanel({ onFilterChange, appliedFilters }) {
  const [filterOptions, setFilterOptions] = useState(null);
  const [filters, setFilters] = useState({
    geo: 'All',
    channel: 'All',
    product: 'All'
  });

  useEffect(() => {
    loadFilterOptions();
  }, []);

  const loadFilterOptions = async () => {
    try {
      const options = await apiService.getFilters();
      setFilterOptions(options);
    } catch (error) {
      console.error('Error loading filter options:', error);
    }
  };

  const handleChange = (key, value) => {
    const newFilters = { ...filters, [key]: value };
    setFilters(newFilters);
    onFilterChange(newFilters);
  };

  const clearFilters = () => {
    const defaultFilters = { geo: 'All', channel: 'All', product: 'All' };
    setFilters(defaultFilters);
    onFilterChange(defaultFilters);
  };

  const hasFiltersApplied = filters.geo !== 'All' || filters.channel !== 'All' || filters.product !== 'All';

  if (!filterOptions) {
    return null;
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-3 sticky top-4">
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-slate-200">
        <Filter className="w-4 h-4 text-blue-600" />
        <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">Filters</h3>
        {hasFiltersApplied && (
          <span className="bg-blue-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full">●</span>
        )}
      </div>

      <div className="space-y-3">
        {/* Geography Filter */}
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">
            Geography
          </label>
          <div className="relative">
            <select 
              value={filters.geo}
              onChange={(e) => handleChange('geo', e.target.value)}
              className="w-full appearance-none border border-slate-300 rounded-md px-2 py-1.5 pr-7 text-xs font-medium text-slate-900 bg-white hover:border-blue-400 focus:border-blue-500 focus:outline-none transition-colors cursor-pointer"
            >
              {filterOptions.geo.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500 pointer-events-none" />
          </div>
        </div>

        {/* Channel Filter */}
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">
            Channel
          </label>
          <div className="relative">
            <select 
              value={filters.channel}
              onChange={(e) => handleChange('channel', e.target.value)}
              className="w-full appearance-none border border-slate-300 rounded-md px-2 py-1.5 pr-7 text-xs font-medium text-slate-900 bg-white hover:border-blue-400 focus:border-blue-500 focus:outline-none transition-colors cursor-pointer"
            >
              {filterOptions.channel.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500 pointer-events-none" />
          </div>
        </div>

        {/* Product Filter */}
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">
            Product
          </label>
          <div className="relative">
            <select 
              value={filters.product}
              onChange={(e) => handleChange('product', e.target.value)}
              className="w-full appearance-none border border-slate-300 rounded-md px-2 py-1.5 pr-7 text-xs font-medium text-slate-900 bg-white hover:border-blue-400 focus:border-blue-500 focus:outline-none transition-colors cursor-pointer"
            >
              {filterOptions.product.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* Clear Button */}
      {hasFiltersApplied && (
        <button 
          onClick={clearFilters}
          className="w-full mt-3 pt-3 border-t border-slate-200 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-semibold text-slate-600 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
        >
          <X className="w-3 h-3" />
          <span>Clear All</span>
        </button>
      )}

      {/* Applied Filters Display */}
      {hasFiltersApplied && (
        <div className="mt-3 pt-3 border-t border-slate-200 space-y-1">
          <span className="text-xs font-bold text-slate-500 uppercase block">Active:</span>
          {filters.geo !== 'All' && (
            <div className="bg-blue-50 text-blue-800 text-xs font-semibold px-2 py-1 rounded border border-blue-200">
              📍 {filterOptions.geo.find(o => o.value === filters.geo)?.label.split('(')[0].trim()}
            </div>
          )}
          {filters.channel !== 'All' && (
            <div className="bg-green-50 text-green-800 text-xs font-semibold px-2 py-1 rounded border border-green-200">
              🔗 {filters.channel}
            </div>
          )}
          {filters.product !== 'All' && (
            <div className="bg-purple-50 text-purple-800 text-xs font-semibold px-2 py-1 rounded border border-purple-200">
              📦 {filters.product}
            </div>
          )}
        </div>
      )}

      {/* Time Period Filter in Sidebar */}
      <div className="mt-4 pt-4 border-t border-slate-200">
        <label className="block text-xs font-semibold text-slate-600 mb-2">
          Time Period
        </label>
        <div className="grid grid-cols-2 gap-1">
          <button className="px-2 py-1 text-xs font-medium text-white bg-blue-600 border border-blue-600 rounded hover:bg-blue-700">QTD</button>
          <button className="px-2 py-1 text-xs font-medium text-slate-700 bg-slate-50 border border-slate-300 rounded hover:bg-slate-100">MTD</button>
          <button className="px-2 py-1 text-xs font-medium text-slate-700 bg-slate-50 border border-slate-300 rounded hover:bg-slate-100">YTD</button>
          <button className="px-2 py-1 text-xs font-medium text-slate-700 bg-slate-50 border border-slate-300 rounded hover:bg-slate-100">L30D</button>
          <button className="px-2 py-1 text-xs font-medium text-slate-700 bg-slate-50 border border-slate-300 rounded hover:bg-slate-100">L90D</button>
          <button className="px-2 py-1 text-xs font-medium text-slate-700 bg-slate-50 border border-slate-300 rounded hover:bg-slate-100">Custom</button>
        </div>
      </div>
    </div>
  );
}
