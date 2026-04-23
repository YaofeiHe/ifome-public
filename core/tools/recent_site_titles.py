"""Discover recent article titles from one website via feed, sitemap, or homepage links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from core.runtime.time import now_in_project_timezone
from core.tools.web_page_client import WebPageClient


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

XML_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9",
}

DEFAULT_FEED_PATHS = (
    "/feed",
    "/rss",
    "/rss.xml",
    "/atom.xml",
    "/feed.xml",
)

DEFAULT_LISTING_PATHS = (
    "/articles",
    "/news",
    "/archive",
    "/information/web_news/",
    "/newsflashes/catalog",
)


@dataclass(frozen=True)
class RecentArticleTitle:
    """One recent article title discovered from a watched site."""

    title: str
    url: str
    published_at: str
    discovery_source: str
    snippet: str | None = None


def _coerce_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00").replace("/", "-")
    normalized = normalized.replace("年", "-").replace("月", "-").replace("日", "")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=now_in_project_timezone().tzinfo)
    return parsed


def _is_recent(value: datetime | None, *, now: datetime, hours: int) -> bool:
    if value is None:
        return False
    age = now - value
    return timedelta(0) <= age <= timedelta(hours=hours)


def _fetch_text(url: str, timeout_seconds: int = 15) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore"), content_type


def _fetch_json(url: str, timeout_seconds: int = 15) -> object:
    body, _ = _fetch_text(url, timeout_seconds=timeout_seconds)
    return json.loads(body)


def _strip_namespace(tag: str) -> str:
    return tag.split("}", 1)[-1]


class _HomepageLinkParser(HTMLParser):
    """Extract feed links and article-like links from one homepage HTML page."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.feed_links: list[str] = []
        self.page_links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401
        attributes = {key.lower(): value for key, value in attrs}
        if tag == "link":
            rel = str(attributes.get("rel") or "").lower()
            href = str(attributes.get("href") or "").strip()
            type_value = str(attributes.get("type") or "").lower()
            if href and "alternate" in rel and any(
                marker in type_value for marker in ("rss", "atom", "xml")
            ):
                self.feed_links.append(urljoin(self.base_url, href))
        if tag == "a":
            href = str(attributes.get("href") or "").strip()
            if href:
                self.page_links.append(urljoin(self.base_url, href))


class _JsonLdParser(HTMLParser):
    """Extract JSON-LD blobs that may contain article list metadata."""

    def __init__(self) -> None:
        super().__init__()
        self._in_json_ld = False
        self._current_parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401
        attributes = {key.lower(): value for key, value in attrs}
        if tag == "script" and str(attributes.get("type") or "").lower() == "application/ld+json":
            self._in_json_ld = True
            self._current_parts = []

    def handle_endtag(self, tag: str) -> None:  # noqa: D401
        if tag == "script" and self._in_json_ld:
            block = "".join(self._current_parts).strip()
            if block:
                self.blocks.append(block)
            self._in_json_ld = False
            self._current_parts = []

    def handle_data(self, data: str) -> None:  # noqa: D401
        if self._in_json_ld:
            self._current_parts.append(data)


def _same_host(left: str, right: str) -> bool:
    left_host = urlparse(left).netloc.lower().replace("www.", "")
    right_host = urlparse(right).netloc.lower().replace("www.", "")
    if not left_host or not right_host:
        return False
    return right_host == left_host or right_host.endswith(f".{left_host}")


def _looks_like_article_link(site_url: str, candidate_url: str) -> bool:
    if not _same_host(site_url, candidate_url):
        return False
    parsed = urlparse(candidate_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = parsed.path or "/"
    if path in {"", "/"}:
        return False
    blocked_markers = (
        "/tag/",
        "/tags/",
        "/category/",
        "/categories/",
        "/about",
        "/contact",
        "/search",
        "/login",
        "/signup",
    )
    if any(marker in path.lower() for marker in blocked_markers):
        return False
    return bool(re.search(r"/[\w-]{4,}", path))


def _iter_rss_entries(xml_text: str) -> Iterable[tuple[str | None, str | None, str | None]]:
    root = ET.fromstring(xml_text)
    root_name = _strip_namespace(root.tag).lower()
    if root_name == "rss":
        for item in root.findall("./channel/item"):
            yield (
                item.findtext("title"),
                item.findtext("link"),
                item.findtext("pubDate") or item.findtext("published"),
            )
        return
    if root_name == "feed":
        for entry in root.findall("atom:entry", XML_NAMESPACES):
            link = None
            link_node = entry.find("atom:link", XML_NAMESPACES)
            if link_node is not None:
                link = link_node.attrib.get("href")
            yield (
                entry.findtext("atom:title", default="", namespaces=XML_NAMESPACES),
                link,
                entry.findtext("atom:updated", default="", namespaces=XML_NAMESPACES)
                or entry.findtext("atom:published", default="", namespaces=XML_NAMESPACES),
            )


def _iter_sitemap_urls(xml_text: str) -> Iterable[tuple[str | None, str | None]]:
    root = ET.fromstring(xml_text)
    root_name = _strip_namespace(root.tag).lower()
    if root_name == "sitemapindex":
        for sitemap in root.findall("sitemap:sitemap", XML_NAMESPACES):
            yield (
                sitemap.findtext("sitemap:loc", default="", namespaces=XML_NAMESPACES),
                sitemap.findtext("sitemap:lastmod", default="", namespaces=XML_NAMESPACES),
            )
        return
    if root_name == "urlset":
        for entry in root.findall("sitemap:url", XML_NAMESPACES):
            yield (
                entry.findtext("sitemap:loc", default="", namespaces=XML_NAMESPACES),
                entry.findtext("sitemap:lastmod", default="", namespaces=XML_NAMESPACES),
            )


def _discover_homepage_candidates(
    site_url: str,
    *,
    timeout_seconds: int,
) -> tuple[list[str], list[str], list[str]]:
    html_text, _ = _fetch_text(site_url, timeout_seconds=timeout_seconds)
    parser = _HomepageLinkParser(site_url)
    parser.feed(html_text)
    feed_links = list(dict.fromkeys(parser.feed_links))
    visible_links = [
        link for link in dict.fromkeys(parser.page_links) if _same_host(site_url, link)
    ]
    article_links = [
        link for link in dict.fromkeys(parser.page_links) if _looks_like_article_link(site_url, link)
    ]
    return feed_links, article_links, visible_links


def _extract_json_ld_articles(site_url: str, html_text: str) -> list[RecentArticleTitle]:
    """Read JSON-LD blocks and convert article-like entries into normalized candidates."""

    parser = _JsonLdParser()
    parser.feed(html_text)
    articles: list[RecentArticleTitle] = []

    def walk(node) -> Iterable[dict]:
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for block in parser.blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        for entry in walk(payload):
            entry_type = str(entry.get("@type") or "").lower()
            if entry_type not in {"newsarticle", "article", "blogposting", "itemlist"}:
                continue
            if entry_type == "itemlist":
                items = entry.get("itemListElement") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    target = item.get("item") if isinstance(item.get("item"), dict) else item
                    title = str(target.get("headline") or target.get("name") or "").strip()
                    url = str(target.get("url") or "").strip()
                    published_at = str(
                        target.get("datePublished") or target.get("dateCreated") or ""
                    ).strip()
                    if title and url and _same_host(site_url, url):
                        articles.append(
                            RecentArticleTitle(
                                title=title,
                                url=url,
                                published_at=published_at,
                                discovery_source="json_ld",
                            )
                        )
                continue
            title = str(entry.get("headline") or entry.get("name") or "").strip()
            url = str(entry.get("url") or "").strip()
            published_at = str(
                entry.get("datePublished") or entry.get("dateCreated") or ""
            ).strip()
            if title and url and _same_host(site_url, url):
                articles.append(
                    RecentArticleTitle(
                        title=title,
                        url=url,
                        published_at=published_at,
                        discovery_source="json_ld",
                    )
                )

    deduped: list[RecentArticleTitle] = []
    seen_urls: set[str] = set()
    for article in articles:
        if not article.url or article.url in seen_urls:
            continue
        seen_urls.add(article.url)
        deduped.append(article)
    return deduped


def _fetch_jiqizhixin_article_library_recent_titles(
    *,
    now: datetime,
    hours: int,
    limit: int,
    timeout_seconds: int,
) -> list[RecentArticleTitle]:
    """Read Jiqizhixin's public article-library API and keep only recent titles."""

    endpoint = "https://www.jiqizhixin.com/api/article_library/articles.json?sort=time&page=1&per=24"
    try:
        payload = _fetch_json(endpoint, timeout_seconds=timeout_seconds)
    except Exception:
        return []

    if not isinstance(payload, dict) or payload.get("success") is not True:
        return []

    data = payload.get("articles")
    if not isinstance(data, list):
        return []

    collected: list[RecentArticleTitle] = []
    seen_urls: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = str(
            entry.get("title") or entry.get("fullCommonName") or entry.get("commonName") or ""
        ).strip()
        published_at = str(entry.get("publishedAt") or "").strip()
        slug = str(entry.get("slug") or "").strip()
        snippet = str(entry.get("content") or "").strip() or None
        if not title or not published_at or not slug:
            continue
        published_dt = _coerce_datetime(published_at)
        if not _is_recent(published_dt, now=now, hours=hours):
            continue
        url = f"https://www.jiqizhixin.com/articles/{slug}"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        collected.append(
            RecentArticleTitle(
                title=title,
                url=url,
                published_at=published_dt.isoformat(),
                discovery_source="jiqizhixin_article_library_api",
                snippet=snippet,
            )
        )
        if len(collected) >= limit:
            break
    return collected


def fetch_recent_site_titles(
    site_url: str,
    *,
    hours: int = 24,
    now: datetime | None = None,
    limit: int = 50,
    timeout_seconds: int = 15,
    page_client: WebPageClient | None = None,
) -> list[RecentArticleTitle]:
    """Try to collect recent article titles from one site using multiple discovery strategies."""

    effective_now = now or now_in_project_timezone()
    page_fetcher = page_client or WebPageClient(timeout_seconds=timeout_seconds)
    collected: list[RecentArticleTitle] = []
    seen_urls: set[str] = set()
    hostname = urlparse(site_url).netloc.lower().replace("www.", "")

    if hostname == "jiqizhixin.com":
        article_titles = _fetch_jiqizhixin_article_library_recent_titles(
            now=effective_now,
            hours=hours,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
        for item in article_titles:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            collected.append(item)

    feed_links: list[str] = []
    homepage_article_links: list[str] = []
    homepage_visible_links: list[str] = []
    try:
        discovered_feed_links, homepage_article_links, homepage_visible_links = _discover_homepage_candidates(
            site_url,
            timeout_seconds=timeout_seconds,
        )
        feed_links.extend(discovered_feed_links)
    except Exception:
        homepage_article_links = []
        homepage_visible_links = []

    feed_links.extend(urljoin(site_url, path) for path in DEFAULT_FEED_PATHS)
    feed_links = list(dict.fromkeys(feed_links))

    listing_pages = [site_url, *(urljoin(site_url, path) for path in DEFAULT_LISTING_PATHS)]
    listing_pages = list(dict.fromkeys(listing_pages))

    for listing_url in listing_pages:
        try:
            html_text, content_type = _fetch_text(listing_url, timeout_seconds=timeout_seconds)
        except Exception:
            continue
        if "html" not in content_type.lower():
            continue
        for article in _extract_json_ld_articles(site_url, html_text):
            if article.url in seen_urls:
                continue
            published_dt = _coerce_datetime(article.published_at)
            if not _is_recent(published_dt, now=effective_now, hours=hours):
                continue
            seen_urls.add(article.url)
            collected.append(
                RecentArticleTitle(
                    title=article.title,
                    url=article.url,
                    published_at=published_dt.isoformat(),
                    discovery_source=article.discovery_source,
                )
            )

    for feed_url in feed_links:
        try:
            xml_text, content_type = _fetch_text(feed_url, timeout_seconds=timeout_seconds)
        except Exception:
            continue
        if "xml" not in content_type.lower() and "<rss" not in xml_text and "<feed" not in xml_text:
            continue
        try:
            for title, entry_url, published_at in _iter_rss_entries(xml_text):
                if not title or not entry_url or entry_url in seen_urls:
                    continue
                published_dt = _coerce_datetime(published_at)
                if not _is_recent(published_dt, now=effective_now, hours=hours):
                    continue
                seen_urls.add(entry_url)
                collected.append(
                    RecentArticleTitle(
                        title=str(title).strip(),
                        url=str(entry_url).strip(),
                        published_at=published_dt.isoformat(),
                        discovery_source="feed",
                    )
                )
        except ET.ParseError:
            continue

    sitemap_url = urljoin(site_url, "/sitemap.xml")
    try:
        sitemap_xml, content_type = _fetch_text(sitemap_url, timeout_seconds=timeout_seconds)
    except Exception:
        sitemap_xml = ""
        content_type = ""
    if sitemap_xml and ("xml" in content_type.lower() or "<urlset" in sitemap_xml or "<sitemapindex" in sitemap_xml):
        sitemap_targets: list[str] = []
        try:
            sitemap_entries = list(_iter_sitemap_urls(sitemap_xml))
        except ET.ParseError:
            sitemap_entries = []
        if sitemap_entries and _strip_namespace(ET.fromstring(sitemap_xml).tag).lower() == "sitemapindex":
            for loc, lastmod in sitemap_entries[:12]:
                if not loc:
                    continue
                lastmod_dt = _coerce_datetime(lastmod)
                if lastmod_dt is not None and not _is_recent(lastmod_dt, now=effective_now, hours=max(hours * 3, 72)):
                    continue
                sitemap_targets.append(loc)
        else:
            sitemap_targets.append(sitemap_url)

        for target in sitemap_targets:
            try:
                target_xml, _ = _fetch_text(target, timeout_seconds=timeout_seconds)
                for loc, lastmod in _iter_sitemap_urls(target_xml):
                    if not loc or loc in seen_urls or not _looks_like_article_link(site_url, loc):
                        continue
                    lastmod_dt = _coerce_datetime(lastmod)
                    if lastmod_dt is None or not _is_recent(lastmod_dt, now=effective_now, hours=hours):
                        continue
                    try:
                        extracted = page_fetcher.fetch(loc)
                    except Exception:
                        continue
                    published_dt = _coerce_datetime(
                        str(extracted.source_metadata.get("published_at") or lastmod)
                    )
                    if not _is_recent(published_dt, now=effective_now, hours=hours):
                        continue
                    seen_urls.add(loc)
                    collected.append(
                        RecentArticleTitle(
                            title=(extracted.title or loc).strip(),
                            url=loc,
                            published_at=published_dt.isoformat(),
                            discovery_source="sitemap",
                        )
                    )
            except Exception:
                continue

    homepage_probe_links = homepage_article_links[: max(limit * 2, 20)]
    if hostname == "jiqizhixin.com":
        homepage_probe_links = homepage_visible_links[: max(limit * 2, 20)]

    for link in homepage_probe_links:
        if link in seen_urls:
            continue
        try:
            extracted = page_fetcher.fetch(link)
        except Exception:
            continue
        published_dt = _coerce_datetime(str(extracted.source_metadata.get("published_at") or ""))
        if not _is_recent(published_dt, now=effective_now, hours=hours):
            continue
        seen_urls.add(link)
        collected.append(
            RecentArticleTitle(
                title=(extracted.title or link).strip(),
                url=link,
                published_at=published_dt.isoformat(),
                discovery_source="homepage",
            )
        )

    collected.sort(key=lambda item: item.published_at, reverse=True)
    return collected[:limit]
