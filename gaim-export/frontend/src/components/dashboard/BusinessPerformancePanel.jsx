/**
 * BusinessPerformancePanel — Executive KPI health summary card.
 * Matches the design in the screenshot: dark card with status badge,
 * filter chips, target achievement %, 4 sub-cards, and bottom alert bar.
 *
 * Props:
 *   kpis          — array of KPI objects (value, target, targetAchievement, id, title)
 *   filters       — current filter state from FilterContext
 *   onStatusFilter — optional callback(status) — called when a sub-card is clicked
 *                    ('at_risk' | 'on_track' | 'exceeding' | null to clear)
 */

import { useMemo } from 'react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { useTheme } from '../../hooks/useTheme';

const THRESHOLDS = { exceeding: 110, onTrack: 90 };

function classify(kpis) {
  let atRisk = 0, onTrack = 0, exceeding = 0;
  (kpis || []).forEach(k => {
    const p = k.targetAchievement ?? 0;
    if (p >= THRESHOLDS.exceeding)      exceeding++;
    else if (p >= THRESHOLDS.onTrack)   onTrack++;
    else                                atRisk++;
  });
  return { atRisk, onTrack, exceeding, total: (kpis || []).length };
}

function avgAchievement(kpis) {
  if (!kpis?.length) return 0;
  const sum = kpis.reduce((s, k) => s + Math.min(k.targetAchievement ?? 0, 150), 0);
  return Math.round(sum / kpis.length);
}

/** Derive a weekly-level sparkline from the avg achievement of all KPIs.
 *  Uses each KPI's trend_data (array of historical weekly values) if available,
 *  otherwise approximates from current attainment. */
function buildSparkline(kpis) {
  const POINTS = 8;
  // Collect trend_data arrays from KPIs that have them
  const series = (kpis || []).filter(k => Array.isArray(k.trend_data) && k.trend_data.length >= 2);
  if (!series.length) {
    // Fallback: manufacture a flat-ish line at current avg
    const avg = avgAchievement(kpis);
    return Array.from({ length: POINTS }, (_, i) => ({ v: avg + (Math.random() - 0.5) * 3 }));
  }
  // Average across series at each index (normalised to % of max in each series)
  const len = Math.max(POINTS, Math.min(...series.map(k => k.trend_data.length)));
  return Array.from({ length: Math.min(POINTS, len) }, (_, i) => {
    const idx = Math.round((i / (Math.min(POINTS, len) - 1)) * (series[0].trend_data.length - 1));
    const avg = series.reduce((s, k) => {
      const tgt = k.target || 1;
      return s + Math.min((k.trend_data[idx] ?? k.value) / tgt * 100, 150);
    }, 0) / series.length;
    return { v: Math.round(avg) };
  });
}

const CHIP_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4',
];

function ActiveChips({ filters, isDark }) {
  const chips = [];
  const SKIP = new Set(['All', '', null, undefined, 'Plan', 'QTD']);
  const LABELS = { geo: null, channel: null, product: null, fuel: null, purchaseType: 'Type', targetVersion: 'Target', period: null };
  let colorIdx = 0;
  Object.entries(filters || {}).forEach(([key, val]) => {
    if (SKIP.has(val) || !(key in LABELS)) return;
    chips.push({ label: val, color: CHIP_COLORS[colorIdx++ % CHIP_COLORS.length] });
  });
  if (!chips.length) return null;
  const arrowColor = isDark ? '#475569' : '#64748b';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
      <span style={{ fontSize: 10, color: arrowColor }}>▼</span>
      {chips.map((c, i) => (
        <span key={i} style={{
          padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 600,
          background: `${c.color}22`, color: c.color,
          border: `1px solid ${c.color}44`,
        }}>{c.label}</span>
      ))}
    </div>
  );
}

const CARD_DEFS = [
  {
    key: 'total',
    icon: '◎',
    label: 'Total Metrics',
    color: '#94a3b8',
    sub: null,
    getValue: c => c.total,
  },
  {
    key: 'onTrack',
    icon: '↗',
    label: 'On Track',
    color: '#10b981',
    sub: '90-110% of target',
    getValue: c => c.onTrack,
  },
  {
    key: 'exceeding',
    icon: '↗',
    label: 'Exceeding',
    color: '#3b82f6',
    sub: '>110% of target',
    getValue: c => c.exceeding,
  },
  {
    key: 'atRisk',
    icon: '⊙',
    label: 'At Risk',
    color: '#ef4444',
    sub: '<90% of target',
    getValue: c => c.atRisk,
  },
];

export default function BusinessPerformancePanel({ kpis, filters, onStatusFilter }) {
  const isDark = useTheme();
  const C = isDark ? {
    panelBg:     'linear-gradient(145deg, rgba(15,23,42,0.98) 0%, rgba(20,30,55,0.98) 100%)',
    panelBorder: 'rgba(255,255,255,0.08)',
    title:       '#f1f5f9',
    subtitle:    '#64748b',
    achieve:     '#f1f5f9',
    achieveSub:  '#475569',
    subCardBg:   'rgba(255,255,255,0.02)',
    subCardBdr:  'rgba(255,255,255,0.06)',
    iconEmpty:   '#334155',
    labelEmpty:  '#64748b',
    valueEmpty:  '#334155',
    subText:     '#475569',
    alertTxt:    '#fca5a5',
  } : {
    panelBg:     'linear-gradient(145deg, #ffffff 0%, #f8fafc 100%)',
    panelBorder: 'rgba(0,0,0,0.09)',
    title:       '#0f172a',
    subtitle:    '#475569',
    achieve:     '#0f172a',
    achieveSub:  '#64748b',
    subCardBg:   'rgba(0,0,0,0.02)',
    subCardBdr:  'rgba(0,0,0,0.07)',
    iconEmpty:   '#94a3b8',
    labelEmpty:  '#94a3b8',
    valueEmpty:  '#94a3b8',
    subText:     '#64748b',
    alertTxt:    '#b91c1c',
  };

  const loading = !kpis?.length;
  const counts  = useMemo(() => classify(kpis), [kpis]);
  const avg     = useMemo(() => avgAchievement(kpis), [kpis]);
  const sparkline = useMemo(() => buildSparkline(kpis), [kpis]);

  // Trend: compare avg attainment of the first half vs second half of kpis' trend_data
  const trendPct = useMemo(() => {
    const series = (kpis || []).filter(k => Array.isArray(k.trend_data) && k.trend_data.length >= 4);
    if (!series.length) return null;
    const avgSlice = (arr, start, end) =>
      arr.slice(start, end).reduce((s, v) => s + v, 0) / (end - start);
    const k = series[0];
    const mid = Math.floor(k.trend_data.length / 2);
    const early = avgSlice(k.trend_data, 0, mid);
    const late  = avgSlice(k.trend_data, mid, k.trend_data.length);
    return early > 0 ? Math.round(((late - early) / early) * 100) : null;
  }, [kpis]);

  const overallStatus = loading             ? null
    : counts.atRisk >= Math.ceil(counts.total / 2) ? 'atRisk'
    : counts.atRisk >= 1                           ? 'attention'
    : 'onTrack';

  const BADGE = {
    atRisk:    { label: '✕ AT RISK',    bg: '#ef4444',             color: '#fff' },
    attention: { label: '⚠ ATTENTION',  bg: '#f59e0b',             color: '#fff' },
    onTrack:   { label: '✓ ON TRACK',   bg: '#10b981',             color: '#fff' },
  };

  const badge = overallStatus ? BADGE[overallStatus] : null;

  // period label
  const periodLabel = {
    QTD: 'Quarter-to-date', MTD: 'Month-to-date',
    YTD: 'Year-to-date', L30D: 'Last 30 days', L90D: 'Last 90 days',
  }[filters?.period] ?? 'Quarter-to-date';

  const alertCount = counts.atRisk;

  return (
    <div style={{
      background: C.panelBg,
      border: `1px solid ${C.panelBorder}`,
      borderRadius: 12,
      padding: '20px 24px',
      marginBottom: 16,
      boxShadow: isDark
        ? '0 4px 24px rgba(0,0,0,0.4)'
        : '0 2px 16px rgba(0,0,0,0.06)',
    }}>

      {/* ── Top row ──────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>

        {/* Left — title + subtitle + chips */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{ fontSize: 18, fontWeight: 800, color: C.title, letterSpacing: '-0.3px' }}>
              Business Performance
            </span>
            {badge && (
              <span style={{
                padding: '3px 10px', borderRadius: 20,
                fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
                background: badge.bg, color: badge.color,
                textTransform: 'uppercase',
              }}>
                {loading ? '…' : badge.label}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: C.subtitle }}>
              {periodLabel} performance vs. targets
            </span>
            <ActiveChips filters={filters} isDark={isDark} />
          </div>
        </div>

        {/* Right — avg achievement + sparkline + trend arrow */}
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          {/* Sparkline behind the % */}
          <div style={{ position: 'relative', display: 'inline-block' }}>
            {/* Ghost sparkline */}
            <div style={{ position: 'absolute', inset: 0, opacity: 0.18, pointerEvents: 'none' }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sparkline} margin={{ top: 2, bottom: 2, left: 2, right: 2 }}>
                  <Line
                    type="monotone" dataKey="v" dot={false} strokeWidth={2}
                    stroke={avg >= 100 ? '#10b981' : avg >= 90 ? '#f59e0b' : '#ef4444'}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {/* Achievement % — colored by status */}
            <div style={{
              fontSize: 36, fontWeight: 800, lineHeight: 1,
              color: loading ? C.achieve
                : avg >= 100 ? '#10b981'
                : avg >= 90  ? '#f59e0b'
                : '#ef4444',
            }}>
              {loading ? '—' : `${avg}%`}
            </div>
          </div>
          {/* Trend arrow */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4, marginTop: 2 }}>
            {trendPct !== null && (
              <span style={{
                fontSize: 11, fontWeight: 700,
                color: trendPct >= 0 ? '#10b981' : '#ef4444',
              }}>
                {trendPct >= 0 ? '↑' : '↓'} {Math.abs(trendPct)}%
              </span>
            )}
            <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: 1, color: C.achieveSub }}>
              vs prior period
            </div>
          </div>
          <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: 1, color: C.achieveSub, marginTop: 1 }}>
            Target Achievement
          </div>
        </div>
      </div>

      {/* ── 4 sub-cards ──────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 12 }}>
        {CARD_DEFS.map(cd => {
          const val = loading ? '—' : cd.getValue(counts);
          const isEmpty = val === 0;
          const isClickable = !!onStatusFilter && cd.key !== 'total' && val > 0;
          const statusKey = cd.key === 'atRisk' ? 'at_risk' : cd.key === 'onTrack' ? 'on_track' : cd.key === 'exceeding' ? 'exceeding' : null;
          return (
            <div
              key={cd.key}
              onClick={isClickable && statusKey ? () => onStatusFilter(statusKey) : undefined}
              title={isClickable ? `Click to filter to ${cd.label} metrics` : undefined}
              style={{
                background: isEmpty ? C.subCardBg : `${cd.color}11`,
                border: `1px solid ${isEmpty ? C.subCardBdr : cd.color + '30'}`,
                borderRadius: 10,
                padding: '14px 16px',
                cursor: isClickable ? 'pointer' : 'default',
                transition: isClickable ? 'transform 0.1s, box-shadow 0.1s' : 'none',
              }}
              onMouseEnter={e => { if (isClickable) { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = `0 4px 12px ${cd.color}22`; } }}
              onMouseLeave={e => { if (isClickable) { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; } }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <span style={{ fontSize: 14, color: isEmpty ? C.iconEmpty : cd.color, lineHeight: 1 }}>
                  {cd.icon}
                </span>
                <span style={{ fontSize: 11, color: isEmpty ? C.labelEmpty : C.subtitle, fontWeight: 600 }}>
                  {cd.label}
                </span>
                {isClickable && (
                  <span style={{ fontSize: 8, color: cd.color, marginLeft: 'auto', opacity: 0.7 }}>↗ filter</span>
                )}
              </div>
              <div style={{ fontSize: 30, fontWeight: 800, color: isEmpty ? C.valueEmpty : cd.color, lineHeight: 1 }}>
                {loading ? '—' : val}
              </div>
              {cd.sub && (
                <div style={{ fontSize: 9, color: C.subText, marginTop: 4, textTransform: 'uppercase', letterSpacing: 0.3 }}>
                  {cd.sub}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Alert bar (only when at-risk KPIs exist) ─────────────────── */}
      {!loading && alertCount > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 14px',
          background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 8,
        }}>
          <span style={{ color: '#ef4444', fontSize: 14 }}>⊙</span>
          <span style={{ fontSize: 12, color: C.alertTxt, fontWeight: 500 }}>
            {alertCount} metric{alertCount > 1 ? 's' : ''} need{alertCount === 1 ? 's' : ''} immediate attention
          </span>
        </div>
      )}
    </div>
  );
}
