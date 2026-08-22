"""Configuration loading for Kora.

Precedence (highest wins):
  1. Environment variables / .env file
  2. User config:  ~/.config/kora/config.yaml
  3. Project config: ./config.yaml (or KORA_CONFIG_FILE)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kora import constants

SafetyLevelName = Literal["normal", "cautious", "yolo"]
LanguageSetting = Literal["auto", "en", "rw"]


class Settings(BaseSettings):
    """Runtime settings resolved from YAML config + environment."""

    model_config = SettingsConfigDict(
        env_prefix="KORA_",
        extra="ignore",
    )

    default_provider: str = "ollama"
    default_model: str = "qwen2.5-coder:7b"
    language: LanguageSetting = "auto"
    safety_level: SafetyLevelName = "normal"
    project_root: Path | None = None
    allow_outside_root: bool = False
    self_modification: bool = False
    confirm_edits: bool = True
    command_timeout: int = Field(default=120, ge=5, le=3600)
    max_iterations: int = Field(default=40, ge=1, le=200)

    # API keys come from the environment (.env supported).
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    nvidia_api_key: str | None = Field(default=None, alias="NVIDIA_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL")

    @model_validator(mode="before")
    @classmethod
    def _empty_strings_are_none(cls, data: dict) -> dict:
        if isinstance(data, dict):
            return {k: (None if v == "" and k.endswith("_api_key") else v) for k, v in data.items()}
        return data

    # ------------------------------------------------------------- factories

    @property
    def root(self) -> Path:
        """Effective project root (cwd unless configured)."""
        return (self.project_root or Path.cwd()).resolve()

    def api_key_for(self, provider: str) -> str | None:
        key_map = {
            "groq": self.groq_api_key,
            "openrouter": self.openrouter_api_key,
            "gemini": self.gemini_api_key,
            "nvidia": self.nvidia_api_key,
        }
        value = key_map.get(provider.lower())
        if not value:
            env_name = f"{provider.upper().replace('-', '_')}_API_KEY"
            value = os.environ.get(env_name)
        return value or None


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(config_file: Path | None = None) -> Settings:
    """Load settings from bundled/project/user YAML then environment."""
    load_dotenv()

    data: dict = {}
    candidates = [
        config_file or Path(os.environ.get("KORA_CONFIG_FILE", Path.cwd() / "config.yaml")),
        constants.CONFIG_FILE,
    ]
    for path in candidates:
        if path and path.is_file():
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    data = _deep_merge(data, loaded)
            except yaml.YAMLError:
                continue

    # Environment overrides YAML.
    env_map = {
        "default_provider": "KORA_DEFAULT_PROVIDER",
        "default_model": "KORA_DEFAULT_MODEL",
        "language": "KORA_LANGUAGE",
        "safety_level": "KORA_SAFETY_LEVEL",
        "self_modification": "KORA_SELF_MODIFICATION",
    }
    for field, env in env_map.items():
        if os.environ.get(env) is not None:
            raw = os.environ[env]
            if raw.lower() in {"true", "false"}:
                data[field] = raw.lower() == "true"
            else:
                data[field] = raw

    known = set(Settings.model_fields)
    filtered = {k: v for k, v in data.items() if k in known}
    return Settings(**filtered)


def save_setting(key: str, value) -> None:
    """Persist a single setting into the user-level config.yaml."""
    constants.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    if constants.CONFIG_FILE.is_file():
        try:
            current = yaml.safe_load(constants.CONFIG_FILE.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            current = {}
    current[key] = value
    constants.CONFIG_FILE.write_text(yaml.safe_dump(current, sort_keys=False), encoding="utf-8")
