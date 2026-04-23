"""Reminder planning helpers for the minimal workflow."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from core.runtime.time import now_in_project_timezone
from core.schemas import ExtractedJobSignal, ReminderTask, ScoreResult


def _build_offsets(due_time) -> list[timedelta]:
    """Return reminder offsets appropriate for a due time."""

    return [timedelta(hours=24), timedelta(hours=2)]


def plan_reminders(
    signal: ExtractedJobSignal, score_result: ScoreResult | None
) -> list[ReminderTask]:
    """Create in-app reminder tasks from extracted time fields."""

    due_time = signal.ddl or signal.interview_time or signal.event_time
    if due_time is None:
        return []

    tasks: list[ReminderTask] = []
    now = now_in_project_timezone()
    for offset in _build_offsets(due_time):
        trigger_time = due_time - offset
        if trigger_time <= now:
            continue
        tasks.append(
            ReminderTask(
                id=f"rem_{uuid4().hex[:10]}",
                user_id=signal.user_id,
                workspace_id=signal.workspace_id,
                trace_id=signal.trace_id,
                source_item_id=signal.source_item_id,
                title=f"{signal.summary_one_line} 提醒",
                description=f"距离关键时间点还有约 {int(offset.total_seconds() / 3600)} 小时",
                trigger_time=trigger_time,
                due_time=due_time,
                priority=score_result.priority if score_result else "P2",
                payload={
                    "company": signal.company,
                    "role": signal.role,
                    "category": signal.category.value,
                },
                created_at=now,
            )
        )

    return tasks
