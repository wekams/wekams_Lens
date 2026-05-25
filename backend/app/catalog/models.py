"""Catalog ORM models — Wekams Lens's own state.

A `Source` is a registered data system (Postgres DB, S3 bucket, etc.).
A `Table` is a queryable entity inside a source (Postgres table, Parquet
file in a bucket, Mongo collection, etc.). A `Column` is a field within
a Table.

Sample rows, glossary, lineage, query history, policies, users — all
arrive in later sub-phases. This is the minimum needed for Phase 1a.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for catalog tables."""


class SourceType(StrEnum):
    POSTGRES = "postgres"
    MYSQL = "mysql"
    S3 = "s3"
    MONGODB = "mongodb"
    FILES = "files"


class SourceStatus(StrEnum):
    PENDING = "pending"        # just added, not yet introspected
    READY = "ready"            # introspection succeeded
    ERROR = "error"            # last sync failed
    DISABLED = "disabled"      # admin-disabled


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[SourceType] = mapped_column(String(32), nullable=False)
    status: Mapped[SourceStatus] = mapped_column(
        String(32), nullable=False, default=SourceStatus.PENDING
    )
    # Connection details (host, port, db, ssl mode, etc.) — non-secret.
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Encrypted credential blob (password, key) — see vault.py.
    credentials_enc: Mapped[bytes | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(String, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    tables: Mapped[list[Table]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Table(Base):
    __tablename__ = "tables"
    __table_args__ = (
        UniqueConstraint("source_id", "schema_name", "name", name="uq_table_qualified"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False, default="public")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Free-text description — may be admin-curated or LLM-generated.
    description: Mapped[str | None] = mapped_column(String, default=None)
    row_count_est: Mapped[int | None] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source: Mapped[Source] = relationship(back_populates="tables")
    columns: Mapped[list[Column]] = relationship(
        back_populates="table",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Column.position",
    )


class Conversation(Base):
    """One chat thread. Owns an ordered list of ChatMessage rows."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.sequence",
    )


class ChatMessage(Base):
    """One turn in a Conversation.

    Stores enough to replay the full chat to the LLM, including tool calls
    and tool results. `role` is one of {system, user, assistant, tool}.
    `tool_calls` and `tool_call_id` are non-null only for the corresponding
    roles (assistant-with-tools / tool, respectively).
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_message_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Chat-completions tool-call list when role == "assistant" and the model called tools.
    tool_calls: Mapped[list | None] = mapped_column(JSON, default=None)
    # Set when role == "tool"; matches the id of the assistant tool_call.
    tool_call_id: Mapped[str | None] = mapped_column(String(128), default=None)
    # Optional structured payload from a tool result — preserved verbatim so
    # the UI can re-render tables, etc. when reloading a conversation.
    tool_data: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Column(Base):
    __tablename__ = "columns"
    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uq_column_per_table"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tables.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    nullable: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_primary_key: Mapped[bool] = mapped_column(default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String, default=None)

    table: Mapped[Table] = relationship(back_populates="columns")
