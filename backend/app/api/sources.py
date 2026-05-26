"""REST endpoints for managing data sources.

GET    /api/v1/sources                — list registered sources
POST   /api/v1/sources                — register a new source
GET    /api/v1/sources/{id}           — get one source with tables/columns
DELETE /api/v1/sources/{id}           — remove a source
POST   /api/v1/sources/{id}/sync      — re-introspect a source
POST   /api/v1/sources/test           — dry-run a connection without saving
GET    /api/v1/sources/types          — list available connector types
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.audit import emit as audit_emit
from app.auth import require_auth
from app.catalog import service
from app.catalog.db import SessionLocal, get_session
from app.catalog.models import Source, SourceType
from app.connectors import ConnectorError
from app.connectors.registry import describe_types, is_supported_type, supported_types
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/sources",
    tags=["sources"],
    dependencies=[Depends(require_auth)],
)


# ── Schemas ──────────────────────────────────────────────────────────


class ConnectionFields(BaseModel):
    """Free-form connection details. Validated per source type by the
    connector itself — at the API boundary we accept any dict."""

    model_config = {"extra": "allow"}


class CreateSourceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    # Plain string so custom connectors (registered via plugin discovery)
    # are accepted. We validate against the registry inside the handler
    # rather than fixing the set of supported types at this boundary.
    type: str = Field(..., min_length=1, max_length=64)
    connection: dict[str, Any]


class TestSourceRequest(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    connection: dict[str, Any]


class ColumnView(BaseModel):
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    position: int
    description: str | None = None


class TableView(BaseModel):
    schema_name: str
    name: str
    description: str | None = None
    row_count_est: int | None = None
    columns: list[ColumnView] = Field(default_factory=list)


class SourceView(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    status: str
    config: dict[str, Any]
    last_error: str | None = None
    tables: list[TableView] = Field(default_factory=list)

    @classmethod
    def from_model(cls, source: Source, *, include_tables: bool = False) -> SourceView:
        tables: list[TableView] = []
        if include_tables:
            for t in source.tables:
                tables.append(
                    TableView(
                        schema_name=t.schema_name,
                        name=t.name,
                        description=t.description,
                        row_count_est=t.row_count_est,
                        columns=[
                            ColumnView(
                                name=c.name,
                                data_type=c.data_type,
                                nullable=c.nullable,
                                is_primary_key=c.is_primary_key,
                                position=c.position,
                                description=c.description,
                            )
                            for c in t.columns
                        ],
                    )
                )
        type_str = source.type.value if hasattr(source.type, "value") else str(source.type)
        status_str = (
            source.status.value if hasattr(source.status, "value") else str(source.status)
        )
        return cls(
            id=source.id,
            name=source.name,
            type=type_str,
            status=status_str,
            config=source.config,
            last_error=source.last_error,
            tables=tables,
        )


# ── Background task ──────────────────────────────────────────────────


async def _sync_in_background(source_id: uuid.UUID) -> None:
    """Run schema sync in its own session — BackgroundTasks executes after
    the response is sent so we can't reuse the request's session."""
    try:
        async with get_session() as session:
            await service.sync_schema(session, source_id)
    except Exception:  # noqa: BLE001 — top of the background task
        log.exception("sources.sync.background_failed", source_id=str(source_id))


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/types", response_model=list[str])
async def list_types() -> list[str]:
    """Compact list of registered connector type strings."""
    return supported_types()


@router.get("/types/details")
async def list_type_details() -> list[dict]:
    """Per-type metadata for the UI source picker: display name, which
    fields are secret, whether the connector is built-in or a plugin."""
    return describe_types()


@router.get("", response_model=list[SourceView])
async def list_sources_endpoint() -> list[SourceView]:
    async with get_session() as session:
        sources = await service.list_sources(session)
        return [SourceView.from_model(s) for s in sources]


@router.post("", response_model=SourceView, status_code=status.HTTP_201_CREATED)
async def create_source_endpoint(
    req: CreateSourceRequest,
    background: BackgroundTasks,
) -> SourceView:
    if not is_supported_type(req.type):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported source type {req.type!r}. Available: {', '.join(supported_types())}",
        )
    try:
        async with get_session() as session:
            source = await service.create_source(
                session,
                name=req.name,
                source_type=req.type,
                body=req.connection,
            )
            view = SourceView.from_model(source)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit_emit(
        "source.created",
        source_name=req.name,
        source_type=req.type,
    )
    # Kick off introspection after the response goes out.
    background.add_task(_sync_in_background, view.id)
    return view


@router.get("/{source_id}", response_model=SourceView)
async def get_source_endpoint(source_id: uuid.UUID) -> SourceView:
    async with get_session() as session:
        source = await service.get_source(session, source_id)
        if source is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
        return SourceView.from_model(source, include_tables=True)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_endpoint(source_id: uuid.UUID) -> None:
    async with get_session() as session:
        # Capture name before deletion for the audit record.
        existing = await service.get_source(session, source_id)
        name = existing.name if existing else str(source_id)
        ok = await service.delete_source(session, source_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    await audit_emit("source.deleted", source_name=name, source_id=str(source_id))


@router.post("/{source_id}/sync", response_model=SourceView)
async def sync_source_endpoint(source_id: uuid.UUID) -> SourceView:
    """Synchronous re-introspect. Useful for tests and small sources;
    larger deployments will trigger this via the background task."""
    async with get_session() as session:
        try:
            source = await service.sync_schema(session, source_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        view = SourceView.from_model(source, include_tables=True)
    await audit_emit(
        "source.synced",
        source_name=source.name,
        table_count=len(view.tables) if view.tables else 0,
    )
    return view


@router.post("/test")
async def test_source_endpoint(req: TestSourceRequest) -> dict:
    if not is_supported_type(req.type):
        return {
            "ok": False,
            "error": f"Unsupported source type {req.type!r}. Available: {', '.join(supported_types())}",
        }
    try:
        ok = await service.test_connection(req.type, req.connection)
    except ConnectorError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — connector misbehaves
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": ok}
