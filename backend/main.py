"""
Atlas Executive Insights - Backend API
FastAPI application serving KPI data, forecasts, and AI insights
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from datetime import datetime, timedelta
from typing import List, Dict, Any
from pathlib import Path
import uvicorn
import os

from config.settings import settings
from services.data_fetcher import DataFetcher  # Direct Databricks connection (live queries)
from services.forecasting import ForecastingService
from services.insights_engine import InsightsEngine
from services.metrics import MetricsCalculator
from models.kpi import KPICard, ChartData, Insight, Forecast

app = FastAPI(
    title="Atlas Executive Insights API",
    description="AI-powered executive analytics backend - LIVE Databricks",
    version="0.3.0"
)

# CORS configuration for React frontend and Databricks Apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services with DIRECT Databricks connection
data_fetcher = DataFetcher()
forecasting_service = ForecastingService()
insights_engine = InsightsEngine()
metrics_calculator = MetricsCalculator()

# Serve static frontend files in production
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists() and settings.environment == "production":
    app.mount("/static", StaticFiles(directory=str(frontend_dist / "assets")), name="static")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve frontend files for production deployment"""
        # API routes are handled by FastAPI
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        
        # Serve index.html for all other routes (SPA routing)
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend not built")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Atlas Executive Insights API",
        "status": "running",
        "version": "0.3.0",
        "timestamp": datetime.now().isoformat(),
        "mode": "direct_databricks",
        "environment": settings.environment,
        "deployed_in_databricks": os.getenv("DATABRICKS_HOST") is not None
    }


@app.get("/api/filters")
async def get_available_filters():
    """
    Get all available filter dimensions and their values
    Returns filter options for Geography, Channel, and Product
    """
    return {
        "geo": [
            {"label": "All Regions", "value": "All"},
            {"label": "Americas (AMER)", "value": "AMER"},
            {"label": "Europe, Middle East & Africa (EMEA)", "value": "EMEA"},
            {"label": "Asia Pacific (APAC)", "value": "APAC"},
            {"label": "Latin America (LATAM)", "value": "LATAM"}
        ],
        "channel": [
            {"label": "All Channels", "value": "All"},
            {"label": "Enterprise", "value": "Enterprise"},
            {"label": "SMB", "value": "SMB"},
            {"label": "Partner", "value": "Partner"},
            {"label": "Strategic", "value": "Strategic"}
        ],
        "product": [
            {"label": "All Products", "value": "All"},
            {"label": "Connect", "value": "Connect"},
            {"label": "Engage", "value": "Engage"},
            {"label": "Rescue", "value": "Rescue"},
            {"label": "Central", "value": "Central"},
            {"label": "Resolve", "value": "Resolve"}
        ]
    }


@app.get("/api/kpis", response_model=List[KPICard])
async def get_kpis(
    start_date: str = None, 
    end_date: str = None,
    geo: str = "All",
    channel: str = "All",
    product: str = "All"
):
    """
    Get KPI cards with current values, trends, and comparisons
    
    Args:
        start_date: Start date for period (ISO format)
        end_date: End date for period (ISO format)
        geo: Geography filter (AMER, EMEA, APAC, LATAM, or All)
        channel: Channel filter (Enterprise, SMB, Partner, Strategic, or All)
        product: Product filter (Connect, Engage, Rescue, Central, Resolve, or All)
    """
    try:
        # Build filter context
        filters = {
            "geo": geo,
            "channel": channel,
            "product": product
        }
        
        # Fetch raw data from database with filters
        raw_data = await data_fetcher.fetch_kpi_data(start_date, end_date, filters)
        
        # Calculate KPI metrics
        kpis = metrics_calculator.calculate_kpis(raw_data)
        
        return kpis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching KPIs: {str(e)}")


@app.get("/api/charts/{chart_type}")
async def get_chart_data(chart_type: str, start_date: str = None, end_date: str = None):
    """
    Get chart data for descriptive analytics
    
    Args:
        chart_type: Type of chart (revenue_by_region, monthly_trend, etc.)
        start_date: Start date for period
        end_date: End date for period
    """
    try:
        raw_data = await data_fetcher.fetch_chart_data(chart_type, start_date, end_date)
        chart_data = metrics_calculator.prepare_chart_data(chart_type, raw_data)
        
        return chart_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching chart data: {str(e)}")


@app.get("/api/insights", response_model=List[Insight])
async def get_ai_insights():
    """
    Get AI-generated insights and alerts based on current data
    Uses Azure OpenAI to analyze trends and generate recommendations
    """
    try:
        # Fetch latest KPI data
        kpi_data = await data_fetcher.fetch_kpi_data()
        
        # Generate insights using Azure OpenAI
        insights = await insights_engine.generate_insights(kpi_data)
        
        return insights
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating insights: {str(e)}")


@app.get("/api/forecast", response_model=Forecast)
async def get_forecast(metric: str, periods: int = 90):
    """
    Get ML-based forecast for a specific metric
    
    Args:
        metric: Metric to forecast (revenue, sales_growth, etc.)
        periods: Number of days to forecast ahead
    """
    try:
        # Fetch historical data
        historical_data = await data_fetcher.fetch_historical_data(metric)
        
        # Generate forecast using Prophet/scikit-learn
        forecast = forecasting_service.forecast(metric, historical_data, periods)
        
        return forecast
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating forecast: {str(e)}")


@app.get("/api/recommendations")
async def get_recommendations():
    """
    Get AI-powered recommendations based on forecasts and current trends
    """
    try:
        # Fetch forecasts for key metrics
        forecasts = await forecasting_service.get_all_forecasts()
        
        # Generate recommendations using Azure OpenAI
        recommendations = await insights_engine.generate_recommendations(forecasts)
        
        return recommendations
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


@app.get("/api/arr/forecast", response_model=Forecast)
async def get_arr_forecast(periods: int = 90):
    """
    Get ARR (Annual Recurring Revenue) forecast
    
    Args:
        periods: Number of days to forecast ahead (default: 90)
        
    Returns:
        Forecast with historical ARR data and future predictions
    """
    try:
        # Fetch ARR historical data from partner_ending_arr table
        historical_data = await data_fetcher.fetch_historical_data('arr')
        
        if historical_data.empty:
            raise HTTPException(status_code=404, detail="No ARR historical data available")
        
        # Generate forecast
        forecast = forecasting_service.forecast('arr', historical_data, periods)
        
        return forecast
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error forecasting ARR: {str(e)}")


@app.get("/api/arr/segments")
async def get_arr_by_segment(segment_type: str = 'product_genus'):
    """
    Get ARR segmented by product, channel, or market
    
    Args:
        segment_type: Type of segmentation (product_genus, product_family, sales_channel, sales_market)
        
    Returns:
        ARR data broken down by the specified segment
    """
    try:
        arr_data = await data_fetcher.fetch_arr_by_segment(segment_type)
        
        if arr_data.empty:
            return {"segments": [], "message": "No ARR segment data available"}
        
        # Transform to JSON-friendly format
        result = {
            "segment_type": segment_type,
            "data": arr_data.to_dict(orient='records'),
            "total_arr": float(arr_data['arr_value'].sum())
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ARR segments: {str(e)}")


@app.get("/api/arr/history")
async def get_arr_history():
    """
    Get historical ARR data (last 365 days)
    
    Returns:
        Historical ARR trends over the past year
    """
    try:
        historical_data = await data_fetcher.fetch_historical_data('arr')
        
        if historical_data.empty:
            return {"history": [], "message": "No ARR historical data available"}
        
        # Calculate month-over-month growth
        historical_data['growth_pct'] = historical_data['y'].pct_change() * 100
        
        # Clean NaN and Inf values before JSON serialization
        historical_data = historical_data.replace([float('inf'), float('-inf')], 0.0)
        historical_data = historical_data.fillna(0.0)
        
        result = {
            "data": historical_data.to_dict(orient='records'),
            "latest_arr": float(historical_data['y'].iloc[-1]) if not historical_data.empty else 0,
            "avg_monthly_growth": float(historical_data['growth_pct'].mean()) if len(historical_data) > 1 else 0
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching ARR history: {str(e)}")


@app.get("/api/forecasts/all")
async def get_all_forecasts(periods: int = 90):
    """
    Get forecasts for all key metrics (ARR, won pipeline, active pipeline, created pipeline)
    
    Args:
        periods: Number of days to forecast ahead (default: 90)
        
    Returns:
        Dictionary of forecasts for all metrics
    """
    try:
        forecasts = await forecasting_service.get_all_forecasts(periods)
        
        # Convert Forecast objects to dict for JSON serialization
        result = {}
        for metric_name, forecast in forecasts.items():
            result[metric_name] = {
                "metric": forecast.metric,
                "historical": [{"date": p.date, "value": p.value} for p in forecast.historical],
                "forecast": [
                    {
                        "date": p.date,
                        "value": p.value,
                        "lower_bound": p.lower_bound,
                        "upper_bound": p.upper_bound
                    } for p in forecast.forecast
                ],
                "accuracy": forecast.accuracy,
                "confidence_interval": forecast.confidence_interval
            }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating forecasts: {str(e)}")


@app.get("/api/forecast/prophet")
async def get_prophet_forecast_data(segment_by: str = None):
    """
    Get Prophet forecast data with actuals and scenarios from forecast_prophet table
    
    Args:
        segment_by: Optional segmentation (product, sales_market, pe_account_flag)
        
    Returns:
        DataFrame with actual ARR, forecast scenarios, and metrics
    """
    try:
        data = await data_fetcher.fetch_prophet_forecast_data(segment_by)
        
        if data.empty:
            return {"data": [], "message": "No Prophet forecast data available"}
        
        # Calculate summary statistics
        latest_actuals = float(data[data['actual_arr'].notna()]['actual_arr'].sum()) if not data[data['actual_arr'].notna()].empty else 0
        latest_forecast = float(data['forecast_most_likely'].sum())
        
        result = {
            "data": data.to_dict(orient='records'),
            "summary": {
                "latest_actuals": latest_actuals,
                "latest_forecast": latest_forecast,
                "best_case": float(data['forecast_best_case'].sum()),
                "worst_case": float(data['forecast_worst_case'].sum()),
                "avg_deal_size": float(data['avg_deal_size'].mean()) if 'avg_deal_size' in data else None,
                "avg_sales_cycle": float(data['avg_sales_cycle'].mean()) if 'avg_sales_cycle' in data else None
            }
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Prophet forecast: {str(e)}")


@app.get("/api/forecast/scenarios")
async def get_forecast_scenarios(metric: str = "arr", periods: int = 90):
    """
    Get best case, most likely, and worst case forecast scenarios
    
    Args:
        metric: Metric to forecast (arr, won_pipeline, etc.)
        periods: Number of days to forecast
        
    Returns:
        Three scenario forecasts with confidence intervals
    """
    try:
        # Fetch historical data
        historical_data = await data_fetcher.fetch_historical_data(metric)
        
        if historical_data.empty:
            raise HTTPException(status_code=404, detail=f"No historical data for metric: {metric}")
        
        # Generate forecast with Prophet (provides confidence intervals)
        base_forecast = forecasting_service.forecast(metric, historical_data, periods)
        
        # Extract scenarios from confidence intervals
        scenarios = {
            "metric": metric,
            "most_likely": [
                {"date": p.date, "value": p.value} 
                for p in base_forecast.forecast
            ],
            "best_case": [
                {"date": p.date, "value": p.upper_bound if p.upper_bound else p.value * 1.15} 
                for p in base_forecast.forecast
            ],
            "worst_case": [
                {"date": p.date, "value": p.lower_bound if p.lower_bound else p.value * 0.85} 
                for p in base_forecast.forecast
            ],
            "accuracy": base_forecast.accuracy,
            "confidence_interval": base_forecast.confidence_interval
        }
        
        return scenarios
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating scenarios: {str(e)}")


@app.get("/api/forecast/models")
async def get_available_models():
    """
    Get list of available forecasting models with descriptions
    
    Returns:
        Dictionary of model names and descriptions
    """
    return forecasting_service.AVAILABLE_MODELS


@app.get("/api/forecast/compare")
async def compare_forecast_models(metric: str = "arr"):
    """
    Compare accuracy of all forecasting models on historical data
    
    Args:
        metric: Metric to evaluate models on
        
    Returns:
        Comparison of model accuracies with MAPE, RMSE, MAE metrics
    """
    try:
        historical_data = await data_fetcher.fetch_historical_data(metric)
        
        if historical_data.empty or len(historical_data) < 60:
            raise HTTPException(status_code=400, detail="Insufficient historical data for model comparison (need 60+ days)")
        
        comparison = forecasting_service.get_model_comparison(metric, historical_data)
        
        # Add recommendations
        best_model = min(comparison.keys(), key=lambda k: comparison[k].get('mape', 1000) if 'mape' in comparison[k] else 1000)
        
        return {
            "metric": metric,
            "models": comparison,
            "recommended": best_model,
            "recommendation_reason": f"{comparison[best_model].get('accuracy', 0)}% accuracy on historical data"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing models: {str(e)}")


@app.get("/api/forecast/advanced")
async def get_advanced_forecast(
    metric: str = "arr", 
    periods: int = 90,
    model: str = "ensemble"
):
    """
    Advanced forecast with model selection
    
    Args:
        metric: Metric to forecast
        periods: Number of days to forecast
        model: Forecasting model to use ('prophet', 'arima', 'exponential', 'ensemble', 'linear')
        
    Returns:
        Forecast with selected model including accuracy metrics
    """
    try:
        historical_data = await data_fetcher.fetch_historical_data(metric)
        
        if historical_data.empty:
            raise HTTPException(status_code=404, detail=f"No historical data for metric: {metric}")
        
        # Generate forecast with selected model
        forecast_result = forecasting_service.forecast(metric, historical_data, periods, model=model)
        
        return {
            "metric": metric,
            "model": model,
            "historical": [{"date": p.date, "value": p.value} for p in forecast_result.historical[-90:]],  # Last 90 days
            "forecast": [
                {
                    "date": p.date,
                    "value": p.value,
                    "lower_bound": p.lower_bound if p.lower_bound else p.value * 0.85,
                    "upper_bound": p.upper_bound if p.upper_bound else p.value * 1.15
                } 
                for p in forecast_result.forecast
            ],
            "accuracy": forecast_result.accuracy,
            "confidence_interval": forecast_result.confidence_interval,
            "model_description": forecasting_service.AVAILABLE_MODELS.get(model, "Unknown model")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating advanced forecast: {str(e)}")


@app.get("/api/forecast/win-probability")
async def get_win_probability():
    """
    Get opportunity win probability data from ML model
    
    Returns:
        Win probability by product, market, and stage with weighted pipeline
    """
    try:
        data = await data_fetcher.fetch_win_probability_data()
        
        if data.empty:
            return {"data": [], "message": "No win probability data available"}
        
        # Calculate weighted averages
        total_pipeline = float(data['total_pipeline_value'].sum())
        total_weighted = float(data['weighted_pipeline'].sum())
        overall_win_prob = total_weighted / total_pipeline if total_pipeline > 0 else 0
        
        result = {
            "data": data.to_dict(orient='records'),
            "summary": {
                "total_pipeline_value": total_pipeline,
                "total_weighted_pipeline": total_weighted,
                "overall_win_probability": overall_win_prob,
                "total_opportunities": int(data['opportunity_count'].sum())
            }
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching win probability: {str(e)}")


@app.get("/api/forecast/accuracy")
async def get_forecast_accuracy():
    """
    Get forecast accuracy metrics using 2024 baseline data
    
    Returns:
        Forecast vs actuals comparison with accuracy percentages
    """
    try:
        data = await data_fetcher.fetch_forecast_accuracy_2024()
        
        if data.empty:
            return {"data": [], "message": "No forecast accuracy data available"}
        
        # Calculate overall accuracy metrics
        total_actual = float(data['actual_value'].sum())
        total_forecast = float(data['forecast_value'].sum())
        overall_error_pct = abs(total_forecast - total_actual) / total_actual * 100 if total_actual > 0 else 0
        
        # Calculate MAPE (Mean Absolute Percentage Error)
        data['abs_pct_error'] = abs((data['forecast_value'] - data['actual_value']) / data['actual_value']) * 100
        mape = float(data['abs_pct_error'].mean())
        
        result = {
            "data": data.to_dict(orient='records'),
            "summary": {
                "total_actual": total_actual,
                "total_forecast": total_forecast,
                "overall_error_pct": overall_error_pct,
                "mape": mape,
                "accuracy": max(0, 100 - mape),
                "forecast_bias": "over" if total_forecast > total_actual else "under"
            }
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating forecast accuracy: {str(e)}")


# ============================================================================
# ENHANCED AI INSIGHTS ENDPOINTS
# ============================================================================

@app.get("/api/insights/kpi/{kpi_id}")
async def get_kpi_insights(kpi_id: str):
    """
    Get detailed AI-powered insights for a specific KPI
    
    Returns:
        - Natural language summary
        - What's working / what needs attention
        - Demographic performance breakdown
        - Actionable recommendations
        - Root cause analysis
    """
    try:
        from services.enhanced_insights_v2 import EnhancedInsightsEngineV2
        insights_engine = EnhancedInsightsEngineV2()
        
        # Fetch KPI data (in production, get from database)
        # For now, using demo data
        kpi_data = {
            'won_pipeline': {'current': 4000000, 'target': 20400000, 'previous': 3700000},
            'won_volume': {'current': 1662, 'target': 7076, 'previous': 1500},
            'ads': {'current': 2390, 'target': 2887, 'previous': 2300},
            'opps_created': {'current': 4022, 'target': 17414, 'previous': 3800},
            'created_pipeline': {'current': 18700000, 'target': 88300000, 'previous': 17000000},
            'active_pipeline': {'current': 12000000, 'target': 10000000, 'previous': 11400000},
            'close_rate': {'current': 31.8, 'target': 30.0, 'previous': 31.3},
            'coverage': {'current': 320, 'target': 300, 'previous': 310}
        }
        
        if kpi_id not in kpi_data:
            raise HTTPException(status_code=404, detail=f"KPI {kpi_id} not found")
        
        data = kpi_data[kpi_id]
        insights = insights_engine.generate_kpi_insights(
            kpi_id=kpi_id,
            current_value=data['current'],
            target=data['target'],
            previous_value=data['previous']
        )
        
        return insights
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating insights: {str(e)}")


@app.get("/api/insights/alerts")
async def get_critical_alerts():
    """
    Get critical alerts and actionable recommendations across all KPIs
    
    Returns:
        List of prioritized alerts with:
        - Priority level (critical/high/medium/low)
        - KPI affected
        - Message and impact
        - Recommended action
        - Action type and deadline
    """
    try:
        from services.enhanced_insights import EnhancedInsightsEngine
        insights_engine = EnhancedInsightsEngine()
        
        # Get current KPIs (in production, fetch from database)
        kpis = [
            {'id': 'won_acv', 'title': 'Won ACV', 'value': 2450000, 'target': 2000000},
            {'id': 'deals_won', 'title': 'Deals Won', 'value': 78, 'target': 70},
            {'id': 'ads', 'title': 'Average Deal Size', 'value': 31410, 'target': 28000},
            {'id': 'opps_created', 'title': 'Opportunities Created', 'value': 245, 'target': 220},
            {'id': 'created_pipeline', 'title': 'Created Pipeline', 'value': 8500000, 'target': 7500000},
            {'id': 'active_pipeline', 'title': 'Active Pipeline', 'value': 12000000, 'target': 10000000},
            {'id': 'close_rate', 'title': 'Close Rate', 'value': 31.8, 'target': 30.0},
            {'id': 'coverage', 'title': 'Coverage', 'value': 320, 'target': 300}
        ]
        
        alerts = insights_engine.generate_critical_alerts(kpis)
        
        return alerts
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating alerts: {str(e)}")


@app.get("/api/forecast/insights")
async def get_forecast_insights(metric: str = 'arr', model: str = 'ensemble'):
    """
    Get AI-powered insights for forecast predictions
    
    Args:
        metric: Metric being forecasted (arr, won_pipeline, etc.)
        model: Forecast model used
        
    Returns:
        - Summary of forecast trend
        - Risk assessment
        - Confidence level
        - Key drivers
        - Recommendations
        - Risks and opportunities
    """
    try:
        # Fetch forecast data to analyze
        historical_data = await data_fetcher.fetch_historical_data(metric)
        
        # Generate forecast
        forecast = forecasting_service.forecast(metric, historical_data, 90, model)
        
        # Analyze forecast
        insights = _analyze_forecast_insights(forecast, metric, model)
        
        return insights
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating forecast insights: {str(e)}")


def _analyze_forecast_insights(forecast, metric: str, model: str) -> Dict[str, Any]:
    """Analyze forecast data and generate AI insights"""
    
    # Calculate trend
    if len(forecast.forecast) > 0 and len(forecast.historical) > 0:
        historical_avg = sum(p.value for p in forecast.historical[-30:]) / 30
        forecast_avg = sum(p.value for p in forecast.forecast[:30]) / 30
        growth_rate = ((forecast_avg - historical_avg) / historical_avg) * 100
        
        if growth_rate > 5:
            trend = "accelerating"
            trend_desc = f"growing at {growth_rate:.1f}% above historical baseline"
        elif growth_rate < -5:
            trend = "decelerating"
            trend_desc = f"declining {abs(growth_rate):.1f}% below historical baseline"
        else:
            trend = "stable"
            trend_desc = f"maintaining steady growth near {growth_rate:+.1f}%"
    else:
        trend = "stable"
        trend_desc = "maintaining current trajectory"
    
    # Risk assessment
    if forecast.accuracy >= 0.90:
        risk = "low"
        confidence = min(95, int(forecast.accuracy * 100))
    elif forecast.accuracy >= 0.75:
        risk = "medium"
        confidence = int(forecast.accuracy * 100)
    else:
        risk = "high"
        confidence = max(60, int(forecast.accuracy * 100))
    
    # Generate summary
    summary = f"Forecast shows {trend_desc}. {model.capitalize()} model predicts next 90 days with {confidence}% confidence."
    
    # Key drivers
    drivers = [
        f"Historical {metric.replace('_', ' ')} trend strongly influences forward projections",
        f"{model.capitalize()} model captures seasonal patterns and growth trajectory",
        "Current quarter performance aligns with model assumptions"
    ]
    
    # Recommendations
    recommendations = []
    if trend == "accelerating":
        recommendations = [
            "Allocate additional resources to capitalize on growth momentum",
            "Review capacity planning to ensure ability to support projected increase",
            "Consider accelerating strategic initiatives while trend is positive"
        ]
    elif trend == "decelerating":
        recommendations = [
            "Investigate root causes of deceleration immediately",
            "Implement corrective actions to reverse downward trend",
            "Review and adjust sales/marketing strategies"
        ]
    else:
        recommendations = [
            "Maintain current execution strategy while monitoring for changes",
            "Look for opportunities to accelerate growth above baseline",
            "Continue regular performance reviews to catch early trend shifts"
        ]
    
    # Risks
    risks = []
    if risk == "high" or risk == "medium":
        risks = [
            "Historical data volatility reduces forecast reliability",
            "External market factors may impact actual performance",
            "Model assumptions may not hold in changing conditions"
        ]
    else:
        risks = [
            "Unexpected market disruptions could alter trajectory",
            "Seasonal variations may differ from historical patterns"
        ]
    
    # Opportunities
    opportunities = []
    if trend == "accelerating" or trend == "stable":
        opportunities = [
            "Strong fundamentals support additional investment",
            "Consistent performance enables strategic planning",
            "Positive momentum can be leveraged for expansion"
        ]
    else:
        opportunities = [
            "Course correction opportunity before significant impact",
            "Early warning enables proactive management",
            "Trend reversal can demonstrate agility and responsiveness"
        ]
    
    return {
        "summary": summary,
        "trend": trend,
        "risk": risk,
        "confidence": confidence,
        "drivers": drivers,
        "recommendations": recommendations[:3],
        "risks": risks[:3],
        "opportunities": opportunities[:3],
        "model": model,
        "metric": metric
    }


if __name__ == "__main__":
    # Use PORT environment variable (for Databricks Apps) or default to 8000
    port = int(os.getenv("PORT", "8000"))
    # Reload only in development
    reload = settings.environment == "development"
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=reload
    )
