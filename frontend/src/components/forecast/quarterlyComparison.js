// Presentation helpers for /quarterly-actual-vs-forecast. Show only what the API returned; never fill gaps.

export const QUARTERLY_MODEL_COLUMNS = [
  { key: 'ensemble', label: 'Ensemble' },
  { key: 'ets', label: 'ETS' },
  { key: 'lightgbm', label: 'LightGBM' },
  { key: 'mstl_v2', label: 'MSTL' },
  { key: 'dhr_arima', label: 'DHR-ARIMA' },
];

const finite = (v) => (v === null || v === undefined || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : null));

export const moneyM = (v) => {
  const n = finite(v);
  if (n === null) return '—';
  return `$${(n / 1e6).toFixed(2)}M`;
};

// Signed: positive means the model over-forecast the quarter.
export const signedPct = (v) => {
  const n = finite(v);
  if (n === null) return '—';
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`;
};

export const errorColor = (v) => {
  const n = finite(v);
  if (n === null) return '#94a3b8';
  const a = Math.abs(n);
  return a < 5 ? '#10b981' : a < 10 ? '#f59e0b' : '#ef4444';
};

export const statusLabel = (q) => {
  if (q.status === 'in_progress') return `In progress · ${q.actual_weeks || 0} wks closed`;
  if (q.status === 'forecast') return 'Forecast only';
  return 'Closed';
};

// The "forecast" figure that sits next to the actual for a quarter:
//  closed -> Ensemble forecast as first published for the weeks that closed
//  in progress / future -> projected landing (actual to date + forecast for the open weeks)
export const forecastCell = (q) => {
  if (q.status === 'closed') {
    const ens = q.models?.ensemble;
    return ens ? { value: ens.forecast, note: `${ens.weeks} wks, as first published` } : { value: null, note: 'No retained forecast' };
  }
  const p = q.projection;
  if (!p) return { value: null, note: 'No forecast published' };
  return { value: p.landing_likely, note: `${moneyM(p.landing_low)} – ${moneyM(p.landing_high)}` };
};

export const quarterRows = (data) => (Array.isArray(data?.quarters) ? data.quarters : []);
