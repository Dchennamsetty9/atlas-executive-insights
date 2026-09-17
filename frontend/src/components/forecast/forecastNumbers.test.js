import test from 'node:test';
import assert from 'node:assert/strict';
import { formatWeekDate, monthlyTotals, uniqueWeeks } from './forecastNumbers.js';

test('Monday dates retain the published calendar date', () => {
  assert.equal(formatWeekDate('2026-09-07'), 'Sep 7');
  assert.equal(formatWeekDate('2026-09-14'), 'Sep 14');
  assert.equal(formatWeekDate('2026-10-01'), 'Oct 1');
});

test('monthly bounds sum weekly scenarios without narrowing or zero-filling', () => {
  assert.deepEqual(monthlyTotals([{ arr_likely: 100, arr_worst: 70, arr_best: 130 },
    { arr_likely: 200, arr_worst: 150, arr_best: 250 }]), {
    arr_actual: null, arr_predicted: null, arr_likely: 300, arr_worst: 220, arr_best: 380,
  });
  assert.equal(monthlyTotals([{ arr_actual: 0 }]).arr_actual, 0);
  assert.equal(monthlyTotals([]).arr_likely, null);
});

test('overlapping forecast publications cannot double quarterly totals', () => {
  const rows = [{ date: '2026-09-07', type: 'forecast', arr_likely: 5 },
    { date: '2026-09-07', type: 'actual', arr_actual: 0 },
    { date: '2026-09-14', type: 'forecast', arr_likely: 7 }];
  const result = uniqueWeeks([...rows, ...rows]);
  assert.equal(result.length, 2);
  assert.equal(result[0].type, 'actual');
});