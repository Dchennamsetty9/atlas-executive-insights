/**
 * AIOrb — Floating AI intelligence core (top-right corner)
 * Simulated 3D using CSS layers + Framer Motion.
 * Color reflects system health state.
 */

import { useEffect, memo } from 'react';
import { motion, useAnimation } from 'framer-motion';

// Color config per state
const STATE_CONFIG = {
  healthy:  { color: '#10b981', glow: 'rgba(16,185,129,0.5)',  label: 'Systems Healthy'  },
  warning:  { color: '#f59e0b', glow: 'rgba(245,158,11,0.5)',  label: 'Watch Required'   },
  risk:     { color: '#ef4444', glow: 'rgba(239,68,68,0.5)',   label: 'Action Required'  },
  insight:  { color: '#3b82f6', glow: 'rgba(59,130,246,0.5)', label: 'Insight Ready'    },
  checking: { color: '#6366f1', glow: 'rgba(99,102,241,0.5)', label: 'Analyzing…'       },
};

// Derive health state from KPIs
function deriveState(kpis, backendStatus) {
  if (backendStatus === 'checking') return 'checking';
  if (!kpis || kpis.length === 0)  return 'checking';

  const achievements = kpis
    .map(k => k.targetAchievement ?? 100)
    .filter(v => v > 0);

  if (achievements.length === 0) return 'checking';

  const avg = achievements.reduce((a, b) => a + b, 0) / achievements.length;
  const hasRisk = achievements.some(v => v < 85);

  if (hasRisk || avg < 85) return 'risk';
  if (avg < 95)            return 'warning';
  return 'healthy';
}

// Animated ring layer
const Ring = memo(({ size, opacity, duration, delay, color }) => (
  <motion.div
    style={{
      position: 'absolute',
      width: size,
      height: size,
      borderRadius: '50%',
      border: `1px solid ${color}`,
      opacity,
      top: '50%',
      left: '50%',
      x: '-50%',
      y: '-50%',
    }}
    animate={{ scale: [1, 1.6, 1], opacity: [opacity, 0, opacity] }}
    transition={{ duration, delay, repeat: Infinity, ease: 'easeInOut' }}
  />
));
Ring.displayName = 'Ring';

const AIOrb = ({ kpis = [], backendStatus = 'checking', onClick, isAnalyzing = false }) => {
  const state     = isAnalyzing ? 'insight' : deriveState(kpis, backendStatus);
  const cfg       = STATE_CONFIG[state];
  const controls  = useAnimation();

  // Float animation
  useEffect(() => {
    controls.start({
      y: [0, -8, 0],
      transition: { duration: 3.5, repeat: Infinity, ease: 'easeInOut' },
    });
  }, [controls]);

  // Pulse faster when analyzing
  const pulseDuration = isAnalyzing ? 0.8 : 2.5;

  return (
    <motion.div
      style={{ position: 'relative', width: 56, height: 56, cursor: 'pointer', flexShrink: 0 }}
      animate={controls}
      onClick={onClick}
      whileHover={{ scale: 1.1 }}
      whileTap={{ scale: 0.95 }}
      title={cfg.label}
    >
      {/* Outer pulse rings */}
      <Ring size={80} opacity={0.2} duration={pulseDuration}       delay={0}    color={cfg.color} />
      <Ring size={68} opacity={0.25} duration={pulseDuration * 0.8} delay={0.3}  color={cfg.color} />

      {/* Core orb */}
      <motion.div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          background: `radial-gradient(circle at 35% 35%,
            ${cfg.color}cc 0%,
            ${cfg.color}66 40%,
            ${cfg.color}22 70%,
            transparent 100%)`,
          boxShadow: `0 0 24px ${cfg.glow}, 0 0 48px ${cfg.glow.replace('0.5', '0.2')}`,
          border: `1px solid ${cfg.color}88`,
        }}
        animate={{
          boxShadow: [
            `0 0 16px ${cfg.glow}`,
            `0 0 32px ${cfg.glow}`,
            `0 0 16px ${cfg.glow}`,
          ],
        }}
        transition={{ duration: pulseDuration, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* Inner highlight (simulates 3D specular) */}
      <div style={{
        position: 'absolute',
        top: '18%',
        left: '22%',
        width: '30%',
        height: '25%',
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(255,255,255,0.45) 0%, transparent 80%)',
        filter: 'blur(1px)',
        pointerEvents: 'none',
      }} />

      {/* AI icon */}
      <div style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 18,
        userSelect: 'none',
      }}>
        {state === 'checking' ? (
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
            style={{ display: 'inline-block', opacity: 0.9 }}
          >⟳</motion.span>
        ) : (
          <span style={{ opacity: 0.95 }}>
            {state === 'risk' ? '⚠' : state === 'warning' ? '◎' : state === 'insight' ? '◈' : '◉'}
          </span>
        )}
      </div>

      {/* State tooltip badge */}
      <motion.div
        initial={{ opacity: 0, x: 8 }}
        animate={{ opacity: 1, x: 0 }}
        style={{
          position: 'absolute',
          right: -4,
          bottom: -2,
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: cfg.color,
          border: '2px solid #0a0f1e',
          boxShadow: `0 0 6px ${cfg.glow}`,
        }}
      />
    </motion.div>
  );
};

export default memo(AIOrb);
