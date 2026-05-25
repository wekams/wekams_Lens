"""Catalog service — orchestration over models + connectors.

API endpoints call into here; nothing in this module knows about HTTP.
That separation keeps the unit tests fast and lets the Slack bot, MCP
server, and CLI reuse the same logic later.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import vault
from app.catalog.models import Column, Source, SourceStatus, Table
from app.connectors import ConnectorError, get_connector
from app.connectors.registry import credential_keys_for
from app.core.logging import get_logger

log = get_logger(__name__)


def _split_secrets(source_type: str, body: dict) -> tuple[dict, dict]:
    """Return (non_secret_config, credentials_to_encrypt).

    Each Connector subclass declares its own `credential_keys` so plugins
    discovered at runtime don't need a hard-coded entry here.
    """
    secret_keys = credential_keys_for(source_type)
    creds: dict = {}
    config: dict = {}
    for k, v in body.items():
        if k in secret_keys:
            creds[k] = v
        else:
            config[k] = v
    return config, creds


async def list_sources(session: AsyncSession) -> list[Source]:
    result = await session.scalars(select(Source).order_by(Source.created_at))
    return list(result)


async def get_source(session: AsyncSession, source_id: uuid.UUID) -> Source | None:
    return await session.get(Source, source_id)


async def get_source_by_name(session: AsyncSession, name: str) -> Source | None:
    return await session.scalar(select(Source).where(Source.name == name))


async def test_connection(source_type: str, body: dict) -> bool:
    """Try to connect without persisting anything. Used by the 'Test' button
    in the Add Source UI."""
    config, creds = _split_secrets(source_type, body)
    connector = get_connector(source_type, config=config, credentials=creds)
    return await connector.healthcheck()


async def create_source(
    session: AsyncSession,
    *,
    name: str,
    source_type: str,
    body: dict,
) -> Source:
    """Persist a new source. Does NOT introspect — call sync_schema separately
    (typically in a background task)."""
    existing = await get_source_by_name(session, name)
    if existing is not None:
        raise ValueError(f"source with name {name!r} already exists")

    config, creds = _split_secrets(source_type, body)
    credentials_enc = vault.encrypt(json.dumps(creds)) if creds else None

    source = Source(
        name=name,
        # The Source.type column is a String — accept any registered type
        # name (built-in or custom plugin) verbatim.
        type=source_type,
        status=SourceStatus.PENDING,
        config=config,
        credentials_enc=credentials_enc,
    )
    session.add(source)
    await session.flush()
    log.info("catalog.source.created", source_id=str(source.id), type=source_type, name=name)
    return source


async def delete_source(session: AsyncSession, source_id: uuid.UUID) -> bool:
    source = await session.get(Source, source_id)
    if source is None:
        return False
    await session.delete(source)
    log.info("catalog.source.deleted", source_id=str(source_id))
    return True


async def sync_schema(session: AsyncSession, source_id: uuid.UUID) -> Source:
    """Introspect the source and refresh catalog tables/columns.

    Drops existing Tables/Columns for this source and rebuilds. Phase 2 will
    do diff-based updates so we preserve LLM-generated descriptions.
    """
    source = await session.get(Source, source_id)
    if source is None:
        raise ValueError(f"source {source_id} not found")

    creds = (
        json.loads(vault.decrypt(source.credentials_enc))
        if source.credentials_enc
        else {}
    )
    # source.type is loaded as a plain str by SQLAlchemy (column type is String,
    # not Enum). The orchestrator and connectors only need the type string.
    source_type_str = source.type.value if hasattr(source.type, "value") else str(source.type)
    connector = get_connector(source_type_str, config=source.config, credentials=creds)

    try:
        introspected = await connector.introspect()
    except ConnectorError as exc:
        source.status = SourceStatus.ERROR
        source.last_error = str(exc)
        await session.flush()
        log.warning("catalog.source.sync_failed", source_id=str(source_id), error=str(exc))
        return source

    # Clear existing — Phase 2 turns this into a diff.
    for existing_table in list(source.tables):
        await session.delete(existing_table)
    await session.flush()

    for t in introspected:
        table = Table(
            source_id=source.id,
            schema_name=t.schema_name,
            name=t.name,
            description=t.description,
            row_count_est=t.row_count_est,
        )
        session.add(table)
        await session.flush()
        for c in t.columns:
            session.add(
                Column(
                    table_id=table.id,
                    name=c.name,
                    data_type=c.data_type,
                    nullable=c.nullable,
                    is_primary_key=c.is_primary_key,
                    position=c.position,
                    description=c.description,
                )
            )

    source.status = SourceStatus.READY
    source.last_error = None
    source.last_synced_at = datetime.now(timezone.utc)
    await session.flush()

    log.info(
        "catalog.source.synced",
        source_id=str(source_id),
        tables=len(introspected),
        columns=sum(len(t.columns) for t in introspected),
    )
    return source
