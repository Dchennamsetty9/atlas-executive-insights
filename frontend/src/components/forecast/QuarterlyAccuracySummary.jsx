import { accuracyProducts, quarterlyRow, quarterlyValue, quarterlyEvidence, quarterlyBasis, errorPercent, sourceDate } from './accuracyPresentation';

export default function QuarterlyAccuracySummary({ rows, product, models, modelKeys, modelMeta, color }) {
  const products = accuracyProducts(product);
  return <>
    <p style={{ color: '#94a3b8', fontSize: 11, marginBottom: 12 }}>
      Latest source publication (leaderboard run date): {products.map(p => `${p}: ${sourceDate(quarterlyRow(rows, p)?.publication_date)}`).join(' · ')}
      {' '}— publication date, not the evaluated quarter or the time this page checked.
    </p>
    {products.length > 1 ? <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
        <thead><tr>{['Model', ...products.map(p => `${p} quarterly error`)].map(label =>
          <th key={label} style={{ padding: '10px 12px', color: '#94a3b8', borderBottom: '1px solid #ffffff12' }}>{label}</th>)}</tr></thead>
        <tbody>{models.map(key => <tr key={key}>
          <td style={{ padding: '10px 12px', color: '#e2e8f0' }}>{modelMeta[key].label}</td>
          {products.map(p => {
            const value = quarterlyValue(rows, p, modelKeys[key]);
            const evidence = quarterlyEvidence(rows, p, modelKeys[key]);
            return <td key={p} style={{ padding: '10px 12px', color: evidence.status === 'measured' ? color(value) : '#94a3b8', fontWeight: 700 }}>
              {errorPercent(value)}
              <div style={{ color: '#94a3b8', fontSize: 11, fontWeight: 400, marginTop: 4 }}>{quarterlyBasis(rows, p, modelKeys[key])}</div>
              {evidence.source_model && <div style={{ color: '#94a3b8', fontSize: 10, fontWeight: 400, overflowWrap: 'anywhere' }}>{evidence.source_model}</div>}
            </td>;
          })}
        </tr>)}</tbody>
      </table>
      <p style={{ color: '#94a3b8', fontSize: 11, marginTop: 10 }}>Product results are shown separately. Error percentages are not averaged into a combined accuracy.</p>
    </div> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
      {models.map(key => {
        const value = quarterlyValue(rows, product, modelKeys[key]);
        const evidence = quarterlyEvidence(rows, product, modelKeys[key]);
        return <div key={key} style={{ padding: 12, borderRadius: 8, border: '1px solid #ffffff12' }}>
          <div style={{ color: '#94a3b8', fontSize: 11 }}>{modelMeta[key].label}</div>
          <div style={{ color: evidence.status === 'measured' ? color(value) : '#94a3b8', fontSize: 22, fontWeight: 700 }}>{errorPercent(value)}</div>
          <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 4 }}>{quarterlyBasis(rows, product, modelKeys[key])}</div>
          {evidence.source_model && <div style={{ color: '#94a3b8', fontSize: 10, overflowWrap: 'anywhere', marginTop: 4 }}>{evidence.source_model}</div>}
        </div>;
      })}
    </div>}
    <p style={{ color: '#93c5fd', fontSize: 11, marginTop: 12 }}>Different measures: published quarterly error shown here is not used to calculate retained weekly backtest MAPE. Their values should not be expected to match.</p>
  </>;
}