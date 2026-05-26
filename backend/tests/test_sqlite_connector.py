"""End-to-end test of the SQLite reference connector.

This is the cheapest "real" connector test — no Postgres / S3 / etc.
infrastructure required. Exercises healthcheck → introspect → execute,
which is the full contract every connector implements.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.connectors.registry import get_connector


@pytest.fixture
def sqlite_db(tmp_path: Path) -> Path:
    """Build a tiny SQLite database with two tables and return its path."""
    db_path = tmp_path / "lens-test.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        INSERT INTO customers (name, country) VALUES
            ('Alice', 'SG'),
            ('Bob', 'IN'),
            ('Cara', 'AU');
        INSERT INTO orders (customer_id, amount) VALUES
            (1, 49.99),
            (1, 12.50),
            (2, 99.00);
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.asyncio
async def test_healthcheck_succeeds_for_valid_path(sqlite_db: Path):
    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    assert await c.healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_fails_for_missing_file(tmp_path: Path):
    c = get_connector("sqlite", config={"path": str(tmp_path / "does-not-exist.db")})
    assert await c.healthcheck() is False


@pytest.mark.asyncio
async def test_introspect_returns_both_tables(sqlite_db: Path):
    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    tables = await c.introspect()
    names = {t.name for t in tables}
    assert names == {"customers", "orders"}


@pytest.mark.asyncio
async def test_introspect_finds_primary_keys(sqlite_db: Path):
    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    tables = await c.introspect()
    customers = next(t for t in tables if t.name == "customers")
    pk_cols = [c.name for c in customers.columns if c.is_primary_key]
    assert pk_cols == ["id"]


@pytest.mark.asyncio
async def test_execute_returns_rows(sqlite_db: Path):
    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    result = await c.execute("SELECT country, COUNT(*) AS n FROM customers GROUP BY country ORDER BY country")
    assert result.columns == ["country", "n"]
    assert result.row_count == 3
    assert result.rows == [("AU", 1), ("IN", 1), ("SG", 1)]


@pytest.mark.asyncio
async def test_execute_join(sqlite_db: Path):
    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    result = await c.execute(
        "SELECT c.name, ROUND(SUM(o.amount), 2) AS total "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "GROUP BY c.name ORDER BY c.name"
    )
    assert result.columns == ["name", "total"]
    by_name = dict(result.rows)
    assert by_name == {"Alice": 62.49, "Bob": 99.0}


@pytest.mark.asyncio
async def test_execute_rejects_writes(sqlite_db: Path):
    """Connectors are read-only by design; mutations must be rejected."""
    from app.connectors import ConnectorError

    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    with pytest.raises(ConnectorError):
        await c.execute("DELETE FROM customers")


@pytest.mark.asyncio
async def test_execute_enforces_max_rows(sqlite_db: Path):
    c = get_connector("sqlite", config={"path": str(sqlite_db)})
    result = await c.execute("SELECT * FROM customers", max_rows=2)
    assert result.row_count == 2
    assert result.truncated is True
