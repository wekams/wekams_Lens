"""Tests for schema-aware SQL validation.

The validator is the first defence against LLM hallucinations. These tests
pin down the contract: parse errors, missing tables, missing columns, and
the passthrough behaviour for cases we deliberately don't analyse (bare
columns, CTEs).
"""

from __future__ import annotations

import pytest

from app.orchestrator.sql_validator import (
    SchemaCatalog,
    TableSchema,
    validate_sql,
)


@pytest.fixture
def catalog() -> SchemaCatalog:
    return SchemaCatalog(
        tables=(
            TableSchema(
                name="customers",
                qualified="public.customers",
                columns=frozenset({"id", "name", "country"}),
            ),
            TableSchema(
                name="orders",
                qualified="public.orders",
                columns=frozenset({"id", "customer_id", "amount", "status"}),
            ),
        )
    )


# ── Happy path ────────────────────────────────────────────────────────


def test_simple_select_passes(catalog: SchemaCatalog):
    r = validate_sql("SELECT * FROM public.customers", catalog)
    assert r.ok is True
    assert r.referenced_tables == ("public.customers",)


def test_bare_table_name_passes(catalog: SchemaCatalog):
    """LLM often omits the schema prefix — we still resolve it."""
    r = validate_sql("SELECT id FROM customers", catalog)
    assert r.ok is True


def test_join_resolves_both_tables(catalog: SchemaCatalog):
    sql = (
        "SELECT c.name, SUM(o.amount) AS total "
        "FROM public.customers c "
        "JOIN public.orders o ON o.customer_id = c.id "
        "GROUP BY c.name"
    )
    r = validate_sql(sql, catalog)
    assert r.ok is True, r.errors
    assert set(r.referenced_tables) == {"public.customers", "public.orders"}


def test_cte_table_is_not_flagged_as_unknown(catalog: SchemaCatalog):
    sql = (
        "WITH paid_orders AS (SELECT * FROM public.orders WHERE status = 'paid') "
        "SELECT COUNT(*) FROM paid_orders"
    )
    r = validate_sql(sql, catalog)
    assert r.ok is True, r.errors


# ── Parse errors ──────────────────────────────────────────────────────


def test_unparseable_sql_fails(catalog: SchemaCatalog):
    r = validate_sql("SELECT FROM WHERE", catalog)
    assert r.ok is False
    assert r.errors[0].kind == "parse"


# ── Unknown tables ────────────────────────────────────────────────────


def test_missing_table_fails(catalog: SchemaCatalog):
    r = validate_sql("SELECT * FROM public.products", catalog)
    assert r.ok is False
    assert any(e.kind == "unknown_table" for e in r.errors)
    err = next(e for e in r.errors if e.kind == "unknown_table")
    assert "products" in err.message
    # Available tables should be listed for the LLM's benefit.
    assert "customers" in err.message or "orders" in err.message


def test_typo_in_table_name_caught(catalog: SchemaCatalog):
    r = validate_sql("SELECT * FROM public.customer", catalog)  # missing 's'
    assert r.ok is False


# ── Unknown columns ───────────────────────────────────────────────────


def test_missing_column_on_aliased_table_fails(catalog: SchemaCatalog):
    sql = "SELECT c.email FROM public.customers c"
    r = validate_sql(sql, catalog)
    assert r.ok is False
    err = next(e for e in r.errors if e.kind == "unknown_column")
    assert "email" in err.message
    assert err.detail["table"] == "public.customers"


def test_bare_column_not_flagged(catalog: SchemaCatalog):
    """Bare column refs (no alias) need full semantic analysis — deferred."""
    r = validate_sql("SELECT email FROM public.customers", catalog)
    # Validator does NOT flag this; deliberate scope choice for v0.1.
    assert r.ok is True


# ── Empty catalog ─────────────────────────────────────────────────────


def test_empty_catalog_rejects_with_sync_hint():
    empty = SchemaCatalog(tables=())
    r = validate_sql("SELECT * FROM customers", empty)
    assert r.ok is False
    assert r.errors[0].kind == "empty_catalog"
    assert "sync" in r.errors[0].message.lower()


# ── Error formatting for the LLM ──────────────────────────────────────


def test_summary_lists_all_errors(catalog: SchemaCatalog):
    sql = "SELECT c.email FROM public.products c"
    r = validate_sql(sql, catalog)
    assert r.ok is False
    msg = r.summary_for_llm()
    assert "validation failed" in msg.lower()
    assert "products" in msg  # the unknown table
    # The validator stopped at the unknown-table error and didn't try to
    # check the column on a non-existent table — that's the right behaviour.


# ── Catalog matching nuances ──────────────────────────────────────────


def test_case_insensitive_table_match(catalog: SchemaCatalog):
    r = validate_sql("SELECT * FROM PUBLIC.CUSTOMERS", catalog)
    assert r.ok is True


def test_case_insensitive_column_match(catalog: SchemaCatalog):
    r = validate_sql("SELECT C.NAME FROM customers C", catalog)
    assert r.ok is True
