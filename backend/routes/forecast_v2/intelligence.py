from fastapi import APIRouter

from routes import forecast_v2_impl as impl

router = APIRouter()

router.add_api_route("/intelligence", impl.get_intelligence, methods=["GET"])
router.add_api_route("/driver-bridge", impl.get_driver_bridge, methods=["GET"])
router.add_api_route("/risk-radar", impl.get_risk_radar, methods=["GET"])
router.add_api_route("/meeting-mode", impl.get_meeting_mode, methods=["GET"])
