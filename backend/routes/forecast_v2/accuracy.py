from fastapi import APIRouter

from routes import forecast_v2_impl as impl

router = APIRouter()

router.add_api_route("/leaderboard", impl.get_leaderboard, methods=["GET"])
router.add_api_route("/backtest", impl.get_backtest, methods=["GET"])
router.add_api_route("/model-lab", impl.get_model_lab, methods=["GET"])
router.add_api_route("/confidence", impl.get_confidence, methods=["GET"])
