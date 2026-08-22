"""Filesystem tools: read_file, write_file, edit_file, list_directory."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from kora.models.base import estimate_tokens
from kora.safety import SafetyLevel
from kora.tools.base import Tool, ToolContext, ToolResult
from kora.utils.atomic import atomic_write_text
from kora.utils.backup import Backups
from kora.utils.diff import colored_diff
from kora.utils.ignore import is_binary_suffix

MAX_READ_CHARS = 120_000


def _run_sync(fn, *args):
    return asyncio.to_thread(fn, *args)


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read a text file. Optionally restrict to a line range (1-based, inclusive). "
        "Output includes line numbers prefixed like '12: content'."
    )
    params = {
        "path": {"type": "string", "description": "File path relative to project root"},
        "start_line": {"type": "integer", "description": "First line to read (1-based)"},
        "end_line": {"type": "integer", "description": "Last line to read (inclusive)"},
    }
    required = ["path"]

    async def run(
        self,
        ctx: ToolContext,
        path: str = "",
        start_line: int | None = None,
        end_line: int | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            target: Path = ctx.resolve_path(path)
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))

        if not target.exists():
            return ToolResult(ok=False, error=f"File not found: {path}")
        if target.is_dir():
            return ToolResult(ok=False, error=f"'{path}' is a directory; use list_directory")
        if is_binary_suffix(target):
            return ToolResult(ok=False, error=f"Refusing to read binary file: {path}")

        def read() -> tuple[str, int]:
            with open(target, encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            total = len(lines)
            start = max(1, start_line or 1)
            end = min(total, end_line or total)
            if start > end:
                return "", total
            selected = lines[start - 1 : end]
            numbered = "".join(f"{i}: {line}" for i, line in enumerate(selected, start=start))
            return numbered, total

        numbered, total = await _run_sync(read)

        if len(numbered) > MAX_READ_CHARS:
            cut = numbered[:MAX_READ_CHARS]
            note = f"\n... [truncated at {MAX_READ_CHARS} chars; use start_line/end_line]"
        else:
            note = ""

        header = f"# {path} ({total} lines)"
        tokens = estimate_tokens(numbered)
        meta_note = f" ~{tokens} tokens" if tokens > 500 else ""
        return ToolResult(
            output=f"{header}{meta_note}\n{cut if len(numbered) > MAX_READ_CHARS else numbered}{note}"
        )


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create or overwrite a file atomically. A timestamped backup of any "
        "existing file is taken first and a diff shown for confirmation."
    )
    params = {
        "path": {"type": "string", "description": "File path relative to project root"},
        "content": {"type": "string", "description": "Complete new file content"},
    }
    required = ["path", "content"]
    max_safety = SafetyLevel.MODERATE

    async def run(
        self, ctx: ToolContext, path: str = "", content: str = "", **_: Any
    ) -> ToolResult:
        try:
            target: Path = ctx.resolve_path(path)
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))

        old_text = ""
        existed = target.is_file()
        if existed:
            backup = Backups.create()
            await _run_sync(backup.backup_file, target)
            try:
                old_text = await _run_sync(target.read_text, "utf-8")
            except (UnicodeDecodeError, OSError):
                return ToolResult(ok=False, error=f"Refusing to overwrite binary file: {path}")

        if ctx.confirm_edits:
            approved = await ctx.confirm(
                SafetyLevel.MODERATE if not existed else SafetyLevel.SAFE,
                f"[write_file] {path}\n{colored_diff(old_text, content, path)}",
            )
            if not approved:
                return ToolResult(ok=False, error="Write cancelled by user")

        try:
            await _run_sync(atomic_write_text, target, content)
        except OSError as exc:
            return ToolResult(ok=False, error=f"Write failed: {exc}")

        rel = str(target.relative_to(Path(ctx.root)))
        ctx.session_files_changed.add(rel)
        verb = "overwrote" if existed else "created"
        return ToolResult(
            output=f"{verb} {rel} ({len(content.splitlines())} lines)",
            files_changed=[rel],
        )


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "Apply a precise search/replace edit inside an existing file. "
        "'old_block' must match exactly once. If it matches multiple times "
        "the edit is rejected unless 'replace_all' is true."
    )
    params = {
        "path": {"type": "string", "description": "Existing file to edit"},
        "old_block": {"type": "string", "description": "Exact text to find"},
        "new_block": {"type": "string", "description": "Replacement text"},
        "replace_all": {
            "type": "boolean",
            "description": "Replace every occurrence (default false)",
        },
    }
    required = ["path", "old_block", "new_block"]
    max_safety = SafetyLevel.MODERATE

    async def run(
        self,
        ctx: ToolContext,
        path: str = "",
        old_block: str = "",
        new_block: str = "",
        replace_all: bool = False,
        **_: Any,
    ) -> ToolResult:
        try:
            target: Path = ctx.resolve_path(path)
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))

        if not target.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")
        if is_binary_suffix(target):
            return ToolResult(ok=False, error=f"Refusing to edit binary file: {path}")

        try:
            original = await _run_sync(target.read_text, "utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            return ToolResult(ok=False, error=f"Cannot read file: {exc}")

        count = original.count(old_block)
        if count == 0:
            hint = original[:200].replace("\n", "\\n")
            return ToolResult(
                ok=False,
                error=(
                    f"old_block not found in {path}. Make sure it matches exactly, "
                    f"including whitespace. File starts with: {hint!r}"
                ),
            )
        if count > 1 and not replace_all:
            return ToolResult(
                ok=False,
                error=(
                    f"old_block appears {count} times in {path}. Provide more surrounding "
                    f"context to make it unique, or pass replace_all=true."
                ),
            )

        updated = (
            original.replace(old_block, new_block)
            if replace_all
            else original.replace(old_block, new_block, 1)
        )

        backup = Backups.create()
        await _run_sync(backup.backup_file, target)

        if ctx.confirm_edits:
            approved = await ctx.confirm(
                SafetyLevel.MODERATE,
                f"[edit_file] {path}\n{colored_diff(original, updated, path)}",
            )
            if not approved:
                return ToolResult(ok=False, error="Edit cancelled by user")

        # Post-edit syntax verification for Python sources.
        if target.suffix == ".py":
            try:
                import ast

                ast.parse(updated)
            except SyntaxError as exc:
                await _run_sync(backup.restore_file, target)
                return ToolResult(
                    ok=False,
                    error=(f"Edit would break Python syntax ({exc}); restored backup of {path}."),
                )

        await _run_sync(atomic_write_text, target, updated)
        rel = str(target.relative_to(Path(ctx.root)))
        ctx.session_files_changed.add(rel)
        occurrences = count if replace_all else 1
        return ToolResult(
            output=f"edited {rel} ({occurrences} replacement{'s' if occurrences != 1 else ''})",
            files_changed=[rel],
        )


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "List files under a directory, respecting .gitignore. Use recursive=true with depth for trees."
    params = {
        "path": {
            "type": "string",
            "description": "Directory relative to project root (default '.')",
        },
        "recursive": {"type": "boolean", "description": "Recurse into subdirectories"},
        "depth": {"type": "integer", "description": "Max depth when recursive (default 3)"},
    }
    required: list[str] = []

    async def run(
        self, ctx: ToolContext, path: str = ".", recursive: bool = False, depth: int = 3, **_: Any
    ) -> ToolResult:
        from kora.utils.ignore import load_ignore_spec

        try:
            base: Path = ctx.resolve_path(path)
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))
        if not base.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {path}")

        depth = max(1, min(int(depth), 6)) if recursive else 1
        spec = load_ignore_spec(Path(ctx.root))
        root: Path = Path(ctx.root)

        entries: list[str] = []

        def walk(directory: Path, level: int) -> None:
            try:
                children = sorted(
                    directory.iterdir(),
                    key=lambda p: (p.is_file(), p.name.lower()),
                )
            except OSError:
                return
            for child in children:
                from kora.utils.ignore import is_ignored

                if is_ignored(spec, root, child):
                    continue
                indent = "  " * level
                if child.is_dir():
                    entries.append(f"{indent}{child.name}/")
                    if level + 1 < depth:
                        walk(child, level + 1)
                else:
                    size = child.stat().st_size if child.exists() else 0
                    entries.append(f"{indent}{child.name} ({size}B)")

        if recursive:
            await _run_sync(walk, base, 0)
        else:
            for item in await _run_sync(
                lambda: sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            ):
                from kora.utils.ignore import is_ignored

                if is_ignored(spec, root, item):
                    continue
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{item.name}{suffix}")

        body = "\n".join(entries) or "(empty)"
        if len(entries) > 800:
            body = "\n".join(entries[:800]) + f"\n... [{len(entries) - 800} more]"
        return ToolResult(output=f"# {base.name}/\n{body}")


class DeleteFileTool(Tool):
    """Explicit delete tool so the model never needs `rm` for project files."""

    name = "delete_file"
    description = "Delete a single project file after backing it up. Directories are refused."
    params = {"path": {"type": "string", "description": "File to delete"}}
    required = ["path"]
    max_safety = SafetyLevel.DESTRUCTIVE

    async def run(self, ctx: ToolContext, path: str = "", **_: Any) -> ToolResult:
        try:
            target: Path = ctx.resolve_path(path)
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))
        if not target.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")

        backup = Backups.create()
        await _run_sync(backup.backup_file, target)
        ok_delete = await ctx.confirm(
            SafetyLevel.DESTRUCTIVE, f"Permanently delete '{path}'? (backup will be kept)"
        )
        if not ok_delete:
            return ToolResult(ok=False, error="Delete cancelled by user")
        await _run_sync(os.unlink, target)
        return ToolResult(output=f"deleted {path} (backup saved)")
