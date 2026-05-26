"""Shared pytest fixtures.

These tests deliberately avoid requiring a running Postgres catalog. Auth
and other tests target the FastAPI app's pre-handler dependencies which
run before any DB access — so we never exercise the catalog session.
Connector and vault tests are pure-Python and stand alone.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Ensure imports of app.* during collection don't fail because required
# env vars are missing. Set safe defaults BEFORE app code runs.
os.environ.setdefault("WEKAMS_CATALOG_DB_URL", "postgresql+asyncpg://test:test@localhost:65535/test")
os.environ.setdefault("GROQ_API_KEY", "test-key")


@pytest.fixture
def auth_token() -> str:
    return "test-token-deadbeef"


@pytest.fixture
def set_auth_token(monkeypatch: pytest.MonkeyPatch, auth_token: str) -> Iterator[str]:
    """Set WEKAMS_AUTH_TOKEN on the live Settings instance for the duration of a test."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_token", auth_token)
    yield auth_token


@pytest.fixture
def unset_auth_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_token", None)
    yield None
