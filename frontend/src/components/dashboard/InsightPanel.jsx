/**
 * InsightPanel â€” AI-generated hidden insight cards
 * Fetches /api/insights/hidden-patterns and renders severity-coloured
 * glass cards with icon, title, description, and recommendation.
 * Features: dismissability, "Why am I seeing this?", owner assignment.
 */

import { useState, useEffect, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const SEVERITY_STYLE = {
  high:   { border: '#ef4444', glow: 'rgba(239,68,68,0.15)',   dot: '#ef4444' },
  medium: { border: '#f59e0b', glow: 'rgba(245,158,11,0.12)',  dot: '#f59e0b' },
  low:    { border: '#10b981', glow: 'rgba(16,185,129,0.10)',  dot: '#10b981' },
};

const DEFAULT_STYLE = { border: '#3b82f6', glow: 'rgba(59,130,246,0.10)', dot: '#3b82f6' };

const InsightCard = memo(({ insight, index, onDismiss }) => {
  const sty = SEVERITY_STYLE[insight.severity] ?? DEFAULT_STYLE;
  const [showWhy, setShowWhy] = useState(false);
  const [owner, setOwner]     = useState(insight.owner || '');
  const [editOwner, setEditOwner] = useState(false);

  const saveOwner = (val) => {
    const trimmed = val.trim();
    setOwner(trimmed);
    setEditOwner(false);
    // Persist to backend if insight has an id
    if (insight.id && trimmed) {
      fetch(`/api/preferences/insight-owner`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: { insight_id: insight.id, owner: trimmed } }),
      }).catch(() => {});
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0  }}
      exit={{ opacity: 0, x: 16, scale: 0.95 }}
      transition={{ delay: index * 0.07, type: 'spring', stiffness: 260, damping: 24 }}
      style={{
        background: `linear-gradient(135deg, ${sty.glow} 0%, rgba(13,20,40,0.95) 100%)`,
        border: `1px solid ${sty.border}44`,
        borderLeft: `3px solid ${sty.border}`,
        borderRadius: 10,
        padding: '14px 16px',
        display: 'flex',
        gap: 14,
        alignItems: 'flex-start',
        position: 'relative',
      }}
    >
      {/* Dismiss button */}
      <button
        onClick={() => onDismiss(insight.id ?? index)}
        title="Dismiss this insight"
        style={{
          position: 'absolute', top: 8, right: 8,
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#334155', fontSize: 12, lineHeight: 1,
          padding: '2px 4px', borderRadius: 4,
          transition: 'color 0.15s',
        }}
        onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; }}
        onMouseLeave={e => { e.currentTarget.style.color = '#334155'; }}
      >
        {'\u2715'}
      </button>

      {/* Icon */}
      <span style={{ fontSize: 22, lineHeight: 1, flexShrink: 0, marginTop: 1 }}>
        {insight.icon || '📊'}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Severity dot + title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: sty.dot, flexShrink: 0,
            boxShadow: `0 0 6px ${sty.dot}`,
          }} />
          <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: '#f1f5f9', lineHeight: 1.3 }}>
            {insight.title}
          </p>
        </div>

        {/* Description */}
        <p style={{ margin: '0 0 6px', fontSize: 12, color: '#94a3b8', lineHeight: 1.5 }}>
          {insight.description}
        </p>

        {/* Recommendation */}
        {insight.recommendation && (
          <p style={{
            margin: '0 0 8px', fontSize: 11, color: '#64748b',
            borderTop: '1px solid rgba(255,255,255,0.05)',
            paddingTop: 6, lineHeight: 1.5,
          }}>
            <span style={{ color: '#f59e0b', fontWeight: 600 }}>Recommendation: </span>
            {insight.recommendation}
          </p>
        )}

        {/* Footer row: owner + "Why am I seeing this?" */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Owner */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10 }}>
            <span style={{ color: '#475569' }}>Owner:</span>
            {editOwner ? (
              <input
                autoFocus
                defaultValue={owner}
                onBlur={e => saveOwner(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && saveOwner(e.target.value)}
                style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                  color: '#f1f5f9', outline: 'none', fontFamily: 'inherit', width: 100,
                }}
              />
            ) : (
              <button
                onClick={() => setEditOwner(true)}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontSize: 10, color: owner ? '#94a3b8' : '#475569',
                  fontStyle: owner ? 'normal' : 'italic', padding: 0,
                }}
              >
                {owner || 'Assign\u2026'}
              </button>
            )}
          </div>

          {/* "Why am I seeing this?" toggle */}
          <button
            onClick={() => setShowWhy(s => !s)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 10, color: '#3b82f6', padding: 0,
              textDecoration: 'underline', textDecorationStyle: 'dotted',
            }}
          >
            {showWhy ? 'Hide explanation' : 'Why am I seeing this?'}
          </button>
        </div>

        {/* Why explanation */}
        <AnimatePresence initial={false}>
          {showWhy && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{ overflow: 'hidden' }}
            >
              <p style={{
                margin: '8px 0 0', fontSize: 11, color: '#64748b',
                background: 'rgba(59,130,246,0.05)',
                border: '1px solid rgba(59,130,246,0.1)',
                borderRadius: 6, padding: '6px 10px', lineHeight: 1.5,
              }}>
                {insight.why_text ||
                  `This insight was surfaced because ${insight.metric ? `${insight.metric} ` : ''}${
                    insight.description?.toLowerCase().includes('below') ? 'is below historical norms' :
                    insight.description?.toLowerCase().includes('above') ? 'is significantly above target' :
                    'shows an unusual pattern compared to recent periods'}.`}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
});
InsightCard.displayName = 'InsightCard';


const InsightPanel = ({ kpis = [], filters = {} }) => {
  const [insights,  setInsights]  = useState([]);
  const [dismissed, setDismissed] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem('atlas_dismissed_insights') || '[]')); }
    catch { return new Set(); }
  });
  const [loading,   setLoading]   = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.product && filters.product !== 'All') params.set('product', filters.product);
    if (filters.geo     && filters.geo     !== 'All') params.set('geo',     filters.geo);
    if (filters.channel && filters.channel !== 'All') params.set('channel', filters.channel);

    setLoading(true);
    fetch(`/api/insights/hidden-patterns?${params}`)
      .then(r => r.json())
      .then(d => setInsights(d.insights || []))
      .catch(() => setInsights([]))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.product, filters.geo, filters.channel, kpis.length]);

  const handleDismiss = (id) => {
    setDismissed(prev => {
      const next = new Set(prev);
      next.add(id);
      localStorage.setItem('atlas_dismissed_insights', JSON.stringify([...next]));
      return next;
    });
  };

  const visible = insights.filter(i => !dismissed.has(i.id ?? insights.indexOf(i)));
  const highCount = visible.filter(i => i.severity === 'high').length;

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: 14,
      padding: '14px 16px',
      marginBottom: 20,
    }}>
      {/* Header row */}
      <div
        onClick={() => setCollapsed(c => !c)}
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          cursor: 'pointer', userSelect: 'none', marginBottom: collapsed ? 0 : 14,
        }}
      >
        <span style={{ fontSize: 16 }}>🔬</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', flex: 1 }}>
          AI Hidden Insights
        </span>

        {loading && (
          <span style={{ fontSize: 11, color: '#475569' }}>Analyzing&hellip;</span>
        )}

        {!loading && highCount > 0 && (
          <span style={{
            background: 'rgba(239,68,68,0.15)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 20, padding: '1px 8px',
            fontSize: 11, fontWeight: 700, color: '#ef4444',
          }}>
            {highCount} High Priority
          </span>
        )}

        {!loading && dismissed.size > 0 && (
          <button
            onClick={e => { e.stopPropagation(); setDismissed(new Set()); localStorage.removeItem('atlas_dismissed_insights'); }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 10, color: '#475569', textDecoration: 'underline' }}
          >
            Restore {dismissed.size} dismissed
          </button>
        )}

        {!loading && visible.length === 0 && !dismissed.size && (
          <span style={{ fontSize: 11, color: '#475569' }}>No patterns detected</span>
        )}

        <span style={{ fontSize: 12, color: '#475569' }}>{collapsed ? '\u25BC' : '\u25B2'}</span>
      </div>

      {/* Cards */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            key="cards"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{    height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            {loading ? (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 0', color: '#475569', fontSize: 12 }}>
                <motion.div
                  style={{ width: 10, height: 10, borderRadius: '50%', background: '#3b82f6' }}
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 1.2, repeat: Infinity }}
                />
                Scanning KPI data for hidden patterns&hellip;
              </div>
            ) : (
              <AnimatePresence>
                <div style={{ display: 'grid', gap: 10,
                  gridTemplateColumns: visible.length > 1 ? 'repeat(auto-fill, minmax(340px, 1fr))' : '1fr',
                }}>
                  {visible.map((ins, i) => (
                    <InsightCard key={ins.id ?? i} insight={ins} index={i} onDismiss={handleDismiss} />
                  ))}
                </div>
              </AnimatePresence>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default memo(InsightPanel);
