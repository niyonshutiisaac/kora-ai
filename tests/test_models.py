"""Tests for model registry, config loading, and Gemini message conversion."""

from pathlib import Path

import pytest
import yaml

from kora.config import Settings, load_settings, save_setting
from kora.models.gemini import GeminiProvider, _clean_schema
from kora.models.registry import ModelRegistry


@pytest.fixture()
def models_file(tmp_path: Path) -> Path:
    data = {
        "providers": {
            "testprov": {
                "kind": "openai_compat",
                "base_url": "http://localhost:9/v1",
                "api_key_env": None,
                "local": True,
                "free": True,
                "models": [
                    {"id": "tiny-1b", "name": "Tiny", "context": 4096},
                ],
            }
        }
    }
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestRegistry:
    def test_loads_bundled_catalog(self):
        settings = Settings(groq_api_key="k", ollama_base_url="http://localhost:11434/v1")
        registry = ModelRegistry(settings)
        keys = {p.key for p in registry.list_providers()}
        assert {"ollama", "groq", "openrouter", "gemini"} <= keys

    def test_build_ollama_provider(self):
        settings = Settings(ollama_base_url="http://localhost:11434/v1")
        registry = ModelRegistry(settings)
        provider = registry.build_provider("ollama", "qwen2.5-coder:7b")
        assert provider.base_url == "http://localhost:11434/v1"
        assert provider.model == "qwen2.5-coder:7b"

    def test_missing_api_key_raises(self):
        settings = Settings(groq_api_key=None)
        registry = ModelRegistry(settings)
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            registry.build_provider("groq", "llama-3.3-70b-versatile")

    def test_custom_models_file(self, tmp_path):
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            yaml.safe_dump(
                {
                    "providers": {
                        "myprov": {
                            "kind": "openai_compat",
                            "base_url": "http://x/v1",
                            "models": [{"id": "m1"}],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        registry = ModelRegistry(Settings(), models_file=custom)
        provider = registry.build_provider("myprov", "m1")
        assert provider.name in ("openai_compat", "myprov")


class TestConfig:
    def test_load_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no config.yaml here
        settings = load_settings(config_file=tmp_path / "missing.yaml")
        assert settings.safety_level == "normal"
        assert settings.command_timeout == 120

    def test_yaml_overrides(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("safety_level: cautious\nmax_iterations: 5\n", encoding="utf-8")
        settings = load_settings(config_file=cfg)
        assert settings.safety_level == "cautious"
        assert settings.max_iterations == 5

    def test_save_setting_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kora.constants.CONFIG_FILE", tmp_path / "user_config.yaml")
        save_setting("default_model", "test-model")
        again = save_setting("language", "rw")
        assert again is None
        content = (tmp_path / "user_config.yaml").read_text(encoding="utf-8")
        assert "default_model" in content and "test-model" in content


class TestGeminiConversion:
    def test_clean_schema_strips_unknown(self):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {"a": {"type": "string", "default": "x"}},
            "required": ["a"],
        }
        cleaned = _clean_schema(schema)
        assert "additionalProperties" not in cleaned
        assert "$schema" not in cleaned
        assert "default" not in cleaned["properties"]["a"]
        assert cleaned["required"] == ["a"]

    def test_message_conversion(self):
        provider = GeminiProvider(model="gemini-2.0-flash", api_key="k")
        messages = [
            {"role": "system", "content": "You are Kora."},
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {"name": "t", "arguments": '{"x": 1}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "1", "_tool_name": "t", "content": "result"},
        ]
        system_text, contents = provider._convert_messages(messages)
        assert system_text == "You are Kora."
        roles = [c["role"] for c in contents]
        assert roles == ["user", "model", "user"]
        assert "functionCall" in contents[1]["parts"][0]
        assert "functionResponse" in contents[2]["parts"][0]

    def test_tool_conversion(self):
        provider = GeminiProvider(model="gemini-2.0-flash", api_key="k")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ]
        converted = provider._convert_tools(tools)
        decl = converted[0]["functionDeclarations"][0]
        assert decl["name"] == "read_file"
        assert decl["parameters"]["type"] == "object"
