"""
Enhanced Insights Engine - AI-Powered Analysis and Recommendations
Provides detailed insights, demographic breakdowns, and actionable recommendations per KPI
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any
from datetime import datetime, timedelta


class EnhancedInsightsEngine:
    """Generates AI-powered insights, recommendations, and demographic analysis"""
    
    def __init__(self):
        self.kpi_thresholds = {
            'won_pipeline': {'critical': 0.85, 'warning': 0.95},
            'won_volume': {'critical': 0.85, 'warning': 0.95},
            'ads': {'critical': 0.90, 'warning': 0.95},
            'opps_created': {'critical': 0.85, 'warning': 0.95},
            'created_pipeline': {'critical': 0.85, 'warning': 0.95},
            'active_pipeline': {'critical': 2.0, 'warning': 2.5},  # Coverage ratio
            'close_rate': {'critical': 0.25, 'warning': 0.28},      # 25% minimum
            'coverage': {'critical': 2.5, 'warning': 3.0}           # 2.5x minimum
        }
    
    def generate_kpi_insights(self, kpi_id: str, current_value: float, target: float, 
                            previous_value: float = None, trend_data: List[float] = None) -> Dict[str, Any]:
        """Generate comprehensive insights for a single KPI"""
        
        achievement = (current_value / target * 100) if target > 0 else 0
        change = ((current_value - previous_value) / previous_value * 100) if previous_value else 0
        
        # Only show demographics for KPIs where segmentation matters
        show_demographics = kpi_id in ['won_pipeline', 'active_pipeline', 'created_pipeline', 'opps_created', 'coverage']
        
        insights = {
            'summary': self._generate_summary(kpi_id, achievement, change),
            'whatsWorking': self._analyze_positives(kpi_id, achievement, change),
            'needsAttention': self._analyze_concerns(kpi_id, achievement, change),
            'demographics': self._generate_demographic_breakdown(kpi_id, current_value) if show_demographics else [],
            'actions': self._generate_recommendations(kpi_id, achievement, change),
            'rootCause': self._analyze_root_cause(kpi_id, achievement, change, trend_data)
        }
        
        return insights
    
    def _generate_summary(self, kpi_id: str, achievement: float, change: float) -> str:
        """Generate natural language summary"""
        
        if achievement >= 110:
            status = "significantly exceeding target"
        elif achievement >= 100:
            status = "on track to meet target"
        elif achievement >= 90:
            status = "slightly below target but recoverable"
        else:
            status = "substantially below target - immediate action needed"
        
        trend = "improving" if change > 5 else "declining" if change < -5 else "stable"
        
        summaries = {
            'won_pipeline': f"Won ACV is {status}. Performance is {trend} compared to previous period.",
            'won_volume': f"Deal volume is {status}. {trend.capitalize()} trend indicates {'strong' if change > 0 else 'weak'} sales execution.",
            'ads': f"Average deal size is {status}. {'Larger' if change > 0 else 'Smaller'} deals suggest {'enterprise' if change > 0 else 'SMB'} focus shift.",
            'opps_created': f"Pipeline generation is {status}. {trend.capitalize()} creation rate {'validates' if change > 0 else 'challenges'} marketing effectiveness.",
            'created_pipeline': f"New pipeline value is {status}. {trend.capitalize()} creation indicates {'healthy' if change > 0 else 'concerning'} demand signals.",
            'active_pipeline': f"Coverage ratio is {status}. {'Adequate' if achievement >= 100 else 'Insufficient'} pipeline for quarter targets.",
            'close_rate': f"Win rate is {status}. {trend.capitalize()} close rate reflects {'improving' if change > 0 else 'declining'} sales effectiveness.",
            'coverage': f"Pipeline coverage is {status}. {'Strong' if achievement >= 100 else 'Weak'} qualification and {trend} velocity."
        }
        
        return summaries.get(kpi_id, f"Performance is {status} with {trend} trend.")
    
    def _analyze_positives(self, kpi_id: str, achievement: float, change: float) -> List[str]:
        """Identify what's working well"""
        
        positives = []
        
        if achievement >= 100:
            positives.append(f"Target achieved - on pace for {achievement:.0f}% of goal")
        
        if change > 10:
            positives.append(f"Strong momentum with {change:+.1f}% growth period-over-period")
        elif change > 5:
            positives.append(f"Positive trend showing {change:+.1f}% improvement")
        
        # KPI-specific positives
        kpi_positives = {
            'won_pipeline': [
                "Revenue execution aligns with business objectives",
                "Sales team demonstrating strong closing capability"
            ] if achievement >= 100 else [],
            'ads': [
                "Deal quality improving with larger average sizes",
                "Enterprise segment showing strong traction"
            ] if change > 10 else [],
            'close_rate': [
                "Sales process optimization delivering results",
                "Qualification improving deal quality"
            ] if achievement >= 100 else [],
            'active_pipeline': [
                "Healthy pipeline coverage reduces risk",
                "Strong demand signal for upcoming quarters"
            ] if achievement >= 100 else [],
        }
        
        positives.extend(kpi_positives.get(kpi_id, []))
        
        if not positives:
            positives = ["Continue monitoring for positive trends", "Opportunity for improvement exists"]
        
        return positives[:3]  # Return top 3
    
    def _analyze_concerns(self, kpi_id: str, achievement: float, change: float) -> List[str]:
        """Identify areas needing attention"""
        
        concerns = []
        
        if achievement < 90:
            concerns.append(f"Tracking {(100 - achievement):.0f}% below target - immediate intervention required")
        elif achievement < 95:
            concerns.append(f"Slightly below pace - need {(100 - achievement):.0f}% catch-up")
        
        if change < -10:
            concerns.append(f"Significant decline of {change:.1f}% requires root cause analysis")
        elif change < -5:
            concerns.append(f"Downward trend of {change:.1f}% - watch closely")
        
        # KPI-specific concerns
        kpi_concerns = {
            'won_pipeline': [
                "Revenue gap may impact quarterly targets",
                "Increased sales support needed to accelerate closes"
            ] if achievement < 90 else [],
            'opps_created': [
                "Insufficient top-of-funnel activity",
                "Marketing campaigns need optimization"
            ] if achievement < 90 else [],
            'active_pipeline': [
                "Coverage below 2.5x increases risk",
                "Need aggressive pipeline building efforts"
            ] if achievement < 90 else [],
            'close_rate': [
                "Win rate below 30% benchmark",
                "Sales training or process improvement needed"
            ] if achievement < 90 else [],
        }
        
        concerns.extend(kpi_concerns.get(kpi_id, []))
        
        if not concerns:
            concerns = ["Maintain current execution momentum", "Monitor for any negative trends"]
        
        return concerns[:3]  # Return top 3
    
    def _generate_demographic_breakdown(self, kpi_id: str, value: float) -> List[Dict[str, Any]]:
        """Generate simulated demographic performance breakdown"""
        # In production, this would query actual data by segment
        
        # Simulated segment performance (in production, query from database)
        demographics = []
        
        # Geographic segments
        geos = [
            {'segment': 'North America', 'performance': np.random.randint(95, 125), 'type': 'geo'},
            {'segment': 'EMEA', 'performance': np.random.randint(85, 115), 'type': 'geo'},
            {'segment': 'APAC', 'performance': np.random.randint(75, 105), 'type': 'geo'},
        ]
        
        # Product segments  
        products = [
            {'segment': 'Enterprise Suite', 'performance': np.random.randint(90, 120), 'type': 'product'},
            {'segment': 'Professional', 'performance': np.random.randint(85, 115), 'type': 'product'},
            {'segment': 'Standard', 'performance': np.random.randint(80, 110), 'type': 'product'},
        ]
        
        # Combine and sort by performance
        demographics = geos + products
        demographics.sort(key=lambda x: x['performance'], reverse=True)
        
        return demographics[:5]  # Return top 5 segments
    
    def _generate_recommendations(self, kpi_id: str, achievement: float, change: float) -> List[Dict[str, Any]]:
        """Generate specific, actionable recommendations"""
        
        actions = []
        urgency = 'high' if achievement < 90 or change < -10 else 'medium'
        
        # KPI-specific recommendations
        recommendations_map = {
            'won_pipeline': [
                {
                    'title': 'Accelerate Deal Closures',
                    'description': 'Review all deals >$50K with sales leadership. Remove blockers and expedite approvals.',
                    'urgency': urgency,
                    'actionType': 'meeting'
                },
                {
                    'title': 'Sales Coaching Session',
                    'description': 'Conduct 1:1 coaching with underperforming reps. Focus on objection handling and closing techniques.',
                    'urgency': 'medium',
                    'actionType': 'call'
                }
            ],
            'opps_created': [
                {
                    'title': 'Campaign Performance Review',
                    'description': 'Analyze marketing campaign ROI. Double down on high-performing channels, pause underperformers.',
                    'urgency': urgency,
                    'actionType': 'review'
                },
                {
                    'title': 'SDR Outreach Blitz',
                    'description': 'Launch targeted outreach campaign to top 100 accounts. Personalized messaging for high-value targets.',
                    'urgency': 'high',
                    'actionType': 'email'
                }
            ],
            'active_pipeline': [
                {
                    'title': 'Pipeline Building Sprint',
                    'description': 'All-hands pipeline generation week. Each sales rep targets 10 new qualified opportunities.',
                    'urgency': 'high' if achievement < 85 else 'medium',
                    'actionType': 'email'
                },
                {
                    'title': 'Partner Enablement',
                    'description': 'Activate channel partners with co-selling incentives. Joint pipeline building sessions.',
                    'urgency': 'medium',
                    'actionType': 'meeting'
                }
            ],
            'close_rate': [
                {
                    'title': 'Deal Qualification Audit',
                    'description': 'Review discovery process and MEDDIC qualification. Improve lead quality over quantity.',
                    'urgency': urgency,
                    'actionType': 'review'
                },
                {
                    'title': 'Win/Loss Analysis',
                    'description': 'Conduct win/loss interviews with last 20 deals. Identify patterns and adjust playbook.',
                    'urgency': 'medium',
                    'actionType': 'call'
                }
            ],
            'coverage': [
                {
                    'title': 'Increase Activity Metrics',
                    'description': 'Raise daily activity targets: 50 calls, 100 emails, 20 meetings per rep.',
                    'urgency': 'high' if achievement < 80 else 'medium',
                    'actionType': 'email'
                },
                {
                    'title': 'Demand Generation Investment',
                    'description': 'Increase marketing spend 30% in high-performing segments. Focus on intent-based targeting.',
                    'urgency': 'medium',
                    'actionType': 'review'
                }
            ]
        }
        
        actions = recommendations_map.get(kpi_id, [
            {
                'title': 'Performance Review',
                'description': 'Schedule review with team leadership to assess performance and develop action plan.',
                'urgency': urgency,
                'actionType': 'meeting'
            }
        ])
        
        # Add urgency-based priority actions
        if achievement < 85:
            actions.insert(0, {
                'title': 'Executive Escalation',
                'description': f'Critical gap requires executive attention. Schedule immediate strategy session with leadership team.',
                'urgency': 'high',
                'actionType': 'meeting'
            })
        
        return actions[:3]  # Return top 3 actions
    
    def _analyze_root_cause(self, kpi_id: str, achievement: float, change: float, trend_data: List[float] = None) -> str:
        """Provide root cause analysis"""
        
        # Analyze trend if available
        if trend_data and len(trend_data) > 3:
            avg_trend = np.mean(np.diff(trend_data))
            volatility = np.std(trend_data)
            
            if volatility > np.mean(trend_data) * 0.3:
                pattern = "high volatility suggests inconsistent execution or external market factors"
            elif avg_trend > 0:
                pattern = "steady upward trend indicates systematic improvement"
            elif avg_trend < 0:
                pattern = "declining trend signals systemic issues requiring intervention"
            else:
                pattern = "stable performance with minimal variation"
        else:
            pattern = "limited historical data for trend analysis"
        
        root_causes = {
            'won_pipeline': f"Current performance reflects {pattern}. Revenue gaps often stem from deal slippage, longer sales cycles, or competitive losses. Pipeline velocity and close rate are leading indicators.",
            'deals_won': f"Volume performance shows {pattern}. Deal count is influenced by sales capacity, lead quality, and conversion efficiency. SDR productivity and qualification process are key drivers.",
            'ads': f"Deal size metrics indicate {pattern}. ADS reflects customer segment mix and value proposition effectiveness. Enterprise focus increases ADS while SMB volume decreases it.",
            'opps_created': f"Pipeline generation demonstrates {pattern}. Creation rate depends on marketing effectiveness, SDR productivity, and inbound demand quality. Top-of-funnel health predicts future revenue.",
            'active_pipeline': f"Coverage levels show {pattern}. Pipeline sufficiency requires 3x target for healthy attainment. Insufficient coverage increases risk and limits flexibility in deal selection.",
            'close_rate': f"Win rate exhibits {pattern}. Close rate reflects sales effectiveness, product-market fit, and competitive positioning. Rates below 30% suggest qualification or competitive issues.",
            'coverage': f"Coverage ratio displays {pattern}. Healthy coverage (3-4x) provides buffer for deal slippage and enables selective pursuit of best-fit opportunities."
        }
        
        return root_causes.get(kpi_id, f"Performance {pattern}. Continuous monitoring and adjustment based on leading indicators will optimize results.")
    
    def generate_critical_alerts(self, kpis: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate critical alerts and proactive recommendations across all KPIs"""
        
        alerts = []
        
        for kpi in kpis:
            kpi_id = kpi.get('id', '')
            value = kpi.get('value', 0)
            target = kpi.get('target', 1)
            achievement = (value / target * 100) if target > 0 else 0
            
            # Critical alerts (below 85% of target)
            if achievement < 85:
                alerts.append({
                    'kpi': kpi.get('title', kpi_id),
                    'priority': 'critical',
                    'message': f'Currently at {achievement:.0f}% of target - {(100-achievement):.0f}% gap requires immediate action',
                    'impact': f'${(target - value):,.0f} at risk' if 'acv' in kpi_id or 'pipeline' in kpi_id else f'{int(target - value)} units needed',
                    'action': 'Review pipeline, accelerate deals, and increase activity levels immediately',
                    'actionType': 'meeting',
                    'deadline': 'This week'
                })
            
            # High priority (85-95% of target)
            elif achievement < 95:
                alerts.append({
                    'kpi': kpi.get('title', kpi_id),
                    'priority': 'high',
                    'message': f'Tracking at {achievement:.0f}% of target - need {(100-achievement):.0f}% improvement to hit goal',
                    'impact': f'${(target - value):,.0f} gap' if 'acv' in kpi_id or 'pipeline' in kpi_id else f'{int(target - value)} units short',
                    'action': 'Increase focus on this metric with daily check-ins and targeted interventions',
                    'actionType': 'email',
                    'deadline': 'Next 2 weeks'
                })
            
            # Medium priority (95-105% - watch zone)
            elif 95 <= achievement < 105:
                alerts.append({
                    'kpi': kpi.get('title', kpi_id),
                    'priority': 'medium',
                    'message': f'On pace at {achievement:.0f}% - maintain momentum to secure target achievement',
                    'impact': 'On track',
                    'action': 'Continue current execution with weekly monitoring to ensure sustained performance',
                    'actionType': 'review',
                    'deadline': 'Monthly review'
                })
            
            # Low priority (exceeding)
            elif achievement >= 110:
                alerts.append({
                    'kpi': kpi.get('title', kpi_id),
                    'priority': 'low',
                    'message': f'Exceeding target at {achievement:.0f}% - celebrate success and identify replicable practices',
                    'impact': f'+${(value - target):,.0f}' if 'acv' in kpi_id or 'pipeline' in kpi_id else f'+{int(value - target)} above target',
                    'action': 'Document winning strategies and scale to underperforming areas',
                    'actionType': 'review',
                    'deadline': 'End of quarter'
                })
        
        # Sort by priority: critical > high > medium > low
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        alerts.sort(key=lambda x: priority_order.get(x['priority'], 99))
        
        return alerts
