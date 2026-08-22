"""Unified diff helpers."""

from __future__ import annotations

import difflib


def unified_diff(
    old_text: str,
    new_text: str,
    fromfile: str = "a/",
    tofile: str = "b/",
    path_label: str = "file",
) -> str:
    """Return a git-style unified diff between old and new text."""
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"{fromfile}{path_label}",
        tofile=f"{tofile}{path_label}",
    )
    result = "".join(diff)
    if not result:
        result = "(no changes)"
    return result


def colored_diff(old_text: str, new_text: str, path_label: str = "file") -> str:
    """Rich markup colored diff for terminal display."""
    lines = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=f"a/{path_label}",
        tofile=f"b/{path_label}",
        lineterm="",
    )
    out: list[str] = []
    for line in lines:
        if line.startswith(("+++", "---")):
            out.append(f"[bold]{line}[/bold]")
        elif line.startswith("@@"):
            out.append(f"[cyan]{line}[/cyan]")
        elif line.startswith("+"):
            out.append(f"[green]{line}[/green]")
        elif line.startswith("-"):
            out.append(f"[red]{line}[/red]")
        else:
            out.append(line)
    return "\n".join(out) or "[dim](no changes)[/dim]"
