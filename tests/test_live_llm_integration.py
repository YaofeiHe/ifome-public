"""Tests for the live-LLM-compatible classify and extract path."""

from __future__ import annotations

from apps.api.src.services import ApiServiceContainer
from core.graph import JobWorkflow, create_initial_state
from core.runtime.dependencies import StaticModelRouter, WorkflowDependencies
from core.runtime.settings import AppSettings, FeatureFlags, LLMSettings
from core.schemas import ContentCategory, SourceType


class FakeLLMGateway:
    """Simple deterministic gateway used to verify the live path wiring."""

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


def test_workflow_can_use_live_llm_gateway_when_available() -> None:
    """Workflow should consume the injected live LLM path before heuristics."""

    workflow = JobWorkflow(
        WorkflowDependencies(
            llm_gateway=FakeLLMGateway(),
        )
    )
    state = create_initial_state(
        raw_input="示例科技招聘 AI Agent 工程师，工作地点上海，截止 2026-05-01 18:00。",
        source_type=SourceType.TEXT,
    )

    result = workflow.run_sequential(state)

    assert result.classified_category == ContentCategory.JOB_POSTING
    assert result.extracted_signal is not None
    assert result.extracted_signal.company == "示例科技"
    assert result.extracted_signal.role == "AI Agent 工程师"


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
