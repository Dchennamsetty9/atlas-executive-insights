import { useState } from 'react';
import { TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle, Info } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';

const EnhancedKPICard = ({ kpi, insights, loading, compact = false, activeInsightId, onInsightToggle }) => {
  const [aiInsight,  setAiInsight]  = useState(null);
  const [aiLoading,  setAiLoading]  = useState(false);
  const [aiOpen,     setAiOpen]     = useState(false);

  const fetchAiInsight = async () => {
    if (aiInsight) { setAiOpen(o => !o); return; }
    setAiLoading(true);
    setAiOpen(true);
    try {
      const res  = await fetch('/api/ai/kpi-card-insight', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          kpi_name:   kpi?.title || '',
          kpi_value:  kpi?.value,
          kpi_target: kpi?.target,
          trend_data: [],
        }),
      });
      const body = await res.json();
      if (body.success && body.data) setAiInsight(body.data);
    } catch { /* silent — button just stays visible */ }
    finally { setAiLoading(false); }
  };

  if (loading) {
    const p = compact ? 12 : 24;
    return (
      <div style={{
        background: 'rgba(15,23,42,0.55)', border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 10, padding: p, animation: 'pulse 1.5s ease-in-out infinite',
      }}>
        <div style={{ height: compact ? 11 : 13, background: 'rgba(255,255,255,0.07)', borderRadius: 4, width: compact ? 64 : 96, marginBottom: compact ? 8 : 16 }} />
        <div style={{ height: compact ? 22 : 30, background: 'rgba(255,255,255,0.07)', borderRadius: 4, width: compact ? 80 : 128, marginBottom: 8 }} />
        <div style={{ height: compact ? 11 : 13, background: 'rgba(255,255,255,0.05)', borderRadius: 4, width: compact ? 48 : 80 }} />
      </div>
    );
  }

  const {
    title,
    value,
    target,
    previous_value,
    unit = '',
  } = kpi;

  // Determine if this is a currency KPI (check for $ in unit)
  const isCurrency = unit === '$' || unit.includes('$');
  const isPercentage = unit === '%' || unit.includes('%');

  // Calculate metrics
  const changeValue = previous_value ? ((value - previous_value) / previous_value) * 100 : 0;
  const isPositive = changeValue > 0;
  const isNeutral = Math.abs(changeValue) < 0.1;
  const targetAchievement = target ? (value / target) * 100 : null;
  const metTarget = targetAchievement >= 100;
  const atRisk = targetAchievement && targetAchievement < 90;
  const exceeding = targetAchievement && targetAchievement > 110;

  // Calculate dollar impact (for currency KPIs)
  const dollarImpact = isCurrency && target ? value - target : null;
  const impactLabel = dollarImpact > 0 ? 'Above Target' : dollarImpact < 0 ? 'Below Target' : 'On Target';
  const impactColor = dollarImpact > 0 ? 'text-green-600' : dollarImpact < 0 ? 'text-red-600' : 'text-blue-600';

  // Format value
  const formatValue = (val) => {
    if (isCurrency) {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(val);
    } else if (isPercentage) {
      return `${val.toFixed(1)}%`;
    } else {
      return new Intl.NumberFormat('en-US').format(val);
    }
  };

  // Format dollar impact (always show decimal for values < 1M)
  const formatDollarImpact = (val) => {
    const absVal = Math.abs(val);
    if (absVal < 1) {
      // Values < $1M: show with 1 decimal place (e.g., "$0.5M" for $500K)
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }).format(val) + 'M';
    } else {
      // Values >= $1M: show without decimals (e.g., "$2M")
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(val) + 'M';
    }
  };

  // Get status icon and message
  const getStatusInfo = () => {
    if (exceeding) {
      return {
        icon: <CheckCircle className="w-5 h-5 text-green-600" />,
        message: 'Exceeding Target',
        color: 'bg-green-50 border-green-200 text-green-800'
      };
    } else if (metTarget) {
      return {
        icon: <CheckCircle className="w-5 h-5 text-blue-600" />,
        message: 'On Target',
        color: 'bg-blue-50 border-blue-200 text-blue-800'
      };
    } else if (atRisk) {
      return {
        icon: <AlertTriangle className="w-5 h-5 text-red-600" />,
        message: 'Action Required',
        color: 'bg-red-50 border-red-200 text-red-800'
      };
    } else {
      return {
        icon: <Info className="w-5 h-5 text-orange-600" />,
        message: 'Watch Closely',
        color: 'bg-orange-50 border-orange-200 text-orange-800'
      };
    }
  };

  const statusInfo = getStatusInfo();
  const trendColor = isNeutral ? 'text-gray-500' : isPositive ? 'text-green-600' : 'text-red-600';
  const getTrendIcon = () => {
    if (isNeutral) return <Minus className="w-4 h-4" />;
    return isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />;
  };

  const glowColor = atRisk ? 'rgba(239,68,68,0.18)' : exceeding ? 'rgba(16,185,129,0.12)' : 'transparent';

  const DARK_STATUS = {
    exceeding: { border: '#10b981', bg: 'rgba(16,185,129,0.12)', text: '#10b981' },
    onTarget:  { border: '#3b82f6', bg: 'rgba(59,130,246,0.1)',  text: '#3b82f6' },
    atRisk:    { border: '#ef4444', bg: 'rgba(239,68,68,0.12)',  text: '#ef4444' },
    watch:     { border: '#f59e0b', bg: 'rgba(245,158,11,0.12)', text: '#f59e0b' },
  };
  const ds = exceeding ? DARK_STATUS.exceeding : metTarget ? DARK_STATUS.onTarget : atRisk ? DARK_STATUS.atRisk : DARK_STATUS.watch;
  const trendColorDark = isNeutral ? '#64748b' : isPositive ? '#10b981' : '#ef4444';

  return (
    <div style={{
      background: 'rgba(15,23,42,0.6)',
      border: `1px solid ${atRisk ? 'rgba(239,68,68,0.25)' : exceeding ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.08)'}`,
      borderRadius: 10,
      backdropFilter: 'blur(8px)',
      boxShadow: atRisk ? '0 0 14px rgba(239,68,68,0.15)' : exceeding ? '0 0 14px rgba(16,185,129,0.1)' : '0 2px 8px rgba(0,0,0,0.3)',
      animation: atRisk ? 'kpiPulse 3s ease-in-out infinite' : 'none',
      transition: 'box-shadow 0.2s',
    }}>

      {/* Main KPI Display */}
      <div style={{ padding: compact ? 12 : 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: compact ? 8 : 14 }}>
          <div style={{ flex: 1 }}>
            <h3 style={{ fontSize: compact ? 11 : 13, fontWeight: 700, color: '#94a3b8', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: 0.5 }}>{title}</h3>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: compact ? '2px 7px' : '3px 9px',
              borderRadius: 20, border: `1px solid ${ds.border}44`,
              background: ds.bg, fontSize: 10, fontWeight: 700, color: ds.text,
            }}>
              {!compact && statusInfo.icon}
              {statusInfo.message}
            </div>
          </div>
          <div style={{ color: trendColorDark, display: 'flex', alignItems: 'center' }}>
            {getTrendIcon()}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 8 : 10 }}>
          <div style={{ fontSize: compact ? 22 : 32, fontWeight: 800, color: '#f1f5f9', lineHeight: 1 }}>
            {formatValue(value)}
            {unit && <span style={{ fontSize: compact ? 11 : 16, fontWeight: 400, color: '#475569', marginLeft: 4 }}>{unit}</span>}
          </div>

          {target && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: compact ? 11 : 12 }}>
                <span style={{ color: '#475569' }}>Target: {formatValue(target)}</span>
                <span style={{ fontWeight: 700, color: metTarget ? '#10b981' : '#f59e0b' }}>
                  {targetAchievement.toFixed(0)}%
                </span>
              </div>

              {/* Dollarized impact row */}
              {dollarImpact !== null && Math.abs(dollarImpact) > (compact ? 0.5 : 0) && (
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: compact ? '5px 8px' : '7px 10px',
                  borderRadius: 6,
                  border: `1px solid ${dollarImpact > 0 ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
                  background: dollarImpact > 0 ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
                }}>
                  <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: 1, textTransform: 'uppercase', color: dollarImpact > 0 ? '#10b981' : '#ef4444' }}>
                    {impactLabel}
                  </span>
                  <span style={{ fontSize: compact ? 13 : 16, fontWeight: 800, color: dollarImpact > 0 ? '#10b981' : '#ef4444' }}>
                    {dollarImpact > 0 ? '+' : ''}{formatDollarImpact(dollarImpact)}
                  </span>
                </div>
              )}
            </>
          )}

          {previous_value && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: '#475569' }}>vs Last Quarter</span>
              <span style={{ fontWeight: 600, color: trendColorDark }}>
                {isPositive && '+'}{changeValue.toFixed(1)}%
              </span>
            </div>
          )}

          {/* Progress bar */}
          {targetAchievement && (
            <div style={{ height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: 2,
                width: `${Math.min(targetAchievement, 100)}%`,
                background: exceeding ? 'linear-gradient(90deg,#10b981,#34d399)'
                           : metTarget ? 'linear-gradient(90deg,#3b82f6,#60a5fa)'
                           : atRisk    ? 'linear-gradient(90deg,#ef4444,#f87171)'
                           : 'linear-gradient(90deg,#f59e0b,#fbbf24)',
                transition: 'width 0.4s ease',
              }} />
            </div>
          )}

          {/* Mini sparkline (weekly trend) */}
          {Array.isArray(kpi.trend_data) && kpi.trend_data.length >= 3 && (
            <div style={{ height: 28, marginTop: 2 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={kpi.trend_data.map((v, i) => ({ i, v }))}
                  margin={{ top: 2, bottom: 2, left: 0, right: 0 }}
                >
                  <Line
                    type="monotone" dataKey="v" dot={false} strokeWidth={1.5}
                    stroke={exceeding ? '#10b981' : atRisk ? '#ef4444' : '#3b82f6'}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Insights preview (non-compact) */}
          {insights && !compact && (
            <div style={{ paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ display: 'flex', gap: 6, fontSize: 11 }}>
                <span style={{ fontSize: 12 }}>💡</span>
                <p style={{ margin: 0, color: '#64748b', lineHeight: 1.5, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                  {insights.summary}
                </p>
              </div>
            </div>
          )}

          {/* ◈ AI Insight Button (Feature 3) */}
          {!compact && (
            <button
              onClick={fetchAiInsight}
              style={{
                width: '100%', marginTop: 4,
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                padding: '4px 8px', fontSize: 10, fontWeight: 600,
                color: aiOpen ? '#a78bfa' : '#7c3aed',
                cursor: 'pointer',
                background: aiOpen ? 'rgba(124,58,237,0.12)' : 'rgba(124,58,237,0.05)',
                border: `1px solid ${aiOpen ? 'rgba(124,58,237,0.4)' : 'rgba(124,58,237,0.15)'}`,
                borderRadius: 6, transition: 'all 0.15s', fontFamily: 'inherit',
              }}
            >
              <span>◈</span>
              <span>{aiLoading ? 'Analyzing…' : aiOpen ? '↑ AI Insight' : '↓ AI Insight'}</span>
            </button>
          )}

          {/* ↓ Compact Insight Toggle */}
          {insights && (
            <button
              onClick={() => onInsightToggle ? onInsightToggle(kpi?.id) : null}
              style={{
                width: '100%', marginTop: compact ? 4 : 8,
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                padding: '4px 8px',
                fontSize: 10, fontWeight: 600,
                color: activeInsightId === kpi?.id ? '#60a5fa' : '#3b82f6',
                cursor: 'pointer',
                background: activeInsightId === kpi?.id ? 'rgba(59,130,246,0.1)' : 'rgba(59,130,246,0.04)',
                border: `1px solid ${activeInsightId === kpi?.id ? 'rgba(59,130,246,0.3)' : 'rgba(59,130,246,0.12)'}`,
                borderRadius: 6, transition: 'all 0.15s', fontFamily: 'inherit',
              }}
            >
              <span>📊</span>
              <span>{activeInsightId === kpi?.id ? '↑ Hide' : '↓ Insights'}</span>
            </button>
          )}
        </div>
      </div>

      {/* ── Compact Insight Panel (accordion, max 150px) ──────────────────── */}
      {/* ── AI Insight Accordion (Feature 3) ─────────────────────────── */}
      {!compact && aiOpen && (
        <div style={{
          borderTop: '1px solid rgba(124,58,237,0.2)',
          background: 'rgba(124,58,237,0.06)',
          padding: '8px 12px',
          display: 'flex', flexDirection: 'column', gap: 5,
        }}>
          {aiLoading ? (
            <div style={{ height: 11, borderRadius: 4, background: 'rgba(255,255,255,0.06)', animation: 'pulse 1.5s ease-in-out infinite' }} />
          ) : aiInsight ? (
            <>
              {aiInsight.summary && (
                <span style={{ fontSize: 11, color: '#c4b5fd', lineHeight: 1.5 }}>{aiInsight.summary}</span>
              )}
              {aiInsight.recommendation && (
                <span style={{ fontSize: 10, color: '#a78bfa', fontWeight: 600 }}>→ {aiInsight.recommendation}</span>
              )}
              <div style={{ display: 'flex', gap: 10, marginTop: 2 }}>
                {aiInsight.trend_direction && (
                  <span style={{ fontSize: 9, color: '#7c3aed', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8 }}>Trend: {aiInsight.trend_direction}</span>
                )}
                {aiInsight.risk_level && (
                  <span style={{ fontSize: 9, color: aiInsight.risk_level === 'high' ? '#f87171' : aiInsight.risk_level === 'medium' ? '#fbbf24' : '#34d399', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8 }}>Risk: {aiInsight.risk_level}</span>
                )}
              </div>
            </>
          ) : (
            <span style={{ fontSize: 10, color: '#64748b' }}>Could not load AI insight.</span>
          )}
        </div>
      )}

      {insights && activeInsightId === kpi?.id && (
        <div style={{
          borderTop: '1px solid rgba(255,255,255,0.07)',
          background: 'rgba(0,0,0,0.25)',
          padding: '8px 12px',
          maxHeight: 150,
          overflowY: 'auto',
          display: 'flex', flexDirection: 'column', gap: 5,
          animation: 'slideDown 0.15s ease-out',
        }}>
          {/* Line 1: Status sentence */}
          {insights.summary && (
            <div style={{ display: 'flex', gap: 5, alignItems: 'flex-start' }}>
              <span style={{ fontSize: 10, flexShrink: 0 }}>💡</span>
              <span style={{ fontSize: 10, color: '#94a3b8', lineHeight: 1.4 }}>
                {insights.summary}
              </span>
            </div>
          )}

          {/* Line 2: Action recommendation */}
          {(insights.needsAttention?.[0] || insights.actions?.[0]) && (
            <div style={{ display: 'flex', gap: 5, alignItems: 'flex-start' }}>
              <span style={{ fontSize: 10, flexShrink: 0 }}>⚠️</span>
              <span style={{ fontSize: 10, color: '#fca5a5', lineHeight: 1.4 }}>
                {insights.needsAttention?.[0] || insights.actions?.[0]?.description}
              </span>
            </div>
          )}

          {/* Line 3: Best / Worst segment */}
          {insights.demographics?.length > 0 && (() => {
            const sorted = [...insights.demographics].sort((a, b) => a.performance - b.performance);
            const worst = sorted[0];
            const best  = sorted[sorted.length - 1];
            return (
              <div style={{ display: 'flex', gap: 5, alignItems: 'flex-start' }}>
                <span style={{ fontSize: 10, flexShrink: 0 }}>📍</span>
                <span style={{ fontSize: 10, color: '#64748b', lineHeight: 1.4 }}>
                  {worst && <span style={{ color: '#fca5a5' }}>Worst: {worst.segment} ({worst.performance}%)</span>}
                  {worst && best && worst !== best && <span style={{ color: '#475569' }}> · </span>}
                  {best && best !== worst && <span style={{ color: '#6ee7b7' }}>Best: {best.segment} ({best.performance}%)</span>}
                </span>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
};

export default EnhancedKPICard;
