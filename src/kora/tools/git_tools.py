"""Git tools backed by GitPython, with plain-subprocess fallback."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from kora.safety import SafetyLevel
from kora.tools.base import Tool, ToolContext, ToolResult


def _git_repo(root: Path):
    from git import InvalidGitRepositoryError, Repo

    try:
        return Repo(str(root))
    except InvalidGitRepositoryError:
        return None


class _GitToolBase(Tool):
    def repo(self, ctx: ToolContext):
        return _git_repo(Path(ctx.root))


class GitStatusTool(_GitToolBase):
    name = "git_status"
    description = "Show git working tree status (branch, staged/modified files)."
    params: dict = {}
    required: list = []

    async def run(self, ctx: ToolContext, **_: Any) -> ToolResult:
        repo = self.repo(ctx)
        if repo is None:
            return ToolResult(ok=False, error="Not a git repository")
        branch = repo.active_branch.name if not repo.head.is_detached else "(detached)"

        def collect() -> list[str]:
            lines = [f"branch: {branch}"]
            for item_a, _item_b in repo.index.diff("HEAD"):
                lines.append(f"M  {item_a.a_path}")
            for entry in repo.index.diff(None):
                path = entry.a_path or entry.b_path or "?"
                state = {None: "??", "R": "R ", "D": " D"}.get(entry.change_type, "M ")
                lines.append(f"{state} {path}")
            for untracked in repo.untracked_files[:200]:
                lines.append(f"?? {untracked}")
            return lines

        lines = await asyncio.to_thread(collect)
        return ToolResult(output="\n".join(lines) or "clean working tree")


class GitDiffTool(_GitToolBase):
    name = "git_diff"
    description = (
        "Show unified diff of the working tree (unstaged by default, pass staged=true for HEAD)."
    )
    params = {"staged": {"type": "boolean", "description": "Diff staged changes against HEAD"}}
    required: list = []

    async def run(self, ctx: ToolContext, staged: bool = False, **_: Any) -> ToolResult:
        repo = self.repo(ctx)
        if repo is None:
            return ToolResult(ok=False, error="Not a git repository")

        def do_diff() -> str:
            if staged:
                return repo.git.diff("--cached", "-U3") or repo.git.diff("HEAD", "-U3")
            return repo.git.diff("-U3")

        text = await asyncio.to_thread(do_diff)
        if len(text) > 60_000:
            text = text[:30_000] + "\n... [diff truncated] ...\n" + text[-30_000:]
        return ToolResult(output=text or "(no differences)")


class GitAddTool(_GitToolBase):
    name = "git_add"
    description = (
        "Stage files for commit. Pass paths relative to project root, or '.' for everything."
    )
    params = {
        "files": {"type": "array", "items": {"type": "string"}, "description": "Paths to stage"}
    }
    required = ["files"]
    max_safety = SafetyLevel.MODERATE

    async def run(self, ctx: ToolContext, files: list[str] | None = None, **_: Any) -> ToolResult:
        repo = self.repo(ctx)
        if repo is None:
            return ToolResult(ok=False, error="Not a git repository")
        files = files or ["."]
        approved = await ctx.confirm(SafetyLevel.MODERATE, f"git add {' '.join(files)}")
        if not approved:
            return ToolResult(ok=False, error="git_add cancelled")

        def do_add() -> str:
            repo.git.add(*files)

        try:
            await asyncio.to_thread(do_add)
        except Exception as exc:  # noqa: BLE001 - GitPython raises many types
            return ToolResult(ok=False, error=f"git add failed: {exc}")
        ctx.session_commands.append(f"git add {' '.join(files)}")
        return ToolResult(output=f"staged: {', '.join(files)}")


class GitCommitTool(_GitToolBase):
    name = "git_commit"
    description = "Commit the staged index with a message."
    params = {"message": {"type": "string", "description": "Commit message"}}
    required = ["message"]
    max_safety = SafetyLevel.MODERATE

    async def run(self, ctx: ToolContext, message: str = "", **_: Any) -> ToolResult:
        repo = self.repo(ctx)
        if repo is None:
            return ToolResult(ok=False, error="Not a git repository")
        approved = await ctx.confirm(
            SafetyLevel.MODERATE,
            f"git commit\n{message}",
        )
        if not approved:
            return ToolResult(ok=False, error="git_commit cancelled")
        try:

            def do_commit() -> object:
                return repo.index.commit(message)

            commit = await asyncio.to_thread(do_commit)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"commit failed: {exc}")
        ctx.session_commands.append(f"git commit -m {message!r}")
        return ToolResult(output=f"committed {commit.hexsha[:8]}: {message.splitlines()[0][:80]}")
