"""Extract tool calls from plain text for models without native tool calling.

Supported formats (checked in order):
  1. <tool_call>{"name": "...", "arguments": {...}}</tool_call>
  2. Fenced ```json blocks containing an object with name+arguments,
     optionally wrapped in a list.
  3. Bare JSON object with "name" and "arguments" keys as the whole message.
"""

from __future__ import annotations

import json
import re
from typing import Any

TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*([\s\S]*?)\s*</tool_call>", re.DOTALL)
FENCED_JSON_RE = re.compile(r"```(?:json|tool)\s*\n(.*?)```", re.DOTALL)


def _parse_single(obj: Any) -> tuple[str | None, dict[str, Any]]:
    """Return (name, args) when the object looks like a tool call."""
    if not isinstance(obj, dict):
        return None, {}
    name = obj.get("name") or obj.get("tool") or obj.get("function_name")
    args = obj.get("arguments")
    if args is None and isinstance(obj.get("function"), dict):
        inner = obj["function"]
        name = name or inner.get("name")
        args = inner.get("parameters") or inner.get("arguments")
    if not isinstance(name, str):
        return None, {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, (args if isinstance(args, dict) else {})


def extract_text_tool_calls(text: str) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    """Return (remaining_text, [(tool_name, arguments), ...])."""
    calls: list[tuple[str, dict[str, Any]]] = []
    remainder = text

    def consume(match: re.Match[str]) -> str:
        payload = match.group(1)
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return ""  # drop malformed block entirely
        candidates = obj if isinstance(obj, list) else [obj]
        for item in candidates:
            name, args = _parse_single(item)
            if name:
                calls.append((name, args))
        return ""  # remove from displayed text

    remainder = TOOL_CALL_TAG_RE.sub(consume, remainder)
    remainder = FENCED_JSON_RE.sub(consume, remainder)

    if not calls:
        stripped = remainder.strip()
        if stripped.startswith(("{", "[")):
            try:
                obj = json.loads(stripped)
                items = obj if isinstance(obj, list) else [obj]
                parsed = [_parse_single(i) for i in items]
                good = [(n, a) for n, a in parsed if n]
                if len(good) == len(items) and good:
                    calls.extend(good)
                    remainder = ""
            except json.JSONDecodeError:
                pass

    remainder = re.sub(r"\n{3,}", "\n\n", remainder).strip()
    return remainder, calls
