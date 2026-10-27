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

// Quarter total for the monthly scenario table.
// - Closed quarters have no scenario values at all: return null (rendered as a dash), never $0.
// - Partly closed quarters: a month with an actual but no scenario contributes its actual to the
//   most-likely landing (zero band width), so the total is not understated.
// - Bands of forecast months combine in quadrature (matches the Overview KPI aggregation).
export function quarterScenarioTotals(months) {
  const rows = months || [];
  const arrActual = sumAvailable(rows, 'arr_actual');
  if (!rows.some(m => m.arr_likely != null)) {
    return { arr_actual: arrActual, arr_worst: null, arr_likely: null, arr_best: null };
  }
  let likely = 0; let loSq = 0; let upSq = 0;
  for (const m of rows) {
    const lk = m.arr_likely ?? m.arr_actual ?? 0;
    likely += lk;
    if (m.arr_likely != null) {
      const lo = Math.max(0, lk - (m.arr_worst ?? lk));
      const up = Math.max(0, (m.arr_best ?? lk) - lk);
      loSq += lo * lo; upSq += up * up;
    }
  }
  return {
    arr_actual: arrActual,
    arr_likely: likely,
    arr_worst: Math.max(0, likely - Math.sqrt(loSq)),
    arr_best: likely + Math.sqrt(upSq),
  };
}
