import test from 'node:test';
import assert from 'node:assert/strict';
import { loadForecastTab } from './loadForecastTab.js';

const selection = { tab: 'Overview', model: 'ensemble', forecastType: 'roy', productLine: 'UCC', salesMarket: 'NA', year: 2026, quarter: null };

test('overview publishes weekly data while secondary requests remain pending', async () => {
  const completions = new Map();
  const api = new Proxy({}, { get: (_, method) => (...args) => {
    const key = JSON.stringify([method, args]);
    if (!completions.has(key)) {
      let resolve;
      const promise = new Promise(done => { resolve = done; });
      completions.set(key, { promise, resolve });
    }
    return completions.get(key).promise;
  } });
  const published = [];
  const done = loadForecastTab(api, selection, field => published.push(field), assert.fail);
  const weeklyKey = JSON.stringify(['getForecastV2Weekly', ['ensemble', 'roy', null, 'UCC', 'NA', 2026, null]]);
  completions.get(weeklyKey).resolve({ rows: [] });
  await Promise.resolve();
  assert.deepEqual(published, ['weekly']);
  for (const completion of completions.values()) completion.resolve({ rows: [] });
  await done;
  assert.ok(published.includes('yearRows'));
});

test('plan bridge starts before overview requests finish', async () => {
  const called = [];
  const api = new Proxy({}, { get: (_, method) => () => {
    called.push(method);
    return Promise.resolve({ rows: [] });
  } });
  const done = loadForecastTab(api, { ...selection, tab: 'Plan Tracking' }, () => {}, assert.fail);
  assert.ok(called.includes('getForecastV2DriverBridge'));
  await done;
});

test('one failed exec request does not discard successful sections', async () => {
  const api = new Proxy({}, { get: (_, method) => () => method === 'getActions'
    ? Promise.reject(new Error('unavailable')) : Promise.resolve({ rows: [] }) });
  const published = [];
  const errors = [];
  await loadForecastTab(api, { ...selection, tab: 'Exec Mode' }, field => published.push(field), field => errors.push(field));
  assert.equal(published.length, 12);
  assert.ok(published.includes('weekly'));
  assert.ok(published.includes('confidenceBands'));
  assert.deepEqual(errors, ['actions']);
});

test('data tabs publish their dedicated payloads', async () => {
  const cases = [
    ['Multi-Year', 'historical'],
    ['By Product', 'byProduct'],
    ['Monthly', 'monthly'],
    ['Weekly', 'weeklyChanges'],
  ];

  for (const [tab, field] of cases) {
    const called = [];
    const api = new Proxy({}, { get: (_, method) => (...args) => {
      called.push([method, args]);
      return Promise.resolve({ rows: [], months: [] });
    } });
    const published = [];
    await loadForecastTab(api, { ...selection, tab }, value => published.push(value), assert.fail);
    assert.ok(published.includes(field), `${tab} did not publish ${field}`);
    if (tab === 'Multi-Year') assert.ok(published.includes('weekly'));
    assert.ok(called.length > 0, `${tab} did not call an API method`);
  }
});

test('executive requests carry product and region scope', async () => {
  const calls = new Map();
  const api = new Proxy({}, { get: (_, method) => (...args) => {
    calls.set(method, args);
    return Promise.resolve({ rows: [] });
  } });
  await loadForecastTab(api, { ...selection, tab: 'Exec Mode' }, () => {}, assert.fail);
  for (const method of ['getForecastV2Confidence', 'getForecastV2DriverBridge', 'getForecastV2RiskRadar', 'getForecastV2MeetingMode']) {
    assert.deepEqual(calls.get(method).slice(-2), ['UCC', 'NA']);
  }
  assert.equal(calls.get('getForecastV2ConfidenceBands').at(-1), 'NA');
});