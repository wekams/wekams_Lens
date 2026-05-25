"""Azure Blob Storage / ADLS Gen2 connector.

Talks to both Azure Blob and Azure Data Lake Storage Gen2 via DuckDB's
`azure` extension. DuckDB handles the protocol routing — abfss://… for
ADLS, azure://… for Blob — so this connector just constructs the right
URL and credential clauses, then files-as-tables identically to the S3
connector.

Auth (one of):
  - **SAS token** (`sas_token`): recommended for sharing time-bounded
    access without giving up the account key. Stored encrypted.
  - **Account key** (`account_key`): full-access. Stored encrypted.
  - **Connection string** (`connection_string`): the Azure-standard
    bundle. Most enterprise scripts use this. Stored encrypted.
  - Anonymous: public blob containers only.

For a fuller account walkthrough (Service Principal / Managed Identity)
see WRITING_CONNECTORS.md — those flows live outside DuckDB's azure
extension today and can be added as a follow-on.
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


class AzureBlobConnector(Connector):
    type = "azure_blob"
    display_name = "Azure Blob / ADLS Gen2"
    credential_keys = frozenset({"account_key", "sas_token", "connection_string"})

    # ── helpers ────────────────────────────────────────────────────

    def _account(self) -> str:
        a = (self.config.get("account_name") or "").strip()
        if not a:
            raise ConnectorError("Azure Blob connector requires `account_name`.")
        return a

    def _container(self) -> str:
        c = (self.config.get("container") or "").strip()
        if not c:
            raise ConnectorError("Azure Blob connector requires `container`.")
        return c

    def _prefix(self) -> str:
        p = (self.config.get("prefix") or "").strip().lstrip("/")
        return p

    def _is_adls(self) -> bool:
        """ADLS Gen2 = Blob account with hierarchical namespace enabled.
        We accept an explicit `adls=true` config flag; otherwise treat
        as plain Blob."""
        v = self.config.get("adls")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in {"1", "true", "yes"}
        return False

    def _base_url(self) -> str:
        account = self._account()
        container = self._container()
        prefix = self._prefix()
        if self._is_adls():
            base = f"abfss://{container}@{account}.dfs.core.windows.net/"
        else:
            # DuckDB also accepts `az://container/...@account.blob.core.windows.net`
            # but the simple `azure://container/...` works once the SECRET
            # has account_name set. We use the simpler form.
            base = f"azure://{container}/"
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        return base + prefix

    def _new_connection(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute("INSTALL azure; LOAD azure;")
        secret_clauses = self._secret_clauses()
        con.execute(
            f"CREATE OR REPLACE SECRET wekams_azure (TYPE AZURE, {secret_clauses})"
        )
        return con

    def _secret_clauses(self) -> str:
        account = self._account()
        parts: list[str] = []

        connection_string = self.credentials.get("connection_string")
        if connection_string:
            parts.append(f"CONNECTION_STRING '{_esc(connection_string)}'")
        else:
            parts.append(f"ACCOUNT_NAME '{_esc(account)}'")
            account_key = self.credentials.get("account_key")
            sas_token = self.credentials.get("sas_token")
            if account_key:
                parts.append(f"ACCOUNT_KEY '{_esc(account_key)}'")
            if sas_token:
                # SAS tokens may start with '?' from the portal; strip it.
                token = sas_token.lstrip("?")
                parts.append(f"SAS_TOKEN '{_esc(token)}'")
            if not (account_key or sas_token):
                # Anonymous public container — let DuckDB try without creds.
                pass

        return ", ".join(parts)

    def _list_files(self, con: duckdb.DuckDBPyConnection) -> dict[str, str]:
        base = self._base_url()
        files: dict[str, str] = {}
        for ext in _KNOWN_EXTENSIONS:
            pattern = f"{base}**/*{ext}"
            try:
                rows = con.execute("SELECT file FROM glob(?)", [pattern]).fetchall()
            except duckdb.IOException as exc:
                log.debug("azure_blob.glob.miss", pattern=pattern, error=str(exc))
                continue
            for (path,) in rows:
                files[_safe_table_name(PurePosixPath(path).name)] = path
        return files

    # ── connector contract ─────────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("azure_blob.healthcheck.failed", error=str(exc))
            return False

    def _healthcheck_sync(self) -> bool:
        con = self._new_connection()
        try:
            base = self._base_url()
            con.execute(f"SELECT file FROM glob('{base.replace(chr(39), chr(39)+chr(39))}**') LIMIT 1").fetchall()
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
                    log.warning("azure_blob.introspect.describe_failed", file=url, error=str(exc))
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
            raise ConnectorError("Azure Blob connector is read-only.")
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
