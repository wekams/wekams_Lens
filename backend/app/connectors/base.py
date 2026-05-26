"""Connector interface — every data source plugin implements this.

Add a new source type by:
  1. Creating `app/connectors/<name>.py` with a class extending Connector
  2. Registering it in `app/connectors/registry.py`

The contract is intentionally small so adding connectors stays cheap.
Phase 1a defines introspect + execute. Streaming and write capability
arrive in later phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ConnectorError(Exception):
    """Anything that goes wrong inside a connector. Wrap underlying errors
    in this so the orchestrator never sees driver-specific exception types."""


@dataclass(slots=True)
class IntrospectedColumn:
    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    position: int = 0
    description: str | None = None


@dataclass(slots=True)
class IntrospectedTable:
    schema_name: str
    name: str
    description: str | None = None
    row_count_est: int | None = None
    columns: list[IntrospectedColumn] = field(default_factory=list)


@dataclass(slots=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    truncated: bool = False


class Connector(ABC):
    """Each connector is constructed with a config dict and (optionally) a
    decrypted credentials dict. Lifecycle is short: connect → use → close.

    Connection pooling and reuse are handled higher up; connectors themselves
    can be lightweight wrappers.

    Subclasses MUST override `type` with a stable lowercase string. They
    SHOULD override `credential_keys` to list any connection-field names
    that contain secrets — those values are pulled out of the catalog's
    plaintext config column and stored encrypted in the vault.

    Optional: override `display_name` for a human-friendly label shown in
    the source picker UI. Defaults to the type string.
    """

    type: str = "abstract"
    display_name: str = ""
    credential_keys: frozenset[str] = frozenset()

    def __init__(self, config: dict, credentials: dict | None = None) -> None:
        self.config = config
        self.credentials = credentials or {}

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Return True if the source is reachable with the given credentials."""

    @abstractmethod
    async def introspect(self) -> list[IntrospectedTable]:
        """Discover tables and columns in the source.

        Should be safe to call repeatedly — implementations must not have
        side effects on the source system.
        """

    @abstractmethod
    async def execute(
        self,
        sql: str,
        *,
        max_rows: int = 10_000,
        timeout_seconds: int = 60,
    ) -> QueryResult:
        """Run a read-only query. Implementations enforce row cap and timeout
        on the source side wherever possible (e.g., Postgres `statement_timeout`)."""

    async def estimate_rows(self, sql: str) -> int | None:
        """Estimate how many rows `sql` will produce, without running it.

        Returns None if the connector cannot estimate (default for sources
        like S3 / Elasticsearch where there's no cheap EXPLAIN). The
        orchestrator uses this to surface a cost preview in the trace, and
        (in Pro / Enterprise builds) to block obviously-runaway queries
        before they hit the source.
        """
        return None

    async def close(self) -> None:
        """Tear down any open connections. Default no-op for stateless connectors."""
        return None
