// GenieAssistant.jsx
// Unified "Ask AI" panel — streams responses from /api/ai/ask/stream
// Intent routing (backend): DATA → Genie NL→SQL | INSIGHT → OpenAI | RECOMMENDATION → Atlas Intelligence

import React, { useState, useRef, useEffect, useCallback } from 'react';
import './GenieAssistant.css';

const API = (path) => path;

// ── Intent badge colours (matches backend classification) ────────────────────
const INTENT_STYLE = {
  DATA:           { label: 'Live Data',       color: '#8b5cf6' },
  INSIGHT:        { label: 'AI Insight',      color: '#10b981' },
  RECOMMENDATION: { label: 'Recommendation',  color: '#f59e0b' },
};

const GenieAssistant = () => {
  const [isOpen, setIsOpen]             = useState(false);
  const [question, setQuestion]         = useState('');
  const [loading, setLoading]           = useState(false);
  const [messages, setMessages]         = useState([]);
  // Each message: { question, answer, sql, status, intent }
  const [conversationId, setConversationId] = useState(null);
  const [suggestions, setSuggestions]   = useState([]);
  const bottomRef   = useRef(null);
  const readerRef   = useRef(null);   // holds the active ReadableStreamReader so we can cancel

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Load suggested questions on first open
  const handleOpen = async () => {
    setIsOpen(true);
    if (suggestions.length === 0) {
      try {
        const res  = await fetch(API('/api/genie/suggested-questions'));
        const data = await res.json();
        setSuggestions(data.questions || []);
      } catch (err) {
        console.error('Could not load suggestions:', err);
      }
    }
  };

  const startNewConversation = useCallback(() => {
    // Cancel any in-flight stream
    readerRef.current?.cancel();
    setMessages([]);
    setConversationId(null);
    setQuestion('');
    setLoading(false);
  }, []);

  // ── Core streaming ask ─────────────────────────────────────────────────────
  const askQuestion = useCallback(async (text) => {
    const q = text.trim();
    if (!q || loading) return;

    setLoading(true);
    setQuestion('');

    // Build history from current messages for multi-turn context
    const history = messages.map((m) => ({
      question: m.question,
      answer:   m.answer || '',
    }));

    // Optimistic placeholder
    const placeholder = { question: q, answer: '', sql: null, status: 'streaming', intent: null };
    setMessages((prev) => [...prev, placeholder]);

    try {
      const res = await fetch(API('/api/ai/ask/stream'), {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          question:        q,
          conversation_id: conversationId || undefined,
          history,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const reader  = res.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let buffer    = '';

      // Stream reading loop
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();   // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }

          switch (event.type) {
            case 'routing':
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  intent: event.intent,
                };
                return updated;
              });
              break;

            case 'progress':
              // Show progress text in the answer area while streaming hasn't started yet
              setMessages((prev) => {
                const updated = [...prev];
                const last    = updated[updated.length - 1];
                if (!last.answer) {
                  updated[updated.length - 1] = { ...last, answer: `⏳ ${event.text}` };
                }
                return updated;
              });
              break;

            case 'token':
              setMessages((prev) => {
                const updated = [...prev];
                const last    = updated[updated.length - 1];
                const current = last.answer.startsWith('⏳') ? '' : last.answer;
                updated[updated.length - 1] = { ...last, answer: current + event.text };
                return updated;
              });
              break;

            case 'sql':
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  sql: event.sql,
                };
                return updated;
              });
              break;

            case 'done':
              if (event.conversation_id) setConversationId(event.conversation_id);
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  status: 'COMPLETED',
                };
                return updated;
              });
              break;

            case 'error':
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  answer: `Error: ${event.text}`,
                  status: 'error',
                };
                return updated;
              });
              break;

            default:
              break;
          }
        }
      }
    } catch (err) {
      console.error('Ask AI stream error:', err);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          answer: `Error: ${err.message}`,
          status: 'error',
        };
        return updated;
      });
    } finally {
      readerRef.current = null;
      setLoading(false);
    }
  }, [loading, messages, conversationId]);

  const handleSubmit = (e) => {
    e.preventDefault();
    askQuestion(question);
  };

  // ── Collapsed FAB ──────────────────────────────────────────────────────────
  if (!isOpen) {
    return (
      <button className="genie-fab" onClick={handleOpen} title="Ask AI">
        <span className="genie-icon">&#x2728;</span>
        Ask AI
      </button>
    );
  }

  // ── Expanded panel ─────────────────────────────────────────────────────────
  return (
    <div className="genie-container">
      {/* Header */}
      <div className="genie-header">
        <h3>
          <span className="genie-icon">&#x2728;</span>
          AI Insights Assistant&nbsp;
          <span className="genie-subtitle">Genie &middot; OpenAI &middot; Atlas Intelligence</span>
        </h3>
        <div className="genie-header-actions">
          {messages.length > 0 && (
            <button className="genie-new-btn" onClick={startNewConversation} title="New conversation">
              New
            </button>
          )}
          <button className="genie-close" onClick={() => setIsOpen(false)}>&#215;</button>
        </div>
      </div>

      {/* Body */}
      <div className="genie-body">

        {/* Conversation history */}
        {messages.map((msg, i) => {
          const intentMeta = INTENT_STYLE[msg.intent] || null;
          return (
            <div key={i} className={`genie-turn ${msg.status === 'error' ? 'is-error' : ''}`}>

              {/* User question */}
              <div className="genie-question">
                <strong>You:</strong> {msg.question}
              </div>

              {/* Intent badge */}
              {intentMeta && (
                <div className="genie-intent-badge" style={{ color: intentMeta.color }}>
                  &#9679; {intentMeta.label}
                </div>
              )}

              {/* Answer / streaming / loading */}
              {msg.status === 'streaming' && !msg.answer ? (
                <div className="genie-loading inline">
                  <span className="spinner-small"></span>
                  <em>Thinking...</em>
                </div>
              ) : (
                <div className="genie-response">
                  <strong>Atlas:</strong>{' '}
                  <span style={{ whiteSpace: 'pre-wrap' }}>{msg.answer}</span>
                  {msg.status === 'streaming' && (
                    <span className="genie-cursor">▍</span>
                  )}
                </div>
              )}

              {/* SQL disclosure */}
              {msg.sql && (
                <details className="genie-sql">
                  <summary>View SQL</summary>
                  <pre><code>{msg.sql}</code></pre>
                </details>
              )}
            </div>
          );
        })}

        {/* Suggestion chips — only when no conversation yet */}
        {messages.length === 0 && !loading && suggestions.length > 0 && (
          <div className="genie-suggestions">
            <p className="suggestions-title">&#x1F4A1; Try asking:</p>
            {suggestions.slice(0, 5).map((s, i) => (
              <button key={i} className="suggestion-button" onClick={() => askQuestion(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        {/* Multi-turn indicator */}
        {conversationId && (
          <p className="genie-context-note">
            &#x1F4AC; Conversation active &mdash; follow-up questions keep context.
          </p>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form className="genie-form" onSubmit={handleSubmit}>
        <input
          type="text"
          className="genie-input"
          placeholder={conversationId ? 'Ask a follow-up...' : 'Ask about KPIs, pipeline, or forecasts...'}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <button
          type="submit"
          className="genie-submit"
          disabled={loading || !question.trim()}
        >
          {loading ? '...' : '→'}
        </button>
      </form>
    </div>
  );
};

export default GenieAssistant;
