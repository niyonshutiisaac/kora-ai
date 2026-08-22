"""Kora command-line interface (typer)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from kora import constants, i18n
from kora.config import Settings, load_settings

app = typer.Typer(
    name="kora",
    help="Kora - AI coding agent for your terminal. English & Kinyarwanda.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"kora {constants.VERSION}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Kora - kora neza: let's get work done."""


@app.command()
def chat(
    project_root: Annotated[
        Path | None, typer.Option("--root", "-r", help="Project directory")
    ] = None,
    provider: Annotated[str | None, typer.Option("--provider", "-p", help="Model provider")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model id")] = None,
    lang: Annotated[str, typer.Option(help="en | rw | auto")] = "auto",
    self_modification: Annotated[
        bool, typer.Option("--self", help="Enable self-modification mode")
    ] = False,
) -> None:
    """Launch the interactive terminal UI."""
    settings = load_settings()
    if project_root is not None:
        settings.project_root = project_root.resolve()
    if provider is not None:
        settings.default_provider = provider
    if model is not None:
        settings.default_model = model
    if lang in ("en", "rw", "auto"):
        settings.language = lang  # type: ignore[assignment]
    if self_modification:
        settings.self_modification = True

    from kora.ui.app import launch_tui

    launch_tui(settings)


@app.command()
def run(
    instruction: Annotated[str, typer.Argument(help="Task description (EN or Kinyarwanda)")],
    project_root: Annotated[Path | None, typer.Option("--root", "-r")] = None,
    provider: Annotated[str | None, typer.Option("--provider", "-p")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Auto-approve moderate actions")] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Print only the final answer")
    ] = False,
) -> None:
    """Run one instruction headlessly (no TUI), then print the result."""
    settings = load_settings()
    if project_root is not None:
        settings.project_root = project_root.resolve()
    if provider is not None:
        settings.default_provider = provider
    if model is not None:
        settings.default_model = model

    exit_code = asyncio.run(_run_headless(settings, instruction, auto_yes=yes, quiet=quiet))
    raise typer.Exit(exit_code)


async def _run_headless(settings: Settings, instruction: str, auto_yes: bool, quiet: bool) -> int:
    from rich.markup import escape

    from kora.agent.loop import KoraAgent
    from kora.models.base import ProviderError
    from kora.models.registry import ModelRegistry
    from kora.safety import SafetyLevel
    from kora.tools import default_registry

    catalog = ModelRegistry(settings)
    try:
        provider_obj = catalog.build_provider(settings.default_provider, settings.default_model)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    registry = default_registry(include_self_update=True)

    async def confirm(level: SafetyLevel, description: str) -> bool:
        if level is SafetyLevel.SAFE:
            return True
        if level is SafetyLevel.DESTRUCTIVE:
            console.print(Panel(f"[bold red]{description}[/bold red]", title="DESTRUCTIVE"))
            answer = await asyncio.to_thread(input, "type 'yes' to proceed: ")
            return answer.strip().lower() == "yes"
        if auto_yes:
            console.print(f"[dim]auto-approved:[/dim] {escape(description[:120])}")
            return True
        console.print(
            Panel(description[:800], title=i18n.tr("run_command", "rw") if False else "Confirm")
        )
        answer = await asyncio.to_thread(input, "[y/N]: ")
        return answer.strip().lower() in ("y", "yes")

    def on_event(kind: str, data: dict) -> None:
        if quiet:
            return
        if kind == "assistant_delta":
            console.print(data["text"], end="", soft_wrap=True)
        elif kind == "tool_start":
            console.print(f"\n[cyan]> {data['name']}[/cyan] {str(data.get('args', ''))[:120]}")
        elif kind == "tool_end":
            status = "[green]ok[/green]" if data["ok"] else f"[red]{data['preview'][:120]}[/red]"
            console.print(f"  {status}")

    agent = KoraAgent(
        settings=settings,
        provider=provider_obj,
        registry=registry,
        confirm=confirm,
        on_event=on_event,
    )
    try:
        result = await agent.process(instruction)
    except KeyboardInterrupt:
        console.print("\n[yellow]cancelled[/yellow]")
        return 130
    except ProviderError as exc:
        hint = ""
        if settings.default_provider == "ollama":
            hint = (
                "\n[dim]Hint:[/dim] start Ollama with [bold]ollama serve[/bold] and pull a "
                "model with [bold]ollama pull "
                f"{settings.default_model}[/bold], or choose a cloud provider "
                "(--provider groq) with its API key set."
            )
        console.print(f"\n[red]{i18n.tr('error', 'en')}:[/red] {exc}{hint}")
        return 2
    finally:
        await provider_obj.close()

    if not quiet and result.files_changed:
        console.print(
            f"\n[green]{i18n.tr('files_changed', 'en')}:[/green] {', '.join(result.files_changed)}"
        )
    console.print(f"\n{result.final_text}")
    return 0


@app.command()
def models() -> None:
    """List configured free models."""
    from kora.models.registry import ModelRegistry

    catalog = ModelRegistry(load_settings())
    for info in catalog.list_providers():
        tag = "local" if info.local else "cloud"
        console.print(
            f"\n[bold cyan]{info.key}[/bold cyan] [dim]({tag}, free)[/dim] - {info.description}"
        )
        for model_info in info.models:
            key_ok = (
                "" if info.api_key_env is None or _has_key(info.key) else " [red](no API key)[/red]"
            )
            console.print(
                f"   {info.key} {model_info.id:<45} [dim]{model_info.context} ctx[/dim]{key_ok}"
            )


def _has_key(provider: str) -> bool:
    import os

    env_names = {
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
    }
    name = env_names.get(provider)
    return bool(name and os.environ.get(name))


def cli() -> None:
    """Entry point used by pyproject scripts."""
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    cli()
