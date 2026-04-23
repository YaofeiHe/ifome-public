"""Tests for Phase 13 Boss 直聘 minimal connector paths."""

from __future__ import annotations

from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.runtime.time import now_in_project_timezone
from core.tools import NoopLLMGateway
from integrations.boss_zhipin import (
    BossZhipinConversationMessage,
    BossZhipinConversationPayload,
    BossZhipinJobPayload,
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
