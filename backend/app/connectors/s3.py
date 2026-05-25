"""S3 / object-storage connector — files-as-tables, powered by DuckDB.

A registered S3 source maps to a (endpoint, bucket, prefix) triple. The
connector globs the bucket for known file extensions (`.parquet`, `.csv`,
`.json`, `.tsv`) and presents each file as a table whose name is the
filename without extension. Schema is inferred by DuckDB.

Works against any S3-compatible store:
  - AWS S3       → endpoint left blank (DuckDB defaults to AWS)
  - MinIO        → endpoint http://host:9000, url_style=path
  - Cloudflare R2 → endpoint https://<account>.r2.cloudflarestorage.com
  - Wasabi, Backblaze B2, Ceph, etc. — same shape

Phase 2a runs each query in a fresh DuckDB connection. Pooling lands in 2b.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

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

# Read-only check — DuckDB SQL gate. S3 connector is *always* read-only.
_WRITE_STATEMENTS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"comment|reindex|vacuum|analyze|copy|call|attach|use)\b",
    re.IGNORECASE,
)

_KNOWN_EXTENSIONS = (".parquet", ".csv", ".json", ".tsv", ".ndjson")


@dataclass(slots=True)
class _S3File:
    """One file in the bucket, presented to the catalog as a table."""

    table_name: str
    s3_url: str
    duckdb_reader: str  # the read_parquet / read_csv_auto / read_json_auto expression


def _safe_table_name(filename: str) -> str:
    """Convert 'web events.csv' → 'web_events'. Strict, conservative."""
    stem = PurePosixPath(filename).stem
    name = re.sub(r"[^a-zA-Z0-9_]", "_", stem).strip("_")
    if not name:
        name = "unnamed"
    if name[0].isdigit():
        name = "_" + name
    return name.lower()


def _reader_expr(s3_url: str) -> str:
    """DuckDB function call appropriate for the file extension."""
    lower = s3_url.lower()
    if lower.endswith(".parquet"):
        return f"read_parquet('{s3_url}')"
    if lower.endswith((".csv", ".tsv")):
        # auto detects delimiter, header, types
        return f"read_csv_auto('{s3_url}')"
    if lower.endswith((".json", ".ndjson")):
        return f"read_json_auto('{s3_url}')"
    # Fallback — DuckDB will reject if it can't infer.
    return f"read_csv_auto('{s3_url}')"


class S3Connector(Connector):
    type = "s3"
    display_name = "S3 / object storage"
    credential_keys = frozenset({"secret_access_key"})

    # ── Helpers ────────────────────────────────────────────────

    def _new_connection(self) -> duckdb.DuckDBPyConnection:
        """Spin up a fresh DuckDB connection wired with httpfs + an S3 secret."""
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        secret_clauses = self._secret_clauses()
        con.execute(
            f"CREATE OR REPLACE SECRET wekams_s3 (TYPE S3, {secret_clauses})"
        )
        return con

    def _secret_clauses(self) -> str:
        """Build the DuckDB SECRET body from config + credentials."""
        endpoint_raw = (self.config.get("endpoint") or "").strip()
        url_style = (self.config.get("url_style") or ("path" if endpoint_raw else "vhost")).lower()
        region = self.config.get("region") or "us-east-1"
        access_key = self.credentials.get("access_key") or self.config.get("access_key", "")
        secret_key = self.credentials.get("secret_access_key", "")

        parts: list[str] = []
        if access_key:
            parts.append(f"KEY_ID '{_escape(access_key)}'")
        if secret_key:
            parts.append(f"SECRET '{_escape(secret_key)}'")
        if region:
            parts.append(f"REGION '{_escape(region)}'")
        if endpoint_raw:
            # DuckDB wants endpoint without scheme; track ssl separately.
            parsed = urlparse(endpoint_raw if "://" in endpoint_raw else f"//{endpoint_raw}")
            host = parsed.netloc or parsed.path
            use_ssl = "true" if parsed.scheme == "https" else "false"
            parts.append(f"ENDPOINT '{_escape(host)}'")
            parts.append(f"USE_SSL {use_ssl}")
        parts.append(f"URL_STYLE '{_escape(url_style)}'")
        return ", ".join(parts)

    def _list_files(self, con: duckdb.DuckDBPyConnection) -> list[_S3File]:
        bucket = (self.config.get("bucket") or "").strip()
        if not bucket:
            raise ConnectorError("S3 connector requires a `bucket`.")
        prefix = (self.config.get("prefix") or "").strip().lstrip("/")
        base = f"s3://{bucket}/" + (f"{prefix}/" if prefix and not prefix.endswith("/") else prefix)

        files: list[_S3File] = []
        for ext in _KNOWN_EXTENSIONS:
            pattern = f"{base}**/*{ext}"
            try:
                rows = con.execute("SELECT file FROM glob(?)", [pattern]).fetchall()
            except duckdb.IOException as exc:
                # Glob fails on empty buckets sometimes; keep going.
                log.debug("s3.glob.miss", pattern=pattern, error=str(exc))
                continue
            for (path,) in rows:
                filename = PurePosixPath(path).name
                files.append(
                    _S3File(
                        table_name=_safe_table_name(filename),
                        s3_url=path,
                        duckdb_reader=_reader_expr(path),
                    )
                )

        # Dedupe by table name — last file wins; warn the user upstream later.
        seen: dict[str, _S3File] = {}
        for f in files:
            seen[f.table_name] = f
        return list(seen.values())

    # ── Connector contract ──────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("s3.healthcheck.failed", error=str(exc))
            return False

    def _healthcheck_sync(self) -> bool:
        con = self._new_connection()
        try:
            bucket = (self.config.get("bucket") or "").strip()
            if not bucket:
                return False
            con.execute(f"SELECT * FROM glob('s3://{bucket}/**') LIMIT 1").fetchall()
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
            for f in files:
                try:
                    schema_rows = con.execute(
                        f"DESCRIBE SELECT * FROM {f.duckdb_reader}"
                    ).fetchall()
                except duckdb.Error as exc:
                    log.warning("s3.introspect.describe_failed", file=f.s3_url, error=str(exc))
                    continue
                columns: list[IntrospectedColumn] = []
                for i, row in enumerate(schema_rows, start=1):
                    col_name = row[0]
                    col_type = row[1]
                    nullable = (row[2] or "YES").upper() != "NO" if len(row) > 2 else True
                    columns.append(
                        IntrospectedColumn(
                            name=col_name,
                            data_type=col_type,
                            nullable=nullable,
                            is_primary_key=False,
                            position=i,
                        )
                    )

                row_count_est: int | None = None
                try:
                    row_count_est = int(
                        con.execute(
                            f"SELECT COUNT(*) FROM {f.duckdb_reader}"
                        ).fetchone()[0]
                    )
                except duckdb.Error:
                    pass

                tables.append(
                    IntrospectedTable(
                        schema_name="files",
                        name=f.table_name,
                        description=f.s3_url,
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
            raise ConnectorError(
                "write statements are not allowed via the S3 connector — it is read-only."
            )
        return await asyncio.to_thread(self._execute_sync, sql, max_rows, timeout_seconds)

    def _execute_sync(self, sql: str, max_rows: int, timeout_seconds: int) -> QueryResult:
        con = self._new_connection()
        try:
            # Register every known file under a `files` schema (matching the
            # schema_name we expose to the catalog) AND in the default schema,
            # so the LLM can write either `SELECT * FROM files.campaigns` or
            # `SELECT * FROM campaigns` and both work.
            con.execute("CREATE SCHEMA IF NOT EXISTS files")
            for f in self._list_files(con):
                con.execute(
                    f"CREATE OR REPLACE VIEW files.{f.table_name} "
                    f"AS SELECT * FROM {f.duckdb_reader}"
                )
                con.execute(
                    f"CREATE OR REPLACE VIEW {f.table_name} "
                    f"AS SELECT * FROM {f.duckdb_reader}"
                )
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


def _escape(v: str) -> str:
    """Conservative single-quote escape for DuckDB SQL literals.

    We control the inputs (config + credentials we just decrypted) so this is
    belt-and-suspenders, not security.
    """
    return v.replace("'", "''")
