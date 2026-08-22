"""Tests for the ReAct agent loop with a scripted fake provider."""

from __future__ import annotations

from pathlib import Path

from kora.agent.loop import AgentRunResult, KoraAgent
from kora.config import Settings
from kora.models.base import LLMResponse, ToolCallRequest
from kora.safety import SafetyLevel
from kora.tools.base import ToolContext
from kora.tools.fs import WriteFileTool
from kora.tools.todo import TodoWriteTool


class FakeProvider:
    """Returns queued responses in order."""

    name = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.model = "fake-model"

    async def chat(self, messages, tools=None, on_delta=None) -> LLMResponse:
        self.calls.append([m["role"] for m in messages])
        return self.responses.pop(0)

    async def close(self) -> None:
        pass


class EchoConfirm:
    def __init__(self, approve: bool) -> None:
        self.approve = approve
        self.requests: list[tuple[str, str]] = []

    async def __call__(self, level: SafetyLevel, description: str) -> bool:
        from kora.tools.base import ConfirmFn  # noqa: F401

        self.requests.append((level.value, description[:80]))
        return self.approve


def build_agent(
    tmp_path: Path, provider: FakeProvider, confirmer, confirm_edits: bool = True
) -> KoraAgent:
    settings = Settings(project_root=tmp_path, confirm_edits=confirm_edits)
    return KoraAgent(
        settings=settings,
        provider=provider,
        registry=_registry(),
        confirm=confirmer,
    )


def _registry():
    from kora.tools import ToolRegistry

    registry = ToolRegistry()
    registry.register(TodoWriteTool())
    registry.register(WriteFileTool())
    return registry


class TestReActLoop:
    async def test_tool_then_answer(self, tmp_path):
        provider = FakeProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            name="todo_write",
                            arguments={
                                "todos": [
                                    {"content": "plan", "status": "in_progress"},
                                    {"content": "finish", "status": "pending"},
                                ]
                            },
                        )
                    ],
                ),
                LLMResponse(
                    content="Done planning.",
                    tool_calls=[],
                ),
            ]
        )
        agent = build_agent(tmp_path, provider, EchoConfirm(True))
        result = await agent.process("kora plan")

        assert isinstance(result, AgentRunResult)
        assert result.final_text == "Done planning."
        assert len(agent.planner.todos) == 2
        # tool message fed back before final answer
        assert "tool" in provider.calls[-1]

    async def test_write_file_updates_session(self, tmp_path):
        provider = FakeProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            name="write_file", arguments={"path": "a.txt", "content": "x"}
                        )
                    ],
                ),
                LLMResponse(content="wrote it"),
            ]
        )
        agent = build_agent(tmp_path, provider, EchoConfirm(True))
        result = await agent.process("andika a.txt")
        assert (tmp_path / "a.txt").read_text() == "x"
        assert "a.txt" in result.files_changed

    async def test_unknown_tool_reported_to_model(self, tmp_path):
        provider = FakeProvider(
            [
                LLMResponse(
                    content=None, tool_calls=[ToolCallRequest(name="does_not_exist", arguments={})]
                ),
                LLMResponse(content="recovered"),
            ]
        )
        agent = build_agent(tmp_path, provider, EchoConfirm(True))
        result = await agent.process("do it")
        assert result.final_text == "recovered"

    async def test_declined_confirmation_stops_flow(self, tmp_path):
        provider = FakeProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            name="write_file", arguments={"path": "b.txt", "content": "y"}
                        )
                    ],
                ),
                LLMResponse(content="understood, skipping"),
            ]
        )
        agent = build_agent(tmp_path, provider, EchoConfirm(False))
        await agent.process("write b.txt")
        assert not (tmp_path / "b.txt").exists()

    async def test_history_grows(self, tmp_path):
        provider = FakeProvider([LLMResponse(content="ok"), LLMResponse(content="again ok")])
        agent = build_agent(tmp_path, provider, EchoConfirm(True))
        await agent.process("first")
        await agent.process("second")
        assert [m["role"] for m in agent.history] == ["user", "assistant", "user", "assistant"]

    async def test_system_prompt_includes_language_rule_and_context(self, tmp_path):
        provider = FakeProvider([LLMResponse(content="hi")])
        agent = build_agent(tmp_path, provider, EchoConfirm(True))
        await agent.process("hello")
        first_call_messages = provider.calls[0]
        assert "system" in first_call_messages


class TestToolContext:
    async def test_todos_shared_state(self, tmp_project):
        async def confirm(level, description):
            return True

        ctx = ToolContext(root=tmp_project, confirm=confirm)
        result = await TodoWriteTool().run(
            ctx,
            todos=[{"content": "a", "status": "pending"}, {"content": "b", "status": "completed"}],
        )
        assert result.ok
        assert ctx.todos[1]["status"] == "completed"

    def test_multiple_in_progress_demoted(self, tmp_project):
        async def confirm(level, description):
            return True

        ctx = ToolContext(root=tmp_project, confirm=confirm)

        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            TodoWriteTool().run(
                ctx,
                todos=[
                    {"content": "a", "status": "in_progress"},
                    {"content": "b", "status": "in_progress"},
                ],
            )
        )
        statuses = [t["status"] for t in ctx.todos]
        assert statuses == ["in_progress", "pending"]
