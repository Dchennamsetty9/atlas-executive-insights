/**
 * FilterContext — global filter state for Atlas Executive Insights
 * All components read from this context; FilterPanel writes to it.
 */
import { createContext, useContext, useState, useCallback } from 'react';

export const DEFAULT_FILTERS = {
  geo:           'All',
  channel:       'All',
  product:       'All',
  fuel:          'All',
  purchaseType:  'All',
  targetVersion: 'Plan',
  period:        'QTD',
};

const FilterContext = createContext(null);

export function FilterProvider({ children }) {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);

  const updateFilter = useCallback((key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  }, []);

  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), []);

  return (
    <FilterContext.Provider value={{ filters, setFilters, updateFilter, resetFilters }}>
      {children}
    </FilterContext.Provider>
  );
}

export function useFilters() {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error('useFilters must be used within a FilterProvider');
  return ctx;
}

export default FilterContext;
