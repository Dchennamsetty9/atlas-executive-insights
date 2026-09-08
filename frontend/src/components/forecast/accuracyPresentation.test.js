import { test } from 'node:test';
import assert from 'node:assert/strict';
import { accuracyProducts, quarterlyValue, quarterlyPill, sourceDate, backtestFreshness, backtestGuidance } from './accuracyPresentation.js';

const rows = [
  { product: 'UCC', sales_market: 'Total', quarterly_errors: { Ensemble: 0.826, ETS: 0 } },
  { product: 'ITSG', sales_market: 'All', quarterly_errors: { Ensemble: 12.52, ETS: 120.01 } },
  { product: 'Total', sales_market: 'Total', quarterly_errors: { Ensemble: 999 } },
];

test('All renders two explicit products rather than a synthetic total', () => {
  for (const product of ['All', 'Total', null, undefined]) assert.deepEqual(accuracyProducts(product), ['UCC', 'ITSG']);
  assert.deepEqual(accuracyProducts('ITSG'), ['ITSG']);
  assert.equal(quarterlyPill(rows, 'All', 'Ensemble'), 'Qtr · UCC 0.8% · ITSG 12.5%');
  assert.equal(quarterlyPill(rows, 'UCC', 'Ensemble'), 'Qtr 0.8%');
});

test('missing product or quarterly data never borrows total, weekly or region errors', () => {
  const partial = [{ product: 'ITSG', sales_market: 'NA', quarterly_errors: { ETS: 9 } },
    { product: 'ITSG', sales_market: 'Total', ETS: 12 }, rows[0], rows[2]];
  assert.equal(quarterlyPill(partial, 'All', 'ETS'), 'Qtr · UCC 0.0% · ITSG —');
  assert.equal(quarterlyValue(partial, 'ITSG', 'ETS'), null);
  assert.equal(quarterlyPill([], 'All', 'Ensemble'), 'Qtr · UCC — · ITSG —');
});

test('quarterly formatting preserves zero and over-100 errors but rejects invalid values', () => {
  assert.equal(quarterlyValue(rows, 'UCC', 'ETS'), 0);
  assert.equal(quarterlyValue(rows, 'ITSG', 'ETS'), 120.01);
  for (const value of [null, undefined, '', ' ', false, true, NaN, Infinity, 'bad']) {
    assert.equal(quarterlyValue([{ product: 'UCC', sales_market: 'Total', quarterly_errors: { ETS: value } }], 'UCC', 'ETS'), null);
  }
});

test('source freshness uses returned publications only, never current check time', () => {
  assert.equal(sourceDate(null), 'Not supplied by source');
  assert.equal(sourceDate('bad'), 'Not supplied by source');
  assert.equal(sourceDate('2026-09-08'), '2026-09-08');
  assert.deepEqual(backtestFreshness([
    { origin_ts: '2026-08-01T12:00:00+00:00', actual_run_date: '2026-09-08' },
    { origin_ts: '2026-08-04T10:00:00+00:00', actual_run_date: '2026-09-07' },
  ]), { forecast: '2026-08-04T10:00:00+00:00', actual: '2026-09-08' });
  assert.equal(backtestFreshness([]).actual, 'Not supplied by source');
});

test('empty guidance differentiates unsupported scope, missing history and failed reads', () => {
  assert.match(backtestGuidance('no_matched_history'), /next daily run may not/);
  assert.match(backtestGuidance('region_history_unverified'), /All regions/);
  assert.match(backtestGuidance('model_history_unverified'), /Native Prophet/);
  assert.match(backtestGuidance('source_query_failed'), /retry/);
  assert.match(backtestGuidance('combined_history_unverified'), /aligned forecast origins/);
  for (const reason of ['invalid_history', 'source_unavailable', undefined]) {
    assert.ok(backtestGuidance(reason));
    assert.doesNotMatch(backtestGuidance(reason), /Check back after the next run/);
  }
});