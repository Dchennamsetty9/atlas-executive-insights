from fastapi import APIRouter

from routes import forecast_v2_impl as impl
from .accuracy import router as accuracy_router
from .governance import router as governance_router
from .intelligence import router as intelligence_router
from .series import router as series_router

# Compatibility exports for existing tests/patches that target routes.forecast_v2
_live = impl._live
execute_query = impl.execute_query

router = APIRouter(prefix="/api/forecast/v2", tags=["forecast-v2"])
router.include_router(series_router)
router.include_router(accuracy_router)
router.include_router(intelligence_router)
router.include_router(governance_router)
