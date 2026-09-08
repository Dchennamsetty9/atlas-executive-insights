// Presentation only: never synthesize combined errors or substitute weekly values.
export const accuracyProducts = product => ['All', 'Total', '', null, undefined].includes(product) ? ['UCC', 'ITSG'] : [product];

export const quarterlyRow = (rows, product) => (rows || []).find(row =>
  row.product === product && ['Total', 'All'].includes(row.sales_market));

export const quarterlyValue = (rows, product, model) => {
  const value = quarterlyRow(rows, product)?.quarterly_errors?.[model];
  return (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) && Number.isFinite(Number(value))
    ? Number(value) : null;
};

export const errorPercent = value => value == null ? '—' : `${value.toFixed(1)}%`;

export const quarterlyPill = (rows, product, model) => {
  const products = accuracyProducts(product);
  return products.length > 1
    ? `Qtr · ${products.map(p => `${p} ${errorPercent(quarterlyValue(rows, p, model))}`).join(' · ')}`
    : `Qtr ${errorPercent(quarterlyValue(rows, product, model))}`;
};

// Preserve source date precision; do not label a browser retrieval time as publication time.
export const sourceDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}(?:$|[T ])/.test(value) && Number.isFinite(Date.parse(value))
  ? value : 'Not supplied by source';

export const backtestFreshness = rows => {
  const latest = field => (rows || []).map(row => row[field]).filter(value => sourceDate(value) !== 'Not supplied by source')
    .sort((a, b) => Date.parse(a) - Date.parse(b)).at(-1);
  return { forecast: sourceDate(latest('origin_ts')), actual: sourceDate(latest('actual_run_date')) };
};

export const backtestGuidance = reason => ({
  combined_history_unverified: 'Select UCC or ITSG. A combined backtest requires aligned forecast origins and target weeks, not averaged errors.',
  region_history_unverified: 'Select All regions to view verified product-total history.',
  model_history_unverified: 'Select a model with verified retained history, such as Ensemble. Native Prophet is not the retained Prophet trend model.',
  no_matched_history: 'Try a shorter horizon. More history requires retained forecasts and closed actual weeks; the next daily run may not supply a match.',
  invalid_history: 'The source history needs review. Ambiguous or invalid pairs are excluded rather than scored.',
  source_query_failed: 'Refresh to retry the source read. Previously loaded or demo values are not substituted.',
  source_unavailable: 'Live history must be connected before these results can be shown.',
}[reason] || 'No verified history is available for this selection. No other product’s results are substituted.');