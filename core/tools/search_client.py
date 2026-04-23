"""Lightweight web search client used for one-shot keyword expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SearchResult:
    """One normalized search result snippet."""

    title: str
    snippet: str
    url: str | None = None


class NoopSearchClient:
    """Fallback client used when web search should be skipped."""

    def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
        return []


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract titles and snippets from the simple DuckDuckGo HTML results page."""

    def __init__(self) -> None:
        super().__init__()
        self._in_result_link = False
        self._in_snippet = False
        self._current_href: str | None = None
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self.results: list[SearchResult] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401
        attributes = dict(attrs)
        classes = attributes.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_result_link = True
            self._current_href = attributes.get("href")
            self._title_parts = []
            self._snippet_parts = []
        if tag == "a" and "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:  # noqa: D401
        if tag == "a" and self._in_result_link:
            title = re.sub(r"\s+", " ", " ".join(self._title_parts)).strip()
            snippet = re.sub(r"\s+", " ", " ".join(self._snippet_parts)).strip()
            if title:
                self.results.append(
                    SearchResult(
                        title=title,
                        snippet=snippet,
                        url=self._current_href,
                    )
                )
            self._in_result_link = False
            self._in_snippet = False
            self._current_href = None
            self._title_parts = []
            self._snippet_parts = []
        elif tag == "a" and self._in_snippet:
            self._in_snippet = False

    def handle_data(self, data: str) -> None:  # noqa: D401
        cleaned = re.sub(r"\s+", " ", data).strip()
        if not cleaned:
            return
        if self._in_result_link:
            self._title_parts.append(cleaned)
        elif self._in_snippet:
            self._snippet_parts.append(cleaned)


class WebSearchClient:
    """Minimal HTML search client for one-shot entity keyword expansion."""

    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
        if not query.strip():
            return []

        request = Request(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            html = response.read().decode("utf-8", errors="ignore")

        parser = _DuckDuckGoHTMLParser()
        parser.feed(html)
        return [
            {
                "title": result.title,
                "snippet": result.snippet,
                "url": result.url,
            }
            for result in parser.results[:limit]
        ]
