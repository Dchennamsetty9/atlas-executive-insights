import { useState } from 'react';
import { X, ChevronDown, SlidersHorizontal } from 'lucide-react';
import { useFilters, DEFAULT_FILTERS } from '../contexts/FilterContext';
import { useTheme } from '../hooks/useTheme';

// ─── Static filter option lists ───────────────────────────────────────────────
const FILTER_CONFIGS = [
  {
    key: 'geo', label: 'Geography',
    options: [
      { label: 'All', value: 'All' },
      { label: 'NA', value: 'NA' },
      { label: 'EMEA', value: 'EMEA' },
      { label: 'LATAM', value: 'LATAM' },
      { label: 'APAC', value: 'APAC' },
      { label: 'AUS/ROW', value: 'AUS/ROW' },
    ],
  },
  {
    key: 'channel', label: 'Channel',
    options: [
      { label: 'All', value: 'All' },
      { label: 'Enterprise', value: 'Enterprise' },
      { label: 'Partner', value: 'Partner' },
      { label: 'Mid-Market', value: 'Mid-Market' },
      { label: 'MSP', value: 'MSP' },
      { label: 'GSI', value: 'GSI' },
      { label: 'Small Business', value: 'Small Business' },
    ],
  },
  {
    key: 'product', label: 'Product',
    options: [
      { label: 'All', value: 'All' },
      { label: 'GoTo Connect', value: 'Connect' },
      { label: 'GoTo Resolve', value: 'Resolve' },
      { label: 'GoTo Engage', value: 'Engage' },
      { label: 'GoTo Central', value: 'Central' },
      { label: 'Contact Center', value: 'ContactCenter' },
    ],
  },
  {
    key: 'fuel', label: 'Fuel Source',
    options: [
      { label: 'All', value: 'All' },
      { label: 'Marketing', value: 'Marketing' },
      { label: 'BDR', value: 'BDR' },
      { label: 'AE', value: 'AE' },
      { label: 'Partner', value: 'Partner' },
    ],
  },
  {
    key: 'purchaseType', label: 'Purchase Type',
    options: [
      { label: 'All', value: 'All' },
      { label: 'Expansion', value: 'Expansion' },
      { label: 'New', value: 'New' },
    ],
  },
  {
    key: 'targetVersion', label: 'Target',
    options: [
      { label: 'Plan (Board)', value: 'Plan' },
      { label: 'FY Forecast', value: 'FY' },
    ],
  },
];

const TIME_PERIODS = ['QTD', 'MTD', 'YTD', 'L30D', 'L90D', 'Custom'];

const CHIP_COLORS = {
  geo: '#3b82f6', channel: '#10b981', product: '#8b5cf6',
  fuel: '#f59e0b', purchaseType: '#06b6d4', targetVersion: '#ef4444',
};

const NON_DEFAULT_CHECK = {
  geo: 'All', channel: 'All', product: 'All',
  fuel: 'All', purchaseType: 'All', targetVersion: 'Plan',
};

export default function FilterPanel({ onFilterChange }) {
  const isDark = useTheme();
  const { filters, updateFilter, resetFilters } = useFilters();
  const [collapsed, setCollapsed] = useState(false);

  // ── Theme-aware color palette ───────────────────────────────────────────
  const C = isDark ? {
    panelBg:       'rgba(13,20,40,0.95)',
    panelBorder:   'rgba(255,255,255,0.07)',
    headerBorder:  'rgba(255,255,255,0.06)',
    filtersLabel:  '#94a3b8',
    labelText:     '#475569',
    divider:       'rgba(255,255,255,0.06)',
    activeLabel:   '#334155',
    dropdownBg:    'rgba(15,23,42,0.85)',
    dropdownBdr:   'rgba(255,255,255,0.1)',
    dropdownColor: '#e2e8f0',
    periodBg:      'rgba(255,255,255,0.03)',
    periodBdr:     'rgba(255,255,255,0.07)',
    periodColor:   '#475569',
  } : {
    panelBg:       '#ffffff',
    panelBorder:   'rgba(0,0,0,0.09)',
    headerBorder:  'rgba(0,0,0,0.07)',
    filtersLabel:  '#334155',
    labelText:     '#64748b',
    divider:       'rgba(0,0,0,0.07)',
    activeLabel:   '#475569',
    dropdownBg:    '#f8fafc',
    dropdownBdr:   'rgba(0,0,0,0.12)',
    dropdownColor: '#0f172a',
    periodBg:      '#f1f5f9',
    periodBdr:     'rgba(0,0,0,0.09)',
    periodColor:   '#475569',
  };

  const handleChange = (key, value) => {
    updateFilter(key, value);
    if (onFilterChange) {
      const newFilters = { ...filters, [key]: value };
      onFilterChange(newFilters);
    }
  };

  const handleReset = () => {
    resetFilters();
    if (onFilterChange) onFilterChange({ ...DEFAULT_FILTERS });
  };

  // Build active chips for any non-default selection
  const activeChips = FILTER_CONFIGS
    .filter(fc => filters[fc.key] !== NON_DEFAULT_CHECK[fc.key])
    .map(fc => ({
      key: fc.key,
      label: fc.options.find(o => o.value === filters[fc.key])?.label ?? filters[fc.key],
      color: CHIP_COLORS[fc.key],
    }));
  if (filters.period !== 'QTD') {
    activeChips.push({ key: 'period', label: filters.period, color: '#64748b' });
  }
  const hasActive = activeChips.length > 0;

  // ── Styles ─────────────────────────────────────────────────────────────────
  const dropdownStyle = {
    width: '100%',
    appearance: 'none',
    background: C.dropdownBg,
    border: `1px solid ${C.dropdownBdr}`,
    borderRadius: 5,
    color: C.dropdownColor,
    fontSize: 11,
    padding: '4px 22px 4px 7px',
    cursor: 'pointer',
    outline: 'none',
    fontFamily: 'inherit',
  };

  return (
    <div style={{
      background: C.panelBg,
      border: `1px solid ${C.panelBorder}`,
      borderRadius: 10,
      backdropFilter: 'blur(12px)',
      overflow: 'hidden',
      position: 'sticky',
      top: 60,
      boxShadow: isDark ? 'none' : '0 2px 12px rgba(0,0,0,0.06)',
    }}>

      {/* ── Header (collapsible toggle) ─────────────────────────────── */}
      <button
        onClick={() => setCollapsed(c => !c)}
        style={{
          width: '100%',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 12px',
          background: 'transparent', border: 'none', cursor: 'pointer',
          borderBottom: collapsed ? 'none' : `1px solid ${C.headerBorder}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <SlidersHorizontal size={12} color="#3b82f6" />
          <span style={{ fontSize: 10, fontWeight: 700, color: C.filtersLabel, textTransform: 'uppercase', letterSpacing: 1.1 }}>
            Filters
          </span>
          {hasActive && (
            <span style={{
              width: 5, height: 5, borderRadius: '50%',
              background: '#3b82f6', boxShadow: '0 0 6px #3b82f6',
              display: 'inline-block',
            }} />
          )}
        </div>
        <ChevronDown
          size={12}
          color="#475569"
          style={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform 0.2s' }}
        />
      </button>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      {!collapsed && (
        <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 9 }}>

          {/* Filter dropdowns */}
          {FILTER_CONFIGS.map(fc => (
            <div key={fc.key}>
              <div style={{
                fontSize: 9, fontWeight: 700, color: C.labelText,
                textTransform: 'uppercase', letterSpacing: 0.9, marginBottom: 3,
                borderLeft: filters[fc.key] !== NON_DEFAULT_CHECK[fc.key]
                  ? `2px solid ${CHIP_COLORS[fc.key]}` : '2px solid transparent',
                paddingLeft: 4,
              }}>
                {fc.label}
              </div>
              <div style={{ position: 'relative' }}>
                <select
                  value={filters[fc.key]}
                  onChange={e => handleChange(fc.key, e.target.value)}
                  style={dropdownStyle}
                >
                  {fc.options.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <ChevronDown
                  size={9}
                  style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', color: '#475569', pointerEvents: 'none' }}
                />
              </div>
            </div>
          ))}

          {/* ── Divider ──────────────────────────────────────────────── */}
          <div style={{ borderTop: `1px solid ${C.divider}`, paddingTop: 8 }}>

            {/* Active filter chips */}
            {hasActive && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 8, fontWeight: 700, color: C.activeLabel, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                  Active
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {activeChips.map(chip => (
                    <div key={chip.key} style={{
                      display: 'flex', alignItems: 'center', gap: 4,
                      padding: '2px 6px', borderRadius: 4,
                      background: `${chip.color}15`,
                      border: `1px solid ${chip.color}40`,
                      fontSize: 10, fontWeight: 600, color: chip.color,
                    }}>
                      <span style={{ fontSize: 8 }}>●</span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{chip.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Time Period */}
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 8, fontWeight: 700, color: C.activeLabel, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                Time Period
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}>
                {TIME_PERIODS.map(p => {
                  const active = filters.period === p;
                  return (
                    <button
                      key={p}
                      onClick={() => handleChange('period', p)}
                      style={{
                        padding: '4px 0', borderRadius: 4,
                        fontSize: 10, fontWeight: active ? 700 : 500,
                        cursor: 'pointer',
                        background: active ? 'rgba(59,130,246,0.15)' : C.periodBg,
                        border: `1px solid ${active ? 'rgba(59,130,246,0.5)' : C.periodBdr}`,
                        color: active ? '#3b82f6' : C.periodColor,
                        transition: 'all 0.12s', fontFamily: 'inherit',
                      }}
                    >
                      {p}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Clear All */}
            {hasActive && (
              <button
                onClick={handleReset}
                style={{
                  width: '100%', marginTop: 4,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                  padding: '5px 0', borderRadius: 5,
                  background: 'rgba(239,68,68,0.06)',
                  border: '1px solid rgba(239,68,68,0.2)',
                  color: '#ef4444',
                  fontSize: 11, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                <X size={10} />
                Clear All
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
