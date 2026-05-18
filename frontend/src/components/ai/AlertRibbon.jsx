/**
 * AlertRibbon — Proactive alert system derived client-side from KPI data.
 * Shows RISK, ATTENTION, OPPORTUNITY, and INSIGHT ribbons.
 * Each alert is individually dismissible. Clears when kpis change.
 */

import { useState, useMemo, useEffect } from 'react';

const TYPE = {
  RISK:        { color: '#ef4444', bg: 'rgba(239,68,68,0.09)',    border: 'rgba(239,68,68,0.25)',    prefix: '🔴 RISK'        },
  ATTENTION:   { color: '#f59e0b', bg: 'rgba(245,158,11,0.09)',   border: 'rgba(245,158,11,0.25)',   prefix: '🟡 ATTENTION'   },
  OPPORTUNITY: { color: '#10b981', bg: 'rgba(16,185,129,0.09)',   border: 'rgba(16,185,129,0.25)',   prefix: '🟢 OPPORTUNITY' },
  INSIGHT:     { color: '#3b82f6', bg: 'rgba(59,130,246,0.09)',   border: 'rgba(59,130,246,0.25)',   prefix: '🔵 INSIGHT'     },
};

function deriveAlerts(kpis) {
  if (!kpis?.length) return [];

  const find = (kw) =>
    kpis.find(k =>
      k.id?.toLowerCase().includes(kw) || k.title?.toLowerCase().includes(kw)
    );

  const pct = (k) => (k && k.target ? (k.value / k.target) * 100 : null);

  const alerts = [];

  // ── RISK: coverage below 2x ──────────────────────────────────
  const coverage = find('coverage');
  if (coverage && typeof coverage.value === 'number' && coverage.value < 2.0) {
    alerts.push({
      type: 'RISK',
      text: `Coverage at ${coverage.value.toFixed(1)}x — pipeline may be insufficient to hit quarter target.`,
    });
  }

  // ── ATTENTION: revenue materially behind target ──────────────
  const wonPipeline = find('won_pipeline') || find('pipeline');
  const wpPct = pct(wonPipeline);
  if (wpPct !== null && wpPct < 75) {
    alerts.push({
      type: 'ATTENTION',
      text: `Revenue is ${(100 - wpPct).toFixed(0)}% behind target — deal velocity needs immediate attention.`,
    });
  }

  // ── INSIGHT: Win Rate healthy but Close Rate low (timing) ────
  const winRate   = find('win_rate');
  const closeRate = find('close_rate');
  const wr = winRate?.value;
  const cr = closeRate?.value;
  if (wr && cr && wr > 60 && cr < 40) {
    alerts.push({
      type: 'INSIGHT',
      text: `Win Rate ${wr.toFixed(0)}% is healthy. Low Close Rate (${cr.toFixed(0)}%) is a timing signal — deals are open, not lost.`,
    });
  }

  // ── OPPORTUNITY: any KPI beating target by >10% ──────────────
  const overperformer = kpis.find(
    k => k.target && typeof k.value === 'number' && k.value / k.target > 1.10
  );
  if (overperformer) {
    const uplift = ((overperformer.value / overperformer.target - 1) * 100).toFixed(0);
    alerts.push({
      type: 'OPPORTUNITY',
      text: `${overperformer.title} is ${uplift}% above target — identify the driver and replicate it.`,
    });
  }

  return alerts;
}

const AlertRibbon = ({ kpis }) => {
  const alerts = useMemo(() => deriveAlerts(kpis), [kpis]);

  // Reset dismissals whenever new alerts arrive (data refresh)
  const [dismissed, setDismissed] = useState(new Set());
  useEffect(() => { setDismissed(new Set()); }, [kpis]);

  const visible = alerts.filter((_, i) => !dismissed.has(i));
  if (!visible.length) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 10 }}>
      {visible.map((alert) => {
        const origIdx = alerts.indexOf(alert);
        const s = TYPE[alert.type];
        return (
          <div
            key={origIdx}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: s.bg,
              border: `1px solid ${s.border}`,
              borderRadius: 7,
              padding: '6px 10px',
            }}
          >
            <span style={{
              fontSize: 10, fontWeight: 800, color: s.color,
              whiteSpace: 'nowrap', letterSpacing: 0.8, flexShrink: 0,
            }}>
              {s.prefix}
            </span>
            <span style={{ flex: 1, fontSize: 12, color: '#cbd5e1', lineHeight: 1.4 }}>
              {alert.text}
            </span>
            <button
              onClick={() => setDismissed(d => new Set([...d, origIdx]))}
              title="Dismiss"
              style={{
                background: 'none', border: 'none', color: '#475569',
                cursor: 'pointer', fontSize: 15, lineHeight: 1,
                padding: '0 4px', flexShrink: 0,
              }}
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
};

export default AlertRibbon;
