"""Auth introspection endpoints.

GET  /api/v1/auth/required  — public, returns whether the server requires a Bearer token
POST /api/v1/auth/check     — protected, returns 200 if the supplied token is valid

The frontend hits /required once on app load to decide whether to show a login
screen, then uses /check to validate a pasted token before persisting it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.core.config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/required")
async def auth_required() -> dict:
    """Public — frontend reads this on load to decide whether /login is needed."""
    return {"required": settings.auth_enabled}


@router.post("/check")
async def auth_check(_: None = Depends(require_auth)) -> dict:
    """Protected — returns 200 only if the Bearer token is valid (or auth disabled)."""
    return {"ok": True}
