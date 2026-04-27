"""Unit tests for the lightweight web page client."""

from __future__ import annotations

from io import BytesIO
import json

import pytest

from core.tools.web_page_client import WebPageClient


class _FakeHeaders:
    def __init__(self, content_type: str = "text/html; charset=utf-8") -> None:
        self._content_type = content_type

    def get(self, key: str, default: str = "") -> str:
        if key.lower() == "content-type":
            return self._content_type
        return default

    def get_content_charset(self) -> str:
        return "utf-8"


class _FakeResponse:
    def __init__(self, html: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.headers = _FakeHeaders(content_type)
        self._buffer = BytesIO(html.encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_web_page_client_rejects_access_verification_page(monkeypatch) -> None:
    """Interstitial verification pages should not be treated as valid正文."""

    html = """
    <html>
      <head><title>微信公众平台</title></head>
      <body>
        <div>环境异常</div>
        <div>当前环境异常，完成验证后即可继续访问。</div>
        <a>去验证</a>
      </body>
    </html>
    """

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        return _FakeResponse(html)

    monkeypatch.setattr("core.tools.web_page_client.urlopen", fake_urlopen)

    client = WebPageClient()
    with pytest.raises(RuntimeError, match="验证页拦截"):
        client.fetch("https://mp.weixin.qq.com/s/demo")


def test_web_page_client_extracts_published_at(monkeypatch) -> None:
    """Publish time metadata should be preserved for downstream market cards."""

    html = """
    <html>
      <head>
        <title>市场文章</title>
        <meta property="article:published_time" content="2026-04-22T08:30:00+08:00" />
      </head>
      <body>
        <article>Agent 平台开始进入企业级交付阶段。</article>
      </body>
    </html>
    """

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        return _FakeResponse(html)

    monkeypatch.setattr("core.tools.web_page_client.urlopen", fake_urlopen)

    client = WebPageClient()
    result = client.fetch("https://example.com/article")
    assert result.source_metadata["published_at"] == "2026-04-22T08:30:00+08:00"


def test_web_page_client_fetches_jiqizhixin_article_detail_api(monkeypatch) -> None:
    """Jiqizhixin article pages should use the public detail JSON endpoint."""

    payload = {
        "title": "机器之心文章",
        "published_at": "2026-04-27 19:10:42",
        "content": "<p>第一段<strong>重点</strong></p><p>第二段正文</p>",
    }

    def fake_urlopen(request, timeout=15):  # noqa: ANN001
        assert request.full_url == (
            "https://www.jiqizhixin.com/api/article_library/articles/demo-slug.json"
        )
        return _FakeResponse(
            json.dumps(payload, ensure_ascii=False),
            content_type="application/json; charset=utf-8",
        )

    monkeypatch.setattr("core.tools.web_page_client.urlopen", fake_urlopen)

    client = WebPageClient()
    result = client.fetch("https://www.jiqizhixin.com/articles/demo-slug")
    assert result.title == "机器之心文章"
    assert "第一段" in result.text
    assert "第二段正文" in result.text
    assert result.source_metadata["fetch_method"] == "jiqizhixin_article_library_detail_api"
    assert result.source_metadata["published_at"] == "2026-04-27 19:10:42"
