"""End-to-end test of the Excel (.xlsx) connector.

Builds a tmp .xlsx with two sheets and exercises healthcheck →
introspect → execute against it. No external infrastructure required.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from app.connectors.registry import get_connector


@pytest.fixture
def xlsx_file(tmp_path: Path) -> Path:
    """Build a small workbook with a `Customers` and an `Orders` sheet."""
    wb = Workbook()
    cust = wb.active
    cust.title = "Customers"
    cust.append(["id", "name", "country"])
    cust.append([1, "Alice", "SG"])
    cust.append([2, "Bob", "IN"])
    cust.append([3, "Cara", "AU"])

    orders = wb.create_sheet("Orders")
    orders.append(["id", "customer_id", "amount"])
    orders.append([10, 1, 49.99])
    orders.append([11, 1, 12.50])
    orders.append([12, 2, 99.00])

    path = tmp_path / "demo.xlsx"
    wb.save(path)
    return path


@pytest.mark.asyncio
async def test_healthcheck_succeeds_for_valid_xlsx(xlsx_file: Path):
    c = get_connector("excel", config={"path": str(xlsx_file)})
    assert await c.healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_fails_for_missing_file(tmp_path: Path):
    c = get_connector("excel", config={"path": str(tmp_path / "nope.xlsx")})
    assert await c.healthcheck() is False


@pytest.mark.asyncio
async def test_healthcheck_fails_for_wrong_extension(tmp_path: Path):
    bogus = tmp_path / "not-excel.txt"
    bogus.write_text("hello")
    c = get_connector("excel", config={"path": str(bogus)})
    assert await c.healthcheck() is False


@pytest.mark.asyncio
async def test_introspect_returns_both_sheets(xlsx_file: Path):
    c = get_connector("excel", config={"path": str(xlsx_file)})
    tables = await c.introspect()
    names = {t.name for t in tables}
    assert names == {"Customers", "Orders"}


@pytest.mark.asyncio
async def test_introspect_columns_from_header_row(xlsx_file: Path):
    c = get_connector("excel", config={"path": str(xlsx_file)})
    tables = await c.introspect()
    customers = next(t for t in tables if t.name == "Customers")
    assert [col.name for col in customers.columns] == ["id", "name", "country"]


@pytest.mark.asyncio
async def test_execute_simple_select(xlsx_file: Path):
    c = get_connector("excel", config={"path": str(xlsx_file)})
    r = await c.execute('SELECT country, COUNT(*) AS n FROM Customers GROUP BY country ORDER BY country')
    assert r.columns == ["country", "n"]
    # rows-as-tuples; values stored as strings, COUNT returns int.
    assert r.rows == [("AU", 1), ("IN", 1), ("SG", 1)]


@pytest.mark.asyncio
async def test_execute_join_across_sheets(xlsx_file: Path):
    c = get_connector("excel", config={"path": str(xlsx_file)})
    r = await c.execute(
        "SELECT c.name, ROUND(SUM(CAST(o.amount AS DOUBLE)), 2) AS total "
        "FROM Customers c JOIN Orders o ON o.customer_id = c.id "
        "GROUP BY c.name ORDER BY c.name"
    )
    assert r.columns == ["name", "total"]
    by_name = dict(r.rows)
    assert by_name == {"Alice": 62.49, "Bob": 99.0}


@pytest.mark.asyncio
async def test_execute_rejects_writes(xlsx_file: Path):
    from app.connectors import ConnectorError

    c = get_connector("excel", config={"path": str(xlsx_file)})
    with pytest.raises(ConnectorError):
        await c.execute("DELETE FROM Customers")


@pytest.mark.asyncio
async def test_execute_enforces_max_rows(xlsx_file: Path):
    c = get_connector("excel", config={"path": str(xlsx_file)})
    r = await c.execute("SELECT * FROM Customers", max_rows=2)
    assert r.row_count == 2
    assert r.truncated is True
