"""Tests for the search tool (ripgrep path and python fallback)."""

from pathlib import Path

from kora.tools.base import ToolContext
from kora.tools.search import SearchCodeTool


def make_ctx(root: Path) -> ToolContext:
    async def confirm(level, description):
        return True

    return ToolContext(root=root, confirm=confirm)


class TestSearchCode:
    async def test_finds_matches(self, tmp_project):
        (tmp_project / "src" / "extra.py").write_text("def helper():\n    return 42\n")
        result = await SearchCodeTool().run(make_ctx(tmp_project), query="helper")
        assert result.ok
        assert "helper" in result.output
        assert "src/extra.py" in result.output or "src\\extra.py" in result.output

    async def test_glob_filter(self, tmp_project):
        (tmp_project / "notes.md").write_text("TODO: write docs\n")
        result = await SearchCodeTool().run(
            make_ctx(tmp_project),
            query="TODO",
            file_glob="*.md",
        )
        assert "notes.md" in result.output or "TODO" in result.output

    async def test_invalid_regex_reported(self, tmp_project):
        result = await SearchCodeTool().run(make_ctx(tmp_project), query="([unclosed")
        assert not result.ok
        assert "regex" in (result.error or "").lower()

    async def test_no_matches(self, tmp_path):
        (tmp_path / "a.txt").write_text("nothing here")
        result = await SearchCodeTool().run(make_ctx(tmp_path), query="zzz-not-there")
        assert result.ok
        assert "(no matches)" in result.output

    async def test_ignores_gitignored_files(self, tmp_project):
        (tmp_project / ".gitignore").write_text("ignored_dir/\n")
        hidden = tmp_project / "ignored_dir"
        hidden.mkdir()
        (hidden / "secret.py").write_text("PASSWORD = 'hunter2'")
        result = await SearchCodeTool().run(make_ctx(tmp_project), query="hunter2")
        assert "ignored_dir" not in result.output
