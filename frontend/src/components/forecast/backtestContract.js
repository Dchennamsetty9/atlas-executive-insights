export const backtestScope = (product, market, model, horizon) => ({
  product: !product || ['all', 'total'].includes(product.toLowerCase()) ? 'Total' : product.toUpperCase(),
  sales_market: !market || ['all', 'total'].includes(market.toLowerCase()) ? 'Total' : market,
  model,
  horizon_weeks: horizon,
});

export const backtestRequestKey = scope => JSON.stringify([
  scope.product, scope.sales_market, scope.model, scope.horizon_weeks,
]);

export const backtestResponseMatches = (response, scope) => Boolean(response &&
  ['live', 'unavailable'].includes(response.source) &&
  Object.entries(scope).every(([key, value]) => response[key] === value));

// ISO date-only targets must not shift to the previous day in a local timezone.
export const backtestDate = value => value
  ? new Date(`${String(value).slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', timeZone: 'UTC',
  }) : '—';