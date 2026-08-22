"""Todo list tool backing the agent planner."""

from __future__ import annotations

from typing import Any

from kora.i18n import tr
from kora.tools.base import Tool, ToolContext, ToolResult

VALID_STATES = {"pending", "in_progress", "completed", "cancelled"}


class TodoWriteTool(Tool):
    name = "todo_write"
    description = (
        "Create or update the task plan. Pass the FULL todo list each time. "
        "Each item: {content: str, status: pending|in_progress|completed|cancelled}. "
        "Keep exactly one item in_progress while working; mark items completed as you finish them."
    )
    params = {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "status": {"type": "string", "enum": sorted(VALID_STATES)},
                },
                "required": ["content", "status"],
            },
            "description": "Complete list of tasks",
        }
    }
    required = ["todos"]

    async def run(
        self, ctx: ToolContext, todos: list[dict[str, Any]] | None = None, **_
    ) -> ToolResult:
        todos = todos or []
        cleaned: list[dict[str, Any]] = []
        for index, item in enumerate(todos[:50]):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            if not content:
                continue
            if status not in VALID_STATES:
                status = "pending"
            cleaned.append({"id": index + 1, "content": content, "status": status})

        in_progress = [t for t in cleaned if t["status"] == "in_progress"]
        if len(in_progress) > 1:
            # demote all but the first
            seen = False
            for t in cleaned:
                if t["status"] == "in_progress":
                    if seen:
                        t["status"] = "pending"
                    seen = True

        ctx.todos.clear()
        ctx.todos.extend(cleaned)

        lang = ctx.language or "en"
        lines = [f"{t['id']}. [{t['status']}] {t['content']}" for t in cleaned]
        title = tr("task_complete", lang) if not cleaned else "TODO"
        return ToolResult(
            output=f"{title}\n" + ("\n".join(lines) or "(empty plan)"), meta={"count": len(cleaned)}
        )
