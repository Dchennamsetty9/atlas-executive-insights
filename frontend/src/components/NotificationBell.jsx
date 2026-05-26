/**
 * NotificationBell — polls /api/notifications/count every 60s,
 * shows unread badge, and renders a dropdown of recent in-app notifications.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
const LEVEL_COLORS = {
  critical: '#ef4444',
  warning:  '#f59e0b',
  info:     '#3b82f6',
};

const BellIcon = ({ hasUnread }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    {hasUnread && <circle cx="18" cy="6" r="4" fill="#ef4444" stroke="none" />}
  </svg>
);

const NotificationBell = () => {
  const [count,         setCount]         = useState(0);
  const [open,          setOpen]          = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [loading,       setLoading]       = useState(false);
  const [testOpen,      setTestOpen]      = useState(false);
  const [testEmail,     setTestEmail]     = useState('');
  const [testSending,   setTestSending]   = useState(false);
  const [testSent,      setTestSent]      = useState(false);
  const dropdownRef = useRef(null);

  // Poll unread count every 60s
  useEffect(() => {
    const fetchCount = async () => {
      try {
        const res  = await fetch('/api/notifications/count');
        const data = await res.json();
        setCount(data.unread_count ?? 0);
      } catch { /* ignore */ }
    };
    fetchCount();
    const id = setInterval(fetchCount, 60_000);
    return () => clearInterval(id);
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const loadNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const res  = await fetch('/api/notifications?limit=20');
      const data = await res.json();
      setNotifications(data.notifications ?? []);
    } catch {
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleOpen = () => {
    setOpen(o => {
      if (!o) loadNotifications();
      return !o;
    });
  };

  const markRead = async (id) => {
    try { await fetch(`/api/notifications/read/${id}`, { method: 'POST' }); } catch { /* ignore */ }
    setNotifications(prev => prev.map(n => n.notification_id === id ? { ...n, is_read: true } : n));
    setCount(c => Math.max(0, c - 1));
  };

  const markAllRead = async () => {
    try { await fetch('/api/notifications/read-all', { method: 'POST' }); } catch { /* ignore */ }
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
    setCount(0);
  };

  const sendTest = async () => {
    setTestSending(true);
    try {
      await fetch('/api/notifications/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message:  'This is a test alert from Atlas Executive Insights.',
          level:    'warning',
          email_to: testEmail.trim() || null,
        }),
      });
      setTestSent(true);
      setTestOpen(false);
      setTestEmail('');
      setTimeout(() => setTestSent(false), 3000);
    } catch { /* ignore */ }
    finally { setTestSending(false); }
  };

  return (
    <div ref={dropdownRef} style={{ position: 'relative' }}>
      {/* Bell button */}
      <button
        onClick={handleOpen}
        title="Notifications"
        style={{
          position: 'relative',
          background: open ? 'rgba(59,130,246,0.1)' : 'transparent',
          border: '1px solid ' + (open ? 'rgba(59,130,246,0.3)' : 'rgba(255,255,255,0.08)'),
          borderRadius: 8,
          color: count > 0 ? '#f59e0b' : '#64748b',
          width: 32, height: 32,
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'all 0.15s',
        }}
      >
        <BellIcon hasUnread={count > 0} />
        {count > 0 && (
          <span style={{
            position: 'absolute', top: -4, right: -4,
            background: '#ef4444',
            color: '#fff',
            fontSize: 9, fontWeight: 700, lineHeight: 1,
            borderRadius: 10,
            padding: '2px 4px',
            minWidth: 16, textAlign: 'center',
          }}>
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {/* Dropdown */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0,  scale: 1    }}
            exit={{    opacity: 0, y: -8, scale: 0.96 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            style={{
              position: 'absolute', top: '110%', right: 0,
              width: 340,
              background: 'rgba(13,20,40,0.98)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 12,
              overflow: 'hidden',
              boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
              zIndex: 900,
            }}
          >
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 14px',
              borderBottom: '1px solid rgba(255,255,255,0.07)',
            }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>Notifications</span>
              {count > 0 && (
                <button
                  onClick={markAllRead}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 10, color: '#3b82f6' }}
                >
                  Mark all read
                </button>
              )}
            </div>

            {/* List */}
            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
              {loading ? (
                <div style={{ padding: '16px', textAlign: 'center', fontSize: 12, color: '#475569' }}>
                  Loading…
                </div>
              ) : notifications.length === 0 ? (
                <div style={{ padding: '24px 16px', textAlign: 'center', fontSize: 12, color: '#475569' }}>
                  No notifications
                </div>
              ) : (
                notifications.map(n => (
                  <div
                    key={n.notification_id}
                    onClick={() => !n.is_read && markRead(n.notification_id)}
                    style={{
                      display: 'flex', alignItems: 'flex-start', gap: 10,
                      padding: '10px 14px',
                      borderBottom: '1px solid rgba(255,255,255,0.04)',
                      background: n.is_read ? 'transparent' : 'rgba(59,130,246,0.04)',
                      cursor: n.is_read ? 'default' : 'pointer',
                      transition: 'background 0.15s',
                    }}
                  >
                    {/* Level dot */}
                    <span style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: LEVEL_COLORS[n.level] ?? '#475569',
                      flexShrink: 0, marginTop: 4,
                      boxShadow: n.is_read ? 'none' : `0 0 6px ${LEVEL_COLORS[n.level] ?? '#475569'}`,
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: '0 0 2px', fontSize: 12, fontWeight: n.is_read ? 400 : 700, color: '#f1f5f9' }}>
                        {n.title}
                      </p>
                      <p style={{ margin: 0, fontSize: 11, color: '#64748b', lineHeight: 1.4 }}>
                        {n.body}
                      </p>
                      <p style={{ margin: '3px 0 0', fontSize: 10, color: '#334155' }}>
                        {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                      </p>
                    </div>
                    {!n.is_read && (
                      <span style={{
                        width: 7, height: 7, borderRadius: '50%',
                        background: '#3b82f6', flexShrink: 0, marginTop: 4,
                      }} />
                    )}
                  </div>
                ))
              )}
            </div>

            {/* Footer — test alerts */}
            <div style={{
              borderTop: '1px solid rgba(255,255,255,0.07)',
              padding: '8px 14px',
            }}>
              {testSent ? (
                <p style={{ margin: 0, fontSize: 10, color: '#10b981', fontWeight: 600, textAlign: 'center' }}>
                  &#10003; Test alert sent!
                </p>
              ) : testOpen ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <p style={{ margin: 0, fontSize: 10, color: '#94a3b8' }}>
                    Sends to <strong style={{ color: '#818cf8' }}>Slack</strong> (if configured)
                    {' '}+ optional email:
                  </p>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      type="email"
                      autoFocus
                      placeholder="email@goto.com (optional)"
                      value={testEmail}
                      onChange={e => setTestEmail(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && sendTest()}
                      style={{
                        flex: 1, fontSize: 10, padding: '4px 8px', borderRadius: 5,
                        background: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.12)',
                        color: '#f1f5f9', outline: 'none', fontFamily: 'inherit',
                      }}
                    />
                    <button
                      onClick={sendTest}
                      disabled={testSending}
                      style={{
                        fontSize: 10, padding: '4px 10px', borderRadius: 5,
                        background: testSending ? 'rgba(99,102,241,0.3)' : 'rgba(99,102,241,0.8)',
                        border: 'none', color: '#fff',
                        cursor: testSending ? 'default' : 'pointer',
                        fontWeight: 600,
                      }}
                    >
                      {testSending ? 'Sending\u2026' : 'Send'}
                    </button>
                    <button
                      onClick={() => { setTestOpen(false); setTestEmail(''); }}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, color: '#475569' }}
                    >
                      {'\u2715'}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setTestOpen(true)}
                  style={{
                    width: '100%', background: 'none',
                    border: '1px dashed rgba(99,102,241,0.3)',
                    borderRadius: 6, cursor: 'pointer',
                    fontSize: 10, color: '#818cf8', padding: '5px 0',
                    transition: 'border-color 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(99,102,241,0.6)'; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(99,102,241,0.3)'; }}
                >
                  &#128276; Test alert channels
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default NotificationBell;
