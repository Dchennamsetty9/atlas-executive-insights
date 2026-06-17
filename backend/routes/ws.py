"""
WebSocket endpoint for live dashboard refresh notifications.
Clients connect to /ws/refresh and receive a JSON ping whenever the
gold-layer data is refreshed — avoiding 15-min polling from the frontend.

Usage from frontend:
  const ws = new WebSocket(`wss://${location.host}/ws/refresh`);
  ws.onmessage = (e) => { const msg = JSON.parse(e.data); if (msg.type === 'refresh') loadKpis(); };
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Connection registry ──────────────────────────────────────────────────────
_clients: Set[WebSocket] = set()


async def broadcast_refresh(event_type: str = "refresh", payload: dict | None = None):
    """Call this from any route/job that refreshes gold-layer data."""
    if not _clients:
        return
    msg = json.dumps({"type": event_type, **(payload or {})})
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ── Endpoint ─────────────────────────────────────────────────────────────────
@router.websocket("/ws/refresh")
async def ws_refresh(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    logger.info("WS client connected — total: %d", len(_clients))
    try:
        # Send an immediate 'connected' handshake so the client knows it's live
        await websocket.send_text(json.dumps({"type": "connected"}))
        # Keep alive: echo pings from client, timeout every 30s with a server ping
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Server-initiated keepalive
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        logger.info("WS client disconnected — total: %d", len(_clients))
