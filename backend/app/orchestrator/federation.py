"""Federation engine — JOINs across vendor boundaries via DuckDB.

For a federated query, we spin up a DuckDB connection and:

  • For each Postgres source → ATTACH it natively as a read-only database
    aliased by the source's normalized name.
  • For each S3 source → install httpfs, register an S3 SECRET, and
    CREATE VIEW per file under a schema named after the source alias.

The LLM then writes a single SQL statement that references all sources
via their alias (e.g. `demo_shop.public.customers JOIN demo_lake.web_events`).

This is the differentiator. None of Snowflake Cortex, Databricks Genie,
Fabric Copilot, or BigQuery's Gemini answer a question that spans a
competitor's warehouse + a customer's S3 in one query. We do.

Phase 2b runs each query in a fresh DuckDB connection. Pooling +
prepared-statement caches arrive in Phase 3+.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import duckdb

from app.catalog import vault
from app.catalog.models import Source
from app.connectors.base import ConnectorError, QueryResult
from app.connectors.logs import _safe_identifier as _logs_safe_identifier
from app.connectors.s3 import _KNOWN_EXTENSIONS, _reader_expr, _safe_table_name
from app.core.logging import get_logger

log = get_logger(__name__)


# Same read-only gate as the per-source connectors. DuckDB is the engine
# here so we also block DuckDB-specific write/admin statements.
_WRITE_STATEMENTS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"comment|reindex|vacuum|analyze|copy|call|attach|detach|use|set|export)\b",
    re.IGNORECASE,
)


def _alias(name: str) -> str:
    """Normalize a source's display name into a DuckDB-safe identifier.

    `demo-shop` → `demo_shop`. Stable for a given name, idempotent.
    """
    a = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_").lower()
    if not a:
        a = "src"
    if a[0].isdigit():
        a = "_" + a
    return a


@dataclass(slots=True)
class _SourceBinding:
    source: Source
    alias: str
    creds: dict[str, Any]


class FederationEngine:
    """One instance = one query. Stateless across calls."""

    def __init__(self, sources: list[Source]) -> None:
        self._sources = sources
        self._bindings: list[_SourceBinding] = []
        for s in sources:
            creds = (
                json.loads(vault.decrypt(s.credentials_enc))
                if s.credentials_enc
                else {}
            )
            self._bindings.append(_SourceBinding(source=s, alias=_alias(s.name), creds=creds))

    def aliases(self) -> dict[str, str]:
        """Map of original source name → federation alias used in SQL."""
        return {b.source.name: b.alias for b in self._bindings}

    async def execute(
        self,
        sql: str,
        *,
        max_rows: int = 10_000,
        timeout_seconds: int = 60,
    ) -> QueryResult:
        if _WRITE_STATEMENTS.search(sql):
            raise ConnectorError(
                "federation is read-only — only SELECT / WITH / VALUES statements are allowed."
            )
        return await asyncio.to_thread(self._execute_sync, sql, max_rows, timeout_seconds)

    # ── internals ──────────────────────────────────────────────────

    def _execute_sync(self, sql: str, max_rows: int, timeout_seconds: int) -> QueryResult:
        con = duckdb.connect()
        try:
            self._prepare(con)
            try:
                cur = con.execute(sql)
            except duckdb.Error as exc:
                raise ConnectorError(f"federated query failed: {exc}") from exc
            columns = [d[0] for d in cur.description] if cur.description else []
            rows_raw = cur.fetchall()
            truncated = len(rows_raw) > max_rows
            rows = rows_raw[:max_rows]
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
            )
        finally:
            con.close()

    def _prepare(self, con: duckdb.DuckDBPyConnection) -> None:
        """Attach Postgres sources + register S3 views with stable aliases."""
        # Always-on extensions. Cheap if already cached.
        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute("INSTALL httpfs; LOAD httpfs;")

        for binding in self._bindings:
            t = binding.source.type
            t_str = t.value if hasattr(t, "value") else str(t)
            if t_str == "postgres":
                self._attach_postgres(con, binding)
            elif t_str == "s3":
                self._attach_s3(con, binding)
            elif t_str == "logs":
                self._attach_logs(con, binding)
            else:
                log.warning(
                    "federation.unsupported_source_type",
                    source=binding.source.name,
                    type=t_str,
                )

    def _attach_postgres(self, con: duckdb.DuckDBPyConnection, b: _SourceBinding) -> None:
        cfg = b.source.config
        password = b.creds.get("password", "")
        # DuckDB's Postgres ATTACH uses libpq connection-string format. We
        # quote-escape any single quotes in values defensively even though
        # we control these inputs.
        parts = [
            f"host={_esc(cfg.get('host', 'localhost'))}",
            f"port={int(cfg.get('port', 5432))}",
            f"user={_esc(cfg.get('user', ''))}",
            f"dbname={_esc(cfg.get('database', ''))}",
        ]
        if password:
            parts.append(f"password={_esc(password)}")
        conn_str = " ".join(parts)
        con.execute(
            f"ATTACH '{conn_str}' AS {b.alias} (TYPE POSTGRES, READ_ONLY)"
        )
        log.info("federation.attach.postgres", source=b.source.name, alias=b.alias)

    def _attach_s3(self, con: duckdb.DuckDBPyConnection, b: _SourceBinding) -> None:
        cfg = b.source.config
        access_key = b.creds.get("access_key") or cfg.get("access_key", "")
        secret_key = b.creds.get("secret_access_key", "")
        endpoint_raw = (cfg.get("endpoint") or "").strip()
        url_style = (cfg.get("url_style") or ("path" if endpoint_raw else "vhost")).lower()
        region = cfg.get("region") or "us-east-1"

        parts: list[str] = []
        if access_key:
            parts.append(f"KEY_ID '{_esc(access_key)}'")
        if secret_key:
            parts.append(f"SECRET '{_esc(secret_key)}'")
        parts.append(f"REGION '{_esc(region)}'")
        if endpoint_raw:
            parsed = urlparse(endpoint_raw if "://" in endpoint_raw else f"//{endpoint_raw}")
            host = parsed.netloc or parsed.path
            use_ssl = "true" if parsed.scheme == "https" else "false"
            parts.append(f"ENDPOINT '{_esc(host)}'")
            parts.append(f"USE_SSL {use_ssl}")
        parts.append(f"URL_STYLE '{_esc(url_style)}'")

        # Use a uniquely-named secret per source alias so multiple S3
        # sources with different credentials can coexist in the same query.
        con.execute(f"CREATE OR REPLACE SECRET wekams_{b.alias} (TYPE S3, {', '.join(parts)})")

        # Create one schema per source alias and register a view per file.
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {b.alias}")
        bucket = (cfg.get("bucket") or "").strip()
        prefix = (cfg.get("prefix") or "").strip().lstrip("/")
        base = f"s3://{bucket}/" + (f"{prefix}/" if prefix and not prefix.endswith("/") else prefix)

        files: dict[str, str] = {}
        for ext in _KNOWN_EXTENSIONS:
            try:
                rows = con.execute("SELECT file FROM glob(?)", [f"{base}**/*{ext}"]).fetchall()
            except duckdb.IOException:
                continue
            for (path,) in rows:
                files[_safe_table_name(PurePosixPath(path).name)] = path

        for table_name, s3_url in files.items():
            con.execute(
                f"CREATE OR REPLACE VIEW {b.alias}.{table_name} "
                f"AS SELECT * FROM {_reader_expr(s3_url)}"
            )

        log.info(
            "federation.attach.s3",
            source=b.source.name,
            alias=b.alias,
            files=len(files),
        )

    def _attach_logs(self, con: duckdb.DuckDBPyConnection, b: _SourceBinding) -> None:
        """Logs sources become a single view under the source's alias schema."""
        cfg = b.source.config
        glob = (cfg.get("path") or "").strip()
        if not glob:
            log.warning("federation.logs.no_path", source=b.source.name)
            return
        glob = glob.replace("'", "''")
        table = _logs_safe_identifier((cfg.get("table_name") or "").strip()) or "events"
        # Best-effort name derivation when table_name isn't set explicitly.
        if not (cfg.get("table_name") or "").strip():
            from pathlib import Path
            table = _logs_safe_identifier(Path(cfg.get("path", "")).parent.name) or "events"

        reader = (
            f"read_json_auto('{glob}', union_by_name=true, "
            f"maximum_object_size=16777216)"
        )
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {b.alias}")
        con.execute(
            f"CREATE OR REPLACE VIEW {b.alias}.{table} AS SELECT * FROM {reader}"
        )
        log.info(
            "federation.attach.logs",
            source=b.source.name,
            alias=b.alias,
            table=table,
        )


def _esc(v: object) -> str:
    return str(v).replace("'", "''")
