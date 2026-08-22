"""Kora terminal UI built on Textual."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    RichLog,
    Static,
)

from kora import constants, i18n
from kora.agent.loop import KoraAgent
from kora.config import Settings, save_setting
from kora.safety import SafetyLevel
from kora.tools import ToolRegistry, ToolResult, default_registry

FLUSH_INTERVAL = 0.06


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


class ConfirmModal(ModalScreen[bool]):
    """y/n modal; destructive actions require typing 'yes'."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    #confirm_box {
        width: 72%;
        height: auto;
        max-height: 80%;
        border: thick $warning;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [("escape", "deny", "Cancel")]

    def __init__(self, title: str, body: str, require_typed: str | None = None) -> None:
        super().__init__()
        self.modal_title = title
        self.body = body
        self.require_typed = require_typed

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_box"):
            yield Label(f"[bold yellow]{self.modal_title}[/bold yellow]")
            yield Label(self.body)
            if self.require_typed:
                yield Input(
                    placeholder=f"type '{self.require_typed}' to confirm", id="confirm_input"
                )
            else:
                yield Label("[dim]y = yes / n or Esc = no[/dim]")

    def on_key(self, event) -> None:
        if self.require_typed:
            return
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip().lower()
        self.dismiss(bool(self.require_typed) and value == self.require_typed)

    def action_deny(self) -> None:
        self.dismiss(False)


class ModelSelectorModal(ModalScreen[tuple[str, str] | None]):
    DEFAULT_CSS = """
    ModelSelectorModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    #model_box {
        width: 82%;
        height: 75%;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    #model_list { height: 1fr; margin-top: 1; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, entries: list[tuple[str, str, str]], current: str) -> None:
        super().__init__()
        self.entries = entries
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="model_box"):
            yield Label("[bold]Select a free model[/bold] [dim](provider : model)[/dim]")
            yield ListView(id="model_list")

    def on_mount(self) -> None:
        list_view = self.query_one("#model_list", ListView)
        for provider, model_id, desc in self.entries:
            marker = "[b]> [/b]" if f"{provider}:{model_id}" == self.current else "   "
            item = ListItem(
                Label(
                    f"{marker}[cyan]{provider}[/cyan] : [b]{model_id}[/b]\n     [dim]{desc}[/dim]"
                )
            )
            item.data_model = (provider, model_id)
            list_view.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        payload = getattr(event.item, "data_model", None)
        self.dismiss(payload)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AskUserModal(ModalScreen[str]):
    DEFAULT_CSS = """
    AskUserModal { align: center middle; background: rgba(0, 0, 0, 0.6); }
    #ask_box {
        width: 70%;
        height: auto;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, question: str, options: list[str]) -> None:
        super().__init__()
        self.question = question
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="ask_box"):
            yield Label(f"[bold cyan]?[/bold cyan] {self.question}")
            placeholder = " / ".join(self.options) if self.options else "your answer..."
            yield Input(placeholder=placeholder, id="ask_input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class KoraTUI(App[None]):
    TITLE = "Kora"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        ("ctrl+m", "model_selector", "Model"),
        ("ctrl+t", "toggle_tools", "Tools"),
        ("ctrl+c", "cancel_task", "Cancel"),
        ("ctrl+d", "quit", "Quit"),
    ]

    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry | None = None,
        agent: KoraAgent | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.registry = registry or default_registry()
        self.agent = agent
        self.lang: i18n.Language = "en"
        self.total_tokens = 0
        self._stream_md: Markdown | None = None
        self._stream_buffer = ""
        self._flush_task: asyncio.Task | None = None
        self._busy = False

    # ------------------------------------------------------------------ setup

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status_bar")
        with Horizontal(id="main_area"):
            yield DirectoryTree(str(Path(self.settings.root)), id="file_tree")
            with VerticalScroll(id="center_panel") as chat:
                chat.can_focus = False
            yield RichLog(id="right_panel", markup=True, wrap=True)
        yield Input(
            placeholder=i18n.tr("enter_command", self.lang),
            id="command_input",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#command_input", Input).focus()
        self._append_markdown(
            f"**{i18n.tr('welcome', self.lang)}** - Kora v{constants.VERSION}\n\n{self._help_text()}",
            classes="assistant_msg",
        )
        self.set_interval(10.0, self._refresh_status)

    # ---------------------------------------------------------------- helpers

    def _help_text(self) -> str:
        return "\n".join(
            [
                "/help (/fasha) - " + i18n.tr("help", self.lang),
                "/model (/moderi) - " + i18n.tr("model", self.lang),
                "/tools (/ibikoresho) - " + i18n.tr("tools", self.lang),
                "/lang en|rw|auto - " + i18n.tr("language", self.lang),
                "/self on|off - " + i18n.tr("self_modification_on", self.lang),
                "/clear - reset conversation",
                "/quit (/sohoka) - " + i18n.tr("quit", self.lang),
                "",
                "Ctrl+M model | Ctrl+T tools | Ctrl+C cancel | Ctrl+D quit",
            ]
        )

    def _status_text(self) -> str:
        branch = ""
        try:
            from git import Repo

            repo = Repo(str(self.settings.root))
            if not repo.head.is_detached:
                branch = f" | {repo.active_branch.name}"
        except Exception:  # noqa: BLE001 - git optional
            pass
        self_flag = " [red]SELF-MOD[/red]" if self.settings.self_modification else ""
        lang_name = {"en": "EN", "rw": "RW"}.get(self.settings.language, "AUTO")
        provider = self.agent.provider.name if self.agent else "?"
        model = self.agent.provider.model if self.agent else "?"
        busy = " | [green]working...[/green]" if self._busy else ""
        return (
            f"{i18n.tr('model', self.lang)}: [cyan]{provider}/{model}[/cyan] | "
            f"{Path(self.settings.root).name}{branch} | "
            f"tok:{self.total_tokens} | {lang_name}{self_flag}{busy}"
        )

    def _refresh_status(self) -> None:
        try:
            self.query_one("#status_bar", Static).update(self._status_text())
        except Exception:  # noqa: BLE001
            pass

    def _append_markdown(self, text: str, classes: str) -> Markdown:
        md = Markdown(text or " ", classes=classes)
        chat = self.query_one("#center_panel", VerticalScroll)
        chat.mount(md)
        chat.scroll_end(animate=False)
        return md

    def _append_tool_line(self, text: str) -> None:
        from textual.widgets import Static

        chat = self.query_one("#center_panel", VerticalScroll)
        chat.mount(Static(text, classes="tool_msg"))
        chat.scroll_end(animate=False)

    def tool_log(self) -> RichLog:
        return self.query_one("#right_panel", RichLog)

    # ---------------------------------------------------------------- actions

    def action_toggle_tools(self) -> None:
        self.query_one("#right_panel").toggle_class("visible")

    def action_cancel_task(self) -> None:
        if self.agent is not None:
            self.agent.cancel_requested = True
        self._append_tool_line("[yellow]Cancel requested - finishing current step...[/yellow]")

    def action_model_selector(self) -> None:
        self.run_worker(self._open_model_selector(), exclusive=True)

    async def _open_model_selector(self) -> None:
        from kora.models.registry import ModelRegistry

        catalog = ModelRegistry(self.settings)
        entries: list[tuple[str, str, str]] = []
        for info in catalog.list_providers():
            for model in info.models:
                tag = "local/offline" if info.local else "cloud/free"
                ctx = model.context or "?"
                entries.append(
                    (info.key, model.id, f"{tag}; ctx={ctx}; {info.description}")
                )
        current = f"{self.settings.default_provider}:{self.settings.default_model}"
        selection = await self.push_screen_wait(ModelSelectorModal(entries, current))
        if selection:
            await self.switch_model(selection[0], selection[1])

    async def switch_model(self, provider_key: str, model_id: str) -> None:
        from kora.models.registry import ModelRegistry

        catalog = ModelRegistry(self.settings)
        try:
            new_provider = catalog.build_provider(provider_key, model_id)
        except ValueError as exc:
            self._append_tool_line(f"[red]{i18n.tr('error', self.lang)}: {exc}[/red]")
            return
        old_provider = self.agent.provider if self.agent else None
        self.settings.default_provider = provider_key
        self.settings.default_model = model_id
        save_setting("default_provider", provider_key)
        save_setting("default_model", model_id)
        if self.agent is not None:
            self.agent.provider = new_provider
        if old_provider is not None and hasattr(old_provider, "close"):
            try:
                await old_provider.close()
            except Exception:  # noqa: BLE001
                pass
        self._refresh_status()
        self.tool_log().write(f"[green]model -> {provider_key}:{model_id}[/green]")
        self._append_tool_line(
            f"[green]{i18n.tr('model', self.lang)}: {provider_key}/{model_id}[/green]"
        )

    # ------------------------------------------------------------- chat flow

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return
        command = i18n.normalize_command(raw)
        if command.startswith("/"):
            await self.handle_slash(command)
            return

        self._append_markdown(raw, classes="user_msg")
        if self.agent is None:
            self._append_tool_line(f"[red]{i18n.tr('error', self.lang)}: agent not ready[/red]")
            return
        if self._busy:
            self._append_tool_line(
                "[yellow]Kora is still working - Ctrl+C to cancel first.[/yellow]"
            )
            return
        self.run_worker(self._run_agent(command), exclusive=False)

    async def handle_slash(self, command: str) -> None:
        name, _, arg = command.partition(" ")
        arg = arg.strip()

        if name in ("/help", "/?"):
            self._append_markdown(self._help_text(), classes="assistant_msg")
        elif name == "/model":
            if arg:
                parts = arg.split(maxsplit=1)
                provider = parts[0]
                model = parts[1] if len(parts) > 1 else self._guess_model(provider)
                await self.switch_model(provider, model)
            else:
                self.action_model_selector()
        elif name in ("/tools",):
            lines = [
                f"- **{t.name}** - {(t.description.splitlines() or [''])[0]}"
                for t in self.registry.all_tools()
            ]
            self._append_markdown("\n".join(lines), classes="assistant_msg")
        elif name == "/lang":
            if arg in ("en", "rw", "auto"):
                self.settings.language = arg  # type: ignore[assignment]
                save_setting("language", arg)
                self._refresh_status()
                self._append_tool_line(f"[green]language -> {arg}[/green]")
            else:
                self._append_tool_line("usage: /lang en|rw|auto")
        elif name == "/self":
            if arg in ("on", "true", "1"):
                new_val = True
            elif arg in ("off", "false", "0"):
                new_val = False
            else:
                new_val = not self.settings.self_modification
            self.settings.self_modification = new_val
            save_setting("self_modification", new_val)
            key = "self_modification_on" if new_val else "self_modification_off"
            self._append_tool_line(f"[yellow]{i18n.tr(key, self.lang)}[/yellow]")
            self._refresh_status()
        elif name == "/clear":
            if self.agent is not None:
                self.agent.reset_history()
            self._append_tool_line("[green]conversation cleared[/green]")
        elif name in ("/quit", "/exit", "/q", "/sohoka"):
            self.exit()
        else:
            self._append_tool_line(f"[red]unknown command: {name}[/red]")

    @staticmethod
    def _guess_model(provider: str) -> str:
        defaults = {
            "ollama": "qwen2.5-coder:7b",
            "groq": "llama-3.3-70b-versatile",
            "openrouter": "deepseek/deepseek-chat-v3-0324:free",
            "gemini": "gemini-3.7-flash",
            "nvidia": "deepseek-ai/deepseek-v4-flash-0731",
        }
        return defaults.get(provider, "")

    # ------------------------------------------------------------ agent run

    async def _run_agent(self, user_input: str) -> None:
        assert self.agent is not None
        input_widget = self.query_one("#command_input", Input)
        input_widget.disabled = True
        self._busy = True
        self._refresh_status()
        try:
            result = await self.agent.process(user_input)
        except KeyboardInterrupt:
            result = None
            self._append_tool_line("[yellow]" + i18n.tr("cancel", self.lang) + "[/yellow]")
        except Exception as exc:  # noqa: BLE001 - show provider errors in chat
            result = None
            message = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
            self._append_markdown(
                f"**{i18n.tr('error', self.lang)}**: {message}", classes="error_msg"
            )
        finally:
            self._busy = False
            input_widget.disabled = False
            input_widget.focus()
            self._refresh_file_tree()
            self._refresh_status()
        if result is not None:
            self.lang = result.language
            if result.final_text:
                self._append_markdown(result.final_text, classes="assistant_msg")

    # ------------------------------------------------------- event handling

    def handle_agent_event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "assistant_start":
            self._stream_md = self._append_markdown("", classes="assistant_msg")
            self._stream_buffer = ""
        elif kind == "assistant_delta":
            self._stream_buffer += data["text"]
            self._schedule_flush()
        elif kind == "tool_start":
            line = f"[magenta]{i18n.tr('tool_running', self.lang)}[/magenta]: {data['name']}({data.get('args', '')})"
            self.tool_log().write(line)
            short = f"{data['name']}({str(data.get('args', ''))[:80]})"
            self._append_tool_line(short)
        elif kind == "tool_end":
            icon = "[green]OK[/green]" if data["ok"] else "[red]ERR[/red]"
            self.tool_log().write(f"  {icon} {data['preview']}")
        elif kind == "usage":
            self.total_tokens += int(data.get("prompt", 0)) + int(data.get("completion", 0))
            self._refresh_status()
        elif kind == "done":
            files = data.get("files") or []
            commands = data.get("commands") or []
            cancelled = data.get("cancelled")
            if files:
                listing = ", ".join(files[-8:])
                self._append_tool_line(
                    f"{i18n.tr('files_changed', self.lang)} ({len(files)}): {listing}"
                )
            if commands:
                self._append_tool_line(f"{i18n.tr('commands_run', self.lang)}: {len(commands)}")
            if cancelled:
                self._append_tool_line("[yellow]" + i18n.tr("cancel", self.lang) + "[/yellow]")
            self._refresh_status()

    def _schedule_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._flush_stream())

    async def _flush_stream(self) -> None:
        await asyncio.sleep(FLUSH_INTERVAL)
        if self._stream_md is not None:
            try:
                await self._stream_md.update(self._stream_buffer)
                self.query_one("#center_panel", VerticalScroll).scroll_end(animate=False)
            except Exception:  # noqa: BLE001
                pass

    def _refresh_file_tree(self) -> None:
        try:
            self.query_one("#file_tree", DirectoryTree).reload()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def make_confirm_hook(app: KoraTUI):
    async def confirm(level: SafetyLevel, description: str) -> bool:
        rw = app.lang == "rw"
        if level is SafetyLevel.SAFE:
            return True
        title = (
            (i18n.tr("run_command", "rw") if rw else "Run command?")
            if level is SafetyLevel.MODERATE
            else ("IKOSI RIKOMEYE!" if rw else "DESTRUCTIVE COMMAND!")
        )
        require_typed = "yes" if level is SafetyLevel.DESTRUCTIVE else None
        decision = await app.push_screen_wait(
            ConfirmModal(title=title, body=description[:1500], require_typed=require_typed)
        )
        return bool(decision)

    return confirm


def make_ask_user_hook(app: KoraTUI):
    async def ask(question: str, options: list[str]) -> str:
        answer = await app.push_screen_wait(AskUserModal(question, options))
        return answer or ""

    return ask


def launch_tui(settings: Settings) -> None:
    """Create provider/agent stack and start the Textual app."""
    from kora.models.registry import ModelRegistry

    catalog = ModelRegistry(settings)
    provider = catalog.build_provider(settings.default_provider, settings.default_model)
    registry = default_registry(include_self_update=True)

    app = KoraTUI(settings=settings, registry=registry)

    agent = KoraAgent(
        settings=settings,
        provider=provider,
        registry=registry,
        confirm=make_confirm_hook(app),
        on_event=lambda kind, data: app.call_later(app.handle_agent_event, kind, dict(data)),
        ask_user=make_ask_user_hook(app),
    )
    ask_tool = registry.get("ask_user")
    if ask_tool is not None:
        ask_tool._answer_hook = make_ask_user_hook(app)  # type: ignore[attr-defined]

    app.agent = agent
    app.run()


__all__ = ["KoraTUI", "launch_tui", "ToolResult"]
