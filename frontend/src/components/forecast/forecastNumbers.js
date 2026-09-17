export function formatWeekDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

export function sumAvailable(rows, field) {
  const values = rows.map(row => row[field]).filter(value => value != null && Number.isFinite(value));
  return values.length ? values.reduce((total, value) => total + value, 0) : null;
}

export function monthlyTotals(months) {
  return Object.fromEntries(['arr_actual', 'arr_predicted', 'arr_likely', 'arr_worst', 'arr_best']
    .map(field => [field, sumAvailable(months, field)]));
}

export function uniqueWeeks(rows) {
  const weeks = new Map();
  for (const row of rows) {
    if (!weeks.has(row.date) || row.type === 'actual') weeks.set(row.date, row);
  }
  return [...weeks.values()].sort((left, right) => left.date.localeCompare(right.date));
}