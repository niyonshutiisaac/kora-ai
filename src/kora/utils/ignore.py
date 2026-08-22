"""Ignore-pattern handling via pathspec (gitignore syntax)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pathspec

DEFAULT_IGNORES = [
    ".git/",
    ".hg/",
    ".svn/",
    "__pycache__/",
    "*.pyc",
    "node_modules/",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".idea/",
    ".vscode/",
    "coverage/",
    ".next/",
    ".expo/",
    "*.lock",
]

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".bmp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".o",
    ".obj",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".parquet",
    ".pkl",
    ".pickle",
}


def load_ignore_spec(root: Path) -> pathspec.PathSpec:
    """Build a PathSpec from .gitignore files plus Kora defaults."""
    patterns = list(DEFAULT_IGNORES)
    for ignore_file in (root / ".gitignore", root / ".ignore"):
        try:
            if ignore_file.is_file():
                patterns.extend(ignore_file.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
    if hasattr(pathspec, "GitIgnoreSpec"):
        return pathspec.GitIgnoreSpec.from_lines("gitwildmatch", patterns)
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def is_ignored(spec: pathspec.PathSpec, root: Path, path: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if path.is_dir():
        rel += "/"
    return spec.match_file(rel)


def matches_glob(name: str, pattern: str) -> bool:
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def is_binary_suffix(path: Path) -> bool:
    return path.suffix.lower() in BINARY_SUFFIXES
