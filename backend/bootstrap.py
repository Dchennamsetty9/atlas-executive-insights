"""
GAIM Executive App - FastAPI bootstrap
Contains application setup, middleware wiring, router registration, and shared services.
"""

import logging
import signal
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

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
from routes.forecast_v2 import router as forecast_v2_router
from routes.performance_hub import router as performance_hub_router
from routes.ai import router as ai_router
from routes.preferences import router as preferences_router
from routes.actions import router as actions_router
from routes.notifications import router as notifications_router
from routes.ai_stream import router as ai_stream_router
from routes.ws import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GAIM Executive App API",
    description="AI-powered executive analytics backend - LIVE Databricks",
    version="0.4.0",
)


def _sigterm_handler(signum, frame):
    logger.info("SIGTERM received — shutting down gracefully.")
    sys.exit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)

# Compress responses >= 500 bytes — cuts JSON payload size ~80% on slow VPNs
app.add_middleware(GZipMiddleware, minimum_size=500)

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
    response = await call_next(request)
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Structured request/error logging for production visibility."""
    import time
    start = time.time()
    try:
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)
        if response.status_code >= 400:
            logger.warning(
                "HTTP %s %s → %s [%dms]",
                request.method, request.url.path, response.status_code, duration_ms,
            )
        else:
            logger.debug(
                "HTTP %s %s → %s [%dms]",
                request.method, request.url.path, response.status_code, duration_ms,
            )
        return response
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        logger.error(
            "UNHANDLED ERROR %s %s [%dms]: %s",
            request.method, request.url.path, duration_ms, exc,
            exc_info=True,
        )
        raise


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
app.include_router(forecast_v2_router)
app.include_router(performance_hub_router)
app.include_router(ai_router)
app.include_router(preferences_router)
app.include_router(actions_router)
app.include_router(notifications_router)
app.include_router(ai_stream_router)
app.include_router(ws_router)
