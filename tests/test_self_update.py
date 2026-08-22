"""Tests for the self_update tool's guard rails and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from kora import constants
from kora.tools.base import ToolContext
from kora.tools.self_update import SelfUpdateTool, kora_source_root


def make_ctx(tmp_project: Path, self_mod: bool = True):
    calls = []

    async def confirm(level, description):
        calls.append((level.value, description[:60]))
        return "yes" in description.lower() or level.value != "destructive"

    return ToolContext(root=tmp_project, confirm=confirm, self_modification=self_mod), calls


class TestSourceRootDetection:
    def test_finds_source_root_in_repo(self):
        root = kora_source_root()
        assert root is not None
        # running from a src/ checkout of kora itself
        assert (root / "pyproject.toml").is_file() or (root / "src" / "kora").is_dir()


class TestSelfUpdateGuards:
    async def test_refuses_when_mode_off(self, tmp_project):
        ctx, _ = make_ctx(tmp_project, self_mod=False)
        result = await SelfUpdateTool().run(
            ctx, summary="t", edits=[{"path": "x.py", "content": "y"}]
        )
        assert not result.ok
        assert "self-modification" in (result.error or "").lower()

    async def test_refuses_empty_edits(self, tmp_project):
        ctx, _ = make_ctx(tmp_project)
        result = await SelfUpdateTool().run(ctx, summary="t", edits=[])
        assert not result.ok

    async def test_refuses_escape_from_source_root(self, tmp_project):
        ctx, _ = make_ctx(tmp_project)
        source_root = kora_source_root()
        if source_root is None:
            pytest.skip("no source root")
        result = await SelfUpdateTool().run(
            ctx,
            summary="evil",
            edits=[{"path": "../../etc/passwd", "content": "x"}],
        )
        assert not result.ok
        assert "escapes" in (result.error or "")

    async def test_safety_critical_requires_typed_confirmation(self, tmp_project, monkeypatch):
        ctx, calls = make_ctx(tmp_project)
        # simulate a fake source tree so we don't touch the real one
        fake_src = tmp_project / "kora_src"
        (fake_src / "src" / "kora" / "safety").mkdir(parents=True)
        monkeypatch.setattr(
            "kora.tools.self_update.kora_source_root",
            lambda: fake_src,
        )
        result = await SelfUpdateTool().run(
            ctx,
            summary="touch classifier",
            edits=[{"path": "src/kora/safety/classifier.py", "content": "# hacked"}],
            run_tests=False,
        )
        assert not result.ok  # our fake confirm only approves non-destructive
        assert any(level == "destructive" for level, _ in calls)

    async def test_missing_old_block_rolls_back(self, tmp_project, monkeypatch):
        """An edit that cannot apply must leave the tree untouched."""
        fake_src = tmp_project / "kora_src"
        target = fake_src / "src" / "kora" / "new_feature.py"
        target.parent.mkdir(parents=True)
        original_content = "X = 1\n"
        target.write_text(original_content, encoding="utf-8")

        monkeypatch.setattr("kora.tools.self_update.kora_source_root", lambda: fake_src)

        ctx, _ = make_ctx(tmp_project)
        result = await SelfUpdateTool().run(
            ctx,
            summary="bad edit",
            edits=[
                {"path": "src/kora/new_feature.py", "old_block": "NOT PRESENT", "new_block": "y"}
            ],
            run_tests=False,
        )
        assert not result.ok
        assert target.read_text() == original_content


class TestHistoryLog:
    def test_log_written(self, tmp_path, monkeypatch):
        log_path = tmp_path / "self_history.log"
        monkeypatch.setattr(constants, "KORA_HOME", tmp_path)
        monkeypatch.setattr(constants, "SELF_HISTORY_LOG", log_path)
        SelfUpdateTool._log_history("add feature X", status="APPLIED", detail="files: a.py")
        content = log_path.read_text(encoding="utf-8")
        assert "APPLIED" in content and "add feature X" in content
