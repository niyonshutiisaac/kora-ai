"""Tests for filesystem tools (read/write/edit/list) and atomic writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from kora.safety import SafetyLevel
from kora.tools.base import ToolContext, ToolResult
from kora.tools.fs import EditFileTool, ListDirectoryTool, ReadFileTool, WriteFileTool


def make_ctx(root: Path, confirm_edits: bool = False) -> ToolContext:
    async def confirm(level: SafetyLevel, description: str) -> bool:
        return True

    return ToolContext(root=root, confirm=confirm, confirm_edits=confirm_edits)


class TestReadFile:
    async def test_read_with_line_numbers(self, tmp_project):
        result = await ReadFileTool().run(make_ctx(tmp_project), path="src/main.py")
        assert result.ok
        assert "1: def main():" in result.output

    async def test_read_range(self, tmp_path):
        (tmp_path / "lines.txt").write_text("\n".join(f"line{i}" for i in range(1, 21)))
        ctx = make_ctx(tmp_path)
        result = await ReadFileTool().run(ctx, path="lines.txt", start_line=5, end_line=7)
        assert "6: line6" in result.output
        assert "line4" not in result.output

    async def test_missing_file(self, tmp_project):
        result = await ReadFileTool().run(make_ctx(tmp_project), path="nope.py")
        assert not result.ok

    async def test_path_escape_rejected(self, tmp_project):
        result = await ReadFileTool().run(make_ctx(tmp_project), path="../outside.txt")
        assert not result.ok
        assert "outside" in (result.error or "").lower()


class TestWriteFile:
    async def test_create_and_overwrite_atomic(self, tmp_project):
        ctx = make_ctx(tmp_project)
        tool = WriteFileTool()

        created = await tool.run(ctx, path="new.txt", content="hello")
        assert created.ok
        assert (tmp_project / "new.txt").read_text() == "hello"

        overwritten = await tool.run(ctx, path="new.txt", content="world")
        assert overwritten.ok
        assert (tmp_project / "new.txt").read_text() == "world"

        # backup of the previous state must exist under ~/.kora/backups
        backups = list(Path("~/.kora/backups").expanduser().rglob("*.bak"))
        assert any("new.txt" in b.name for b in backups)

    async def test_no_tmp_files_left(self, tmp_project):
        await WriteFileTool().run(make_ctx(tmp_project), path="x.txt", content="data")
        leftovers = [p for p in tmp_project.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


class TestEditFile:
    async def test_unique_replace(self, tmp_project):
        target = tmp_project / "src" / "main.py"
        original = target.read_text()
        result = await EditFileTool().run(
            make_ctx(tmp_project),
            path="src/main.py",
            old_block='print("hi")',
            new_block='print("hello")',
        )
        assert result.ok
        updated = target.read_text()
        assert 'print("hello")' in updated
        assert updated != original

    async def test_multiple_matches_requires_flag(self, tmp_project):
        (tmp_project / "dup.txt").write_text("aaa\naaa\naaa")
        ctx = make_ctx(tmp_project)
        result = await EditFileTool().run(ctx, path="dup.txt", old_block="aaa", new_block="bbb")
        assert not result.ok
        assert "3 times" in (result.error or "")

        replace_all = await EditFileTool().run(
            ctx,
            path="dup.txt",
            old_block="aaa",
            new_block="bbb",
            replace_all=True,
        )
        assert replace_all.ok
        assert (tmp_project / "dup.txt").read_text() == "bbb\nbbb\nbbb"

    async def test_broken_python_restored(self, tmp_project):
        """A syntax-breaking edit on a .py file must be rolled back."""
        target = tmp_project / "src" / "main.py"
        before = target.read_text()
        result = await EditFileTool().run(
            make_ctx(tmp_project),
            path="src/main.py",
            old_block="def main():",
            new_block="def main(:",
        )
        assert not result.ok
        assert target.read_text() == before
        assert "restored" in (result.error or "")

    async def test_old_block_not_found(self, tmp_project):
        result = await EditFileTool().run(
            make_ctx(tmp_project),
            path="src/main.py",
            old_block="does not exist anywhere",
            new_block="x",
        )
        assert not result.ok


class TestListDirectory:
    async def test_respects_gitignore(self, tmp_project):
        (tmp_project / ".gitignore").write_text("secret*\n")
        (tmp_project / "secret_key.env").write_text("k=1")
        (tmp_project / "keep.txt").write_text("ok")
        result = await ListDirectoryTool().run(make_ctx(tmp_project))
        assert result.ok
        assert "keep.txt" in result.output
        assert "secret_key.env" not in result.output

    async def test_recursive_depth(self, tmp_project):
        deep = tmp_project / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "file.txt").write_text("x")
        result = await ListDirectoryTool().run(make_ctx(tmp_project), recursive=True, depth=2)
        # depth 2 from root shows a/ and a/b/ but not c/
        assert "a/" in result.output


class TestPathResolution:
    def test_absolute_inside_root_ok(self, tmp_project):
        ctx = make_ctx(tmp_project)
        resolved = ctx.resolve_path(str(tmp_project / "src" / "main.py"))
        assert resolved == (tmp_project / "src" / "main.py")

    def test_absolute_outside_root_blocked(self, tmp_project):
        ctx = make_ctx(tmp_project)
        with pytest.raises(PermissionError):
            ctx.resolve_path("C:/Windows/System32/config.sys")


class TestToolResult:
    def test_for_model_truncates(self):
        result = ToolResult(output="x" * 50_000)
        rendered = result.for_model(limit=1000)
        assert len(rendered) < 2000
        assert "truncated" in rendered
