"""ReAct agent loop: model <-> tools until final answer."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kora import i18n
from kora.agent.planner import Planner
from kora.agent.prompts import build_system_prompt
from kora.config import Settings
from kora.models.base import (
    BaseProvider,
    DeltaCallback,
    LLMResponse,
    ToolCallRequest,
    assistant_with_calls,
    make_openai_tool_message,
)
from kora.safety import SafetyLevel
from kora.tools import ToolRegistry, ToolResult

logger = logging.getLogger("kora.agent")

ConfirmFn = Callable[[SafetyLevel, str], Awaitable[bool]]
EventFn = Callable[[str, dict[str, Any]], None]  # sync event sink for UI


@dataclass
class AgentRunResult:
    final_text: str = ""
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    iterations: int = 0
    language: str = "en"
    cancelled: bool = False


class KoraAgent:
    """One interactive session: history + provider + tool registry."""

    def __init__(
        self,
        settings: Settings,
        provider: BaseProvider,
        registry: ToolRegistry,
        confirm: ConfirmFn,
        on_event: EventFn | None = None,
        ask_user: Callable[[str, list[str]], Awaitable[str]] | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.registry = registry
        self.confirm_fn = confirm
        self.on_event = on_event or (lambda kind, data: None)
        self.planner = Planner()
        self.history: list[dict[str, Any]] = []
        self.cancel_requested = False
        self.language = "en"

    # ----------------------------------------------------------------- events

    def _emit(self, kind: str, **data: Any) -> None:
        try:
            self.on_event(kind, data)
        except Exception:  # noqa: BLE001 - UI must never break the loop
            logger.exception("event sink failed")

    # -------------------------------------------------------------- utilities

    def reset_history(self) -> None:
        self.history.clear()
        self.planner.replace_all([])

    def _system_prompt(self) -> str:
        branch = ""
        try:
            from git import Repo

            repo = Repo(str(self.settings.root))
            if not repo.head.is_detached:
                branch = repo.active_branch.name
        except Exception:  # noqa: BLE001 - git optional
            branch = ""
        return build_system_prompt(
            root=Path(self.settings.root),
            registry=self.registry,
            language=self.language,
            todos=self.planner.todos,
            self_modification=self.settings.self_modification,
            git_branch=branch,
        )

    def _trim_history(self, max_chars: int = 400_000) -> None:
        total = sum(len(str(m.get("content") or "")) for m in self.history)
        while total > max_chars and len(self.history) > 4:
            removed = self.history.pop(0)
            total -= len(str(removed.get("content") or ""))

    async def _confirm(self, level: SafetyLevel, description: str) -> bool:
        """Confirmation entry point used by every tool."""
        if self.cancel_requested:
            return False
        decision = await self.confirm_fn(level, description)
        self._emit("confirm", level=level.value, description=description[:200], approved=decision)
        return decision

    # -------------------------------------------------------------------- run

    async def process(self, user_input: str) -> AgentRunResult:
        """Process one user instruction through the full ReAct loop."""
        self.cancel_requested = False
        self.language = i18n.resolve_language(self.settings.language, user_input)

        ctx = self._make_context()

        system = self._system_prompt()
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_input})

        result = AgentRunResult(language=self.language)
        max_iterations = max(self.settings.max_iterations, 5)

        for iteration in range(max_iterations):
            if self.cancel_requested:
                result.cancelled = True
                result.final_text = i18n.tr("cancel", self.language)
                break

            response: LLMResponse = await self.provider.chat(
                messages,
                tools=self.registry.openai_schemas(
                    include_self_update=self.settings.self_modification
                ),
                on_delta=self._make_delta_sink(iteration),
            )
            result.iterations = iteration + 1

            if response.usage:
                self._emit(
                    "usage",
                    prompt=response.usage.prompt_tokens,
                    completion=response.usage.completion_tokens,
                )

            if response.has_tool_calls:
                messages.append(assistant_with_calls(response.content, response.tool_calls))
                for call in response.tool_calls:
                    if self.cancel_requested:
                        break
                    tool_result = await self._execute(ctx, call)
                    messages.append(make_openai_tool_message(call.id, tool_result.for_model()))
                continue

            result.final_text = response.content or ""
            break
        else:
            result.final_text = result.final_text or "(stopped: max iterations reached)"

        if not result.cancelled and result.final_text:
            summary = self._session_summary()
            result.files_changed = sorted(ctx.session_files_changed)
            result.commands_run = list(ctx.session_commands)
            self.history.append({"role": "user", "content": user_input})
            self.history.append(
                {
                    "role": "assistant",
                    "content": (result.final_text + ("\n\n" + summary if summary else "")),
                }
            )
            self._trim_history()
        elif result.cancelled:
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": result.final_text})

        self._emit(
            "done",
            files=list(result.files_changed),
            commands=list(result.commands_run),
            cancelled=result.cancelled,
        )
        return result

    def _make_delta_sink(self, iteration: int) -> DeltaCallback | None:
        first = {"done": False}

        async def sink(piece: str) -> None:
            if not first["done"]:
                first["done"] = True
                self._emit("assistant_start", iteration=iteration)
            self._emit("assistant_delta", text=piece)

        return sink if self.on_event else None

    # ------------------------------------------------------------ tool exec

    def _make_context(self):
        from kora.tools.base import ToolContext

        return ToolContext(
            root=self.settings.root,
            confirm=self._confirm,
            language=self.language,
            safety_level=self.settings.safety_level,
            allow_outside_root=self.settings.allow_outside_root,
            self_modification=self.settings.self_modification,
            confirm_edits=self.settings.confirm_edits,
            todos=self.planner.todos,
        )

    async def _execute(self, ctx, call: ToolCallRequest) -> ToolResult:
        tool = self.registry.get(call.name)
        self._emit("tool_start", name=call.name, args=_safe_json(call.arguments))
        if tool is None:
            known = ", ".join(self.registry.names())
            return ToolResult(ok=False, error=f"Unknown tool '{call.name}'. Available: {known}")

        missing = tool.validate(call.arguments)
        if missing:
            return ToolResult(ok=False, error=f"Missing required arguments: {missing}")

        try:
            if (
                tool.max_safety is SafetyLevel.DESTRUCTIVE
                and not ctx.self_modification
                and call.name == "self_update"
            ):
                return ToolResult(
                    ok=False, error="self_update requires self-modification mode (/self)."
                )
            result = await tool.run(ctx, **call.arguments)
        except PermissionError as exc:
            result = ToolResult(ok=False, error=str(exc))
        except TypeError as exc:
            result = ToolResult(ok=False, error=f"Bad arguments for {call.name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - report to model instead of crashing
            logger.exception("tool %s crashed", call.name)
            result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        preview = (result.error if not result.ok else result.output)[:300]
        self._emit("tool_end", name=call.name, ok=result.ok, preview=preview)
        return result

    # ---------------------------------------------------------------- summary

    def _session_summary(self) -> str:
        lines: list[str] = []
        lang = self.language
        if self.planner.todos:
            done, total = self.planner.progress
            label = f"{done}/{total}"
            title = "Plan" if lang == "en" else "Gahunda"
            lines.append(f"{title}: {label}")
        return "\n".join(lines)


def _safe_json(args: dict[str, Any], limit: int = 600) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(args)
    return text if len(text) <= limit else text[:limit] + "..."
