"""Shared constants for Kora."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Kora"
VERSION = "0.1.0"

# Runtime data directory (~/.kora): backups, logs, history.
KORA_HOME = Path(os.environ.get("KORA_HOME", Path.home() / ".kora"))
BACKUPS_DIR = KORA_HOME / "backups"
LOGS_DIR = KORA_HOME / "logs"
SELF_HISTORY_LOG = KORA_HOME / "self_history.log"

# User configuration directory.
CONFIG_DIR = Path(os.environ.get("KORA_CONFIG_DIR", Path.home() / ".config" / "kora"))
CONFIG_FILE = CONFIG_DIR / "config.yaml"
MODELS_FILE = CONFIG_DIR / "models.yaml"

BUNDLED_MODELS_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"

DEFAULT_TIMEOUT = 120
MAX_TOOL_OUTPUT_LINES = 2000
MAX_ITERATIONS_DEFAULT = 40

# Context window safety margin when trimming history.
HISTORY_TOKEN_BUDGET = 100_000
CHARS_PER_TOKEN_ESTIMATE = 4

IS_WINDOWS = sys.platform == "win32"

# Files whose accidental corruption would break Kora's own safety guarantees.
SAFETY_CRITICAL_FILES = (
    "src/kora/safety/classifier.py",
    "src/kora/tools/shell.py",
    "src/kora/utils/backup.py",
    "src/kora/agent/loop.py",
)
