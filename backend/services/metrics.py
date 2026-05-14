"""
Metrics calculator - transforms raw data into KPI cards and chart data
"""

from typing import List, Dict, Any
import pandas as pd
import numpy as np

from models.kpi import KPICard, TrendDirection, ChartData


class MetricsCalculator:
    """Calculate KPIs and prepare chart data from raw database queries"""
    
    def calculate_kpis(self, raw_data: pd.DataFrame) -> List[KPICard]:
        """
        Transform raw KPI data into KPICard objects
        
        Args:
            raw_data: DataFrame with columns [metric_name, metric_value, target_value, previous_period_value]
            
        Returns:
            List of KPICard objects
        """
        
        kpi_cards = []
        
        for _, row in raw_data.iterrows():
            # Calculate change percentage
            if row['previous_period_value'] > 0:
                change_pct = ((row['metric_value'] - row['previous_period_value']) 
                             / row['previous_period_value'] * 100)
            else:
                change_pct = 0
            
            # Determine trend direction
            if change_pct > 1:
                trend = TrendDirection.UP
            elif change_pct < -1:
                trend = TrendDirection.DOWN
            else:
                trend = TrendDirection.FLAT
            
            # Generate mock sparkline data (replace with actual historical data)
            trend_data = self._generate_sparkline(row['metric_value'], 10)
            
            # Determine unit and formatting
            unit, formatted_value = self._format_value(row['metric_name'], row['metric_value'])
            _, formatted_target = self._format_value(row['metric_name'], row['target_value'])
            
            # Calculate target achievement percentage
            target_achievement = (row['metric_value'] / row['target_value'] * 100) if row['target_value'] > 0 else 0
            
            kpi_card = KPICard(
                id=row['metric_name'],
                title=self._format_metric_name(row['metric_name']),
                value=formatted_value,
                unit=unit,
                target=formatted_target,
                change_percent=round(change_pct, 1),
                change_direction=trend,
                vs_last_period="vs last period",
                trend_data=trend_data,
                icon=self._get_icon(row['metric_name']),
                targetAchievement=round(target_achievement, 1)
            )
            
            kpi_cards.append(kpi_card)
        
        return kpi_cards
    
    def prepare_chart_data(self, chart_type: str, raw_data: pd.DataFrame) -> ChartData:
        """
        Transform raw data into chart-ready format
        
        Args:
            chart_type: Type of chart (revenue_by_region, monthly_trend, etc.)
            raw_data: DataFrame from database query
            
        Returns:
            ChartData object ready for frontend
        """
        
        if chart_type == "revenue_by_region":
            return self._prepare_revenue_by_region(raw_data)
        elif chart_type == "monthly_trend":
            return self._prepare_monthly_trend(raw_data)
        else:
            return ChartData(
                chart_type="bar",
                title="Unknown Chart",
                labels=[],
                datasets=[]
            )
    
    def _prepare_revenue_by_region(self, raw_data: pd.DataFrame) -> ChartData:
        """Prepare revenue by region bar chart"""
        return ChartData(
            chart_type="bar",
            title="Revenue by Region",
            labels=raw_data['region'].tolist(),
            datasets=[{
                "label": "Revenue",
                "data": raw_data['total_revenue'].tolist(),
                "backgroundColor": "#4F46E5"
            }]
        )
    
    def _prepare_monthly_trend(self, raw_data: pd.DataFrame) -> ChartData:
        """Prepare monthly trend line chart"""
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        labels = [month_names[int(m)-1] for m in raw_data['month']]
        
        return ChartData(
            chart_type="line",
            title="Monthly Trend (Revenue)",
            labels=labels,
            datasets=[{
                "label": "Revenue",
                "data": raw_data['revenue'].tolist(),
                "borderColor": "#4F46E5",
                "fill": True,
                "backgroundColor": "rgba(79, 70, 229, 0.1)"
            }]
        )
    
    def _format_metric_name(self, metric_name: str) -> str:
        """Convert metric_name to human-readable title"""
        name_map = {
            'won_pipeline': 'Won ACV $',
            'won_volume': '# of Deals Won',
            'ads': 'Average Deal Size',
            'opps_created': '# of Opps Created',
            'created_pipeline': 'Created Pipeline $',
            'active_pipeline': 'Active Pipeline $',
            'close_rate': 'Close Rate',
            'coverage': 'Coverage',
            # Legacy names for backwards compatibility
            'revenue': 'Total Revenue',
            'sales_growth': 'Sales Growth',
            'gross_margin': 'Gross Margin',
            'win_rate': 'Deal Win Rate',
            'customer_acquisition_cost': 'Customer Acquisition Cost'
        }
        return name_map.get(metric_name, metric_name.replace('_', ' ').title())
    
    def _format_value(self, metric_name: str, value: float) -> tuple:
        """
        Format value with appropriate unit
        Returns: (unit, formatted_value)
        """
        if metric_name in ['won_pipeline', 'created_pipeline', 'active_pipeline', 'revenue', 'customer_acquisition_cost']:
            # Currency - convert to millions
            if value >= 1_000_000:
                return "M", round(value / 1_000_000, 1)
            elif value >= 1_000:
                return "K", round(value / 1_000, 1)
            else:
                return "$", round(value, 2)
        elif metric_name in ['close_rate', 'coverage', 'sales_growth', 'gross_margin', 'win_rate']:
            # Percentage
            return "%", round(value, 1)
        else:
            # Plain number (counts)
            return "", int(value)
    
    def _get_icon(self, metric_name: str) -> str:
        """Get icon identifier for metric"""
        icon_map = {
            'won_pipeline': 'dollar',
            'won_volume': 'trending-up',
            'ads': 'dollar',
            'opps_created': 'activity',
            'created_pipeline': 'dollar',
            'active_pipeline': 'dollar',
            'close_rate': 'percent',
            'coverage': 'target',
            # Legacy
            'revenue': 'dollar',
            'sales_growth': 'trending-up',
            'gross_margin': 'percent',
            'win_rate': 'target',
            'customer_acquisition_cost': 'user-plus'
        }
        return icon_map.get(metric_name, 'bar-chart')
    
    def _generate_sparkline(self, current_value: float, points: int = 10) -> List[float]:
        """
        Generate mock sparkline data around current value
        
        TODO: Replace with actual historical data
        """
        base = current_value * 0.9
        trend = (current_value - base) / points
        noise = current_value * 0.05
        
        sparkline = []
        for i in range(points):
            value = base + (i * trend) + np.random.uniform(-noise, noise)
            sparkline.append(round(value, 2))
        
        return sparkline
