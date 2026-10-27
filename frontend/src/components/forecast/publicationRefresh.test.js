import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PUBLICATION_REFRESH_MIN_GAP_MS, PUBLICATION_REFRESH_MS, subscribePublicationRefresh } from './publicationRefresh.js';

test('refreshes every five minutes and on visible return; removes listeners on unmount', () => {
  const listeners = new Map();
  let tick, delay, cleared, calls = 0;
  const doc = {
    visibilityState: 'visible',
    addEventListener: (event, callback) => listeners.set(event, callback),
    removeEventListener: event => listeners.delete(event),
  };
  const win = {
    setInterval: (callback, ms) => { tick = callback; delay = ms; return 42; },
    clearInterval: id => { cleared = id; },
    addEventListener: (event, callback) => listeners.set(event, callback),
    removeEventListener: event => listeners.delete(event),
  };
  let clock = 1000;
  const stop = subscribePublicationRefresh(() => calls++, doc, win, () => clock);
  assert.equal(delay, PUBLICATION_REFRESH_MS);
  assert.equal(delay, 300000);
  tick();
  assert.equal(calls, 1);
  doc.visibilityState = 'hidden';
  tick(); listeners.get('focus')(); listeners.get('visibilitychange')();
  assert.equal(calls, 1);
  doc.visibilityState = 'visible';
  // focus + visibilitychange fire together on a tab switch: coalesced inside the min gap
  listeners.get('visibilitychange')(); listeners.get('focus')();
  assert.equal(calls, 1);
  clock += PUBLICATION_REFRESH_MIN_GAP_MS;
  listeners.get('visibilitychange')(); listeners.get('focus')();
  assert.equal(calls, 2);
  clock += PUBLICATION_REFRESH_MS;
  tick();
  assert.equal(calls, 3);
  stop();
  assert.equal(cleared, 42);
  assert.equal(listeners.size, 0);
});