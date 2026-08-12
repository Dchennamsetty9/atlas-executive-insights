/**
 * KPISummaryRow — Quick 4-card count grid before the KPI detail cards.
 * Shows: At Risk / Needs Attention / On Track / Exceeding counts.
 * Uses existing kpi objects with kpi.targetAchievement (%).
 * No API calls — all computed from the kpis prop.
 */

const CARDS = [
  {
    key:    'atRisk',
    label:  'At Risk',
    icon:   '🔴',
    filter: (k) => (k.targetAchievement ?? 0) < 80,
    color:  '#ef4444',
    bg:     'rgba(239,68,68,0.1)',
    border: 'rgba(239,68,68,0.25)',
  },
  {
    key:    'attention',
    label:  'Needs Attention',
    icon:   '🟡',
    filter: (k) => { const p = k.targetAchievement ?? 0; return p >= 80 && p < 90; },
    color:  '#eab308',
    bg:     'rgba(234,179,8,0.1)',
    border: 'rgba(234,179,8,0.25)',
  },
  {
    key:    'onTrack',
    label:  'On Track',
    icon:   '🟢',
    filter: (k) => { const p = k.targetAchievement ?? 0; return p >= 90 && p < 110; },
    color:  '#10b981',
    bg:     'rgba(16,185,129,0.1)',
    border: 'rgba(16,185,129,0.25)',
  },
  {
    key:    'exceeding',
    label:  'Exceeding',
    icon:   '🚀',
    filter: (k) => (k.targetAchievement ?? 0) >= 110,
    color:  '#3b82f6',
    bg:     'rgba(59,130,246,0.1)',
    border: 'rgba(59,130,246,0.25)',
  },
];

export default function KPISummaryRow({ kpis }) {
  const loading = !kpis?.length;

  const counts = loading
    ? { atRisk: '—', attention: '—', onTrack: '—', exceeding: '—' }
    : Object.fromEntries(
        CARDS.map(c => [c.key, kpis.filter(c.filter).length])
      );

  const totalKpis = loading ? '—' : kpis.length;

  return (
    <div style={{
      display: 'flex', gap: 8, alignItems: 'stretch',
      marginBottom: 12, marginTop: 4,
      flexShrink: 0,
    }}>
      {CARDS.map(card => {
        const count = counts[card.key];
        const isEmpty = count === 0 || count === '—';

        return (
          <div
            key={card.key}
            style={{
              flex: 1,
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 12px',
              background: isEmpty ? 'rgba(26,35,50,0.5)' : card.bg,
              border: `1px solid ${isEmpty ? 'rgba(255,255,255,0.06)' : card.border}`,
              borderRadius: 8,
              transition: 'border-color 0.2s',
            }}
          >
            <span style={{ fontSize: 16, lineHeight: 1 }}>{card.icon}</span>
            <div>
              <div style={{
                fontSize: 22, fontWeight: 700, lineHeight: 1,
                color: isEmpty ? '#475569' : card.color,
              }}>
                {loading ? '—' : count}
              </div>
              <div style={{
                fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5,
                color: '#64748b', marginTop: 1,
              }}>
                {card.label}
              </div>
            </div>
          </div>
        );
      })}

      {/* Total */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 16px',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 8,
        flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#94a3b8', lineHeight: 1 }}>
            {totalKpis}
          </div>
          <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, color: '#475569', marginTop: 1 }}>
            Total KPIs
          </div>
        </div>
      </div>
    </div>
  );
}
