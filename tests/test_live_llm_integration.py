"""Tests for the live-LLM-compatible classify and extract path."""

from __future__ import annotations

from apps.api.src.services import ApiServiceContainer
from core.graph import JobWorkflow, create_initial_state
from core.runtime.dependencies import StaticModelRouter, WorkflowDependencies
from core.runtime.settings import AppSettings, FeatureFlags, LLMSettings
from core.schemas import ContentCategory, SourceType


class FakeLLMGateway:
    """Simple deterministic gateway used to verify the live path wiring."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_available(self, route: str) -> bool:
        return True

    def complete_json(
        self,
        *,
        route: str,
        task_name: str,
        system_prompt: str,
        user_payload: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(task_name)
        if task_name == "intake_standardize":
            return {
                "input_kind": "mixed",
                "should_visit_links": True,
                "shared_context_summary": "共享笔试和投递规则",
                "seed_entities": ["阿里系", "淘宝闪购"],
                "relationship_family": "阿里系",
                "relationship_stage": "暑期实习",
                "section_hints": ["淘宝闪购"],
                "reason": "检测到共享规则与岗位片段混合输入。",
            }
        if task_name == "classify":
            return {
                "category": "job_posting",
                "confidence": 0.92,
                "reason": "文本明显是岗位招聘信息。",
            }
        if task_name == "job_title_assessment":
            source_title = str(user_payload.get("source_title") or "")
            return {
                "is_complete_segment": "请分析这个岗位" not in source_title,
                "confidence": 0.91,
                "reason": "标题是否已经包含完整岗位主体信息。",
            }

        return {
            "category": "job_posting",
            "company": "示例科技",
            "role": "AI Agent 工程师",
            "city": "上海",
            "ddl": "2026-05-01T18:00:00+08:00",
            "apply_url": "https://example.com/apply",
            "summary_one_line": "示例科技 - AI Agent 工程师 / 上海",
            "confidence": 0.9,
            "tags": ["上海", "AI Agent 工程师"],
            "evidence": [
                {
                    "field_name": "company",
                    "snippet": "示例科技",
                    "confidence": 0.88,
                }
            ],
        }


class FakeSearchClient:
    """Deterministic search client used to verify prompt-context web lookup."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, *, query: str, limit: int = 5) -> list[dict[str, str | None]]:
        self.queries.append(query)
        return [
            {
                "title": "示例科技 AI Agent 招聘说明",
                "snippet": "示例科技近期在上海招聘 AI Agent 工程师，关注工程化与智能体平台。",
                "url": "https://example.com/sample-agent-role",
            }
        ]


def test_workflow_can_use_live_llm_gateway_when_available() -> None:
    """Ambiguous samples should use the injected live LLM path after the rule precheck."""

    gateway = FakeLLMGateway()
    workflow = JobWorkflow(
        WorkflowDependencies(
            llm_gateway=gateway,
        )
    )
    state = create_initial_state(
        raw_input="请分析这个岗位：示例科技 AI Agent 工程师 上海 2026-05-01 18:00。",
        source_type=SourceType.TEXT,
    )

    result = workflow.run_sequential(state)

    assert result.classified_category == ContentCategory.JOB_POSTING
    assert result.extracted_signal is not None
    assert result.extracted_signal.company == "示例科技"
    assert result.extracted_signal.role == "AI Agent 工程师"
    assert "classify" in gateway.calls
    assert "extract" in gateway.calls


def test_incomplete_job_title_can_trigger_llm_title_repair() -> None:
    """Job-facing fragment titles should be repaired through the LLM extraction path."""

    gateway = FakeLLMGateway()
    workflow = JobWorkflow(
        WorkflowDependencies(
            llm_gateway=gateway,
        )
    )
    state = create_initial_state(
        raw_input="示例科技 AI Agent 工程师，工作地点上海，投递截止 2026-05-01 18:00。",
        source_type=SourceType.TEXT,
        source_metadata={
            "source_title": "请分析这个岗位",
        },
    )

    result = workflow.run_sequential(state)

    assert result.normalized_item is not None
    assert result.extracted_signal is not None
    assert "job_title_assessment" in gateway.calls
    assert "extract" in gateway.calls
    assert result.normalized_item.source_title == "示例科技 - AI Agent 工程师 / 上海"


def test_rule_first_llm_escalation_can_attach_keyword_search_references() -> None:
    """Ambiguous samples should enrich LLM prompts with keyword-search references."""

    gateway = FakeLLMGateway()
    search_client = FakeSearchClient()
    workflow = JobWorkflow(
        WorkflowDependencies(
            llm_gateway=gateway,
            search_client=search_client,
        )
    )
    state = create_initial_state(
        raw_input="请帮我看看这条消息，示例科技 AI Agent 方向，像不像值得投递？",
        source_type=SourceType.TEXT,
        source_metadata={
            "keyword_hints": ["示例科技", "AI Agent"],
        },
    )

    result = workflow.run_sequential(state)

    assert result.extracted_signal is not None
    assert search_client.queries
    assert any("示例科技" in query for query in search_client.queries)
    assert any(
        reference.get("source_kind") == "keyword_search"
        for reference in result.source_metadata.get("classification_prompt_references", [])
    )
    assert any(
        reference.get("source_kind") == "keyword_search"
        for reference in result.source_metadata.get("extraction_prompt_references", [])
    )


def test_rule_first_workflow_can_skip_live_llm_when_heuristic_is_already_clear() -> None:
    """Very clear recruiting text should stay on the rule-first path."""

    gateway = FakeLLMGateway()
    workflow = JobWorkflow(
        WorkflowDependencies(
            llm_gateway=gateway,
        )
    )
    state = create_initial_state(
        raw_input="阿里云招聘 后端工程师，工作地点上海，投递截止 2026-05-01 18:00。",
        source_type=SourceType.TEXT,
    )

    result = workflow.run_sequential(state)

    assert result.classified_category == ContentCategory.JOB_POSTING
    assert result.extracted_signal is not None
    assert "classify" not in gateway.calls
    assert "extract" not in gateway.calls


def test_model_router_keeps_high_complexity_tasks_off_openai_by_default() -> None:
    """High-complexity routing should stay on DashScope until OpenAI is enabled."""

    router = StaticModelRouter(
        AppSettings(
            feature_flags=FeatureFlags(enable_project_self_memory=False),
            llm=LLMSettings(enable_live_llm=True, enable_openai_routing=False),
        )
    )

    assert router.select("rank", "high") == "dashscope:qwen-primary"


def test_ingest_auto_can_use_prompt_library_for_intake_standardization() -> None:
    """The upload text/link interface should read a prompt from disk for intake standardization."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=FakeLLMGateway(),
        )
    )

    analysis = services.analyze_submission(
        "阿里系笔试提醒 + 淘宝闪购岗位链接 https://example.com/posting"
    )

    assert analysis.input_kind == "mixed"
    assert analysis.should_visit_links is True
    assert any("prompt standardized" in reason for reason in analysis.reasons)
