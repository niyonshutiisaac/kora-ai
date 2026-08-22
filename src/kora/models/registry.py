"""Model registry: loads config/models.yaml, builds provider adapters."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from kora.config import Settings
from kora.models.base import BaseProvider
from kora.models.gemini import GeminiProvider
from kora.models.openai_compat import OpenAICompatProvider
from kora.models.providers import GroqProvider, OllamaProvider, OpenRouterProvider


@dataclass
class ModelInfo:
    id: str
    name: str
    context: int = 0
    notes: str = ""


@dataclass
class ProviderInfo:
    key: str
    kind: str
    description: str = ""
    local: bool = False
    free: bool = True
    models: list[ModelInfo] = field(default_factory=list)
    base_url: str | None = None
    base_url_env: str | None = None
    default_base_url: str | None = None
    api_key_env: str | None = None
    dynamic_models: bool = False


DEFAULT_MODELS_YAML = Path(__file__).resolve().parents[3] / "config" / "models.yaml"

# Substrings that mark NVIDIA NIM entries as non-chat (embeddings, rerankers,
# reward/safety classifiers, OCR/vision utilities, TTS...).
_NON_CHAT_SUBSTRINGS = (
    "embed",
    "rerank",
    "retriever",
    "reward",
    "guard",
    "safety",
    "parse",
    "deplot",
    "kosmos",
    "neva-",
    "nvclip",
    "-clip",
    "riva",
    "detector",
    "topic-control",
    "bge-",
)

_REMOTE_MODELS_TTL_SECONDS = 600
_remote_models_cache: dict[str, tuple[float, list[str]]] = {}


def _is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(bad in lowered for bad in _NON_CHAT_SUBSTRINGS)


def _fetch_remote_model_ids(base_url: str, timeout: float = 8.0) -> list[str]:
    """Fetch chat-capable model ids from an OpenAI-compatible /models endpoint."""
    cached = _remote_models_cache.get(base_url)
    if cached and time.monotonic() - cached[0] < _REMOTE_MODELS_TTL_SECONDS:
        return cached[1]
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        ids = [
            str(item["id"])
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id") and _is_chat_model(str(item["id"]))
        ]
    except (httpx.HTTPError, ValueError):
        return []
    _remote_models_cache[base_url] = (time.monotonic(), ids)
    return ids


class ModelRegistry:
    """Loads the free-model catalog and instantiates providers on demand."""

    def __init__(self, settings: Settings, models_file: Path | None = None) -> None:
        self.settings = settings
        self.providers: dict[str, ProviderInfo] = {}
        self._load(models_file or DEFAULT_MODELS_YAML)

    def _load(self, path: Path) -> None:
        candidates = [path, Path.home() / ".config" / "kora" / "models.yaml"]
        data: dict = {}
        for candidate in candidates:
            if candidate.is_file():
                try:
                    loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                    if isinstance(loaded.get("providers"), dict):
                        raw = loaded["providers"]
                        for key, info in raw.items():
                            data[key] = info  # user file wins by load order
                        break
                except yaml.YAMLError:
                    continue

        for key, info in data.items():
            models = [
                ModelInfo(
                    id=m.get("id", ""),
                    name=m.get("name", m.get("id", "")),
                    context=int(m.get("context", 0) or 0),
                    notes=m.get("notes", ""),
                )
                for m in info.get("models", [])
                if m.get("id")
            ]
            self.providers[key] = ProviderInfo(
                key=key,
                kind=info.get("kind", "openai_compat"),
                description=info.get("description", ""),
                local=bool(info.get("local", False)),
                free=bool(info.get("free", True)),
                models=models,
                base_url=info.get("base_url"),
                base_url_env=info.get("base_url_env"),
                default_base_url=info.get("default_base_url"),
                api_key_env=info.get("api_key_env"),
                dynamic_models=bool(info.get("dynamic_models", False)),
            )

        self._merge_dynamic_models()

    def _merge_dynamic_models(self) -> None:
        """Append live catalog entries for providers flagged dynamic_models.

        Skipped when no API key is configured (keeps tests/offline use
        network-free) or when the /models endpoint is unreachable.
        """
        for info in self.providers.values():
            if not info.dynamic_models:
                continue
            if self.settings.api_key_for(info.key) is None:
                continue
            try:
                base_url = self._resolve_base_url(info)
            except ValueError:
                continue
            known = {m.id for m in info.models}
            for model_id in _fetch_remote_model_ids(base_url):
                if model_id in known:
                    continue
                tail = model_id.split("/")[-1]
                info.models.append(
                    ModelInfo(id=model_id, name=tail.replace("-", " ").replace("_", " "))
                )

    # ------------------------------------------------------------------ query

    def list_providers(self) -> list[ProviderInfo]:
        return list(self.providers.values())

    def get_provider_info(self, key: str) -> ProviderInfo:
        try:
            return self.providers[key]
        except KeyError as exc:
            raise KeyError(
                f"Unknown provider '{key}'. Available: {', '.join(self.providers)}"
            ) from exc

    # ----------------------------------------------------------------- build

    def build_provider(self, provider_key: str, model_id: str) -> BaseProvider:
        info = self.get_provider_info(provider_key)

        base_url = self._resolve_base_url(info)
        api_key = self.settings.api_key_for(provider_key)

        env_name = (info.api_key_env or "").upper()
        if env_name and not api_key:
            raise ValueError(
                f"No API key for provider '{provider_key}'. "
                f"Set {env_name} in your .env file or environment."
            )

        kind_map = {
            "ollama": OllamaProvider,
            "groq": GroqProvider,
            "openrouter": OpenRouterProvider,
        }

        if info.kind == "gemini":
            return GeminiProvider(model=model_id, api_key=api_key, base_url=base_url)

        cls = kind_map.get(info.key, OpenAICompatProvider)
        instance = cls(model=model_id, base_url=base_url, api_key=api_key)
        instance.name = info.key
        return instance

    def _resolve_base_url(self, info: ProviderInfo) -> str:
        if info.base_url:
            return info.base_url
        if info.key == "ollama":
            base = self.settings.ollama_base_url.rstrip("/")
            return base if base.endswith("/v1") else base + "/v1"
        if info.base_url_env:
            import os

            from_env = os.environ.get(info.base_url_env)
            if from_env:
                return from_env.rstrip("/") + (
                    "/v1" if not from_env.rstrip("/").endswith("/v1") else ""
                )
        if info.default_base_url:
            return info.default_base_url
        raise ValueError(f"Provider '{info.key}' has no base_url configured")

    def find_model(self, model_id: str) -> tuple[str, ModelInfo] | None:
        for provider in self.providers.values():
            for model in provider.models:
                if model.id == model_id:
                    return provider.key, model
        return None
