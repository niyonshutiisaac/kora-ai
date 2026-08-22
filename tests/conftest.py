"""Pytest fixtures for Kora tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """An empty temporary directory acting as a project root."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text('def main():\n    print("hi")\n', encoding="utf-8")
    return tmp_path


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
