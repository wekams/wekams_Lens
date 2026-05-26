"""Schema-aware SQL validation.

Catches LLM hallucinations BEFORE we send them to the source database:
  - SQL that doesn't parse
  - Tables that don't exist in the introspected catalog
  - Columns that don't exist on the resolved table (when qualified by an alias)

Validation failures are returned to the orchestrator as a structured error
which is surfaced to the LLM as a tool result — the LLM then retries with
a corrected query in the existing tool-use loop, so no separate retry
machinery is needed.

Scope (Community v0.1):
  - Validates table references
  - Validates qualified column references (e.g. `c.name` where `c` is a
    table alias)
  - Skips bare column references (proper resolution needs full semantic
    analysis; deferred)
  - Skips type compatibility checks
  - Skips join-condition consistency checks
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


@dataclass(frozen=True, slots=True)
class TableSchema:
    """One table the LLM is allowed to reference."""

    name: str  # bare table name, e.g. "customers"
    qualified: str  # what you'd write in SQL, e.g. "public.customers"
    columns: frozenset[str]

    def has_column(self, col: str) -> bool:
        col_lower = col.lower()
        return any(c.lower() == col_lower for c in self.columns)


@dataclass(frozen=True, slots=True)
class SchemaCatalog:
    """The set of tables that exist in a source (or across federated sources)."""

    tables: tuple[TableSchema, ...]

    def find(self, ref: str) -> TableSchema | None:
        """Resolve a table reference. Matches either bare name or fully-qualified."""
        ref_lower = ref.lower().strip('"').strip("`")
        for t in self.tables:
            if t.qualified.lower() == ref_lower:
                return t
        # Fall back to bare-name match — useful when LLM omits the schema prefix.
        for t in self.tables:
            if t.name.lower() == ref_lower:
                return t
        return None

    def is_empty(self) -> bool:
        return len(self.tables) == 0


@dataclass(frozen=True, slots=True)
class ValidationError:
    kind: str  # "parse" | "unknown_table" | "unknown_column" | "empty_catalog"
    message: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: tuple[ValidationError, ...] = ()
    referenced_tables: tuple[str, ...] = ()  # qualified names that resolved

    @classmethod
    def success(cls, referenced: tuple[str, ...] = ()) -> ValidationResult:
        return cls(ok=True, referenced_tables=referenced)

    @classmethod
    def failure(cls, *errors: ValidationError) -> ValidationResult:
        return cls(ok=False, errors=errors)

    def summary_for_llm(self) -> str:
        """Format errors as a compact message the LLM can act on."""
        lines = [f"SQL validation failed ({len(self.errors)} issue(s)):"]
        for e in self.errors:
            lines.append(f"  - {e.message}")
        lines.append("Review the schema above and try again with corrected references.")
        return "\n".join(lines)


def _resolve_table_ref(node: exp.Table) -> str:
    """Render a table reference back to text, ignoring catalog/db prefixes if absent."""
    parts: list[str] = []
    db = node.args.get("db")
    if db is not None:
        parts.append(db.name)
    parts.append(node.name)
    return ".".join(parts)


def validate_sql(sql: str, catalog: SchemaCatalog, dialect: str = "duckdb") -> ValidationResult:
    """Validate SQL against a per-source schema catalog.

    Returns ValidationResult with ok=True on success, or with a list of
    specific errors on failure. Errors are designed to be surfaced verbatim
    to the LLM so it can self-correct.
    """
    if catalog.is_empty():
        return ValidationResult.failure(
            ValidationError(
                kind="empty_catalog",
                message=(
                    "The source has no introspected tables yet. "
                    "Run the source's sync action before querying it."
                ),
            )
        )

    # ── 1. Parse ──────────────────────────────────────────────────────
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
    except sqlglot.errors.ParseError as exc:
        return ValidationResult.failure(
            ValidationError(
                kind="parse",
                message=f"SQL did not parse: {exc}",
            )
        )

    if tree is None:
        return ValidationResult.failure(
            ValidationError(kind="parse", message="Empty SQL statement.")
        )

    errors: list[ValidationError] = []
    referenced: list[str] = []
    alias_to_schema: dict[str, TableSchema] = {}

    # ── 2. Tables ─────────────────────────────────────────────────────
    # Build the set of CTE names so we don't mistake them for missing tables.
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}

    for tbl in tree.find_all(exp.Table):
        ref = _resolve_table_ref(tbl)
        if ref.lower() in cte_names:
            # CTE references are valid; we don't validate columns inside CTEs at this depth.
            continue

        schema = catalog.find(ref)
        if schema is None:
            errors.append(
                ValidationError(
                    kind="unknown_table",
                    message=(
                        f"Unknown table {ref!r}. "
                        f"Available tables: {', '.join(sorted(t.qualified for t in catalog.tables[:12]))}"
                    ),
                    detail={"ref": ref, "available": [t.qualified for t in catalog.tables]},
                )
            )
            continue

        referenced.append(schema.qualified)
        # Record the alias (or bare table name when no alias) for column lookup below.
        alias = tbl.alias_or_name.lower()
        alias_to_schema[alias] = schema

    # ── 3. Qualified columns ──────────────────────────────────────────
    # Bare columns (no `alias.` prefix) are skipped — resolving them
    # against multiple joined tables requires deeper semantic analysis.
    for col in tree.find_all(exp.Column):
        table_part = col.table
        if not table_part:
            continue
        ts = alias_to_schema.get(table_part.lower())
        if ts is None:
            # Could be a CTE alias or a not-yet-resolved scope; skip.
            continue
        if not ts.has_column(col.name):
            sorted_cols = sorted(ts.columns)
            errors.append(
                ValidationError(
                    kind="unknown_column",
                    message=(
                        f"Column {col.name!r} does not exist on {ts.qualified!r}. "
                        f"Available columns: {', '.join(sorted_cols[:10])}"
                        + ("…" if len(sorted_cols) > 10 else "")
                    ),
                    detail={
                        "table": ts.qualified,
                        "column": col.name,
                        "available": sorted_cols,
                    },
                )
            )

    if errors:
        return ValidationResult.failure(*errors)
    return ValidationResult.success(referenced=tuple(referenced))


def build_catalog_from_orm_tables(orm_tables, source_type: str = "") -> SchemaCatalog:  # noqa: ANN001
    """Convert a list of catalog.Table ORM rows into a SchemaCatalog.

    The qualified name uses the source's natural form: `schema.table` for
    relational sources, bare `table` for Elasticsearch / log-style sources
    where schemas don't apply.
    """
    tables: list[TableSchema] = []
    for t in orm_tables:
        if source_type == "elasticsearch":
            qualified = t.name
        else:
            qualified = f"{t.schema_name}.{t.name}"
        tables.append(
            TableSchema(
                name=t.name,
                qualified=qualified,
                columns=frozenset(c.name for c in t.columns),
            )
        )
    return SchemaCatalog(tables=tuple(tables))
