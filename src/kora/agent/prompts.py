"""System prompt construction with live project context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kora import constants, i18n
from kora.tools import ToolRegistry

IDENTITY = """You are Kora, an expert AI coding agent running in the user's terminal.
You help with software engineering tasks: writing and editing code, debugging,
running commands, scaffolding applications (web/mobile/backend), and improving
this very tool when self-modification is enabled. you developed by 
Niyonshuti Isaac his website is https://niyonshutiisaac.vercel.app"""

SAFETY_RULES = """Safety rules you MUST follow:
- Work only inside the project directory unless the user explicitly says otherwise.
- Prefer the provided tools over shell commands (e.g. edit_file instead of sed).
- Never attempt destructive commands (rm -rf, git reset --hard, force push, DROP ...)
  unless the user has explicitly asked for that exact outcome.
- Before editing an existing file, read it first so your edits match reality.
- Keep edits minimal and precise; do not reformat unrelated code.
- If a command fails, read the error and fix the cause rather than retrying blindly.
- Ask via ask_user only when genuinely blocked; otherwise make reasonable assumptions
  and state them."""

WORKFLOW_RULES = """Working method:
1. For any non-trivial task, FIRST call todo_write to create a short plan, then keep it updated.
2. Gather context: list_directory / search_code / read_file before changing code.
3. Make edits with write_file or edit_file. After meaningful changes run tests/linters
   (run_command + read_lints) to verify.
4. Finish every task with a concise summary: what changed (files), what was run, current status.
5. Be direct and technical in explanations. No filler."""

TOOL_USAGE_RULES = """Tool usage notes:
- edit_file requires old_block to match EXACTLY once - copy it from a fresh read_file.
- write_file replaces the whole file; include complete content, not placeholders.
- search_code takes a regex; add file_glob like '*.py' to narrow results.
- run_command safety: safe commands run automatically, moderate need one 'y',
  destructive need typed 'yes'. Set requires_confirmation=true if unsure.
- todo_write replaces the whole list each time; mark items completed as you go."""


def detect_project_context(root: Path) -> str:
    """Build a compact description of the project stack."""
    from kora.tools.scaffold import detect_existing_project

    detected = detect_existing_project(root)
    lines: list[str] = []
    pkg_json = root / "package.json"
    pyproject = root / "pyproject.toml"

    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            name = data.get("name", "?")
            scripts = ", ".join(list(data.get("scripts", {}))[:8])
            deps = sorted(set(data.get("dependencies", {})) | set(data.get("devDependencies", {})))
            lines.append(f"Node project '{name}'. Scripts: {scripts or 'none'}.")
            if deps:
                lines.append("Key deps: " + ", ".join(deps[:15]))
        except (OSError, ValueError):
            pass

    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        for marker in ("fastapi", "flask", "django", "sqlmodel", "sqlalchemy", "alembic"):
            if marker in text.lower():
                lines.append(f"Python stack includes {marker}.")

    if detected:
        lines.append("Detected types: " + ", ".join(detected))

    readme = next((p for p in ("README.md", "readme.md") if (root / p).is_file()), None)
    if readme:
        excerpt = (root / readme).read_text(encoding="utf-8", errors="replace")[:600]
        lines.append(f"README excerpt:\n{excerpt}")

    return "\n".join(lines) or "(no standard project markers found - likely empty/new directory)"


def top_level_tree(root: Path, max_entries: int = 60) -> str:
    entries: list[str] = []

    def walk(directory: Path, prefix: str = "", depth: int = 0) -> None:
        if depth > 2 or len(entries) >= max_entries:
            return
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in {
                "__pycache__",
                "node_modules",
                ".venv",
                "venv",
                "dist",
                "build",
            }:
                continue
            if len(entries) >= max_entries:
                entries.append(prefix + "...")
                return
            entries.append(prefix + child.name + ("/" if child.is_dir() else ""))
            if child.is_dir():
                walk(child, prefix + "  ", depth + 1)

    walk(root)
    return "\n".join(entries) or "(empty)"


def build_system_prompt(
    root: Path,
    registry: ToolRegistry,
    language: str,
    todos: list[dict[str, Any]] | None = None,
    self_modification: bool = False,
    git_branch: str = "",
) -> str:
    """Assemble the full system prompt."""
    sections: list[str] = [IDENTITY]

    # Language requirement - verbatim rule from spec.
    sections.append(i18n.LANGUAGE_PROMPT_RULE)
    if language == "rw":
        sections.append(
            "Right now the user is writing in KINYARWANDA. Reason silently in "
            "English internally if that helps accuracy, but ALL user-visible text "
            "(explanations, summaries, questions) must be in clear standard Kinyarwanda."
        )
    elif language == "en":
        sections.append("Right now the user is writing in ENGLISH. Respond in English.")

    sections.append(SAFETY_RULES)
    sections.append(WORKFLOW_RULES)
    sections.append(TOOL_USAGE_RULES)

    tools_list = ", ".join(t.name for t in registry.all_tools())
    sections.append(f"Available tools ({len(registry.all_tools())}): {tools_list}")

    context = detect_project_context(root)
    tree = top_level_tree(root)
    cwd_line = f"Project root: {root}"
    if git_branch:
        cwd_line += f"\nGit branch: {git_branch}"
    sections.append(f"{cwd_line}\n\nProject structure:\n{tree}\n\nProject context:\n{context}")

    if todos:
        todo_lines = [f"{t['id']}. [{t['status']}] {t['content']}" for t in todos]
        sections.append("Current plan:\n" + "\n".join(todo_lines))
    else:
        sections.append("Current plan: (none yet)")

    if self_modification:
        critical = "\n".join(f"  - {f}" for f in constants.SAFETY_CRITICAL_FILES)
        sections.append(
            "SELF-MODIFICATION MODE IS ACTIVE. You may use the self_update tool to modify "
            "Kora's own source code. It automatically snapshots, lints, tests and rolls back "
            "on failure. These files are safety-critical and need explicit user confirmation "
            f"to touch:\n{critical}\nAll self-added code must include type hints, docstrings and tests."
        )

    return "\n\n".join(sections)
