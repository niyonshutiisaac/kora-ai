"""OpenAI-compatible chat-completions client (Ollama, Groq, OpenRouter).

Handles:
  * native tool calling via the standard `tools` parameter
  * SSE streaming with incremental text deltas
  * automatic fallback to text-based tool-call extraction for models that
    emit <tool_call>{...}</tool_call> blocks instead of native calls
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from kora.models.base import (
    BaseProvider,
    DeltaCallback,
    LLMResponse,
    ProviderError,
    ToolCallRequest,
    Usage,
)
from kora.models.toolcall_parser import extract_text_tool_calls

MAX_TOOL_ARGUMENTS_CHARS = 262_144


class OpenAICompatProvider(BaseProvider):
    """Adapter for any /v1/chat/completions compatible endpoint."""

    name = "openai_compat"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 300.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url)
        self._client: httpx.AsyncClient | None = None
        self._extra_headers = extra_headers or {}
        self._timeout = timeout

    # ------------------------------------------------------------------ http

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = self._headers()
            headers.update(self._extra_headers)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self._timeout, connect=30.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ----------------------------------------------------------------- chat

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": on_delta is not None,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            if on_delta is not None:
                return await self._chat_stream(payload, on_delta)
            return await self._chat_plain(payload)
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise ProviderError(f"{self.describe()} request failed: {exc}") from exc

    async def _request_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._http().post("/chat/completions", json=payload)
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.describe()} HTTP {response.status_code}: {_short_error(response.text)}"
            )
        return response.json()

    async def _chat_plain(self, payload: dict[str, Any]) -> LLMResponse:
        data = await self._request_json({**payload, "stream": False})
        choice = _first_choice(data)
        message = choice.get("message", {}) or {}

        content = message.get("content") or ""
        raw_calls = message.get("tool_calls") or []

        tool_calls: list[ToolCallRequest] = []
        from kora.models.base import parse_arguments

        for entry in raw_calls:
            fn = entry.get("function", {}) or {}
            name = fn.get("name")
            if name:
                tool_calls.append(
                    ToolCallRequest(
                        id=entry.get("id") or ToolCallRequest(name="x").id,
                        name=name,
                        arguments=parse_arguments(fn.get("arguments")),
                    )
                )

        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0) or 0,
            completion_tokens=usage_data.get("completion_tokens", 0) or 0,
            total_tokens=usage_data.get("total_tokens", 0)
            or (usage_data.get("prompt_tokens", 0) + usage_data.get("completion_tokens", 0)),
        )
        finish = choice.get("finish_reason") or ("tool_calls" if tool_calls else "stop")

        # Text-fallback parsing when the model emitted tagged calls in content.
        if not tool_calls and content and ("<tool_call>" in content or "```" in content):
            cleaned, parsed = extract_text_tool_calls(content)
            if parsed:
                content = cleaned.strip() or None
                tool_calls = [ToolCallRequest(name=n, arguments=a) for n, a in parsed]
                finish = "tool_calls"

        return LLMResponse(
            content=content or None,
            tool_calls=tool_calls,
            finish_reason=finish,
            usage=usage,
            model=data.get("model", self.model),
            raw_provider=self.name,
        )

    async def _chat_stream(self, payload: dict[str, Any], on_delta: DeltaCallback) -> LLMResponse:
        content_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}
        usage_data: dict[str, Any] = {}
        model_name = self.model

        try:
            async with self._http().stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise ProviderError(
                        f"{self.describe()} HTTP {response.status_code}: {_short_error(body.decode('utf-8', 'replace'))}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk_raw = line[5:].strip()
                    if chunk_raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(chunk_raw)
                    except json.JSONDecodeError:
                        continue
                    model_name = chunk.get("model", model_name)
                    if isinstance(chunk.get("usage"), dict):
                        usage_data = chunk["usage"]
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {}) or {}
                        piece = delta.get("content")
                        if piece:
                            content_parts.append(piece)
                            await on_delta(piece)
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function", {}) or {}
                            slot["name"] = fn.get("name") or slot["name"]
                            args_piece = fn.get("arguments")
                            if args_piece and len(slot["arguments"]) < MAX_TOOL_ARGUMENTS_CHARS:
                                slot["arguments"] += args_piece
                            slot.setdefault("done_ids", set())
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise ProviderError(f"{self.describe()} stream failed: {exc}") from exc

        from kora.models.base import parse_arguments

        tool_calls = [
            ToolCallRequest(
                id=slot["id"] or ToolCallRequest(name="x").id,
                name=slot["name"],
                arguments=parse_arguments(slot["arguments"]),
            )
            for _, slot in sorted(tool_acc.items())
        ]

        full_content = "".join(content_parts)
        if not tool_calls and full_content and "<tool_call>" in full_content:
            cleaned, parsed = extract_text_tool_calls(full_content)
            if parsed:
                full_content = cleaned
                tool_calls = [ToolCallRequest(name=n, arguments=a) for n, a in parsed]

        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0) or 0,
            completion_tokens=usage_data.get("completion_tokens", 0) or 0,
            total_tokens=usage_data.get("total_tokens", 0),
        )
        return LLMResponse(
            content=full_content or None,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
            model=model_name,
            raw_provider=self.name,
        )


def _first_choice(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") or []
    return choices[0] if choices else {}


def _short_error(text: str, limit: int = 400) -> str:
    try:
        data = json.loads(text)
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message", text))[:limit]
    except json.JSONDecodeError:
        pass
    return text[:limit]
