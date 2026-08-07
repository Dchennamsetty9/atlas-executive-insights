const toIsoDate = (d) => {
  const dt = new Date(d);
  const y = dt.getUTCFullYear();
  const m = String(dt.getUTCMonth() + 1).padStart(2, '0');
  const day = String(dt.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

export const buildDemoWeekly = (forecastType) => {
  const now = new Date();
  const rows = [];
  const actualWeeks = 14;
  const forecastWeeks = forecastType === 'roy' ? 18 : 13;
  const base = 11500000;

  for (let i = actualWeeks - 1; i >= 0; i -= 1) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - i * 7);
    const val = base + (actualWeeks - i) * 110000 + Math.sin(i / 2) * 150000;
    rows.push({ date: toIsoDate(d), arr_actual: Math.round(val), arr_worst: null, arr_likely: null, arr_best: null });
  }

  const fcBase = rows.length ? rows[rows.length - 1].arr_actual : base;
  for (let i = 1; i <= forecastWeeks; i += 1) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() + i * 7);
    const likely = fcBase + i * 130000 + Math.sin(i / 3) * 120000;
    rows.push({ date: toIsoDate(d), arr_actual: null, arr_worst: Math.round(likely * 0.93), arr_likely: Math.round(likely), arr_best: Math.round(likely * 1.08) });
  }

  return rows;
};

export const buildDemoYtd = (weeklyRows) => {
  let ytdActual = 0;
  let ytdWorst = 0;
  let ytdLikely = 0;
  let ytdBest = 0;

  return weeklyRows.map((r) => {
    if (r.arr_actual != null) ytdActual += r.arr_actual;
    if (r.arr_worst != null) ytdWorst += r.arr_worst;
    if (r.arr_likely != null) ytdLikely += r.arr_likely;
    if (r.arr_best != null) ytdBest += r.arr_best;
    return {
      date: r.date,
      ytd_actual: r.arr_actual != null ? Math.round(ytdActual) : null,
      ytd_worst: r.arr_worst != null ? Math.round(ytdWorst) : null,
      ytd_likely: r.arr_likely != null ? Math.round(ytdLikely) : null,
      ytd_best: r.arr_best != null ? Math.round(ytdBest) : null,
    };
  });
};

export const buildDemoMonthly = () => {
  const months = [
    { year: 2026, quarter: 2, month: 6, month_name: 'June' },
    { year: 2026, quarter: 3, month: 7, month_name: 'July' },
    { year: 2026, quarter: 3, month: 8, month_name: 'August' },
    { year: 2026, quarter: 3, month: 9, month_name: 'September' },
  ];
  return months.map((m, idx) => ({ ...m, arr_actual: idx === 0 ? 44200000 : null, arr_worst: 40500000 + idx * 1050000, arr_likely: 43100000 + idx * 1180000, arr_best: 46000000 + idx * 1260000 }));
};

export const buildDemoHistorical = () => {
  const rows = [];
  const years = [2024, 2025, 2026];
  years.forEach((y, yi) => {
    for (let w = 1; w <= 52; w += 1) {
      const seasonal = Math.sin((w / 52) * Math.PI * 2) * 1400000;
      const trend = yi * 900000;
      rows.push({ date: `${y}-${String(Math.min(12, Math.ceil(w / 4))).padStart(2, '0')}-01`, year: y, iso_week: w, quarter: Math.ceil(w / 13), arr: Math.round(31000000 + seasonal + trend) });
    }
  });
  return rows;
};

export const buildDemoByProduct = () => ({
  by_product: [
    { product: 'ITSG', product_line: 'ITSG', arr_worst: 122000000, arr_likely: 136000000, arr_best: 147000000, best_mape: 12.4 },
    { product: 'UCC', product_line: 'UCC', arr_worst: 108000000, arr_likely: 121000000, arr_best: 133000000, best_mape: 11.1 },
  ],
  by_product_line: [
    { product: 'ITSG', product_line: 'ITSG', arr_worst: 122000000, arr_likely: 136000000, arr_best: 147000000, best_mape: 12.4 },
    { product: 'UCC', product_line: 'UCC', arr_worst: 108000000, arr_likely: 121000000, arr_best: 133000000, best_mape: 11.1 },
  ],
  by_geo: [
    { sales_market: 'NA', arr_worst: 88000000, arr_likely: 99000000, arr_best: 109000000 },
    { sales_market: 'EMEA', arr_worst: 55000000, arr_likely: 63000000, arr_best: 70000000 },
    { sales_market: 'APAC', arr_worst: 44000000, arr_likely: 49000000, arr_best: 55000000 },
    { sales_market: 'LATAM', arr_worst: 29000000, arr_likely: 33000000, arr_best: 38000000 },
  ],
});

export const buildDemoLeaderboard = () => [
  { product: 'Total', sales_market: 'Total', Ensemble: 14.8, ETS: 17.1, Prophet: 16.2, MSTL_v2: 19.8, DHR_ARIMA: 23.6, LightGBM: 18.3, best_mape: 16.2, best_model: 'Prophet' },
  { product: 'UCC', sales_market: 'Total', ETS: 15.6, Prophet: 14.4, MSTL_v2: 17.0, DHR_ARIMA: 22.5, LightGBM: 20.7, best_mape: 14.4, best_model: 'Prophet' },
  { product: 'ITSG', sales_market: 'Total', ETS: 34.1, Prophet: 35.3, MSTL_v2: 40.8, DHR_ARIMA: 40.0, LightGBM: 117.0, best_mape: 34.1, best_model: 'ETS' },
  { product: 'Total', sales_market: 'NA', ETS: 17.5, Prophet: 16.7, MSTL_v2: 20.1, DHR_ARIMA: 24.0, LightGBM: 18.8, best_mape: 16.7, best_model: 'Prophet' },
  { product: 'Total', sales_market: 'EMEA', ETS: 18.2, Prophet: 17.1, MSTL_v2: 21.3, DHR_ARIMA: 25.1, LightGBM: 19.4, best_mape: 17.1, best_model: 'Prophet' },
  { product: 'Total', sales_market: 'APAC', ETS: 19.4, Prophet: 18.3, MSTL_v2: 22.6, DHR_ARIMA: 26.7, LightGBM: 20.9, best_mape: 18.3, best_model: 'Prophet' },
  { product: 'Total', sales_market: 'LATAM', ETS: 20.1, Prophet: 19.0, MSTL_v2: 23.4, DHR_ARIMA: 27.5, LightGBM: 21.7, best_mape: 19.0, best_model: 'Prophet' },
  { product: 'UCC', sales_market: 'NA', ETS: 15.1, Prophet: 13.9, MSTL_v2: 16.4, DHR_ARIMA: 21.8, LightGBM: 19.9, best_mape: 13.9, best_model: 'Prophet' },
];
