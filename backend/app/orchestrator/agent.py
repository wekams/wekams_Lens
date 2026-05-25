"""Orchestrator — the agent loop.

  user message
    ↓
  build system prompt + schema context
    ↓
  loop:
    LLM.complete(messages, tools=[query_data])
      ↓
    if assistant has tool calls:
      execute each, append tool messages, continue
    else:
      stream final answer to client
      break

  Emits typed events for the API layer to serialize to SSE.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from app.catalog.db import get_session
from app.core.logging import get_logger
from app.llm import LLMBackend, Message, Role, ToolCall
from app.orchestrator.schema_context import render_schema_context
from app.orchestrator.tools import ALL_TOOLS, ToolResult, execute_tool_call

log = get_logger(__name__)


_SYSTEM_PROMPT_TEMPLATE = """\
You are Wekams Lens — a unified data agent. You help users explore and
reason about data across multiple registered sources by answering in
plain language.

Choosing the right tool:
  • If the question can be answered from ONE source, call `query_data`.
  • If the question requires JOINing across two or more sources (e.g.
    "which of our database customers viewed the checkout page in our
    web events?"), call `query_federated` with the list of source
    names and a single DuckDB SQL statement that references each
    source via its federation alias (shown below in DATA SOURCES).
  • If the question is general ("what is Wekams Lens?", "what can you
    do?"), answer directly without calling tools.
  • If a question would require a source that isn't registered, say so
    honestly — do not fabricate data.

After a tool returns, write a clear natural-language answer that
references the actual numbers. Aggregate on the database side; do not
return huge rowsets.

SQL correctness notes:
  • When the same entity (e.g., a customer) needs to be counted from
    one table and also joined to another many-to-many table, pre-
    aggregate first with CTEs or subqueries — do NOT throw all the
    joins together and then COUNT, because the inner join will
    multiply rows and inflate the count (Cartesian fanout).
  • String values are case- and prefix-sensitive: '/checkout' is
    different from 'checkout'. If a literal match returns 0 rows,
    consider listing distinct values first (SELECT DISTINCT col …
    LIMIT 20) and trying again.

{schema_context}
"""


# ── Event types emitted by run() ────────────────────────────────────


@dataclass(slots=True, frozen=True, kw_only=True)
class _Event:
    type: str

@dataclass(slots=True, frozen=True, kw_only=True)
class TokenEvent(_Event):
    text: str
    type: Literal["token"] = "token"

@dataclass(slots=True, frozen=True, kw_only=True)
class ToolCallEvent(_Event):
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: Literal["tool_call"] = "tool_call"

@dataclass(slots=True, frozen=True, kw_only=True)
class ToolResultEvent(_Event):
    call_id: str
    name: str
    ok: bool
    summary: str
    data: dict[str, Any] | None
    type: Literal["tool_result"] = "tool_result"

@dataclass(slots=True, frozen=True, kw_only=True)
class ErrorEvent(_Event):
    message: str
    type: Literal["error"] = "error"

@dataclass(slots=True, frozen=True, kw_only=True)
class DoneEvent(_Event):
    type: Literal["done"] = "done"


OrchestratorEvent = (
    TokenEvent | ToolCallEvent | ToolResultEvent | ErrorEvent | DoneEvent
)


# ── Orchestrator ────────────────────────────────────────────────────


class Orchestrator:
    """One conversation = one Orchestrator.run(messages) call.

    Stateless across requests (the catalog is the persistent state).
    """

    MAX_TOOL_TURNS = 5  # safety cap so a misbehaving model can't loop forever

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm

    async def run(self, user_messages: list[Message]) -> AsyncIterator[OrchestratorEvent]:
        # Fresh session for this request — the orchestrator doesn't hold one
        # so each tool call gets a clean transaction scope.
        async with get_session() as session:
            schema_ctx = await render_schema_context(session)

        history: list[Message] = [
            Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT_TEMPLATE.format(schema_context=schema_ctx)),
            *user_messages,
        ]

        for turn in range(self.MAX_TOOL_TURNS):
            log.info("orchestrator.turn", n=turn, history_len=len(history))

            try:
                assistant = await self._llm.complete(
                    history,
                    tools=ALL_TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("orchestrator.complete_failed")
                yield ErrorEvent(message=f"LLM call failed: {exc}")
                return

            if not assistant.tool_calls:
                # Model produced its final answer; stream it for nicer UX.
                async for ev in self._stream_final_answer(history, assistant.content):
                    yield ev
                yield DoneEvent()
                return

            # Record the assistant's tool-calling turn in the history so the
            # next round has the proper context.
            history.append(
                Message(
                    role=Role.ASSISTANT,
                    content=assistant.content or "",
                    tool_calls=assistant.tool_calls,
                )
            )

            # Run every tool the model asked for, in order, in fresh sessions.
            for call in assistant.tool_calls:
                yield ToolCallEvent(
                    call_id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                )
                result = await self._invoke_tool(call)
                yield ToolResultEvent(
                    call_id=call.id,
                    name=result.name,
                    ok=result.ok,
                    summary=result.content if len(result.content) < 400 else result.content[:400] + " …",
                    data=result.data,
                )
                history.append(
                    Message(
                        role=Role.TOOL,
                        content=result.content,
                        tool_call_id=call.id,
                    )
                )
            # Loop again — model will see tool results and decide whether
            # to call more tools or write a final answer.

        # Safety cap exhausted.
        yield ErrorEvent(
            message=(
                f"Stopped after {self.MAX_TOOL_TURNS} tool-call rounds without "
                f"producing a final answer."
            )
        )
        yield DoneEvent()

    async def _invoke_tool(self, call: ToolCall) -> ToolResult:
        async with get_session() as session:
            return await execute_tool_call(session, call)

    async def _stream_final_answer(
        self,
        history: list[Message],
        already_emitted_content: str,
    ) -> AsyncIterator[OrchestratorEvent]:
        """Re-ask the model with stream=True to get token-level UX.

        If `complete()` already produced text, emit it first (the model
        sometimes interleaves text and tool calls), then stream a
        continuation.
        """
        if already_emitted_content:
            # Most of the time the final answer is the text from the no-tool
            # turn — just emit it as one token chunk to keep flow simple.
            yield TokenEvent(text=already_emitted_content)
            return

        # If for some reason complete() returned no text and no tool calls,
        # do a streaming pass as a fallback.
        try:
            async for chunk in self._llm.stream(history, temperature=0.2):
                yield TokenEvent(text=chunk)
        except Exception as exc:  # noqa: BLE001
            log.exception("orchestrator.stream_failed")
            yield ErrorEvent(message=f"Final-answer stream failed: {exc}")

    # ── Helpers exposed for callers that want the raw history ──────

    @staticmethod
    def serialize_event(ev: OrchestratorEvent) -> str:
        if isinstance(ev, TokenEvent):
            return json.dumps({"type": "token", "text": ev.text}, ensure_ascii=False)
        if isinstance(ev, ToolCallEvent):
            return json.dumps(
                {
                    "type": "tool_call",
                    "call_id": ev.call_id,
                    "name": ev.name,
                    "arguments": ev.arguments,
                },
                ensure_ascii=False,
                default=str,
            )
        if isinstance(ev, ToolResultEvent):
            return json.dumps(
                {
                    "type": "tool_result",
                    "call_id": ev.call_id,
                    "name": ev.name,
                    "ok": ev.ok,
                    "summary": ev.summary,
                    "data": ev.data,
                },
                ensure_ascii=False,
                default=str,
            )
        if isinstance(ev, ErrorEvent):
            return json.dumps({"type": "error", "message": ev.message}, ensure_ascii=False)
        if isinstance(ev, DoneEvent):
            return json.dumps({"type": "done"})
        raise ValueError(f"unknown event {ev!r}")
