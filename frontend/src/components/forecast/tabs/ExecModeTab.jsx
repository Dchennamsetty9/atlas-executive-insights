import { CardWrap, SectionTitle, fmtM } from '../common';

const ExecModeTab = ({
  confidenceBands,
  weeklyKpis,
  confidence,
  meetingMode,
  driverBridge,
  simWinRate,
  setSimWinRate,
  simCycle,
  setSimCycle,
  simDealSize,
  setSimDealSize,
  simCoverage,
  setSimCoverage,
  simulatedScenario,
  riskRadar,
  actionDraft,
  setActionDraft,
  submitAction,
  actions,
  markActionDone,
  decisionDraft,
  setDecisionDraft,
  submitDecisionLog,
  governanceLog,
}) => {
  const heroLikely = weeklyKpis?.most_likely ?? confidenceBands?.most_likely ?? 0;
  const p10Floor = confidenceBands?.p10 ?? weeklyKpis?.worst_case ?? 0;
  const topDrivers = [...(driverBridge?.components || [])]
    .sort((a, b) => Math.abs(Number(b.value || 0)) - Math.abs(Number(a.value || 0)))
    .slice(0, 3);
  const ownerActions = (actions || []).slice(0, 3);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <CardWrap>
        <SectionTitle>Executive Board Narrative</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
          <div style={{ padding: '12px 14px', borderRadius: 10, background: 'linear-gradient(135deg, rgba(59,130,246,0.18), rgba(59,130,246,0.04))', border: '1px solid rgba(59,130,246,0.32)' }}>
            <div style={{ fontSize: 9, color: '#93c5fd', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>Hero Number</div>
            <div style={{ fontSize: 26, fontWeight: 900, color: '#dbeafe', lineHeight: 1 }}>{fmtM(heroLikely)}</div>
            <div style={{ fontSize: 10, color: '#93c5fd', marginTop: 4 }}>Most likely quarter close</div>
          </div>
          <div style={{ padding: '12px 14px', borderRadius: 10, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.28)' }}>
            <div style={{ fontSize: 9, color: '#fca5a5', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>P10 Risk Floor</div>
            <div style={{ fontSize: 26, fontWeight: 900, color: '#ef4444', lineHeight: 1 }}>{fmtM(p10Floor)}</div>
            <div style={{ fontSize: 10, color: '#fca5a5', marginTop: 4 }}>Board downside protection number</div>
          </div>
        </div>
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
          <div style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '12px 14px', background: 'rgba(255,255,255,0.02)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#10b981', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Top 3 Drivers</div>
            {topDrivers.length === 0 && <div style={{ fontSize: 11, color: '#64748b' }}>No driver decomposition available.</div>}
            {topDrivers.map((d, i) => <div key={i} style={{ fontSize: 12, color: '#cbd5e1', marginBottom: 6 }}>{i + 1}. {d.name}: <span style={{ color: Number(d.value || 0) >= 0 ? '#10b981' : '#ef4444', fontWeight: 700 }}>{fmtM(d.value)}</span></div>)}
          </div>
          <div style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '12px 14px', background: 'rgba(255,255,255,0.02)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Top 3 Owner Actions</div>
            {ownerActions.length === 0 && <div style={{ fontSize: 11, color: '#64748b' }}>No pending actions logged.</div>}
            {ownerActions.map((a, i) => <div key={a.action_id || i} style={{ fontSize: 12, color: '#cbd5e1', marginBottom: 6 }}>{i + 1}. {a.text} <span style={{ color: '#93c5fd' }}>({a.owner || 'Unassigned'})</span></div>)}
          </div>
        </div>
      </CardWrap>

      <CardWrap>
        <SectionTitle>Prediction Interval Fan — Source Model P10 / P50 / P90</SectionTitle>
        {(() => {
          const cb = confidenceBands;
          const p10 = cb?.p10 ?? weeklyKpis?.worst_case ?? 0;
          const p50 = cb?.most_likely ?? weeklyKpis?.most_likely ?? 0;
          const p90 = cb?.p90 ?? weeklyKpis?.best_case ?? 0;
          const isDemo = cb?.source === 'demo' || !cb;
          const hasData = p50 > 0;
          const spread = p90 - p10;
          const maxVal = p90 * 1.08;
          const bar = (val, color, label, pct) => (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <div style={{ width: 96, fontSize: 10, color: '#64748b', textAlign: 'right', flexShrink: 0 }}>{label}</div>
              <div style={{ flex: 1, height: 24, background: 'rgba(255,255,255,0.04)', borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.4s ease' }} />
              </div>
              <div style={{ width: 72, fontSize: 12, fontWeight: 700, color, textAlign: 'right', flexShrink: 0 }}>{fmtM(val)}</div>
            </div>
          );
          return (
            <div>
              {isDemo && <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 10, padding: '6px 10px', background: 'rgba(245,158,11,0.08)', borderRadius: 6, border: '1px solid rgba(245,158,11,0.2)' }}>⚠ Demo — run Panel Writer to populate real P10/P90 columns</div>}
              {!hasData && <div style={{ fontSize: 11, color: '#64748b' }}>No confidence-band data for current selection.</div>}
              {hasData && (
                <div>
                  {bar(p10, '#ef4444', 'Risk Floor (P10)', maxVal > 0 ? (p10 / maxVal) * 100 : 0)}
                  {bar(p50, '#f1f5f9', 'Most Likely (P50)', maxVal > 0 ? (p50 / maxVal) * 100 : 0)}
                  {bar(p90, '#10b981', 'Stretch (P90)', maxVal > 0 ? (p90 / maxVal) * 100 : 0)}
                  <div style={{ display: 'flex', gap: 20, marginTop: 12, padding: '10px 14px', background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>Spread (P10→P90): <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtM(spread)}</span></div>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>Spread / P50: <span style={{ color: p50 > 0 ? (spread / p50 > 0.3 ? '#ef4444' : spread / p50 > 0.15 ? '#f59e0b' : '#10b981') : '#64748b', fontWeight: 700 }}>{p50 > 0 ? `${((spread / p50) * 100).toFixed(1)}%` : '—'}</span></div>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>Source: <span style={{ color: cb?.source === 'live' ? '#10b981' : '#f59e0b', fontWeight: 700 }}>{cb?.source === 'live' ? 'Live (model P10/P90)' : 'Demo'}</span></div>
                  </div>
                </div>
              )}
            </div>
          );
        })()}
      </CardWrap>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <CardWrap>
          <SectionTitle>Forecast Confidence Score</SectionTitle>
          <div style={{ fontSize: 30, fontWeight: 800, color: confidence?.confidence_score >= 85 ? '#10b981' : confidence?.confidence_score >= 65 ? '#f59e0b' : '#ef4444' }}>{confidence?.confidence_score ?? '—'}</div>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{confidence?.confidence_label || 'Unknown'} confidence</div>
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>{(confidence?.reasons || []).slice(0, 3).map((r, i) => <div key={i} style={{ fontSize: 11, color: '#cbd5e1', lineHeight: 1.5 }}>• {r}</div>)}</div>
        </CardWrap>

        <CardWrap>
          <SectionTitle>Meeting Snapshot</SectionTitle>
          <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>Top Moves This Quarter</div>
          {(meetingMode?.top_moves || []).slice(0, 3).map((m, i) => <div key={i} style={{ fontSize: 11, color: '#e2e8f0', marginBottom: 6, lineHeight: 1.5 }}>{i + 1}. {m}</div>)}
        </CardWrap>
      </div>

      <CardWrap>
        <SectionTitle>Driver Bridge (Plan vs Actual)
          <span style={{ fontSize: 9, color: '#f59e0b', fontWeight: 400, letterSpacing: 0, textTransform: 'none', marginLeft: 8 }}>— Illustrative breakdown; driver attribution requires source data</span>
        </SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>Plan: <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtM(driverBridge?.plan_total)}</span></div>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>Actual: <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtM(driverBridge?.actual_total)}</span></div>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>Variance: <span style={{ color: (driverBridge?.variance || 0) >= 0 ? '#10b981' : '#ef4444', fontWeight: 700 }}>{fmtM(driverBridge?.variance)}</span></div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {(driverBridge?.components || []).map((c, i) => {
            const positive = (c.value || 0) >= 0;
            const widthPct = Math.min(100, Math.max(4, Math.abs(c.value || 0) / Math.max(1, Math.abs(driverBridge?.variance || 1)) * 100));
            return (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 100px', gap: 8, alignItems: 'center' }}>
                <div style={{ fontSize: 11, color: '#cbd5e1' }}>{c.name}</div>
                <div style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}><div style={{ width: `${widthPct}%`, height: '100%', background: positive ? '#10b981' : '#ef4444' }} /></div>
                <div style={{ textAlign: 'right', fontSize: 11, color: positive ? '#10b981' : '#ef4444' }}>{fmtM(c.value)}</div>
              </div>
            );
          })}
        </div>
      </CardWrap>

      <CardWrap>
        <SectionTitle>Pipeline Sensitivity Simulator</SectionTitle>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10 }}>Adjusts pipeline conversion factors relative to baseline — not a direct ARR override. Use as directional sensitivity, not a forecast number.</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          <div><div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Win Rate %: {simWinRate.toFixed(1)}</div><input type="range" min="15" max="60" step="0.1" value={simWinRate} onChange={(e) => setSimWinRate(Number(e.target.value))} style={{ width: '100%' }} /></div>
          <div><div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Cycle Time Days: {simCycle}</div><input type="range" min="20" max="120" step="1" value={simCycle} onChange={(e) => setSimCycle(Number(e.target.value))} style={{ width: '100%' }} /></div>
          <div><div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Avg Deal Size Multiplier: {simDealSize.toFixed(2)}x</div><input type="range" min="0.7" max="1.4" step="0.01" value={simDealSize} onChange={(e) => setSimDealSize(Number(e.target.value))} style={{ width: '100%' }} /></div>
          <div><div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Coverage: {simCoverage.toFixed(1)}x</div><input type="range" min="1.5" max="5" step="0.1" value={simCoverage} onChange={(e) => setSimCoverage(Number(e.target.value))} style={{ width: '100%' }} /></div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(120px, 1fr))', gap: 10, marginTop: 12 }}>
          <div style={{ padding: '10px', borderRadius: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}><div style={{ fontSize: 10, color: '#ef4444', marginBottom: 3 }}>Worst</div><div style={{ fontSize: 17, fontWeight: 700, color: '#ef4444' }}>{fmtM(simulatedScenario.worst)}</div></div>
          <div style={{ padding: '10px', borderRadius: 8, background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}><div style={{ fontSize: 10, color: '#3b82f6', marginBottom: 3 }}>Base</div><div style={{ fontSize: 17, fontWeight: 700, color: '#93c5fd' }}>{fmtM(simulatedScenario.base)}</div></div>
          <div style={{ padding: '10px', borderRadius: 8, background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}><div style={{ fontSize: 10, color: '#10b981', marginBottom: 3 }}>Best</div><div style={{ fontSize: 17, fontWeight: 700, color: '#10b981' }}>{fmtM(simulatedScenario.best)}</div></div>
        </div>
      </CardWrap>

      <CardWrap>
        <SectionTitle>At-Risk ARR Radar (Top 20)</SectionTitle>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>{['Product', 'Geo', 'Likely', 'Worst', 'Risk Impact', 'Spread %', 'Risk Level'].map((h) => <th key={h} style={{ padding: '6px 10px', textAlign: ['Product', 'Geo', 'Risk Level'].includes(h) ? 'left' : 'right', fontSize: 10, color: '#64748b' }}>{h}</th>)}</tr></thead>
            <tbody>{(riskRadar || []).slice(0, 20).map((r, i) => <tr key={`${r.product}-${r.sales_market}-${i}`} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}><td style={{ padding: '6px 10px', fontSize: 11, color: '#f1f5f9' }}>{r.product}</td><td style={{ padding: '6px 10px', fontSize: 11, color: '#94a3b8' }}>{r.sales_market}</td><td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#e2e8f0' }}>{fmtM(r.likely)}</td><td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#f87171' }}>{fmtM(r.worst)}</td><td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#ef4444', fontWeight: 700 }}>{fmtM(r.risk_dollar_impact)}</td><td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 11, color: '#94a3b8' }}>{r.confidence_spread_pct != null ? `${Number(r.confidence_spread_pct).toFixed(1)}%` : '—'}</td><td style={{ padding: '6px 10px', fontSize: 10, color: r.risk_level === 'high' ? '#ef4444' : r.risk_level === 'moderate' ? '#f59e0b' : '#10b981' }}>{String(r.risk_level || '').toUpperCase()}</td></tr>)}</tbody>
          </table>
        </div>
      </CardWrap>

      <CardWrap>
        <SectionTitle>Action Command Center</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: 8, marginBottom: 10 }}>
          <input value={actionDraft.text} onChange={(e) => setActionDraft((d) => ({ ...d, text: e.target.value }))} placeholder="Action item" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <input value={actionDraft.owner} onChange={(e) => setActionDraft((d) => ({ ...d, owner: e.target.value }))} placeholder="Owner" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <input type="date" value={actionDraft.due_date} onChange={(e) => setActionDraft((d) => ({ ...d, due_date: e.target.value }))} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <select value={actionDraft.priority} onChange={(e) => setActionDraft((d) => ({ ...d, priority: e.target.value }))} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }}><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
          <button onClick={submitAction} style={{ background: 'rgba(59,130,246,0.16)', border: '1px solid rgba(59,130,246,0.35)', color: '#93c5fd', borderRadius: 6, padding: '6px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>Add</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {(actions || []).slice(0, 12).map((a) => <div key={a.action_id} style={{ display: 'grid', gridTemplateColumns: '1fr 110px 100px 72px', gap: 8, alignItems: 'center', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8, padding: '8px 10px' }}><div style={{ fontSize: 11, color: '#e2e8f0' }}>{a.text}</div><div style={{ fontSize: 10, color: '#94a3b8' }}>{a.owner || 'Unassigned'}</div><div style={{ fontSize: 10, color: '#f59e0b' }}>{a.due_date || 'No due date'}</div><button onClick={() => markActionDone(a.action_id)} style={{ background: 'rgba(16,185,129,0.14)', border: '1px solid rgba(16,185,129,0.35)', color: '#10b981', borderRadius: 6, padding: '5px 8px', fontSize: 10, fontWeight: 700, cursor: 'pointer' }}>Done</button></div>)}
          {(!actions || actions.length === 0) && <div style={{ fontSize: 11, color: '#64748b' }}>No pending actions. Add one above.</div>}
        </div>
      </CardWrap>

      <CardWrap>
        <SectionTitle>Forecast Governance and Audit Trail</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 2fr auto', gap: 8, marginBottom: 10 }}>
          <input value={decisionDraft.decision} onChange={(e) => setDecisionDraft((d) => ({ ...d, decision: e.target.value }))} placeholder="Decision / override" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <input value={decisionDraft.owner} onChange={(e) => setDecisionDraft((d) => ({ ...d, owner: e.target.value }))} placeholder="Owner" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <input type="number" value={decisionDraft.expected_impact} onChange={(e) => setDecisionDraft((d) => ({ ...d, expected_impact: e.target.value }))} placeholder="Expected impact" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <input value={decisionDraft.reason} onChange={(e) => setDecisionDraft((d) => ({ ...d, reason: e.target.value }))} placeholder="Reason" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', borderRadius: 6, padding: '6px 8px', fontSize: 11 }} />
          <button onClick={submitDecisionLog} style={{ background: 'rgba(168,85,247,0.16)', border: '1px solid rgba(168,85,247,0.35)', color: '#c4b5fd', borderRadius: 6, padding: '6px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>Log</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {(governanceLog || []).slice(0, 12).map((g) => <div key={g.id} style={{ border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8, padding: '8px 10px' }}><div style={{ fontSize: 11, color: '#f1f5f9', marginBottom: 3 }}>{g.decision}</div><div style={{ fontSize: 10, color: '#94a3b8' }}>{g.owner || 'Unknown owner'} · {g.created_at ? String(g.created_at).slice(0, 10) : '—'} · Impact {g.expected_impact != null ? fmtM(g.expected_impact) : '—'}</div>{g.reason && <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>{g.reason}</div>}</div>)}
          {(!governanceLog || governanceLog.length === 0) && <div style={{ fontSize: 11, color: '#64748b' }}>No governance entries yet.</div>}
        </div>
      </CardWrap>
    </div>
  );
};

export default ExecModeTab;
