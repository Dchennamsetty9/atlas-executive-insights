import { useCallback, useEffect, useState } from 'react';
import { apiService } from '../../services/api';
import { MOMENTUM_META, RISK_META, Skeleton, fmtM, mapeColor } from './common';

const normalizeInsightItems = (value) => {
  if (Array.isArray(value)) {
    return value.map((v) => (v == null ? '' : String(v).trim())).filter(Boolean);
  }

  if (typeof value === 'string') {
    const s = value.trim();
    if (!s) return [];
    if (s.startsWith('[')) {
      try {
        const parsed = JSON.parse(s);
        if (Array.isArray(parsed)) {
          return parsed.map((v) => (v == null ? '' : String(v).trim())).filter(Boolean);
        }
      } catch (_e) {
      }
    }
    const parts = s.split(/\r?\n|;|\|/).map((v) => v.trim()).filter(Boolean);
    return parts.length > 0 ? parts : [s];
  }

  return [];
};

const AiInsightsSection = () => {
  const [aiData, setAiData] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);

  const loadAi = useCallback(async () => {
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await apiService.getForecastV2Intelligence();
      const d = (res?.data && typeof res.data === 'object') ? res.data : res;
      setAiData({ ...d, _source: res?.source ?? d?.source });
    } catch (e) {
      setAiError(e.message || 'Failed to load AI insights');
    } finally {
      setAiLoading(false);
    }
  }, []);

  useEffect(() => { loadAi(); }, [loadAi]);

  const momentum = aiData?.momentum ?? aiData?.trend_status;
  const risk = aiData?.risk_level;
  const momMeta = MOMENTUM_META[momentum] ?? MOMENTUM_META.STABLE;
  const riskMeta = RISK_META[risk] ?? RISK_META.moderate;
  const rawConf = aiData?.model_confidence;
  const confidence = rawConf != null ? (rawConf > 1 ? Math.round(rawConf) : Math.round(rawConf * 100)) : null;
  const confColor = confidence == null ? '#94a3b8' : confidence >= 90 ? '#10b981' : confidence >= 70 ? '#f59e0b' : '#ef4444';
  const narrative = aiData?.narrative ?? aiData?.description;
  const mape = aiData?.best_mape ?? aiData?.mape;
  const isDemo = aiData?._source === 'demo';

  const fmtDelta = (v) => {
    if (v == null) return null;
    if (typeof v === 'string') return v;
    return fmtM(Math.abs(Number(v)));
  };

  const upsideStr = fmtDelta(aiData?.upside ?? aiData?.upside_dollar);
  const downsideStr = fmtDelta(aiData?.downside ?? aiData?.downside_dollar);

  if (aiLoading) return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}><Skeleton height={80} /><Skeleton height={60} /><Skeleton height={48} /><Skeleton height={48} /></div>;

  if (aiError) {
    return (
      <div style={{ padding: '24px', background: 'rgba(239,68,68,0.06)', borderRadius: 10, color: '#ef4444', textAlign: 'center' }}>
        <p style={{ margin: 0 }}>{aiError}</p>
        <button onClick={loadAi} style={{ marginTop: 10, padding: '4px 16px', borderRadius: 6, cursor: 'pointer', background: 'transparent', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)', fontSize: 12 }}>Retry</button>
      </div>
    );
  }

  if (aiData?.error && !aiData?.key_drivers?.length) {
    return (
      <div style={{ padding: '24px', background: 'rgba(245,158,11,0.06)', borderRadius: 10, color: '#f59e0b', textAlign: 'center' }}>
        <div style={{ fontSize: 24, marginBottom: 8 }}>💭</div>
        <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{aiData.narrative || aiData.error}</p>
        <p style={{ margin: '8px 0 0', fontSize: 12, color: '#64748b' }}>Run Cell 10 (Step 7) of the Panel Writer notebook to populate the AI Insights Delta table.</p>
        <button onClick={loadAi} style={{ marginTop: 10, padding: '4px 16px', borderRadius: 6, cursor: 'pointer', background: 'transparent', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)', fontSize: 12 }}>↻ Retry</button>
      </div>
    );
  }

  const drivers = normalizeInsightItems(aiData?.key_drivers);
  const downsideItems = normalizeInsightItems(aiData?.downside_risks);
  const upsideItems = normalizeInsightItems(aiData?.upside_opportunities);
  const actions = normalizeInsightItems(aiData?.executive_actions);
  const topAction = actions[0] ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {isDemo && <div style={{ padding: '8px 14px', borderRadius: 8, fontSize: 12, color: '#f59e0b', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)' }}>📋 Sample data — connect to Databricks for live AI insights</div>}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {momentum && <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', padding: '4px 12px', borderRadius: 20, color: momMeta.color, background: momMeta.bg, border: `1px solid ${momMeta.color}40` }}>{String(momentum).toUpperCase()}</span>}
          {risk && <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', padding: '4px 12px', borderRadius: 20, color: riskMeta.color, background: riskMeta.bg, border: `1px solid ${riskMeta.color}40` }}>{String(risk).toUpperCase().replace('_', ' ')}</span>}
          {mape != null && <span style={{ fontSize: 10, padding: '4px 10px', borderRadius: 16, color: mapeColor(Number(mape)), background: 'rgba(255,255,255,0.04)', border: `1px solid ${mapeColor(Number(mape))}40` }}>MAPE {Number(mape).toFixed ? Number(mape).toFixed(1) : mape}%</span>}
        </div>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end' }}>
          {upsideStr && <div style={{ textAlign: 'right' }}><div style={{ fontSize: 10, fontWeight: 600, color: '#10b981', letterSpacing: '0.06em', marginBottom: 2 }}>UPSIDE</div><div style={{ fontSize: 18, fontWeight: 800, color: '#10b981', lineHeight: 1 }}>{upsideStr}</div></div>}
          {confidence != null && <div style={{ textAlign: 'right' }}><div style={{ fontSize: 10, color: '#64748b', letterSpacing: '0.06em', marginBottom: 1 }}>CONFIDENCE</div><div style={{ fontSize: 28, fontWeight: 800, color: confColor, lineHeight: 1 }}>{confidence}%</div></div>}
          {downsideStr && <div style={{ textAlign: 'right' }}><div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', letterSpacing: '0.06em', marginBottom: 2 }}>DOWNSIDE</div><div style={{ fontSize: 18, fontWeight: 800, color: '#ef4444', lineHeight: 1 }}>−{downsideStr}</div></div>}
        </div>
      </div>
      {narrative && <div style={{ fontSize: 14, color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.7, padding: '14px 18px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10 }}>{narrative}</div>}

      {drivers.length > 0 && (
        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '14px 16px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#10b981', letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 8 }}>Key Drivers</div>
          {drivers.slice(0, 3).map((item, i) => <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 6 }}><span style={{ color: '#10b981', marginTop: 2, flexShrink: 0 }}>▸</span><span style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.5 }}>{item}</span></div>)}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
        <div style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 10, padding: '12px 14px' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#ef4444', letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 6 }}>Downside ($)</div>
          <div style={{ fontSize: 19, fontWeight: 800, color: '#ef4444' }}>{downsideStr ? `−${downsideStr}` : '—'}</div>
          {downsideItems[0] && <div style={{ fontSize: 12, color: '#fca5a5', marginTop: 5, lineHeight: 1.4 }}>{downsideItems[0]}</div>}
        </div>
        <div style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.25)', borderRadius: 10, padding: '12px 14px' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#10b981', letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 6 }}>Upside ($)</div>
          <div style={{ fontSize: 19, fontWeight: 800, color: '#10b981' }}>{upsideStr || '—'}</div>
          {upsideItems[0] && <div style={{ fontSize: 12, color: '#86efac', marginTop: 5, lineHeight: 1.4 }}>{upsideItems[0]}</div>}
        </div>
      </div>

      {topAction && (
        <div style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 10, padding: '14px 16px' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#93c5fd', letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 6 }}>One Action</div>
          <div style={{ fontSize: 14, color: '#dbeafe', lineHeight: 1.55 }}>{topAction}</div>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 4 }}>
        <span style={{ fontSize: 11, color: '#334155' }}>{isDemo ? '🔵 Demo — connect to Databricks for live insights' : `🟢 Live · Pre-computed insights${aiData?.run_date ? ` · Run ${aiData.run_date}` : ''}`}</span>
        <button onClick={loadAi} disabled={aiLoading} style={{ padding: '4px 12px', borderRadius: 6, cursor: aiLoading ? 'default' : 'pointer', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: '#64748b', fontSize: 11, opacity: aiLoading ? 0.5 : 1 }}>{aiLoading ? 'Refreshing…' : '↻ Refresh'}</button>
      </div>
    </div>
  );
};

export default AiInsightsSection;
