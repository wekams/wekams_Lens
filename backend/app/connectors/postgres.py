"""Postgres connector — the first concrete data source plugin.

Talks to any standard Postgres (or compatible: Aurora, RDS, Yugabyte, etc.)
via asyncpg. Read-only by default — execute() refuses non-SELECT statements.
"""

from __future__ import annotations

import asyncio
import re

import asyncpg

from app.connectors.base import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
)

# Crude but effective gate. Anything starting with INSERT/UPDATE/DELETE/etc.
# is rejected before being sent to the DB. Belt-and-suspenders alongside
# the read-only role recommendation in customer setup.
_WRITE_STATEMENTS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"comment|reindex|vacuum|analyze|copy|call)\b",
    re.IGNORECASE,
)


class PostgresConnector(Connector):
    type = "postgres"
    display_name = "Postgres"
    credential_keys = frozenset({"password"})

    async def _connect(self) -> asyncpg.Connection:
        try:
            return await asyncpg.connect(
                host=self.config["host"],
                port=int(self.config.get("port", 5432)),
                user=self.credentials.get("user") or self.config.get("user"),
                password=self.credentials.get("password"),
                database=self.config["database"],
                ssl=self.config.get("ssl"),
                timeout=10,
            )
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
            raise ConnectorError(f"could not connect to Postgres: {exc}") from exc

    async def healthcheck(self) -> bool:
        try:
            conn = await self._connect()
        except ConnectorError:
            return False
        try:
            await conn.fetchval("SELECT 1")
            return True
        except asyncpg.PostgresError:
            return False
        finally:
            await conn.close()

    async def introspect(self) -> list[IntrospectedTable]:
        conn = await self._connect()
        try:
            schemas = self.config.get("schemas", ["public"])
            rows = await conn.fetch(
                """
                SELECT
                    c.table_schema,
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.ordinal_position,
                    COALESCE(pk.is_primary, false) AS is_primary,
                    obj_description(format('%I.%I', c.table_schema, c.table_name)::regclass, 'pg_class') AS table_description,
                    col_description(format('%I.%I', c.table_schema, c.table_name)::regclass, c.ordinal_position) AS column_description
                FROM information_schema.columns c
                LEFT JOIN LATERAL (
                    SELECT true AS is_primary
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema    = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema    = c.table_schema
                      AND tc.table_name      = c.table_name
                      AND kcu.column_name    = c.column_name
                    LIMIT 1
                ) pk ON true
                WHERE c.table_schema = ANY($1::text[])
                ORDER BY c.table_schema, c.table_name, c.ordinal_position;
                """,
                schemas,
            )

            tables: dict[tuple[str, str], IntrospectedTable] = {}
            for r in rows:
                key = (r["table_schema"], r["table_name"])
                table = tables.get(key)
                if table is None:
                    table = IntrospectedTable(
                        schema_name=r["table_schema"],
                        name=r["table_name"],
                        description=r["table_description"],
                    )
                    tables[key] = table
                table.columns.append(
                    IntrospectedColumn(
                        name=r["column_name"],
                        data_type=r["data_type"],
                        nullable=r["is_nullable"] == "YES",
                        is_primary_key=bool(r["is_primary"]),
                        position=r["ordinal_position"],
                        description=r["column_description"],
                    )
                )

            # Row count estimates (cheap, may be stale).
            for (schema, name), table in tables.items():
                rc = await conn.fetchval(
                    """
                    SELECT reltuples::bigint
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = $1 AND c.relname = $2;
                    """,
                    schema,
                    name,
                )
                if rc is not None and rc >= 0:
                    table.row_count_est = int(rc)

            return list(tables.values())
        finally:
            await conn.close()

    async def execute(
        self,
        sql: str,
        *,
        max_rows: int = 10_000,
        timeout_seconds: int = 60,
    ) -> QueryResult:
        if _WRITE_STATEMENTS.search(sql):
            raise ConnectorError(
                "write statements are not allowed via the Postgres connector "
                "in read-only mode (Phase 1a)."
            )

        conn = await self._connect()
        try:
            # Belt-and-suspenders timeout on the DB side.
            await conn.execute(
                f"SET statement_timeout = {int(timeout_seconds) * 1000}"
            )
            stmt = await conn.prepare(sql)
            rows = await stmt.fetch(timeout=timeout_seconds)
        except asyncpg.PostgresError as exc:
            raise ConnectorError(f"query failed: {exc}") from exc
        finally:
            await conn.close()

        columns = list(rows[0].keys()) if rows else []
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        data = [tuple(r[c] for c in columns) for r in rows]
        return QueryResult(
            columns=columns,
            rows=data,
            row_count=len(data),
            truncated=truncated,
        )
