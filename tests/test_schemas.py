"""Schema validation tests for the step-8 milestone."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.schemas import NormalizedItem, ReminderTask, SourceType


def test_normalized_item_requires_timezone_aware_datetime() -> None:
    """Naive datetimes should be rejected to keep reminder timing unambiguous."""

    with pytest.raises(ValidationError):
        NormalizedItem(
            id="item_1",
            user_id="user_1",
            workspace_id="ws_1",
            trace_id="trace_1",
            source_type=SourceType.TEXT,
            raw_content="raw",
            normalized_text="clean",
            created_at=datetime.now(),
        )


def test_reminder_task_accepts_timezone_aware_datetime() -> None:
    """Reminder tasks should validate successfully with ISO-like aware times."""

    task = ReminderTask(
        id="rem_1",
        user_id="user_1",
        workspace_id="ws_1",
        trace_id="trace_1",
        source_item_id="item_1",
        title="提醒",
        trigger_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )

    assert task.id == "rem_1"
    assert task.trigger_time.tzinfo is not None
