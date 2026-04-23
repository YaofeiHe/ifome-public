"""Unit tests for the lightweight web page client."""

from __future__ import annotations

from io import BytesIO

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
    def __init__(self, html: str) -> None:
        self.headers = _FakeHeaders()
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
