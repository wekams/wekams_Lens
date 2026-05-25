"""SQLite connector — reference custom plugin.

A worked example of writing a Wekams Lens connector. Drop this file in
~/.wekams/connectors/ (or it auto-loads from connectors/external/ in the
repo) and a new "sqlite" source type appears in the UI.

A registered SQLite source points at a single .db file on disk. The
connector introspects its tables/columns via sqlite_master and
PRAGMA table_info, and executes read-only SELECTs.

Real-world uses:
  - Quick analysis on an exported DuckDB / SQLite snapshot
  - Local file from a customer support ticket
  - Test-doubles for staging
  - Embedded databases shipped inside an application

Only ~100 lines including comments — meant to be readable. See
WRITING_CONNECTORS.md for the contract.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path

# In the published SDK this is `from wekams_lens_sdk import ...`. Inside the
# repo we import from app.sdk; both paths resolve to the same classes.
from app.sdk import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
)


_WRITE_STATEMENTS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|attach|detach|"
    r"pragma|vacuum|reindex|analyze|replace|begin|commit|rollback)\b",
    re.IGNORECASE,
)


class SqliteConnector(Connector):
    type = "sqlite"
    display_name = "SQLite (file)"
    credential_keys = frozenset()  # SQLite files use filesystem perms, no secrets

    # ── helpers ────────────────────────────────────────────────────

    def _open(self) -> sqlite3.Connection:
        path = self.config.get("path")
        if not path:
            raise ConnectorError("SQLite connector requires a `path` to a .db file.")
        p = Path(path).expanduser()
        if not p.is_file():
            raise ConnectorError(f"SQLite file not found: {p}")
        # mode=ro guarantees the connector cannot mutate the file even if
        # somehow a write statement slips past the regex gate.
        uri = f"file:{p.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # ── connector contract ─────────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except ConnectorError:
            return False

    def _healthcheck_sync(self) -> bool:
        con = self._open()
        try:
            con.execute("SELECT 1").fetchone()
            return True
        finally:
            con.close()

    async def introspect(self) -> list[IntrospectedTable]:
        return await asyncio.to_thread(self._introspect_sync)

    def _introspect_sync(self) -> list[IntrospectedTable]:
        con = self._open()
        try:
            tables: list[IntrospectedTable] = []
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for r in rows:
                tname = r["name"]
                cols_raw = con.execute(f'PRAGMA table_info("{tname}")').fetchall()
                cols = [
                    IntrospectedColumn(
                        name=c["name"],
                        data_type=c["type"] or "TEXT",
                        nullable=not c["notnull"],
                        is_primary_key=bool(c["pk"]),
                        position=c["cid"] + 1,
                    )
                    for c in cols_raw
                ]
                count_row = con.execute(f'SELECT COUNT(*) AS n FROM "{tname}"').fetchone()
                tables.append(
                    IntrospectedTable(
                        schema_name="main",
                        name=tname,
                        row_count_est=int(count_row["n"]),
                        columns=cols,
                    )
                )
            return tables
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
            raise ConnectorError("the sqlite connector is read-only; refusing write statement.")
        return await asyncio.to_thread(self._execute_sync, sql, max_rows, timeout_seconds)

    def _execute_sync(self, sql: str, max_rows: int, timeout_seconds: int) -> QueryResult:
        con = self._open()
        try:
            try:
                cur = con.execute(sql)
            except sqlite3.Error as exc:
                raise ConnectorError(f"query failed: {exc}") from exc
            columns = [d[0] for d in cur.description] if cur.description else []
            rows_raw = cur.fetchall()
            truncated = len(rows_raw) > max_rows
            rows = [tuple(r) for r in rows_raw[:max_rows]]
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
            )
        finally:
            con.close()
