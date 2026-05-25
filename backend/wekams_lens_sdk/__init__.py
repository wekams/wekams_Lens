"""Forward-compatible alias for app.sdk.

When the SDK is published as a standalone PyPI package, customers will
``pip install wekams-lens-sdk`` and ``from wekams_lens_sdk import ...``.
Today we re-export from app.sdk so the import path is already what it
will be later — your connector code never needs to change.
"""

from app.sdk import (
    Connector,
    ConnectorError,
    IntrospectedColumn,
    IntrospectedTable,
    QueryResult,
    __version__,
)

__all__ = [
    "Connector",
    "ConnectorError",
    "IntrospectedColumn",
    "IntrospectedTable",
    "QueryResult",
    "__version__",
]
