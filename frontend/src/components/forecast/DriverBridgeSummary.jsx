const label = { fontSize: 11, color: '#94a3b8' };
const value = { color: '#f1f5f9', fontWeight: 700 };
const signColor = (v) => ((v || 0) >= 0 ? '#10b981' : '#ef4444');

const fmtPct = (v) => (v == null || Number.isNaN(Number(v)) ? '' : ` (${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%)`);

// Plan-vs-actual summary for /driver-bridge. Renders only what the API returned:
// a null total shows as an em dash and an unavailable response shows its reason.
export function DriverBridgeSummary({ bridge, fmt, maxComponents = 6 }) {
  if (!bridge) return null;
  const unavailable = bridge.source === 'unavailable';
  const comps = (bridge.components || []).slice(0, maxComponents);
  const denom = Math.max(1, Math.abs(bridge.variance || 1));
  return (
    <div>
      {bridge.quarter_label && (
        <div style={{ ...label, marginBottom: 6 }}>
          {bridge.quarter_label} · {bridge.product || 'Total'}
          {bridge.weeks_closed != null ? ` · ${bridge.weeks_closed} closed week${bridge.weeks_closed === 1 ? '' : 's'}` : ''}
        </div>
      )}
      {unavailable && bridge.reason && (
        <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 8 }}>{bridge.reason}</div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginBottom: 10 }}>
        <div style={label}>Plan (closed weeks): <span style={value}>{fmt(bridge.plan_total)}</span></div>
        <div style={label}>Actual: <span style={value}>{fmt(bridge.actual_total)}</span></div>
        <div style={label}>Variance: <span style={{ ...value, color: signColor(bridge.variance) }}>{fmt(bridge.variance)}{fmtPct(bridge.variance_pct)}</span></div>
        <div style={label}>Plan (full quarter): <span style={value}>{fmt(bridge.plan_total_quarter)}</span></div>
        <div style={label}>Outlook: <span style={value}>{fmt(bridge.outlook_total)}</span></div>
        <div style={label}>Outlook vs plan: <span style={{ ...value, color: signColor(bridge.outlook_vs_plan) }}>{fmt(bridge.outlook_vs_plan)}</span></div>
      </div>
      {comps.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {comps.map((c, i) => {
            const v = c.variance ?? c.value ?? 0;
            const widthPct = Math.min(100, Math.max(4, Math.abs(v) / denom * 100));
            return (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 180px', gap: 8, alignItems: 'center' }}>
                <div style={{ fontSize: 11, color: '#cbd5e1' }}>{c.name || c.driver || `Driver ${i + 1}`}</div>
                <div style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                  <div style={{ width: `${widthPct}%`, height: '100%', background: signColor(v) }} />
                </div>
                <div style={{ textAlign: 'right', fontSize: 11, color: signColor(v) }}>
                  {fmt(c.actual)} vs {fmt(c.plan)} ({fmt(v)})
                </div>
              </div>
            );
          })}
        </div>
      )}
      {bridge.basis && <div style={{ fontSize: 10, color: '#64748b', marginTop: 10, lineHeight: 1.5 }}>{bridge.basis}</div>}
    </div>
  );
}

// Reason + basis lines under the confidence score (shown even when unavailable).
export function ConfidenceNotes({ confidence }) {
  if (!confidence) return null;
  const unavailable = confidence.source === 'unavailable';
  return (
    <>
      {unavailable && confidence.reason && (
        <div style={{ fontSize: 11, color: '#f59e0b', marginTop: 6, lineHeight: 1.5 }}>{confidence.reason}</div>
      )}
      {confidence.basis && (
        <div style={{ fontSize: 10, color: '#64748b', marginTop: 8, lineHeight: 1.5 }}>{confidence.basis}</div>
      )}
    </>
  );
}
