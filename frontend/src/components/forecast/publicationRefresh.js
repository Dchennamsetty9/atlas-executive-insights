// Publication polling, not a training trigger. Also catches jobs that finish late.
export const PUBLICATION_REFRESH_MS = 5 * 60 * 1000;

// A tab switch fires both `visibilitychange` and `focus` (and embedded/iframe hosts can
// fire `focus` repeatedly), so coalesce triggers: each refresh re-queries Databricks.
export const PUBLICATION_REFRESH_MIN_GAP_MS = 30 * 1000;

export function subscribePublicationRefresh(refresh, doc = document, win = window, now = Date.now) {
  let last = -Infinity;
  const onVisible = () => {
    if (doc.visibilityState !== 'visible') return;
    const t = now();
    if (t - last < PUBLICATION_REFRESH_MIN_GAP_MS) return;
    last = t;
    refresh();
  };
  const timer = win.setInterval(onVisible, PUBLICATION_REFRESH_MS);
  doc.addEventListener('visibilitychange', onVisible);
  win.addEventListener('focus', onVisible);
  return () => {
    win.clearInterval(timer);
    doc.removeEventListener('visibilitychange', onVisible);
    win.removeEventListener('focus', onVisible);
  };
}