"""Backend Data Models

Data models and schemas for the Executive Insights application.
"""

from .kpi import KPICard, ChartData, Insight, Forecast, Recommendation

__all__ = ['KPICard', 'ChartData', 'Insight', 'Forecast', 'Recommendation']
