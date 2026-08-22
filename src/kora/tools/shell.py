"""Shell command execution tool with safety classification."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from kora import constants
from kora.safety import SafetyLevel, classify_command
from kora.tools.base import Tool, ToolContext, ToolResult

MAX_OUTPUT_LINES = constants.MAX_TOOL_OUTPUT_LINES

# Commands that are always refused outright.
_BLOCKED_PATTERNS = ("shutdown", "rm -rf /", "mkfs", "dd if=", ":(){", "> /dev/sda")


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Run a shell command inside the project directory. Safety levels: "
        "'safe' (read-only) runs automatically; 'moderate' (builds/installs/"
        "git writes) needs one confirmation; 'destructive' needs typed "
        "'yes'. Set requires_confirmation=false only to skip the extra "
        "prompt for safe commands."
    )
    params = {
        "command": {"type": "string", "description": "The shell command to run"},
        "cwd": {"type": "string", "description": "Working directory relative to project root"},
        "timeout": {
            "type": "integer",
            "description": f"Timeout seconds (default {constants.DEFAULT_TIMEOUT})",
        },
        "requires_confirmation": {
            "type": "boolean",
            "description": "Explicitly request confirmation",
        },
    }
    required = ["command"]
    max_safety = SafetyLevel.DESTRUCTIVE

    async def run(
        self,
        ctx: ToolContext,
        command: str = "",
        cwd: str | None = None,
        timeout: int | None = None,
        requires_confirmation: bool | None = None,
        **_: object,
    ) -> ToolResult:
        command = command.strip()
        if not command:
            return ToolResult(ok=False, error="Empty command")

        lowered = command.lower()
        if any(blocked in lowered for blocked in _BLOCKED_PATTERNS):
            return ToolResult(
                ok=False, error=f"Command is hard-blocked by Kora safety policy: {command}"
            )

        workdir: Path = ctx.root if not cwd else ctx.resolve_path(cwd)
        if not workdir.is_dir():
            return ToolResult(ok=False, error=f"cwd does not exist: {workdir}")

        classification = classify_command(command)
        level = classification.level

        # Confirmation policy.
        need_confirm = level is SafetyLevel.MODERATE or level is SafetyLevel.DESTRUCTIVE
        if ctx.safety_level == "cautious" and level is SafetyLevel.SAFE:
            need_confirm = True
        if requires_confirmation:
            need_confirm = True

        if need_confirm:
            approved = await ctx.confirm(level, command)
            if not approved:
                return ToolResult(ok=False, error=f"User declined command: {command}")

        timeout_s = min(int(timeout) if timeout else constants.DEFAULT_TIMEOUT, 1800)
        ctx.session_commands.append(command)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return ToolResult(ok=False, error=f"Failed to start command: {exc}")

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            return ToolResult(
                ok=False,
                output=f"(timed out after {timeout_s}s)",
                error=f"Command timed out after {timeout_s}s and was killed",
                meta={"exit_code": -1},
            )

        text = stdout.decode("utf-8", errors="replace") if stdout else ""
        lines = text.splitlines()
        if len(lines) > MAX_OUTPUT_LINES:
            shown = lines[-MAX_OUTPUT_LINES:]
            body = "\n".join(shown)
            header = f"[showing last {MAX_OUTPUT_LINES} of {len(lines)} lines]"
        else:
            body = "\n".join(lines)
            header = ""

        exit_code = proc.returncode or 0
        meta = {"exit_code": exit_code, "safety": classification.level.value}
        ok = exit_code == 0
        out = f"$ {command}\n{header}\n{body}".rstrip() or "(no output)"
        return ToolResult(
            ok=ok,
            output=out,
            error=None if ok else f"exit code {exit_code}",
            meta=meta,
        )


def quote_args(*parts: str) -> str:
    """Shell-quote helper exposed for tests and tools."""

    return " ".join(shlex.quote(p) for p in parts)
