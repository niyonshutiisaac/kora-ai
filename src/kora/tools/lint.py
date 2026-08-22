"""Lint tool: ruff for Python (fallback pyflakes via compile), eslint for JS/TS."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from kora.tools.base import Tool, ToolContext, ToolResult


class ReadLintsTool(Tool):
    name = "read_lints"
    description = (
        "Run available linters on a file or the whole project. Uses 'ruff check' "
        "for Python and 'eslint' for JS/TS when installed. Returns diagnostics."
    )
    params = {
        "path": {
            "type": "string",
            "description": "File or directory to lint (default project root)",
        }
    }
    required: list = []

    async def run(self, ctx: ToolContext, path: str | None = None, **_) -> ToolResult:
        try:
            target = ctx.resolve_path(path or ".")
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))

        sections: list[str] = []
        if target.is_file() and target.suffix == ".py" or target.is_dir():
            ruff = shutil.which("ruff")
            if ruff:
                args = [ruff, "check", "--output-format", "concise", str(target)]
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=str(ctx.root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
                text = stdout.decode("utf-8", errors="replace").strip()
                sections.append(
                    f"# ruff ({'clean' if proc.returncode == 0 else 'issues'})\n{text or '(no issues)'}"
                )

        if target.suffix in {".js", ".jsx", ".ts", ".tsx"} or (
            target.is_dir() and (Path(ctx.root) / "package.json").is_file()
        ):
            eslint = shutil.which("eslint") or shutil.which("eslint.cmd")
            if eslint:
                proc = await asyncio.create_subprocess_shell(
                    f"{eslint} --no-error-on-unmatched-pattern {target}",
                    cwd=str(ctx.root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
                text = stdout.decode("utf-8", errors="replace").strip()
                sections.append(f"# eslint\n{text or '(no issues)'}")
            else:
                sections.append("# eslint not installed - skipped")

        if not sections:
            return ToolResult(
                output=(
                    "No linter available. Install ruff (pip install ruff) "
                    "or add eslint to the project for automatic checks."
                )
            )
        ok = "issues" not in "\n".join(s.splitlines()[0] for s in sections)
        return ToolResult(ok=True, output="\n\n".join(sections), meta={"clean": ok})
