import { test } from 'node:test';
import assert from 'node:assert/strict';
import { backtestScope, backtestRequestKey, backtestResponseMatches, backtestDate } from './backtestContract.js';

test('All is a distinct combined scope, not UCC', () => {
  const all = backtestScope('All', 'All', 'ensemble', 4);
  assert.equal(all.product, 'Total');
  assert.equal(all.sales_market, 'Total');
  assert.notEqual(backtestRequestKey(all), backtestRequestKey(backtestScope('UCC', 'All', 'ensemble', 4)));
});

test('every filter and horizon changes the request key', () => {
  const original = backtestRequestKey(backtestScope('UCC', 'All', 'ensemble', 4));
  for (const args of [['ITSG', 'All', 'ensemble', 4], ['UCC', 'NA', 'ensemble', 4], ['UCC', 'All', 'ets', 4], ['UCC', 'All', 'ensemble', 1]]) {
    assert.notEqual(backtestRequestKey(backtestScope(...args)), original);
  }
});

test('reject mismatched product, model, market, horizon and demo responses', () => {
  const scope = backtestScope('ITSG', 'All', 'ensemble', 4);
  const response = { ...scope, source: 'live' };
  assert.equal(backtestResponseMatches(response, scope), true);
  for (const change of [{ product: 'UCC' }, { sales_market: 'NA' }, { model: 'ets' }, { horizon_weeks: 1 }, { source: 'demo' }]) {
    assert.equal(backtestResponseMatches({ ...response, ...change }, scope), false);
  }
  assert.equal(backtestResponseMatches(null, scope), false);
  assert.equal(backtestResponseMatches({ ...scope, source: 'unavailable' }, scope), true);
});

test('date-only target weeks do not shift to Sunday', () => {
  assert.equal(backtestDate('2026-08-31'), 'Aug 31');
  assert.equal(backtestDate('2026-08-10'), 'Aug 10');
  assert.equal(backtestDate(null), '—');
});