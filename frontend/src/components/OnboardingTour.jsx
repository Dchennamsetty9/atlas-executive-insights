/**
 * OnboardingTour — 3-step spotlight tour for first-time visitors.
 *
 * Steps:
 *  1. KPI Strip — "These are your live KPIs. Click 📊 for detailed charts."
 *  2. Ask AI    — "Ask anything about your pipeline, forecast, or KPIs."
 *  3. Filters   — "Filter by Geo, Channel, Product and share the link."
 *
 * Stores completion in localStorage so it only shows once.
 */

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ChevronRight, ChevronLeft } from 'lucide-react';

const STEPS = [
  {
    title: '👋 Welcome to Atlas Executive Insights',
    body:  'Your real-time GAIM sales intelligence dashboard. This quick tour covers the 3 things you need to know.',
    icon:  '🏠',
    cta:   'Start tour',
  },
  {
    title: '📊 Live KPI Cards',
    body:  'Each card shows a key metric vs. target — with trend, dollar impact, and AI-generated insight. Click 📊 on any card to drill into detailed charts.',
    icon:  '📊',
    cta:   'Next',
  },
  {
    title: '✦ Ask AI (⌘K)',
    body:  'Ask anything in plain English — "Why is close rate dropping in EMEA?" — and get a live SQL answer from Databricks Genie or an AI insight from GPT-4.',
    icon:  '✦',
    cta:   'Next',
    action: 'openAI',
  },
  {
    title: '🎛 Filters & Sharing',
    body:  'Filter by Geography, Channel, Product, and more. Active filters sync to the URL — copy and share the link to give teammates your exact view.',
    icon:  '🎛',
    cta:   'Done',
  },
];

const STORAGE_KEY = 'atlas_onboarding_done';

export default function OnboardingTour({ onOpenAI }) {
  const [step, setStep] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const done = localStorage.getItem(STORAGE_KEY);
    if (!done) {
      // Slight delay so the dashboard has time to render first
      const t = setTimeout(() => setVisible(true), 1800);
      return () => clearTimeout(t);
    }
  }, []);

  const dismiss = () => {
    setVisible(false);
    localStorage.setItem(STORAGE_KEY, '1');
  };

  const next = () => {
    const current = STEPS[step];
    if (current.action === 'openAI') onOpenAI?.();
    if (step >= STEPS.length - 1) {
      dismiss();
    } else {
      setStep(s => s + 1);
    }
  };

  const back = () => setStep(s => Math.max(0, s - 1));

  if (!visible) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <AnimatePresence>
      {visible && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={dismiss}
            style={{
              position: 'fixed', inset: 0,
              background: 'rgba(0,0,0,0.5)',
              backdropFilter: 'blur(2px)',
              zIndex: 2000,
            }}
          />

          {/* Card */}
          <motion.div
            initial={{ opacity: 0, scale: 0.92, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 24 }}
            transition={{ type: 'spring', stiffness: 300, damping: 28 }}
            style={{
              position: 'fixed',
              bottom: 48,
              left: '50%',
              transform: 'translateX(-50%)',
              width: 420,
              zIndex: 2001,
              background: 'linear-gradient(160deg, rgba(17,24,39,0.99) 0%, rgba(13,20,40,0.99) 100%)',
              border: '1px solid rgba(0,102,255,0.35)',
              borderRadius: 16,
              boxShadow: '0 0 48px rgba(0,102,255,0.15), 0 24px 64px rgba(0,0,0,0.7)',
              overflow: 'hidden',
            }}
          >
            {/* Progress bar */}
            <div style={{ height: 3, background: 'rgba(255,255,255,0.06)' }}>
              <motion.div
                animate={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
                transition={{ duration: 0.4 }}
                style={{ height: '100%', background: 'linear-gradient(90deg, #0066FF, #7c3aed)', borderRadius: 2 }}
              />
            </div>

            {/* Body */}
            <div style={{ padding: '20px 22px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
                <div style={{ fontSize: 24, lineHeight: 1 }}>{current.icon}</div>
                <button
                  onClick={dismiss}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#475569', padding: 2 }}
                >
                  <X size={14} />
                </button>
              </div>

              <AnimatePresence mode="wait">
                <motion.div
                  key={step}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  transition={{ duration: 0.2 }}
                >
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>
                    {current.title}
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.6 }}>
                    {current.body}
                  </div>
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Footer */}
            <div style={{
              padding: '10px 22px 16px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              borderTop: '1px solid rgba(255,255,255,0.06)',
            }}>
              {/* Step dots */}
              <div style={{ display: 'flex', gap: 5 }}>
                {STEPS.map((_, i) => (
                  <div key={i} style={{
                    width: i === step ? 18 : 6, height: 6, borderRadius: 3,
                    background: i === step ? '#0066FF' : 'rgba(255,255,255,0.12)',
                    transition: 'all 0.3s',
                  }} />
                ))}
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                {step > 0 && (
                  <button
                    onClick={back}
                    style={{
                      padding: '6px 12px', borderRadius: 8, fontSize: 12,
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      color: '#64748b', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: 4,
                    }}
                  >
                    <ChevronLeft size={12} /> Back
                  </button>
                )}
                <button
                  onClick={next}
                  style={{
                    padding: '6px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600,
                    background: 'linear-gradient(135deg, #0066FF, #7c3aed)',
                    border: 'none', color: '#fff', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: 5,
                    boxShadow: '0 0 16px rgba(0,102,255,0.3)',
                  }}
                >
                  {current.cta}
                  {!isLast && <ChevronRight size={12} />}
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
