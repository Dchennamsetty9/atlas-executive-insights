"""
Genie AI Service — Databricks Genie natural-language-to-SQL layer.

Auth strategy (in priority order):
  1. WorkspaceClient() — on Databricks Apps this auto-authenticates using the
     app's built-in service principal (no token config needed). Locally it reads
     DATABRICKS_HOST + DATABRICKS_TOKEN from the environment.
  2. Per-request forwarded user token (x-forwarded-access-token ContextVar) —
     kept as a fallback for cases where WorkspaceClient is unavailable.

Using WorkspaceClient removes the need for each end-user to have Unity Catalog
permissions on the federated catalog; only the app's service principal needs access.

Genie API flow
--------------
1. POST  /start-conversation              → {conversation_id, message_id, status}
2. GET   /conversations/{c}/messages/{m}  (poll until COMPLETED / FAILED)
3. POST  /conversations/{c}/messages      → follow-up in same conversation
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "goto-data-dock.cloud.databricks.com")
GENIE_SPACE_ID  = os.environ.get("GENIE_SPACE_ID", "01f10b2015dc1186928a78ee0bb4869f")

_POLL_INTERVAL = 2    # seconds between status checks
_POLL_TIMEOUT  = 90   # seconds before giving up (Genie can be slow on cold start)


# -- Auth: WorkspaceClient (preferred) ----------------------------------------

def _build_ws_client():
    """
    Return a Databricks WorkspaceClient.
    On Databricks Apps: auto-authenticates via the app's service principal OAuth.
    Locally: reads DATABRICKS_HOST + DATABRICKS_TOKEN from the environment.
    Returns None if the SDK is unavailable (shouldn't happen — it's in requirements.txt).
    """
    try:
        from databricks.sdk import WorkspaceClient
        host = DATABRICKS_HOST
        if not host.startswith("https://"):
            host = f"https://{host}"
        return WorkspaceClient(host=host)
    except Exception:
        return None


_ws_client = _build_ws_client()


def _fallback_token() -> str:
    """Fallback: per-request user token or static env var."""
    try:
        from services.databricks_connection import _request_token as _req_tok
        return (
            _req_tok.get()
            or os.environ.get("DATABRICKS_TOKEN")
            or os.environ.get("DATABRICKS_ACCESS_TOKEN")
            or ""
        )
    except Exception:
        return os.environ.get("DATABRICKS_TOKEN") or os.environ.get("DATABRICKS_ACCESS_TOKEN") or ""


# -- HTTP helpers (blocking — called via asyncio.to_thread) -------------------

def _api_call(method: str, path: str, body: Optional[Dict] = None) -> Dict:
    """
    Make a Genie REST API call.
    Uses WorkspaceClient.api_client when available (preferred — uses app's identity).
    Falls back to raw requests with a Bearer token.
    """
    full_path = f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}{path}"

    if _ws_client is not None:
        result = _ws_client.api_client.do(method, full_path, body=body or {})
        return result if isinstance(result, dict) else {}

    # Fallback: raw requests
    import requests
    host = DATABRICKS_HOST
    if not host.startswith("https://"):
        host = f"https://{host}"
    url     = f"{host}{full_path}"
    headers = {
        "Authorization": f"Bearer {_fallback_token()}",
        "Content-Type":  "application/json",
    }
    if method.upper() == "POST":
        r = requests.post(url, headers=headers, json=body or {}, timeout=30)
    else:
        r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _poll_message(conversation_id: str, message_id: str) -> Dict:
    """Blocking poll loop — run inside asyncio.to_thread."""
    path     = f"/conversations/{conversation_id}/messages/{message_id}"
    deadline = time.time() + _POLL_TIMEOUT

    while time.time() < deadline:
        data   = _api_call("GET", path)
        status = data.get("status", "")

        if status == "COMPLETED":
            return data
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(
                f"Genie message {message_id} ended with status {status}: "
                f"{data.get('error', data.get('content', ''))}"
            )
        time.sleep(_POLL_INTERVAL)

    raise TimeoutError(
        f"Genie did not complete within {_POLL_TIMEOUT}s "
        f"(conversation {conversation_id}, message {message_id})"
    )


# -- GenieService -------------------------------------------------------------

class GenieService:
    """
    Async-safe client for the Databricks Genie REST API.
    Maintains a per-user conversation map so follow-ups stay in context.
    """

    def __init__(self):
        self.conversations: Dict[str, str] = {}   # user_id → conversation_id

    async def start_conversation(self, question: str) -> Dict[str, Any]:
        """Start a new Genie conversation; poll until response is ready."""
        init = await asyncio.to_thread(
            _api_call, "POST", "/start-conversation", {"content": question}
        )
        conversation_id = init.get("conversation_id")
        message_id      = init.get("message_id")

        if not conversation_id or not message_id:
            raise ValueError(f"Unexpected start-conversation response: {init}")

        completed = await asyncio.to_thread(_poll_message, conversation_id, message_id)
        completed["conversation_id"] = conversation_id
        return completed

    async def send_message(self, conversation_id: str, message: str) -> Dict[str, Any]:
        """Send a follow-up message in an existing conversation."""
        sent = await asyncio.to_thread(
            _api_call,
            "POST",
            f"/conversations/{conversation_id}/messages",
            {"content": message},
        )
        message_id = sent.get("id")
        if not message_id:
            raise ValueError(f"No message id in response: {sent}")

        completed = await asyncio.to_thread(_poll_message, conversation_id, message_id)
        completed["conversation_id"] = conversation_id
        return completed

    async def ask_kpi_question(self, question: str) -> Dict[str, Any]:
        """One-shot question — always starts a fresh conversation."""
        result = await self.start_conversation(question)
        return self.parse_genie_response(result)

    async def ask_with_context(
        self, question: str, user_id: str = "default"
    ) -> Dict[str, Any]:
        """Ask using an existing conversation for this user_id, or start a new one."""
        conv_id = self.conversations.get(user_id)
        if conv_id:
            try:
                raw = await self.send_message(conv_id, question)
            except Exception:
                raw = await self.start_conversation(question)
                self.conversations[user_id] = raw.get("conversation_id", conv_id)
        else:
            raw = await self.start_conversation(question)
            self.conversations[user_id] = raw.get("conversation_id", "")
        return self.parse_genie_response(raw)

    def parse_genie_response(self, response: Dict) -> Dict[str, Any]:
        """Extract SQL, narrative, and metadata from a completed Genie message."""
        attachments = response.get("attachments") or []

        sql         = None
        description = None
        text_parts: List[str] = []

        for att in attachments:
            query_block = att.get("query") or {}
            if query_block.get("query"):
                sql         = query_block["query"]
                description = query_block.get("description", "")
            text_block = att.get("text") or {}
            if text_block.get("content"):
                text_parts.append(text_block["content"])

        answer = (
            response.get("content")
            or description
            or (text_parts[0] if text_parts else "")
            or "Query completed — see data below."
        )

        return {
            "conversation_id": response.get("conversation_id", ""),
            "message_id":      response.get("id", ""),
            "answer":          answer,
            "sql":             sql,
            "data":            attachments,
            "status":          response.get("status", "COMPLETED"),
        }

    async def get_suggested_questions(self) -> List[str]:
        return [
            "Show me won amount vs Plan for this quarter",
            "What is our attainment against target for each market?",
            "Compare ADS this quarter to last quarter",
            "Close rate by channel for UCaaS",
            "Show me won opps over the past 7 quarters",
            "What's pipeline coverage for EMEA?",
            "Which product has the highest win rate this quarter?",
            "How does created pipeline compare YoY?",
            "Which segment is underperforming against targets?",
            "What's driving the change in active pipeline?",
        ]

    async def ask_question(self, question: str) -> Dict[str, Any]:
        """Alias kept for backward compatibility."""
        return await self.ask_kpi_question(question)


# Singleton
genie_service = GenieService()
