"""Bearer-token auth for Community Edition.

Single shared token loaded from WEKAMS_AUTH_TOKEN. Routes that require
authentication declare it via the require_auth dependency. If the token
is unset, the dependency is a no-op and a warning is logged once at
startup — appropriate for laptop development, NOT for any deployment
that listens on a network-reachable interface.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


_bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency that enforces the configured Bearer token.

    When auth is disabled (no token configured), this is a no-op so the
    route remains accessible — useful for laptop dev.
    """
    if not settings.auth_enabled:
        return

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison to avoid leaking length / prefix info.
    expected = settings.auth_token or ""
    provided = credentials.credentials or ""
    if not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def log_startup_auth_state() -> None:
    """Called once during app startup to log whether auth is enforced."""
    if settings.auth_enabled:
        log.info("auth.enabled", scheme="bearer")
    else:
        log.warning(
            "auth.disabled",
            message=(
                "WEKAMS_AUTH_TOKEN is not set; API endpoints are open. "
                "Set WEKAMS_AUTH_TOKEN before exposing this instance on a network."
            ),
        )
