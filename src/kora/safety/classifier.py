"""Command safety classification.

Three levels:
  SAFE        - read-only commands, auto-run (but logged)
  MODERATE    - installs/builds/git-writes; needs a single "y"
  DESTRUCTIVE - data-destroying commands; needs typed "yes"

The classifier is intentionally conservative: anything not recognized as
safe falls through to MODERATE unless a destructive pattern matches.
"""

from __future__ import annotations

import re
import shlex
from enum import StrEnum
from typing import NamedTuple


class SafetyLevel(StrEnum):
    SAFE = "safe"
    MODERATE = "moderate"
    DESTRUCTIVE = "destructive"


class Classification(NamedTuple):
    level: SafetyLevel
    reason: str


# --------------------------------------------------------------------------
# Destructive patterns (checked first, they always win)
# --------------------------------------------------------------------------

_DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\b[^|;&]*\s-(?:[a-zA-Z]*r[a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*r)", re.I),
        "recursive forced delete",
    ),
    (re.compile(r"\brm\b\s+-[a-zA-Z]*r", re.I), "recursive delete"),
    (re.compile(r"\bdel\b.*\s/[sq]", re.I), "Windows recursive delete"),
    (re.compile(r"\brd\b\s+/s", re.I), "Windows recursive dir delete"),
    (re.compile(r"Remove-Item\b.*-Recurse", re.I), "PowerShell recursive remove"),
    (re.compile(r"\bformat\b\s+[a-zA-Z]:", re.I), "disk format"),
    (re.compile(r"\bmkfs\b"), "filesystem creation"),
    (re.compile(r"\bdd\b\s+if="), "raw disk write"),
    (re.compile(r">\s*/dev/(?:sd|nvme|hd)"), "direct device overwrite"),
    (re.compile(r":\(\)\s*\{.*\};\s*:"), "fork bomb"),
    (re.compile(r"\bsudo\b"), "superuser execution"),
    (re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b", re.I), "system power control"),
    (
        re.compile(r"git\s+(?:reset\s+--hard|checkout\s+--\s+\.)", re.I),
        "git hard reset / wipe changes",
    ),
    (
        re.compile(r"git\s+push\b[^|;&]*(?:--force\b|-f\b|--force-with-lease)", re.I),
        "forced git push",
    ),
    (re.compile(r"git\s+clean\s+-[a-zA-Z]*[fdx]", re.I), "git clean removing files"),
    (re.compile(r"git\s+branch\s+-[a-zA-Z]*D", re.I), "force branch deletion"),
    (re.compile(r"\bdrop\s+(?:table|database|schema)\b", re.I), "SQL drop"),
    (re.compile(r"\btruncate\s+table\b", re.I), "SQL truncate"),
    (re.compile(r"\btaskkill\b\s+/f", re.I), "force process kill"),
    (re.compile(r"\bkill(?:\s+-9|\s+-KILL)\b", re.I), "SIGKILL process"),
    (re.compile(r"chmod\s+-R\s+777"), "world-writable permissions"),
    (re.compile(r"\bshred\b"), "file shredding"),
]

# --------------------------------------------------------------------------
# Safe patterns (read-only)
# --------------------------------------------------------------------------

_SAFE_COMMANDS: set[str] = {
    # POSIX
    "ls",
    "pwd",
    "cat",
    "head",
    "tail",
    "grep",
    "rg",
    "find",
    "which",
    "whoami",
    "wc",
    "file",
    "stat",
    "du",
    "df",
    "env",
    "printenv",
    "date",
    "uname",
    "hostname",
    "echo",
    "tree",
    "less",
    "more",
    "diff",
    "python",
    "python3",
    "pip",
    "pip3",
    "node",
    "npm",
    "git",
    "cargo",
    "go",
    "java",
    "dotnet",
    "flutter",
    "docker",
    "kubectl",
    # Windows / PowerShell
    "dir",
    "type",
    "where",
    "get-childitem",
    "get-content",
    "select-string",
    "measure-object",
    "test-path",
}

# Subcommands that keep these binaries in SAFE territory when they appear as
# the first argument. Anything else falls back to MODERATE.
_SAFE_SUBCOMMANDS: dict[str, set[str]] = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame"},
    "python": {"--version", "-V"},
    "python3": {"--version", "-V"},
    "pip": {"list", "show", "--version"},
    "pip3": {"list", "show", "--version"},
    "npm": {"list", "ls", "--version", "view", "outdated"},
    "npx": {"--version"},
    "node": {"--version", "-v"},
    "flutter": {"--version", "doctor"},
    "docker": {"ps", "images", "--version"},
    "kubectl": {"get", "describe", "version"},
    "cargo": {"--version", "search"},
    "go": {"version"},
    "java": {"--version", "-version"},
    "dotnet": {"--version", "--info"},
}

# Commands that are inherently mutating even though they look benign.
_MODERATE_HINTS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:pip3?|poetry|uv)\s+install\b", re.I),
    re.compile(r"\bnpm\s+(?:install|i|ci|update|run|exec|link)\b", re.I),
    re.compile(r"\byarn\s+(?:add|install|run|remove)\b", re.I),
    re.compile(r"\bpnpm\s+(?:add|install|update|remove|run)\b", re.I),
    re.compile(
        r"\bapt(?:-get)?\s+install\b|\bbrew\s+install\b|\byum\s+install\b|\bpacman\s+-S\b", re.I
    ),
    re.compile(
        r"\bgit\s+(?:add|commit|push|pull|fetch|clone|merge|rebase|stash|tag|init|restore|apply|cherry-pick)\b",
        re.I,
    ),
    re.compile(
        r"\bpytest\b|\bunittest\b|\bblack\b|\bruff\b(?!.*--version)|\beslint\b|\bprettier\b|\bmypy\b",
        re.I,
    ),
    re.compile(r"\bmkdir\b|\btouch\b|\bcp\b|\bmv\b|\bln\b|\bcopy\b|\bmove\b|\bnew-item\b", re.I),
    re.compile(r"\bcurl\b|\bwget\b|\binvoke-webrequest\b", re.I),
    re.compile(r"\balembic\s+(?:upgrade|revision|downgrade)\b", re.I),
    re.compile(r"\bdocker\s+(?:build|run|compose|pull|stop|restart)\b", re.I),
    re.compile(r"\b(npx|flutter|create-)", re.I),
    re.compile(r"\b(?:uvicorn|gunicorn|flask|fastapi|vite|next|expo|serve)\b", re.I),
    re.compile(r"\bkill\b|\btaskkill\b", re.I),
    re.compile(r"\bset-content\b|\badd-content\b|\bout-file\b|\becho\s+>", re.I),
]


def _first_token(command: str) -> str:
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return ""
    token = tokens[0].strip("'\"")
    return token.lower().replace(".exe", "")


def classify_command(command: str) -> Classification:
    """Classify a shell command string into a safety level."""
    cmd = command.strip()
    lowered = cmd.lower()

    for pattern, reason in _DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd):
            return Classification(SafetyLevel.DESTRUCTIVE, reason)

    binary = _first_token(cmd)

    if binary in _SAFE_COMMANDS:
        subcommands = _SAFE_SUBCOMMANDS.get(binary)
        if subcommands is None:
            return Classification(SafetyLevel.SAFE, f"'{binary}' is read-only")
        rest = lowered[len(binary) :].split()
        first_arg = next((a for a in rest if not a.startswith("-")), "")
        if not first_arg or any(
            first_arg.startswith(s.lstrip("-")) or first_arg in s for s in subcommands
        ):
            return Classification(SafetyLevel.SAFE, f"'{binary}' read-only usage")
        # e.g. `git add` -> moderate via hints below

    for hint in _MODERATE_HINTS:
        if hint.search(cmd):
            return Classification(SafetyLevel.MODERATE, hint.pattern[:40])

    if binary and binary not in ("", "cd"):
        # Unknown binaries default to moderate (needs one "y").
        return Classification(SafetyLevel.MODERATE, f"unrecognized command '{binary}'")

    return Classification(SafetyLevel.MODERATE, "default")


def max_level(a: SafetyLevel, b: SafetyLevel) -> SafetyLevel:
    order = {SafetyLevel.SAFE: 0, SafetyLevel.MODERATE: 1, SafetyLevel.DESTRUCTIVE: 2}
    return a if order[a] >= order[b] else b


def confirmation_prompt(
    level: SafetyLevel, command: str, lang: str = "en"
) -> tuple[str, list[str]]:
    """Return (prompt_text, accepted_answers) for a given safety level."""
    from kora import i18n

    rw = lang == "rw"
    if level is SafetyLevel.SAFE:
        return "", ["y"]
    if level is SafetyLevel.MODERATE:
        prompt = i18n.tr("run_command", "rw") if rw else "Run command?"
        return f"{prompt}\n[dim]{command}[/dim]\n[y/n]", ["y", "yes"]
    prompt = "IKOSI RIKOMEYE / DESTRUCTIVE COMMAND" if rw else "DESTRUCTIVE COMMAND"
    accept = "andika yes" if rw else "type yes"
    return (
        f"[bold red]{prompt}[/bold red]\n{command}\n{accept} to proceed",
        ["yes"],
    )
