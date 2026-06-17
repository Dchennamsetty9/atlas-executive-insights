/**
 * AIChatPanel — Redesigned executive AI assistant
 * Glass dark panel, gold/blue border glow, animated typing effect,
 * insight badge icons, question drop animation.
 * Wraps the existing /api/genie/* endpoints unchanged.
 */

import { useState, useRef, useCallback, useEffect, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

// ── Badge config per insight type ────────────────────────────────────────────
const BADGE = {
  data:        { icon: '📊', label: 'Data Insight',   color: '#3b82f6' },
  risk:        { icon: '⚠',  label: 'Risk',           color: '#ef4444' },
  opportunity: { icon: '🚀', label: 'Opportunity',    color: '#10b981' },
  trend:       { icon: '📈', label: 'Trend Detected', color: '#f59e0b' },
  default:     { icon: '◈',  label: 'Insight',        color: '#6366f1' },
};

function inferBadge(text = '') {
  const t = text.toLowerCase();
  if (t.includes('risk') || t.includes('below') || t.includes('decline')) return BADGE.risk;
  if (t.includes('opportunit') || t.includes('above') || t.includes('exceed')) return BADGE.opportunity;
  if (t.includes('trend') || t.includes('increas') || t.includes('growing')) return BADGE.trend;
  if (t.includes('data') || t.includes('metric') || t.includes('kpi'))       return BADGE.data;
  return BADGE.default;
}

// ── Typing animation ─────────────────────────────────────────────────────────
const TypingDots = () => (
  <div style={{ display: 'flex', gap: 4, alignItems: 'center', padding: '8px 0' }}>
    {[0, 1, 2].map(i => (
      <motion.div
        key={i}
        style={{ width: 6, height: 6, borderRadius: '50%', background: '#3b82f6' }}
        animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
        transition={{ duration: 1.2, delay: i * 0.2, repeat: Infinity }}
      />
    ))}
  </div>
);

// ── Message bubble ───────────────────────────────────────────────────────────
const MessageBubble = memo(({ msg }) => {
  const isUser = msg.role === 'user';
  const badge  = isUser ? null : inferBadge(msg.text);

  return (
    <motion.div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 14,
      }}
      initial={{ opacity: 0, y: isUser ? -16 : 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 24 }}
    >
      {/* Badge (AI messages only) */}
      {badge && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          marginBottom: 5,
          fontSize: 11,
          color: badge.color,
          fontWeight: 600,
          letterSpacing: 0.5,
        }}>
          <span>{badge.icon}</span>
          <span style={{ textTransform: 'uppercase' }}>{badge.label}</span>
        </div>
      )}

      {/* Bubble */}
      <div style={{
        maxWidth: '88%',
        padding: '10px 14px',
        borderRadius: isUser ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
        background: isUser
          ? 'linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%)'
          : 'rgba(255,255,255,0.05)',
        border: isUser
          ? '1px solid rgba(59,130,246,0.4)'
          : `1px solid ${badge?.color ?? '#ffffff'}22`,
        color: '#f1f5f9',
        fontSize: 13,
        lineHeight: 1.6,
        boxShadow: isUser
          ? '0 0 16px rgba(59,130,246,0.2)'
          : `0 0 12px ${badge?.color ?? '#ffffff'}11`,
      }}>
        {msg.text}
      </div>
    </motion.div>
  );
});
MessageBubble.displayName = 'MessageBubble';

// ── Suggestions chip ─────────────────────────────────────────────────────────
const SuggestionChip = memo(({ text, onClick }) => (
  <motion.button
    whileHover={{ scale: 1.03, borderColor: 'rgba(59,130,246,0.6)' }}
    whileTap={{ scale: 0.97 }}
    onClick={() => onClick(text)}
    style={{
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 20,
      padding: '5px 12px',
      color: '#94a3b8',
      fontSize: 12,
      cursor: 'pointer',
      whiteSpace: 'nowrap',
    }}
  >
    {text}
  </motion.button>
));
SuggestionChip.displayName = 'SuggestionChip';

// ── Main panel ───────────────────────────────────────────────────────────────
const AIChatPanel = ({ onAnalyzingChange, context, externalOpen, onOpenChange }) => {
  const [isOpen,           setIsOpen]           = useState(false);

  // Sync with external open state (Cmd+K)
  useEffect(() => {
    if (externalOpen !== undefined && externalOpen !== isOpen) {
      setIsOpen(externalOpen);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalOpen]);
  const [question,         setQuestion]         = useState('');
  const [messages,         setMessages]         = useState([]);
  const [loading,          setLoading]          = useState(false);
  const [statusMsg,        setStatusMsg]        = useState('');
  const [suggestions,      setSuggestions]      = useState([]);
  // Persist Genie conversation_id so follow-up questions have context.
  const [genieConvId,      setGenieConvId]      = useState(null);
  const messagesEndRef = useRef(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Detect whether a question is asking for interpretation (OpenAI) vs raw data (Genie)
  const isInsightQuestion = useCallback((text) => {
    const t = text.toLowerCase();
    return [
      'why', 'explain', 'what does', 'interpret', 'analyze', 'analyse',
      'what is driving', 'root cause', 'should i', 'recommend', 'what action',
      'what should', 'insight', 'pattern', 'anomaly',
    ].some(kw => t.includes(kw));
  }, []);

  // Context-aware suggestion sets per active tab/section
  const CONTEXT_SUGGESTIONS = {
    kpi:       ['Which KPIs are at risk this quarter?', 'Where are we vs. quota?', 'What is driving the close rate drop?'],
    pipeline:  ['What is the current pipeline coverage?', 'Show pipeline by segment', 'How has pipeline changed this month?'],
    forecast:  ['What is the forecast confidence?', 'What scenarios are most likely?', 'What drove the forecast revision?'],
    deals:     ['Which deals are most at risk?', 'Show me stalled deals over 30 days', 'What is in-quarter pipeline?'],
    analytics: ['What is MQL to SQL conversion?', 'Show ARR by geo', 'Which deal band closes fastest?'],
    default:   [
      'What is the current pipeline coverage?',
      'Which KPIs are at risk this quarter?',
      'How is close rate trending?',
      'What drove the change in won pipeline?',
      'Where are we vs. quota?',
    ],
  };

  const getSuggestions = useCallback((contextKey) => {
    return CONTEXT_SUGGESTIONS[contextKey] || CONTEXT_SUGGESTIONS.default;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleOpen = useCallback(async () => {
    setIsOpen(true);
    onOpenChange?.(true);
    const ctxKey = context?.activeTab ?? context?.section ?? 'default';
    const contextual = getSuggestions(ctxKey);
    setSuggestions(contextual);
    // Also try personalised suggestions from the backend
    try {
      const params = ctxKey !== 'default' ? `?context=${ctxKey}` : '';
      const res  = await fetch(`/api/genie/suggested-questions${params}`);
      const data = await res.json();
      if (data.questions?.length) setSuggestions(data.questions.slice(0, 5));
    } catch { /* keep context-aware fallback */ }
  }, [context, getSuggestions]);

  const askQuestion = useCallback(async (text) => {
    if (!text?.trim()) return;
    const q = text.trim();
    setMessages(prev => [...prev, { role: 'user', text: q }]);
    setQuestion('');
    setLoading(true);
    onAnalyzingChange?.(true);

    try {
      // Feature 7: /api/ai/ask — text-to-SQL → execute → interpret
      setStatusMsg('Generating query…');
      const t1 = setTimeout(() => setStatusMsg('Running query…'), 4000);
      const t2 = setTimeout(() => setStatusMsg('Interpreting results…'), 10000);

      let answer = '';
      let rows   = [];

      try {
        const res  = await fetch('/api/ai/ask', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ question: q }),
        });
        clearTimeout(t1);
        clearTimeout(t2);

        const body = await res.json();
        if (body.success && body.data) {
          answer = body.data.answer || 'No response received.';
          rows   = body.data.data   || [];
        } else {
          answer = body.detail || 'No response received.';
        }
      } catch (err) {
        clearTimeout(t1);
        clearTimeout(t2);
        throw err;
      }

      // Build display text — append a compact row count if data came back
      const displayText = rows.length > 0
        ? `${answer}\n\n_(${rows.length} row${rows.length !== 1 ? 's' : ''} returned)_`
        : answer;

      setMessages(prev => [...prev, { role: 'ai', text: displayText, source: 'data' }]);
    } catch {
      setMessages(prev => [...prev, {
        role: 'ai',
        text: 'Unable to reach AI service. Please try again.',
        source: 'error',
      }]);
    } finally {
      setLoading(false);
      setStatusMsg('');
      onAnalyzingChange?.(false);
    }
  }, [onAnalyzingChange, isInsightQuestion, genieConvId]);

  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    askQuestion(question);
  }, [askQuestion, question]);

  // FAB (closed state)
  if (!isOpen) {
    return (
      <motion.button
        style={{
          position: 'fixed',
          bottom: 28,
          right: 28,
          padding: '12px 20px',
          background: 'linear-gradient(135deg, #1d4ed8 0%, #7c3aed 100%)',
          color: '#fff',
          border: '1px solid rgba(99,102,241,0.5)',
          borderRadius: 40,
          fontSize: 14,
          fontWeight: 600,
          cursor: 'pointer',
          zIndex: 800,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          boxShadow: '0 0 24px rgba(99,102,241,0.3), 0 8px 24px rgba(0,0,0,0.4)',
        }}
        onClick={handleOpen}
        whileHover={{ scale: 1.06, boxShadow: '0 0 32px rgba(99,102,241,0.5)' }}
        whileTap={{ scale: 0.97 }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
      >
        <motion.span
          animate={{ opacity: [1, 0.6, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
        >✦</motion.span>
        Ask AI
        <span style={{
          fontSize: 9, fontWeight: 500,
          background: 'rgba(255,255,255,0.15)',
          borderRadius: 4, padding: '1px 5px',
          letterSpacing: 0.3,
        }}>⌘K</span>
      </motion.button>
    );
  }

  // Panel (open state)
  return (
    <motion.div
      style={{
        position: 'fixed',
        bottom: 28,
        right: 28,
        width: 420,
        maxHeight: 580,
        display: 'flex',
        flexDirection: 'column',
        zIndex: 800,
        borderRadius: 16,
        overflow: 'hidden',
        background: 'linear-gradient(160deg, rgba(17,24,39,0.98) 0%, rgba(13,20,40,0.99) 100%)',
        border: '1px solid rgba(245,158,11,0.25)',
        boxShadow: '0 0 40px rgba(245,158,11,0.08), 0 24px 64px rgba(0,0,0,0.6)',
        backdropFilter: 'blur(16px)',
      }}
      initial={{ opacity: 0, scale: 0.9, y: 20 }}
      animate={{ opacity: 1, scale: 1,   y: 0  }}
      exit={{    opacity: 0, scale: 0.9, y: 20 }}
      transition={{ type: 'spring', stiffness: 280, damping: 26 }}
    >
      {/* Header */}
      <div style={{
        padding: '14px 18px',
        background: 'linear-gradient(90deg, rgba(29,78,216,0.15) 0%, rgba(124,58,237,0.15) 100%)',
        borderBottom: '1px solid rgba(245,158,11,0.12)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <motion.div
            style={{
              width: 32, height: 32, borderRadius: '50%',
              background: 'linear-gradient(135deg, #1d4ed8, #7c3aed)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, border: '1px solid rgba(99,102,241,0.4)',
              boxShadow: '0 0 12px rgba(99,102,241,0.3)',
            }}
            animate={{ boxShadow: ['0 0 8px rgba(99,102,241,0.3)', '0 0 18px rgba(99,102,241,0.5)', '0 0 8px rgba(99,102,241,0.3)'] }}
            transition={{ duration: 2.5, repeat: Infinity }}
          >✦</motion.div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>AI Insights Assistant</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Genie · OpenAI · Atlas Intelligence</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {messages.length > 0 && (
            <button
              onClick={() => { setMessages([]); setGenieConvId(null); }}
              title="New conversation"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 8, color: '#64748b',
                fontSize: 10, padding: '3px 8px',
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              New chat
            </button>
          )}
          <button
            onClick={() => { setIsOpen(false); onOpenChange?.(false); }}
            style={{
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 8,
            color: '#94a3b8',
            width: 28, height: 28,
            cursor: 'pointer',
            fontSize: 15,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >×</button>
        </div>
      </div>

      {/* Messages area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px', minHeight: 0 }}>
        {messages.length === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{ marginBottom: 16 }}
          >
            <p style={{ fontSize: 12, color: '#475569', marginBottom: 12 }}>
              {context?.activeTab
                ? `Suggested questions for ${context.activeTab}:`
                : 'Ask anything about your KPIs, pipeline, or forecasts:'}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {suggestions.map((s, i) => (
                <SuggestionChip key={i} text={s} onClick={askQuestion} />
              ))}
            </div>
          </motion.div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} />
        ))}

        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#64748b', fontSize: 12 }}
          >
            <TypingDots />
            <span>{statusMsg || 'Thinking…'}</span>
          </motion.div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        style={{
          padding: '12px 18px 16px',
          borderTop: '1px solid rgba(255,255,255,0.06)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="input-dark"
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder="Ask about KPIs, pipeline, trends…"
            disabled={loading}
            style={{ flex: 1, fontSize: 13 }}
          />
          <motion.button
            type="submit"
            disabled={loading || !question.trim()}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            style={{
              padding: '8px 14px',
              background: loading || !question.trim()
                ? 'rgba(255,255,255,0.06)'
                : 'linear-gradient(135deg, #1d4ed8, #7c3aed)',
              border: '1px solid rgba(99,102,241,0.3)',
              borderRadius: 8,
              color: loading || !question.trim() ? '#475569' : '#fff',
              cursor: loading || !question.trim() ? 'not-allowed' : 'pointer',
              fontSize: 16,
              flexShrink: 0,
            }}
          >↑</motion.button>
        </div>
      </form>
    </motion.div>
  );
};

export default memo(AIChatPanel);
