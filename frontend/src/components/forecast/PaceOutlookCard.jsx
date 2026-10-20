import React from 'react';
import { paceView } from './paceOutlook';

const BADGE = {
  validated: { color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.35)' },
  indicative: { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.35)' },
};

// In-quarter pace outlook (informational; it does not replace the plan numbers shown elsewhere).
export default function PaceOutlookCard({ pace, fmt }) {
  const view = paceView(pace);
  if (!view) return null;
  const sign = (d) => `${d >= 0 ? '+' : '−'}${fmt(Math.abs(d))}`;
  const line = (r, label) => {
    const b = BADGE[r.badge.kind];
    return (
      <div key={label} style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', padding: '6px 0' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', minWidth: 44 }}>{label}</span>
        <span style={{ fontSize: 20, fontWeight: 800, color: '#f1f5f9' }}>{fmt(r.outlook_landing)}</span>
        <span style={{ fontSize: 11, color: '#64748b' }}>
          vs static forecast {fmt(r.model_landing)} ({sign(r.delta)})
        </span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 999, color: b.color,
                       background: b.bg, border: `1px solid ${b.border}` }}>{r.badge.text}</span>
        {r.backtest && <span style={{ fontSize: 10, color: '#475569' }}>{r.backtest}</span>}
      </div>
    );
  };
  return (
    <div style={{ padding: '10px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.02)',
                  border: '1px solid rgba(255,255,255,0.07)' }}>
      <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
        In-quarter pace outlook{view.quarter ? ` · ${view.quarter}` : ''}{view.asof ? ` · as of ${view.asof}` : ''}
      </div>
      {view.rows.map((r) => line(r, r.product))}
      {view.total && line({ ...view.total, backtest: null }, 'Total')}
      <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>
        Realized so far plus the remaining forecast scaled by how the quarter is tracking, plus the learned quarter-end uplift.
        Shown for reference; the plan numbers above are unchanged.
      </div>
    </div>
  );
}
