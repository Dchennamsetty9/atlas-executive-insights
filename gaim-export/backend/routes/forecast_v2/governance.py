from fastapi import APIRouter

from routes import forecast_v2_impl as impl

router = APIRouter()

router.add_api_route("/governance/log", impl.list_governance_log, methods=["GET"])
router.add_api_route("/governance/log", impl.create_governance_log, methods=["POST"])
router.add_api_route("/freshness", impl.get_freshness, methods=["GET"])
router.add_api_route("/models", impl.get_models, methods=["GET"])
router.add_api_route("/run-delta", impl.get_run_delta, methods=["GET"])
