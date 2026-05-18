"""
Atlas Executive Insights - Backend API
FastAPI application serving KPI data, forecasts, and AI insights
"""

import logging
import os
import signal
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from datetime import datetime, timedelta
from typing import List, Dict, Any
from pathlib import Path
import uvicorn

import pandas as pd
from config.settings import settings
from services.data_fetcher import DataFetcher  # Direct Databricks connection (live queries)
from services.gaim_data_service import GAIMDataService  # GAIM-specific KPI queries with exact formulas
from services.data_cache import data_cache             # In-memory TTL cache (15-min refresh)
from services.forecasting import ForecastingService
from services.insights_engine import InsightsEngine
from services.metrics import MetricsCalculator
from services.genie_service import GenieService  # AI-powered insights from Genie
from routes.genie import router as genie_router
from routes.insights import router as insights_router
from routes.mql import router as mql_router
from routes.pipeline_segments import router as pipeline_segments_router
from routes.deal_bands import router as deal_bands_router
from routes.coverage import router as coverage_router
from routes.deals import router as deals_router
from routes.forecast import router as forecast_router
from models.kpi import KPICard, ChartData, Insight, Forecast

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Atlas Executive Insights API",
    description="AI-powered executive analytics backend - LIVE Databricks",
    version="0.3.0"
)

# ── Graceful shutdown (Databricks Apps sends SIGTERM before SIGKILL) ──────────
def _sigterm_handler(signum, frame):
    logger.info("SIGTERM received — shutting down gracefully.")
    sys.exit(0)

signal.signal(signal.SIGTERM, _sigterm_handler)

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
gaim_service = GAIMDataService()  # Primary KPI service — exact GAIM formulas + real targets
forecasting_service = ForecastingService()
insights_engine = InsightsEngine()
metrics_calculator = MetricsCalculator()
genie_service = GenieService()  # AI-powered insights

# Mount routers
app.include_router(genie_router)
app.include_router(insights_router)
app.include_router(mql_router)
app.include_router(pipeline_segments_router)
app.include_router(deal_bands_router)
app.include_router(coverage_router)
app.include_router(deals_router)
app.include_router(forecast_router)


@app.get("/api/health")
async def health_check():
    """API health check endpoint — DB ping runs in a thread with a 5s timeout."""
    import asyncio
    connection_status = "unknown"
    connection_error  = None

    def _ping():
        with data_fetcher.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 as test")
                cursor.fetchall()

    try:
        if data_fetcher.use_databricks:
            await asyncio.wait_for(asyncio.to_thread(_ping), timeout=5.0)
            connection_status = "healthy"
        else:
            connection_status = "mock_mode"
    except asyncio.TimeoutError:
        connection_status = "timeout"
        connection_error  = "DB ping exceeded 5 s — Databricks may be cold-starting"
    except Exception as e:
        connection_status = "error"
        connection_error  = str(e)

    
    return {
        "service": "Atlas Executive Insights API",
        "status": "running",
        "version": "0.3.0",
        "timestamp": datetime.now().isoformat(),
        "mode": "direct_databricks" if data_fetcher.use_databricks else "mock",
        "environment": settings.environment,
        "deployed_in_databricks": os.getenv("DATABRICKS_HOST") is not None,
        "databricks_connection": connection_status,
        "connection_error": connection_error,
        "databricks_host": settings.databricks_server_hostname[:50] if settings.databricks_server_hostname else "not set",
        "has_token": bool(os.getenv("DATABRICKS_TOKEN")),
        "catalog": settings.databricks_catalog,
        "schema": settings.databricks_schema
    }


@app.get("/api/filters")
async def get_available_filters():
    """
    Get all available filter dimensions and their values.
    Values must exactly match the GAIM Databricks table columns:
      sales_market  (geo)
      smoothed_channel (channel)
      product_genus → product display name mapping (product)
    """
    return {
        "geo": [
            {"label": "All Markets",                    "value": "All"},
            {"label": "North America (NA)",             "value": "NA"},
            {"label": "Europe, Middle East & Africa",   "value": "EMEA"},
            {"label": "Latin America (LATAM)",          "value": "LATAM"},
            {"label": "Asia Pacific (APAC)",            "value": "APAC"},
            {"label": "AUS / Rest of World",            "value": "AUS/ROW"},
        ],
        "channel": [
            {"label": "All Channels",      "value": "All"},
            {"label": "Enterprise",        "value": "Enterprise"},
            {"label": "Partner",           "value": "Partner"},
            {"label": "Mid-Market",        "value": "Mid-Market"},
            {"label": "MSP",               "value": "MSP"},
            {"label": "GSI",               "value": "GSI"},
            {"label": "Small Business",    "value": "Small Business"},
        ],
        "product": [
            {"label": "All Products",      "value": "All"},
            {"label": "GoToConnect",       "value": "Connect"},
            {"label": "GoToWebinar",       "value": "Engage"},
            {"label": "Rescue",            "value": "Rescue"},
            {"label": "GoTo Central",      "value": "Central"},
            {"label": "GoTo Resolve",      "value": "Resolve"},
        ],
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

        # Build a stable cache key from filter combo (include dates so period changes re-fetch)
        cache_key = f"kpis:{start_date}:{end_date}:{geo}:{channel}:{product}"
        cached = data_cache.get(cache_key)
        if cached is not None:
            print(f"Cache hit: {cache_key} (age {data_cache.cache_age_seconds(cache_key):.0f}s)")
            return cached

        # Cache miss — fetch from GAIM tables (real targets, correct formulas)
        kpi_rows = await gaim_service.fetch_kpis(start_date, end_date, filters)
        raw_data = pd.DataFrame(kpi_rows)

        # Log the result for debugging
        print(f"Cache miss: {cache_key} — fetched {len(raw_data)} rows from Databricks")
        if len(raw_data) == 0:
            print("WARNING: No KPI data returned from GAIM service")

        # Format values, compute sparklines, trend directions
        kpis = metrics_calculator.calculate_kpis(raw_data)

        # Store in cache for next request
        data_cache.set(cache_key, kpis)

        print(f"Calculated {len(kpis)} KPIs")
        
        return kpis
    except Exception as e:
        logger.error("Error fetching KPIs: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch KPIs. Please try again.")


@app.post("/api/cache/refresh")
async def force_cache_refresh(geo: str = "All", channel: str = "All", product: str = "All"):
    """
    Force-invalidate the KPI cache so the next /api/kpis call re-queries Databricks.
    Called by the frontend "Refresh Now" button.
    Passing geo/channel/product invalidates that specific slice; omitting them
    (or passing "All") invalidates everything.
    """
    if geo == "All" and channel == "All" and product == "All":
        data_cache.invalidate_all()
        return {"status": "invalidated", "scope": "all"}
    key = f"kpis:{geo}:{channel}:{product}"
    data_cache.invalidate(key)
    return {"status": "invalidated", "scope": key}


@app.get("/api/cache/status")
async def cache_status():
    """Return cache freshness info — used by the frontend Last Refreshed indicator."""
    entries = []
    for key in list(data_cache.last_refresh.keys()):
        age = data_cache.cache_age_seconds(key)
        entries.append({
            "key": key,
            "last_refreshed_utc": data_cache.last_refreshed_at(key).isoformat() if data_cache.last_refreshed_at(key) else None,
            "age_seconds": round(age, 1) if age is not None else None,
            "is_stale": data_cache.is_stale(key),
        })
    return {"entries": entries, "refresh_interval_minutes": 15}


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
        logger.error("Error fetching chart data (%s): %s", chart_type, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chart data. Please try again.")


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
        logger.error("Error generating insights: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate insights. Please try again.")


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
        logger.error("Error generating recommendations: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate recommendations. Please try again.")


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
        logger.error("Error forecasting ARR: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate ARR forecast. Please try again.")


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
        logger.error("Error fetching ARR segments (%s): %s", segment_type, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch ARR segments. Please try again.")


@app.get("/api/arr/history")
async def get_arr_history():
    """
    Get historical ARR data.

    Tries partner_ending_arr first, then kpi_active_mrr_arr as fallback.
    Returns demo_mode=True only if both Databricks tables return no data.
    """
    def _build_response(df, demo_mode: bool, source):
        df = df.copy()
        df['growth_pct'] = df['y'].pct_change() * 100
        df = df.replace([float('inf'), float('-inf')], 0.0).fillna(0.0)
        return {
            "history": df.to_dict(orient='records'),
            "latest_arr": float(df['y'].iloc[-1]) if not df.empty else 0,
            "avg_monthly_growth": float(df['growth_pct'].mean()) if len(df) > 1 else 0,
            "demo_mode": demo_mode,
            "source": source,
        }

    try:
        historical_data = await data_fetcher.fetch_historical_data('arr')
        source = historical_data.attrs.get('arr_source') if not historical_data.empty else None

        if not historical_data.empty:
            return _build_response(historical_data, demo_mode=False, source=source)

        # Both real tables were empty — fall back to mock so the chart still renders
        logger.warning("ARR history: both partner_ending_arr and kpi_active_mrr_arr returned no data; using demo")
        mock_data = data_fetcher._get_mock_historical_data('arr')
        return _build_response(mock_data, demo_mode=True, source=None)

    except Exception as e:
        logger.error("Error fetching ARR history: %s", e)
        try:
            mock_data = data_fetcher._get_mock_historical_data('arr')
            return _build_response(mock_data, demo_mode=True, source=None)
        except Exception:
            return {"history": [], "latest_arr": 0, "avg_monthly_growth": 0, "demo_mode": True, "source": None}


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
        logger.error("Error generating KPI insights (%s): %s", kpi_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate insights. Please try again.")


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
        logger.error("Error generating alerts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate alerts. Please try again.")


# ============================================================================
# STATIC FILE SERVING (must be last - catch-all route)
# ============================================================================

# Serve static frontend files — must be the LAST route registered (catch-all)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

# Mount /assets only when the build output is present
if (frontend_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Catch-all SPA route. Returns index.html for all non-API paths."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    # dist not present — give a helpful JSON response (dev mode / pre-build)
    return {
        "message": (
            "Atlas Executive Insights API is running. "
            "Frontend not yet built — run build.sh first."
        ),
        "api_docs": "/docs",
        "health": "/api/health",
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
