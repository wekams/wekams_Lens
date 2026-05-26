"""Tool definitions exposed to the LLM, and the code that executes them.

Phase 1b has one tool: `query_data`. Phase 2 will add `search_logs`,
`describe_table`, `list_files`, etc. Each tool is:

  1. A `ToolDefinition` (schema the LLM sees)
  2. An async function `_execute_<name>` that runs it server-side

Tools are intentionally small and side-effect-free. The orchestrator wraps
them with timeout, row caps, error handling, and audit logging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import service, vault
from app.connectors import ConnectorError, get_connector
from app.core.logging import get_logger
from app.llm import ToolCall, ToolDefinition, ToolParameter
from app.orchestrator.federation import FederationEngine, _alias as federation_alias
from app.orchestrator.sql_validator import (
    build_catalog_from_orm_tables,
    validate_sql,
)

log = get_logger(__name__)


# ── Tool: query_data ────────────────────────────────────────────────


QUERY_DATA = ToolDefinition(
    name="query_data",
    description=(
        "Run a single read-only query against a registered data source. "
        "Use this whenever the user asks a question that requires looking "
        "up real data. Aggregate at the source rather than returning many "
        "rows."
    ),
    parameters=[
        ToolParameter(
            name="source",
            type="string",
            description=(
                "Name of the registered source to query, exactly as shown in "
                "DATA SOURCES."
            ),
            required=True,
        ),
        ToolParameter(
            name="sql",
            type="string",
            description=(
                "The query. For relational sources (postgres / sqlite / s3 / "
                "logs) write a SQL SELECT. For Elasticsearch / OpenSearch "
                "sources write a JSON Query DSL body — see the per-source "
                "hint in DATA SOURCES. No DDL or DML in either case."
            ),
            required=True,
        ),
    ],
)


@dataclass(slots=True)
class ToolResult:
    """What we send back to the LLM and surface to the UI."""

    name: str
    arguments: dict[str, Any]
    ok: bool
    # Compact human-readable summary the model will see.
    content: str
    # Optional structured payload the UI can render (e.g., table data).
    data: dict[str, Any] | None = None


async def _execute_query_data(
    session: AsyncSession,
    *,
    source_name: str,
    sql: str,
) -> ToolResult:
    log.info("tool.query_data.invoked", source=source_name, sql=sql)

    source = await service.get_source_by_name_with_schema(session, source_name)
    if source is None:
        msg = f"Unknown source {source_name!r}. List available sources first."
        return ToolResult(name=QUERY_DATA.name, arguments={"source": source_name, "sql": sql}, ok=False, content=msg)

    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)

    # Schema-aware pre-flight check. Catches LLM hallucinations (missing
    # tables / columns / parse errors) before round-tripping to the source.
    # The error message is designed to be surfaced back to the LLM so the
    # next turn corrects itself in the existing tool-use loop.
    catalog = build_catalog_from_orm_tables(source.tables, source_type=source_type)
    validation = validate_sql(sql, catalog)
    if not validation.ok:
        log.info(
            "tool.query_data.validation_failed",
            source=source_name,
            errors=[e.kind for e in validation.errors],
        )
        return ToolResult(
            name=QUERY_DATA.name,
            arguments={"source": source_name, "sql": sql},
            ok=False,
            content=validation.summary_for_llm(),
        )

    creds = (
        json.loads(vault.decrypt(source.credentials_enc))
        if source.credentials_enc
        else {}
    )
    connector = get_connector(source_type, config=source.config, credentials=creds)

    try:
        result = await connector.execute(sql, max_rows=1000, timeout_seconds=30)
    except ConnectorError as exc:
        log.warning("tool.query_data.failed", source=source_name, error=str(exc))
        return ToolResult(
            name=QUERY_DATA.name,
            arguments={"source": source_name, "sql": sql},
            ok=False,
            content=f"Query failed: {exc}",
        )

    # Compact serialization for the LLM. Truncate large rowsets.
    preview_rows = result.rows[:50]
    json_rows = [
        {col: _json_safe(val) for col, val in zip(result.columns, row, strict=False)}
        for row in preview_rows
    ]
    summary = (
        f"{result.row_count} row(s) returned"
        + (" (showing first 50)" if result.row_count > 50 else "")
        + (" (truncated by 1000-row cap)" if result.truncated else "")
        + ".\n"
        + json.dumps({"columns": result.columns, "rows": json_rows}, default=str)
    )

    return ToolResult(
        name=QUERY_DATA.name,
        arguments={"source": source_name, "sql": sql},
        ok=True,
        content=summary,
        data={
            "columns": result.columns,
            "rows": json_rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
        },
    )


def _json_safe(v: Any) -> Any:
    """Datetime / decimal / uuid / etc. → JSON-safe primitive."""
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v.hex()
    return v


# ── Tool: query_federated ───────────────────────────────────────────


QUERY_FEDERATED = ToolDefinition(
    name="query_federated",
    description=(
        "Run a single read-only DuckDB SQL SELECT that JOINs across two or "
        "more registered data sources. Use this when the question requires "
        "combining data from different sources (e.g., a Postgres table and "
        "an S3 file). For single-source questions, prefer query_data. Each "
        "source is exposed under its federation alias (see DATA SOURCES). "
        "Reference Postgres tables as alias.schema.table and S3 files as "
        "alias.table. The sources array must list the source names being "
        "joined."
    ),
    parameters=[
        ToolParameter(
            name="sources",
            type="array",
            description=(
                "Names of the registered sources to attach for this query, "
                "exactly as shown in DATA SOURCES. Must include at least two."
            ),
            required=True,
        ),
        ToolParameter(
            name="sql",
            type="string",
            description=(
                "A single read-only SELECT statement that references each "
                "source via its federation alias."
            ),
            required=True,
        ),
    ],
)


async def _execute_query_federated(
    session: AsyncSession,
    *,
    source_names: list[str],
    sql: str,
) -> ToolResult:
    log.info("tool.query_federated.invoked", sources=source_names, sql=sql)
    args_echo = {"sources": source_names, "sql": sql}

    if len(source_names) < 2:
        return ToolResult(
            name=QUERY_FEDERATED.name,
            arguments=args_echo,
            ok=False,
            content="query_federated requires at least two sources. Use query_data for single-source queries.",
        )

    sources = []
    missing: list[str] = []
    for n in source_names:
        s = await service.get_source_by_name(session, n)
        if s is None:
            missing.append(n)
        else:
            sources.append(s)
    if missing:
        return ToolResult(
            name=QUERY_FEDERATED.name,
            arguments=args_echo,
            ok=False,
            content=f"Unknown source(s): {missing}. List available sources first.",
        )

    engine = FederationEngine(sources)
    try:
        result = await engine.execute(sql, max_rows=1000, timeout_seconds=60)
    except ConnectorError as exc:
        log.warning("tool.query_federated.failed", error=str(exc))
        return ToolResult(
            name=QUERY_FEDERATED.name,
            arguments=args_echo,
            ok=False,
            content=f"Federated query failed: {exc}",
        )

    preview_rows = result.rows[:50]
    json_rows = [
        {col: _json_safe(val) for col, val in zip(result.columns, row, strict=False)}
        for row in preview_rows
    ]
    summary = (
        f"{result.row_count} row(s) returned"
        + (" (showing first 50)" if result.row_count > 50 else "")
        + (" (truncated by 1000-row cap)" if result.truncated else "")
        + ".\n"
        + json.dumps({"columns": result.columns, "rows": json_rows}, default=str)
    )

    return ToolResult(
        name=QUERY_FEDERATED.name,
        arguments=args_echo,
        ok=True,
        content=summary,
        data={
            "columns": result.columns,
            "rows": json_rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
        },
    )


# ── Dispatch ────────────────────────────────────────────────────────


ALL_TOOLS: list[ToolDefinition] = [QUERY_DATA, QUERY_FEDERATED]


async def execute_tool_call(
    session: AsyncSession,
    call: ToolCall,
) -> ToolResult:
    if call.name == QUERY_DATA.name:
        return await _execute_query_data(
            session,
            source_name=str(call.arguments.get("source", "")),
            sql=str(call.arguments.get("sql", "")),
        )
    if call.name == QUERY_FEDERATED.name:
        raw_sources = call.arguments.get("sources", [])
        # Some models occasionally hand back a JSON-encoded string in array args.
        if isinstance(raw_sources, str):
            try:
                raw_sources = json.loads(raw_sources)
            except json.JSONDecodeError:
                raw_sources = [raw_sources]
        if not isinstance(raw_sources, list):
            raw_sources = [str(raw_sources)]
        return await _execute_query_federated(
            session,
            source_names=[str(s) for s in raw_sources],
            sql=str(call.arguments.get("sql", "")),
        )

    return ToolResult(
        name=call.name,
        arguments=call.arguments,
        ok=False,
        content=f"Unknown tool {call.name!r}.",
    )
