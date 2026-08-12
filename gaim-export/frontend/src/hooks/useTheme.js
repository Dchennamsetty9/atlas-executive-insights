import { useState, useEffect } from 'react';

/**
 * Reads the current [data-theme] attribute from the nearest ancestor
 * that carries it (the App root div) and returns whether the theme is dark.
 * Re-renders whenever the attribute changes.
 */
export function useTheme() {
  const getIsDark = () => {
    const el = document.querySelector('[data-theme]');
    return el?.getAttribute('data-theme') !== 'light';
  };

  const [isDark, setIsDark] = useState(getIsDark);

  useEffect(() => {
    // Re-read after mount so we see the committed DOM value (fixes first-paint
    // race where lazy useState runs before React writes data-theme to the DOM).
    setIsDark(getIsDark());

    const el = document.querySelector('[data-theme]');
    if (!el) return;
    const obs = new MutationObserver(() => setIsDark(getIsDark()));
    obs.observe(el, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);

  return isDark;
}
