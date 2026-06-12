import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

# Ensure backend package root is importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth
from config.settings import settings


@pytest.mark.asyncio
async def test_requires_token_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "auth_allow_anonymous_local", True)

    with pytest.raises(HTTPException) as exc:
        await auth.require_authenticated_user("")

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_allows_local_dev_without_token(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "auth_allow_anonymous_local", True)

    user_id = await auth.require_authenticated_user("")
    assert user_id == "local-dev"


@pytest.mark.asyncio
async def test_verifies_non_empty_token(monkeypatch):
    async def fake_verify(token: str) -> str:
        assert token == "abc.def.ghi"
        return "user@example.com"

    monkeypatch.setattr(auth, "_verify_forwarded_token", fake_verify)
    monkeypatch.setattr(settings, "environment", "production")

    user_id = await auth.require_authenticated_user("Bearer abc.def.ghi")
    assert user_id == "user@example.com"


@pytest.mark.asyncio
async def test_debug_access_respects_flag(monkeypatch):
    monkeypatch.setattr(settings, "enable_debug_endpoints", False)

    with pytest.raises(HTTPException) as exc:
        await auth.require_debug_access("Bearer abc.def.ghi")

    assert exc.value.status_code == 404
