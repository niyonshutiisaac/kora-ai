"""Free web tools: DuckDuckGo HTML search and plain page fetch."""

from __future__ import annotations

import html
import re

import httpx

from kora.tools.base import Tool, ToolContext, ToolResult

USER_AGENT = "Mozilla/5.0 (compatible; KoraAgent/0.1; +https://github.com/kora-ai/kora)"

_DDG_URL = "https://html.duckduckgo.com/html/"
_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL,
)
_SNIPPET_RE = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.DOTALL)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web (DuckDuckGo, no API key needed). Returns titles, URLs and snippets."
    )
    params = {"query": {"type": "string", "description": "Search query"}}
    required = ["query"]

    async def run(self, ctx: ToolContext, query: str = "", **_) -> ToolResult:
        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.post(_DDG_URL, data={"q": query})
                response.raise_for_status()
                body = response.text
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"web_search failed: {exc}")

        results: list[str] = []
        urls = _RESULT_RE.findall(body)
        snippets = [_clean(s.group(1)) for s in _SNIPPET_RE.finditer(body)]

        for index, (raw_url, raw_title) in enumerate(urls[:8]):
            url = html.unescape(raw_url)
            # DuckDuckGo wraps URLs like //duckduckgo.com/l/?uddg=<encoded>
            match = re.search(r"uddg=([^&]+)", url)
            if match:
                from urllib.parse import unquote

                url = unquote(match.group(1))
            title = _clean(raw_title)
            snippet = snippets[index] if index < len(snippets) else ""
            results.append(f"{index + 1}. {title}\n   {url}\n   {snippet[:220]}")

        output = (
            "\n".join(results)
            or "(no results - the endpoint may be rate-limiting; try web_fetch on a known URL)"
        )
        return ToolResult(output=f"# Search: {query}\n{output}")


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch a URL and return readable text content (HTML stripped), truncated."
    params = {
        "url": {"type": "string", "description": "Full http(s) URL to fetch"},
        "max_chars": {"type": "integer", "description": "Max characters to return (default 8000)"},
    }
    required = ["url"]

    async def run(self, ctx: ToolContext, url: str = "", max_chars: int = 8000, **_) -> ToolResult:
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult(ok=False, error="URL must start with http:// or https://")

        try:
            async with httpx.AsyncClient(
                timeout=25.0,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                body = response.text
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"web_fetch failed: {exc}")

        # Strip scripts/styles then tags.
        body = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", body)
        body = re.sub(r"(?is)<br\s*/?>", "\n", body)
        body = re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", body)
        text = _clean(body)
        text = re.sub(r"\n\s*\n+", "\n\n", text)

        limit = max(500, min(int(max_chars), 40_000))
        shown = text[:limit]
        suffix = f"\n... [truncated, {len(text)} chars total]" if len(text) > limit else ""
        return ToolResult(output=f"# {url}\n{shown}{suffix}")
