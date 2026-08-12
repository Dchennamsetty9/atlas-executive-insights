/**
 * BusinessStatusBanner — Single-line "Am I winning?" health indicator.
 * Uses existing kpi objects: kpi.targetAchievement (%), kpi.id, kpi.value, kpi.target, kpi.unit
 * No API calls — all computed from the kpis prop passed by App.jsx.
 */

const formatGap = (kpi) => {
  if (!kpi || kpi.target == null || kpi.value == null) return null;
  const gap = kpi.target - kpi.value;
  if (gap <= 0) return null;
  if (kpi.unit === 'M') return `$${gap.toFixed(1)}M`;
  if (kpi.unit === 'K') return `$${Math.round(gap)}K`;
  if (kpi.unit === '%') return `${gap.toFixed(1)} pts`;
  return null;
};

const generateNarrative = (kpis) => {
  if (!kpis?.length) return 'Loading performance data...';
  const atRiskCount = kpis.filter(k => (k.targetAchievement ?? 0) < 80).length;
  const wonKpi = kpis.find(k => k.id === 'won_pipeline' || k.id === 'won_acv');
  const gapStr = wonKpi ? formatGap(wonKpi) : null;
  const gapPhrase = gapStr ? ` Revenue gap: ${gapStr}.` : '';

  if (atRiskCount >= 3) return `${atRiskCount} of ${kpis.length} KPIs below target.${gapPhrase} Immediate action required.`;
  if (atRiskCount >= 1) return `${atRiskCount} KPI${atRiskCount > 1 ? 's' : ''} need${atRiskCount === 1 ? 's' : ''} attention.${gapPhrase} Monitor closely.`;
  return `All KPIs tracking well.${gapPhrase ? gapPhrase : ' Maintain current execution strategy.'}`;
};

const computeAchievement = (kpis) => {
  if (!kpis?.length) return null;
  const vals = kpis.map(k => Math.min(k.targetAchievement ?? 0, 150));
  return Math.round(vals.reduce((s, v) => s + v, 0) / vals.length);
};

const STATUS = {
  atRisk:    { label: '🔴 AT RISK',   bg: 'rgba(239,68,68,0.14)',  color: '#ef4444', border: 'rgba(239,68,68,0.3)',  barColor: '#ef4444' },
  attention: { label: '🟡 ATTENTION', bg: 'rgba(234,179,8,0.14)',  color: '#eab308', border: 'rgba(234,179,8,0.3)',  barColor: '#eab308' },
  onTrack:   { label: '🟢 ON TRACK',  bg: 'rgba(16,185,129,0.14)', color: '#10b981', border: 'rgba(16,185,129,0.3)', barColor: '#10b981' },
};

export default function BusinessStatusBanner({ kpis }) {
  const loading = !kpis?.length;

  const atRiskCount   = loading ? 0 : kpis.filter(k => (k.targetAchievement ?? 0) < 80).length;
  const attentionCount = loading ? 0 : kpis.filter(k => { const p = k.targetAchievement ?? 0; return p >= 80 && p < 90; }).length;

  const status = atRiskCount >= 3 ? STATUS.atRisk
               : atRiskCount >= 1 || attentionCount >= 1 ? STATUS.attention
               : STATUS.onTrack;

  const narrative = loading ? 'Loading performance data...' : generateNarrative(kpis);
  const achievement = loading ? null : computeAchievement(kpis);

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      height: 48, padding: '0 16px',
      background: 'rgba(26,35,50,0.9)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderLeft: `3px solid ${status.barColor}`,
      borderRadius: 8,
      backdropFilter: 'blur(8px)',
      marginBottom: 10,
      gap: 12,
      flexShrink: 0,
    }}>

      {/* LEFT — status pill */}
      <span style={{
        padding: '3px 10px', borderRadius: 12,
        fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
        textTransform: 'uppercase', whiteSpace: 'nowrap',
        background: status.bg, color: status.color,
        border: `1px solid ${status.border}`,
        flexShrink: 0,
      }}>
        {loading ? '— —' : status.label}
      </span>

      {/* CENTER — narrative */}
      <span style={{
        flex: 1, fontSize: 12, color: '#94a3b8',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        textAlign: 'center',
      }}>
        {narrative}
      </span>

      {/* RIGHT — avg achievement % */}
      <div style={{ flexShrink: 0, textAlign: 'right' }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: '#fff', lineHeight: 1 }}>
          {loading ? '—' : `${achievement}%`}
        </span>
        <span style={{
          display: 'block', fontSize: 8, color: '#475569',
          textTransform: 'uppercase', letterSpacing: 0.5,
        }}>
          avg target
        </span>
      </div>
    </div>
  );
}
