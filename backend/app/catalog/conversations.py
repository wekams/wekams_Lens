"""Conversation persistence service.

Owns the lifecycle of Conversation + ChatMessage rows. Decoupled from
the chat HTTP endpoint so the orchestrator (and a future Slack bot,
CLI, MCP server) can reuse it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ChatMessage, Conversation
from app.core.logging import get_logger

log = get_logger(__name__)


_TITLE_MAX_CHARS = 60
_DEFAULT_TITLE = "New conversation"


def _derive_title(first_user_text: str) -> str:
    """Pull a short, readable title from the first user message."""
    s = " ".join(first_user_text.split())  # collapse whitespace
    if not s:
        return _DEFAULT_TITLE
    if len(s) <= _TITLE_MAX_CHARS:
        return s
    return s[: _TITLE_MAX_CHARS - 1].rstrip() + "…"


async def list_conversations(session: AsyncSession, limit: int = 50) -> list[Conversation]:
    """Most-recent-first, capped."""
    result = await session.scalars(
        select(Conversation).order_by(desc(Conversation.updated_at)).limit(limit)
    )
    return list(result)


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def create_conversation(
    session: AsyncSession, *, title: str | None = None
) -> Conversation:
    conv = Conversation(title=title or _DEFAULT_TITLE)
    session.add(conv)
    await session.flush()
    log.info("conversations.created", id=str(conv.id))
    return conv


async def delete_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> bool:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        return False
    await session.delete(conv)
    log.info("conversations.deleted", id=str(conversation_id))
    return True


async def rename_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, *, title: str
) -> Conversation | None:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        return None
    conv.title = title.strip() or _DEFAULT_TITLE
    await session.flush()
    return conv


async def _next_sequence(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    # COUNT-based; chat throughput is human-paced so no contention worth
    # adding a per-conversation lock for.
    n = await session.scalar(
        select(ChatMessage.id).where(ChatMessage.conversation_id == conversation_id)
    )
    if n is None:
        return 0
    result = await session.scalars(
        select(ChatMessage.sequence)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(desc(ChatMessage.sequence))
        .limit(1)
    )
    last = result.first()
    return (last + 1) if last is not None else 0


async def append_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: str = "",
    tool_calls: list | None = None,
    tool_call_id: str | None = None,
    tool_data: dict | None = None,
) -> ChatMessage:
    seq = await _next_sequence(session, conversation_id)
    msg = ChatMessage(
        conversation_id=conversation_id,
        sequence=seq,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        tool_data=tool_data,
    )
    session.add(msg)

    # Keep updated_at fresh on the parent so the sidebar reorders correctly.
    conv = await session.get(Conversation, conversation_id)
    if conv is not None:
        # If this is the first user message in a default-titled conversation,
        # auto-derive a title from it.
        if (
            role == "user"
            and content.strip()
            and conv.title == _DEFAULT_TITLE
        ):
            conv.title = _derive_title(content)
        # Touch the parent so SQLAlchemy fires the onupdate.
        conv.updated_at = conv.updated_at  # noqa: PLW0127  (touch for onupdate)

    await session.flush()
    return msg


async def get_or_create_default(session: AsyncSession) -> Conversation:
    """Return the most recent conversation, or create one if none exist.

    Convenience for the frontend's "show me something on first load" path —
    we don't want a blank screen for a returning user.
    """
    existing = await session.scalars(
        select(Conversation).order_by(desc(Conversation.updated_at)).limit(1)
    )
    most_recent = existing.first()
    if most_recent is not None:
        return most_recent
    return await create_conversation(session)


def messages_to_llm_format(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Project ChatMessage rows into the chat-completions message shape consumed
    by the orchestrator (excluding any system message — orchestrator
    injects its own fresh one each turn)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        entry: dict[str, Any] = {"role": m.role, "content": m.content or ""}
        if m.tool_calls:
            entry["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        out.append(entry)
    return out
