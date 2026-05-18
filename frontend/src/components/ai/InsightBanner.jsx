/**
 * InsightBanner — Auto-generated 2-3 sentence executive narrative summary.
 * Fetches /api/insights/hidden-patterns?include_narrative=true and displays
 * the OpenAI (or rule-based fallback) narrative with a severity-colored border.
 *
 * Shown at the very top of the dashboard main column.
 */

import { useState, useEffect } from 'react';

const SEV = {
  high:   { border: '#ef4444', bg: 'rgba(239,68,68,0.07)',    label: 'ACTION REQUIRED', icon: '⚠️' },
  medium: { border: '#f59e0b', bg: 'rgba(245,158,11,0.07)',   label: 'INSIGHT',         icon: '💡' },
  low:    { border: '#10b981', bg: 'rgba(16,185,129,0.07)',   label: 'ON TRACK',        icon: '✅' },
};

const InsightBanner = ({ filters }) => {
  const [narrative, setNarrative] = useState('');
  const [severity,  setSeverity]  = useState('medium');
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ include_narrative: 'true' });
        if (filters?.product && filters.product !== 'All') params.set('product', filters.product);
        if (filters?.geo     && filters.geo     !== 'All') params.set('geo',     filters.geo);
        if (filters?.channel && filters.channel !== 'All') params.set('channel', filters.channel);

        const res  = await fetch(`/api/insights/hidden-patterns?${params}`);
        const data = await res.json();
        if (cancelled) return;

        if (data.narrative) setNarrative(data.narrative);

        const insights = data.insights ?? [];
        if      (insights.some(i => i.severity === 'high'))   setSeverity('high');
        else if (insights.some(i => i.severity === 'medium')) setSeverity('medium');
        else                                                   setSeverity('low');
      } catch {
        if (!cancelled) setNarrative('');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => { cancelled = true; };
  }, [filters]);

  if (!loading && !narrative) return null;

  const s = SEV[severity] ?? SEV.medium;

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      borderLeft: `3px solid ${s.border}`,
      background: s.bg,
      borderRadius: '0 8px 8px 0',
      padding: '10px 14px',
      marginBottom: 10,
      minHeight: 38,
    }}>
      {loading ? (
        <>
          <div style={{ width: 14, height: 14, borderRadius: 3, background: 'rgba(255,255,255,0.08)', flexShrink: 0, animation: 'pulse 1.5s ease-in-out infinite' }} />
          <div style={{ flex: 1, height: 13, borderRadius: 4, background: 'rgba(255,255,255,0.06)', animation: 'pulse 1.5s ease-in-out infinite' }} />
        </>
      ) : (
        <>
          <span style={{ fontSize: 14, flexShrink: 0, marginTop: 1 }}>{s.icon}</span>
          <div style={{ flex: 1 }}>
            <span style={{
              fontSize: 9, fontWeight: 800, color: s.border,
              letterSpacing: 1.2, textTransform: 'uppercase', marginRight: 8,
            }}>
              {s.label} ·{' '}
            </span>
            <span style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.6 }}>
              {narrative}
            </span>
          </div>
        </>
      )}
    </div>
  );
};

export default InsightBanner;
