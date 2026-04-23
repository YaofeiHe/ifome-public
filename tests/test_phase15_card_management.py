"""Tests for card dedupe, overwrite, and manual management flows."""

from __future__ import annotations

from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.schemas import ContentCategory, PriorityLevel, SourceType
from core.tools import NoopLLMGateway


class FakeBatchAnalysisGateway:
    """Deterministic gateway covering ingest and batch-analysis tasks."""

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
        if task_name == "classify":
            return {
                "category": "job_posting",
                "confidence": 0.92,
                "reason": "文本明显是岗位招聘信息。",
            }
        if task_name == "extract":
            return {
                "category": "job_posting",
                "company": "示例公司",
                "role": "算法工程师",
                "city": "上海",
                "ddl": "2026-05-01T18:00:00+08:00",
                "apply_url": "https://example.com/apply",
                "summary_one_line": "示例公司 - 算法工程师 / 上海",
                "confidence": 0.9,
                "tags": ["算法工程师", "上海"],
                "evidence": [],
            }
        if task_name == "batch_card_analysis":
            return {
                "analysis": "这些卡片都属于同一组暑期实习投递信息，建议优先处理最接近DDL的岗位。",
                "key_points": [
                    "共同关系：同一批投递卡片",
                    "建议保留原链接和原文证据",
                ],
            }
        return {
            "same_core": False,
            "should_replace_existing": False,
            "confidence": 0.2,
            "reason": "默认不合并。",
        }


def test_duplicate_job_updates_existing_card_instead_of_creating_new_one(
    tmp_path, monkeypatch
) -> None:
    """Same岗位 with updated fields should overwrite the old card record."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    first = services.ingest(
        raw_input="阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    second = services.ingest(
        raw_input="阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月03日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert first.normalized_item is not None
    assert second.normalized_item is not None
    assert second.normalized_item.id == first.normalized_item.id

    items = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    assert len(items) == 1
    assert items[0].extracted_signal is not None
    assert items[0].extracted_signal.ddl is not None
    assert items[0].extracted_signal.ddl.day == 3


def test_same_apply_url_different_role_variants_should_not_merge(
    tmp_path, monkeypatch
) -> None:
    """Cards from one recruiting site should stay separate when source titles differ."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    shared_url = "https://campus-talent.alibaba.com/campus/position?batchId=demo"
    first = services.ingest(
        raw_input=(
            "岗位标题：阿里系-暑期实习-淘宝闪购-算法工程师-生成器式方向\n"
            "当前岗位片段：淘宝闪购 暑期实习 算法工程师-生成器式方向 "
            f"投递链接 {shared_url}"
        ),
        source_type=SourceType.LINK,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_ref=shared_url,
        source_metadata={
            "source_title": "阿里系-暑期实习-淘宝闪购-算法工程师-生成器式方向",
            "role_variant": "算法工程师-生成器式方向",
            "semantic_tags": [
                "阿里系",
                "暑期实习",
                "淘宝闪购",
                "阿里系-暑期实习-淘宝闪购",
                "算法工程师-生成器式方向",
            ],
        },
    )
    second = services.ingest(
        raw_input=(
            "岗位标题：阿里系-暑期实习-淘宝闪购-数据研发工程师\n"
            "当前岗位片段：淘宝闪购 暑期实习 数据研发工程师 "
            f"投递链接 {shared_url}"
        ),
        source_type=SourceType.LINK,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_ref=shared_url,
        source_metadata={
            "source_title": "阿里系-暑期实习-淘宝闪购-数据研发工程师",
            "role_variant": "数据研发工程师",
            "semantic_tags": [
                "阿里系",
                "暑期实习",
                "淘宝闪购",
                "阿里系-暑期实习-淘宝闪购",
                "数据研发工程师",
            ],
        },
    )

    assert first.normalized_item is not None
    assert second.normalized_item is not None
    assert first.normalized_item.id != second.normalized_item.id

    items = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    assert len(items) == 2


def test_item_can_be_updated_and_deleted(tmp_path, monkeypatch) -> None:
    """Manual edit and delete endpoints should operate on the stored card."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    result = services.ingest(
        raw_input="某科技公司招聘 数据分析师，工作地点杭州。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert result.normalized_item is not None
    item_id = result.normalized_item.id
    updated = services.update_item(
        item_id=item_id,
        summary_one_line="某科技公司 - 数据分析师 / 杭州 / 手动修订",
        company="某科技公司",
        role="数据分析师",
        city="杭州",
        tags=["手动修订", "重点关注"],
        priority=PriorityLevel.P1,
        content_category=ContentCategory.JOB_POSTING,
    )

    assert updated is not None
    assert updated.render_card is not None
    assert updated.render_card.priority == PriorityLevel.P1
    assert "手动修订" in updated.render_card.summary_one_line
    assert updated.render_card.tags == ["手动修订", "重点关注"]

    deleted = services.delete_item(item_id)
    assert deleted is True
    assert services.get_item(item_id) is None


def test_items_can_be_batch_deleted(tmp_path, monkeypatch) -> None:
    """Batch delete should remove multiple selected cards at once."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    first = services.ingest(
        raw_input="A公司招聘 后端工程师，工作地点上海。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    second = services.ingest(
        raw_input="B公司招聘 数据分析师，工作地点杭州。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert first.normalized_item is not None
    assert second.normalized_item is not None

    deleted_item_ids, missing_item_ids = services.delete_items(
        [first.normalized_item.id, second.normalized_item.id, "item_missing"]
    )

    assert deleted_item_ids == [first.normalized_item.id, second.normalized_item.id]
    assert missing_item_ids == ["item_missing"]
    assert services.list_items(user_id="demo_user", workspace_id="demo_workspace") == []


def test_items_can_be_batch_analyzed_with_stored_raw_content(tmp_path, monkeypatch) -> None:
    """Batch analysis should use selected cards and keep the original raw content available."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=FakeBatchAnalysisGateway(),
        )
    )

    first = services.ingest(
        raw_input="字节系暑期实习 抖音电商 算法工程师，原链接 https://example.com/a",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_ref="https://example.com/a",
        source_metadata={"source_title": "字节系-暑期实习-抖音电商-算法工程师"},
    )
    second = services.ingest(
        raw_input="字节系暑期实习 抖音电商 数据研发工程师，原链接 https://example.com/b",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_ref="https://example.com/b",
        source_metadata={"source_title": "字节系-暑期实习-抖音电商-数据研发工程师"},
    )

    assert first.normalized_item is not None
    assert second.normalized_item is not None
    assert "https://example.com/a" in first.normalized_item.raw_content

    analysis, analyzed_item_ids, missing_item_ids, retrieval_mode = services.analyze_items(
        item_ids=[first.normalized_item.id, second.normalized_item.id],
        question="帮我比较这些岗位的投递优先级和链接信息",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert retrieval_mode == "batch_llm"
    assert len(analyzed_item_ids) == 2
    assert missing_item_ids == []
    assert "原链接" in analysis
