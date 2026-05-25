"""Google Cloud Storage connector.

GCS exposes an S3-interoperable HMAC endpoint at `storage.googleapis.com`,
which DuckDB's httpfs extension consumes the same way it consumes
AWS S3 — so this connector is effectively the S3 connector with a fixed
endpoint and a different secret type (`GCS` instead of `S3`).

Auth: HMAC interoperability keys generated from the GCS console
(IAM & Admin → Service Accounts → Keys → Add → Interoperability).
The HMAC access key + secret pair is what we accept here. They're stored
encrypted.

Native service-account-JSON auth via the dedicated `gcs` DuckDB
extension is a roadmap item; HMAC is universal and works against any
GCS bucket without configuration changes on the bucket side.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import PurePosixPath

import duckdb

from app.connectors.base import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
)
from app.connectors.s3 import _KNOWN_EXTENSIONS, _reader_expr, _safe_table_name
from app.core.logging import get_logger

log = get_logger(__name__)

_WRITE_STATEMENTS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"comment|reindex|vacuum|analyze|copy|call|attach|use)\b",
    re.IGNORECASE,
)


class GcsConnector(Connector):
    type = "gcs"
    display_name = "Google Cloud Storage"
    credential_keys = frozenset({"hmac_secret"})

    def _bucket(self) -> str:
        b = (self.config.get("bucket") or "").strip()
        if not b:
            raise ConnectorError("GCS connector requires `bucket`.")
        return b

    def _prefix(self) -> str:
        return (self.config.get("prefix") or "").strip().lstrip("/")

    def _new_connection(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")

        hmac_key = (self.credentials.get("hmac_access_key")
                    or self.config.get("hmac_access_key", ""))
        hmac_secret = self.credentials.get("hmac_secret", "")

        # DuckDB has a dedicated GCS SECRET type since v0.10 that uses the
        # GCS endpoint + HMAC interop keys under the hood.
        parts: list[str] = []
        if hmac_key:
            parts.append(f"KEY_ID '{_esc(hmac_key)}'")
        if hmac_secret:
            parts.append(f"SECRET '{_esc(hmac_secret)}'")
        if not parts:
            # Public-bucket access. Skip the secret entirely.
            return con

        con.execute(f"CREATE OR REPLACE SECRET wekams_gcs (TYPE GCS, {', '.join(parts)})")
        return con

    def _base_url(self) -> str:
        bucket = self._bucket()
        prefix = self._prefix()
        base = f"gs://{bucket}/"
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        return base + prefix

    def _list_files(self, con: duckdb.DuckDBPyConnection) -> dict[str, str]:
        base = self._base_url()
        files: dict[str, str] = {}
        for ext in _KNOWN_EXTENSIONS:
            pattern = f"{base}**/*{ext}"
            try:
                rows = con.execute("SELECT file FROM glob(?)", [pattern]).fetchall()
            except duckdb.IOException as exc:
                log.debug("gcs.glob.miss", pattern=pattern, error=str(exc))
                continue
            for (path,) in rows:
                files[_safe_table_name(PurePosixPath(path).name)] = path
        return files

    # ── connector contract ─────────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("gcs.healthcheck.failed", error=str(exc))
            return False

    def _healthcheck_sync(self) -> bool:
        con = self._new_connection()
        try:
            base = self._base_url().replace("'", "''")
            con.execute(f"SELECT file FROM glob('{base}**') LIMIT 1").fetchall()
            return True
        finally:
            con.close()

    async def introspect(self) -> list[IntrospectedTable]:
        return await asyncio.to_thread(self._introspect_sync)

    def _introspect_sync(self) -> list[IntrospectedTable]:
        con = self._new_connection()
        try:
            files = self._list_files(con)
            tables: list[IntrospectedTable] = []
            for table_name, url in files.items():
                try:
                    schema_rows = con.execute(
                        f"DESCRIBE SELECT * FROM {_reader_expr(url)}"
                    ).fetchall()
                except duckdb.Error as exc:
                    log.warning("gcs.introspect.describe_failed", file=url, error=str(exc))
                    continue
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
                            f"SELECT COUNT(*) FROM {_reader_expr(url)}"
                        ).fetchone()[0]
                    )
                except duckdb.Error:
                    pass

                tables.append(
                    IntrospectedTable(
                        schema_name="files",
                        name=table_name,
                        description=url,
                        row_count_est=row_count_est,
                        columns=columns,
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
            raise ConnectorError("GCS connector is read-only.")
        return await asyncio.to_thread(self._execute_sync, sql, max_rows, timeout_seconds)

    def _execute_sync(self, sql: str, max_rows: int, timeout_seconds: int) -> QueryResult:
        con = self._new_connection()
        try:
            con.execute("CREATE SCHEMA IF NOT EXISTS files")
            for table_name, url in self._list_files(con).items():
                expr = _reader_expr(url)
                con.execute(
                    f"CREATE OR REPLACE VIEW files.{table_name} AS SELECT * FROM {expr}"
                )
                con.execute(
                    f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM {expr}"
                )

            try:
                cur = con.execute(sql)
            except duckdb.Error as exc:
                raise ConnectorError(f"query failed: {exc}") from exc

            columns = [d[0] for d in cur.description] if cur.description else []
            rows_raw = cur.fetchall()
            truncated = len(rows_raw) > max_rows
            return QueryResult(
                columns=columns,
                rows=rows_raw[:max_rows],
                row_count=min(len(rows_raw), max_rows),
                truncated=truncated,
            )
        finally:
            con.close()


def _esc(v: str) -> str:
    return v.replace("'", "''")
