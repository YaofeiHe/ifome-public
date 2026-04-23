"""Unit tests for the recent-site title discovery helper."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import json

from core.tools.recent_site_titles import fetch_recent_site_titles


class _FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get(self, key: str, default: str = "") -> str:
        if key.lower() == "content-type":
            return self._content_type
        return default

    def get_content_charset(self) -> str:
        return "utf-8"


class _FakeResponse:
    def __init__(self, body: str, content_type: str) -> None:
        self.headers = _FakeHeaders(content_type)
        self._buffer = BytesIO(body.encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_fetch_recent_site_titles_reads_recent_rss_entries(monkeypatch) -> None:
    """Feed-based discovery should return recent titles with direct article links."""

    homepage_html = """
    <html>
      <head>
        <link rel="alternate" type="application/rss+xml" href="/feed" />
      </head>
      <body><a href="/articles/ignored-home-link">Ignored</a></body>
    </html>
    """
    feed_xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>最近 24 小时的 Agent 平台文章</title>
          <link>https://www.example.com/articles/agent-platform</link>
          <pubDate>2099-04-23T10:00:00+08:00</pubDate>
        </item>
        <item>
          <title>更早之前的旧文章</title>
          <link>https://www.example.com/articles/old</link>
          <pubDate>2099-04-20T10:00:00+08:00</pubDate>
        </item>
      </channel>
    </rss>
    """

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        url = request.full_url
        if url == "https://www.example.com/":
            return _FakeResponse(homepage_html, "text/html; charset=utf-8")
        if url == "https://www.example.com/feed":
            return _FakeResponse(feed_xml, "application/rss+xml; charset=utf-8")
        raise RuntimeError(f"unexpected url: {url}")

    monkeypatch.setattr("core.tools.recent_site_titles.urlopen", fake_urlopen)

    results = fetch_recent_site_titles(
        "https://www.example.com/",
        now=datetime.fromisoformat("2099-04-23T12:00:00+08:00"),
        hours=24,
    )

    assert len(results) == 1
    assert results[0].title == "最近 24 小时的 Agent 平台文章"
    assert results[0].url == "https://www.example.com/articles/agent-platform"
    assert results[0].discovery_source == "feed"


def test_fetch_recent_site_titles_falls_back_to_homepage_article_links(monkeypatch) -> None:
    """When feed and sitemap fail, homepage article links should still be tested page by page."""

    homepage_html = """
    <html>
      <body>
        <a href="/articles/recent-story">recent</a>
        <a href="/articles/old-story">old</a>
      </body>
    </html>
    """

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        url = request.full_url
        if url == "https://www.example.com/":
            return _FakeResponse(homepage_html, "text/html; charset=utf-8")
        raise RuntimeError(f"unexpected url: {url}")

    class _FakePageClient:
        def fetch(self, url: str):  # noqa: ANN001
            published_at = (
                "2099-04-23T09:30:00+08:00"
                if "recent-story" in url
                else "2099-04-19T09:30:00+08:00"
            )
            return type(
                "Result",
                (),
                {
                    "title": "最近文章" if "recent-story" in url else "旧文章",
                    "source_metadata": {"published_at": published_at},
                },
            )()

    monkeypatch.setattr("core.tools.recent_site_titles.urlopen", fake_urlopen)

    results = fetch_recent_site_titles(
        "https://www.example.com/",
        now=datetime.fromisoformat("2099-04-23T12:00:00+08:00"),
        hours=24,
        page_client=_FakePageClient(),
    )

    assert len(results) == 1
    assert results[0].title == "最近文章"
    assert results[0].url == "https://www.example.com/articles/recent-story"
    assert results[0].discovery_source == "homepage"


def test_fetch_recent_site_titles_reads_json_ld_item_list(monkeypatch) -> None:
    """Listing pages with JSON-LD itemList should also expose recent article titles."""

    homepage_html = "<html><body>plain homepage</body></html>"
    listing_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@type": "ItemList",
          "itemListElement": [
            {
              "@type": "ListItem",
              "position": 1,
              "item": {
                "@type": "NewsArticle",
                "headline": "JSON-LD 最近文章",
                "url": "https://www.example.com/articles/json-ld-story",
                "datePublished": "2099-04-23T11:00:00+08:00"
              }
            }
          ]
        }
        </script>
      </head>
    </html>
    """

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        url = request.full_url
        if url == "https://www.example.com/":
            return _FakeResponse(homepage_html, "text/html; charset=utf-8")
        if url == "https://www.example.com/articles":
            return _FakeResponse(listing_html, "text/html; charset=utf-8")
        raise RuntimeError(f"unexpected url: {url}")

    monkeypatch.setattr("core.tools.recent_site_titles.urlopen", fake_urlopen)

    results = fetch_recent_site_titles(
        "https://www.example.com/",
        now=datetime.fromisoformat("2099-04-23T12:00:00+08:00"),
        hours=24,
    )

    assert len(results) == 1
    assert results[0].title == "JSON-LD 最近文章"
    assert results[0].url == "https://www.example.com/articles/json-ld-story"
    assert results[0].discovery_source == "json_ld"


def test_fetch_recent_site_titles_uses_visible_homepage_links_for_jiqizhixin(monkeypatch) -> None:
    """Jiqizhixin adapter should follow homepage-visible same-host links, not only article-like links."""

    homepage_html = """
    <html>
      <body>
        <a href="/rss">rss</a>
        <a href="/short_urls/demo">visible-short-link</a>
      </body>
    </html>
    """

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        url = request.full_url
        if url == "https://www.jiqizhixin.com/":
            return _FakeResponse(homepage_html, "text/html; charset=utf-8")
        raise RuntimeError(f"unexpected url: {url}")

    class _FakePageClient:
        def fetch(self, url: str):  # noqa: ANN001
            if url.endswith("/short_urls/demo"):
                return type(
                    "Result",
                    (),
                    {
                        "title": "机器之心可见入口文章",
                        "source_metadata": {"published_at": "2099-04-23T09:30:00+08:00"},
                    },
                )()
            raise RuntimeError("non-article visible links should be skipped")

    monkeypatch.setattr("core.tools.recent_site_titles.urlopen", fake_urlopen)

    results = fetch_recent_site_titles(
        "https://www.jiqizhixin.com/",
        now=datetime.fromisoformat("2099-04-23T12:00:00+08:00"),
        hours=24,
        page_client=_FakePageClient(),
    )

    assert len(results) == 1
    assert results[0].title == "机器之心可见入口文章"
    assert results[0].url == "https://www.jiqizhixin.com/short_urls/demo"


def test_fetch_recent_site_titles_reads_jiqizhixin_article_library_api(monkeypatch) -> None:
    """Jiqizhixin should prefer its public article-library API when it exposes recent content."""

    homepage_html = "<html><body><a href=\"/rss\">rss</a></body></html>"
    sota_json = json.dumps(
        {
            "success": True,
            "articles": [
                {
                    "title": "机器之心近期文章",
                    "publishedAt": "2099-04-23T10:20:00+08:00",
                    "slug": "fresh-agent-article",
                    "content": "这是一段用于回退卡片生成的摘要正文。",
                },
                {
                    "title": "机器之心旧文章",
                    "publishedAt": "2099-04-20T10:20:00+08:00",
                    "slug": "old-article",
                    "content": "旧摘要",
                },
            ],
        }
    )

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        url = request.full_url
        if url == "https://www.jiqizhixin.com/":
            return _FakeResponse(homepage_html, "text/html; charset=utf-8")
        if url == "https://www.jiqizhixin.com/api/article_library/articles.json?sort=time&page=1&per=24":
            return _FakeResponse(sota_json, "application/json; charset=utf-8")
        raise RuntimeError(f"unexpected url: {url}")

    monkeypatch.setattr("core.tools.recent_site_titles.urlopen", fake_urlopen)

    results = fetch_recent_site_titles(
        "https://www.jiqizhixin.com/",
        now=datetime.fromisoformat("2099-04-23T12:00:00+08:00"),
        hours=24,
    )

    assert len(results) == 1
    assert results[0].title == "机器之心近期文章"
    assert results[0].url == "https://www.jiqizhixin.com/articles/fresh-agent-article"
    assert results[0].snippet == "这是一段用于回退卡片生成的摘要正文。"
    assert results[0].discovery_source == "jiqizhixin_article_library_api"
