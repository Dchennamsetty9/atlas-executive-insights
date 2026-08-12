/**
 * LargestDealsTable — Top 20 largest open deals.
 * Sortable columns: Amount, Stage, Close Date, Days in Stage.
 * Color coding by stage_category: early=blue, mid=amber, late=green.
 * Flags: 🔥 = in-quarter, ⚠️ = slipped.
 * AI concentration risk banner at top.
 */

import { useState, useEffect } from 'react';

const fmtM = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(0)}K`;
  return `$${Math.round(v)}`;
};

/** Deal velocity: 'hot' | 'progressing' | 'stalled' | 'stuck'
 *  Based on days_in_stage vs. stage benchmarks. */
function velocityScore(deal) {
  const d = deal.days_in_stage ?? 0;
  const cat = deal.stage_category ?? 'mid';
  const benchmarks = { early: 14, mid: 21, late: 14 };
  const bench = benchmarks[cat] ?? 21;
  if (d <= bench * 0.5) return { label: '🔥 Hot',        color: '#10b981' };
  if (d <= bench)       return { label: '↗ Progressing', color: '#3b82f6' };
  if (d <= bench * 2)   return { label: '⚡ Stalled',    color: '#f59e0b' };
  return                       { label: '🔴 Stuck',      color: '#ef4444' };
}

/** Derive a "next action needed" suggestion based on stage and days in stage. */
function nextAction(deal) {
  const d = deal.days_in_stage ?? 0;
  const stage = (deal.stage ?? '').toLowerCase();
  if (d > 30) return 'Escalate to manager';
  if (stage.includes('negotiat')) return 'Send final proposal';
  if (stage.includes('discover')) return 'Schedule demo';
  if (stage.includes('qualify'))  return 'Confirm champion';
  if (stage.includes('propos'))   return 'Follow up on proposal';
  if (stage.includes('close'))    return 'Confirm PO / contract';
  return 'Check in with prospect';
}

const fmtDate = (d) => {
  if (!d) return '—';
  const dt = new Date(d);
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
};

const STAGE_COLORS = {
  early: { border: '#3b82f6', bg: 'rgba(59,130,246,0.08)' },
  mid:   { border: '#f59e0b', bg: 'rgba(245,158,11,0.08)' },
  late:  { border: '#10b981', bg: 'rgba(16,185,129,0.08)' },
};

const COLS = [
  { key: 'rank',            label: '#',           style: { width: 28 },    align: 'center', sortable: false },
  { key: 'name',            label: 'Deal Name',   style: { minWidth: 160 }, align: 'left',  sortable: false },
  { key: 'amount',          label: 'Amount',      style: { width: 90 },    align: 'right', sortable: true },
  { key: 'stage',           label: 'Stage',       style: { minWidth: 100 }, align: 'left',  sortable: false },
  { key: 'close_date',      label: 'Close',       style: { width: 80 },    align: 'center', sortable: true },
  { key: 'channel',         label: 'Channel',     style: { width: 80 },    align: 'center', sortable: false },
  { key: 'owner',           label: 'Owner',       style: { minWidth: 90 }, align: 'left',  sortable: false },
  { key: 'days_in_stage',   label: 'Days in Stage', style: { width: 90 }, align: 'right', sortable: true },
  { key: 'velocity',        label: 'Velocity',    style: { width: 80 },    align: 'center', sortable: false },
  { key: 'next_action',     label: 'Next Action', style: { minWidth: 120 }, align: 'left', sortable: false },
];

const LargestDealsTable = ({ limit = 20 }) => {
  const [deals,   setDeals]   = useState([]);
  const [insight, setInsight] = useState('');
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState('amount');
  const [sortDir, setSortDir] = useState('desc');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const res  = await fetch(`/api/deals/largest-open?limit=${limit}`);
        const json = await res.json();
        if (cancelled) return;
        setDeals(json.data ?? []);
        setInsight(json.insight ?? '');
      } catch (e) {
        console.error('LargestDealsTable load error', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [limit]);

  const handleSort = (key) => {
    if (!COLS.find(c => c.key === key)?.sortable) return;
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  const sorted = [...deals].sort((a, b) => {
    const av = sortKey === 'close_date' ? new Date(a[sortKey]) : (a[sortKey] ?? 0);
    const bv = sortKey === 'close_date' ? new Date(b[sortKey]) : (b[sortKey] ?? 0);
    if (av < bv) return sortDir === 'desc' ? 1 : -1;
    if (av > bv) return sortDir === 'desc' ? -1 : 1;
    return 0;
  });

  const thStyle = (key) => ({
    padding: '6px 8px',
    textAlign: COLS.find(c => c.key === key)?.align ?? 'left',
    fontSize: 9,
    fontWeight: 700,
    color: sortKey === key ? '#3b82f6' : '#475569',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    cursor: COLS.find(c => c.key === key)?.sortable ? 'pointer' : 'default',
    whiteSpace: 'nowrap',
    userSelect: 'none',
  });

  return (
    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
      {/* Header */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>🏆 Largest Open Deals</div>
        <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>Top {limit} open opportunities by ARR — sorted by {sortKey.replace('_', ' ')}</div>
      </div>

      {/* AI Insight Banner */}
      {insight && (
        <div style={{
          marginBottom: 10, padding: '8px 12px', borderRadius: '0 6px 6px 0',
          borderLeft: '3px solid #f59e0b',
          background: 'rgba(245,158,11,0.08)',
          fontSize: 11, color: '#cbd5e1', lineHeight: 1.5,
        }}>
          <span style={{ color: '#f59e0b', marginRight: 6 }}>⚠️</span>
          {insight}
        </div>
      )}

      {loading ? (
        <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
          Loading deals…
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                {COLS.map(col => (
                  <th key={col.key} style={{ ...thStyle(col.key), ...col.style }} onClick={() => handleSort(col.key)}>
                    {col.label}
                    {col.sortable && sortKey === col.key && (
                      <span style={{ marginLeft: 3 }}>{sortDir === 'desc' ? '↓' : '↑'}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((deal, i) => {
                const cat   = deal.stage_category ?? 'mid';
                const clr   = STAGE_COLORS[cat] ?? STAGE_COLORS.mid;
                const rowBg = i % 2 === 0 ? 'rgba(255,255,255,0.015)' : 'transparent';
                const vel   = velocityScore(deal);
                const next  = nextAction(deal);
                return (
                  <tr key={deal.opportunity_id ?? i} style={{
                    background: rowBg,
                    borderBottom: '1px solid rgba(255,255,255,0.03)',
                    borderLeft: `2px solid ${clr.border}`,
                  }}>
                    <td style={{ padding: '5px 8px', textAlign: 'center', fontSize: 10, color: '#475569' }}>{i + 1}</td>
                    <td style={{ padding: '5px 8px', fontSize: 11, color: '#f1f5f9', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {deal.in_quarter && <span title="In-quarter deal" style={{ marginRight: 4 }}>🔥</span>}
                      {deal.slipped    && <span title="Slipped"         style={{ marginRight: 4 }}>⚠️</span>}
                      {deal.name}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontSize: 11, fontWeight: 700, color: '#3b82f6' }}>{fmtM(deal.amount)}</td>
                    <td style={{ padding: '5px 8px', fontSize: 10, color: clr.border }}>{deal.stage}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'center', fontSize: 10, color: '#94a3b8' }}>{fmtDate(deal.close_date)}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'center', fontSize: 10, color: '#64748b' }}>{deal.channel}</td>
                    <td style={{ padding: '5px 8px', fontSize: 10, color: '#94a3b8', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{deal.owner}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontSize: 10, color: deal.days_in_stage > 30 ? '#f59e0b' : '#64748b', fontWeight: deal.days_in_stage > 30 ? 700 : 400 }}>
                      {deal.days_in_stage}d
                    </td>
                    {/* Velocity score */}
                    <td style={{ padding: '5px 8px', textAlign: 'center', fontSize: 10, color: vel.color, fontWeight: 600, whiteSpace: 'nowrap' }}>
                      {vel.label}
                    </td>
                    {/* Next action */}
                    <td style={{ padding: '5px 8px', fontSize: 10, color: '#94a3b8', whiteSpace: 'nowrap' }}>
                      {next}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Legend */}
          <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 9, color: '#475569' }}>
            {Object.entries(STAGE_COLORS).map(([cat, c]) => (
              <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 8, height: 8, borderRadius: 2, background: c.border }} />
                <span style={{ textTransform: 'capitalize' }}>{cat} stage</span>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>🔥 In-quarter</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>⚠️ Slipped</div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LargestDealsTable;
