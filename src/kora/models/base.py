"""Model provider abstraction.

Every provider implements:

    async chat(messages, tools, on_delta=None) -> LLMResponse

`messages` are OpenAI-style dicts: {"role": ..., "content": ...} plus tool
messages {"role": "tool", "tool_call_id": ..., "content": ...} and assistant
messages that may carry "tool_calls".

`tools` are OpenAI-style schemas: [{"type": "function", "function": {...}}].
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    """A tool invocation requested by the model."""

    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified response from any provider."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Usage | None = None
    model: str = ""
    raw_provider: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


DeltaCallback = Callable[[str], Awaitable[None]]


class ProviderError(RuntimeError):
    """Raised when a provider call fails after retries."""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Parse tool-call arguments which may be a dict or a JSON string."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def make_openai_tool_message(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def assistant_with_calls(content: str | None, calls: list[ToolCallRequest]) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in calls
        ],
    }
    return msg


class BaseProvider(ABC):
    """Common interface implemented by all model adapters."""

    name: str = "base"

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return a unified response."""

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP resources."""

    # ------------------------------------------------------------------ utils

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def describe(self) -> str:
        return f"{self.name}:{self.model}"
