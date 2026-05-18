"""
Genie AI Service â€” Databricks Genie natural-language-to-SQL layer.

Connects to the "Metis - Sales KPI Analytics" Genie Space using a Personal
Access Token. All HTTP calls are run in a thread pool so the FastAPI event
loop is never blocked.

Genie API flow
--------------
1. POST  /start-conversation          â†’ {conversation_id, message_id, status}
2. GET   /conversations/{c}/messages/{m}   (poll until COMPLETED / FAILED)
3. POST  /conversations/{c}/messages  â†’ {id (message_id), status}   (follow-up)

The full message object (when COMPLETED) contains:
  - attachments[].query.query      â† generated SQL
  - attachments[].query.descriptionâ† narrative explanation
  - content                        â† top-level narrative (may be empty)
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import requests

DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "goto-data-dock.cloud.databricks.com")
GENIE_SPACE_ID  = os.environ.get("GENIE_SPACE_ID", "01f10b2015dc1186928a78ee0bb4869f")

_POLL_INTERVAL  = 2   # seconds between status checks
_POLL_TIMEOUT   = 60  # seconds before giving up


def _token() -> str:
    """Return PAT â€” prefers DATABRICKS_TOKEN, falls back to DATABRICKS_ACCESS_TOKEN."""
    return (
        os.environ.get("DATABRICKS_TOKEN")
        or os.environ.get("DATABRICKS_ACCESS_TOKEN")
        or ""
    )


class GenieService:
    """
    Async-safe client for the Databricks Genie REST API.
    Maintains a per-user conversation map so follow-ups stay in context.
    """

    def __init__(self):
        self.base_url = f"https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{GENIE_SPACE_ID}"
        self.conversations: Dict[str, str] = {}  # user_id â†’ conversation_id

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {_token()}",
            "Content-Type":  "application/json",
        }

    # â”€â”€ Blocking helpers (called via asyncio.to_thread) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _post(self, path: str, body: Dict) -> Dict:
        url = f"{self.base_url}{path}"
        r   = requests.post(url, headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> Dict:
        url = f"{self.base_url}{path}"
        r   = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def _poll_message(self, conversation_id: str, message_id: str) -> Dict:
        """Blocking poll loop â€” runs in thread pool."""
        path     = f"/conversations/{conversation_id}/messages/{message_id}"
        deadline = time.time() + _POLL_TIMEOUT

        while time.time() < deadline:
            data   = self._get(path)
            status = data.get("status", "")

            if status == "COMPLETED":
                return data
            if status in ("FAILED", "ERROR", "CANCELLED"):
                raise RuntimeError(
                    f"Genie message {message_id} ended with status {status}: "
                    f"{data.get('error', '')}"
                )
            time.sleep(_POLL_INTERVAL)

        raise TimeoutError(
            f"Genie did not complete within {_POLL_TIMEOUT}s "
            f"(conversation {conversation_id}, message {message_id})"
        )

    # â”€â”€ Public async API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def start_conversation(self, question: str) -> Dict[str, Any]:
        """
        Start a brand-new Genie conversation with an opening question.
        Returns the raw Genie response (includes conversation_id, message_id).
        Polls until the response is ready, then returns the completed message.
        """
        init = await asyncio.to_thread(
            self._post,
            "/start-conversation",
            {"content": question},
        )
        conversation_id = init.get("conversation_id")
        message_id      = init.get("message_id")

        if not conversation_id or not message_id:
            raise ValueError(f"Unexpected start-conversation response: {init}")

        completed = await asyncio.to_thread(
            self._poll_message, conversation_id, message_id
        )
        completed["conversation_id"] = conversation_id
        return completed

    async def send_message(self, conversation_id: str, message: str) -> Dict[str, Any]:
        """
        Send a follow-up message in an existing conversation.
        Polls until the response is ready.
        """
        sent = await asyncio.to_thread(
            self._post,
            f"/conversations/{conversation_id}/messages",
            {"content": message},
        )
        message_id = sent.get("id")
        if not message_id:
            raise ValueError(f"No message id in response: {sent}")

        completed = await asyncio.to_thread(
            self._poll_message, conversation_id, message_id
        )
        completed["conversation_id"] = conversation_id
        return completed

    async def ask_kpi_question(self, question: str) -> Dict[str, Any]:
        """One-shot question â€” always starts a fresh conversation."""
        result = await self.start_conversation(question)
        return self.parse_genie_response(result)

    async def ask_with_context(
        self, question: str, user_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Ask a question, reusing an existing conversation for this user if one
        exists, or starting a new one.
        """
        conv_id = self.conversations.get(user_id)
        if conv_id:
            try:
                raw = await self.send_message(conv_id, question)
            except Exception:
                # Conversation may have expired â€” start fresh
                raw = await self.start_conversation(question)
                self.conversations[user_id] = raw.get("conversation_id", conv_id)
        else:
            raw = await self.start_conversation(question)
            self.conversations[user_id] = raw.get("conversation_id", "")

        return self.parse_genie_response(raw)

    def parse_genie_response(self, response: Dict) -> Dict[str, Any]:
        """
        Extract a clean, structured result from a completed Genie message.

        Genie returns:
          - content          narrative summary (sometimes empty)
          - attachments[]
              .query.query           generated SQL
              .query.description     narrative about the query
              .text.content          plain-text paragraph attachments
        """
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
            or "Query completed â€” see data below."
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

    # â”€â”€ Legacy compatibility (used by main.py /api/insights) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def ask_question(self, question: str) -> Dict[str, Any]:
        """Alias kept for backward compatibility with existing /api/insights calls."""
        return await self.ask_kpi_question(question)


# Singleton

genie_service = GenieService()
