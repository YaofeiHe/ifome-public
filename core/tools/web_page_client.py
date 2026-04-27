"""Lightweight web page fetching and text extraction for link ingest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PUBLISHED_META_KEYS = {
    "article:published_time",
    "article:modified_time",
    "og:published_time",
    "og:updated_time",
    "publishdate",
    "pubdate",
    "date",
    "datepublished",
    "datecreated",
    "lastmodified",
    "timestamp",
}


def _normalize_text(text: str) -> str:
    """Collapse noisy whitespace while preserving readable sentence flow."""

    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_access_verification_page(title: str | None, text: str) -> bool:
    """Detect interstitial pages that should not be treated as article正文."""

    combined = _normalize_text(f"{title or ''} {text}")
    markers = (
        "环境异常",
        "当前环境异常",
        "完成验证后即可继续访问",
        "去验证",
        "verify.html",
        "secitptpage",
        "机器之心·数据服务",
        "机器之心数据服务已上线",
    )
    return any(marker in combined for marker in markers)


class _HTMLTextExtractor(HTMLParser):
    """Small HTML parser that keeps title and visible text."""

    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._ignored_tags = {"script", "style", "noscript", "svg"}
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta_values: dict[str, str] = {}
        self.time_values: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401
        attributes = {key.lower(): value for key, value in attrs}
        if tag in self._ignored_tags:
            self._ignored_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag == "meta":
            meta_key = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or attributes.get("http-equiv")
            )
            meta_value = attributes.get("content")
            if meta_key and meta_value:
                self.meta_values[meta_key.strip().lower()] = meta_value.strip()
        if tag == "time" and attributes.get("datetime"):
            self.time_values.append(attributes["datetime"].strip())
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # noqa: D401
        if tag in self._ignored_tags and self._ignored_depth > 0:
            self._ignored_depth -= 1
        if tag == "title" and self._title_depth > 0:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:  # noqa: D401
        cleaned = _normalize_text(data)
        if not cleaned:
            return
        if self._title_depth > 0:
            self.title_parts.append(cleaned)
            return
        if self._ignored_depth == 0:
            self.text_parts.append(cleaned)


@dataclass(frozen=True)
class WebPageExtractionResult:
    """Extracted web page text and metadata returned to the ingest service."""

    title: str | None
    text: str
    source_metadata: dict[str, Any]


def _parse_datetime_candidate(value: str) -> datetime | None:
    """Parse one publish-time candidate conservatively."""

    cleaned = value.strip().replace("Z", "+00:00")
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned)
        return parsed
    except ValueError:
        return None


def _extract_published_at(raw_html: str, parser: _HTMLTextExtractor, text: str) -> str | None:
    """Collect likely publish/update timestamps from HTML metadata."""

    candidates: list[str] = []
    for key in PUBLISHED_META_KEYS:
        value = parser.meta_values.get(key)
        if value:
            candidates.append(value)
    candidates.extend(parser.time_values)

    regex_candidates = re.findall(
        r"(20\d{2}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2})?)",
        raw_html,
    )
    candidates.extend(regex_candidates[:4])

    for visible_match in re.findall(
        r"(20\d{2}[年/-]\d{1,2}[月/-]\d{1,2}(?:日)?(?:\s+\d{1,2}:\d{2})?)",
        text[:1200],
    ):
        normalized = (
            visible_match.replace("年", "-")
            .replace("月", "-")
            .replace("日", "")
            .replace("/", "-")
        )
        if re.match(r"20\d{2}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?$", normalized):
            candidates.append(normalized)

    for candidate in candidates:
        parsed = _parse_datetime_candidate(candidate)
        if parsed is not None:
            return parsed.isoformat()
    return None


def _jiqizhixin_article_slug(url: str) -> str | None:
    """Return the article slug for Jiqizhixin article URLs."""

    parsed = urlparse(url)
    hostname = parsed.netloc.lower().replace("www.", "")
    if hostname != "jiqizhixin.com":
        return None
    match = re.fullmatch(r"/articles/([^/?#]+)", parsed.path)
    if not match:
        return None
    return match.group(1).strip()


class WebPageClient:
    """
    Fetch and extract visible text from a public web page.

    This keeps the link-ingest path useful before bringing in a heavier
    readability stack. The extracted text is intentionally plain and explicit.
    """

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> WebPageExtractionResult:
        """Fetch one URL and return normalized visible text plus metadata."""

        jiqizhixin_slug = _jiqizhixin_article_slug(url)
        if jiqizhixin_slug:
            try:
                return self._fetch_jiqizhixin_article(url=url, slug=jiqizhixin_slug)
            except Exception:
                pass

        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            raw_html = response.read().decode(charset, errors="ignore")

        parser = _HTMLTextExtractor()
        parser.feed(raw_html)
        title = _normalize_text(" ".join(parser.title_parts)) or None
        text = _normalize_text(" ".join(parser.text_parts))
        published_at = _extract_published_at(raw_html, parser, text)

        if not text:
            raise RuntimeError("网页正文抽取失败：未提取到可用正文。")
        if _looks_like_access_verification_page(title, text):
            raise RuntimeError("网页访问被站点验证页拦截，未获取到可用正文。")

        return WebPageExtractionResult(
            title=title,
            text=text,
            source_metadata={
                "source_kind": "link",
                "content_type": content_type,
                "page_title": title,
                "fetch_method": "urllib_html_parser",
                "text_length": len(text),
                "published_at": published_at,
            },
        )

    def _fetch_jiqizhixin_article(self, *, url: str, slug: str) -> WebPageExtractionResult:
        """Fetch Jiqizhixin article正文 from its public article-library JSON endpoint."""

        api_url = f"https://www.jiqizhixin.com/api/article_library/articles/{slug}.json"
        request = Request(
            api_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            payload = json.loads(response.read().decode(charset, errors="ignore"))

        title = _normalize_text(str(payload.get("title") or "")) or None
        content_html = str(payload.get("content") or "")
        parser = _HTMLTextExtractor()
        parser.feed(content_html)
        text = _normalize_text(" ".join(parser.text_parts))
        published_at = str(payload.get("published_at") or "").strip() or None
        if not text:
            raise RuntimeError("机器之心详情 API 未返回可用正文。")

        return WebPageExtractionResult(
            title=title,
            text=text,
            source_metadata={
                "source_kind": "link",
                "content_type": content_type,
                "page_title": title,
                "fetch_method": "jiqizhixin_article_library_detail_api",
                "text_length": len(text),
                "published_at": published_at,
                "api_url": api_url,
                "canonical_url": url,
            },
        )
