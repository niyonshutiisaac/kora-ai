"""Planner: maintains the todo list shown to the user and the model."""

from __future__ import annotations

from typing import Any


class Planner:
    """Thin state holder around the current plan (todos).

    The model mutates it through todo_write; the UI renders it live.
    """

    def __init__(self) -> None:
        self.todos: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ state

    @property
    def in_progress(self) -> dict[str, Any] | None:
        for item in self.todos:
            if item.get("status") == "in_progress":
                return item
        return None

    @property
    def progress(self) -> tuple[int, int]:
        done = sum(1 for t in self.todos if t.get("status") == "completed")
        return done, len(self.todos)

    def replace_all(self, todos: list[dict[str, Any]]) -> None:
        self.todos = todos

    # ----------------------------------------------------------------- render

    def render(self, lang: str = "en") -> str:
        if not self.todos:
            return ""
        lines = []
        icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]", "cancelled": "[-]"}
        for item in self.todos:
            icon = icons.get(item.get("status", "pending"), "[ ]")
            lines.append(f"{icon} {item['content']}")
        header = "Plan" if lang == "en" else "Gahunda"
        return f"{header}:\n" + "\n".join(lines)
