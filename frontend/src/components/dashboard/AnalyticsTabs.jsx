/**
 * AnalyticsTabs — 5-tab wrapper for Extended Analytics section.
 * Tabs: MQL Analytics | Pipeline by Segment | Deal Band Analysis | Pipeline Coverage | Largest Deals
 */

import { useState } from 'react';
import MQLAnalytics from '../charts/MQLAnalytics';
import PipelineSegmentAnalysis from '../charts/PipelineSegmentAnalysis';
import DealBandAnalysis from '../charts/DealBandAnalysis';
import PipelineCoverage from '../charts/PipelineCoverage';
import LargestDealsTable from '../tables/LargestDealsTable';

const TABS = [
  { id: 'mql',      label: 'MQL Analytics',       icon: '📈' },
  { id: 'pipeline', label: 'Pipeline by Segment',  icon: '📊' },
  { id: 'deals',    label: 'Deal Band Analysis',   icon: '💰' },
  { id: 'coverage', label: 'Pipeline Coverage',    icon: '🎯' },
  { id: 'largest',  label: 'Largest Deals',        icon: '🏆' },
];

export default function AnalyticsTabs() {
  const [active, setActive] = useState('mql');

  return (
    <div>
      {/* Section header */}
      <div style={{
        fontSize: 11, fontWeight: 700, color: '#475569',
        textTransform: 'uppercase', letterSpacing: 1.2,
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        paddingBottom: 6, marginBottom: 0,
      }}>
        Extended Analytics
      </div>

      {/* Tab strip */}
      <div style={{
        display: 'flex', gap: 2,
        borderBottom: '1px solid rgba(255,255,255,0.07)',
        marginBottom: 0,
        overflowX: 'auto',
        paddingBottom: 0,
      }}>
        {TABS.map(tab => {
          const isActive = active === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '10px 16px',
                background: 'transparent',
                border: 'none',
                borderBottom: isActive ? '2px solid #3b82f6' : '2px solid transparent',
                marginBottom: -1,
                color: isActive ? '#f1f5f9' : '#64748b',
                fontSize: 12, fontWeight: isActive ? 700 : 500,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'color 0.15s, border-color 0.15s',
              }}
            >
              <span style={{ fontSize: 13 }}>{tab.icon}</span>
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab panels */}
      <div style={{
        background: 'rgba(15,23,42,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderTop: 'none',
        borderRadius: '0 0 10px 10px',
        padding: '20px 16px',
        minHeight: 200,
      }}>
        {active === 'mql'      && <MQLAnalytics />}
        {active === 'pipeline' && <PipelineSegmentAnalysis />}
        {active === 'deals'    && <DealBandAnalysis />}
        {active === 'coverage' && <PipelineCoverage />}
        {active === 'largest'  && <LargestDealsTable limit={20} />}
      </div>
    </div>
  );
}
