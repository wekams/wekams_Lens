"""Connector registry + protocol-compliance tests.

Catches regressions like:
- Built-in connector type accidentally unregistered
- External plugin failing to auto-load
- A connector class forgetting to override a required attribute
"""

from __future__ import annotations

import pytest

from app.connectors.base import Connector
from app.connectors.registry import (
    credential_keys_for,
    describe_types,
    get_connector,
    is_supported_type,
    supported_types,
)

BUILTIN_TYPES = {
    "postgres",
    "s3",
    "azure_blob",
    "gcs",
    "logs",
    "elasticsearch",
    "excel",
}

# The reference SQLite plugin auto-loads from connectors/external/.
EXPECTED_PLUGIN_TYPES = {"sqlite"}


def test_all_builtin_types_registered():
    registered = set(supported_types())
    missing = BUILTIN_TYPES - registered
    assert not missing, f"missing built-in connector types: {missing}"


def test_sqlite_reference_plugin_autoloads():
    """The external SQLite plugin in connectors/external/ must auto-load on first registry access."""
    assert "sqlite" in supported_types()


def test_is_supported_type_recognises_builtins():
    for t in BUILTIN_TYPES:
        assert is_supported_type(t), f"{t} should be supported"
    assert not is_supported_type("nope-not-a-thing")


def test_describe_types_returns_metadata():
    rows = describe_types()
    by_type = {r["type"]: r for r in rows}
    for t in BUILTIN_TYPES:
        assert t in by_type, f"{t} missing from describe_types()"
        assert by_type[t]["display_name"], f"{t} has no display_name"
        assert "credential_keys" in by_type[t]
        assert "module" in by_type[t]
        assert by_type[t]["builtin"] is True


def test_sqlite_plugin_marked_non_builtin():
    rows = describe_types()
    sqlite_row = next((r for r in rows if r["type"] == "sqlite"), None)
    assert sqlite_row is not None
    assert sqlite_row["builtin"] is False


def test_credential_keys_for_postgres_includes_password():
    keys = credential_keys_for("postgres")
    assert "password" in keys


@pytest.mark.parametrize("type_name", sorted(BUILTIN_TYPES | EXPECTED_PLUGIN_TYPES))
def test_each_connector_is_constructible(type_name: str):
    """get_connector() should return a Connector instance for every registered type."""
    instance = get_connector(type_name, config={}, credentials={})
    assert isinstance(instance, Connector)
    assert instance.type == type_name


@pytest.mark.parametrize("type_name", sorted(BUILTIN_TYPES | EXPECTED_PLUGIN_TYPES))
def test_each_connector_has_required_methods(type_name: str):
    """healthcheck / introspect / execute must be overridden on the concrete class."""
    instance = get_connector(type_name, config={}, credentials={})
    cls = type(instance)
    for method in ("healthcheck", "introspect", "execute"):
        assert getattr(cls, method) is not getattr(Connector, method), (
            f"{type_name} did not override {method}()"
        )
