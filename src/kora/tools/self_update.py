"""self_update tool: safe self-modification with backup-edit-test-rollback.

Flow:
  1. Refuse unless self-modification mode is enabled.
  2. Require explicit confirmation for safety-critical files.
  3. Snapshot: git commit checkpoint (or file backups when no repo).
  4. Apply edits (each file individually backed up as well).
  5. Run `ruff check` then `pytest` on Kora's own source tree.
  6. Keep changes + log success, or roll back to the snapshot and report why.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path
from typing import Any

from kora import constants
from kora.models.base import estimate_tokens
from kora.safety import SafetyLevel
from kora.tools.base import Tool, ToolContext, ToolResult
from kora.utils.atomic import atomic_write_text
from kora.utils.backup import Backups


def kora_source_root() -> Path | None:
    """Directory containing the kora package's parent (the src/ checkout)."""
    import kora

    package_dir = Path(kora.__file__).resolve().parent  # .../src/kora
    project_root = package_dir.parent.parent  # .../ (repo root)
    if (project_root / "pyproject.toml").is_file() or package_dir.name == "kora":
        return project_root if (project_root / "src" / "kora").is_dir() else package_dir.parent
    return None


class SelfUpdateTool(Tool):
    name = "self_update"
    description = (
        "Modify Kora's OWN source code safely. Provide a list of edits; each "
        "edit is {path (relative to the kora source root), and either "
        "'content' (full new content) or 'old_block'+'new_block'}. Kora will "
        "snapshot its state, apply the edits, run ruff check and pytest, and "
        "automatically roll back if anything fails. Use risk='high' only for "
        "core changes - these require extra user confirmation."
    )
    params = {
        "summary": {"type": "string", "description": "What this change does and why"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "old_block": {"type": "string"},
                    "new_block": {"type": "string"},
                },
                "required": ["path"],
            },
            "description": "List of file edits to apply",
        },
        "risk": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Risk classification",
        },
        "run_tests": {"type": "boolean", "description": "Run pytest after linting (default true)"},
    }
    required = ["summary", "edits"]
    max_safety = SafetyLevel.DESTRUCTIVE

    async def run(
        self,
        ctx: ToolContext,
        summary: str = "",
        edits: list[dict[str, Any]] | None = None,
        risk: str = "medium",
        run_tests: bool = True,
        **_: Any,
    ) -> ToolResult:
        edits = edits or []

        if not ctx.self_modification:
            return ToolResult(
                ok=False,
                error=(
                    "Self-modification mode is OFF. Enable it first with /self or set "
                    "self_modification: true in config."
                ),
            )

        source_root = kora_source_root()
        if source_root is None:
            return ToolResult(
                ok=False, error="Kora source directory not found for this installation."
            )
        if not edits:
            return ToolResult(ok=False, error="No edits provided.")

        # ---- resolve and guard every target before touching anything -------
        targets: list[tuple[Path, dict[str, Any]]] = []
        critical_touched: list[str] = []
        for edit in edits:
            raw_path = str(edit.get("path", "")).replace("\\", "/")
            candidate = source_root / raw_path.lstrip("/")
            try:
                candidate.resolve().relative_to(source_root.resolve())
            except ValueError:
                return ToolResult(ok=False, error=f"Edit path escapes kora source root: {raw_path}")

            rel_posix = candidate.resolve().relative_to(source_root.resolve()).as_posix()
            if any(rel_posix.endswith(critical) for critical in constants.SAFETY_CRITICAL_FILES):
                critical_touched.append(rel_posix)
            targets.append((candidate, edit))

        if critical_touched:
            approved = await ctx.confirm(
                SafetyLevel.DESTRUCTIVE,
                "SAFETY-CRITICAL Kora files would be modified:\n  - "
                + "\n  - ".join(critical_touched)
                + "\nThese files implement command-safety / rollback logic.\nProceed?",
            )
            if not approved:
                return ToolResult(
                    ok=False,
                    error="Cancelled: user declined modification of safety-critical files.",
                )

        if risk == "high":
            approved = await ctx.confirm(
                SafetyLevel.MODERATE,
                f"[self_update] HIGH-RISK change to Kora itself:\n{summary}\nProceed?",
            )
            if not approved:
                return ToolResult(ok=False, error="Cancelled by user.")

        # ---- 1. snapshot ----------------------------------------------------
        checkpoint_sha: str | None = None
        session_backup = Backups.create()
        repo = self._git_repo(source_root)

        if repo is not None:

            def make_checkpoint() -> str:
                repo.git.add("-A")
                dirty = bool(repo.git.status("--porcelain"))
                if dirty:
                    commit = repo.index.commit(f"[kora-self] checkpoint before: {summary[:80]}")
                    return commit.hexsha
                return repo.head.commit.hexsha

            try:
                checkpoint_sha = await asyncio.to_thread(make_checkpoint)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, error=f"Could not create git checkpoint: {exc}")
        else:
            for path, _edit in targets:
                await asyncio.to_thread(session_backup.backup_file, path)

        # ---- 2. apply edits -------------------------------------------------
        applied: list[str] = []
        errors: list[str] = []
        for path, edit in targets:
            try:
                current = path.read_text(encoding="utf-8") if path.is_file() else ""
            except (UnicodeDecodeError, OSError) as exc:
                errors.append(f"{path.name}: cannot read ({exc})")
                continue
            if "content" in edit and edit["content"] is not None:
                updated = str(edit["content"])
            elif "old_block" in edit and "new_block" in edit:
                old_block, new_block = str(edit["old_block"]), str(edit["new_block"])
                count = current.count(old_block)
                if count == 0:
                    errors.append(f"{path}: old_block not found")
                    continue
                if count > 1:
                    errors.append(f"{path}: old_block matches {count} times; needs more context")
                    continue
                updated = current.replace(old_block, new_block, 1)
            else:
                errors.append(f"{path}: edit needs either 'content' or 'old_block'+'new_block'")
                continue

            if path.suffix == ".py":
                import ast

                try:
                    ast.parse(updated)
                except SyntaxError as exc:
                    errors.append(f"{path}: syntax error after edit ({exc.lineno}): {exc.msg}")
                    continue

            await asyncio.to_thread(session_backup.backup_file, path)
            await asyncio.to_thread(atomic_write_text, path, updated)
            applied.append(str(path.relative_to(source_root)))

        if errors:
            self._rollback(repo, checkpoint_sha, session_backup, targets)
            return ToolResult(
                ok=False, error="Edits failed validation; rolled back.\n" + "\n".join(errors)
            )

        # ---- 3. verify -------------------------------------------------------
        checks: list[str] = []
        failed = False

        ruff_out = await self._run_tool(
            source_root, [sys.executable, "-m", "ruff", "check", "src"], timeout=120
        )
        checks.append(f"ruff: {'PASS' if ruff_out.ok else 'FAIL'}\n{ruff_out[:1500]}")
        if not ruff_out.ok:
            failed = True

        if run_tests and not failed:
            pytest_out = await self._run_tool(
                source_root,
                [sys.executable, "-m", "pytest", "-x", "-q"],
                timeout=600,
                cwd_tests=True,
            )
            checks.append(f"pytest: {'PASS' if pytest_out.ok else 'FAIL'}\n{pytest_out[:2500]}")
            if not pytest_out.ok:
                failed = True

        if failed:
            self._rollback(repo, checkpoint_sha, session_backup, targets)
            self._log_history(summary, status="ROLLED_BACK", detail="\n".join(checks))
            return ToolResult(
                ok=False,
                error=(
                    "Verification failed; all changes rolled back automatically.\n\n"
                    + "\n\n".join(checks)
                ),
            )

        # ---- 4. success --------------------------------------------------------
        self._log_history(
            summary, status="APPLIED", detail=f"files: {', '.join(applied)}; risk={risk}"
        )
        tokens = estimate_tokens("\n".join(checks))
        note = f" ~{tokens}t" if tokens > 800 else ""
        return ToolResult(
            output=(
                f"Self-update applied successfully{note}.\nFiles changed: {', '.join(applied)}\n"
                + "\n".join(checks)
                + ("\nGit checkpoint kept at " + checkpoint_sha if checkpoint_sha else "")
            ),
            meta={"applied": applied},
        )

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _git_repo(source_root: Path):
        from git import InvalidGitRepositoryError, Repo

        try:
            return Repo(str(source_root))
        except InvalidGitRepositoryError:
            return None

    @staticmethod
    async def _run_tool(cwd: Path, args: list[str], timeout: int, cwd_tests: bool = False):
        workdir = cwd
        if cwd_tests:
            tests_dir = cwd / "tests"
            if tests_dir.is_dir():
                workdir = tests_dir
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            text = stdout.decode("utf-8", errors="replace").strip()
            return proc.returncode == 0, text
        except (OSError, TimeoutError) as exc:
            return False, f"(could not run {args[-1]}: {exc})"

    @staticmethod
    def _rollback(
        repo,
        checkpoint_sha: str | None,
        backup: Backups,
        targets: list[tuple[Path, dict[str, Any]]],
    ) -> None:
        """Restore the pre-edit state via git reset, else per-file backups."""
        if repo is not None and checkpoint_sha:

            def do_reset() -> None:
                repo.git.reset("--hard", checkpoint_sha)
                repo.git.clean("-fd")

            try:
                do_reset()
            except Exception:  # noqa: BLE001 - fall back to per-file backups below
                pass
        for path, _edit in targets:
            try:
                backup.restore_file(path)
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _log_history(summary: str, status: str, detail: str = "") -> None:
        constants.KORA_HOME.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{stamp}] {status} :: {summary}\n"
        if detail:
            entry += "\n".join("    " + line for line in detail.splitlines()[:40]) + "\n"
        entry += "-" * 60 + "\n"
        with open(constants.SELF_HISTORY_LOG, "a", encoding="utf-8") as handle:
            handle.write(entry)
