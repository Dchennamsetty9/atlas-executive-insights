import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MIRADORE_STORAGE_KEY, MIRADORE_INCLUDED_NOTE, MIRADORE_UNAVAILABLE_NOTE, MIRADORE_MODEL_NOTE,
  readIncludeMiradore, writeIncludeMiradore, showMiradoreToggle, withIncludeMiradore, miradoreNote,
} from './miradore.js';
import { DEFAULT_INCLUDE_MIRADORE } from './constants.js';

const memory = (initial = {}) => {
  const data = { ...initial };
  return { getItem: key => (key in data ? data[key] : null), setItem: (key, value) => { data[key] = value; }, data };
};

test('default is ON and persisted values round-trip', () => {
  assert.equal(DEFAULT_INCLUDE_MIRADORE, true);
  const storage = memory();
  assert.equal(readIncludeMiradore(storage), true);
  writeIncludeMiradore(false, storage);
  assert.equal(storage.data[MIRADORE_STORAGE_KEY], 'false');
  assert.equal(readIncludeMiradore(storage), false);
  writeIncludeMiradore(true, storage);
  assert.equal(readIncludeMiradore(storage), true);
});

test('broken or missing storage falls back to the default without throwing', () => {
  const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.equal(readIncludeMiradore(broken), true);
  assert.doesNotThrow(() => writeIncludeMiradore(false, broken));
  assert.equal(readIncludeMiradore(null), true);
  assert.equal(readIncludeMiradore(memory({ [MIRADORE_STORAGE_KEY]: 'junk' })), true);
});

test('toggle is shown for ITSG and All only', () => {
  assert.equal(showMiradoreToggle('ITSG'), true);
  assert.equal(showMiradoreToggle('All'), true);
  assert.equal(showMiradoreToggle('UCC'), false);
});

test('include flag is added to every forecast v2 GET and nothing else', () => {
  assert.deepEqual(withIncludeMiradore('/api/forecast/v2/weekly', { model: 'ensemble' }, true), { model: 'ensemble', include_miradore: true });
  assert.deepEqual(withIncludeMiradore('/api/forecast/v2/ytd', undefined, false), { include_miradore: false });
  assert.deepEqual(withIncludeMiradore('/api/forecast/v2/health?strict=true', {}, true), { include_miradore: true });
  assert.deepEqual(withIncludeMiradore('/api/kpis', { a: 1 }, true), { a: 1 });
  assert.deepEqual(withIncludeMiradore('/api/forecast/v2/governance/log', { a: 1 }, true, 'post'), { a: 1 });
  assert.deepEqual(withIncludeMiradore('/api/forecast/v2/weekly', { include_miradore: false }, true), { include_miradore: false });
});

test('labels follow product, flag and backend scope', () => {
  const ok = { miradore_requested: true, miradore_included: true, reason: null };
  const down = { miradore_requested: true, miradore_included: false, reason: 'miradore_table_error' };
  assert.equal(miradoreNote({ productLine: 'ITSG', includeMiradore: true, scope: ok }).text, MIRADORE_INCLUDED_NOTE);
  assert.equal(miradoreNote({ productLine: 'All', includeMiradore: true, scope: ok }).kind, 'included');
  assert.deepEqual(miradoreNote({ productLine: 'ITSG', includeMiradore: true, scope: down }), { kind: 'unavailable', text: MIRADORE_UNAVAILABLE_NOTE });
  assert.equal(miradoreNote({ productLine: 'UCC', includeMiradore: true, scope: ok }), null);
  assert.equal(miradoreNote({ productLine: 'ITSG', includeMiradore: false, scope: ok }), null);
  assert.equal(miradoreNote({ productLine: 'ITSG', includeMiradore: true, scope: null }), null);
  assert.deepEqual(miradoreNote({ productLine: 'ITSG', includeMiradore: true, scope: ok, model: 'ets' }), { kind: 'model', text: MIRADORE_MODEL_NOTE });
  assert.equal(miradoreNote({ productLine: 'All', includeMiradore: true, scope: ok, tab: 'Model Lab' }).kind, 'model');
  assert.equal(miradoreNote({ productLine: 'ITSG', includeMiradore: true, scope: { miradore_requested: true, miradore_included: false, reason: 'model_views_exclude_miradore' } }).kind, 'model');
});
