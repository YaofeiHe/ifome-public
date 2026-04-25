"""Tests for card dedupe, overwrite, and manual management flows."""

from __future__ import annotations

from pathlib import Path

from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.schemas import ContentCategory, PriorityLevel, SourceType
from core.tools import OCRExtractionResult
from core.tools import NoopLLMGateway


class FakeBatchAnalysisGateway:
    """Deterministic gateway covering ingest and batch-analysis tasks."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.payloads: dict[str, list[dict[str, object]]] = {}

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
        current_payloads = self.payloads.get(task_name, [])
        current_payloads.append(user_payload)
        self.payloads[task_name] = current_payloads
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
        if task_name == "card_deduplicate":
            current = user_payload.get("current", {})
            existing = user_payload.get("existing", {})
            current_company = current.get("company") or current.get("primary_unit")
            existing_company = existing.get("company") or existing.get("primary_unit")
            same_company = current_company and current_company == existing_company
            return {
                "same_core": bool(same_company),
                "should_replace_existing": bool(same_company),
                "confidence": 0.91 if same_company else 0.2,
                "reason": "同公司同岗位更新，应视为同一核心卡片。" if same_company else "默认不合并。",
            }
        if task_name == "job_card_relationship":
            current = user_payload.get("current", {})
            existing = user_payload.get("existing", {})
            current_company = current.get("company") or current.get("primary_unit")
            existing_company = existing.get("company") or existing.get("primary_unit")
            same_company = current_company and current_company == existing_company
            return {
                "relation": "parallel" if same_company else "none",
                "confidence": 0.88 if same_company else 0.2,
                "reason": "同公司下的不同岗位方向，应组织到同一岗位合集。" if same_company else "没有明显层级关系。",
                "group_title": "示例公司-岗位合集" if same_company else None,
            }
        return {
            "same_core": False,
            "should_replace_existing": False,
            "confidence": 0.2,
            "reason": "默认不合并。",
        }


class TransitiveRelationshipGateway(FakeBatchAnalysisGateway):
    """Gateway that only reveals one company cluster through transitive relationship checks."""

    def complete_json(
        self,
        *,
        route: str,
        task_name: str,
        system_prompt: str,
        user_payload: dict[str, object],
    ) -> dict[str, object]:
        if task_name != "job_card_relationship":
            return super().complete_json(
                route=route,
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
            )

        self.calls.append(task_name)
        current_payloads = self.payloads.get(task_name, [])
        current_payloads.append(user_payload)
        self.payloads[task_name] = current_payloads

        current = user_payload.get("current", {})
        existing = user_payload.get("existing", {})
        current_title = str(current.get("source_title") or "")
        existing_title = str(existing.get("source_title") or "")
        title_pair = {current_title, existing_title}
        if {
            "示例公司-算法工程师",
            "示例公司-技术平台岗位合集说明",
        } == title_pair:
            return {
                "relation": "subordinate",
                "confidence": 0.91,
                "reason": "算法岗位属于技术平台岗位合集的子方向。",
                "group_title": "示例公司-技术平台岗位合集",
            }
        if {
            "示例公司-技术平台岗位合集说明",
            "示例公司-数据研发工程师",
        } == title_pair:
            return {
                "relation": "parallel",
                "confidence": 0.89,
                "reason": "数据研发岗位也属于同一个技术平台岗位合集。",
                "group_title": "示例公司-技术平台岗位合集",
            }
        return {
            "relation": "none",
            "confidence": 0.2,
            "reason": "只靠这两个岗位看不出直接归组关系。",
            "group_title": None,
        }


class RecruitingImageOCRClient:
    """Deterministic OCR client that returns recruiting text based on the image file name."""

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        file_name = image_path.name
        if "bundle" in file_name:
            text = (
                "⏰示例系笔试提醒\n"
                "📅 剩余笔试时间安排：2026年05月03日 18:00\n"
                "1️⃣【示例公司 暑期实习】\n"
                "仅可投递示例公司的岗位\n"
                "①算法工程师\n"
                "②测试工程师\n"
                "工作地点上海"
            )
        else:
            text = "示例公司招聘 算法工程师，工作地点上海，投递截止 2026年05月03日 18:00。"
        return OCRExtractionResult(
            text=text,
            source_metadata={
                "source_kind": "image",
                "ocr_engine": "fake_recruiting_ocr",
            },
        )


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


def test_dedupe_llm_only_runs_for_fuzzy_overlap(tmp_path, monkeypatch) -> None:
    """Heuristic dedupe should escalate to LLM only in the ambiguous middle band."""

    monkeypatch.chdir(tmp_path)
    gateway = FakeBatchAnalysisGateway()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=gateway,
        )
    )

    services.ingest(
        raw_input="示例公司招聘 算法工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    services.ingest(
        raw_input="示例公司算法岗，base上海，截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert "card_deduplicate" in gateway.calls


def test_same_company_same_role_update_can_force_llm_dedupe(tmp_path, monkeypatch) -> None:
    """Same-company same-role updates should escalate directly to LLM dedupe."""

    monkeypatch.chdir(tmp_path)
    gateway = FakeBatchAnalysisGateway()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=gateway,
        )
    )

    first = services.ingest(
        raw_input="示例公司招聘 算法工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )
    second = services.ingest(
        raw_input="示例公司招聘 算法工程师，工作地点上海，投递截止 2026年05月03日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert first.normalized_item is not None
    assert second.normalized_item is not None
    assert second.normalized_item.id == first.normalized_item.id
    assert "card_deduplicate" in gateway.calls


def test_same_company_non_duplicate_roles_can_form_dynamic_overview(tmp_path, monkeypatch) -> None:
    """Same-company sibling roles should be reorganized into one overview plus child cards."""

    monkeypatch.chdir(tmp_path)
    gateway = FakeBatchAnalysisGateway()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=gateway,
        )
    )

    first = services.ingest(
        raw_input="示例公司招聘 算法工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-算法工程师"},
    )
    second = services.ingest(
        raw_input="示例公司招聘 数据研发工程师，工作地点上海，投递截止 2026年05月03日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-数据研发工程师"},
    )

    assert first.normalized_item is not None
    assert second.normalized_item is not None
    assert "job_card_relationship" in gateway.calls

    states = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    overview_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "overview"
    ]
    role_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "role"
    ]
    assert len(overview_states) == 1
    assert len(role_states) == 2
    overview = overview_states[0]
    assert overview.render_card is not None
    assert overview.render_card.summary_one_line == "示例公司-岗位合集（2个岗位）"
    assert len(overview.render_card.job_child_item_ids) == 2
    assert all(
        state.render_card and state.render_card.job_parent_item_id == overview.normalized_item.id
        for state in role_states
        if overview.normalized_item is not None
    )


def test_relationship_prompt_can_include_old_card_multi_entity_candidates(tmp_path, monkeypatch) -> None:
    """Relationship LLM should receive rebuilt entity candidates from old mixed-role cards."""

    monkeypatch.chdir(tmp_path)
    gateway = FakeBatchAnalysisGateway()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=gateway,
        )
    )

    services.ingest(
        raw_input=(
            "示例公司春招岗位合集\n"
            "① 算法工程师\n"
            "② 数据研发工程师\n"
            "工作地点上海"
        ),
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-岗位合集说明"},
    )
    services.ingest(
        raw_input="示例公司招聘 数据研发工程师，工作地点上海，投递截止 2026年05月03日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-数据研发工程师"},
    )

    relationship_payloads = gateway.payloads.get("job_card_relationship", [])
    assert relationship_payloads
    assert any(
        len(payload.get("existing_entity_candidates", [])) >= 2
        for payload in relationship_payloads
    )


def test_transitive_same_company_cards_can_join_one_dynamic_overview(tmp_path, monkeypatch) -> None:
    """Old cards related through one bridge card should still be grouped with the new card."""

    monkeypatch.chdir(tmp_path)
    gateway = TransitiveRelationshipGateway()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=gateway,
        )
    )

    bridge = services.ingest(
        raw_input=(
            "示例公司技术平台岗位合集说明，包含算法工程师和数据研发工程师方向，"
            "工作地点上海。"
        ),
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-技术平台岗位合集说明"},
    )
    sibling = services.ingest(
        raw_input="示例公司招聘 数据研发工程师，工作地点上海，投递截止 2026年05月03日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-数据研发工程师"},
    )
    current = services.ingest(
        raw_input="示例公司招聘 算法工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-算法工程师"},
    )

    assert bridge.normalized_item is not None
    assert sibling.normalized_item is not None
    assert current.normalized_item is not None

    states = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    overview_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "overview"
    ]
    role_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "role"
    ]
    assert len(overview_states) == 1
    overview = overview_states[0]
    assert overview.render_card is not None
    assert overview.render_card.summary_one_line == "示例公司-技术平台岗位合集（3个岗位）"
    assert len(role_states) == 3
    assert len(overview.render_card.job_child_item_ids) == 3

    refreshed_current = next(
        state
        for state in states
        if state.normalized_item and state.normalized_item.id == current.normalized_item.id
    )
    checks = refreshed_current.source_metadata.get("job_relationship_checks", [])
    assert any(
        {check.get("left_item_id"), check.get("right_item_id")}
        == {bridge.normalized_item.id, sibling.normalized_item.id}
        for check in checks
    )


def test_image_ingest_can_merge_existing_job_cards_into_expanded_overview(tmp_path, monkeypatch) -> None:
    """OCR image ingest should still attach related old cards into the final overview cluster."""

    monkeypatch.chdir(tmp_path)
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=FakeBatchAnalysisGateway(),
            ocr_client=RecruitingImageOCRClient(),
        )
    )

    existing = services.ingest(
        raw_input="示例公司招聘 数据研发工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
        source_metadata={"source_title": "示例公司-数据研发工程师"},
    )
    result = services.ingest_image_file(
        file_name="bundle.png",
        file_bytes=b"fake-image",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert existing.normalized_item is not None
    assert result.normalized_item is not None
    assert result.normalized_item.source_metadata["ocr_engine"] == "fake_recruiting_ocr"

    states = services.list_items(user_id="demo_user", workspace_id="demo_workspace")
    overview_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "overview"
    ]
    role_states = [
        state for state in states if state.render_card and state.render_card.job_group_kind == "role"
    ]
    assert len(overview_states) == 1
    assert len(role_states) == 3
    overview = overview_states[0]
    assert overview.render_card is not None
    assert overview.render_card.summary_one_line == "示例公司-岗位合集（3个岗位）"
    assert len(overview.render_card.job_child_item_ids) == 3


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


def test_delete_item_removes_unreferenced_archived_source_file(tmp_path, monkeypatch) -> None:
    """Deleting one standalone card should also remove its archived source file."""

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
    source_file = services.get_source_file(result.normalized_item.id)
    assert source_file is not None
    source_path, _ = source_file
    assert source_path.exists() is True

    deleted = services.delete_item(result.normalized_item.id)

    assert deleted is True
    assert source_path.exists() is False


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
