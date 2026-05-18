// Genie AI Assistant Component
// Natural-language interface to the Metis - Sales KPI Analytics Genie Space.
// Supports multi-turn conversations: each follow-up stays in the same Genie context.

import React, { useState, useRef, useEffect } from 'react';
import './GenieAssistant.css';

const API = (path) => path; // relative paths â€” proxied to :8000 by Vite

const GenieAssistant = () => {
  const [isOpen, setIsOpen]             = useState(false);
  const [question, setQuestion]         = useState('');
  const [loading, setLoading]           = useState(false);
  const [messages, setMessages]         = useState([]);   // [{question, answer, sql, status}]
  const [conversationId, setConversationId] = useState(null);
  const [suggestions, setSuggestions]   = useState([]);
  const bottomRef = useRef(null);

  // Scroll to bottom whenever a new message arrives
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, loading]);

  // Load suggested questions when the panel first opens
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

  const startNewConversation = () => {
    setMessages([]);
    setConversationId(null);
    setQuestion('');
  };

  // Send a question â€” reuses existing conversationId for follow-ups
  const askQuestion = async (text) => {
    const q = text.trim();
    if (!q) return;

    setLoading(true);
    setQuestion('');

    // Optimistically append the question while we wait
    setMessages((prev) => [...prev, { question: q, answer: null, sql: null, status: 'loading' }]);

    try {
      const body = { question: q };
      if (conversationId) body.conversation_id = conversationId;

      const res  = await fetch(API('/api/genie/ask'), {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();

      // Persist the conversation ID so follow-ups stay in context
      if (data.conversation_id) setConversationId(data.conversation_id);

      setMessages((prev) => [
        ...prev.slice(0, -1),   // remove the optimistic placeholder
        {
          question: q,
          answer:   data.answer  || 'No narrative returned.',
          sql:      data.sql     || null,
          status:   data.status  || 'COMPLETED',
        },
      ]);
    } catch (err) {
      console.error('Genie error:', err);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { question: q, answer: `Error: ${err.message}`, sql: null, status: 'error' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    askQuestion(question);
  };

  /* â”€â”€ Collapsed FAB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  if (!isOpen) {
    return (
      <button className="genie-fab" onClick={handleOpen} title="Ask AI Assistant">
        <span className="genie-icon">&#x2728;</span>
        Ask AI
      </button>
    );
  }

  /* â”€â”€ Expanded panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  return (
    <div className="genie-container">
      {/* Header */}
      <div className="genie-header">
        <h3>
          <span className="genie-icon">&#x2728;</span>
          AI Insights&nbsp;
          <span className="genie-subtitle">Metis &mdash; Sales KPI Analytics</span>
        </h3>
        <div className="genie-header-actions">
          {messages.length > 0 && (
            <button
              className="genie-new-btn"
              onClick={startNewConversation}
              title="Start a new conversation"
            >
              New
            </button>
          )}
          <button className="genie-close" onClick={() => setIsOpen(false)}>&#215;</button>
        </div>
      </div>

      {/* Body */}
      <div className="genie-body">

        {/* Conversation history */}
        {messages.map((msg, i) => (
          <div key={i} className={`genie-turn ${msg.status === 'error' ? 'is-error' : ''}`}>
            <div className="genie-question"><strong>You:</strong> {msg.question}</div>
            {msg.status === 'loading' ? (
              <div className="genie-loading inline">
                <span className="spinner-small"></span>
                <em>Genie is translating to SQL and running the query&hellip;</em>
              </div>
            ) : (
              <div className="genie-response">
                <strong>Genie:</strong> {msg.answer}
              </div>
            )}
            {msg.sql && (
              <details className="genie-sql">
                <summary>View SQL</summary>
                <pre><code>{msg.sql}</code></pre>
              </details>
            )}
          </div>
        ))}

        {/* Suggestion chips â€” only when conversation is empty */}
        {messages.length === 0 && !loading && suggestions.length > 0 && (
          <div className="genie-suggestions">
            <p className="suggestions-title">&#x1F4A1; Try asking:</p>
            {suggestions.slice(0, 5).map((s, i) => (
              <button
                key={i}
                className="suggestion-button"
                onClick={() => askQuestion(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {/* Conversation context indicator */}
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
          placeholder={conversationId ? 'Ask a follow-up...' : 'Ask about your KPIs...'}
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
          {loading ? '...' : 'Ask'}
        </button>
      </form>
    </div>
  );
};

export default GenieAssistant;
