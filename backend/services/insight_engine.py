"""
insight_engine.py
Automatically detects hidden patterns in GAIM KPI data and translates them
into actionable, dollar-denominated insights.

Four analysis modules:
  1. decompose_revenue_gap   — dollarized impact breakdown of each KPI shortfall
  2. detect_rate_divergence  — timing signal when Win Rate >> Close Rate
  3. find_segment_anomalies  — segments masking or dragging aggregate performance
  4. detect_pacing_patterns  — trajectory vs. same-day historical benchmarks
"""

from typing import List, Dict


class InsightEngine:
    """Detects hidden patterns in GAIM KPI data."""

    def generate_all_insights(self, kpi_data: dict) -> List[Dict]:
        insights = []
        insights.extend(self.decompose_revenue_gap(kpi_data))
        insights.extend(self.detect_rate_divergence(kpi_data))
        insights.extend(self.find_segment_anomalies(kpi_data))
        insights.extend(self.detect_pacing_patterns(kpi_data))
        return insights

    # ------------------------------------------------------------------
    # 1. DOLLARIZED IMPACT DECOMPOSITION
    # ------------------------------------------------------------------

    def decompose_revenue_gap(self, data: dict) -> List[Dict]:
        """
        Dollarized impact decomposition — exact methodology from the KPI Trends dashboard.

        Two parallel funnels both reconcile to Won Amount:

          Opp Volume Funnel
          ─────────────────
          Opened Opps impact     = (actual − target) × target_CR_vol × target_ADS
          Close Rate (Vol) impact= actual_opened × (actual_CR_vol − target_CR_vol) × target_ADS
          Won Opps impact        = (actual − target) × target_ADS          ← sum of above two
          ADS impact             = actual_won_opps × (actual_ADS − target_ADS)
          Won Amount impact      = actual − target                          ← sum of Won Opps + ADS

          Dollar Funnel
          ─────────────
          Avg Opp Size impact    = actual_opened × (actual_AOS − target_AOS) × target_CR_dollar
          Pipeline impact        = (actual − target) × target_CR_dollar
          Close Rate ($) impact  = actual_pipeline × (actual_CR_dollar − target_CR_dollar)
          Won Amount impact      = actual − target                          ← sum of Pipeline + CR($)

        Rates from data dict are on the 0-100 scale; divide by 100 for formula use.
        Returns an insight for every call (positive gap = tailwind analysis).
        """
        insights = []

        cwa_actual = float(data.get("won_pipeline_actual") or 0)
        cwa_target = float(data.get("won_pipeline_target") or 0)
        cwa_gap    = cwa_actual - cwa_target

        if cwa_target == 0:
            return insights

        # Pull all inputs
        won_opps_actual     = float(data.get("won_opps_actual")         or 0)
        won_opps_target     = float(data.get("won_opps_target")         or 0)
        ads_actual          = float(data.get("ads_actual")              or 0)
        ads_target          = float(data.get("ads_target")              or 0)
        opps_actual         = float(data.get("opps_created_actual")     or 0)
        opps_target         = float(data.get("opps_created_target")     or 0)
        pipeline_actual     = float(data.get("created_pipeline_actual") or 0)
        pipeline_target     = float(data.get("created_pipeline_target") or 0)
        aos_actual          = float(data.get("aos_actual")              or 0)
        aos_target          = float(data.get("aos_target")              or 0)

        # Rates: stored 0-100, convert to fractions for formula
        cr_vol_actual   = float(data.get("close_rate_vol")           or 0) / 100
        cr_vol_target   = float(data.get("close_rate_vol_target")    or 0) / 100
        cr_dol_actual   = float(data.get("close_rate_dollar")        or 0) / 100
        cr_dol_target   = float(data.get("close_rate_dollar_target") or 0) / 100

        # Guard against zero targets — fall back to actuals so the formula still runs
        ads_target     = ads_target     or ads_actual
        cr_vol_target  = cr_vol_target  or cr_vol_actual
        cr_dol_target  = cr_dol_target  or cr_dol_actual

        # ── Opp Volume Funnel ──────────────────────────────────────────────────
        opened_opps_impact = (opps_actual     - opps_target)    * cr_vol_target * ads_target
        cr_vol_impact      = opps_actual      * (cr_vol_actual  - cr_vol_target) * ads_target
        won_opps_impact    = (won_opps_actual - won_opps_target) * ads_target
        ads_impact         = won_opps_actual  * (ads_actual     - ads_target)

        # ── Dollar Funnel ──────────────────────────────────────────────────────
        aos_impact         = opps_actual      * (aos_actual     - aos_target)    * cr_dol_target
        pipeline_impact    = (pipeline_actual - pipeline_target) * cr_dol_target
        cr_dollar_impact   = pipeline_actual  * (cr_dol_actual  - cr_dol_target)

        impacts = {
            "Opened Opps":     round(opened_opps_impact, 0),
            "Close Rate (Vol)": round(cr_vol_impact,      0),
            "Won Opps":        round(won_opps_impact,     0),
            "ADS":             round(ads_impact,          0),
            "Avg Opp Size":    round(aos_impact,          0),
            "Pipeline ($)":    round(pipeline_impact,     0),
            "Close Rate ($)":  round(cr_dollar_impact,    0),
        }

        # Primary driver = KPI with largest absolute impact (drag or tailwind)
        sorted_impacts = sorted(impacts.items(), key=lambda x: abs(x[1]), reverse=True)
        primary_driver, primary_val = sorted_impacts[0]
        driver_pct = abs(primary_val / cwa_gap) * 100 if cwa_gap != 0 else 0

        below_target = cwa_gap < 0
        gap_abs_str  = f"${abs(cwa_gap):,.0f}"
        direction    = "below paced target" if below_target else "ahead of paced target"

        # Actionable recommendation based on top drag (if below target)
        drag_kpi, _ = min(impacts.items(), key=lambda x: x[1])
        rec_map = {
            "Opened Opps":      "Drive more qualified opportunities into the funnel.",
            "Close Rate (Vol)": "Focus on deal progression and reducing stalled opportunities.",
            "Won Opps":         "Prioritise closing open opportunities before quarter-end.",
            "ADS":              "Negotiate larger deal sizes or bundle additional products.",
            "Avg Opp Size":     "Qualify larger-ACV opportunities at the top of funnel.",
            "Pipeline ($)":     "Accelerate pipeline creation to hit the dollar ramp.",
            "Close Rate ($)":   "Improve dollar-weighted conversion — prioritise high-ACV deals.",
        }
        recommendation = rec_map.get(drag_kpi, f"Address {drag_kpi} to recover the largest portion of the gap.") if below_target else (
            f"{primary_driver} is the biggest tailwind. Protect it through quarter-end."
        )

        insights.append({
            "type":        "impact_decomposition",
            "severity":    "high" if below_target else "positive",
            "icon":        "\U0001f4b0",
            "title":       f"{'Revenue Gap' if below_target else 'Revenue Beat'} Driver: {primary_driver}",
            "description": (
                f"Revenue is {gap_abs_str} {direction}. "
                f"{primary_driver} accounts for {driver_pct:.0f}% of the variance."
            ),
            "recommendation": recommendation,
            "impact_dollars": round(cwa_gap, 0),
            "impacts":        impacts,
            # ── Two-funnel breakdown (matches KPI Trends — Overview Power BI layout) ──
            # Opp Volume Funnel: Opened Opps × CR(Vol) = Won Opps → Won Opps × ADS = Won Amount
            # Additivity: Opened Opps + Close Rate (Vol) = Won Opps; Won Opps + ADS = Won Amount
            "funnel_opp_volume": {
                "Opened Opps":      round(opened_opps_impact, 0),
                "Close Rate (Vol)": round(cr_vol_impact,      0),
                "Won Opps":         round(won_opps_impact,    0),   # = Opened Opps + CR(Vol)
                "ADS":              round(ads_impact,         0),
            },
            # Dollar Funnel: Opened Opps × AOS = Pipeline → Pipeline × CR($) = Won Amount
            # Additivity: (Opened Opps vol impact + AOS impact) ≈ Pipeline impact; Pipeline + CR($) = Won Amount
            "funnel_dollar": {
                "Avg Opp Size":    round(aos_impact,        0),
                "Pipeline ($)":    round(pipeline_impact,   0),   # = Opened Opps (dollar basis) + AOS
                "Close Rate ($)":  round(cr_dollar_impact,  0),
            },
        })

        return insights

    # ------------------------------------------------------------------
    # 2. WIN RATE vs CLOSE RATE DIVERGENCE (TIMING SIGNAL)
    # ------------------------------------------------------------------

    def detect_rate_divergence(self, data: dict) -> List[Dict]:
        """
        When Win Rate is healthy but Close Rate is low the most likely cause
        is that many deals are still open (unresolved), not that deals are
        being lost. This is a TIMING signal, not a performance problem.

        Win Rate  = Wins / (Wins + Losses) — resolved deals ONLY
        Close Rate= Wins / All Opps entered — includes still-open deals

        Flag when: Win Rate > 60% AND Close Rate < 40%
        """
        insights = []

        win_rate   = float(data.get("win_rate")   or 0)
        close_rate = float(data.get("close_rate_vol") or 0)

        # Normalise if values were passed as percentages (>1 means 0-100 scale)
        if win_rate > 1:
            win_rate /= 100
        if close_rate > 1:
            close_rate /= 100

        if win_rate > 0.60 and close_rate < 0.40:
            divergence = win_rate - close_rate
            insights.append({
                "type":     "rate_divergence",
                "severity": "medium",
                "icon":     "\u23f1\ufe0f",
                "title":    "Timing Signal: Pipeline Resolution Pending",
                "description": (
                    f"Win Rate ({win_rate*100:.0f}%) is healthy but Close Rate "
                    f"({close_rate*100:.0f}%) appears low. This means many deals "
                    f"are still open and unresolved — not that you are losing more."
                ),
                "recommendation": (
                    "This is expected mid-quarter. Monitor deal velocity rather "
                    "than close rate until more deals resolve."
                ),
                "data": {
                    "win_rate":   win_rate,
                    "close_rate": close_rate,
                    "gap":        round(divergence, 4),
                },
            })

        return insights

    # ------------------------------------------------------------------
    # 3. SEGMENT ANOMALY DETECTION
    # ------------------------------------------------------------------

    def find_segment_anomalies(self, data: dict) -> List[Dict]:
        """
        Detect segments (channel, geo, product, deal band) that are masking
        or dragging overall performance.

        Flags any segment whose win_rate deviates more than 15 pp from average.
        """
        insights = []
        segments = data.get("segment_performance") or []

        if not segments:
            return insights

        rates    = [float(s.get("win_rate") or 0) for s in segments]
        avg_rate = sum(rates) / len(rates) if rates else 0

        for segment in segments:
            seg_rate  = float(segment.get("win_rate") or 0)
            deviation = seg_rate - avg_rate

            if abs(deviation) <= 0.15:
                continue

            direction = "outperforming" if deviation > 0 else "underperforming"
            insights.append({
                "type":     "segment_anomaly",
                "severity": "medium",
                "icon":     "\U0001f50d",
                "title": (
                    f"{segment.get('name','Segment')} is {direction} "
                    f"by {abs(deviation)*100:.0f}%"
                ),
                "description": (
                    f"{segment.get('name','Segment')} Win Rate is {seg_rate*100:.0f}% "
                    f"vs overall {avg_rate*100:.0f}%. This segment is "
                    f"{'masking poor performance elsewhere' if deviation > 0 else 'dragging down the aggregate'}."
                ),
                "recommendation": (
                    "Investigate what is working in this segment and replicate."
                    if deviation > 0
                    else "Deep-dive into this segment for root cause."
                ),
                "data": {
                    "segment":          segment.get("name"),
                    "segment_win_rate": round(seg_rate, 4),
                    "overall_avg":      round(avg_rate, 4),
                    "deviation":        round(deviation, 4),
                },
            })

        return insights

    # ------------------------------------------------------------------
    # 4. PACING PATTERN DETECTION
    # ------------------------------------------------------------------

    def detect_pacing_patterns(self, data: dict) -> List[Dict]:
        """
        Compare current-quarter pacing vs. historical same-day benchmarks.
        Flags when the current trajectory deviates by more than 5 pp.
        """
        insights = []

        current_pct    = float(data.get("percent_to_target")       or 0)
        historical_pct = float(data.get("historical_median_pacing") or 0)

        if not current_pct or not historical_pct:
            return insights

        pacing_gap = current_pct - historical_pct

        if abs(pacing_gap) <= 0.05:
            return insights

        direction = "ahead of" if pacing_gap > 0 else "behind"
        severity  = "high" if pacing_gap < -0.10 else "low"

        insights.append({
            "type":     "pacing_pattern",
            "severity": severity,
            "icon":     "\U0001f4ca",
            "title":    f"Pacing: {abs(pacing_gap)*100:.0f}% {direction} historical norm",
            "description": (
                f"At this point in the quarter you are typically at "
                f"{historical_pct*100:.0f}% of target. Currently at "
                f"{current_pct*100:.0f}%."
            ),
            "recommendation": (
                "Strong position — maintain momentum."
                if pacing_gap > 0
                else (
                    "Historical data suggests end-of-quarter acceleration is needed. "
                    "Focus on deals closest to close."
                )
            ),
            "data": {
                "current_pct":    round(current_pct, 4),
                "historical_pct": round(historical_pct, 4),
                "gap":            round(pacing_gap, 4),
            },
        })

        return insights


# Singleton
insight_engine = InsightEngine()
