"""REST endpoints for chat conversation history.

GET    /api/v1/conversations           — list, most-recent first
POST   /api/v1/conversations           — create a new conversation
GET    /api/v1/conversations/{id}      — full conversation with messages
PATCH  /api/v1/conversations/{id}      — rename
DELETE /api/v1/conversations/{id}      — delete
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.catalog import conversations as svc
from app.catalog.db import get_session
from app.catalog.export_markdown import render_conversation_markdown
from app.catalog.models import ChatMessage, Conversation

router = APIRouter(
    prefix="/api/v1/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_auth)],
)


class MessageView(BaseModel):
    id: uuid.UUID
    sequence: int
    role: str
    content: str = ""
    tool_calls: list | None = None
    tool_call_id: str | None = None
    tool_data: dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, m: ChatMessage) -> MessageView:
        return cls(
            id=m.id,
            sequence=m.sequence,
            role=m.role,
            content=m.content or "",
            tool_calls=m.tool_calls,
            tool_call_id=m.tool_call_id,
            tool_data=m.tool_data,
            created_at=m.created_at,
        )


class ConversationView(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    messages: list[MessageView] = Field(default_factory=list)

    @classmethod
    def from_model(cls, c: Conversation, *, include_messages: bool = False) -> ConversationView:
        return cls(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=len(c.messages),
            messages=[MessageView.from_model(m) for m in c.messages] if include_messages else [],
        )


class CreateConversationRequest(BaseModel):
    title: str | None = None


class RenameConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


@router.get("", response_model=list[ConversationView])
async def list_conversations() -> list[ConversationView]:
    async with get_session() as session:
        convs = await svc.list_conversations(session)
        return [ConversationView.from_model(c) for c in convs]


@router.post("", response_model=ConversationView, status_code=status.HTTP_201_CREATED)
async def create_conversation(req: CreateConversationRequest) -> ConversationView:
    async with get_session() as session:
        c = await svc.create_conversation(session, title=req.title)
        return ConversationView.from_model(c, include_messages=True)


@router.get("/{conversation_id}", response_model=ConversationView)
async def get_conversation(conversation_id: uuid.UUID) -> ConversationView:
    async with get_session() as session:
        c = await svc.get_conversation(session, conversation_id)
        if c is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        return ConversationView.from_model(c, include_messages=True)


@router.patch("/{conversation_id}", response_model=ConversationView)
async def rename_conversation(
    conversation_id: uuid.UUID, req: RenameConversationRequest
) -> ConversationView:
    async with get_session() as session:
        c = await svc.rename_conversation(session, conversation_id, title=req.title)
        if c is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        return ConversationView.from_model(c)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID) -> None:
    async with get_session() as session:
        ok = await svc.delete_conversation(session, conversation_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")


@router.get(
    "/{conversation_id}/export.md",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def export_conversation_markdown(
    conversation_id: uuid.UUID, download: bool = False
) -> Response:
    """Render the conversation as a Markdown transcript.

    Pass ?download=1 to set a Content-Disposition attachment header
    so browsers offer it as a `.md` file save.
    """
    async with get_session() as session:
        c = await svc.get_conversation(session, conversation_id)
        if c is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        body = render_conversation_markdown(c)
        title = c.title

    headers: dict[str, str] = {}
    if download:
        # Best-effort safe filename derivation.
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in title).strip() or "conversation"
        headers["Content-Disposition"] = f'attachment; filename="{safe[:80]}.md"'

    return Response(content=body, media_type="text/markdown; charset=utf-8", headers=headers)
