"""
routes/preferences.py
======================
User preferences and filter preset endpoints.

All routes extract the user identity from the x-forwarded-access-token header
(Databricks Apps user passthrough).  Falls back to "anonymous" in local dev.

  GET  /api/preferences/presets          → list saved filter presets
  POST /api/preferences/presets          → save a named preset
  DELETE /api/preferences/presets/{name} → remove a preset

  GET  /api/preferences/{key}            → read a generic pref
  PUT  /api/preferences/{key}            → write a generic pref
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_authenticated_user
from services.user_preferences_service import user_prefs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

# ── Pydantic models ────────────────────────────────────────────────────────────

class SavePresetRequest(BaseModel):
    name: str
    filters: Dict[str, Any]


class SetPrefRequest(BaseModel):
    value: Any


# ── Filter presets ─────────────────────────────────────────────────────────────

@router.get("/presets")
async def list_presets(
    user_id: str = Depends(require_authenticated_user)
):
    presets = user_prefs_service.get_presets(user_id)
    return {"success": True, "data": presets}


@router.post("/presets")
async def save_preset(
    body: SavePresetRequest,
    user_id: str = Depends(require_authenticated_user)
):
    user_prefs_service.save_preset(user_id, body.name, body.filters)
    return {"success": True, "message": f"Preset '{body.name}' saved."}


@router.delete("/presets/{name}")
async def delete_preset(
    name: str,
    user_id: str = Depends(require_authenticated_user)
):
    user_prefs_service.delete_preset(user_id, name)
    return {"success": True, "message": f"Preset '{name}' deleted."}


# ── Generic preferences ────────────────────────────────────────────────────────

@router.get("/{key}")
async def get_pref(
    key: str,
    user_id: str = Depends(require_authenticated_user)
):
    value = user_prefs_service.get_pref(user_id, key)
    return {"success": True, "data": value}


@router.put("/{key}")
async def set_pref(
    key: str,
    body: SetPrefRequest,
    user_id: str = Depends(require_authenticated_user)
):
    user_prefs_service.set_pref(user_id, key, body.value)
    return {"success": True, "message": f"Preference '{key}' updated."}
