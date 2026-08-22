"""Tool base classes and execution context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from kora.safety import SafetyLevel


class ToolResult(BaseModel):
    """Structured result of a tool invocation."""

    ok: bool = True
    output: str = ""
    error: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def for_model(self, limit: int = 12_000) -> str:
        """Render result as text to feed back to the model."""
        header = "OK" if self.ok else "ERROR"
        body = self.error if not self.ok and self.error else self.output
        if len(body) > limit:
            body = (
                body[: limit // 2]
                + f"\n... [truncated {len(body) - limit} chars] ...\n"
                + body[-limit // 2 :]
            )
        suffix = ""
        if self.files_changed:
            suffix += "\nFiles changed: " + ", ".join(self.files_changed)
        return f"[{header}] {body}{suffix}"


ConfirmFn = Callable[[SafetyLevel, str], Awaitable[bool]]


@dataclass
class ToolContext:
    """Everything a tool needs at run time."""

    root: Any  # Path - project root; typed Any to avoid circular imports
    confirm: ConfirmFn
    language: str = "en"
    safety_level: str = "normal"
    allow_outside_root: bool = False
    self_modification: bool = False
    confirm_edits: bool = True
    todos: list[dict[str, Any]] = field(default_factory=list)
    session_files_changed: set[str] = field(default_factory=set)
    session_commands: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ paths

    def resolve_path(self, raw: str | None) -> Any:
        """Resolve user/model path against project root, guarding escapes.

        Returns a pathlib.Path guaranteed (unless allow_outside_root) to stay
        inside the project root.
        """
        from pathlib import Path

        from kora.utils import sanitize_rel_path

        root: Path = type(Path())(str(self.root))
        if not raw or raw in (".", "./"):
            return root

        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if not self.allow_outside_root:
                try:
                    resolved.relative_to(root)
                except ValueError as exc:
                    raise PermissionError(
                        f"Path '{raw}' is outside the project root ({root}). "
                        "Enable allow_outside_root to permit this."
                    ) from exc
            return resolved

        rel = sanitize_rel_path(raw)
        resolved = (root / rel).resolve()
        if not self.allow_outside_root:
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise PermissionError(f"Path '{raw}' escapes the project root.") from exc
        return resolved

    async def require_confirmation(self, level: SafetyLevel, description: str) -> bool:
        return await self.confirm(level, description)


FieldSpec = dict[str, Any]


class Tool(ABC):
    """Base class for every Kora tool."""

    name: str = "tool"
    description: str = ""
    params: dict[str, FieldSpec] = {}
    required: list[str] = []
    max_safety: SafetyLevel = SafetyLevel.SAFE  # worst-case level for this tool

    # ---------------------------------------------------------------- schema

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": self.required,
                },
            },
        }

    # ------------------------------------------------------------------- run

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult: ...

    def validate(self, kwargs: dict[str, Any]) -> list[str]:
        return [name for name in self.required if name not in kwargs]
