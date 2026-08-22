"""Internationalization: English + Kinyarwanda."""

from __future__ import annotations

import re
from typing import Literal

Language = Literal["en", "rw"]

# Common Kinyarwanda function words / verbs used for lightweight detection.
KINYARWANDA_MARKERS = frozenset(
    [
        "kora",
        "andika",
        "fungura",
        "koresha",
        "shyira",
        "tangiza",
        "sobanura",
        "gerageza",
        "reba",
        "niba",
        "kuri",
        "muri",
        "gukora",
        "kwandika",
        "gufungura",
        "gukoresha",
        "gushyira",
        "gutangiza",
        "gusobanura",
        "kugerageza",
        "kureba",
        # Additional high-frequency markers that improve accuracy.
        "murakoze",
        "urakoze",
        "yego",
        "oya",
        "ubu",
        "ubwo",
        "iki",
        "ikihe",
        "ndakwiha",
        "nyamuneka",
        "cyane",
        "byose",
        "umwanya",
        "dosiye",
        "porogaramu",
        "amakuru",
        "bishoboka",
        "kena",
        "twihishe",
    ]
)

_WORD_RE = re.compile(r"[a-zA-Z'’]+")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "welcome": {
        "en": "Welcome to Kora",
        "rw": "Murakaza neza muri Kora",
    },
    "enter_command": {
        "en": "Type a command or instruction...",
        "rw": "Andika itegeko cyangwa amabwiriza...",
    },
    "model": {"en": "Model", "rw": "Moderi"},
    "tools": {"en": "Tools", "rw": "Ibikoresho"},
    "file": {"en": "File", "rw": "Dosiye"},
    "confirm": {"en": "Confirm", "rw": "Emeza"},
    "cancel": {"en": "Cancel", "rw": "Hagarika"},
    "run_command": {"en": "Run command?", "rw": "Koresha itegeko?"},
    "error": {"en": "Error", "rw": "Ikosa"},
    "thinking": {"en": "Thinking...", "rw": "Ndibwira..."},
    "files_changed": {"en": "Files changed", "rw": "Amadosiye yahinduwe"},
    "commands_run": {"en": "Commands run", "rw": "Ibikorwa byakozwe"},
    "language": {"en": "Language", "rw": "Ururimi"},
    "self_modification_on": {
        "en": "Self-modification ON",
        "rw": "Ihindura-ubwayo RIMOZE",
    },
    "self_modification_off": {
        "en": "Self-modification off",
        "rw": "Ihindura-ubwayo RIMEZE HO",
    },
    "help": {"en": "Help", "rw": "Ubufasha"},
    "quit": {"en": "Quit", "rw": "Sohoka"},
    "yes": {"en": "yes", "rw": "yego"},
    "no": {"en": "no", "rw": "oya"},
    "task_complete": {"en": "Task complete.", "rw": "Umurimo warangiye."},
    "tool_running": {"en": "Running tool", "rw": "Koresha igikoresho"},
    "backup_created": {"en": "Backup created", "rw": "Inkomeza yakorewe"},
    "rolled_back": {"en": "Rolled back", "rw": "Byagarutswe inyuma"},
}

# Kinyarwanda aliases for slash commands.
COMMAND_ALIASES: dict[str, str] = {
    "/fasha": "/help",
    "/moderi": "/model",
    "/ibikoresho": "/tools",
    "/hagarika": "/cancel",
    "/sohoka": "/quit",
    "/ururimi": "/lang",
}


def detect_language(text: str) -> Language:
    """Detect 'rw' if Kinyarwanda markers dominate, else 'en'.

    A single strong marker (imperative verb like kora/andika) is enough when
    the text is short; longer texts need a small ratio of matches.
    """
    words = [w.lower().strip("'’") for w in _WORD_RE.findall(text)]
    if not words:
        return "en"
    hits = sum(1 for w in words if w in KINYARWANDA_MARKERS)
    if len(words) <= 4:
        return "rw" if hits >= 1 else "en"
    return "rw" if hits / len(words) >= 0.15 else "en"


def resolve_language(setting: str, text: str) -> Language:
    """Resolve configured language ('auto'|'en'|'rw') against sample text."""
    if setting == "rw":
        return "rw"
    if setting == "en":
        return "en"
    return detect_language(text)


def tr(key: str, lang: Language = "en") -> str:
    """Translate a UI string key, falling back to English then the key."""
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key


def normalize_command(raw: str) -> str:
    """Map Kinyarwanda slash-command aliases onto canonical commands."""
    stripped = raw.strip()
    lowered = stripped.lower()
    for alias, canonical in COMMAND_ALIASES.items():
        if lowered.startswith(alias):
            remainder = stripped[len(alias) :]
            return f"{canonical}{remainder}"
    return stripped


LANGUAGE_PROMPT_RULE = (
    "The user may write in English or Kinyarwanda. Detect the language and "
    "always respond in the same language. If the user uses Kinyarwanda, use "
    "clear, standard Kinyarwanda for technical instructions."
)
