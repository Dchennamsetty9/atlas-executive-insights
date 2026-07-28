import { fmtM } from '../common';

const MonthlyTable = ({ months }) => {
  const quarters = [...new Set((months || []).map((m) => m.quarter))].sort();
  const byQtr = {};
  for (const m of months || []) {
    if (!byQtr[m.quarter]) byQtr[m.quarter] = [];
    byQtr[m.quarter].push(m);
  }

  const td = { padding: '6px 12px', textAlign: 'right', fontSize: 12, color: '#94a3b8', borderBottom: '1px solid rgba(255,255,255,0.04)' };
  const th = { padding: '6px 12px', textAlign: 'right', fontSize: 10, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' };
  const inProgressMonthKey = (() => {
    const open = (months || []).find((m) => m.arr_actual == null);
    return open ? `${open.year}-${open.month}` : null;
  })();

  const spark = (worst, likely, best) => {
    const INNER_Z_RATIO = 0.6745 / 1.2816;
    const innerLo = likely - (likely - worst) * INNER_Z_RATIO;
    const innerHi = likely + (best - likely) * INNER_Z_RATIO;
    const vals = [worst, innerLo, likely, innerHi, best];
    const nums = vals.map((v) => Number(v || 0));
    const min = Math.min(...nums);
    const max = Math.max(...nums);
    const span = Math.max(1, max - min);
    const points = nums.map((v, i) => {
      const x = i * 12;
      const y = 24 - ((v - min) / span) * 20;
      return `${x},${y}`;
    }).join(' ');
    return <svg width="60" height="24" viewBox="0 0 60 24" style={{ overflow: 'visible' }}><polyline fill="none" stroke="#93c5fd" strokeWidth="1.8" points={points} /></svg>;
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            {['Year', 'Qtr', 'Month', 'Actuals', 'Forecast', 'Target', 'Variance %', 'Sparkline'].map((h) => (
              <th key={h} style={{ ...th, textAlign: ['Month', 'Year', 'Qtr'].includes(h) ? 'left' : 'right' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {quarters.map((q) => {
            const qm = byQtr[q] || [];
            const tot = qm.reduce((a, m) => ({
              arr_actual: m.arr_actual != null ? (a.arr_actual ?? 0) + m.arr_actual : a.arr_actual,
              arr_worst: a.arr_worst + m.arr_worst,
              arr_likely: a.arr_likely + m.arr_likely,
              arr_best: a.arr_best + m.arr_best,
            }), { arr_actual: null, arr_worst: 0, arr_likely: 0, arr_best: 0 });

            return [
              ...qm.map((m, i) => (
                <tr key={`${q}-${m.month}`} style={{ background: i % 2 === 0 ? 'rgba(255,255,255,0.01)' : 'transparent' }}>
                  <td style={{ ...td, textAlign: 'left', color: '#64748b' }}>{i === 0 ? m.year : ''}</td>
                  <td style={{ ...td, textAlign: 'left', color: '#64748b' }}>{i === 0 ? `Q${q}` : ''}</td>
                  <td style={{ ...td, textAlign: 'left', color: '#f1f5f9', fontWeight: inProgressMonthKey === `${m.year}-${m.month}` ? 800 : 500 }}>{m.month_name}{inProgressMonthKey === `${m.year}-${m.month}` ? ' · in progress' : ''}</td>
                  <td style={{ ...td, color: m.arr_actual ? '#f59e0b' : '#334155' }}>{fmtM(m.arr_actual)}</td>
                  <td style={{ ...td, color: '#f1f5f9', fontWeight: 600 }}>{fmtM(m.arr_likely)}</td>
                  <td style={{ ...td, color: '#10b981' }}>{fmtM(m.arr_target ?? m.arr_best ?? m.arr_likely)}</td>
                  <td style={{ ...td, color: (() => {
                    const target = Number((m.arr_target ?? m.arr_best ?? m.arr_likely) || 0);
                    const base = m.arr_actual != null ? Number(m.arr_actual) : Number(m.arr_likely || 0);
                    if (!target) return '#64748b';
                    const v = ((base - target) / target) * 100;
                    return v >= 0 ? '#10b981' : '#ef4444';
                  })() }}>
                    {(() => {
                      const target = Number((m.arr_target ?? m.arr_best ?? m.arr_likely) || 0);
                      const base = m.arr_actual != null ? Number(m.arr_actual) : Number(m.arr_likely || 0);
                      if (!target) return '—';
                      const v = ((base - target) / target) * 100;
                      return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
                    })()}
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}>{spark(m.arr_worst, m.arr_likely, m.arr_best)}</td>
                </tr>
              )),
              <tr key={`qtot-${q}`} style={{ background: 'rgba(59,130,246,0.06)', borderTop: '1px solid rgba(59,130,246,0.2)' }}>
                <td style={{ ...td, textAlign: 'left', color: '#64748b' }} />
                <td style={{ ...td, textAlign: 'left', color: '#3b82f6', fontWeight: 700 }}>Total</td>
                <td style={{ ...td, textAlign: 'left', color: '#3b82f6', fontWeight: 700 }}>{`Q${q} Total`}</td>
                <td style={{ ...td, color: '#f59e0b', fontWeight: 700 }}>{fmtM(tot.arr_actual)}</td>
                <td style={{ ...td, color: '#f1f5f9', fontWeight: 700 }}>{fmtM(tot.arr_likely)}</td>
                <td style={{ ...td, color: '#10b981', fontWeight: 700 }}>{fmtM(tot.arr_best)}</td>
                <td style={{ ...td, color: '#64748b', fontWeight: 700 }}>—</td>
                <td style={{ ...td, color: '#64748b', fontWeight: 700 }}>—</td>
              </tr>,
            ];
          })}
        </tbody>
      </table>
    </div>
  );
};

export default MonthlyTable;
