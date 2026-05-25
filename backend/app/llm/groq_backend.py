"""Groq LLM backend — dev only.

Groq is an external API. It MUST NOT be used in air-gap production builds.
The factory enforces this; this module is included in the image only when
the build is not flagged air-gap.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from app.core.logging import get_logger
from app.llm.base import (
    AssistantTurn,
    LLMBackend,
    Message,
    Role,
    ToolCall,
    ToolDefinition,
)

log = get_logger(__name__)


def _message_to_chat_dict(m: Message) -> dict[str, Any]:
    """Convert our generic Message into the chat-completions wire format used by Groq."""
    if m.role == Role.TOOL:
        return {
            "role": "tool",
            "tool_call_id": m.tool_call_id,
            "content": m.content,
        }
    if m.role == Role.ASSISTANT and m.tool_calls:
        return {
            "role": "assistant",
            "content": m.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in m.tool_calls
            ],
        }
    return {"role": m.role.value, "content": m.content}


class GroqBackend(LLMBackend):
    name = "groq"
    # Groq's chat-completions endpoint URL is literally this path — it is
    # served by Groq's infrastructure, not by any third-party LLM provider.
    base_url = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required for the Groq backend")
        self._api_key = api_key
        self._model = model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [_message_to_chat_dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[len("data: ") :]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        log.warning("groq.stream.bad_chunk", chunk=data)
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
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
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_message_to_chat_dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [t.to_function_schema() for t in tools]
            payload["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        choice = body["choices"][0]["message"]
        content = choice.get("content") or ""
        raw_tool_calls = choice.get("tool_calls") or []

        tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                log.warning("groq.tool_call.bad_args", call=tc)
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=arguments)
            )

        return AssistantTurn(content=content, tool_calls=tool_calls)

    async def healthcheck(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return r.status_code == 200
        except httpx.HTTPError as exc:
            log.warning("groq.healthcheck.failed", error=str(exc))
            return False
