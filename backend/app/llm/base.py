"""Pluggable LLM interface.

Every backend (Ollama, Groq, ...) implements this contract. The
orchestrator never references a concrete backend — it only sees LLMBackend.
Production / air-gapped deployments wire in Ollama; dev wires in Groq for
speed.

Backends without native tool calling (e.g., very small Ollama models) can
fall back to prompt-based JSON extraction in a later iteration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A request from the model to invoke a tool."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Role
    content: str = ""
    # Populated when role == ASSISTANT and the model called tools.
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # Populated when role == TOOL — the id of the assistant tool call this responds to.
    tool_call_id: str | None = None


class ToolParameter(BaseModel):
    name: str
    type: Literal["string", "number", "integer", "boolean", "array", "object"]
    description: str
    required: bool = True
    enum: list[str] | None = None
    # For type == "array", JSON Schema requires an items schema. Default to
    # an array of strings since that covers the common case (list of names,
    # IDs, etc.); callers can override with e.g. {"type": "integer"} or a
    # nested object schema.
    items: dict[str, Any] | None = None


class ToolDefinition(BaseModel):
    """Schema for a tool the model can call. Backend-agnostic shape."""

    name: str
    description: str
    parameters: list[ToolParameter] = Field(default_factory=list)

    def to_function_schema(self) -> dict[str, Any]:
        """Function-tool schema in the chat-completions format used by Groq and Ollama."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum is not None:
                prop["enum"] = p.enum
            if p.type == "array":
                prop["items"] = p.items or {"type": "string"}
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class AssistantTurn(BaseModel):
    """A single non-streaming model response. Either text content,
    tool calls, or both."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMBackend(ABC):
    """Contract every LLM backend must satisfies."""

    name: str = "abstract"

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Yield successive text chunks from the model. Used for the final
        natural-language answer where we want token-level streaming to the UI."""
        raise NotImplementedError
        yield  # pragma: no cover

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        tool_choice: Literal["auto", "required", "none"] = "auto",
    ) -> AssistantTurn:
        """Non-streaming completion. Used for tool-call turns where we need
        the full response before deciding what to do next."""
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Return True if the backend is reachable and configured."""
        raise NotImplementedError
