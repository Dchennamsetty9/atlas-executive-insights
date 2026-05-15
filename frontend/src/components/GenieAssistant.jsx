// Genie AI Assistant Component
// Provides natural language query interface to Metis Genie space

import React, { useState } from 'react';
import './GenieAssistant.css';

const GenieAssistant = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [suggestions, setSuggestions] = useState([]);

  // Load suggestions when panel opens
  const handleOpen = async () => {
    setIsOpen(true);
    if (suggestions.length === 0) {
      try {
        const response = await fetch('/api/genie/suggestions');
        const data = await response.json();
        setSuggestions(data.suggestions || []);
      } catch (error) {
        console.error('Error loading suggestions:', error);
      }
    }
  };

  // Ask Genie a question
  const askQuestion = async (questionText) => {
    setLoading(true);
    setAnswer(null);
    
    try {
      const response = await fetch('/api/genie/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: questionText })
      });
      
      const data = await response.json();
      setAnswer(data);
      setQuestion('');
    } catch (error) {
      console.error('Error asking Genie:', error);
      setAnswer({
        question: questionText,
        answer: 'Unable to get AI insights. Please try again.',
        status: 'error'
      });
    } finally {
      setLoading(false);
    }
  };

  // Handle suggestion click
  const handleSuggestionClick = (suggestion) => {
    setQuestion(suggestion);
    askQuestion(suggestion);
  };

  // Handle form submit
  const handleSubmit = (e) => {
    e.preventDefault();
    if (question.trim()) {
      askQuestion(question);
    }
  };

  if (!isOpen) {
    return (
      <button
        className="genie-fab"
        onClick={handleOpen}
        title="Ask AI Assistant"
      >
        <span className="genie-icon">✨</span>
        Ask AI
      </button>
    );
  }

  return (
    <div className="genie-container">
      <div className="genie-header">
        <h3>
          <span className="genie-icon">✨</span>
          AI Insights Assistant
        </h3>
        <button className="genie-close" onClick={() => setIsOpen(false)}>×</button>
      </div>

      <div className="genie-body">
        {/* Answer display */}
        {answer && (
          <div className={`genie-answer ${answer.status === 'error' ? 'error' : ''}`}>
            <div className="genie-question">
              <strong>Q:</strong> {answer.question}
            </div>
            <div className="genie-response">
              <strong>A:</strong> {answer.answer}
            </div>
            {answer.sql && (
              <details className="genie-sql">
                <summary>View SQL Query</summary>
                <pre><code>{answer.sql}</code></pre>
              </details>
            )}
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className="genie-loading">
            <div className="spinner"></div>
            <p>Thinking...</p>
          </div>
        )}

        {/* Suggestions */}
        {!answer && !loading && suggestions.length > 0 && (
          <div className="genie-suggestions">
            <p className="suggestions-title">💡 Try asking:</p>
            {suggestions.slice(0, 4).map((suggestion, index) => (
              <button
                key={index}
                className="suggestion-button"
                onClick={() => handleSuggestionClick(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        {/* Input form */}
        <form className="genie-form" onSubmit={handleSubmit}>
          <input
            type="text"
            className="genie-input"
            placeholder="Ask about your KPIs..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
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
    </div>
  );
};

export default GenieAssistant;
