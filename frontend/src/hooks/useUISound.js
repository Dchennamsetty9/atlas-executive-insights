/**
 * useUISound — Toggleable UI sound system
 * Sounds are disabled by default; no autoplay without user interaction.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Howl } from 'howler';

// ── Tiny inline base64 sounds (no network requests needed) ──────────────────
// These are minimal Web Audio API-generated tones encoded as data URIs.
// Using programmatic audio generation so no external audio files are needed.

function createTone(frequency, duration, type = 'sine', volume = 0.15) {
  if (typeof window === 'undefined') return null;
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    return { frequency, duration, type, volume };
  } catch {
    return null;
  }
}

const SOUNDS = {
  click:   createTone(880,  80,  'sine',     0.08),
  load:    createTone(440,  300, 'sine',     0.10),
  insight: createTone(660,  200, 'triangle', 0.10),
  warning: createTone(220,  400, 'sawtooth', 0.06),
  open:    createTone(550,  150, 'sine',     0.08),
};

function playTone(config) {
  if (!config) return;
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const oscillator = ctx.createOscillator();
    const gainNode = ctx.createGain();

    oscillator.connect(gainNode);
    gainNode.connect(ctx.destination);

    oscillator.type = config.type;
    oscillator.frequency.setValueAtTime(config.frequency, ctx.currentTime);
    gainNode.gain.setValueAtTime(config.volume, ctx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + config.duration / 1000);

    oscillator.start(ctx.currentTime);
    oscillator.stop(ctx.currentTime + config.duration / 1000);
  } catch {
    // Silently fail — audio is non-critical
  }
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useUISound() {
  const [enabled, setEnabled] = useState(false); // OFF by default
  const hasInteracted = useRef(false);

  // Mark first user interaction
  useEffect(() => {
    const mark = () => { hasInteracted.current = true; };
    window.addEventListener('click', mark, { once: true });
    return () => window.removeEventListener('click', mark);
  }, []);

  const play = useCallback((soundName) => {
    if (!enabled || !hasInteracted.current) return;
    playTone(SOUNDS[soundName]);
  }, [enabled]);

  const toggle = useCallback(() => {
    setEnabled(prev => !prev);
  }, []);

  return { enabled, toggle, play };
}
