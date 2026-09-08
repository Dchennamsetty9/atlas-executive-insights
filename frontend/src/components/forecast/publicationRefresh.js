// Publication polling, not a training trigger. Also catches jobs that finish late.
export const PUBLICATION_REFRESH_MS = 5 * 60 * 1000;

export function subscribePublicationRefresh(refresh, doc = document, win = window) {
  const onVisible = () => {
    if (doc.visibilityState === 'visible') refresh();
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