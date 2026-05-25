# Writing a custom Wekams Lens connector

Wekams Lens can talk to any data source you can reach from Python. The
built-in connectors (Postgres, S3) and the bundled reference connector
(SQLite) all implement the same small interface — and so does anything
you build yourself.

This document walks through writing one in about ten minutes. The
finished example is `connectors/external/sqlite_connector.py` in the
repo — look there if you prefer reading code.

---

## The contract

A connector is a Python class extending `Connector` from the SDK:

```python
from wekams_lens_sdk import (
    Connector, ConnectorError,
    IntrospectedColumn, IntrospectedTable, QueryResult,
)
```

It has three required `async` methods:

```python
class MyConnector(Connector):
    type = "myservice"                       # unique lowercase id
    display_name = "My Service"              # shown in the UI
    credential_keys = frozenset({"api_key"}) # fields to encrypt at rest

    async def healthcheck(self) -> bool: ...
    async def introspect(self) -> list[IntrospectedTable]: ...
    async def execute(self, sql, *, max_rows, timeout_seconds) -> QueryResult: ...
```

Optional: an `async def close(self) -> None:` for cleanup of any
long-lived resources (default is a no-op).

### `__init__` and the catalog split

Connectors are instantiated with two dicts:

```python
def __init__(self, config: dict, credentials: dict | None = None):
    self.config = config           # non-secret fields from the UI
    self.credentials = credentials or {}  # decrypted secret fields
```

When a user adds a source through the UI, Wekams Lens splits the form
data using your `credential_keys` set: any field whose name is in that
set is encrypted before storage, decrypted only when a query runs, and
delivered to you in `self.credentials`. Everything else lives in
`self.config`.

### `healthcheck()`

Cheap call — *can we reach this source with these credentials?* Returns
True/False. Errors should be swallowed (return False) so the Sources
UI's `Test connection` button always renders something useful.

### `introspect()`

Discover what's queryable. Returns a list of `IntrospectedTable`:

```python
@dataclass
class IntrospectedTable:
    schema_name: str            # logical grouping (e.g. "public", "files")
    name: str
    description: str | None = None
    row_count_est: int | None = None
    columns: list[IntrospectedColumn] = ...

@dataclass
class IntrospectedColumn:
    name: str
    data_type: str              # free-form (Postgres "text", SQLite "TEXT", whatever)
    nullable: bool = True
    is_primary_key: bool = False
    position: int = 0
    description: str | None = None
```

Must be idempotent — safe to call repeatedly. Should be **read-only**
on the source: no temp tables, no DDL.

### `execute(sql, *, max_rows, timeout_seconds)`

Run a single read-only `SELECT` (or your source's equivalent) and
return:

```python
@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    row_count: int
    truncated: bool       # True if your source returned more than max_rows
```

You are responsible for refusing write statements. The convention is a
top-of-file regex matching `INSERT|UPDATE|DELETE|...`. Be conservative.

Use `asyncio.to_thread(...)` when the underlying driver is synchronous
(SQLite, most ODBC drivers, boto3) so you don't block the event loop.

---

## Where the file lives

Wekams Lens looks for plugins in two locations:

| Path | When to use |
|---|---|
| `~/.wekams/connectors/*.py` | Personal / per-machine, not checked in |
| `<repo>/connectors/external/*.py` | Checked into the repo, shipped with the deploy |

Override with `WEKAMS_CONNECTOR_DIRS` (colon-separated paths) if you want
different locations.

Each `*.py` is imported at backend startup. Every class that
**(a) extends `Connector`** and **(b) is defined in that file** is
registered automatically.

A registration failure (bad import, duplicate `type` string) is logged but
**does not crash the server** — a broken plugin can't take down the rest
of the product.

---

## End-to-end walkthrough

A minimal "hello world" connector that returns a single greeting row:

```python
# ~/.wekams/connectors/hello.py
from wekams_lens_sdk import (
    Connector, IntrospectedColumn, IntrospectedTable, QueryResult,
)

class HelloConnector(Connector):
    type = "hello"
    display_name = "Hello (toy)"
    credential_keys = frozenset()

    async def healthcheck(self) -> bool:
        return True

    async def introspect(self) -> list[IntrospectedTable]:
        return [IntrospectedTable(
            schema_name="main",
            name="greetings",
            row_count_est=1,
            columns=[IntrospectedColumn(name="message", data_type="TEXT", position=1)],
        )]

    async def execute(self, sql, *, max_rows=10_000, timeout_seconds=60):
        return QueryResult(
            columns=["message"],
            rows=[("hello world",)],
            row_count=1,
            truncated=False,
        )
```

1. Save it to `~/.wekams/connectors/hello.py`.
2. Restart the Wekams Lens backend.
3. Open `http://localhost:3000/sources` → **+ Add**. The type picker
   now shows **Hello (toy)** alongside Postgres and S3.
4. Pick it, give it any name, click **Add source**.
5. Ask Lens: *"what does the hello source say?"*

---

## Best practices

- **Be read-only by default.** Block write statements at the connector
  boundary. Customers expect Lens to never mutate their data.
- **Wrap driver errors in `ConnectorError`.** The orchestrator catches
  these specifically; uncaught driver exceptions bubble up as `500 Internal
  Server Error` and look worse.
- **Push aggregation to the source.** Don't return 100k rows just to
  COUNT them client-side; let the source do its job.
- **Respect `max_rows` and `timeout_seconds`.** Pass them through to your
  driver where supported (Postgres `statement_timeout`, DuckDB `SET
  TIMEOUT`, etc.).
- **Cheap healthchecks.** `SELECT 1` style — sub-second.
- **No secrets in `__repr__`/log lines.** `self.credentials` should never
  hit stdout.

---

## Federation interaction

By default, custom connectors participate in `query_data` (single-source
NL → SQL) only. The federation engine (`query_federated`) currently
knows two source types natively:

- **Postgres** → attached via DuckDB's `postgres` extension
- **S3** → attached via DuckDB's `httpfs` + glob

If you want your connector to also participate in cross-source JOINs,
either:

1. Convert your data to a format DuckDB reads (Parquet / CSV in S3, a
   real Postgres backing store) and register that, or
2. Wait for Phase 3 of the SDK roadmap — a `prepare_for_federation()`
   hook that lets a connector inject views into the federation engine's
   DuckDB session. (Not yet shipped.)

---

## Testing

The `Connector` interface is pure async Python — no FastAPI, no DB
session, no orchestrator. You can unit-test a connector directly:

```python
import asyncio
from my_connector import MyConnector

async def main():
    c = MyConnector(config={"host": "localhost"}, credentials={"api_key": "xxx"})
    assert await c.healthcheck()
    tables = await c.introspect()
    print(f"{len(tables)} tables")
    result = await c.execute("SELECT 1")
    print(result)

asyncio.run(main())
```

That's it. If you ship Wekams Lens to an enterprise customer who needs
their internal mainframe / proprietary REST API / niche SaaS connected,
a competent Python developer can have it working in an afternoon.
