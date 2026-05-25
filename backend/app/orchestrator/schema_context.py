"""Render the catalog as a compact, LLM-friendly schema string.

Goal: give the model enough structure to write correct SQL without burning
the context window. Phase 1b includes ALL ready sources and ALL their
tables. Phase 2b adds per-source federation aliases so the model knows
how to reference each source in a cross-source JOIN. Phase 3+ will narrow
this with retrieval — for now, our demo catalog is tiny enough that
fitting everything is fine.

The format separates two things the model frequently conflates:

  • The per-source table reference — what you write inside query_data SQL.
    Each connector picks the natural form for its source: `public.customers`
    for Postgres, `files.campaigns` for S3, `logs.checkout` for logs,
    `main.books` for SQLite.

  • The federation reference — what you write inside query_federated SQL.
    Always `<alias>.<schema>.<table>` for Postgres (DuckDB ATTACH keeps the
    schema) and `<alias>.<table>` for file-style sources (S3, logs).

The two forms used to live on the same line of the prompt and the model
mixed them up; they're now visually separated.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import service
from app.catalog.models import Source, SourceStatus
from app.orchestrator.federation import _alias as federation_alias


def _format_table(t, source_alias: str, source_type: str) -> list[str]:  # noqa: ANN001
    """Render one table block in the LLM-facing schema context."""
    # Elasticsearch references are bare index names (no schema prefix).
    if source_type == "elasticsearch":
        single_ref = t.name
    else:
        single_ref = f"{t.schema_name}.{t.name}"

    # Federated form (what to write inside query_federated SQL). ES indices
    # don't currently participate in cross-source federation (DuckDB has no
    # native ES extension); we still show the name so the model knows the
    # source exists.
    if source_type == "postgres":
        fed_ref = f"{source_alias}.{t.schema_name}.{t.name}"
    elif source_type == "elasticsearch":
        fed_ref = f"(use query_data only — cross-source federation with ES is not yet supported)"
    else:
        fed_ref = f"{source_alias}.{t.name}"

    header = f"    {single_ref}"
    if t.row_count_est is not None:
        header += f"  (~{t.row_count_est} rows)"
    if t.description:
        header += f" — {t.description}"

    lines = [
        header,
        f"      reference inside query_data:      {single_ref}",
        f"      reference inside query_federated: {fed_ref}",
        "      columns:",
    ]
    for c in t.columns:
        flags = []
        if c.is_primary_key:
            flags.append("PK")
        if not c.nullable:
            flags.append("NOT NULL")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        line = f"        - {c.name}: {c.data_type}{flag_str}"
        if c.description:
            line += f" — {c.description}"
        lines.append(line)
    return lines


async def render_schema_context(session: AsyncSession) -> str:
    sources = await service.list_sources(session)
    ready = [s for s in sources if _status_str(s) == SourceStatus.READY.value]
    if not ready:
        return (
            "DATA SOURCES: (none ready)\n"
            "No data sources are currently registered. Answer general "
            "questions clearly and tell the user honestly when their "
            "question would require data you don't have."
        )

    blocks: list[str] = ["DATA SOURCES:", ""]
    for s in ready:
        type_str = _type_str(s)
        alias = federation_alias(s.name)
        blocks.append(
            f'source name: "{s.name}"   (type: {type_str}, federation alias: {alias})'
        )
        if type_str == "elasticsearch":
            blocks.append(
                "  ▸ This is an Elasticsearch / OpenSearch source. The `sql` argument "
                "must be a JSON Query DSL body, NOT a SQL string. Example:"
            )
            blocks.append(
                "      {\"size\":0,\"query\":{\"term\":{\"level\":\"error\"}},"
                "\"aggs\":{\"by_day\":{\"date_histogram\":"
                "{\"field\":\"ts\",\"calendar_interval\":\"day\"}}}}"
            )
        blocks.append("  tables:")
        if not s.tables:
            blocks.append("    (no tables — sync may have failed)")
        else:
            for t in s.tables:
                blocks.extend(_format_table(t, alias, type_str))
        blocks.append("")

    blocks.extend(
        [
            "HOW TO PICK A TOOL:",
            "  • Question fits inside ONE source → call query_data with",
            "    {source: \"<source name>\", sql: <SQL using the 'reference inside query_data' form>}",
            "  • Question requires JOINing across TWO OR MORE sources → call query_federated with",
            "    {sources: [<source names>], sql: <DuckDB SQL using the 'reference inside query_federated' form for every table>}",
            "  • General/about-Lens question → answer directly without a tool call.",
            "",
            "RULES:",
            "  • Never reference a table by the federation form inside query_data — that schema does not exist there.",
            "  • Never reference a table by the single-source form inside query_federated — the engine won't find it.",
            "  • Aggregate on the database side; do not return huge rowsets.",
            "  • Pre-aggregate via CTEs before joining many-to-many tables so JOINs don't multiply row counts.",
            "  • String matches are exact: '/checkout' is not 'checkout'. If a literal returns 0 rows, SELECT DISTINCT the column first.",
        ]
    )
    return "\n".join(blocks)


def _status_str(s: Source) -> str:
    return s.status.value if hasattr(s.status, "value") else str(s.status)


def _type_str(s: Source) -> str:
    return s.type.value if hasattr(s.type, "value") else str(s.type)
