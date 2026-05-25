"""Render a Conversation as a Markdown transcript.

Goal: a Lens transcript that pastes cleanly into Slack, GitHub issues,
Notion, or any Markdown-aware tool — so a user can share what they
found without forcing the reader to install Lens first.

Format:

    # <conversation title>

    > Wekams Lens conversation - YYYY-MM-DD HH:MM UTC - N messages

    ## You
    <user text>

    ## Lens
    ```sql
    -- source: demo-shop
    SELECT COUNT(*) AS customer_count FROM public.customers;
    ```

    | customer_count |
    | --- |
    | 7 |

    We have 7 customers in total.

Result tables are capped (default 20 rows + truncated marker) so a
1000-row query doesn't produce a 30 KB transcript. SQL is in a fenced
``sql block. Failed tool calls render with a clearly-marked panel.
"""

from __future__ import annotations

import json
from typing import Any

from app.catalog.models import ChatMessage, Conversation

_MAX_ROWS = 20


def render_conversation_markdown(conv: Conversation) -> str:
    lines: list[str] = []
    lines.append(f"# {conv.title}")
    lines.append("")
    lines.append(
        f"> Wekams Lens conversation - {conv.updated_at.strftime('%Y-%m-%d %H:%M UTC')} "
        f"- {len(conv.messages)} messages"
    )
    lines.append("")

    last_speaker: str | None = None
    sorted_msgs = sorted(conv.messages, key=lambda m: m.sequence)

    for m in sorted_msgs:
        if m.role == "user":
            if last_speaker != "user":
                lines.append("## You")
                lines.append("")
            lines.append(m.content.strip())
            lines.append("")
            last_speaker = "user"
            continue

        if m.role == "system":
            continue  # never render system prompts in user-facing exports

        # assistant or tool — both render under the same "Lens" speaker.
        if last_speaker != "lens":
            lines.append("## Lens")
            lines.append("")
            last_speaker = "lens"

        if m.role == "assistant":
            _render_assistant(lines, m)
        elif m.role == "tool":
            _render_tool_result(lines, m)

    return "\n".join(lines).rstrip() + "\n"


def _render_assistant(lines: list[str], m: ChatMessage) -> None:
    if m.tool_calls:
        for tc in m.tool_calls:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            name = fn.get("name", "tool")
            raw_args = fn.get("arguments", "{}")
            try:
                args: dict = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}

            source = args.get("source")
            sources = args.get("sources")
            sql = (args.get("sql") or "").strip()

            header_bits: list[str] = []
            if name == "query_federated" and isinstance(sources, list):
                header_bits.append(
                    "Federating across " + ", ".join(str(s) for s in sources)
                )
            elif source:
                header_bits.append(f"Querying source: {source}")
            else:
                header_bits.append(f"Tool: {name}")
            if header_bits:
                lines.append("> " + " - ".join(header_bits))
                lines.append("")
            if sql:
                lines.append("```sql")
                lines.append(sql)
                lines.append("```")
                lines.append("")

    if m.content.strip():
        lines.append(m.content.strip())
        lines.append("")


def _render_tool_result(lines: list[str], m: ChatMessage) -> None:
    raw = m.tool_data
    has_envelope = isinstance(raw, dict) and "ok" in raw
    ok = raw["ok"] if has_envelope else True  # legacy rows assumed ok
    data = (raw.get("data") if has_envelope else raw) if isinstance(raw, dict) else None

    if not ok:
        lines.append("> **Query failed**")
        lines.append("")
        lines.append("```")
        lines.append((m.content or "").strip())
        lines.append("```")
        lines.append("")
        return

    if not isinstance(data, dict) or not data.get("rows"):
        lines.append("_Query returned 0 rows._")
        lines.append("")
        return

    columns: list[str] = list(data.get("columns") or [])
    rows: list[dict[str, Any]] = list(data.get("rows") or [])
    row_count = data.get("row_count", len(rows))
    truncated = bool(data.get("truncated"))

    shown = rows[:_MAX_ROWS]

    if columns:
        lines.append("| " + " | ".join(_md_cell(c) for c in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for r in shown:
            lines.append("| " + " | ".join(_md_cell(r.get(c)) for c in columns) + " |")

    note_bits: list[str] = []
    if len(rows) > len(shown):
        note_bits.append(f"showing first {len(shown)} of {row_count}")
    elif row_count > len(shown):
        note_bits.append(f"{row_count} rows total")
    if truncated:
        note_bits.append("truncated by the connector row cap")
    if note_bits:
        lines.append("")
        lines.append("_" + " - ".join(note_bits) + "_")
    lines.append("")


def _md_cell(v: Any) -> str:
    """Markdown-table-safe cell rendering. Escapes pipes + newlines."""
    if v is None:
        return "-"
    s = str(v)
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")
