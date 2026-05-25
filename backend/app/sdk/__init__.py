"""Wekams Lens — stable SDK for building custom connectors.

A custom connector is a Python class that extends ``Connector`` from this
module and is dropped into a directory Wekams Lens watches:

  ~/.wekams/connectors/           — user-installed, per-machine
  <repo>/connectors/external/     — checked into the repo

The plugin loader imports each ``*.py`` file from those directories at
startup and registers every subclass of ``Connector`` it finds.

This module is the **public API**. The shape of these classes is stable
across MAJOR versions; we only break things across MAJOR bumps and only
with a migration guide. Internal helpers in ``app.connectors.*`` may
change at any time.

Minimal custom connector:

    from wekams_lens_sdk import Connector, IntrospectedTable, QueryResult

    class HelloConnector(Connector):
        type = "hello"
        display_name = "Hello (toy)"
        credential_keys = frozenset({"api_key"})

        async def healthcheck(self) -> bool:
            return bool(self.credentials.get("api_key"))

        async def introspect(self) -> list[IntrospectedTable]:
            return []  # no tables

        async def execute(self, sql, *, max_rows=10_000, timeout_seconds=60):
            return QueryResult(columns=["greeting"], rows=[("hello world",)],
                               row_count=1, truncated=False)

See WRITING_CONNECTORS.md at the repo root for a fuller walkthrough.
"""

from __future__ import annotations

from app.connectors.base import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
)

__all__ = [
    "Connector",
    "ConnectorError",
    "IntrospectedColumn",
    "IntrospectedTable",
    "QueryResult",
]

# Public SDK version. Bumped only when the contract changes.
__version__ = "1.0.0"
