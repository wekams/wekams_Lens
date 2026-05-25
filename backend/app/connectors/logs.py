"""LogsConnector — read JSON-lines log files (one stream per source).

The single biggest missing piece for the "logs + structured + unstructured
in one query" wedge from POSITIONING.md §4. A registered logs source is
a (path-glob, table-name) pair pointing at a directory of `.log` /
`.jsonl` / `.ndjson` files. Each line is a JSON object; DuckDB's
`read_json_auto` reads them natively and unions schemas across files.

Phase 3a covers JSON-lines logs only. CLF / syslog / regex-based parsing
arrives in Phase 3a-ext; Elasticsearch / OpenSearch as Phase 3b.

Same DuckDB-backed pattern as the S3 connector — every execute() spins up
a fresh DuckDB connection, registers a view over the glob, runs the user's
SQL. Read-only at the connector boundary (write statements rejected by
the standard regex gate before they reach the engine).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import duckdb

from app.connectors.base import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
)
from app.core.logging import get_logger

log = get_logger(__name__)

_WRITE_STATEMENTS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"comment|reindex|vacuum|analyze|copy|call|attach|detach|use|set|export)\b",
    re.IGNORECASE,
)


def _safe_identifier(s: str) -> str:
    """Make `s` a valid DuckDB unquoted identifier (lowercase, [a-z0-9_])."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", s).strip("_").lower()
    if not s:
        s = "events"
    if s[0].isdigit():
        s = "_" + s
    return s


class LogsConnector(Connector):
    type = "logs"
    display_name = "Application logs (JSON lines)"
    credential_keys = frozenset()  # filesystem perms; no secrets

    # ── helpers ────────────────────────────────────────────────────

    def _glob(self) -> str:
        g = (self.config.get("path") or "").strip()
        if not g:
            raise ConnectorError("logs connector requires a `path` (glob).")
        # DuckDB accepts globs in the file path string itself.
        return str(Path(g).expanduser())

    def _table_name(self) -> str:
        # Explicit override → derived from parent dir → 'events'.
        explicit = (self.config.get("table_name") or "").strip()
        if explicit:
            return _safe_identifier(explicit)
        g = self._glob()
        parent = Path(g).parent.name
        return _safe_identifier(parent or "events")

    def _new_connection(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect()

    def _reader_expr(self) -> str:
        # Single quotes around the glob; DuckDB read_json_auto handles
        # newline-delimited JSON automatically (format='auto' default).
        g = self._glob().replace("'", "''")
        return f"read_json_auto('{g}', union_by_name=true, maximum_object_size=16777216)"

    # ── connector contract ─────────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("logs.healthcheck.failed", error=str(exc))
            return False

    def _healthcheck_sync(self) -> bool:
        g = self._glob()
        # Ensure at least one file matches; helpful error if not.
        matches = list(Path("/").glob(g.lstrip("/"))) if g.startswith("/") else list(Path(".").glob(g))
        if not matches:
            return False
        con = self._new_connection()
        try:
            con.execute(f"SELECT 1 FROM {self._reader_expr()} LIMIT 1").fetchone()
            return True
        finally:
            con.close()

    async def introspect(self) -> list[IntrospectedTable]:
        return await asyncio.to_thread(self._introspect_sync)

    def _introspect_sync(self) -> list[IntrospectedTable]:
        con = self._new_connection()
        try:
            try:
                schema_rows = con.execute(
                    f"DESCRIBE SELECT * FROM {self._reader_expr()} LIMIT 1"
                ).fetchall()
            except duckdb.Error as exc:
                raise ConnectorError(f"could not infer schema from logs: {exc}") from exc

            columns: list[IntrospectedColumn] = []
            for i, row in enumerate(schema_rows, start=1):
                columns.append(
                    IntrospectedColumn(
                        name=row[0],
                        data_type=row[1],
                        nullable=True,
                        is_primary_key=False,
                        position=i,
                    )
                )

            row_count_est: int | None = None
            try:
                row_count_est = int(
                    con.execute(
                        f"SELECT COUNT(*) FROM {self._reader_expr()}"
                    ).fetchone()[0]
                )
            except duckdb.Error:
                pass

            return [
                IntrospectedTable(
                    schema_name="logs",
                    name=self._table_name(),
                    description=f"JSON-lines logs from {self._glob()}",
                    row_count_est=row_count_est,
                    columns=columns,
                )
            ]
        finally:
            con.close()

    async def execute(
        self,
        sql: str,
        *,
        max_rows: int = 10_000,
        timeout_seconds: int = 60,
    ) -> QueryResult:
        if _WRITE_STATEMENTS.search(sql):
            raise ConnectorError("logs connector is read-only.")
        return await asyncio.to_thread(self._execute_sync, sql, max_rows, timeout_seconds)

    def _execute_sync(self, sql: str, max_rows: int, timeout_seconds: int) -> QueryResult:
        con = self._new_connection()
        try:
            # Register the log stream under its catalog-visible table name AND
            # under a `logs.<name>` schema so the LLM can write either form.
            table = self._table_name()
            reader = self._reader_expr()
            con.execute("CREATE SCHEMA IF NOT EXISTS logs")
            con.execute(f"CREATE OR REPLACE VIEW logs.{table} AS SELECT * FROM {reader}")
            con.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM {reader}")

            try:
                cur = con.execute(sql)
            except duckdb.Error as exc:
                raise ConnectorError(f"query failed: {exc}") from exc

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
