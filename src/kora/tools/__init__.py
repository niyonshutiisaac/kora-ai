"""Tools package: registry of all Kora tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from kora.tools.base import Tool, ToolContext, ToolResult
from kora.tools.fs import (
    DeleteFileTool,
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from kora.tools.git_tools import GitAddTool, GitCommitTool, GitDiffTool, GitStatusTool
from kora.tools.lint import ReadLintsTool
from kora.tools.scaffold import ScaffoldProjectTool
from kora.tools.search import SearchCodeTool
from kora.tools.self_update import SelfUpdateTool
from kora.tools.shell import RunCommandTool
from kora.tools.todo import TodoWriteTool
from kora.tools.user import AskUserTool
from kora.tools.web import WebFetchTool, WebSearchTool

__all__ = [
    "AskUserTool",
    "DeleteFileTool",
    "EditFileTool",
    "GitAddTool",
    "GitCommitTool",
    "GitDiffTool",
    "GitStatusTool",
    "ListDirectoryTool",
    "ReadFileTool",
    "ReadLintsTool",
    "RunCommandTool",
    "ScaffoldProjectTool",
    "SearchCodeTool",
    "SelfUpdateTool",
    "TodoWriteTool",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "WebFetchTool",
    "WebSearchTool",
    "WriteFileTool",
    "default_registry",
]


class ToolRegistry:
    """Ordered collection of tools with schema generation."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_schemas(self, include_self_update: bool = False) -> list[dict]:
        schemas = []
        for tool in self._tools.values():
            if isinstance(tool, SelfUpdateTool) and not include_self_update:
                continue
            schemas.append(tool.json_schema())
        return schemas


ConfirmFactory = Callable[[], Awaitable[bool]]  # unused placeholder for typing clarity


def default_registry(
    ask_user_hook: Callable[[str, list[str]], Awaitable[str]] | None = None,
    include_self_update: bool = True,
) -> ToolRegistry:
    """Build the standard tool set."""
    registry = ToolRegistry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        ListDirectoryTool(),
        SearchCodeTool(),
        RunCommandTool(),
        ReadLintsTool(),
        GitStatusTool(),
        GitDiffTool(),
        GitAddTool(),
        GitCommitTool(),
        TodoWriteTool(),
        WebSearchTool(),
        WebFetchTool(),
        ScaffoldProjectTool(),
        AskUserTool(),
    ):
        registry.register(tool)
    if ask_user_hook is not None:
        registry.get("ask_user")._answer_hook = ask_user_hook  # type: ignore[union-attr]
    if include_self_update:
        registry.register(SelfUpdateTool())
    return registry
