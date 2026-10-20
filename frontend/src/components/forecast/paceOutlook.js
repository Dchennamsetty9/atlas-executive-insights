// Presentation helpers for /pace-outlook. Never combine errors across products; show only what the API returned.
export const paceBadge = (row) => row?.validated
  ? { text: 'Validated', kind: 'validated' }
  : { text: 'Indicative', kind: 'indicative' };

export const paceBacktestText = (row) => {
  if (!row?.validated) return 'Not yet validated at this point in the quarter';
  const out = row.backtest_mape_pct, mod = row.model_mape_pct;
  if (typeof out !== 'number' || typeof mod !== 'number') return 'Validated in backtest';
  const q = row.n_quarters;
  return `Backtest error ${out.toFixed(1)}% vs ${mod.toFixed(1)}% for the static forecast`
    + (typeof q === 'number' && q > 0 ? ` (${q} quarters)` : '');
};

// Returns null when there is nothing trustworthy to show.
export const paceView = (pace) => {
  if (!pace || pace.source !== 'live' || !Array.isArray(pace.products) || pace.products.length === 0) return null;
  const rows = pace.products
    .filter((r) => typeof r.outlook_landing === 'number' && typeof r.model_landing === 'number')
    .map((r) => ({ ...r, delta: r.outlook_landing - r.model_landing, badge: paceBadge(r), backtest: paceBacktestText(r) }));
  if (rows.length === 0) return null;
  const total = pace.total && typeof pace.total.outlook_landing === 'number'
    ? { ...pace.total, delta: pace.total.outlook_landing - pace.total.model_landing, badge: paceBadge(pace.total) } : null;
  return { quarter: pace.quarter_label, asof: pace.asof_date ?? null, rows, total };
};
