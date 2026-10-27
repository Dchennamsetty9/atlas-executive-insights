import test from 'node:test';
import assert from 'node:assert/strict';
import { forecastCell, moneyM, signedPct, errorColor, statusLabel, quarterRows } from './quarterlyComparison.js';

test('money and signed percent never invent values', () => {
  assert.equal(moneyM(null), '—');
  assert.equal(moneyM('abc'), '—');
  assert.equal(moneyM(12_345_678), '$12.35M');
  assert.equal(signedPct(undefined), '—');
  assert.equal(signedPct(-10), '-10.0%');
  assert.equal(signedPct(3.26), '+3.3%');
});

test('error colour is by absolute size', () => {
  assert.equal(errorColor(-2), '#10b981');
  assert.equal(errorColor(7), '#f59e0b');
  assert.equal(errorColor(-15), '#ef4444');
  assert.equal(errorColor(null), '#94a3b8');
});

test('closed quarter shows the first-published ensemble forecast, open quarters the projected landing', () => {
  const closed = { status: 'closed', models: { ensemble: { forecast: 9e6, weeks: 13 } } };
  assert.deepEqual(forecastCell(closed), { value: 9e6, note: '13 wks, as first published' });
  assert.equal(forecastCell({ status: 'closed', models: {} }).value, null);
  const open = { status: 'forecast', projection: { landing_likely: 9e6, landing_low: 8e6, landing_high: 10e6 } };
  assert.deepEqual(forecastCell(open), { value: 9e6, note: '$8.00M – $10.00M' });
  assert.equal(forecastCell({ status: 'forecast', projection: null }).value, null);
});

test('status labels and row extraction', () => {
  assert.equal(statusLabel({ status: 'in_progress', actual_weeks: 4 }), 'In progress · 4 wks closed');
  assert.equal(statusLabel({ status: 'forecast' }), 'Forecast only');
  assert.deepEqual(quarterRows({ quarters: 'nope' }), []);
  assert.equal(quarterRows({ quarters: [{ label: 'Q1' }] }).length, 1);
});
