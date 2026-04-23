"""Tests for Phase 12 SQLite-backed workflow persistence."""

from __future__ import annotations

from apps.api.src.services import ApiServiceContainer
from core.reminders.queue import ReminderQueue
from core.runtime.dependencies import WorkflowDependencies, build_seed_memory_payload
from core.schemas import CareerStateMemory, SourceType
from core.runtime.time import now_in_project_timezone
from core.storage.sqlite_memory import SQLiteMemoryProvider
from core.storage.sqlite_reminders import SQLiteReminderRepository
from core.storage.sqlite_workflows import SQLiteWorkflowRepository
from core.tools import NoopLLMGateway


def test_sqlite_workflow_repository_survives_service_restart(tmp_path) -> None:
    """Workflow states should still be readable after a fresh service container is created."""

    workflow_db_path = tmp_path / "runtime" / "workflows.sqlite3"
    reminder_db_path = tmp_path / "runtime" / "reminders.sqlite3"

    first_container = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            workflow_repository=SQLiteWorkflowRepository(workflow_db_path),
            reminder_queue=ReminderQueue(SQLiteReminderRepository(reminder_db_path)),
            llm_gateway=NoopLLMGateway(),
        )
    )

    first_result = first_container.ingest(
        raw_input=(
            "阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月01日 18:00，"
            "投递链接 https://example.com/apply"
        ),
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert first_result.normalized_item is not None
    item_id = first_result.normalized_item.id

    restarted_container = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            workflow_repository=SQLiteWorkflowRepository(workflow_db_path),
            reminder_queue=ReminderQueue(SQLiteReminderRepository(reminder_db_path)),
            llm_gateway=NoopLLMGateway(),
        )
    )

    restored = restarted_container.get_item(item_id)
    assert restored is not None
    assert restored.normalized_item is not None
    assert restored.normalized_item.id == item_id
    assert restored.render_card is not None
    assert restored.render_card.summary_one_line == first_result.render_card.summary_one_line
    assert restarted_container.list_items()[0].normalized_item.id == item_id


def test_sqlite_memory_provider_survives_service_restart(tmp_path) -> None:
    """Profile and career-state memory should still be readable after restart."""

    memory_db_path = tmp_path / "runtime" / "memory.sqlite3"
    dependencies = WorkflowDependencies(
        memory_provider=SQLiteMemoryProvider(
            memory_db_path,
            default_payload_factory=build_seed_memory_payload,
        ),
        llm_gateway=NoopLLMGateway(),
    )
    first_container = ApiServiceContainer(dependencies=dependencies)

    _, updated_career_state = first_container.upsert_career_state_memory(
        CareerStateMemory(
            user_id="demo_user",
            workspace_id="demo_workspace",
            today_focus=["准备一面"],
            active_priorities=["优先处理有明确面试时间的条目"],
            notes="需要回看项目亮点。",
            updated_at=now_in_project_timezone(),
        )
    )

    restarted_container = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            memory_provider=SQLiteMemoryProvider(
                memory_db_path,
                default_payload_factory=build_seed_memory_payload,
            ),
            llm_gateway=NoopLLMGateway(),
        )
    )

    restored = restarted_container.dependencies.memory_provider.load(
        "demo_user", "demo_workspace"
    )
    assert restored["career_state_memory"].today_focus == updated_career_state.today_focus
    assert restored["career_state_memory"].notes == updated_career_state.notes
