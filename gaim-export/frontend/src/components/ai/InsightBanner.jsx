/**
 * InsightBanner — AI-generated executive summary banner (Feature 1).
 * Calls GET /api/ai/executive-summary and displays status + headline + action.
 * Falls back to the hidden-patterns narrative if the new endpoint is unavailable.
 */

import { useState, useEffect } from 'react';

const STATUS_STYLE = {
  green:  { border: '#10b981', bg: 'rgba(16,185,129,0.07)',   label: 'ON TRACK',        icon: '✅' },
  yellow: { border: '#f59e0b', bg: 'rgba(245,158,11,0.07)',   label: 'WATCH CLOSELY',   icon: '💡' },
  red:    { border: '#ef4444', bg: 'rgba(239,68,68,0.07)',    label: 'ACTION REQUIRED', icon: '⚠️' },
};

const InsightBanner = ({ filters }) => {
  const [headline, setHeadline] = useState('');
  const [action,   setAction]   = useState('');
  const [status,   setStatus]   = useState('yellow');
  const [loading,  setLoading]  = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        // Build query params from filters
        const params = new URLSearchParams();
        if (filters?.product && filters.product !== 'All') params.set('product', filters.product);
        if (filters?.geo     && filters.geo     !== 'All') params.set('geo',     filters.geo);
        if (filters?.channel && filters.channel !== 'All') params.set('channel', filters.channel);

        // Feature 1: /api/ai/executive-summary
        const res  = await fetch(`/api/ai/executive-summary?${params}`);
        const body = await res.json();
        if (cancelled) return;

        if (body.success && body.data) {
          const { status: s, headline: h, action: a } = body.data;
          setStatus(s   || 'yellow');
          setHeadline(h || '');
          setAction(a   || '');
        } else {
          // Fallback: hidden-patterns narrative
          const fp = new URLSearchParams({ include_narrative: 'true' });
          if (filters?.product && filters.product !== 'All') fp.set('product', filters.product);
          if (filters?.geo     && filters.geo     !== 'All') fp.set('geo',     filters.geo);
          if (filters?.channel && filters.channel !== 'All') fp.set('channel', filters.channel);
          const fr   = await fetch(`/api/insights/hidden-patterns?${fp}`);
          const fd   = await fr.json();
          if (cancelled) return;
          setHeadline(fd.narrative || '');
          const sev = (fd.insights ?? []).some(i => i.severity === 'high') ? 'red'
                    : (fd.insights ?? []).some(i => i.severity === 'medium') ? 'yellow'
                    : 'green';
          setStatus(sev);
        }
      } catch {
        if (!cancelled) { setHeadline(''); setAction(''); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => { cancelled = true; };
  }, [filters]);

  if (!loading && !headline) return null;

  const s = STATUS_STYLE[status] ?? STATUS_STYLE.yellow;

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
              {headline}
            </span>
            {action && (
              <span style={{ fontSize: 11, color: s.border, fontWeight: 600, marginLeft: 8 }}>
                → {action}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default InsightBanner;
