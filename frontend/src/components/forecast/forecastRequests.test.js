import test from 'node:test';
import assert from 'node:assert/strict';
import { createForecastRequests } from './forecastRequests.js';

test('identical requests share one call regardless of parameter order', async () => {
  let calls = 0;
  const requests = createForecastRequests(async () => { calls += 1; return { rows: [] }; });
  const batch = requests.start();
  const first = batch.get('/weekly', { params: { year: 2026, model: 'ensemble' } });
  const second = batch.get('/weekly', { params: { model: 'ensemble', year: 2026 } });
  assert.equal(first, second);
  await first;
  assert.equal(calls, 1);
});

test('metadata is reused across filters, expires, and refresh bypasses it', async () => {
  let time = 0;
  let calls = 0;
  const requests = createForecastRequests(async () => ({ calls: ++calls }), { now: () => time, metadataTtl: 100 });
  await requests.start().get('/api/forecast/v2/models');
  await requests.start().get('/api/forecast/v2/models');
  assert.equal(calls, 1);
  time = 101;
  await requests.start().get('/api/forecast/v2/models');
  assert.equal(calls, 2);
  await requests.start({ force: true }).get('/api/forecast/v2/models');
  assert.equal(calls, 3);
});

test('new filters abort old transport and reject late responses', async () => {
  let finish;
  let signal;
  const requests = createForecastRequests((url, config) => {
    signal = config.signal;
    return new Promise(resolve => { finish = resolve; });
  });
  const oldBatch = requests.start();
  const oldResult = oldBatch.get('/weekly');
  await Promise.resolve();
  const newBatch = requests.start();
  assert.equal(signal.aborted, true);
  assert.equal(oldBatch.isCurrent(), false);
  assert.equal(newBatch.isCurrent(), true);
  finish({ rows: ['old'] });
  await assert.rejects(oldResult, { name: 'AbortError' });
});

test('fast requests resolve without waiting for slow secondary data', async () => {
  let finish;
  const requests = createForecastRequests(url => url === '/slow'
    ? new Promise(resolve => { finish = resolve; }) : Promise.resolve('ready'));
  const batch = requests.start();
  const slow = batch.get('/slow');
  assert.equal(await batch.get('/fast'), 'ready');
  finish('done');
  assert.equal(await slow, 'done');
});

test('failed and demo metadata are not cached', async () => {
  let calls = 0;
  const requests = createForecastRequests(async () => {
    calls += 1;
    if (calls === 1) throw new Error('offline');
    return { source: 'demo' };
  });
  await assert.rejects(requests.start().get('/api/forecast/v2/freshness'));
  await assert.rejects(requests.start().get('/api/forecast/v2/freshness'), /Data unavailable/);
  await assert.rejects(requests.start().get('/api/forecast/v2/freshness'), /Data unavailable/);
  assert.equal(calls, 3);
});

test('core forecast requests cannot mix publications in the same batch', async () => {
  const requests = createForecastRequests(async url => ({ source: 'live',
    publication_id: url.endsWith('/weekly') ? '2026-09-15' : '2026-09-22' }));
  const batch = requests.start();
  await batch.get('/api/forecast/v2/weekly');
  await assert.rejects(batch.get('/api/forecast/v2/confidence-bands'), /Publication changed/);
  const nextBatch = requests.start();
  assert.equal((await nextBatch.get('/api/forecast/v2/confidence-bands')).publication_id, '2026-09-22');
});