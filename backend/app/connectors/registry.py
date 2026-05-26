"""Connector type → class lookup.

The single place that maps a string type to a concrete Connector class.

Built-in connectors are imported at module-load time. Custom connectors
are discovered from two directories at startup:

  $WEKAMS_CONNECTOR_DIRS  — colon-separated, environment-overridable
                            (default: ~/.wekams/connectors and the repo's
                            connectors/external/)

Each `*.py` file in those directories is imported; every Connector
subclass declared in the module is registered under its `type` attribute.

Loading errors are logged but never fatal — a broken plugin must not
take the whole product down.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import threading
from pathlib import Path

from app.connectors.azure_blob import AzureBlobConnector
from app.connectors.base import Connector, ConnectorError
from app.connectors.elasticsearch import ElasticsearchConnector
from app.connectors.excel import ExcelConnector
from app.connectors.gcs import GcsConnector
from app.connectors.logs import LogsConnector
from app.connectors.postgres import PostgresConnector
from app.connectors.s3 import S3Connector
from app.core.logging import get_logger

log = get_logger(__name__)


_REGISTRY: dict[str, type[Connector]] = {
    PostgresConnector.type: PostgresConnector,
    S3Connector.type: S3Connector,
    AzureBlobConnector.type: AzureBlobConnector,
    GcsConnector.type: GcsConnector,
    LogsConnector.type: LogsConnector,
    ElasticsearchConnector.type: ElasticsearchConnector,
    ExcelConnector.type: ExcelConnector,
}

_LOADED = False
_LOAD_LOCK = threading.Lock()


# ── Public API ──────────────────────────────────────────────────────


def get_connector(
    source_type: str,
    config: dict,
    credentials: dict | None = None,
) -> Connector:
    _ensure_loaded()
    cls = _REGISTRY.get(source_type)
    if cls is None:
        raise ConnectorError(
            f"unknown source type {source_type!r}. "
            f"Available: {', '.join(sorted(_REGISTRY))}"
        )
    return cls(config=config, credentials=credentials)


def supported_types() -> list[str]:
    _ensure_loaded()
    return sorted(_REGISTRY.keys())


def is_supported_type(t: str) -> bool:
    _ensure_loaded()
    return t in _REGISTRY


def credential_keys_for(source_type: str) -> frozenset[str]:
    """Return the set of connection-field names that should be encrypted."""
    _ensure_loaded()
    cls = _REGISTRY.get(source_type)
    if cls is None:
        return frozenset()
    return cls.credential_keys


def describe_types() -> list[dict]:
    """For the UI type picker: every type with its display name and
    credential field names."""
    _ensure_loaded()
    out = []
    for t, cls in sorted(_REGISTRY.items()):
        out.append(
            {
                "type": t,
                "display_name": cls.display_name or t,
                "credential_keys": sorted(cls.credential_keys),
                "module": getattr(cls, "__module__", ""),
                "builtin": cls.__module__.startswith("app.connectors."),
            }
        )
    return out


def register(connector_cls: type[Connector]) -> None:
    """Add a connector class to the registry. Idempotent for the same
    class; raises on type-name collision with a different class."""
    t = connector_cls.type
    if not t or t == "abstract":
        raise ValueError(
            f"connector {connector_cls.__name__} did not override `type`"
        )
    existing = _REGISTRY.get(t)
    if existing is not None and existing is not connector_cls:
        raise ConnectorError(
            f"connector type {t!r} is already registered by "
            f"{existing.__module__}.{existing.__qualname__}"
        )
    _REGISTRY[t] = connector_cls
    log.info(
        "connectors.registered",
        type=t,
        module=connector_cls.__module__,
        cls=connector_cls.__qualname__,
    )


# ── Plugin discovery ────────────────────────────────────────────────


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        _load_external_plugins()
        _LOADED = True


def _plugin_dirs() -> list[Path]:
    raw = os.environ.get("WEKAMS_CONNECTOR_DIRS")
    if raw:
        return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]

    dirs = [Path.home() / ".wekams" / "connectors"]
    # Repo-checked-in plugins: <repo-root>/connectors/external
    here = Path(__file__).resolve()
    # backend/app/connectors/registry.py → backend → repo-root
    repo_root = here.parents[3]
    dirs.append(repo_root / "connectors" / "external")
    return dirs


def _load_external_plugins() -> None:
    for plugin_dir in _plugin_dirs():
        if not plugin_dir.is_dir():
            log.debug("connectors.plugin_dir.missing", path=str(plugin_dir))
            continue
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            _import_plugin(path)


def _import_plugin(path: Path) -> None:
    mod_name = f"wekams_lens_plugins.{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        log.warning("connectors.plugin.spec_failed", path=str(path))
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        log.warning("connectors.plugin.import_failed", path=str(path), error=str(exc))
        return

    found = 0
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if obj is Connector:
            continue
        if not issubclass(obj, Connector):
            continue
        # Skip classes that are imports from elsewhere (only register
        # classes whose module is this plugin).
        if obj.__module__ != mod_name:
            continue
        try:
            register(obj)
            found += 1
        except (ValueError, ConnectorError) as exc:
            log.warning("connectors.plugin.register_failed", cls=obj.__name__, error=str(exc))

    if found == 0:
        log.info("connectors.plugin.no_connectors_found", path=str(path))
