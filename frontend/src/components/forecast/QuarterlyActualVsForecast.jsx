import { useEffect, useState } from 'react';
import { apiService } from '../../services/api';
import { CardWrap, EmptyState, SectionTitle, Skeleton } from './common';
import {
  QUARTERLY_MODEL_COLUMNS, moneyM, signedPct, errorColor, statusLabel, forecastCell, quarterRows,
} from './quarterlyComparison';

const th = { padding: '8px 10px', color: '#94a3b8', borderBottom: '1px solid #ffffff12', fontWeight: 600, fontSize: 11, textAlign: 'right', whiteSpace: 'nowrap' };
const td = { padding: '9px 10px', textAlign: 'right', fontSize: 12, borderBottom: '1px solid #ffffff08', whiteSpace: 'nowrap' };

// Quarter-level actual vs forecast: what landed, what each model said, and the quarters still ahead (to the 18-month horizon).
export default function QuarterlyActualVsForecast({ prodLine, salesMarket, refreshVersion }) {
  const requestKey = `${prodLine}|${salesMarket}|${refreshVersion}`;
  const [result, setResult] = useState({ key: null, data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    apiService.getForecastV2QuarterlyActualVsForecast(prodLine, salesMarket)
      .then((res) => { if (!cancelled) setResult({ key: requestKey, data: res?.data && !res.quarters ? res.data : res, error: null }); })
      .catch((e) => { if (!cancelled) setResult({ key: requestKey, data: null, error: e.message || 'Quarterly actual vs forecast unavailable' }); });
    return () => { cancelled = true; };
  }, [prodLine, salesMarket, requestKey]);

  const loading = result.key !== requestKey;
  const { data, error } = result;

  const rows = quarterRows(data);
  const hasHistory = rows.some((q) => Object.keys(q.models || {}).length > 0);

  return (
    <CardWrap downloadName="quarterly_actual_vs_forecast">
      <SectionTitle>Quarterly actual vs forecast{prodLine && prodLine !== 'All' ? ` · ${prodLine}` : ''}</SectionTitle>
      <p style={{ color: '#64748b', fontSize: 11, marginBottom: 12, lineHeight: 1.5 }}>
        Closed quarters compare what landed with what each model forecast <b style={{ color: '#94a3b8' }}>as first published</b>, over the same weeks.
        Error is signed: <b style={{ color: '#94a3b8' }}>+ = over-forecast, − = under-forecast</b>. The current and future quarters show the
        projected landing (actual to date + forecast for the open weeks) out to {data?.horizon_months || 18} months.
      </p>
      {loading ? <Skeleton height={220} /> : error ? <EmptyState message={error} /> : rows.length === 0 ? <EmptyState message={data?.history_note || 'No quarterly data available.'} /> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: 'left' }}>Quarter</th>
                <th style={th}>Actual</th>
                <th style={th}>Forecast / landing</th>
                {hasHistory && QUARTERLY_MODEL_COLUMNS.map((m) => <th key={m.key} style={th}>{m.label} error</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((q) => {
                const fc = forecastCell(q);
                return (
                  <tr key={q.label}>
                    <td style={{ ...td, textAlign: 'left', color: '#e2e8f0', fontWeight: 700 }}>
                      {q.label}
                      <div style={{ color: '#64748b', fontSize: 10, fontWeight: 400 }}>{statusLabel(q)}</div>
                    </td>
                    <td style={{ ...td, color: '#f59e0b', fontWeight: 700 }}>
                      {q.actual != null ? moneyM(q.actual) : '—'}
                      {q.status === 'in_progress' && <div style={{ color: '#64748b', fontSize: 10, fontWeight: 400 }}>to date</div>}
                    </td>
                    <td style={{ ...td, color: '#93c5fd', fontWeight: 700 }}>
                      {moneyM(fc.value)}
                      <div style={{ color: '#64748b', fontSize: 10, fontWeight: 400 }}>{fc.note}</div>
                    </td>
                    {hasHistory && QUARTERLY_MODEL_COLUMNS.map((m) => {
                      const cell = q.models?.[m.key];
                      return (
                        <td key={m.key} style={{ ...td, color: cell ? errorColor(cell.error_pct) : '#475569', fontWeight: 700 }}
                          title={cell ? `${m.label}: forecast ${moneyM(cell.forecast)} vs actual ${moneyM(cell.actual_matched)} over ${cell.weeks} weeks` : undefined}>
                          {cell ? signedPct(cell.error_pct) : '—'}
                          {cell && <div style={{ color: '#64748b', fontSize: 10, fontWeight: 400 }}>{moneyM(cell.forecast)}</div>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data?.history_note && rows.length > 0 && <p style={{ color: '#fbbf24', fontSize: 11, marginTop: 10 }}>{data.history_note}</p>}
      {hasHistory && <p style={{ color: '#64748b', fontSize: 10, marginTop: 10 }}>
        Model columns show error % with the model's forecast underneath. The current quarter's model figures cover only the weeks that have closed.
        History starts when forecast vintages began to be retained, so earlier quarters are not shown.
      </p>}
    </CardWrap>
  );
}
