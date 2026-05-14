"""
Data models for KPIs, insights, and forecasts
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TrendDirection(str, Enum):
    """Trend direction indicator"""
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class KPICard(BaseModel):
    """KPI card displayed at the top of dashboard"""
    id: str
    title: str
    value: float
    unit: str = ""  # $, %, units, etc.
    target: float = 0  # Target value for this KPI
    change_percent: float
    change_direction: TrendDirection
    vs_last_period: str = "vs last period"
    trend_data: List[float] = []  # Mini sparkline data
    icon: str = ""  # Icon identifier
    targetAchievement: float = 0  # Target achievement percentage


class ChartData(BaseModel):
    """Generic chart data structure"""
    chart_type: str  # bar, line, area, etc.
    title: str
    labels: List[str]
    datasets: List[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]] = None


class InsightType(str, Enum):
    """Type of AI insight"""
    ALERT = "alert"
    OPPORTUNITY = "opportunity"
    RECOMMENDATION = "recommendation"
    OBSERVATION = "observation"


class Insight(BaseModel):
    """AI-generated insight or alert"""
    id: str
    type: InsightType
    title: str
    description: str
    impact: str  # High, Medium, Low
    metric: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    generated_at: datetime = Field(default_factory=datetime.now)


class ForecastPoint(BaseModel):
    """Single point in forecast"""
    date: str
    value: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None


class Forecast(BaseModel):
    """ML-based forecast for a metric"""
    metric: str
    historical: List[ForecastPoint]
    forecast: List[ForecastPoint]
    accuracy: float = Field(ge=0, le=1)  # Model accuracy score
    confidence_interval: float = 0.95
    generated_at: datetime = Field(default_factory=datetime.now)


class Recommendation(BaseModel):
    """AI-powered recommendation"""
    id: str
    title: str
    description: str
    priority: int = Field(ge=1, le=3)  # 1=High, 2=Medium, 3=Low
    category: str
    expected_impact: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.now)
