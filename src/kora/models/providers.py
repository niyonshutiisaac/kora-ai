"""Concrete OpenAI-compatible providers."""

from __future__ import annotations

from kora.models.openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    """Local Ollama server via its OpenAI-compatible endpoint."""

    name = "ollama"

    def describe(self) -> str:
        return f"ollama:{self.model} (local)"


class GroqProvider(OpenAICompatProvider):
    name = "groq"


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        # Optional attribution headers recommended by OpenRouter.
        headers.setdefault("HTTP-Referer", "https://github.com/kora-ai/kora")
        headers.setdefault("X-Title", "Kora CLI")
        return headers
