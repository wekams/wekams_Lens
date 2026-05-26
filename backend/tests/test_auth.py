"""Bearer-token auth tests.

Covers the just-shipped require_auth dependency and the two auth API
endpoints. Critical security path — we want fast regression detection if
anyone weakens the guard.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ── /api/v1/auth/required ─────────────────────────────────────────────


def test_auth_required_reports_enabled_when_token_set(client: TestClient, set_auth_token: str):
    r = client.get("/api/v1/auth/required")
    assert r.status_code == 200
    assert r.json() == {"required": True}


def test_auth_required_reports_disabled_when_no_token(client: TestClient, unset_auth_token: None):
    r = client.get("/api/v1/auth/required")
    assert r.status_code == 200
    assert r.json() == {"required": False}


# ── /api/v1/auth/check ────────────────────────────────────────────────


def test_auth_check_accepts_correct_token(client: TestClient, set_auth_token: str):
    r = client.post(
        "/api/v1/auth/check",
        headers={"Authorization": f"Bearer {set_auth_token}"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_auth_check_rejects_wrong_token(client: TestClient, set_auth_token: str):
    r = client.post(
        "/api/v1/auth/check",
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert r.status_code == 401


def test_auth_check_rejects_missing_token(client: TestClient, set_auth_token: str):
    r = client.post("/api/v1/auth/check")
    assert r.status_code == 401


def test_auth_check_rejects_wrong_scheme(client: TestClient, set_auth_token: str):
    r = client.post(
        "/api/v1/auth/check",
        headers={"Authorization": f"Basic {set_auth_token}"},
    )
    assert r.status_code == 401


def test_auth_check_passes_when_disabled(client: TestClient, unset_auth_token: None):
    """With no token configured, /auth/check is a no-op and always succeeds."""
    r = client.post("/api/v1/auth/check")
    assert r.status_code == 200


# ── Protected routes (sources / chat / conversations) ─────────────────


def test_sources_returns_401_without_token(client: TestClient, set_auth_token: str):
    r = client.get("/api/v1/sources")
    assert r.status_code == 401


def test_sources_returns_401_with_wrong_token(client: TestClient, set_auth_token: str):
    r = client.get(
        "/api/v1/sources",
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert r.status_code == 401


def test_conversations_returns_401_without_token(client: TestClient, set_auth_token: str):
    r = client.get("/api/v1/conversations")
    assert r.status_code == 401


# ── Health endpoints stay open regardless ─────────────────────────────


def test_healthz_open_when_auth_enabled(client: TestClient, set_auth_token: str):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_open_when_auth_disabled(client: TestClient, unset_auth_token: None):
    r = client.get("/healthz")
    assert r.status_code == 200
