"""Timestamped backups under ~/.kora/backups/ with restore support."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from kora import constants
from kora.utils.atomic import atomic_write_text


def _backup_target_name(original_path: Path) -> str:
    """Flatten an absolute path into a unique, filesystem-safe file name."""
    digest = hashlib.sha1(str(original_path).encode("utf-8")).hexdigest()[:10]
    safe_name = str(original_path).replace(":", "_").replace("\\", "_").replace("/", "_")
    return f"{safe_name}.{digest}.bak"


class Backups:
    """A single backup session directory holding multiple restorable files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.manifest_path = directory / "_manifest.json"

    @classmethod
    def create(cls) -> Backups:
        constants.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return cls(constants.BACKUPS_DIR / stamp)

    def backup_file(self, path: Path | str) -> bool:
        """Copy `path` into this session. Returns True if a copy was created."""
        path = Path(path)
        if not path.is_file():
            return False
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / _backup_target_name(path)
        if not target.exists():  # keep the earliest state within a session
            shutil.copy2(path, target)
        return True

    def restore_file(self, original_path: Path | str) -> bool:
        """Restore the newest matching backup of `original_path`, if any."""
        original_path = Path(original_path)
        wanted = _backup_target_name(original_path)
        candidates = [p for p in constants.BACKUPS_DIR.rglob("*.bak") if p.name == wanted]
        if not candidates:
            return False
        source = max(candidates, key=lambda p: p.stat().st_mtime)
        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, original_path)
        return True

    def record(self, description: str) -> None:
        """Append a human-readable entry to the session manifest."""
        entries: list[str] = []
        if self.manifest_path.exists():
            try:
                loaded = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    entries = loaded
            except (json.JSONDecodeError, OSError):
                entries = []
        entries.append(description)
        atomic_write_text(self.manifest_path, json.dumps(entries, indent=2))
