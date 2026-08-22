"""scaffold_project tool: generate full starter applications."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from kora.models.base import estimate_tokens
from kora.safety import SafetyLevel
from kora.tools.base import Tool, ToolContext, ToolResult
from kora.tools.scaffold_templates import PROJECT_TYPE_DETECTORS, scaffold_files


class ScaffoldProjectTool(Tool):
    name = "scaffold_project"
    description = (
        "Generate a complete starter project in a subdirectory of the current "
        "project root. Supported types: fastapi (Python REST backend), react "
        "(Vite+TS+Tailwind), nextjs, expo (React Native), flutter. Existing "
        "files are never overwritten unless overwrite=true."
    )
    params = {
        "project_type": {
            "type": "string",
            "enum": ["fastapi", "react", "nextjs", "expo", "flutter"],
            "description": "Kind of app to generate",
        },
        "name": {"type": "string", "description": "Project/app name"},
        "directory": {"type": "string", "description": "Target directory (defaults to the name)"},
        "options": {"type": "object", "description": "Extra options, e.g. {overwrite: true}"},
    }
    required = ["project_type", "name"]
    max_safety = SafetyLevel.MODERATE

    async def run(
        self,
        ctx: ToolContext,
        project_type: str = "",
        name: str = "",
        directory: str | None = None,
        options: dict[str, Any] | None = None,
        **_: Any,
    ) -> ToolResult:
        options = options or {}
        try:
            files = scaffold_files(project_type, name)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))

        safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip("-_") or "app"
        target_rel = directory or safe_name
        try:
            target: Path = ctx.resolve_path(target_rel)
        except PermissionError as exc:
            return ToolResult(ok=False, error=str(exc))

        if target.exists() and list(target.iterdir()) and not options.get("overwrite"):
            return ToolResult(
                ok=False,
                error=f"Directory '{target_rel}' is not empty. Pass options {{'overwrite': true}} or choose another directory.",
            )

        # Prefer official CLIs when installed for mobile targets.
        if options.get("use_cli", False):
            cli_result = await self._try_official_cli(ctx, project_type, target, safe_name, options)
            if cli_result is not None:
                return cli_result

        approved = await ctx.confirm(
            SafetyLevel.MODERATE,
            f"[scaffold_project] Create {len(files)} files under '{target_rel}' ({project_type})?",
        )
        if not approved:
            return ToolResult(ok=False, error="Scaffold cancelled by user")

        created: list[str] = []
        for rel_path, content in sorted(files.items()):
            destination = target / rel_path
            if destination.exists() and not options.get("overwrite"):
                continue
            from kora.utils.atomic import atomic_write_text

            destination.parent.mkdir(parents=True, exist_ok=True)
            await __import__("asyncio").to_thread(atomic_write_text, destination, content)
            created.append(rel_path)

        total_tokens = estimate_tokens("".join(files.values()))
        next_steps = {
            "fastapi": 'pip install -e ".[dev]" && uvicorn app.main:app --reload',
            "react": "npm install && npm run dev",
            "nextjs": "npm install && npm run dev",
            "expo": "npm install && npx expo start",
            "flutter": "flutter pub get && flutter run",
        }.get(project_type.lower(), "")

        output = (
            f"Scaffolded {len(created)} files for '{name}' ({project_type}) in {target_rel}\n"
            + "\n".join(f"  + {c}" for c in created[:40])
            + ("\n  ..." if len(created) > 40 else "")
            + (f"\nNext: {next_steps}" if next_steps else "")
        )
        rel_all = [str((target / r).relative_to(Path(ctx.root))) for r in created]
        ctx.session_files_changed.update(rel_all)
        return ToolResult(
            output=output, files_changed=rel_all, meta={"approx_template_tokens": total_tokens}
        )

    @staticmethod
    async def _try_official_cli(
        ctx: ToolContext, project_type: str, target: Path, name: str, options: dict[str, Any]
    ) -> ToolResult | None:
        """Use npx/flutter CLI when available; returns None to fall back to direct generation."""
        import asyncio

        commands = {
            "expo": ("npx", ["--yes", "create-expo-app", str(target)]),
            "flutter": (
                "flutter",
                ["create", "--org", "com.kora", "--project-name", name, str(target)],
            ),
        }
        entry = commands.get(project_type.lower())
        if not entry:
            return None
        binary, args = entry
        resolved = shutil.which(binary) or shutil.which(binary + ".cmd")
        if not resolved:
            return None

        proc = await asyncio.create_subprocess_exec(
            resolved,
            *args,
            cwd=str(ctx.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
        except TimeoutError:
            proc.kill()
            return None
        if proc.returncode == 0:
            return ToolResult(output=f"Created via '{binary}' CLI in {target.name}")
        return None  # fall back silently


def detect_existing_project(root: Path) -> list[str]:
    """Detect what kind of project lives at `root` (used by prompts/context)."""
    detected: list[str] = []
    checks: list[tuple[Path, str]] = [
        (root / "package.json", "node"),
        (root / "pyproject.toml", "python"),
        (root / "pubspec.yaml", "flutter"),
        (root / "app.json", "expo"),
        (root / "requirements.txt", "python"),
    ]
    for marker, kind in checks:
        if marker.is_file():
            detected.append(kind)

    if (root / "package.json").is_file():
        try:
            import json

            data = json.loads((root / "package.json").read_text(encoding="utf-8"))
            deps = set(data.get("dependencies", {})) | set(data.get("devDependencies", {}))
            if "next" in deps:
                detected.append("nextjs")
            elif "react-native" in deps or "expo" in deps:
                detected.append("react-native")
            elif "react" in deps:
                detected.append("react")
            elif "vue" in deps:
                detected.append("vue")
        except (OSError, ValueError):
            pass
    if (root / "pyproject.toml").is_file():
        try:
            text = (root / "pyproject.toml").read_text(encoding="utf-8")
            if "fastapi" in text.lower():
                detected.append("fastapi")
            if "flask" in text.lower():
                detected.append("flask")
        except OSError:
            pass

    known = {kind for kinds in PROJECT_TYPE_DETECTORS.values() for kind in kinds}
    return [d for d in dict.fromkeys(detected) if d in known | {"node", "python"}]
