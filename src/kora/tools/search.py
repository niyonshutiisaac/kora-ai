"""Code search tool with ripgrep fast path."""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from kora.models.base import estimate_tokens
from kora.tools.base import Tool, ToolContext, ToolResult
from kora.utils.ignore import load_ignore_spec

MAX_RESULTS = 300


class SearchCodeTool(Tool):
    name = "search_code"
    description = (
        "Search file contents with a regular expression. Returns matching "
        "lines as 'path:line: text'. Uses ripgrep when available."
    )
    params = {
        "query": {"type": "string", "description": "Regular expression to search for"},
        "path": {"type": "string", "description": "Subdirectory to search (default project root)"},
        "file_glob": {"type": "string", "description": "Optional glob filter like '*.py'"},
        "case_sensitive": {
            "type": "boolean",
            "description": "Case-sensitive search (default false)",
        },
    }
    required = ["query"]

    async def run(
        self,
        ctx: ToolContext,
        query: str = "",
        path: str | None = None,
        file_glob: str | None = None,
        case_sensitive: bool = False,
        **_: Any,
    ) -> ToolResult:
        try:
            base: Path = ctx.resolve_path(path or ".")
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            return ToolResult(ok=False, error=f"Invalid regex: {exc}")

        rg_path = shutil.which("rg")
        if rg_path:
            result = await self._ripgrep_search(rg_path, base, query, file_glob, case_sensitive)
            if result is not None:
                return result

        return await self._python_search(ctx, base, pattern, file_glob)

    # ------------------------------------------------------------- ripgrep

    async def _ripgrep_search(
        self, rg: str, base: Path, query: str, file_glob: str | None, case_sensitive: bool
    ) -> ToolResult | None:
        args = [rg, "--no-heading", "--line-number", "--color", "never", "--max-count", "5"]
        if not case_sensitive:
            args.append("--ignore-case")
        if file_glob:
            args.extend(["--glob", file_glob])
        args.extend([query, str(base)])
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (OSError, TimeoutError):
            return None  # fall back to python search

        lines = stdout.decode("utf-8", errors="replace").splitlines()
        return self._format(lines, engine="ripgrep")

    # -------------------------------------------------------------- python

    async def _python_search(
        self, ctx: ToolContext, base: Path, pattern: re.Pattern[str], file_glob: str | None
    ) -> ToolResult:
        project_root = Path(ctx.root)
        spec = load_ignore_spec(project_root)
        results: list[str] = []

        def iter_files():
            yield from base.rglob("*")

        for candidate in await asyncio.to_thread(lambda: list(iter_files())):
            if len(results) >= MAX_RESULTS:
                break
            if not candidate.is_file() or candidate.suffix in {".pyc"}:
                continue
            from kora.utils.ignore import is_binary_suffix, is_ignored

            try:
                rel_check = candidate.relative_to(project_root)
            except ValueError:
                rel_check = (
                    candidate.relative_to(base) if base != project_root else Path(candidate.name)
                )
            if is_ignored(spec, project_root, candidate) or is_binary_suffix(candidate):
                continue
            if file_glob:
                from kora.utils.ignore import matches_glob

                if not matches_glob(candidate.name, file_glob):
                    continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            matched_here = 0
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    results.append(f"{rel_check.as_posix()}:{lineno}: {line.strip()[:200]}")
                    matched_here += 1
                    if len(results) >= MAX_RESULTS or matched_here >= 5:
                        break

        header = f"# {len(results)} matches"
        if len(results) >= MAX_RESULTS:
            header += " (truncated)"
        tokens = estimate_tokens("\n".join(results))
        note = f" ~{tokens}t" if tokens > 1000 else ""
        body = "\n".join(results) or "(no matches)"
        return ToolResult(output=f"{header}{note}\n{body}")

    @staticmethod
    def _format(lines: list[str], engine: str) -> ToolResult:
        shown = lines[:MAX_RESULTS]
        header = f"# {len(shown)} matches ({engine})"
        if len(lines) > MAX_RESULTS:
            header += f" showing first {MAX_RESULTS}"
        return ToolResult(output=f"{header}\n" + ("\n".join(shown) or "(no matches)"))
