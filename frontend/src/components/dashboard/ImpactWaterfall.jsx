/**
 * ImpactWaterfall — Revenue Gap Decomposition (two-funnel model).
 *
 * Mirrors the KPI Trends — Overview Power BI dashboard exactly:
 *
 *   Opp Volume Funnel:
 *     Opened Opps × Close Rate (Vol) = Won Opps → Won Opps × ADS = Won Amount
 *
 *   Dollar Funnel:
 *     Opened Opps × Avg Opp Size = Pipeline → Pipeline × Close Rate ($) = Won Amount
 *
 * Additivity rule (within each funnel equation):
 *   Opened Opps impact + Close Rate (Vol) impact = Won Opps impact
 *   Pipeline impact    + Close Rate ($) impact   = Won Amount impact
 *
 * Data source: /api/insights/impact-decomposition
 *   → decomp.funnel_opp_volume  { "Opened Opps", "Close Rate (Vol)", "Won Opps", "ADS" }
 *   → decomp.funnel_dollar      { "Avg Opp Size", "Pipeline ($)", "Close Rate ($)" }
 *   → decomp.impact_dollars     total Won Amount gap
 */

import { useEffect, useState } from 'react';
import { ComposedChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

// ── Helpers ───────────────────────────────────────────────────────────────────

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtDollar = (v) => {
  if (v == null) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '−' : '+';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)     return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
};

const fmtDollarTotal = (v) => {
  if (v == null) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '(' : '';
  const end  = v < 0 ? ')' : '';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M${end}`;
  if (abs >= 1_000)     return `${sign}$${(abs / 1_000).toFixed(1)}K${end}`;
  return `${sign}$${abs.toFixed(0)}${end}`;
};

// ── WaterfallChart — recharts-based proper waterfall ─────────────────────────

/** Build waterfall chart data from named impact values.
 *  Returns [{name, base, bar, color, value}] ready for recharts ComposedChart. */
function buildWaterfallData(factors) {
  const rows = [];
  let running = 0;
  factors.forEach(([name, value]) => {
    const isNeg = value < 0;
    const base  = isNeg ? running + value : running;
    rows.push({ name, base, bar: Math.abs(value), color: isNeg ? '#ef4444' : '#10b981', value });
    running += value;
  });
  // Total bar
  rows.push({ name: 'Gap Total', base: 0, bar: Math.abs(running), color: running < 0 ? '#ef4444' : '#10b981', value: running, isTotal: true });
  return rows;
}

const WaterfallTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0]?.payload || {};
  const sign = value >= 0 ? '+' : '';
  const color = value < 0 ? '#ef4444' : '#10b981';
  return (
    <div style={{
      background: 'rgba(15,23,42,0.95)', border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: 8, padding: '8px 12px', fontSize: 11,
    }}>
      <div style={{ color: '#94a3b8', marginBottom: 3 }}>{name}</div>
      <div style={{ color, fontWeight: 800, fontSize: 14 }}>
        {sign}{value >= 1e6 ? `$${(Math.abs(value)/1e6).toFixed(2)}M` : value >= 1e3 ? `$${(Math.abs(value)/1e3).toFixed(0)}K` : `$${Math.abs(value).toFixed(0)}`}
        {value < 0 && value !== 0 && ' below target'}
      </div>
    </div>
  );
};

const WaterfallChart = ({ factors }) => {
  const chartData = buildWaterfallData(factors);
  return (
    <div style={{ height: 130, marginBottom: 8 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} barCategoryGap="20%">
          <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#64748b' }} axisLine={false} tickLine={false} />
          <YAxis hide />
          <Tooltip content={<WaterfallTooltip />} />
          {/* Transparent spacer bar (creates the "floating" effect) */}
          <Bar dataKey="base" stackId="wf" fill="transparent" isAnimationActive={false} />
          {/* Colored impact bar */}
          <Bar dataKey="bar" stackId="wf" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={entry.isTotal ? entry.color + 'cc' : entry.color + '99'} stroke={entry.color} strokeWidth={1} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

// ── ImpactBar — single KPI row ────────────────────────────────────────────────

const MAX_BAR_WIDTH = 120; // px

const ImpactBar = ({ name, value, maxAbs, isSubtotal = false }) => {
  const barWidth = maxAbs > 0 ? Math.round((Math.abs(value) / maxAbs) * MAX_BAR_WIDTH) : 4;
  const isNeg    = value < 0;
  const barColor = isNeg ? '#ef4444' : '#10b981';
  const prefix   = isSubtotal ? '=' : '►';
  const prefixColor = isSubtotal ? '#64748b' : '#475569';

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: isSubtotal ? '5px 0 5px 0' : '3px 0',
      borderTop: isSubtotal ? '1px solid rgba(255,255,255,0.07)' : 'none',
      marginTop: isSubtotal ? 2 : 0,
    }}>
      {/* Prefix symbol */}
      <span style={{ width: 10, fontSize: 10, color: prefixColor, flexShrink: 0, textAlign: 'center' }}>
        {prefix}
      </span>

      {/* KPI name */}
      <span style={{
        width: 110, fontSize: isSubtotal ? 11 : 10, color: isSubtotal ? '#cbd5e1' : '#94a3b8',
        fontWeight: isSubtotal ? 600 : 400, flexShrink: 0,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {name}
      </span>

      {/* Impact bar */}
      <div style={{
        width: MAX_BAR_WIDTH, height: isSubtotal ? 14 : 10,
        background: 'rgba(255,255,255,0.04)', borderRadius: 3, flexShrink: 0, position: 'relative',
      }}>
        <div style={{
          width: barWidth, height: '100%',
          background: barColor, opacity: isSubtotal ? 0.85 : 0.65,
          borderRadius: 3,
        }} />
      </div>

      {/* Dollar value */}
      <span style={{
        fontSize: isSubtotal ? 12 : 11, fontWeight: isSubtotal ? 700 : 500,
        color: isNeg ? '#ef4444' : '#10b981',
        minWidth: 80, textAlign: 'right',
      }}>
        {fmtDollar(value)}
      </span>
    </div>
  );
};

// ── FunnelPanel — one funnel section ─────────────────────────────────────────

const FunnelPanel = ({ title, equation, rows, subtotals, totalGap, maxAbs }) => (
  <div style={{
    flex: 1, minWidth: 0,
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 8, padding: '10px 12px',
  }}>
    {/* Funnel title */}
    <div style={{ fontSize: 11, fontWeight: 700, color: '#93c5fd', marginBottom: 2, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
      {title}
    </div>
    {/* Funnel equation */}
    <div style={{ fontSize: 9.5, color: '#475569', marginBottom: 10, lineHeight: 1.4 }}>
      {equation}
    </div>

    {/* KPI rows */}
    {rows.map(([name, val]) => (
      <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} />
    ))}

    {/* Subtotal rows (Won Opps, Pipeline) */}
    {subtotals?.map(([name, val]) => (
      <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} isSubtotal />
    ))}

    {/* Total gap — Won Amount */}
    <div style={{
      marginTop: 4,
      borderTop: '1px solid rgba(255,255,255,0.1)',
      paddingTop: 6,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: '#cbd5e1' }}>= Won Amount</span>
      <span style={{
        fontSize: 13, fontWeight: 800,
        color: totalGap < 0 ? '#ef4444' : '#10b981',
      }}>
        {fmtDollar(totalGap)}
      </span>
    </div>
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const ImpactWaterfall = ({ filters }) => {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (filters?.product && filters.product !== 'All') params.set('product', filters.product);
        if (filters?.geo     && filters.geo     !== 'All') params.set('geo',     filters.geo);
        if (filters?.channel && filters.channel !== 'All') params.set('channel', filters.channel);

        const res  = await fetch(`/api/insights/impact-decomposition?${params}`);
        const json = await res.json();
        if (cancelled) return;

        const decomp = json.decomposition?.[0];
        if (!decomp?.funnel_opp_volume || !decomp?.funnel_dollar) return;

        setData(decomp);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => { cancelled = true; };
  }, [filters]);

  if (loading || !data) return null;

  const totalGap = data.impact_dollars ?? 0;
  const ov       = data.funnel_opp_volume ?? {};
  const df       = data.funnel_dollar    ?? {};

  // Only render when there is a meaningful gap
  if (Math.abs(totalGap) < 1) return null;

  // Max absolute value across all impacts — used to normalise bar widths
  const allVals = [
    ov['Opened Opps']     ?? 0,
    ov['Close Rate (Vol)'] ?? 0,
    ov['Won Opps']        ?? 0,
    ov['ADS']             ?? 0,
    df['Avg Opp Size']    ?? 0,
    df['Pipeline ($)']    ?? 0,
    df['Close Rate ($)']  ?? 0,
    totalGap,
  ];
  const maxAbs = Math.max(...allVals.map(Math.abs), 1);

  // Opp Volume Funnel rows
  const ovInputs   = [
    ['Opened Opps',      ov['Opened Opps']      ?? 0],
    ['Close Rate (Vol)', ov['Close Rate (Vol)'] ?? 0],
  ];
  const ovSubtotal = [['Won Opps', ov['Won Opps'] ?? 0]];
  const ovADS      = [['ADS',      ov['ADS']      ?? 0]];

  // Dollar Funnel rows
  const dfInputs   = [['Avg Opp Size', df['Avg Opp Size'] ?? 0]];
  const dfSubtotal = [['Pipeline ($)',  df['Pipeline ($)'] ?? 0]];
  const dfCR       = [['Close Rate ($)', df['Close Rate ($)'] ?? 0]];

  // Build combined row lists for each funnel
  const ovRows      = [...ovInputs, ...ovADS];
  const ovSubtotals = ovSubtotal;
  const dfRows      = [...dfInputs, ...dfCR];
  const dfSubtotals = dfSubtotal;

  const below  = totalGap < 0;
  const headingColor = below ? '#ef4444' : '#10b981';

  return (
    <div className="glass-card" style={{ padding: '14px 16px', marginBottom: 16 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>💰</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>
              Revenue Gap Decomposition
            </div>
            <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>
              Two-funnel model · Dollarized impact per KPI
            </div>
          </div>
        </div>
        {/* Total gap badge */}
        <div style={{
          background: below ? 'rgba(239,68,68,0.12)' : 'rgba(16,185,129,0.12)',
          border: `1px solid ${below ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)'}`,
          borderRadius: 6, padding: '4px 10px',
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
        }}>
          <span style={{ fontSize: 9, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Won Amount Gap
          </span>
          <span style={{ fontSize: 14, fontWeight: 800, color: headingColor }}>
            {fmtDollarTotal(totalGap)}
          </span>
        </div>
      </div>

      {/* Column legend */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9.5, color: '#475569', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: '#10b981', display: 'inline-block' }} />
          Above target (tailwind)
        </span>
        <span style={{ fontSize: 9.5, color: '#475569', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: '#ef4444', display: 'inline-block' }} />
          Below target (drag)
        </span>
      </div>

      {/* ── Recharts waterfall chart ──────────────────────────────────── */}
      <WaterfallChart factors={[
        ['Won Volume',   ov['Opened Opps']      ?? 0],
        ['Close Rate',   ov['Close Rate (Vol)'] ?? 0],
        ['Avg Deal Size', ov['ADS']             ?? 0],
        ['Pipeline $',   df['Pipeline ($)']     ?? 0],
        ['CR($)',         df['Close Rate ($)']  ?? 0],
      ]} />

      {/* Two funnel panels side by side */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>

        {/* Opp Volume Funnel */}
        <div style={{
          flex: 1, minWidth: 260,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 8, padding: '10px 12px',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#93c5fd', marginBottom: 2, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Opp Volume Funnel
          </div>
          <div style={{ fontSize: 9.5, color: '#475569', marginBottom: 10, lineHeight: 1.5 }}>
            Opened Opps × CR(Vol) = Won Opps<br />
            Won Opps × ADS = Won Amount
          </div>

          {ovInputs.map(([name, val]) => (
            <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} />
          ))}
          {/* Won Opps subtotal */}
          {ovSubtotals.map(([name, val]) => (
            <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} isSubtotal />
          ))}
          {/* ADS input */}
          {ovADS.map(([name, val]) => (
            <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} />
          ))}
          {/* Won Amount total */}
          <div style={{
            marginTop: 4, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 6,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#cbd5e1' }}>= Won Amount</span>
            <span style={{ fontSize: 13, fontWeight: 800, color: headingColor }}>
              {fmtDollar(totalGap)}
            </span>
          </div>
        </div>

        {/* Dollar Funnel */}
        <div style={{
          flex: 1, minWidth: 260,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 8, padding: '10px 12px',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#a78bfa', marginBottom: 2, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Dollar Funnel
          </div>
          <div style={{ fontSize: 9.5, color: '#475569', marginBottom: 10, lineHeight: 1.5 }}>
            Opened Opps × Avg Opp Size = Pipeline<br />
            Pipeline × CR($) = Won Amount
          </div>

          {/* Avg Opp Size — driver of pipeline gap */}
          {dfInputs.map(([name, val]) => (
            <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} />
          ))}
          {/* Pipeline subtotal */}
          {dfSubtotals.map(([name, val]) => (
            <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} isSubtotal />
          ))}
          {/* Close Rate ($) input */}
          {dfCR.map(([name, val]) => (
            <ImpactBar key={name} name={name} value={val} maxAbs={maxAbs} />
          ))}
          {/* Won Amount total */}
          <div style={{
            marginTop: 4, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 6,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#cbd5e1' }}>= Won Amount</span>
            <span style={{ fontSize: 13, fontWeight: 800, color: headingColor }}>
              {fmtDollar(totalGap)}
            </span>
          </div>
        </div>

      </div>

      {/* Recommendation */}
      {data.recommendation && (
        <div style={{
          marginTop: 10, padding: '8px 10px',
          background: 'rgba(255,255,255,0.03)', borderRadius: 6,
          borderLeft: '3px solid #3b82f6',
          fontSize: 11, color: '#94a3b8', lineHeight: 1.5,
        }}>
          <span style={{ color: '#60a5fa', fontWeight: 600 }}>Recommendation: </span>
          {data.recommendation}
        </div>
      )}

    </div>
  );
};

export default ImpactWaterfall;
