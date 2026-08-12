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

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_authenticated_user
from services.user_preferences_service import user_prefs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])

class CreateActionRequest(BaseModel):
    text: str
    owner: Optional[str] = None
    priority: str = "medium"
    source: str = "manual"
    due_date: Optional[str] = None
    playbook_action: Optional[str] = None
    expected_impact: Optional[float] = None
    actual_impact: Optional[float] = None


class UpdateActionMetaRequest(BaseModel):
    due_date: Optional[str] = None
    playbook_action: Optional[str] = None
    expected_impact: Optional[float] = None
    actual_impact: Optional[float] = None


class UpdateStatusRequest(BaseModel):
    status: str                    # pending | done
    owner: Optional[str] = None


@router.get("")
async def list_actions(
    status: Optional[str] = None,
    user_id: str = Depends(require_authenticated_user)
):
    actions = user_prefs_service.list_actions(user_id=user_id, status=status)
    metadata_map = user_prefs_service.list_action_metadata(user_id)
    for action in actions:
        meta = metadata_map.get(str(action.get("action_id") or ""), {})
        if meta:
            action.update(meta)
    return {"success": True, "data": actions}


@router.post("")
async def create_action(
    body: CreateActionRequest,
    user_id: str = Depends(require_authenticated_user)
):
    action = user_prefs_service.create_action(
        text=body.text, owner=body.owner,
        priority=body.priority, source=body.source,
        user_id=user_id,
    )
    meta = {
        "due_date": body.due_date,
        "playbook_action": body.playbook_action,
        "expected_impact": body.expected_impact,
        "actual_impact": body.actual_impact,
    }
    if any(v is not None for v in meta.values()):
        action.update(user_prefs_service.upsert_action_metadata(user_id, action["action_id"], meta))
    return {"success": True, "data": action}


@router.patch("/{action_id}/status")
async def update_status(
    action_id: str,
    body: UpdateStatusRequest,
    _user_id: str = Depends(require_authenticated_user)
):
    user_prefs_service.update_action_status(action_id, body.status, body.owner)
    return {"success": True, "message": f"Action {action_id} → {body.status}"}


@router.delete("/{action_id}")
async def delete_action(
    action_id: str,
    _user_id: str = Depends(require_authenticated_user)
):
    user_prefs_service.delete_action(action_id)
    return {"success": True, "message": f"Action {action_id} deleted."}


@router.patch("/{action_id}/meta")
async def update_action_meta(
    action_id: str,
    body: UpdateActionMetaRequest,
    user_id: str = Depends(require_authenticated_user)
):
    meta = user_prefs_service.upsert_action_metadata(user_id, action_id, {
        "due_date": body.due_date,
        "playbook_action": body.playbook_action,
        "expected_impact": body.expected_impact,
        "actual_impact": body.actual_impact,
    })
    return {"success": True, "data": {"action_id": action_id, **meta}}
