"""Small filesystem utilities used across Kora."""

from __future__ import annotations

import re


def sanitize_rel_path(raw: str) -> str:
    """Normalize a user/model supplied relative path.

    Rejects drive letters, UNC prefixes, and leading absolute markers so the
    caller can safely join it onto a project root.
    """
    cleaned = raw.strip().replace("\\", "/")
    cleaned = re.sub(r"^[A-Za-z]:", "", cleaned)
    cleaned = cleaned.lstrip("/")
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    return "/".join(parts)


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"
