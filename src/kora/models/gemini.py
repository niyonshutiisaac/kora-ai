"""Google Gemini adapter using the REST generateContent API."""

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


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip JSON-schema keys Gemini's API does not accept."""
    allowed = {"type", "description", "enum", "items", "properties", "required", "format"}
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in allowed:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: _clean_schema(sub or {}) for name, sub in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = _clean_schema(value)
        else:
            out[key] = value
    if out.get("type") == "object":
        out.setdefault("properties", {})
        out.setdefault("required", [])
    return out


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta",
        )
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------ conversion

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        role_map = {"assistant": "model"}

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content")

            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue

            if role == "tool":
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": msg.get("_tool_name", "tool"),
                                    "response": {"result": str(content)[:120_000]},
                                }
                            }
                        ],
                    }
                )
                continue

            gemini_role = role_map.get(role, role)
            parts: list[dict[str, Any]] = []
            tool_calls = msg.get("tool_calls") or []
            if content:
                parts.append({"text": str(content)})
            for tc in tool_calls:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                parts.append({"functionCall": {"name": fn.get("name", ""), "args": args}})
            if parts:
                contents.append({"role": gemini_role, "parts": parts})

        system_text = "\n\n".join(system_parts) or None
        return system_text, contents

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        declarations = []
        for tool in tools:
            fn = tool.get("function", tool)
            decl = {
                "name": fn.get("name"),
                "description": fn.get("description", ""),
            }
            params = fn.get("parameters")
            if params:
                cleaned = _clean_schema(params)
                if cleaned:
                    decl["parameters"] = cleaned
            declarations.append(decl)
        return [{"functionDeclarations": declarations}]

    # ------------------------------------------------------------------ chat

    def _endpoint(self, stream: bool) -> str:
        method = "streamGenerateContent?alt=sse&key=" if stream else "generateContent?key="
        return f"/models/{self.model}:{method}{self.api_key or ''}"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        system_text, contents = self._convert_messages(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        gemini_tools = self._convert_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools
        payload["generationConfig"] = {"temperature": 0.2}
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools)
        streaming = on_delta is not None
        url = self._endpoint(streaming)

        try:
            if streaming:
                return await self._chat_stream(payload, on_delta)
            response = await self._http().post(url, json=payload)
            if response.status_code >= 400:
                raise ProviderError(
                    f"{self.describe()} HTTP {response.status_code}: {response.text[:400]}"
                )
            return self._parse_response(response.json())
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise ProviderError(f"{self.describe()} request failed: {exc}") from exc

    async def _chat_stream(self, payload: dict[str, Any], on_delta: DeltaCallback) -> LLMResponse:
        text_parts: list[str] = []
        calls: list[ToolCallRequest] = []
        usage_data: dict[str, Any] = {}

        async with self._http().stream("POST", self._endpoint(True), json=payload) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise ProviderError(
                    f"{self.describe()} HTTP {response.status_code}: {body.decode('utf-8', 'replace')[:400]}"
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk.get("usageMetadata"), dict):
                    usage_data = chunk["usageMetadata"]
                for candidate in chunk.get("candidates", []):
                    for part in (candidate.get("content") or {}).get("parts", []):
                        if "text" in part:
                            text_parts.append(part["text"])
                            await on_delta(part["text"])
                        elif "functionCall" in part:
                            fc = part["functionCall"]
                            calls.append(
                                ToolCallRequest(
                                    name=fc.get("name", ""), arguments=fc.get("args") or {}
                                )
                            )

        usage = Usage(
            prompt_tokens=usage_data.get("promptTokenCount", 0),
            completion_tokens=usage_data.get("candidatesTokenCount", 0),
            total_tokens=usage_data.get("totalTokenCount", 0),
        )
        full = "".join(text_parts)
        return LLMResponse(
            content=full or None,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            usage=usage,
            model=self.model,
            raw_provider=self.name,
        )

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        candidates = data.get("candidates") or [{}]
        candidate = candidates[0]
        text_parts: list[str] = []
        calls: list[ToolCallRequest] = []
        for part in (candidate.get("content") or {}).get("parts", []):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                calls.append(
                    ToolCallRequest(name=fc.get("name", ""), arguments=fc.get("args") or {})
                )

        usage_data = data.get("usageMetadata") or {}
        usage = Usage(
            prompt_tokens=usage_data.get("promptTokenCount", 0),
            completion_tokens=usage_data.get("candidatesTokenCount", 0),
            total_tokens=usage_data.get("totalTokenCount", 0),
        )
        return LLMResponse(
            content="".join(text_parts) or None,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            usage=usage,
            model=data.get("modelVersion", self.model),
            raw_provider=self.name,
        )
