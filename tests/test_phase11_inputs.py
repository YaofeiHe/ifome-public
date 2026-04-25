"""Tests for Phase 11 real link and image ingest paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import apps.api.src.services as services_module
from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.tools.recent_site_titles import RecentArticleTitle
from core.tools import OCRExtractionResult, WebPageExtractionResult


class FakeWebPageClient:
    """Deterministic page fetcher used for link-ingest tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebPageExtractionResult:
        self.calls.append(url)
        if "mp.weixin.qq.com" in url:
            return WebPageExtractionResult(
                title="微信文章岗位汇总",
                text=(
                    "滴滴 2026届春季校招正式启动，岗位涵盖工程、算法、产品与运营，"
                    "工作地点北京、杭州、上海、广州。"
                ),
                source_metadata={
                    "source_kind": "link",
                    "page_title": "微信文章岗位汇总",
                    "fetch_method": "fake_web_client",
                    "published_at": "2099-04-22T09:15:00+08:00",
                },
            )
        if "jiqizhixin.com" in url:
            return WebPageExtractionResult(
                title="机器之心 Agent 平台新观察",
                text="企业级 Agent 平台、模型评测与开发工具进入持续落地阶段。",
                source_metadata={
                    "source_kind": "link",
                    "page_title": "机器之心 Agent 平台新观察",
                    "fetch_method": "fake_web_client",
                    "published_at": "2099-04-22T08:30:00+08:00",
                },
            )
        if "qbitai.com" in url:
            return WebPageExtractionResult(
                title="量子位 编程 agent 新进展",
                text="编程 agent、仓库级检索、多文件修改和企业知识增强持续升温。",
                source_metadata={
                    "source_kind": "link",
                    "page_title": "量子位 编程 agent 新进展",
                    "fetch_method": "fake_web_client",
                    "published_at": "2099-04-22T07:40:00+08:00",
                },
            )
        if "36kr.com" in url:
            return WebPageExtractionResult(
                title="36氪 AI 应用市场动态",
                text="AI 应用工程化、智能体平台和企业服务相关融资与新品继续增加。",
                source_metadata={
                    "source_kind": "link",
                    "page_title": "36氪 AI 应用市场动态",
                    "fetch_method": "fake_web_client",
                    "published_at": "2099-04-22T06:20:00+08:00",
                },
            )
        if "taobao" in url:
            return WebPageExtractionResult(
                title="淘宝闪购暑期实习",
                text=(
                    "淘宝闪购 暑期实习 算法工程师-生成器式方向，工作地点上海，"
                    "投递截止 2026年05月01日 18:00。"
                ),
                source_metadata={
                    "source_kind": "link",
                    "page_title": "淘宝闪购暑期实习",
                    "fetch_method": "fake_web_client",
                },
            )
        return WebPageExtractionResult(
            title="阿里云校园招聘",
            text="阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
            source_metadata={
                "source_kind": "link",
                "page_title": "阿里云校园招聘",
                "fetch_method": "fake_web_client",
            },
        )


class FakeOCRClient:
    """Deterministic OCR client used for image-ingest tests."""

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        return OCRExtractionResult(
            text="你已进入二面，面试时间 2026年04月24日 15:30，地点上海。",
            source_metadata={
                "source_kind": "image",
                "ocr_engine": "fake_ocr",
            },
        )


class FakeSearchClient:
    """Deterministic search client used for keyword expansion tests."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
        self.queries.append(query)
        if "滴滴" in query:
            return [
                {
                    "title": "滴滴出行校招",
                    "snippet": "滴滴春季校招通常覆盖工程、算法、产品、运营等多个岗位类别。",
                    "url": "https://example.com/didi-campus",
                }
            ]
        if "阿里" in query:
            return [
                {
                    "title": "阿里系招聘业务线",
                    "snippet": "阿里系包含淘宝闪购、淘天、菜鸟、阿里云等招聘业务线。",
                    "url": "https://example.com/alibaba-family",
                }
            ]
        if "字节" in query:
            return [
                {
                    "title": "字节系招聘业务线",
                    "snippet": "字节系常见业务线包括抖音电商、飞书、番茄小说。",
                    "url": "https://example.com/bytedance-family",
                }
            ]
        if "自动驾驶" in query:
            return [
                {
                    "title": "自动驾驶招聘相关公司",
                    "snippet": "自动驾驶方向常见公司包括滴滴、地平线、蔚来。",
                    "url": "https://example.com/autonomous-driving",
                }
            ]
        if "site:jiqizhixin.com" in query:
            return [
                {
                    "title": "机器之心 Agent 平台新观察",
                    "snippet": "过去 24 小时关于 Agent 平台、评测和工程化的新文章。",
                    "url": "https://www.jiqizhixin.com/articles/agent-platform",
                },
                {
                    "title": "企业级智能体评测进入落地期",
                    "snippet": "评测、工具调用和企业部署加速。",
                    "url": "https://www.jiqizhixin.com/articles/agent-eval",
                },
                {
                    "title": "编程 Agent 与代码库检索新趋势",
                    "snippet": "多文件修改和仓库级检索继续升温。",
                    "url": "https://www.jiqizhixin.com/articles/coding-agent",
                },
                {
                    "title": "办公 Agent 的企业应用边界",
                    "snippet": "企业办公和任务执行场景的新案例。",
                    "url": "https://www.jiqizhixin.com/articles/office-agent",
                },
                {
                    "title": "多模态助手正在切入生产力场景",
                    "snippet": "搜索、文档和工作流场景的新信号。",
                    "url": "https://www.jiqizhixin.com/articles/productivity-agent",
                },
                {
                    "title": "具身智能机器人量产与融资进入新阶段",
                    "snippet": "机器人、硬件量产和产业协同的市场价值继续抬升。",
                    "url": "https://www.jiqizhixin.com/articles/robotics-expansion",
                },
                {
                    "title": "低价值泛资讯",
                    "snippet": "一篇相关度更低的泛资讯文章。",
                    "url": "https://www.jiqizhixin.com/articles/low-value",
                },
            ]
        if "site:qbitai.com" in query:
            return [
                {
                    "title": "量子位 编程 agent 新进展",
                    "snippet": "过去 24 小时关于编程 agent 和代码智能体的跟踪文章。",
                    "url": "https://www.qbitai.com/articles/coding-agent",
                }
            ]
        if "site:36kr.com" in query:
            return [
                {
                    "title": "36氪 AI 应用市场动态",
                    "snippet": "最近 24 小时 AI 应用工程化与企业服务相关文章。",
                    "url": "https://36kr.com/p/agent-market",
                }
            ]
        return []


class SparseMarketWebPageClient(FakeWebPageClient):
    """Simulate market article fetch failures so title-only fallback must create real child cards."""

    def fetch(self, url: str) -> WebPageExtractionResult:
        if url.endswith("/articles/agent-platform") or url.endswith("/articles/agent-eval"):
            return super().fetch(url)
        if "jiqizhixin.com/articles/" in url:
            raise RuntimeError("正文抓取失败")
        return super().fetch(url)


class SparseMarketSearchClient(FakeSearchClient):
    """Search client that returns title-only market candidates without snippets."""

    def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
        results = super().search(query=query, limit=limit)
        if "site:jiqizhixin.com" not in query:
            return results
        sparse_results: list[dict[str, str | None]] = []
        for index, result in enumerate(results):
            sparse_results.append(
                {
                    **result,
                    "snippet": None if index >= 2 else result.get("snippet"),
                }
            )
        return sparse_results


def test_ingest_link_fetches_page_text_when_raw_text_missing() -> None:
    """Link ingest should fetch real page text when no override text is provided."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
        )
    )

    result = services.ingest_link(
        url="https://example.com/posting",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert result.normalized_item is not None
    assert result.normalized_item.source_metadata["page_title"] == "阿里云校园招聘"
    assert "后端工程师" in result.normalized_item.raw_content


def test_ingest_image_file_runs_ocr_before_workflow(tmp_path, monkeypatch) -> None:
    """Image ingest should store the upload and run OCR before the workflow."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            ocr_client=FakeOCRClient(),
        )
    )

    result = services.ingest_image_file(
        file_name="wechat-shot.png",
        file_bytes=b"fake-image-bytes",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert result.normalized_item is not None
    assert result.normalized_item.source_metadata["ocr_engine"] == "fake_ocr"
    assert "面试时间" in result.normalized_item.raw_content


def test_ingest_auto_detects_mixed_content_and_fetches_link() -> None:
    """Unified ingest should detect mixed content, visit the link, and keep context."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
        )
    )

    analysis, states = services.ingest_auto(
        content="这是我比较关注的一条后端岗位 https://example.com/posting",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert analysis.input_kind == "mixed"
    assert analysis.should_visit_links is True
    assert states
    assert states[0].normalized_item is not None
    assert states[0].normalized_item.source_metadata["detected_input_kind"] == "mixed"
    assert "共享上下文" not in states[0].normalized_item.raw_content
    assert states[0].normalized_item.source_metadata["shared_context"] == "这是我比较关注的一条后端岗位"
    assert states[0].normalized_item.source_metadata["fetch_plan"]


def test_ingest_auto_fetches_pure_link_even_for_non_whitelisted_domain() -> None:
    """Pure-link submissions should proactively fetch the page before analysis."""

    web_client = FakeWebPageClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=web_client,
        )
    )

    analysis, states = services.ingest_auto(
        content="https://mp.weixin.qq.com/s/demo",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert analysis.input_kind == "link"
    assert analysis.should_visit_links is True
    assert web_client.calls == ["https://mp.weixin.qq.com/s/demo"]
    assert states[0].normalized_item is not None
    assert states[0].normalized_item.source_title == "滴滴-2026届春季校招"
    assert "滴滴" in states[0].normalized_item.raw_content


def test_ingest_auto_fetches_sparse_context_link_before_analysis() -> None:
    """Very short surrounding text should still trigger proactive link fetching."""

    web_client = FakeWebPageClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=web_client,
        )
    )

    analysis, states = services.ingest_auto(
        content="看看 https://mp.weixin.qq.com/s/demo",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert analysis.input_kind == "mixed"
    assert analysis.should_visit_links is True
    assert web_client.calls == ["https://mp.weixin.qq.com/s/demo"]
    assert states[0].normalized_item is not None
    assert states[0].normalized_item.source_title == "滴滴-2026届春季校招"
    assert states[0].source_metadata.get("visited_urls") == ["https://mp.weixin.qq.com/s/demo"]


def test_ingest_auto_can_attach_explicit_search_references() -> None:
    """When the user explicitly asks to search, the search results should feed later analysis."""

    search_client = FakeSearchClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=search_client,
        )
    )

    _, states = services.ingest_auto(
        content="请在网页上搜索有关内容，帮我看看滴滴 AI agent 工程化岗位方向",
        user_id="demo_user",
        workspace_id="demo_workspace",
        visit_links=False,
    )

    assert search_client.queries
    assert states[0].normalized_item is not None
    assert "搜索参考：" in states[0].normalized_item.raw_content
    assert states[0].source_metadata.get("search_references")


def test_refresh_market_watch_creates_market_cards() -> None:
    """Market refresh should create market-signal cards and update the refresh timestamp."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    refreshed, reason, states, last_market_refresh_at = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        input_link="https://mp.weixin.qq.com/s/demo",
        force=True,
    )

    assert refreshed is True
    assert reason
    assert states
    assert last_market_refresh_at is not None
    assert states[0].render_card is not None
    assert states[0].render_card.is_market_signal is True
    assert states[0].render_card.content_category.value == "general_update"
    assert states[0].render_card.ai_score is not None
    assert states[0].render_card.advice is not None
    assert states[0].render_card.message_time is not None


def test_refresh_market_watch_searches_recent_articles_from_configured_sources(
    tmp_path, monkeypatch
) -> None:
    """Scheduled market refresh should build overview cards plus top-ranked child articles."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={"market_watch_sources": ["https://www.jiqizhixin.com/"]}
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    assert len(states) == 6
    overview_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "overview"
    ]
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(overview_states) == 1
    assert len(article_states) == 5
    overview_card = overview_states[0].render_card
    assert overview_card is not None
    assert overview_card.market_child_item_ids
    assert len(overview_card.market_child_item_ids) == 5
    assert len(overview_card.market_child_previews) == 5
    assert overview_card.ai_score is not None
    assert all(state.render_card and state.render_card.message_time is not None for state in article_states)
    assert all(
        state.render_card
        and state.render_card.summary_one_line == state.source_metadata.get("market_article_title")
        for state in article_states
    )
    assert all(
        state.render_card and state.render_card.market_parent_item_id == overview_card.item_id
        for state in article_states
    )
    assert all(
        state.source_metadata.get("market_article_title")
        for state in article_states
    )


def test_refresh_market_watch_keeps_one_high_value_exploration_article(
    tmp_path, monkeypatch
) -> None:
    """Title selection should reserve one valuable exploration article beyond the tightest profile match."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={
            "market_watch_sources": ["https://www.jiqizhixin.com/"],
            "market_article_fetch_limit": 4,
        }
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(article_states) == 4
    assert any(
        state.source_metadata.get("market_title_selection_mode") == "keyword_exploration"
        for state in article_states
    )
    assert any(
        "具身智能机器人量产与融资进入新阶段"
        in str(state.source_metadata.get("market_article_title") or "")
        for state in article_states
    )


def test_refresh_market_watch_keeps_real_child_cards_when_only_titles_are_available(
    tmp_path, monkeypatch
) -> None:
    """Title-only market candidates should still become persisted child cards instead of preview-only ghosts."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=SparseMarketWebPageClient(),
            search_client=SparseMarketSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={"market_watch_sources": ["https://www.jiqizhixin.com/"]}
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    overview_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "overview"
    ]
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(overview_states) == 1
    assert len(article_states) == 5
    assert all(state.render_card and state.render_card.item_id for state in article_states)
    assert all(
        state.render_card and state.render_card.summary_one_line for state in article_states
    )


def test_list_items_repairs_old_market_child_titles_and_parent_previews(tmp_path, monkeypatch) -> None:
    """Older persisted market cards should be repaired to use explicit article titles when listed."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={"market_watch_sources": ["https://www.jiqizhixin.com/"]}
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    overview = next(
        state for state in states if state.render_card and state.render_card.market_group_kind == "overview"
    )
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert article_states

    broken_title = "机器之心推出数据服务，强调高效稳定数据获取能力，提及华为云合作背书"
    for article_state in article_states:
        article_state.render_card.summary_one_line = broken_title
        if article_state.extracted_signal is not None:
            article_state.extracted_signal.summary_one_line = broken_title
        services.dependencies.workflow_repository.save(article_state)

    overview.render_card.market_child_previews = [broken_title] * len(article_states)
    overview.source_metadata["market_child_previews"] = [broken_title] * len(article_states)
    services.dependencies.workflow_repository.save(overview)

    repaired_states = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    repaired_articles = [
        state for state in repaired_states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    repaired_overview = next(
        state
        for state in repaired_states
        if state.render_card and state.render_card.market_group_kind == "overview"
    )

    assert all(
        state.render_card and state.render_card.summary_one_line == state.source_metadata.get("market_article_title")
        for state in repaired_articles
    )
    assert repaired_overview.render_card is not None
    assert broken_title not in repaired_overview.render_card.market_child_previews


def test_refresh_market_watch_prefers_qbitai_site_level_title_discovery(
    tmp_path, monkeypatch
) -> None:
    """Qbitai should use direct recent-title discovery before falling back to search results."""

    monkeypatch.chdir(tmp_path)

    class FailingQbitaiSearchClient(FakeSearchClient):
        def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
            if "site:qbitai.com" in query:
                raise RuntimeError("qbitai generic search should not be needed")
            return super().search(query=query, limit=limit)

    def fake_recent_titles(site_url: str, **kwargs):  # noqa: ANN001
        assert "qbitai.com" in site_url
        return [
            RecentArticleTitle(
                title="量子位站点级标题 1",
                url="https://www.qbitai.com/2026/04/qa-1.html",
                published_at="2099-04-23T08:00:00+08:00",
                discovery_source="homepage",
            ),
            RecentArticleTitle(
                title="量子位站点级标题 2",
                url="https://www.qbitai.com/2026/04/qa-2.html",
                published_at="2099-04-23T07:00:00+08:00",
                discovery_source="homepage",
            ),
        ]

    monkeypatch.setattr(services_module, "fetch_recent_site_titles", fake_recent_titles)

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FailingQbitaiSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={
            "market_watch_sources": ["https://www.qbitai.com/"],
            "market_article_fetch_limit": 2,
        }
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(article_states) == 2
    assert all(
        str(state.source_metadata.get("market_candidate_source") or "").startswith("site_recent_titles:")
        for state in article_states
    )


def test_refresh_market_watch_uses_jiqizhixin_search_adapter(
    tmp_path, monkeypatch
) -> None:
    """Jiqizhixin should use its dedicated search adapter when direct site discovery is not viable."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(services_module, "fetch_recent_site_titles", lambda *args, **kwargs: [])
    search_client = FakeSearchClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=search_client,
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={
            "market_watch_sources": ["https://www.jiqizhixin.com/"],
            "market_article_fetch_limit": 2,
        }
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(article_states) == 2
    assert all(
        state.source_metadata.get("market_candidate_source") == "search_adapter:jiqizhixin"
        for state in article_states
    )
    assert any("site:jiqizhixin.com/articles" in query for query in search_client.queries)


def test_refresh_market_watch_prefers_jiqizhixin_site_level_title_discovery(
    tmp_path, monkeypatch
) -> None:
    """Jiqizhixin should use direct recent-title discovery when its verified API yields fresh titles."""

    monkeypatch.chdir(tmp_path)

    def fake_recent_titles(site_url: str, **kwargs):  # noqa: ANN001
        assert "jiqizhixin.com" in site_url
        return [
            RecentArticleTitle(
                title="机器之心站点级标题 1",
                url="https://www.jiqizhixin.com/articles/fresh-agent-article",
                published_at="2099-04-23T08:00:00+08:00",
                discovery_source="jiqizhixin_article_library_api",
                snippet="Agent 平台、评测和工具链正在持续落地。",
            ),
            RecentArticleTitle(
                title="机器之心站点级标题 2",
                url="https://www.jiqizhixin.com/articles/fresh-eval-article",
                published_at="2099-04-23T07:00:00+08:00",
                discovery_source="jiqizhixin_article_library_api",
                snippet="评测体系与工程化部署仍是重要方向。",
            ),
        ]

    monkeypatch.setattr(services_module, "fetch_recent_site_titles", fake_recent_titles)

    class FailingJiqizhixinSearchClient(FakeSearchClient):
        def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
            if "jiqizhixin.com" in query:
                raise RuntimeError("jiqizhixin search should not be needed")
            return super().search(query=query, limit=limit)

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FailingJiqizhixinSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={
            "market_watch_sources": ["https://www.jiqizhixin.com/"],
            "market_article_fetch_limit": 2,
        }
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(article_states) == 2
    assert all(
        str(state.source_metadata.get("market_candidate_source") or "").startswith("site_recent_titles:")
        for state in article_states
    )


def test_refresh_market_watch_uses_candidate_snippet_when_jiqizhixin_detail_is_blocked(
    tmp_path, monkeypatch
) -> None:
    """When Jiqizhixin detail pages are blocked, article-library snippets should still form child cards."""

    monkeypatch.chdir(tmp_path)

    def fake_recent_titles(site_url: str, **kwargs):  # noqa: ANN001
        assert "jiqizhixin.com" in site_url
        return [
            RecentArticleTitle(
                title="机器之心文章库标题",
                url="https://www.jiqizhixin.com/articles/fresh-agent-article",
                published_at="2099-04-23T08:00:00+08:00",
                discovery_source="jiqizhixin_article_library_api",
                snippet="Agent 平台、RAG 和评测工具链仍在加速落地。",
            )
        ]

    class BlockingJiqizhixinWebClient(FakeWebPageClient):
        def fetch(self, url: str) -> WebPageExtractionResult:
            if "jiqizhixin.com/articles/" in url:
                raise RuntimeError("detail page blocked")
            return super().fetch(url)

    monkeypatch.setattr(services_module, "fetch_recent_site_titles", fake_recent_titles)

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=BlockingJiqizhixinWebClient(),
            search_client=FakeSearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={
            "market_watch_sources": ["https://www.jiqizhixin.com/"],
            "market_article_fetch_limit": 1,
        }
    )
    services.upsert_career_state_memory(career_state)

    refreshed, _, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    article_states = [
        state for state in states if state.render_card and state.render_card.market_group_kind == "article"
    ]
    assert len(article_states) == 1
    assert article_states[0].source_metadata.get("fetch_method") == "market_candidate_snippet_fallback"
    assert article_states[0].source_metadata.get("market_article_snippet") == "Agent 平台、RAG 和评测工具链仍在加速落地。"


def test_refresh_market_watch_falls_back_to_source_homepage_when_search_is_empty(
    tmp_path, monkeypatch
) -> None:
    """When title search finds nothing, market refresh should still analyze the source homepage."""

    monkeypatch.chdir(tmp_path)

    class EmptySearchClient:
        def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
            return []

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=EmptySearchClient(),
        )
    )

    memory_payload = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    career_state = memory_payload["career_state_memory"].model_copy(
        update={"market_watch_sources": ["https://unknown.example.com/market"]}
    )
    services.upsert_career_state_memory(career_state)

    refreshed, reason, states, _ = services.refresh_market_watch(
        user_id="demo_user",
        workspace_id="demo_workspace",
        force=True,
    )

    assert refreshed is True
    assert reason
    assert len(states) == 1
    assert states[0].render_card is not None
    assert states[0].render_card.market_group_kind == "overview"
    assert states[0].source_metadata.get("market_watch_fallback") == "homepage_fetch"


def test_market_refresh_due_checks_10am_and_9pm_slots() -> None:
    """Scheduled market refresh should be due when the latest 10:00 / 21:00 slot was missed."""

    services = ApiServiceContainer()
    morning_slot = datetime.fromisoformat("2026-04-25T10:00:00+08:00")
    before_evening = datetime.fromisoformat("2026-04-25T20:30:00+08:00")
    evening_slot = datetime.fromisoformat("2026-04-25T21:00:00+08:00")
    next_morning = datetime.fromisoformat("2026-04-26T09:30:00+08:00")

    assert services._market_refresh_due(None, before_evening) is True
    assert services._market_refresh_due(
        datetime.fromisoformat("2026-04-25T09:55:00+08:00"),
        before_evening,
    ) is True
    assert services._market_refresh_due(
        datetime.fromisoformat("2026-04-25T10:05:00+08:00"),
        before_evening,
    ) is False
    assert services._market_refresh_due(
        datetime.fromisoformat("2026-04-25T21:05:00+08:00"),
        next_morning,
    ) is False
    assert services._market_refresh_due(morning_slot, evening_slot) is True


def test_ingest_auto_splits_multi_section_submission_into_multiple_cards(tmp_path, monkeypatch) -> None:
    """Multi-position recruiting collections should split into multiple item cards."""

    monkeypatch.chdir(tmp_path)
    web_client = FakeWebPageClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=web_client,
            search_client=FakeSearchClient(),
        )
    )

    content = """
⏰阿里系笔试提醒
❗️最晚要在终面前完成笔试
📅 剩余笔试时间安排：2099年05月07日、2099年05月08日

1️⃣【阿里云 暑期实习】
仅可内推阿里云的岗位
🔗内推链接：https://alibaba.example.com/aliyun

2⃣🔥【淘宝闪购 暑期实习】
仅可内推淘宝闪购的岗位
岗位上新①算法工程师-生成器式方向
②数据研发工程师
🔗 内推链接：https://alibaba.example.com/taobao

3⃣【27届校招实习秋招内推信息汇总】
https://docs.qq.com/smartsheet/demo
""".strip()

    analysis, states = services.ingest_auto(
        content=content,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert analysis.input_kind == "mixed"
    assert len(states) == 4
    titles = [state.normalized_item.source_title for state in states if state.normalized_item]
    assert any(title and "阿里系-暑期实习-阿里云" in title for title in titles)
    assert any(title and "淘宝闪购-算法工程师-生成器式方向" in title for title in titles)
    assert any(title and "淘宝闪购-数据研发工程师" in title for title in titles)
    assert any(title and title == "阿里系-暑期实习-淘宝闪购" for title in titles)
    assert all(state.extracted_signal is not None for state in states)
    assert any("阿里系-暑期实习-淘宝闪购" in state.extracted_signal.tags for state in states)
    assert all("共享规则：" in (state.normalized_item.raw_content if state.normalized_item else "") for state in states)
    assert all("关键词提示：" in (state.normalized_item.raw_content if state.normalized_item else "") for state in states)
    assert all(state.extracted_signal and state.extracted_signal.ddl is not None for state in states)
    assert all(
        state.extracted_signal and state.extracted_signal.ddl and state.extracted_signal.ddl.year == 2099
        for state in states
    )
    assert all(
        state.source_metadata.get("job_group_kind") == "overview"
        or state.source_metadata.get("fetch_plan")
        for state in states
    )
    overview_state = next(
        state for state in states if state.source_metadata.get("job_group_kind") == "overview"
    )
    child_states = [
        state for state in states if state.source_metadata.get("job_group_kind") == "role"
    ]
    assert len(child_states) == 2
    assert overview_state.source_metadata.get("job_child_item_ids")
    assert overview_state.render_card is not None
    assert overview_state.render_card.job_group_kind == "overview"
    assert len(overview_state.render_card.job_child_item_ids) == 2
    assert all(
        child.source_metadata.get("job_parent_item_id") == overview_state.normalized_item.id
        for child in child_states
        if child.normalized_item is not None
    )
    stored_items = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    assert len(stored_items) == 4
    assert "https://docs.qq.com/smartsheet/demo" not in web_client.calls


def test_ingest_auto_derives_platform_neutral_relationship_tags(tmp_path, monkeypatch) -> None:
    """Company-group relationship tags should work beyond Alibaba-specific inputs."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    content = """
⏰字节系笔试提醒
📅 剩余笔试时间安排：2099年06月01日、2099年06月08日

1️⃣【抖音电商 暑期实习】
仅可投递抖音电商的岗位
①算法工程师
②数据研发工程师
""".strip()

    _, states = services.ingest_auto(
        content=content,
        user_id="demo_user",
        workspace_id="demo_workspace",
        visit_links=False,
    )

    assert len(states) == 3
    assert all(state.normalized_item is not None for state in states)
    assert any(
        state.normalized_item
        and state.normalized_item.source_title
        and "字节系-暑期实习-抖音电商" in state.normalized_item.source_title
        for state in states
    )
    role_states = [state for state in states if state.source_metadata.get("job_group_kind") == "role"]
    overview_state = next(
        state for state in states if state.source_metadata.get("job_group_kind") == "overview"
    )
    assert len(role_states) == 2
    assert all(state.source_metadata.get("identity_tag") == "字节系-暑期实习-抖音电商" for state in states)
    assert all("抖音电商" in state.source_metadata.get("keyword_hints", []) for state in states)
    assert overview_state.render_card is not None
    assert overview_state.render_card.job_group_kind == "overview"


def test_ingest_auto_marks_location_pending_when_city_is_missing(tmp_path, monkeypatch) -> None:
    """When no explicit city is found, cards should explain that location is pending."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    content = """
⏰阿里系笔试提醒
📅 剩余笔试时间安排：2026年05月01日、2026年05月08日

1️⃣【阿里云 暑期实习】
仅可内推阿里云的岗位
投递后地点待确认
🔗内推链接：https://alibaba.example.com/unknown-role
""".strip()

    _, states = services.ingest_auto(
        content=content,
        user_id="demo_user",
        workspace_id="demo_workspace",
        visit_links=False,
    )

    assert len(states) == 1
    assert states[0].render_card is not None
    assert states[0].render_card.location_note is not None
    assert "待识别" in states[0].render_card.location_note


def test_ingest_auto_uses_profile_guided_theme_detection_to_expand_company_keywords(
    tmp_path, monkeypatch
) -> None:
    """Profile focus should help recognize a topic head before expanding company keywords."""

    monkeypatch.chdir(tmp_path)
    search_client = FakeSearchClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=search_client,
        )
    )

    content = """
#自动驾驶相关
1️⃣🔥【滴滴 27届暑期实习预投递】
🔗内推链接：https://example.com/didi

2⃣地平线实习
【内推链接】https://example.com/horizon

3⃣【蔚来 自动驾驶暑期实习】
内推链接🔗: https://example.com/nio
""".strip()

    _, states = services.ingest_auto(
        content=content,
        user_id="demo_user",
        workspace_id="demo_workspace",
        visit_links=False,
    )

    assert len(states) == 3
    titles = [state.normalized_item.source_title for state in states if state.normalized_item]
    assert any(title and "滴滴" in title for title in titles)
    assert any(title and "地平线" in title for title in titles)
    assert any(title and "蔚来" in title for title in titles)
    assert all("自动驾驶" in state.source_metadata.get("keyword_hints", []) for state in states)
    assert all(
        any(company in state.source_metadata.get("keyword_hints", []) for company in ("滴滴", "地平线", "蔚来"))
        for state in states
    )
    assert any("自动驾驶" in query for query in search_client.queries)


def test_ingest_auto_builds_meaningful_card_for_unstructured_campaign_bulletin(
    tmp_path, monkeypatch
) -> None:
    """A single recruiting bulletin should still become a meaningful campaign card."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            web_page_client=FakeWebPageClient(),
            search_client=FakeSearchClient(),
        )
    )

    content = """
滴滴2026届春季校招正式启动啦！
岗位类别
工程/算法/机器人/数据/安全技术/效能管理/产品/商业分析/金融业务/运营/专业职能
面向人群
2025年9月~2026年8月之间毕业的海内外高校毕业生
投递规则
每位同学每次可投递1个职位，该职位流程结束可再次投递新职位，每位同学全渠道共3次主动投递机会；
工作地点
北京/杭州/上海/广州等
招聘流程
简历投递（3月2日起，岗位招满即下线，建议尽早投递）-在线笔试（3月8日起，部分岗位需要）-面试（3月初起）-Offer发放（3月中旬起）
投递方式
登录滴滴校招官网/滴滴招聘公众号一键投递
校招官网：campus.didiglobal.com
""".strip()

    analysis, states = services.ingest_auto(
        content=content,
        user_id="demo_user",
        workspace_id="demo_workspace",
        visit_links=False,
    )

    assert len(states) == 1
    assert analysis.keyword_hints
    assert states[0].normalized_item is not None
    assert states[0].normalized_item.source_title == "滴滴-2026届春季校招"
    assert states[0].extracted_signal is not None
    assert states[0].extracted_signal.company == "滴滴"
    assert states[0].extracted_signal.role == "2026届春季校招"
    assert states[0].source_ref == "https://campus.didiglobal.com"
    assert "统一输入卡片" not in states[0].normalized_item.raw_content
