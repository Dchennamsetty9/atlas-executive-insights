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
        fontSize: 10, fontWeight: 700, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: 1.4,
        paddingBottom: 8, marginBottom: 0,
      }}>
        Extended Analytics
      </div>

      {/* Tab strip */}
      <div style={{
        display: 'flex', gap: 8,
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 16,
        padding: 8,
        marginBottom: 14,
        overflowX: 'auto',
        backdropFilter: 'blur(14px)',
      }}>
        {TABS.map(tab => {
          const isActive = active === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '10px 14px',
                background: isActive ? 'linear-gradient(135deg, rgba(59,130,246,0.18), rgba(124,58,237,0.12))' : 'transparent',
                border: `1px solid ${isActive ? 'rgba(59,130,246,0.28)' : 'transparent'}`,
                borderRadius: 12,
                color: isActive ? '#f8fafc' : '#64748b',
                fontSize: 12, fontWeight: isActive ? 700 : 600,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'color 0.15s, border-color 0.15s, background 0.15s, box-shadow 0.15s',
                boxShadow: isActive ? '0 10px 24px rgba(59,130,246,0.12)' : 'none',
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
        background: 'linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02))',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 18,
        padding: 18,
        minHeight: 240,
        boxShadow: '0 14px 34px rgba(0,0,0,0.16)',
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
