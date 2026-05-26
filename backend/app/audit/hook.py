"""Audit subscriber registry — single global slot.

Community: no subscriber registered, `emit()` is a no-op.
Pro / Enterprise: `ee.audit` registers `write_event` via `set_subscriber()`
at import time. After that, every call to `emit()` persists to the
catalog DB.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

Subscriber = Callable[..., Awaitable[None]]
_subscriber: Subscriber | None = None


def set_subscriber(fn: Subscriber) -> None:
    """Install the (single) audit subscriber. Called by ee.audit on import."""
    global _subscriber
    _subscriber = fn
    log.info("audit.subscriber.installed")


async def emit(
    event_type: str,
    *,
    outcome: str = "ok",
    actor: str | None = None,
    source_name: str | None = None,
    license_id: str | None = None,
    **payload: Any,
) -> None:
    """Announce an audit-worthy event. No-op when no subscriber is installed.

    Subscriber exceptions are logged but never raised — audit failure must
    not break the main code path.
    """
    if _subscriber is None:
        return
    try:
        await _subscriber(
            event_type=event_type,
            outcome=outcome,
            actor=actor,
            source_name=source_name,
            license_id=license_id,
            payload=payload,
        )
    except Exception as exc:
        log.warning("audit.emit.failed", event_type=event_type, error=str(exc))
