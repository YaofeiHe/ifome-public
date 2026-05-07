"""Tests for Phase 13 Boss 直聘 minimal connector paths."""

from __future__ import annotations

from types import SimpleNamespace

from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.runtime.time import now_in_project_timezone
from core.tools import NoopLLMGateway
from integrations.boss_zhipin import (
    BossMCPReadOnlyError,
    BossZhipinMCPReadOnlyClient,
    BossZhipinConversationMessage,
    BossZhipinConversationPayload,
    BossZhipinJobPayload,
    search_envelope_to_job_payloads,
    search_item_to_job_payload,
)


def test_ingest_boss_job_routes_payload_into_shared_workflow(tmp_path) -> None:
    """Boss 直聘岗位 payload should become a normal workflow item."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    result = services.ingest_boss_job(
        payload=BossZhipinJobPayload(
            job_id="job_001",
            job_url="https://www.zhipin.com/job_detail/123.html",
            company_name="阿里云",
            role_title="后端工程师",
            city="上海",
            apply_deadline=now_in_project_timezone().replace(month=5, day=1, hour=18, minute=0),
            job_description="负责 Agent 平台后端开发，要求 Python、FastAPI、RAG 经验。",
            tags=["校招", "后端", "AI"],
            hr_name="张三",
        ),
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert result.normalized_item is not None
    assert result.normalized_item.source_metadata["connector"] == "boss_zhipin"
    assert result.normalized_item.source_metadata["connector_entity"] == "job_posting"
    assert "来源平台：Boss直聘" in result.raw_input
    assert result.render_card is not None


def test_ingest_boss_conversation_routes_thread_into_shared_workflow() -> None:
    """Boss 直聘对话 payload should become a normal workflow item."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    result = services.ingest_boss_conversation(
        payload=BossZhipinConversationPayload(
            thread_id="thread_001",
            job_id="job_001",
            job_url="https://www.zhipin.com/job_detail/123.html",
            company_name="阿里云",
            role_title="后端工程师",
            city="上海",
            hr_name="张三",
            messages=[
                BossZhipinConversationMessage(
                    sender_role="hr",
                    text="你好，想和你约一下面试，时间是 2026年04月24日 15:30。",
                    sent_at=now_in_project_timezone(),
                ),
                BossZhipinConversationMessage(
                    sender_role="candidate",
                    text="可以，我这边有时间。",
                    sent_at=now_in_project_timezone(),
                ),
            ],
        ),
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert result.normalized_item is not None
    assert result.normalized_item.source_metadata["connector_entity"] == "conversation"
    assert result.normalized_item.source_metadata["message_count"] == 2
    assert "内容类型：HR对话" in result.raw_input


def test_boss_mcp_readonly_client_blocks_write_tools() -> None:
    """The MCP boundary must reject chat, greet, apply, resume, and HR write tools."""

    client = BossZhipinMCPReadOnlyClient()

    try:
        client.call_tool("boss_greet", {"security_id": "sid", "job_id": "jid"})
    except BossMCPReadOnlyError as exc:
        assert "not allowed in read-only mode" in str(exc)
    else:
        raise AssertionError("boss_greet should be blocked by the read-only MCP client")


def test_search_item_to_job_payload_preserves_boss_search_fields() -> None:
    """Boss search rows should become the existing connector job payload shape."""

    payload = search_item_to_job_payload(
        {
            "job_id": "job_001",
            "title": "AI Agent开发实习生",
            "company": "字节跳动",
            "salary": "490-500元/天",
            "city": "上海",
            "district": "浦东新区",
            "experience": "在校/应届",
            "education": "本科",
            "skills": ["Python", "RAG", "LLM"],
            "welfare": ["五险一金"],
            "industry": "互联网",
            "boss_name": "徐先生",
            "boss_title": "HR",
            "security_id": "security_001",
        }
    )

    assert payload.job_id == "job_001"
    assert payload.company_name == "字节跳动"
    assert payload.role_title == "AI Agent开发实习生"
    assert payload.city == "上海 浦东新区"
    assert payload.salary_range == "490-500元/天"
    assert "Python" in payload.tags
    assert "Boss security_id：security_001" in payload.job_description


def test_search_envelope_to_job_payloads_rejects_failed_envelope() -> None:
    """Failed Boss envelopes should not silently write empty data into ifome."""

    try:
        search_envelope_to_job_payloads(
            {
                "ok": False,
                "error": {"message": "未登录，请先执行 boss login"},
            }
        )
    except BossMCPReadOnlyError as exc:
        assert "未登录" in str(exc)
    else:
        raise AssertionError("failed Boss search envelopes should raise")


def test_ingest_boss_search_readonly_routes_mcp_results_into_workflow(monkeypatch) -> None:
    """Read-only MCP search should write normal ifome cards without long-term memory writes."""

    class FakeBossMCPClient:
        allowed_tools = frozenset({"boss_status", "boss_search", "boss_detail", "boss_cities"})

        def __init__(self, command: str) -> None:
            self.command = command

        def search_jobs(self, **kwargs):
            assert kwargs["query"] == "AI Agent"
            return {
                "ok": True,
                "data": [
                    {
                        "job_id": "job_002",
                        "title": "AI Agent工程师",
                        "company": "测试科技",
                        "salary": "20-30K",
                        "city": "上海",
                        "experience": "1-3年",
                        "education": "本科",
                        "skills": ["Python", "FastAPI"],
                        "boss_name": "李女士",
                    }
                ],
                "pagination": {"page": 1, "has_more": False, "total": 1},
            }

    monkeypatch.setattr(
        "apps.api.src.services.BossZhipinMCPReadOnlyClient",
        FakeBossMCPClient,
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._resolve_boss_mcp_command",
        lambda self: "boss-mcp",
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._boss_cli_json",
        lambda self, *args, **kwargs: {"ok": True, "data": {"logged_in": True}, "error": None},
    )

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    result = services.ingest_boss_search_readonly(
        query="AI Agent",
        city="上海",
        salary=None,
        experience=None,
        education=None,
        page=1,
        max_items=5,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert result["ingested_count"] == 1
    assert result["memory_write_mode"] == "context_only"
    assert result["boss_pagination"]["total"] == 1
    assert result["item_ids"]


def test_unified_input_boss_search_instruction_groups_results_by_company(tmp_path, monkeypatch) -> None:
    """A natural-language Boss search request should create company overviews with role children."""

    monkeypatch.chdir(tmp_path)

    class FakeBossMCPClient:
        allowed_tools = frozenset({"boss_status", "boss_search", "boss_detail", "boss_cities"})

        def __init__(self, command: str) -> None:
            self.command = command

        def search_jobs(self, **kwargs):
            query = kwargs["query"]
            if query == "AI 应用后端":
                rows = [
                    {
                        "job_id": "job_backend",
                        "title": "AI 应用后端工程师",
                        "company": "测试科技",
                        "salary": "20-30K",
                        "city": "上海",
                        "experience": "1-3年",
                        "education": "本科",
                        "skills": ["Python", "FastAPI"],
                        "boss_name": "李女士",
                    }
                ]
            elif query == "智能体平台":
                rows = [
                    {
                        "job_id": "job_agent_platform",
                        "title": "智能体平台工程师",
                        "company": "测试科技",
                        "salary": "25-35K",
                        "city": "上海",
                        "experience": "3-5年",
                        "education": "本科",
                        "skills": ["Agent", "RAG"],
                        "boss_name": "王先生",
                    },
                    {
                        "job_id": "job_eval",
                        "title": "数据与评测工程师",
                        "company": "评测智能",
                        "salary": "18-28K",
                        "city": "杭州",
                        "experience": "1-3年",
                        "education": "本科",
                        "skills": ["评测", "LLM"],
                        "boss_name": "赵女士",
                    },
                ]
            else:
                rows = []
            return {
                "ok": True,
                "data": rows,
                "pagination": {"page": 1, "has_more": False, "total": len(rows)},
            }

    monkeypatch.setattr(
        "apps.api.src.services.BossZhipinMCPReadOnlyClient",
        FakeBossMCPClient,
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._resolve_boss_mcp_command",
        lambda self: "boss-mcp",
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._boss_cli_json",
        lambda self, *args, **kwargs: {"ok": True, "data": {"logged_in": True}, "error": None},
    )

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    analysis, states, attachments, resolved_paths = services.ingest_unified(
        content="请搜索boss直聘中有关关键词“AI 应用后端 / 智能体平台”的有关的内容",
        uploaded_files=[],
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert analysis.input_kind == "boss_search_instruction"
    assert analysis.keyword_hints == ["AI 应用后端", "智能体平台"]
    assert attachments == []
    assert resolved_paths == []
    assert len(states) == 5

    stored = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    overview_states = [
        state for state in stored if state.render_card and state.render_card.job_group_kind == "overview"
    ]
    role_states = [
        state for state in stored if state.render_card and state.render_card.job_group_kind == "role"
    ]
    assert len(overview_states) == 2
    assert len(role_states) == 3

    test_company_overview = next(
        state
        for state in overview_states
        if state.render_card and state.render_card.company == "测试科技"
    )
    assert test_company_overview.render_card is not None
    assert test_company_overview.render_card.summary_one_line == "测试科技（2个岗位）"
    assert len(test_company_overview.render_card.job_child_item_ids) == 2
    assert "AI 应用后端" in test_company_overview.render_card.tags
    assert all(
        state.render_card
        and state.render_card.job_parent_item_id == test_company_overview.normalized_item.id
        for state in role_states
        if state.render_card and state.render_card.company == "测试科技"
    )


def test_boss_search_instruction_stops_on_risk_control_without_bypass_hint(tmp_path, monkeypatch) -> None:
    """Boss risk-control messages should stop the workflow without surfacing bypass guidance."""

    monkeypatch.chdir(tmp_path)

    class FakeBossMCPClient:
        allowed_tools = frozenset({"boss_status", "boss_search", "boss_detail", "boss_cities"})

        def __init__(self, command: str) -> None:
            self.command = command

        def search_jobs(self, **kwargs):
            return {
                "ok": False,
                "error": {
                    "message": "BOSS 直聘风控拦截：建议使用 CDP 模式规避风控检测",
                },
            }

    monkeypatch.setattr(
        "apps.api.src.services.BossZhipinMCPReadOnlyClient",
        FakeBossMCPClient,
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._resolve_boss_mcp_command",
        lambda self: "boss-mcp",
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._boss_cli_json",
        lambda self, *args, **kwargs: {"ok": True, "data": {"logged_in": True}, "error": None},
    )
    monkeypatch.setattr(
        "apps.api.src.services.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    try:
        services.ingest_unified(
            content="请搜索boss直聘中有关关键词“AI 应用后端”的有关的内容",
            uploaded_files=[],
            user_id="demo_user",
            workspace_id="demo_workspace",
        )
    except BossMCPReadOnlyError as exc:
        message = str(exc)
        assert "已停止只读搜索" in message
        assert "绕过" in message
        assert "规避" not in message
        assert "CDP" not in message
    else:
        raise AssertionError("Boss risk-control errors should stop the search workflow")


def test_boss_search_instruction_triggers_login_recovery_once(tmp_path, monkeypatch) -> None:
    """Boss risk-control should clear stale auth and launch login only once per cycle."""

    monkeypatch.chdir(tmp_path)
    launches: list[tuple[str, list[str]]] = []

    class FakeBossMCPClient:
        allowed_tools = frozenset({"boss_status", "boss_search", "boss_detail", "boss_cities"})

        def __init__(self, command: str) -> None:
            self.command = command

        def search_jobs(self, **kwargs):
            return {
                "ok": False,
                "error": {
                    "message": "BOSS 直聘风控拦截：需要人工验证后再试",
                },
            }

    monkeypatch.setattr(
        "apps.api.src.services.BossZhipinMCPReadOnlyClient",
        FakeBossMCPClient,
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._resolve_boss_mcp_command",
        lambda self: "boss-mcp",
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._boss_cli_json",
        lambda self, *args, **kwargs: {"ok": True, "data": {"logged_in": True}, "error": None},
    )

    def fake_run(cmd, **kwargs):
        launches.append(("logout" if "logout" in cmd else "login", list(cmd)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("apps.api.src.services.subprocess.run", fake_run)

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    monkeypatch.setattr(services, "_resolve_boss_cli_command", lambda: "boss")

    try:
        services.ingest_unified(
            content="请搜索boss直聘中有关关键词“AI 应用后端”的有关的内容",
            uploaded_files=[],
            user_id="demo_user",
            workspace_id="demo_workspace",
        )
    except BossMCPReadOnlyError as exc:
        assert "唤起登录界面" in str(exc)
    else:
        raise AssertionError("Boss risk-control errors should trigger login recovery")

    assert launches == [
        ("logout", ["boss", "logout"]),
        ("login", ["boss", "login", "--timeout", "120"]),
    ]


def test_boss_search_instruction_uses_raw_keywords_and_default_small_limit(tmp_path, monkeypatch) -> None:
    """Natural-language Boss search should keep user keywords and conservative batches."""

    monkeypatch.chdir(tmp_path)
    seen_queries: list[str] = []

    class FakeBossMCPClient:
        allowed_tools = frozenset({"boss_status", "boss_search", "boss_detail", "boss_cities"})

        def __init__(self, command: str) -> None:
            self.command = command

        def search_jobs(self, **kwargs):
            seen_queries.append(kwargs["query"])
            return {
                "ok": True,
                "data": [
                    {
                        "job_id": f"job_{len(seen_queries)}_{index}",
                        "title": f"{kwargs['query']} 工程师 {index}",
                        "company": "测试科技",
                        "salary": "20-30K",
                        "city": "杭州",
                        "experience": "1-3年",
                        "education": "本科",
                    }
                    for index in range(3)
                ],
                "pagination": {"page": 1, "has_more": False, "total": 3},
            }

    monkeypatch.setattr(
        "apps.api.src.services.BossZhipinMCPReadOnlyClient",
        FakeBossMCPClient,
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._resolve_boss_mcp_command",
        lambda self: "boss-mcp",
    )
    monkeypatch.setattr(
        "apps.api.src.services.ApiServiceContainer._boss_cli_json",
        lambda self, *args, **kwargs: {"ok": True, "data": {"logged_in": True}, "error": None},
    )
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    analysis, states, _, _ = services.ingest_unified(
        content="请搜索boss直聘中有关关键词“AI 应用后端 / 智能体平台”的有关的内容",
        uploaded_files=[],
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert seen_queries == ["AI 应用后端", "智能体平台"]
    assert analysis.keyword_hints == ["AI 应用后端", "智能体平台"]
    assert "limited Boss search to 2 items per keyword" in analysis.reasons
    assert "no required Boss search keyword" in analysis.reasons
    role_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "role"
    ]
    assert len(role_states) == 4


def test_shutdown_runtime_cleans_boss_login_state_and_requests_exit(monkeypatch) -> None:
    """The shutdown endpoint should clear Boss auth before stopping ifome."""

    calls: list[str] = []

    monkeypatch.setattr(
        "apps.api.src.main.services.cleanup_boss_login_state",
        lambda: calls.append("cleanup"),
    )
    monkeypatch.setattr(
        "apps.api.src.main.os.kill",
        lambda pid, sig: calls.append(f"kill:{pid}:{sig}"),
    )

    from fastapi.testclient import TestClient
    from apps.api.src.main import app

    client = TestClient(app)
    response = client.post("/runtime/shutdown")

    assert response.status_code == 200
    assert calls[0] == "cleanup"
    assert calls[1].startswith("kill:")


def test_unified_ingest_offloads_boss_work_to_threadpool(tmp_path, monkeypatch) -> None:
    """The async unified ingest route should not call the Boss workflow on the event loop."""

    monkeypatch.chdir(tmp_path)

    seen: dict[str, object] = {}

    def fake_ingest_unified(**kwargs):
        import threading

        seen["on_main_thread"] = threading.current_thread() is threading.main_thread()
        seen["kwargs"] = kwargs
        return (
            SimpleNamespace(
                input_kind="boss_search_instruction",
                urls=[],
                should_visit_links=False,
                reasons=["stubbed"],
            ),
            [],
            [],
            [],
        )

    monkeypatch.setattr("apps.api.src.main.services.ingest_unified", fake_ingest_unified)

    from fastapi.testclient import TestClient
    from apps.api.src.main import app

    client = TestClient(app)
    response = client.post(
        "/ingest/unified",
        data={
            "content": "请搜索boss直聘中有关关键词“AI 应用后端 / 智能体平台”的有关的内容",
            "user_id": "demo_user",
            "workspace_id": "demo_workspace",
        },
    )

    assert response.status_code == 200
    assert seen["on_main_thread"] is False
    assert seen["kwargs"]["content"].startswith("请搜索boss直聘")
