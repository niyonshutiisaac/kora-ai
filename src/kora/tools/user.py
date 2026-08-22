"""ask_user tool: lets the agent request clarification mid-loop."""

from __future__ import annotations

from kora.tools.base import Tool, ToolContext, ToolResult


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user a clarifying question and wait for their typed answer. "
        "Use sparingly - only when genuinely blocked."
    )
    params = {
        "question": {"type": "string", "description": "The question to ask the user"},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional answer choices",
        },
    }
    required = ["question"]

    def __init__(self) -> None:
        self._answer_hook = None  # set by UI: async fn(question, options) -> str

    async def run(
        self, ctx: ToolContext, question: str = "", options: list[str] | None = None, **_
    ) -> ToolResult:
        if self._answer_hook is None:
            return ToolResult(
                ok=False,
                error="No interactive prompt available in this mode; make your best assumption instead.",
            )
        answer = await self._answer_hook(question, options or [])
        return ToolResult(output=f"User answered: {answer}")
