"""
GAIM Executive App - FastAPI bootstrap
Contains application setup, middleware wiring, router registration, and shared services.
"""

import logging
import signal
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from services.data_fetcher import DataFetcher
from services.gaim_data_service import GAIMDataService
from services.databricks_connection import set_request_token
from services.forecasting import ForecastingService
from services.insights_engine import InsightsEngine
from services.metrics import MetricsCalculator
from services.genie_service import GenieService

from routes.genie import router as genie_router
from routes.insights import router as insights_router
from routes.mql import router as mql_router
from routes.pipeline_segments import router as pipeline_segments_router
from routes.deal_bands import router as deal_bands_router
from routes.coverage import router as coverage_router
from routes.deals import router as deals_router
from routes.forecast import router as forecast_router
from routes.performance_hub import router as performance_hub_router
from routes.ai import router as ai_router
from routes.preferences import router as preferences_router
from routes.actions import router as actions_router
from routes.notifications import router as notifications_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GAIM Executive App API",
    description="AI-powered executive analytics backend - LIVE Databricks",
    version="0.3.0",
)


def _sigterm_handler(signum, frame):
    logger.info("SIGTERM received — shutting down gracefully.")
    sys.exit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def inject_forwarded_token(request: Request, call_next):
    token = request.headers.get("x-forwarded-access-token", "")
    set_request_token(token or "")
    return await call_next(request)


# Shared service singletons
data_fetcher = DataFetcher()
gaim_service = GAIMDataService()
forecasting_service = ForecastingService()
insights_engine = InsightsEngine()
metrics_calculator = MetricsCalculator()
genie_service = GenieService()

# Mount API routers
app.include_router(genie_router)
app.include_router(insights_router)
app.include_router(mql_router)
app.include_router(pipeline_segments_router)
app.include_router(deal_bands_router)
app.include_router(coverage_router)
app.include_router(deals_router)
app.include_router(forecast_router)
app.include_router(performance_hub_router)
app.include_router(ai_router)
app.include_router(preferences_router)
app.include_router(actions_router)
app.include_router(notifications_router)
