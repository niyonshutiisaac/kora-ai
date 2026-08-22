# Kora

**Kora** (Kinyarwanda for *"work" / "do"*) is an open, terminal-based AI coding agent.
It plans and executes coding tasks, edits files safely, runs shell commands with
tiered safety, scaffolds full web/mobile/backend apps, speaks **English and
Kinyarwanda**, and can even **modify its own source code** - safely.

Works with 100% free models: local [Ollama](https://ollama.com), Groq free tier,
OpenRouter `:free` models, or Google Gemini free tier.

---

## Features

- **Full-screen TUI** (Textual): project file tree, streaming chat, tool log,
  status bar (model / cwd / git branch / tokens / language / self-mod flag).
- **ReAct agent loop**: plan -> act -> observe -> answer, with a live todo list.
- **Powerful tools**: read/write/edit/list files, regex code search (ripgrep fast path),
  shell execution, git status/diff/add/commit, linting, todos, web search & fetch,
  project scaffolding, ask-user, and self-update.
- **Tiered command safety**: `safe` runs automatically, `moderate` needs one `y`,
  `destructive` needs typed `yes`. Everything is logged; timeouts and output caps apply.
- **Safe file editing**: timestamped backups in `~/.kora/backups`, atomic writes,
  unified diff preview before applying, automatic restore on syntax-breaking edits.
- **Self-modification mode** (`/self`): Kora snapshots its state (git checkpoint),
  applies its own patches, runs `ruff check` + `pytest`, and **rolls back automatically**
  if anything fails. Safety-critical files require explicit confirmation.
- **EN/RW bilingual**: language auto-detection, translated UI (`/moderi`, `/fasha`,
  `/ibikoresho`...), and a system-prompt rule that makes the model answer in the
  user's language.

## Install

```bash
# Python 3.11+
git clone <this repo> && cd koraAI
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and add any API keys you want (Ollama needs none).

## Quick start

```bash
kora chat                     # launch the TUI in the current directory
kora chat --provider groq     # start with a specific provider
kora run "explain this repo"  # one-shot headless run
kora models                   # list all configured free models
```

Inside the TUI:

| Shortcut | Action |
|----------|--------|
| `Ctrl+M` | Model selector |
| `Ctrl+T` | Toggle tool log panel |
| `Ctrl+C` | Cancel running task |
| `Ctrl+D` | Quit |

Commands: `/help` `/model` `/tools` `/lang en|rw|auto` `/self on|off` `/clear` `/quit`
Kinyarwanda aliases: `/fasha` `/moderi` `/ibikoresho` `/hagarika` `/sohoka` `/ururimi`

Example instructions:

```text
> Create a FastAPI endpoint that returns user statistics, then write tests for it.
> Kora porogaramu ya Expo y'amabanki y'imikino, iyikorere neza.
```

## Free model providers

| Provider | Needs key? | Example models |
|----------|------------|----------------|
| Ollama (local) | No | `qwen2.5-coder:7b`, `deepseek-coder:6.7b`, `llama3.1:8b`, `mistral` |
| Groq (free tier) | `GROQ_API_KEY` | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` |
| OpenRouter (free) | `OPENROUTER_API_KEY` | `deepseek/deepseek-chat-v3-0324:free`, `qwen/qwen-2.5-coder-32b-instruct:free` |
| Gemini (free tier) | `GEMINI_API_KEY` | `gemini-2.0-flash`, `gemini-1.5-flash` |

The catalog lives in [`config/models.yaml`](config/models.yaml) - edit it freely to add
models. Your selection persists across sessions. Models without native tool-calling are
supported through a robust `<tool_call>{json}</tool_call>` text parser.

For local models: install [Ollama](https://ollama.com/download), then
`ollama pull qwen2.5-coder:7b`.

## Safety model

Shell commands are classified before running:

- **safe** - read-only (`ls`, `git status`, `grep`, ...) -> auto-run, logged
- **moderate** - installs/builds/git writes (`npm install`, `pytest`, `git commit`) -> one `y`
- **destructive** - `rm -rf`, `git reset --hard`, `--force` push, `DROP`, `sudo`, ... -> typed `yes`

Additional guard rails: commands run inside the project root only (unless allowed),
120 s default timeout (configurable), last 2000 output lines shown, and a small
hard-block list (fork bombs, raw disk writes, etc.).

### Self-modification

Enable with `/self` (or `self_modification: true` in config). When active, the
agent may use the `self_update` tool which always performs:

```
snapshot (git commit checkpoint) -> apply edits -> ruff check -> pytest
   PASS -> keep changes + log to ~/.kora/self_history.log
   FAIL -> automatic rollback (git reset --hard / file backups) + error report
```

Safety-critical modules (command classifier, shell tool, backup logic, agent loop)
always require explicit typed confirmation.

## Scaffolding

Ask naturally, or use the tool directly: `scaffold_project(project_type, name)`.

| Type | Stack |
|------|-------|
| `fastapi` | FastAPI + SQLModel + Pydantic v2 settings + REST CRUD + pytest |
| `react` | Vite + React + TypeScript + Tailwind CSS + typed API client |
| `nextjs` | Next.js App Router + TypeScript + Tailwind |
| `expo` | React Native/Expo + navigation + screens + typed API client |
| `flutter` | Flutter + Material 3 + widget test |

Mobile targets can also use official CLIs (`npx create-expo-app`, `flutter create`)
via `options: {"use_cli": true}` when installed.

## Configuration

`~/.config/kora/config.yaml` (user-level, created on demand):

```yaml
default_provider: ollama      # ollama | groq | openrouter | gemini
default_model: qwen2.5-coder:7b
language: auto                # auto | en | rw
safety_level: normal          # normal | cautious | yolo
confirm_edits: true           # show diffs before applying edits
self_modification: false
allow_outside_root: false
command_timeout: 120
max_iterations: 40
```

Environment (`.env`): `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`,
`OLLAMA_BASE_URL`.

## Development

```bash
pip install -e ".[dev]"
pytest            # run the test suite
ruff check src    # lint
black src         # format
```

Project layout:

```
src/kora/
  agent/     ReAct loop, planner, system prompts
  models/    provider adapters (OpenAI-compat + Gemini), registry, tool-call parser
  tools/     all agent tools + safety-aware shell execution
  ui/        Textual TUI (app.py, app.tcss)
  utils/     atomic writes, backups, diffs, ignore patterns
tests/       pytest suite (124 tests)
```

## License

MIT

##DEVELOPED BY
 --niyonshuti Isaac