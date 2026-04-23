"""Reminder planner and queue tests."""

from __future__ import annotations

from datetime import timedelta

from core.reminders import ReminderQueue, plan_reminders
from core.runtime.time import now_in_project_timezone
from core.schemas import (
    ContentCategory,
    ExtractedJobSignal,
    PriorityLevel,
    RecommendedAction,
    ScoreResult,
)
from core.storage.sqlite_reminders import SQLiteReminderRepository


def build_signal() -> ExtractedJobSignal:
    """Construct a representative job signal with a future deadline."""

    future_due = now_in_project_timezone() + timedelta(days=3)
    return ExtractedJobSignal(
        user_id="user_1",
        workspace_id="ws_1",
        source_item_id="item_1",
        trace_id="trace_1",
        category=ContentCategory.JOB_POSTING,
        company="Example",
        role="后端工程师",
        city="上海",
        ddl=future_due,
        summary_one_line="Example - 后端工程师 / 上海",
        extracted_at=now_in_project_timezone(),
    )


def build_score() -> ScoreResult:
    """Construct a score result used by the reminder planner."""

    return ScoreResult(
        relevance_score=0.8,
        urgency_score=0.7,
        total_score=0.76,
        priority=PriorityLevel.P1,
        recommended_action=RecommendedAction.APPLY_NOW,
        reasoning="测试用评分结果。",
    )


def test_plan_reminders_creates_multiple_offsets() -> None:
    """A due time should fan out into multiple planned reminder tasks."""

    tasks = plan_reminders(build_signal(), build_score())

    assert len(tasks) >= 1
    assert all(task.source_item_id == "item_1" for task in tasks)


def test_sqlite_reminder_queue_persists_tasks(tmp_path) -> None:
    """ReminderQueue should store tasks durably in SQLite."""

    repository = SQLiteReminderRepository(tmp_path / "reminders.sqlite3")
    queue = ReminderQueue(repository)
    tasks = plan_reminders(build_signal(), build_score())

    created_ids = queue.enqueue(tasks)
    loaded_tasks = queue.list_tasks()

    assert created_ids
    assert len(loaded_tasks) == len(tasks)
    assert loaded_tasks[0].id in created_ids
