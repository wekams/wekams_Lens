"""Semantic-layer hook (Community-visible interface).

Default: no-op. Returns an empty block, so the LLM prompt is unchanged
in Community installs.

Pro / Enterprise: ee.semantic registers a provider here at import time
that returns a formatted list of business metrics. The orchestrator's
schema_context appends whatever this returns to the LLM prompt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger(__name__)

Provider = Callable[[AsyncSession], Awaitable[str]]
_provider: Provider | None = None


def set_provider(fn: Provider) -> None:
    """Install the (single) semantic-layer provider. Called by ee.semantic."""
    global _provider
    _provider = fn
    log.info("semantic.provider.installed")


async def get_metrics_block(session: AsyncSession) -> str:
    """Return the semantic-layer block to append to the LLM prompt.

    Empty string when no provider is installed — Community installs see
    no change in prompt size.
    """
    if _provider is None:
        return ""
    try:
        return await _provider(session)
    except Exception as exc:
        log.warning("semantic.provider.failed", error=str(exc))
        return ""
