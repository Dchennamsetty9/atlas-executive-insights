import test from 'node:test';
import assert from 'node:assert/strict';
import { paceView, paceBacktestText, paceBadge, paceScopeNote, PACE_SALESFORCE_NOTE } from './paceOutlook.js';

const row = (o = {}) => ({ product: 'UCC', outlook_landing: 15e6, model_landing: 14e6, validated: true,
  backtest_mape_pct: 2.8, model_mape_pct: 8.6, n_quarters: 4, weeks_closed: 8, ...o });

test('nothing to show when unavailable or empty', () => {
  assert.equal(paceView(null), null);
  assert.equal(paceView({ source: 'unavailable', products: [row()] }), null);
  assert.equal(paceView({ source: 'live', products: [] }), null);
  assert.equal(paceView({ source: 'live', products: [row({ outlook_landing: null })] }), null);
});

test('validated row reports its own backtest error', () => {
  const v = paceView({ source: 'live', quarter_label: '2026Q4', products: [row()], total: null });
  assert.equal(v.rows[0].delta, 1e6);
  assert.equal(v.rows[0].badge.kind, 'validated');
  assert.equal(v.rows[0].backtest, 'Backtest error 2.8% vs 8.6% for the static forecast (4 quarters)');
  assert.equal(v.total, null);
});

test('indicative row says it is not validated and never shows a backtest error', () => {
  assert.equal(paceBadge(row({ validated: false })).kind, 'indicative');
  assert.equal(paceBacktestText(row({ validated: false })), 'Not yet validated at this point in the quarter');
});

test('total is a plain sum and carries no combined error', () => {
  const v = paceView({ source: 'live', quarter_label: '2026Q4',
    products: [row(), row({ product: 'ITSG', outlook_landing: 4e6, model_landing: 3.5e6, validated: false })],
    total: { outlook_landing: 19e6, model_landing: 17.5e6, validated: false } });
  assert.equal(v.total.delta, 1.5e6);
  assert.equal(v.total.badge.kind, 'indicative');
  assert.ok(!('backtest_mape_pct' in v.total));
});

test('scope note appears only when Miradore is on', () => {
  assert.equal(paceScopeNote(true), PACE_SALESFORCE_NOTE);
  assert.match(PACE_SALESFORCE_NOTE, /excludes the Miradore estimate/);
  assert.equal(paceScopeNote(false), null);
});

test('validated without numbers falls back to a plain label', () => {
  assert.equal(paceBacktestText(row({ backtest_mape_pct: null })), 'Validated in backtest');
});
