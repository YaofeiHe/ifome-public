"""Probe publicly visible Jiqizhixin pages and scripts for article-source clues."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.web_page_client import WebPageClient  # noqa: E402


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_URLS = (
    "https://www.jiqizhixin.com/",
    "https://www.jiqizhixin.com/rss",
    "https://www.jiqizhixin.com/articles",
    "https://www.jiqizhixin.com/ai_shortlist",
)


class _HtmlProbeParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.script_urls: list[str] = []
        self.page_title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401
        attributes = {key.lower(): value for key, value in attrs}
        if tag == "a":
            href = str(attributes.get("href") or "").strip()
            if href:
                self.links.append(urljoin(self.base_url, href))
        if tag == "script":
            src = str(attributes.get("src") or "").strip()
            if src:
                self.script_urls.append(urljoin(self.base_url, src))
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:  # noqa: D401
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:  # noqa: D401
        if self._in_title:
            self.page_title_parts.append(data)


def _fetch(url: str, timeout_seconds: int = 20) -> tuple[str, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="ignore")
        return body, response.headers.get("Content-Type", ""), response.geturl()


def _same_host(left: str, right: str) -> bool:
    left_host = urlparse(left).netloc.lower().replace("www.", "")
    right_host = urlparse(right).netloc.lower().replace("www.", "")
    return bool(left_host and right_host and right_host.endswith(left_host))


def _dedupe_keep_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _extract_clues_from_js(script_url: str, body: str) -> dict[str, object]:
    same_host_urls = sorted(
        {
            match
            for match in re.findall(r"https://[A-Za-z0-9._/-]+", body)
            if "jiqizhixin.com" in match or "cdn.jiqizhixin.com" in match
        }
    )
    relative_api_paths = sorted(
        {
            match
            for match in re.findall(
                r'["\']((?:/|https?://)[^"\']*(?:api|graphql|short_urls|articles|news|rss)[^"\']*)["\']',
                body,
            )
        }
    )
    article_like_paths = sorted(
        {
            match
            for match in re.findall(
                r'["\']((?:/|https?://)[^"\']*(?:short_urls|articles|newsflashes|ai_shortlist)[^"\']*)["\']',
                body,
            )
        }
    )
    return {
        "script_url": script_url,
        "same_host_urls": same_host_urls[:40],
        "api_like_paths": relative_api_paths[:40],
        "article_like_paths": article_like_paths[:40],
        "contains_fetch_call": "fetch(" in body,
        "contains_xml_http_request": "XMLHttpRequest" in body,
    }


def _normalize_candidate_url(base_url: str, candidate: str) -> str:
    normalized = urljoin(base_url, candidate)
    if normalized.startswith("https://cdn.jiqizhixin.com/"):
        return ""
    return normalized


def _extract_candidate_article_urls(
    base_url: str,
    same_host_links: list[str],
    js_clues: list[dict[str, object]],
) -> list[str]:
    candidates: list[str] = []
    for link in same_host_links:
        if any(marker in link for marker in ("/short_urls/", "/articles/", "/news/", "/post/")):
            candidates.append(link)
    for clue in js_clues:
        for key in ("article_like_paths", "same_host_urls"):
            for value in clue.get(key, []):
                if not isinstance(value, str):
                    continue
                normalized = _normalize_candidate_url(base_url, value)
                if not normalized:
                    continue
                if any(
                    marker in normalized
                    for marker in ("/short_urls/", "/articles/", "/news/", "/post/", "sota.jiqizhixin.com")
                ):
                    candidates.append(normalized)
    return _dedupe_keep_order(candidates)


def _probe_candidate_pages(candidate_urls: list[str], limit: int) -> list[dict[str, object]]:
    client = WebPageClient(timeout_seconds=20)
    probed: list[dict[str, object]] = []
    for url in candidate_urls[:limit]:
        try:
            result = client.fetch(url)
        except Exception as exc:  # noqa: BLE001
            probed.append(
                {
                    "url": url,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
            continue
        published_at = str(result.source_metadata.get("published_at") or "").strip() or None
        recency_hours = None
        if published_at:
            try:
                recency_hours = round(
                    (datetime.now().astimezone() - datetime.fromisoformat(published_at)).total_seconds()
                    / 3600,
                    2,
                )
            except ValueError:
                recency_hours = None
        probed.append(
            {
                "url": url,
                "title": result.title,
                "published_at": published_at,
                "recency_hours": recency_hours,
                "text_preview": result.text[:240],
            }
        )
    return probed


def probe_url(url: str, follow_candidates: int = 0) -> dict[str, object]:
    body, content_type, final_url = _fetch(url)
    parser = _HtmlProbeParser(url)
    parser.feed(body)
    links = _dedupe_keep_order(parser.links)
    scripts = _dedupe_keep_order(parser.script_urls)
    same_host_links = [link for link in links if _same_host(url, link)]
    visible_shortcuts = [
        link
        for link in same_host_links
        if any(marker in link for marker in ("/short_urls/", "/articles", "/ai_shortlist", "/rss"))
    ]

    js_clues: list[dict[str, object]] = []
    for script_url in scripts[:8]:
        try:
            script_body, script_type, _ = _fetch(script_url)
        except Exception as exc:  # noqa: BLE001
            js_clues.append(
                {
                    "script_url": script_url,
                    "error": type(exc).__name__,
                }
            )
            continue
        if "javascript" not in script_type.lower() and not script_url.endswith(".js"):
            continue
        js_clues.append(_extract_clues_from_js(script_url, script_body))

    candidate_urls = _extract_candidate_article_urls(url, same_host_links, js_clues)
    return {
        "url": url,
        "final_url": final_url,
        "content_type": content_type,
        "title": "".join(parser.page_title_parts).strip(),
        "same_host_link_count": len(same_host_links),
        "same_host_links": same_host_links[:30],
        "visible_shortcuts": visible_shortcuts[:20],
        "script_count": len(scripts),
        "script_urls": scripts[:20],
        "js_clues": js_clues,
        "candidate_article_urls": candidate_urls[:30],
        "candidate_page_probes": _probe_candidate_pages(candidate_urls, follow_candidates)
        if follow_candidates > 0
        else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Jiqizhixin pages for article-source clues.")
    parser.add_argument("urls", nargs="*", default=list(DEFAULT_URLS))
    parser.add_argument(
        "--follow-candidates",
        type=int,
        default=0,
        help="Fetch a few discovered candidate article URLs for title/time validation.",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = {
        "results": [
            probe_url(url, follow_candidates=max(0, args.follow_candidates))
            for url in args.urls
        ]
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
