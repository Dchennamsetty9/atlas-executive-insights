import { formatModelLabel, mapeColor } from '../common';

const AccuracyTable = ({ data }) => {
  const allModels = [
    { key: 'ETS', label: formatModelLabel('ETS') },
    { key: 'Prophet', label: formatModelLabel('Prophet') },
    { key: 'LightGBM', label: formatModelLabel('LightGBM') },
  ];

  const hasMstl = data?.some((r) => r.MSTL_v2 != null && r.MSTL_v2 < 999);
  const hasDhr = data?.some((r) => r.DHR_ARIMA != null && r.DHR_ARIMA < 999);
  const hasEns = data?.some((r) => r.Ensemble != null && r.Ensemble < 999);

  const models = [
    ...(hasEns ? [{ key: 'Ensemble', label: 'Ensemble ★' }] : []),
    ...allModels,
    ...(hasMstl ? [{ key: 'MSTL_v2', label: formatModelLabel('MSTL_v2') }] : []),
    ...(hasDhr ? [{ key: 'DHR_ARIMA', label: formatModelLabel('DHR_ARIMA') }] : []),
  ];

  const hiddenModels = [!hasMstl && 'MSTL', !hasDhr && 'DHR-ARIMA'].filter(Boolean).join(', ');

  const scoreVal = (r, key) => {
    const v = r?.[key];
    return v && v < 999 ? Number(v) : null;
  };

  const monthlyVal = (r, key) => {
    const cands = [
      `${key}_monthly`,
      `${key}_month`,
      `${key}_m`,
      `${key}_monthly_mape`,
    ];
    for (const c of cands) {
      const v = r?.[c];
      if (v != null && Number(v) < 999) return Number(v);
    }
    return null;
  };

  return (
    <div>
      {hasEns && (
        <div style={{ fontSize: 10, color: '#64748b', marginBottom: 8 }}>
          ★ Ensemble MAPE is realized accuracy — past forecasts vs weeks that later closed as actuals.
          Individual models are scored on holdout validation.
        </div>
      )}
      {hiddenModels && (
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, padding: '6px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)' }}>
          ℹ️ {hiddenModels} — columns hidden; leaderboard data unavailable for these models.
        </div>
      )}
      <div style={{ fontSize: 10, color: '#64748b', marginBottom: 8 }}>Model cells are shown as <b style={{ color: '#cbd5e1' }}>weekly / monthly</b> MAPE when monthly values are available.</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
              {['Product', 'Geo', ...models.map((m) => m.label), 'Best Model', 'Best MAPE'].map((h) => (
                <th key={h} style={{ padding: '6px 12px', textAlign: ['Product', 'Geo', 'Best Model'].includes(h) ? 'left' : 'right', fontSize: 10, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data || []).map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', background: i % 2 === 0 ? 'rgba(255,255,255,0.01)' : 'transparent' }}>
                <td style={{ padding: '6px 12px', fontSize: 12, color: '#f1f5f9' }}>{r.product}</td>
                <td style={{ padding: '6px 12px', fontSize: 11, color: '#64748b' }}>{r.sales_market}</td>
                {models.map((m) => (
                  <td key={m.key} style={{ padding: '6px 12px', textAlign: 'right', fontSize: 11, color: '#cbd5e1', fontWeight: r.best_model === m.key ? 700 : 400 }}>
                    <span style={{ color: scoreVal(r, m.key) != null ? mapeColor(scoreVal(r, m.key)) : '#334155' }}>{scoreVal(r, m.key) != null ? `${scoreVal(r, m.key).toFixed(1)}%` : '—'}</span>
                    <span style={{ color: '#64748b' }}> / </span>
                    <span style={{ color: monthlyVal(r, m.key) != null ? mapeColor(monthlyVal(r, m.key)) : '#334155' }}>{monthlyVal(r, m.key) != null ? `${monthlyVal(r, m.key).toFixed(1)}%` : '—'}</span>
                    {r.best_model === m.key && <span style={{ marginLeft: 4, fontSize: 9 }}>★</span>}
                  </td>
                ))}
                <td style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, color: '#f59e0b', fontWeight: 600 }}>{formatModelLabel(r.best_model)}</td>
                <td style={{ padding: '6px 12px', textAlign: 'right', fontSize: 12, fontWeight: 700, color: r.best_mape && r.best_mape < 999 ? mapeColor(r.best_mape) : '#334155' }}>
                  {r.best_mape && r.best_mape < 999 ? `${r.best_mape.toFixed(1)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default AccuracyTable;
