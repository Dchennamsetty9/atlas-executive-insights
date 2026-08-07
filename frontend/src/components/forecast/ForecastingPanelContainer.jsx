import { Component, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiService } from '../../services/api';
import { FC_TYPES, MODELS, MODEL_LB_KEY, MODEL_KEY_META, PROD_LINES, TABS } from './constants';
import { buildDemoByProduct, buildDemoHistorical, buildDemoLeaderboard, buildDemoMonthly, buildDemoWeekly, buildDemoYtd } from './demoData';
import { Skeleton, formatModelLabel, fmtDate, fmtM, mapeColor, calculateStaleness } from './common';

const OverviewTab = lazy(() => import('./tabs/OverviewTab'));
const MultiYearTab = lazy(() => import('./tabs/MultiYearTab'));
const ByProductTab = lazy(() => import('./tabs/ByProductTab'));
const MonthlyTab = lazy(() => import('./tabs/MonthlyTab'));
const AccuracyTab = lazy(() => import('./tabs/AccuracyTab'));
const ModelLabTab = lazy(() => import('./tabs/ModelLabTab'));
const AiInsightsTab = lazy(() => import('./tabs/AiInsightsTab'));
const ExecModeTab = lazy(() => import('./tabs/ExecModeTab'));

class TabErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { hasError: false }; }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(err) { console.error('[ForecastingPanel] tab error:', err); }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: '#ef4444' }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>⚠</div>
        <p style={{ fontSize: 14, margin: 0 }}>This tab encountered a rendering error.</p>
        <button onClick={() => this.setState({ hasError: false })} style={{ marginTop: 12, padding: '6px 20px', borderRadius: 8, cursor: 'pointer', background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)', fontSize: 12 }}>Retry</button>
      </div>
    );
  }
}

const ForecastingPanelContainer = () => {
  const [tab, setTab] = useState('Overview');
  const [model, setModel] = useState('ensemble');
  const [fcType, setFcType] = useState('rolling');
  const [prodLine, setProdLine] = useState('All');
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [selectedQuarter, setSelectedQuarter] = useState(null);
  const [multiYearView, setMultiYearView] = useState('overlay');
  const [modelsOpen, setModelsOpen] = useState(false);
  const [salesMarket, setSalesMarket] = useState('All');

  const [weekly, setWeekly] = useState(null);
  const [weeklyKpis, setWeeklyKpis] = useState(null);
  const [ytd, setYtd] = useState(null);
  const [historical, setHistorical] = useState(null);
  const [byProduct, setByProduct] = useState(null);
  const [monthly, setMonthly] = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [modelRegistry, setModelRegistry] = useState([]);
  const [freshness, setFreshness] = useState(null);
  const [confidence, setConfidence] = useState(null);
  const [driverBridge, setDriverBridge] = useState(null);
  const [riskRadar, setRiskRadar] = useState([]);
  const [meetingMode, setMeetingMode] = useState(null);
  const [confidenceBands, setConfidenceBands] = useState(null);
  const [trust, setTrust] = useState(null);
  const [runDelta, setRunDelta] = useState(null);
  const [actions, setActions] = useState([]);
  const [governanceLog, setGovernanceLog] = useState([]);
  const [actionDraft, setActionDraft] = useState({ text: '', owner: '', due_date: '', playbook_action: '', priority: 'medium' });
  const [decisionDraft, setDecisionDraft] = useState({ decision: '', owner: '', expected_impact: '', reason: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [source, setSource] = useState(null);

  const loadedTabsRef = useRef(new Set());
  const tabLoadInFlightRef = useRef(new Set());
  const hasHydratedFiltersRef = useRef(false);

  const [simWinRate, setSimWinRate] = useState(31.8);
  const [simCycle, setSimCycle] = useState(45);
  const [simDealSize, setSimDealSize] = useState(1.0);
  const [simCoverage, setSimCoverage] = useState(3.2);

  const activePl = prodLine !== 'All' ? prodLine : null;
  const activeGeo = salesMarket !== 'All' ? salesMarket : null;

  const fetchOverviewData = useCallback(async () => {
    const [wk, yt, modelsRes, fr, cb, rd] = await Promise.allSettled([
      apiService.getForecastV2Weekly(model, fcType, null, activePl, activeGeo, selectedYear, selectedQuarter),
      apiService.getForecastV2YTD(fcType, null, activePl, activeGeo, selectedYear, selectedQuarter, model),
      apiService.getForecastV2Models(),
      apiService.getForecastV2Freshness(),
      apiService.getForecastV2ConfidenceBands(fcType, activePl, selectedYear, selectedQuarter, model),
      apiService.getForecastV2RunDelta(activePl, activeGeo),
    ]);

    if (wk.status === 'fulfilled') {
      setWeekly(wk.value?.rows ?? []);
      setWeeklyKpis(wk.value?.kpis ?? null);
      setSource(wk.value?.source ?? null);
      if ((wk.value?.source ?? null) === 'demo' && wk.value?.error) setError(`Forecast data fallback: ${wk.value.error}`);
    }
    if (yt.status === 'fulfilled') setYtd(yt.value?.rows ?? []);
    if (modelsRes.status === 'fulfilled') setModelRegistry(modelsRes.value?.models ?? []);
    if (fr.status === 'fulfilled') setFreshness(fr.value ?? null);
    if (cb.status === 'fulfilled') setConfidenceBands(cb.value ?? null);
    if (rd.status === 'fulfilled') setRunDelta(rd.value ?? null);

    const firstReject = [wk, yt].find((r) => r.status === 'rejected');
    if (firstReject) {
      setSource('demo');
      setError(firstReject.reason?.message || 'Some endpoints failed to load');
    }
  }, [model, fcType, activePl, activeGeo, selectedYear, selectedQuarter]);

  const fetchTabData = useCallback(async (targetTab, { force = false } = {}) => {
    if (tabLoadInFlightRef.current.has(targetTab)) return;
    if (!force && loadedTabsRef.current.has(targetTab)) return;

    tabLoadInFlightRef.current.add(targetTab);
    setLoading(true);
    setError(null);
    try {
      if (targetTab === 'Overview') {
        await fetchOverviewData();
      } else if (targetTab === 'Multi-Year') {
        const [hs] = await Promise.allSettled([apiService.getForecastV2Historical(null, activePl, activeGeo)]);
        if (hs.status === 'fulfilled') setHistorical(hs.value?.rows ?? []);
      } else if (targetTab === 'By Product') {
        const [bp] = await Promise.allSettled([apiService.getForecastV2ByProduct(model, fcType, null, activePl, activeGeo, selectedYear, selectedQuarter)]);
        if (bp.status === 'fulfilled') setByProduct(bp.value ?? null);
      } else if (targetTab === 'Monthly') {
        const [mo] = await Promise.allSettled([apiService.getForecastV2Monthly(fcType, null, activePl, activeGeo, selectedYear, selectedQuarter, model)]);
        if (mo.status === 'fulfilled') setMonthly(mo.value?.months ?? []);
      } else if (targetTab === 'Accuracy') {
        const [lb, bt] = await Promise.allSettled([apiService.getForecastV2Leaderboard(), apiService.getForecastV2Backtest(4, model, activePl, activeGeo)]);
        if (lb.status === 'fulfilled') setLeaderboard(lb.value?.data ?? []);
        if (bt.status === 'fulfilled') setTrust(bt.value ?? null);
      } else if (targetTab === 'Exec Mode') {
        const [conf, bridge, radar, meeting, act, gov, rd] = await Promise.allSettled([
          apiService.getForecastV2Confidence(model, selectedYear, selectedQuarter),
          apiService.getForecastV2DriverBridge(selectedYear, selectedQuarter, model),
          apiService.getForecastV2RiskRadar(fcType, selectedYear, selectedQuarter, 20, model),
          apiService.getForecastV2MeetingMode(model, selectedYear, selectedQuarter),
          apiService.getActions('pending'),
          apiService.getForecastV2GovernanceLog(),
          apiService.getForecastV2RunDelta(activePl, activeGeo),
        ]);
        if (conf.status === 'fulfilled') setConfidence(conf.value ?? null);
        if (bridge.status === 'fulfilled') setDriverBridge(bridge.value ?? null);
        if (radar.status === 'fulfilled') setRiskRadar(radar.value?.items ?? []);
        if (meeting.status === 'fulfilled') setMeetingMode(meeting.value ?? null);
        if (act.status === 'fulfilled') setActions(act.value?.data ?? []);
        if (gov.status === 'fulfilled') setGovernanceLog(gov.value?.data ?? []);
        if (rd.status === 'fulfilled') setRunDelta(rd.value ?? null);
      }

      loadedTabsRef.current.add(targetTab);
    } catch (e) {
      setError(e.message);
    } finally {
      tabLoadInFlightRef.current.delete(targetTab);
      setLoading(false);
    }
  }, [model, fcType, activePl, activeGeo, selectedYear, selectedQuarter, fetchOverviewData]);

  useEffect(() => { fetchTabData(tab); }, [tab, fetchTabData]);

  useEffect(() => {
    if (!hasHydratedFiltersRef.current) { hasHydratedFiltersRef.current = true; return; }
    loadedTabsRef.current = new Set();
    const timer = setTimeout(() => { fetchTabData(tab, { force: true }); }, 280);
    return () => clearTimeout(timer);
  }, [model, fcType, activePl, activeGeo, selectedYear, selectedQuarter, fetchTabData, tab]);

  const refreshCurrentTab = useCallback(() => { fetchTabData(tab, { force: true }); }, [tab, fetchTabData]);

  const activeModelMeta = useMemo(() => (modelRegistry || []).find((entry) => entry.key === model) || null, [modelRegistry, model]);
  const activeModelDisplay = activeModelMeta?.display_name || (model.charAt(0).toUpperCase() + model.slice(1));
  const activeModelFreshness = activeModelMeta?.freshness || activeModelMeta?.latest_refresh || null;
  const freshnessStamp = freshness?.freshness || activeModelFreshness || null;
  const freshnessState = source === 'live' ? 'live' : source === 'demo' ? 'demo' : 'awaiting';

  const pill = (active, color) => ({
    padding: '4px 11px', borderRadius: 999, fontSize: 10, fontWeight: 700,
    cursor: 'pointer', transition: 'all 0.15s ease', display: 'flex', alignItems: 'center', gap: 5,
    border: `1px solid ${active ? (color ?? 'rgba(255,255,255,0.4)') : 'rgba(255,255,255,0.08)'}`,
    background: active ? `${(color ?? '#ffffff')}1a` : 'rgba(255,255,255,0.03)',
    color: active ? (color ?? '#f1f5f9') : '#475569',
  });

  const isDemo = source !== 'live';
  const demoPayload = useMemo(() => {
    const dWeekly = buildDemoWeekly(fcType);
    return {
      weekly: dWeekly,
      ytd: buildDemoYtd(dWeekly),
      monthly: buildDemoMonthly(),
      historical: buildDemoHistorical(),
      byProduct: buildDemoByProduct(),
      leaderboard: buildDemoLeaderboard(),
    };
  }, [fcType]);

  const weeklyView = (weekly && weekly.length > 0) ? weekly : (isDemo ? demoPayload.weekly : []);
  const ytdView = (ytd && ytd.length > 0) ? ytd : (isDemo ? demoPayload.ytd : []);
  const monthlyView = (monthly && monthly.length > 0) ? monthly : (isDemo ? demoPayload.monthly : []);
  const historicalView = (historical && historical.length > 0) ? historical : (isDemo ? demoPayload.historical : []);
  const byProductView = (byProduct && byProduct.by_product?.length > 0) ? byProduct : (isDemo ? demoPayload.byProduct : null);
  const leaderboardView = (leaderboard && leaderboard.length > 0) ? leaderboard : demoPayload.leaderboard;

  const graphInsights = useMemo(() => {
    const insight = { weekly: null, ytd: null, seasonality: null, trend: null, byProduct: null, monthly: null, accuracy: null };
    const actuals = (weeklyView || []).filter((r) => r.arr_actual != null);
    const forecast = (weeklyView || []).filter((r) => r.arr_likely != null);
    if (actuals.length && forecast.length) {
      const first = Number(actuals[0].arr_actual || 0);
      const last = Number(actuals[actuals.length - 1].arr_actual || 0);
      const trendPct = first > 0 ? ((last - first) / first) * 100 : 0;
      const avgBandPct = forecast.length ? forecast.reduce((s, r) => {
        const likely = Number(r.arr_likely || 0);
        const spread = Number(r.arr_best || 0) - Number(r.arr_worst || 0);
        return s + (likely > 0 ? (spread / likely) * 100 : 0);
      }, 0) / forecast.length : 0;
      const quarterText = selectedQuarter ? `Q${selectedQuarter}` : 'all quarters';
      insight.weekly = `Actuals trend ${trendPct >= 0 ? 'up' : 'down'} ${Math.abs(trendPct).toFixed(1)}% through ${quarterText} ${selectedYear}. Most-likely forecast sits inside an average confidence band of ${Math.max(0, avgBandPct).toFixed(1)}%.`;
    }
    const ytdRows = (ytdView || []).filter((r) => r.ytd_actual != null || r.ytd_likely != null);
    if (ytdRows.length) {
      const lastActual = [...ytdRows].reverse().find((r) => r.ytd_actual != null)?.ytd_actual ?? null;
      const lastLikely = [...ytdRows].reverse().find((r) => r.ytd_likely != null)?.ytd_likely ?? null;
      const gap = (lastLikely != null && lastActual != null) ? Number(lastLikely) - Number(lastActual) : null;
      insight.ytd = gap == null ? `YTD curve is tracking with current selection (${selectedYear}${selectedQuarter ? `, Q${selectedQuarter}` : ''}).` : `YTD actual is ${fmtM(lastActual)} versus likely path ${fmtM(lastLikely)}, a ${gap >= 0 ? 'remaining upside' : 'shortfall'} of ${fmtM(Math.abs(gap))}.`;
    }
    const lines = byProductView?.by_product_line || byProductView?.by_product || [];
    if (lines.length) {
      const sorted = [...lines].sort((a, b) => Number(b.arr_likely || 0) - Number(a.arr_likely || 0));
      const lead = sorted[0];
      const second = sorted[1];
      const gap = second ? Number(lead.arr_likely || 0) - Number(second.arr_likely || 0) : null;
      insight.byProduct = gap == null ? `${lead.product_line || lead.product} is the primary contributor in the current forecast mix.` : `${lead.product_line || lead.product} leads forecast mix at ${fmtM(lead.arr_likely)}, ahead of ${second.product_line || second.product} by ${fmtM(Math.abs(gap))}.`;
    }
    const monthRows = monthlyView || [];
    if (monthRows.length) {
      const totalLikely = monthRows.reduce((s, m) => s + Number(m.arr_likely || 0), 0);
      const totalActual = monthRows.reduce((s, m) => s + Number(m.arr_actual || 0), 0);
      const openMonths = monthRows.filter((m) => !m.arr_actual).length;
      insight.monthly = `Monthly view shows ${fmtM(totalActual)} realized and ${fmtM(totalLikely)} likely for ${selectedYear}${selectedQuarter ? ` Q${selectedQuarter}` : ''}, with ${openMonths} month(s) still forecast-driven.`;
    }
    const totalRow = (leaderboardView || []).find((r) => (r.product === 'Total' || r.product === 'All') && (r.sales_market === 'Total' || r.sales_market === 'All'));
    if (totalRow) {
      const models = [
        { name: 'ETS', val: Number(totalRow.ETS || Infinity) },
        { name: 'Prophet', val: Number(totalRow.Prophet || Infinity) },
        { name: 'LightGBM', val: Number(totalRow.LightGBM || Infinity) },
        { name: 'MSTL_v2', val: Number(totalRow.MSTL_v2 || Infinity) },
        { name: 'DHR_ARIMA', val: Number(totalRow.DHR_ARIMA || Infinity) },
      ].filter((m) => Number.isFinite(m.val) && m.val < 999);
      const best = [...models].sort((a, b) => a.val - b.val)[0];
      if (best) insight.accuracy = `${formatModelLabel(best.name)} is currently the most accurate model at ${best.val.toFixed(1)}% MAPE on the total slice; use it as the tie-breaker when scenario ranges are wide.`;
    }
    return insight;
  }, [weeklyView, ytdView, byProductView, monthlyView, leaderboardView, selectedYear, selectedQuarter]);

  const modelMapes = useMemo(() => {
    const totalRow = (leaderboardView || []).find((r) => (r.product === 'Total' || r.product === 'All') && (r.sales_market === 'Total' || r.sales_market === 'All'));
    return totalRow ? { ETS: totalRow.ETS, Prophet: totalRow.Prophet, LightGBM: totalRow.LightGBM, MSTL_v2: totalRow.MSTL_v2, DHR_ARIMA: totalRow.DHR_ARIMA, Ensemble: totalRow.Ensemble } : {};
  }, [leaderboardView]);

  const isEmpty = !loading && weeklyView !== null && weeklyView.length === 0;
  const simulatedScenario = useMemo(() => {
    const baseLikely = (weeklyView || []).filter((r) => r.arr_likely != null).reduce((s, r) => s + Number(r.arr_likely || 0), 0);
    if (!baseLikely) return { base: 0, worst: 0, best: 0 };
    const multiplier = (simWinRate / 31.8) * (45 / Math.max(20, simCycle)) * simDealSize * (simCoverage / 3.2);
    const base = baseLikely * multiplier;
    return { base, worst: base * 0.92, best: base * 1.08 };
  }, [weeklyView, simWinRate, simCycle, simDealSize, simCoverage]);

  const refreshActionData = useCallback(async () => {
    try {
      const [act, gov] = await Promise.allSettled([apiService.getActions('pending'), apiService.getForecastV2GovernanceLog()]);
      if (act.status === 'fulfilled') setActions(act.value?.data ?? []);
      if (gov.status === 'fulfilled') setGovernanceLog(gov.value?.data ?? []);
    } catch (_e) {}
  }, []);

  const submitAction = useCallback(async () => {
    if (!actionDraft.text?.trim()) return;
    try {
      await apiService.createAction({ text: actionDraft.text.trim(), owner: actionDraft.owner || null, priority: actionDraft.priority || 'medium', source: 'forecast', due_date: actionDraft.due_date || null, playbook_action: actionDraft.playbook_action || null });
      setActionDraft({ text: '', owner: '', due_date: '', playbook_action: '', priority: 'medium' });
      refreshActionData();
    } catch (_e) { setError('Unable to create action. Please verify authentication context.'); }
  }, [actionDraft, refreshActionData]);

  const markActionDone = useCallback(async (actionId) => {
    try { await apiService.updateActionStatus(actionId, 'done'); refreshActionData(); } catch (_e) { setError('Unable to update action status.'); }
  }, [refreshActionData]);

  const submitDecisionLog = useCallback(async () => {
    if (!decisionDraft.decision?.trim()) return;
    try {
      await apiService.createForecastV2GovernanceLog({ decision: decisionDraft.decision.trim(), owner: decisionDraft.owner || null, expected_impact: decisionDraft.expected_impact ? Number(decisionDraft.expected_impact) : null, reason: decisionDraft.reason || null, scenario_name: `${selectedYear}${selectedQuarter ? `-Q${selectedQuarter}` : '-All'}` });
      setDecisionDraft({ decision: '', owner: '', expected_impact: '', reason: '' });
      refreshActionData();
    } catch (_e) { setError('Unable to write governance log. Please verify authentication context.'); }
  }, [decisionDraft, refreshActionData, selectedQuarter, selectedYear]);

  const renderTab = () => {
    switch (tab) {
      case 'Overview': return <OverviewTab loading={loading} weeklyView={weeklyView} ytdView={ytdView} weeklyKpis={weeklyKpis} selectedYear={selectedYear} selectedQuarter={selectedQuarter} runDelta={runDelta} trust={trust} isDemo={isDemo} graphInsights={graphInsights} runDate={freshnessStamp} />;
      case 'Multi-Year': return <MultiYearTab loading={loading} historicalView={historicalView} graphInsights={graphInsights} multiYearView={multiYearView} setMultiYearView={setMultiYearView} pill={pill} runDate={freshnessStamp} />;
      case 'By Product': return <ByProductTab loading={loading} byProductView={byProductView} graphInsights={graphInsights} runDate={freshnessStamp} />;
      case 'Monthly': return <MonthlyTab loading={loading} monthlyView={monthlyView} graphInsights={graphInsights} runDate={freshnessStamp} />;
      case 'Accuracy': return <AccuracyTab loading={loading} leaderboardView={leaderboardView} graphInsights={graphInsights} model={model} prodLine={prodLine} salesMarket={salesMarket} runDate={freshnessStamp} />;
      case 'Model Lab': return <ModelLabTab prodLine={prodLine} salesMarket={salesMarket} />;
      case 'AI Insights': return <AiInsightsTab />;
      case 'Exec Mode': return <ExecModeTab confidenceBands={confidenceBands} weeklyKpis={weeklyKpis} confidence={confidence} meetingMode={meetingMode} driverBridge={driverBridge} simWinRate={simWinRate} setSimWinRate={setSimWinRate} simCycle={simCycle} setSimCycle={setSimCycle} simDealSize={simDealSize} setSimDealSize={setSimDealSize} simCoverage={simCoverage} setSimCoverage={setSimCoverage} simulatedScenario={simulatedScenario} riskRadar={riskRadar} actionDraft={actionDraft} setActionDraft={setActionDraft} submitAction={submitAction} actions={actions} markActionDone={markActionDone} decisionDraft={decisionDraft} setDecisionDraft={setDecisionDraft} submitDecisionLog={submitDecisionLog} governanceLog={governanceLog} runDate={freshnessStamp} />;
      default: return null;
    }
  };

  return (
    <div style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary, #f1f5f9)', letterSpacing: -0.5 }}>ARR Forecast</span>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.05em', padding: '2px 8px', borderRadius: 20, color: source === 'live' ? '#10b981' : source === 'demo' ? '#f59e0b' : '#475569', background: source === 'live' ? 'rgba(16,185,129,0.1)' : source === 'demo' ? 'rgba(245,158,11,0.08)' : 'rgba(255,255,255,0.04)', border: source === 'live' ? '1px solid rgba(16,185,129,0.3)' : source === 'demo' ? '1px solid rgba(245,158,11,0.2)' : '1px solid rgba(255,255,255,0.08)' }}>{source === 'live' ? 'LIVE' : source === 'demo' ? 'DEMO' : '—'}</span>
            <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>{freshnessStamp ? `as of ${freshnessStamp}` : 'as of awaiting refresh metadata'}</span>
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 3 }}>{activeModelDisplay} · Growth ARR</div>
        </div>
        <button onClick={refreshCurrentTab} disabled={loading} style={{ padding: '5px 14px', borderRadius: 8, fontSize: 11, fontWeight: 600, background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.25)', color: '#3b82f6', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.5 : 1 }}>{loading ? '⟳ Loading…' : '⟳ Refresh'}</button>
      </div>

      {(() => {
        const staleness = freshnessStamp ? calculateStaleness(freshnessStamp) : null;
        const isStale = staleness?.isStale;
        return (
          <>
            <div style={{ padding: '8px 12px', marginBottom: 10, borderRadius: 8, background: freshnessState === 'live' ? 'rgba(16,185,129,0.08)' : freshnessState === 'demo' ? 'rgba(245,158,11,0.08)' : 'rgba(148,163,184,0.08)', border: freshnessState === 'live' ? '1px solid rgba(16,185,129,0.22)' : freshnessState === 'demo' ? '1px solid rgba(245,158,11,0.28)' : '1px solid rgba(148,163,184,0.22)', color: freshnessState === 'live' ? '#a7f3d0' : freshnessState === 'demo' ? '#fde68a' : '#cbd5e1', fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <span>Data freshness: <b style={{ color: freshnessState === 'live' ? '#d1fae5' : freshnessState === 'demo' ? '#fef3c7' : '#e2e8f0' }}>{freshnessStamp || 'awaiting refresh metadata'}</b> {staleness && <span style={{ fontSize: 10, opacity: 0.8 }}>({staleness.value} {staleness.unit}{staleness.plural} old)</span>}</span>
              <span style={{ color: freshnessState === 'live' ? '#6ee7b7' : freshnessState === 'demo' ? '#fcd34d' : '#94a3b8' }}>{freshnessState === 'live' ? 'Shared live snapshot applied across all tabs' : freshnessState === 'demo' ? 'Demo fallback snapshot applied across all tabs' : 'Awaiting live snapshot metadata across all tabs'}</span>
            </div>
            {isStale && freshnessState === 'live' && (
              <div style={{ padding: '10px 12px', marginBottom: 10, borderRadius: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', color: '#fca5a5', fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ fontSize: 14 }}>⚠️</span><span><b>Data is stale.</b> Forecast last ran {staleness?.value} {staleness?.unit}{staleness?.plural} ago. Expected weekly update: Monday 03:00 UTC</span></span>
                <button onClick={refreshCurrentTab} disabled={loading} style={{ padding: '4px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'rgba(239,68,68,0.2)', border: '1px solid rgba(239,68,68,0.4)', color: '#fca5a5', cursor: loading ? 'default' : 'pointer', whiteSpace: 'nowrap' }}>{loading ? 'Refreshing…' : 'Refresh now'}</button>
              </div>
            )}
          </>
        );
      })()}

      <div style={{ padding: '10px 14px', marginBottom: 10, borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <div><div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>PRODUCT</div><div style={{ display: 'flex', gap: 4 }}>{PROD_LINES.map((pl) => <button key={pl} onClick={() => setProdLine(pl)} style={pill(prodLine === pl, pl === 'UCC' ? '#3b82f6' : pl === 'ITSG' ? '#10b981' : null)}>{pl}</button>)}</div></div>
        <div style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />
        <div><div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>REGION</div><select value={salesMarket} onChange={(e) => setSalesMarket(e.target.value)} style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: '#f1f5f9', fontSize: 11, cursor: 'pointer' }}><option value="All">All Regions</option><option value="NA">NA</option><option value="EMEA">EMEA</option><option value="APAC">APAC</option><option value="LATAM">LATAM</option></select></div>
        <div style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />
        <div><div style={{ fontSize: 8, color: '#475569', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 4 }}>TIME PERIOD</div><div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>{FC_TYPES.map((f) => <button key={f.key} onClick={() => setFcType(f.key)} style={pill(fcType === f.key, '#3b82f6')}>{f.label}</button>)}<select value={selectedYear} onChange={(e) => setSelectedYear(Number(e.target.value))} style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: '#f1f5f9', fontSize: 11, cursor: 'pointer' }}>{[2026, 2025, 2024, 2023].map((yr) => <option key={yr} value={yr}>{yr}</option>)}</select><select value={selectedQuarter || ''} onChange={(e) => setSelectedQuarter(e.target.value ? Number(e.target.value) : null)} style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: '#f1f5f9', fontSize: 11, cursor: 'pointer' }}><option value="">Full Year</option><option value="1">Q1 (Jan–Mar)</option><option value="2">Q2 (Apr–Jun)</option><option value="3">Q3 (Jul–Sep)</option><option value="4">Q4 (Oct–Dec)</option></select></div></div>
      </div>
      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.07)', overflowX: 'auto' }}>
        {TABS.map((t, i) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} tabIndex={tab === t ? 0 : -1} onKeyDown={(e) => {
          if (e.key === 'ArrowRight') { e.preventDefault(); setTab(TABS[(i + 1) % TABS.length]); }
          else if (e.key === 'ArrowLeft') { e.preventDefault(); setTab(TABS[(i - 1 + TABS.length) % TABS.length]); }
          else if (e.key === 'Home') { e.preventDefault(); setTab(TABS[0]); }
          else if (e.key === 'End') { e.preventDefault(); setTab(TABS[TABS.length - 1]); }
        }} style={{ padding: '10px 18px', fontSize: 12, fontWeight: tab === t ? 700 : 500, color: tab === t ? '#f1f5f9' : '#475569', background: 'transparent', border: 'none', whiteSpace: 'nowrap', borderBottom: tab === t ? '2px solid #3b82f6' : '2px solid transparent', cursor: 'pointer' }}>{t}</button>)}
      </div>
      <div style={{ paddingTop: 16 }}>
        <TabErrorBoundary key={tab}>
          <Suspense fallback={<Skeleton height={260} />}>
            {renderTab()}
          </Suspense>
        </TabErrorBoundary>
      </div>
      <style>{`
        @keyframes fp-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
        select { appearance: none; background-color: rgba(15, 23, 42, 0.8) !important; color: #f1f5f9 !important; }
        select option { background-color: #0f172a !important; color: #f1f5f9 !important; }
        select option:checked { background: linear-gradient(#3b82f6, #3b82f6) !important; background-color: #3b82f6 !important; color: #ffffff !important; }
      `}</style>
    </div>
  );
};

export default ForecastingPanelContainer;
