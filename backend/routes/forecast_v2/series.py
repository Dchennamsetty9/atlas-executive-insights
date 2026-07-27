from fastapi import APIRouter

from routes import forecast_v2_impl as impl

router = APIRouter()

router.add_api_route("/weekly", impl.get_weekly, methods=["GET"])
router.add_api_route("/monthly", impl.get_monthly, methods=["GET"])
router.add_api_route("/ytd", impl.get_ytd, methods=["GET"])
router.add_api_route("/by-product", impl.get_by_product, methods=["GET"])
router.add_api_route("/historical", impl.get_historical, methods=["GET"])
router.add_api_route("/confidence-bands", impl.get_confidence_bands, methods=["GET"])
