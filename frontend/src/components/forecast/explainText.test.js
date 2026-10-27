import test from 'node:test';
import assert from 'node:assert/strict';
import { splitExplanation, bulletsAreCompact } from './explainText.js';

const sample = 'UCC 2026 by quarter: Q1 closed at $13.6M; Q2 closed at $13.9M; Q4 is in progress — $0.0M realized + $15.2M forecast = $15.2M landing. '
  + 'Orange is realized bookings; blue is the Adaptive_Ensemble most-likely forecast. Full-year landing $59.1M, -1% vs 2025\'s $59.7M. Later quarters carry wider uncertainty.';

test('headline is the first sentence and decimals do not split sentences', () => {
  const { headline, rest } = splitExplanation(sample);
  assert.ok(headline.startsWith('UCC 2026 by quarter'));
  assert.ok(headline.endsWith('$15.2M landing.'));
  assert.ok(rest.startsWith('Orange is realized bookings'));
  assert.ok(rest.includes('Later quarters carry wider uncertainty.'));
});

test('short text stays entirely in the headline', () => {
  assert.deepEqual(splitExplanation('One short sentence.'), { headline: 'One short sentence.', rest: '' });
  assert.deepEqual(splitExplanation(''), { headline: '', rest: '' });
  assert.deepEqual(splitExplanation(null), { headline: '', rest: '' });
});

test('a very long first sentence is kept whole rather than cut', () => {
  const long = `${'word '.repeat(80)}end.`;
  assert.equal(splitExplanation(long).headline, long);
});

test('compact bullets are detected only when all are short', () => {
  assert.equal(bulletsAreCompact(['Q1: $13.6M actual', 'Q2: $13.9M actual']), true);
  assert.equal(bulletsAreCompact(['Q1: $13.6M actual', 'x'.repeat(60)]), false);
  assert.equal(bulletsAreCompact(['only one']), false);
  assert.equal(bulletsAreCompact([]), false);
});
