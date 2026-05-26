"""
routes/actions.py
==================
Executive action tracking endpoints.

  GET    /api/actions              → list actions (optional ?status=pending|done)
  POST   /api/actions              → create a new action
  PATCH  /api/actions/{id}/status  → mark done / reopen
  DELETE /api/actions/{id}         → delete an action

Actions can be created manually (via the UI) or auto-populated from AI forecast
intelligence bullets (source="forecast") and insight panel bullets (source="insight").
"""

import logging
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from services.user_preferences_service import user_prefs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])


def _user(token: str = "") -> str:
    return token[:64] if token else "anonymous"


class CreateActionRequest(BaseModel):
    text: str
    owner: Optional[str] = None
    priority: str = "medium"
    source: str = "manual"


class UpdateStatusRequest(BaseModel):
    status: str                    # pending | done
    owner: Optional[str] = None


@router.get("")
async def list_actions(
    status: Optional[str] = None,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_id = _user(x_forwarded_access_token)
    actions = user_prefs_service.list_actions(user_id=user_id, status=status)
    return {"success": True, "data": actions}


@router.post("")
async def create_action(
    body: CreateActionRequest,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_id = _user(x_forwarded_access_token)
    action = user_prefs_service.create_action(
        text=body.text, owner=body.owner,
        priority=body.priority, source=body.source,
        user_id=user_id,
    )
    return {"success": True, "data": action}


@router.patch("/{action_id}/status")
async def update_status(
    action_id: str,
    body: UpdateStatusRequest,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_prefs_service.update_action_status(action_id, body.status, body.owner)
    return {"success": True, "message": f"Action {action_id} → {body.status}"}


@router.delete("/{action_id}")
async def delete_action(
    action_id: str,
    x_forwarded_access_token: Optional[str] = Header(default="")
):
    user_prefs_service.delete_action(action_id)
    return {"success": True, "message": f"Action {action_id} deleted."}
