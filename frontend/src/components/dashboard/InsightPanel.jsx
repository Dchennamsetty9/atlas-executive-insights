/**
 * InsightPanel — AI-generated hidden insight cards
 * Fetches /api/insights/hidden-patterns and renders severity-coloured
 * glass cards with icon, title, description, and recommendation.
 * Auto-refreshes whenever the KPI data changes (kpis prop update).
 */

import { useState, useEffect, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const SEVERITY_STYLE = {
  high:   { border: '#ef4444', glow: 'rgba(239,68,68,0.15)',   dot: '#ef4444' },
  medium: { border: '#f59e0b', glow: 'rgba(245,158,11,0.12)',  dot: '#f59e0b' },
  low:    { border: '#10b981', glow: 'rgba(16,185,129,0.10)',  dot: '#10b981' },
};

const DEFAULT_STYLE = { border: '#3b82f6', glow: 'rgba(59,130,246,0.10)', dot: '#3b82f6' };

const InsightCard = memo(({ insight, index }) => {
  const sty = SEVERITY_STYLE[insight.severity] ?? DEFAULT_STYLE;

  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0  }}
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
      }}
    >
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
            margin: 0, fontSize: 11, color: '#64748b',
            borderTop: '1px solid rgba(255,255,255,0.05)',
            paddingTop: 6, lineHeight: 1.5,
          }}>
            <span style={{ color: '#f59e0b', fontWeight: 600 }}>Recommendation: </span>
            {insight.recommendation}
          </p>
        )}
      </div>
    </motion.div>
  );
});
InsightCard.displayName = 'InsightCard';


const InsightPanel = ({ kpis = [], filters = {} }) => {
  const [insights,  setInsights]  = useState([]);
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
  // Re-fetch when filters or kpi data changes (kpis.length as proxy)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.product, filters.geo, filters.channel, kpis.length]);

  const highCount = insights.filter(i => i.severity === 'high').length;

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
          <span style={{ fontSize: 11, color: '#475569' }}>Analyzing…</span>
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

        {!loading && insights.length === 0 && (
          <span style={{ fontSize: 11, color: '#475569' }}>No patterns detected</span>
        )}

        <span style={{ fontSize: 12, color: '#475569' }}>{collapsed ? '▼' : '▲'}</span>
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
                Scanning KPI data for hidden patterns…
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 10,
                gridTemplateColumns: insights.length > 1 ? 'repeat(auto-fill, minmax(340px, 1fr))' : '1fr',
              }}>
                {insights.map((ins, i) => (
                  <InsightCard key={i} insight={ins} index={i} />
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default memo(InsightPanel);
