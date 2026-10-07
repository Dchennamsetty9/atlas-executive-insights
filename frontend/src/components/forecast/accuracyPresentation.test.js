import { test } from 'node:test';
import assert from 'node:assert/strict';
import { accuracyProducts, quarterlyValue, quarterlyPill, quarterlyEvidence, quarterlyBasis, sourceDate, backtestFreshness, backtestGuidance, historicalAccuracyCard } from './accuracyPresentation.js';

const rows = [
  { product: 'UCC', sales_market: 'Total', quarterly_errors: { Ensemble: 0.826, ETS: 0 } },
  { product: 'ITSG', sales_market: 'All', quarterly_errors: { Ensemble: 12.52, ETS: 120.01 } },
  { product: 'Total', sales_market: 'Total', quarterly_errors: { Ensemble: 999 } },
];

test('All renders two explicit products rather than a synthetic total', () => {
  for (const product of ['All', 'Total', null, undefined]) assert.deepEqual(accuracyProducts(product), ['UCC', 'ITSG']);
  assert.deepEqual(accuracyProducts('ITSG'), ['ITSG']);
  assert.equal(quarterlyPill(rows, 'All', 'Ensemble'), 'Qtr · UCC 0.8% (unverified) · ITSG 12.5% (unverified)');
  assert.equal(quarterlyPill(rows, 'UCC', 'Ensemble'), 'Qtr 0.8% (unverified)');
});

test('missing product or quarterly data never borrows total, weekly or region errors', () => {
  const partial = [{ product: 'ITSG', sales_market: 'NA', quarterly_errors: { ETS: 9 } },
    { product: 'ITSG', sales_market: 'Total', ETS: 12 }, rows[0], rows[2]];
  assert.equal(quarterlyPill(partial, 'All', 'ETS'), 'Qtr · UCC 0.0% (unverified) · ITSG —');
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

test('quarterly provenance distinguishes measured, estimated, blended and missing evidence', () => {
  const evidenceRows = rows.map(row => ({ ...row, quarterly_provenance: {
    Ensemble: row.product === 'UCC'
      ? { status: 'measured', quarter: '2026Q2', quarters_evaluated: 1 }
      : { status: 'estimated' },
    ETS: { status: 'blended' },
  } }));
  assert.equal(quarterlyPill(evidenceRows, 'All', 'Ensemble'), 'Qtr · UCC 0.8% · ITSG 12.5% (estimated)');
  assert.equal(quarterlyBasis(evidenceRows, 'UCC', 'Ensemble'), 'Measured · 2026Q2 · 1 quarter');
  assert.equal(quarterlyBasis(evidenceRows, 'ITSG', 'Ensemble'), 'Estimated from weekly error');
  assert.equal(quarterlyBasis(evidenceRows, 'UCC', 'ETS'), 'Weighted blend');
  assert.equal(quarterlyBasis(rows, 'UCC', 'ETS'), 'Evaluation basis unverified');
  assert.equal(quarterlyBasis([], 'UCC', 'ETS'), 'Not available');
  assert.equal(quarterlyEvidence([{ ...rows[0], quarterly_provenance: { ETS: { status: 'unknown' } } }], 'UCC', 'ETS').status, 'unverified');
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

test('historicalAccuracyCard leads with the quarter-level figure and adds weekly context', () => {
  const measured = [{ product: 'UCC', sales_market: 'Total', quarterly_errors: { Ensemble: 14.1 },
    quarterly_provenance: { Ensemble: { status: 'measured', quarter: '2026Q3', quarters_evaluated: 1 } } }];
  const card = historicalAccuracyCard(measured, 'UCC', { avgSmape: 25.2, nQuarters: 1 });
  assert.equal(card.text, "The Ensemble's full-quarter forecast landed within about 14.1% of the actual in the latest closed quarter. Week by week the typical miss is larger (about 25%) because weekly swings partly offset across a quarter.");
  assert.equal(card.color, '#10b981');
  assert.ok(card.text.includes(quarterlyPill(measured, 'UCC', 'Ensemble').replace('Qtr ', '')));
});

test('historicalAccuracyCard colours by quarter-level error, not weekly, and never calls a miss a win', () => {
  const rows = [{ product: 'ITSG', sales_market: 'Total', quarterly_errors: { Ensemble: 31 },
    quarterly_provenance: { Ensemble: { status: 'measured', quarters_evaluated: 4 } } }];
  const card = historicalAccuracyCard(rows, 'ITSG', { avgSmape: 5, nQuarters: 4 });
  assert.equal(card.color, '#ef4444');
  assert.match(card.text, /across the last 4 evaluated quarters/);
  assert.match(card.text, /Week by week the typical miss is about 5%\./);
  assert.doesNotMatch(card.text, /larger/);
});

test('historicalAccuracyCard falls back to an explicit weekly-only sentence', () => {
  const one = historicalAccuracyCard([], 'UCC', { avgSmape: 25.2, nQuarters: 1 });
  assert.match(one.text, /^Week by week, /);
  assert.doesNotMatch(one.text, /over the most recent closed quarter/);
  assert.match(one.text, /in the latest closed quarter/);
  assert.equal(one.color, '#ef4444');
  const many = historicalAccuracyCard([], 'UCC', { avgSmape: 12, nQuarters: 3 });
  assert.match(many.text, /across the last 3 closed quarters/);
  assert.equal(many.color, '#10b981');
  assert.equal(historicalAccuracyCard([], 'UCC', null), null);
});

test('historicalAccuracyCard shows All products separately, colours by the worst, and flags unverified basis', () => {
  const card = historicalAccuracyCard(rows, 'All', null);
  assert.match(card.text, /UCC 0\.8% \(unverified\) and ITSG 12\.5% \(unverified\)/);
  assert.equal(card.color, '#10b981');
  assert.doesNotMatch(card.text, /Week by week/);
});

