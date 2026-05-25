"""Elasticsearch / OpenSearch connector.

Talks to both Elasticsearch and OpenSearch via opensearch-py (which
deliberately keeps the API compatible with vanilla ES on the operations
we care about).

Execution model: **native `_search` Query DSL**, not SQL. Why:
  - The SQL plugin is *optional* on OpenSearch and not present in the
    minimal Homebrew distribution. Relying on it would make the
    connector fragile across customer installs.
  - DSL is universal — every ES/OpenSearch install accepts it.
  - Modern LLMs (Qwen, Llama, DeepSeek, etc.) write DSL JSON
    natively; in practice it's not harder for them than SQL.

The connector's `execute()` takes the `sql` argument verbatim and
treats it as a JSON string representing the `_search` request body
({"query": {...}, "aggs": {...}, "size": ...}). It posts to
`/{index}/_search` and projects the response into a flat
columns/rows shape:

  - If the body has `aggs` / `aggregations`, the result is one row per
    leaf bucket, with the bucket key(s) and metric values as columns.
    Buckets like terms / date_histogram / range are supported.
  - Otherwise, the result is one row per hit, with each top-level key
    of `_source` as a column.

Auth supported: anonymous (dev), HTTP basic, OpenSearch / ES API key.
mTLS and AWS SigV4 are roadmap.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import OpenSearchException

from app.connectors.base import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
)
from app.core.logging import get_logger

log = get_logger(__name__)


_BUCKET_KEY_NAME = "_bucket"  # used when a bucket has no explicit key field name


class ElasticsearchConnector(Connector):
    type = "elasticsearch"
    display_name = "Elasticsearch / OpenSearch"
    credential_keys = frozenset({"password", "api_key"})

    # ── client construction ───────────────────────────────────────

    def _client(self) -> OpenSearch:
        url = (self.config.get("url") or "").strip()
        if not url:
            raise ConnectorError(
                "Elasticsearch connector requires a `url` (e.g. http://localhost:9200)."
            )

        http_auth = None
        user = self.config.get("user")
        password = self.credentials.get("password")
        api_key = self.credentials.get("api_key")
        headers: dict[str, str] = {}

        if user and password:
            http_auth = (user, password)
        if api_key:
            headers["Authorization"] = f"ApiKey {api_key}"

        verify_certs = bool(self.config.get("verify_certs", True))

        return OpenSearch(
            hosts=[url],
            http_auth=http_auth,
            verify_certs=verify_certs,
            ssl_show_warn=False,
            headers=headers or None,
            request_timeout=30,
        )

    def _index_pattern(self) -> str:
        return (self.config.get("index_pattern") or self.config.get("index") or "*").strip()

    # ── connector contract ────────────────────────────────────────

    async def healthcheck(self) -> bool:
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("elasticsearch.healthcheck.failed", error=str(exc))
            return False

    def _healthcheck_sync(self) -> bool:
        client = self._client()
        try:
            client.info()
            return True
        except OpenSearchException:
            return False

    async def introspect(self) -> list[IntrospectedTable]:
        return await asyncio.to_thread(self._introspect_sync)

    def _introspect_sync(self) -> list[IntrospectedTable]:
        client = self._client()
        pattern = self._index_pattern()

        try:
            indices = client.indices.get(index=pattern, allow_no_indices=True)
        except OpenSearchException as exc:
            raise ConnectorError(f"could not list indices for {pattern!r}: {exc}") from exc

        tables: list[IntrospectedTable] = []
        for name, info in sorted(indices.items()):
            if name.startswith("."):
                continue  # hidden / system indices
            mappings = (info.get("mappings") or {}).get("properties") or {}
            columns: list[IntrospectedColumn] = []
            for i, (field, spec) in enumerate(sorted(mappings.items()), start=1):
                columns.append(
                    IntrospectedColumn(
                        name=field,
                        data_type=str(spec.get("type") or "keyword"),
                        nullable=True,
                        is_primary_key=False,
                        position=i,
                    )
                )

            row_count: int | None = None
            try:
                row_count = int(client.count(index=name)["count"])
            except OpenSearchException:
                pass

            tables.append(
                IntrospectedTable(
                    schema_name="indices",
                    name=name,
                    description=f"OpenSearch / Elasticsearch index '{name}'",
                    row_count_est=row_count,
                    columns=columns,
                )
            )

        return tables

    async def execute(
        self,
        sql: str,
        *,
        max_rows: int = 10_000,
        timeout_seconds: int = 60,
    ) -> QueryResult:
        return await asyncio.to_thread(self._execute_sync, sql, max_rows, timeout_seconds)

    # ── execution: parse the model's JSON, query, flatten response ──

    def _execute_sync(self, body_str: str, max_rows: int, timeout_seconds: int) -> QueryResult:
        """body_str must be a JSON-encoded `_search` request body.

        We accept two top-level shapes for the model's convenience:
          1. {"query": {...}, "aggs": {...}, ...}           (canonical)
          2. {"index": "...", "body": {"query": {...}, ...}} (explicit)
        Shape 2 lets the model override the source's configured index
        pattern, which is occasionally useful for "search across a
        specific date-suffixed index."
        """
        try:
            parsed = json.loads(body_str)
        except json.JSONDecodeError as exc:
            raise ConnectorError(
                "Elasticsearch source expects a JSON Query DSL body, "
                f"not a SQL string. JSON parse error: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ConnectorError("Query body must be a JSON object.")

        if "body" in parsed and isinstance(parsed.get("body"), dict):
            index = str(parsed.get("index") or self._index_pattern())
            body = parsed["body"]
        else:
            index = self._index_pattern()
            body = parsed

        body.setdefault("size", max(min(max_rows, 100), 1))
        if "track_total_hits" not in body:
            body["track_total_hits"] = True

        client = self._client()
        try:
            resp = client.search(index=index, body=body, request_timeout=timeout_seconds)
        except OpenSearchException as exc:
            raise ConnectorError(f"OpenSearch query failed: {exc}") from exc

        # Aggregation results take priority — they're what the LLM typically
        # asks for ("count by service", "errors per day", etc.). If aggs is
        # present, we flatten its leaf buckets into rows; otherwise we
        # return hits.
        aggs = resp.get("aggregations") or {}
        if aggs:
            columns, rows = _flatten_aggregations(aggs)
        else:
            columns, rows = _flatten_hits(resp.get("hits", {}).get("hits", []))

        truncated = len(rows) > max_rows
        return QueryResult(
            columns=columns,
            rows=[tuple(r) for r in rows[:max_rows]],
            row_count=min(len(rows), max_rows),
            truncated=truncated,
        )


# ── response flattening helpers ─────────────────────────────────────


def _flatten_hits(hits: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    """One row per hit, columns = union of _source keys (sorted)."""
    columns_set: set[str] = set()
    for h in hits:
        src = h.get("_source") or {}
        columns_set.update(src.keys())
    columns = sorted(columns_set)
    rows = [[(h.get("_source") or {}).get(c) for c in columns] for h in hits]
    return columns, rows


def _flatten_aggregations(
    aggs: dict[str, Any],
) -> tuple[list[str], list[list[Any]]]:
    """Walk the agg tree and emit one row per leaf bucket.

    Handles the common shapes:
      - terms / significant_terms / date_histogram / histogram / range
        (each has a `buckets` array)
      - filter / filters (single-bucket nested aggs)
      - leaf metric aggs: value (avg/sum/min/max/cardinality), values
        (percentiles), top_hits is best-effort
    """
    rows: list[list[Any]] = []
    columns: list[str] = []

    def emit_row(path: dict[str, Any], metrics: dict[str, Any]) -> None:
        nonlocal columns
        merged = {**path, **metrics}
        for k in merged.keys():
            if k not in columns:
                columns.append(k)
        rows.append([merged.get(c) for c in columns])

    def walk(node: dict[str, Any], path: dict[str, Any]) -> None:
        # Find any bucket-producing sub-aggs at this level. If none, this
        # IS the leaf — emit metric values along the current path.
        bucket_aggs: list[tuple[str, dict[str, Any]]] = []
        metrics: dict[str, Any] = {}

        for key, val in node.items():
            if not isinstance(val, dict):
                continue
            if "buckets" in val and isinstance(val["buckets"], (list, dict)):
                bucket_aggs.append((key, val))
            elif "value" in val:
                metrics[key] = val["value"]
            elif "values" in val:
                # Percentiles, etc.
                for k2, v2 in (val.get("values") or {}).items():
                    metrics[f"{key}.{k2}"] = v2
            elif "hits" in val and isinstance(val["hits"], dict):
                # top_hits — emit a count, leave the documents themselves out.
                metrics[key] = (val["hits"].get("total") or {}).get("value")
            elif "doc_count_error_upper_bound" in val or "sum_other_doc_count" in val:
                # Sub-keys of a terms agg; skip — handled by the bucket loop.
                continue
            elif "doc_count" in val and "buckets" not in val:
                # filter / single-bucket agg with possible nested aggs.
                # Treat doc_count as a metric and recurse for nested.
                metrics[f"{key}.doc_count"] = val["doc_count"]

        # Always carry doc_count if it's on the current node.
        if "doc_count" in node and "doc_count" not in metrics:
            metrics["doc_count"] = node["doc_count"]

        if not bucket_aggs:
            emit_row(path, metrics)
            return

        for agg_name, agg_node in bucket_aggs:
            buckets = agg_node["buckets"]
            iterable: list[tuple[Any, dict[str, Any]]]
            if isinstance(buckets, list):
                iterable = []
                for b in buckets:
                    key = b.get("key_as_string") or b.get("key")
                    iterable.append((key, b))
            else:  # dict (filters agg)
                iterable = list(buckets.items())

            for bkey, bucket in iterable:
                sub_path = {**path, agg_name: bkey}
                # Carry doc_count up by default — it's the most common metric.
                bucket_with_doc = dict(bucket)
                walk(bucket_with_doc, sub_path)

    walk(aggs, {})
    return columns, rows
