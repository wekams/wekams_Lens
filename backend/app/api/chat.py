"""POST /api/v1/chat — orchestrator-driven streaming endpoint.

Conversation contract:
  - First request in a thread: client sends `messages: [<user msg>]` with
    no conversation_id. Backend creates a new conversation, persists the
    user message, returns the new id in a `conversation` SSE event.
  - Subsequent requests: client sends ONLY the new user message plus the
    conversation_id. Backend loads prior turns from the DB and replays
    them to the orchestrator. The client is NOT the source of truth for
    conversation history — the catalog is.

This keeps the wire format small and avoids replay corruption where the
client's in-memory state could drift from what was actually stored.

Emits a leading `conversation` event with id + title so the frontend can
pin its sidebar / URL state without an extra round-trip.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.catalog import conversations as conv_svc
from app.catalog.db import get_session
from app.core.logging import get_logger
from app.llm import Message, Role, ToolCall, get_llm
from app.llm.base import ToolCall as LLMToolCall
from app.orchestrator import Orchestrator
from app.orchestrator.agent import (
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    conversation_id: uuid.UUID | None = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=8192)


def _stored_message_to_llm(row) -> Message:  # noqa: ANN001 — ChatMessage ORM
    tool_calls = []
    if row.tool_calls:
        for raw in row.tool_calls:
            fn = raw.get("function", {}) if isinstance(raw, dict) else {}
            args = fn.get("arguments", "{}")
            try:
                args = json.loads(args) if isinstance(args, str) else (args or {})
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                LLMToolCall(
                    id=raw.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                )
            )
    return Message(
        role=Role(row.role),
        content=row.content or "",
        tool_calls=tool_calls,
        tool_call_id=row.tool_call_id,
    )


@router.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    llm = get_llm()
    orchestrator = Orchestrator(llm)

    log.info(
        "chat.request",
        provider=llm.name,
        message_count=len(req.messages),
        conversation_id=str(req.conversation_id) if req.conversation_id else None,
    )

    async def event_stream() -> AsyncIterator[dict]:
        # ── 1) Resolve / create the conversation. ──────────────────
        history_for_llm: list[Message] = []
        conversation_id: uuid.UUID
        conversation_title: str

        try:
            async with get_session() as session:
                if req.conversation_id is not None:
                    conv = await conv_svc.get_conversation(session, req.conversation_id)
                    if conv is None:
                        # Stale id from a deleted conversation — start fresh.
                        conv = await conv_svc.create_conversation(session)
                    else:
                        history_for_llm = [_stored_message_to_llm(m) for m in conv.messages]
                else:
                    conv = await conv_svc.create_conversation(session)

                conversation_id = conv.id
                conversation_title = conv.title

                # Persist the trailing user message in this request, if any.
                new_user_msg = next(
                    (m for m in reversed(req.messages) if m.role == Role.USER),
                    None,
                )
                if new_user_msg is not None:
                    await conv_svc.append_message(
                        session,
                        conversation_id=conversation_id,
                        role="user",
                        content=new_user_msg.content,
                    )
                    history_for_llm.append(new_user_msg)
        except Exception as exc:  # noqa: BLE001
            log.exception("chat.persist.failed")
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "message": f"could not start conversation: {exc}"}),
            }
            return

        # Re-read the title after possible auto-derivation from the first
        # user message — keeps the sidebar in sync from the start.
        async with get_session() as session:
            refreshed = await conv_svc.get_conversation(session, conversation_id)
            if refreshed is not None:
                conversation_title = refreshed.title

        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "type": "conversation",
                    "id": str(conversation_id),
                    "title": conversation_title,
                }
            ),
        }

        # ── 2) Run the orchestrator + persist assistant turn as we go. ──
        accumulated_text: list[str] = []
        had_error = False

        try:
            async for ev in orchestrator.run(history_for_llm):
                yield {"event": "message", "data": Orchestrator.serialize_event(ev)}

                if isinstance(ev, TokenEvent):
                    accumulated_text.append(ev.text)
                elif isinstance(ev, ToolCallEvent):
                    # Flush any buffered text as an assistant text row first.
                    await _flush_text_row(conversation_id, accumulated_text)
                    accumulated_text = []
                    call_payload = _tool_call_payload(ev)
                    async with get_session() as session:
                        await conv_svc.append_message(
                            session,
                            conversation_id=conversation_id,
                            role="assistant",
                            content="",
                            tool_calls=[call_payload],
                        )
                elif isinstance(ev, ToolResultEvent):
                    # Wrap the structured payload so we preserve the ok flag.
                    # On reload, the UI uses `ok` to decide whether to render
                    # this row as a success table or a "query failed" panel.
                    persisted_data: dict[str, Any] = {
                        "ok": ev.ok,
                        "data": ev.data,
                    }
                    async with get_session() as session:
                        await conv_svc.append_message(
                            session,
                            conversation_id=conversation_id,
                            role="tool",
                            content=ev.summary,
                            tool_call_id=ev.call_id,
                            tool_data=persisted_data,
                        )
                elif isinstance(ev, ErrorEvent):
                    had_error = True
                elif isinstance(ev, DoneEvent):
                    break
        except Exception as exc:  # noqa: BLE001
            log.exception("chat.stream.unhandled")
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "message": f"unhandled error: {exc}"}),
            }
            had_error = True

        # Flush trailing assistant text, success or partial.
        if accumulated_text:
            await _flush_text_row(conversation_id, accumulated_text)

    return EventSourceResponse(event_stream())


def _tool_call_payload(ev: ToolCallEvent) -> dict[str, Any]:
    """Chat-completions tool-call representation we persist + replay."""
    return {
        "id": ev.call_id,
        "type": "function",
        "function": {
            "name": ev.name,
            "arguments": json.dumps(ev.arguments, default=str),
        },
    }


async def _flush_text_row(conversation_id: uuid.UUID, parts: list[str]) -> None:
    text = "".join(parts)
    if not text:
        return
    async with get_session() as session:
        await conv_svc.append_message(
            session,
            conversation_id=conversation_id,
            role="assistant",
            content=text,
        )
