import { DEFAULT_INCLUDE_MIRADORE } from './constants.js';

export const MIRADORE_STORAGE_KEY = 'forecast.includeMiradore';
export const MIRADORE_LABEL = 'Include Miradore (ITSG)';
export const MIRADORE_INCLUDED_NOTE = 'ITSG includes estimated Miradore bookings (trailing 3-month average; held flat beyond Dec 2026)';
export const MIRADORE_TOTAL_NOTE = "Total includes ITSG's estimated Miradore bookings (trailing 3-month average; held flat beyond Dec 2026)";
export const MIRADORE_UNAVAILABLE_NOTE = 'Miradore estimate unavailable — showing Salesforce only';
export const MIRADORE_MODEL_NOTE = 'Model views exclude Miradore (Salesforce only)';

const FORECAST_V2_PREFIX = '/api/forecast/v2/';

function defaultStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

// Persisted preference; every storage access is guarded (private windows, blocked storage).
export function readIncludeMiradore(storage = defaultStorage()) {
  try {
    const raw = storage?.getItem(MIRADORE_STORAGE_KEY);
    if (raw === 'true') return true;
    if (raw === 'false') return false;
  } catch { /* fall through to default */ }
  return DEFAULT_INCLUDE_MIRADORE;
}

export function writeIncludeMiradore(value, storage = defaultStorage()) {
  try { storage?.setItem(MIRADORE_STORAGE_KEY, String(Boolean(value))); } catch { /* non-fatal */ }
}

// The toggle only matters where ITSG numbers are shown (ITSG itself, or All via Total).
export function showMiradoreToggle(productLine) {
  return productLine === 'ITSG' || productLine === 'All' || productLine == null || productLine === '';
}

// Module-level current value, read by the api request interceptor so no call can miss it.
let current = null;
export function getIncludeMiradore() {
  if (current === null) current = readIncludeMiradore();
  return current;
}
export function setIncludeMiradore(value) {
  current = Boolean(value);
  writeIncludeMiradore(current);
  return current;
}

// Adds include_miradore=true|false to forecast v2 GET params; leaves everything else alone.
export function withIncludeMiradore(url, params, include, method = 'get') {
  if (String(method).toLowerCase() !== 'get' || typeof url !== 'string') return params;
  const path = url.split('?')[0];
  if (!path.startsWith(FORECAST_V2_PREFIX)) return params;
  if (params && Object.prototype.hasOwnProperty.call(params, 'include_miradore')) return params;
  return { ...(params ?? {}), include_miradore: Boolean(include) };
}

// Label for the numbers on screen. `scope` is the backend response's scope object.
export function miradoreNote({ productLine, includeMiradore, scope, model = 'ensemble', tab = null } = {}) {
  if (!includeMiradore || !showMiradoreToggle(productLine)) return null;
  if (tab === 'Model Lab' || (model && model !== 'ensemble')) return { kind: 'model', text: MIRADORE_MODEL_NOTE };
  if (!scope || scope.miradore_requested === false) return null;
  if (scope.miradore_included) {
    return { kind: 'included', text: productLine === 'ITSG' ? MIRADORE_INCLUDED_NOTE : MIRADORE_TOTAL_NOTE };
  }
  if (scope.reason === 'model_views_exclude_miradore') return { kind: 'model', text: MIRADORE_MODEL_NOTE };
  return { kind: 'unavailable', text: MIRADORE_UNAVAILABLE_NOTE };
}
