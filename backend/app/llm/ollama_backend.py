"""Ollama LLM backend — local, air-gap safe, production default.

This is the backend customers run in their own network. The bundled Wekams
Lens Community image ships a Qwen 2.5 7B model file and runs Ollama as a
sidecar (or assumes a co-located Ollama server).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from typing import Any, Literal

import httpx

from app.core.logging import get_logger
from app.llm.base import AssistantTurn, LLMBackend, Message, ToolDefinition

log = get_logger(__name__)


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, host: str, model: str) -> None:
        self._host = host.rstrip("/")
        self._model = model

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": True,
        }
        # Ollama streams newline-delimited JSON objects, not SSE.
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{self._host}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("ollama.stream.bad_chunk", chunk=line)
                        continue
                    if chunk.get("done"):
                        break
                    text = chunk.get("message", {}).get("content")
                    if text:
                        yield text

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> AssistantTurn:
        """Ollama's native /api/chat now supports tools for capable models
        (Llama 3.1+, Qwen 2.5, etc.). For Phase 1b we wire the same shape
        as Groq; Phase 1c will add prompt-fallback for non-tool-capable
        bundled models like Qwen 2.5 7B."""
        import json as _json

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in messages
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        if tools:
            payload["tools"] = [t.to_function_schema() for t in tools]

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
            response = await client.post(f"{self._host}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()

        msg = body.get("message", {})
        content = msg.get("content") or ""
        raw_tool_calls = msg.get("tool_calls") or []

        from app.llm.base import ToolCall

        tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = _json.loads(args)
                except _json.JSONDecodeError:
                    args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", "") or f"call_{len(tool_calls)}",
                    name=fn.get("name", ""),
                    arguments=args,
                )
            )

        return AssistantTurn(content=content, tool_calls=tool_calls)

    async def healthcheck(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._host}/api/tags")
                return r.status_code == 200
        except httpx.HTTPError as exc:
            log.warning("ollama.healthcheck.failed", error=str(exc))
            return False
