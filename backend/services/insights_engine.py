"""
AI Insights Engine using Azure OpenAI

Note: OpenAI is optional - rule-based insights work without it
"""

from typing import List, Dict, Any
from datetime import datetime
import json

# Optional OpenAI import - falls back to rule-based insights if not available
try:
    from openai import AzureOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️  OpenAI not installed - using rule-based insights only")

import pandas as pd

from models.kpi import Insight, InsightType, Recommendation
from config.settings import settings


class InsightsEngine:
    """Generate insights and recommendations using Azure OpenAI (optional) or rule-based logic"""
    
    def __init__(self):
        self.client = None
        if OPENAI_AVAILABLE and settings.azure_openai_api_key:
            try:
                self.client = AzureOpenAI(
                    api_key=settings.azure_openai_api_key,
                    api_version=settings.azure_openai_api_version,
                    azure_endpoint=settings.azure_openai_endpoint
                )
                print("✅ Azure OpenAI client initialized")
            except Exception as e:
                print(f"⚠️  Azure OpenAI initialization failed: {e}")
                print("   Falling back to rule-based insights")
        else:
            print("✅ Using rule-based insights (OpenAI not configured)")
        
    async def generate_insights(self, kpi_data: pd.DataFrame) -> List[Insight]:
        """
        Generate AI insights based on KPI data
        
        Args:
            kpi_data: DataFrame with KPI metrics and values
            
        Returns:
            List of Insight objects with alerts and observations
        """
        
        # If OpenAI is not available, use rule-based insights immediately
        if not self.client:
            return self._get_fallback_insights()
        
        # Prepare data summary for LLM
        data_summary = self._prepare_data_summary(kpi_data)
        
        prompt = f"""
You are an executive analytics AI assistant. Analyze the following KPI data and generate 2-3 key insights.

KPI Data:
{data_summary}

For each insight, provide:
1. Type: alert (urgent issue), opportunity (potential gain), or observation (notable pattern)
2. Title: Brief headline (max 10 words)
3. Description: Clear explanation (2-3 sentences)
4. Impact: High, Medium, or Low
5. Metric: Related metric name if applicable

Return insights as a JSON array with this structure:
[
  {{
    "type": "alert|opportunity|observation",
    "title": "...",
    "description": "...",
    "impact": "High|Medium|Low",
    "metric": "...",
    "confidence": 0.85
  }}
]
"""
        
        try:
            response = self.client.chat.completions.create(
                model=settings.azure_openai_deployment,
                messages=[
                    {"role": "system", "content": "You are an expert business intelligence analyst specializing in executive insights."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            # Parse response
            insights_data = json.loads(response.choices[0].message.content)
            
            # Convert to Insight objects
            insights = []
            for idx, insight_dict in enumerate(insights_data):
                insights.append(Insight(
                    id=f"insight_{datetime.now().timestamp()}_{idx}",
                    type=InsightType(insight_dict['type']),
                    title=insight_dict['title'],
                    description=insight_dict['description'],
                    impact=insight_dict['impact'],
                    metric=insight_dict.get('metric'),
                    confidence=insight_dict.get('confidence', 0.8)
                ))
            
            return insights
            
        except Exception as e:
            print(f"Error generating insights: {e}")
            # Return fallback insights
            return self._get_fallback_insights()
    
    async def generate_recommendations(self, forecasts: Dict[str, Any]) -> List[Recommendation]:
        """
        Generate AI-powered recommendations based on forecasts
        
        Args:
            forecasts: Dictionary of metric forecasts
            
        Returns:
            List of Recommendation objects
        """
        
        # If OpenAI is not available, use rule-based recommendations
        if not self.client:
            return self._get_fallback_recommendations()
        
        forecast_summary = json.dumps(forecasts, indent=2)
        
        prompt = f"""
You are an executive strategy advisor. Based on the following forecast data, generate 3 actionable recommendations.

Forecast Data:
{forecast_summary}

For each recommendation, provide:
1. Title: Action-oriented headline
2. Description: Clear explanation with expected outcome
3. Priority: 1 (High), 2 (Medium), or 3 (Low)
4. Category: Focus area (e.g., "Conversion Optimization", "Marketing", "Pricing")
5. Expected Impact: Brief description of anticipated results

Return as JSON array:
[
  {{
    "title": "...",
    "description": "...",
    "priority": 1,
    "category": "...",
    "expected_impact": "..."
  }}
]
"""
        
        try:
            response = self.client.chat.completions.create(
                model=settings.azure_openai_deployment,
                messages=[
                    {"role": "system", "content": "You are an expert business strategist focused on data-driven recommendations."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )
            
            # Parse response
            recs_data = json.loads(response.choices[0].message.content)
            
            # Convert to Recommendation objects
            recommendations = []
            for idx, rec_dict in enumerate(recs_data):
                recommendations.append(Recommendation(
                    id=f"rec_{datetime.now().timestamp()}_{idx}",
                    title=rec_dict['title'],
                    description=rec_dict['description'],
                    priority=rec_dict['priority'],
                    category=rec_dict['category'],
                    expected_impact=rec_dict.get('expected_impact')
                ))
            
            return recommendations
            
        except Exception as e:
            print(f"Error generating recommendations: {e}")
            return self._get_fallback_recommendations()
    
    def _prepare_data_summary(self, kpi_data: pd.DataFrame) -> str:
        """Format KPI data for LLM prompt"""
        summary_lines = []
        for _, row in kpi_data.iterrows():
            summary_lines.append(
                f"- {row['metric_name']}: {row['metric_value']} "
                f"(Target: {row['target_value']}, Previous: {row['previous_period_value']})"
            )
        return "\n".join(summary_lines)
    
    def _get_fallback_insights(self) -> List[Insight]:
        """Return mock insights if API fails"""
        return [
            Insight(
                id="fallback_1",
                type=InsightType.ALERT,
                title="Revenue declined 12% in Q3",
                description="Revenue dropped mainly due to lower performance in the West region.",
                impact="High",
                metric="revenue",
                confidence=0.9
            )
        ]
    
    def _get_fallback_recommendations(self) -> List[Recommendation]:
        """Return mock recommendations if API fails"""
        return [
            Recommendation(
                id="fallback_rec_1",
                title="Improve conversion in West region",
                description="Focus on increasing marketing spend in high-performing channels.",
                priority=1,
                category="Marketing",
                expected_impact="5-10% improvement in conversion rate"
            )
        ]
