"""Reserved calendar adapter interface."""

from __future__ import annotations

from dataclasses import dataclass

from core.schemas import ReminderTask


@dataclass
class CalendarEventPreview:
    """Serializable preview for a future calendar event creation."""

    title: str
    start_time: str
    end_time: str | None = None
    description: str | None = None


class CalendarClient:
    """
    Reserved adapter for future calendar event creation.

    Responsibilities:
    - Convert one `ReminderTask` into a calendar-event shaped payload.

    Non-responsibilities:
    - Workflow planning.
    - Real provider authentication in the current phase.
    """

    def build_preview(self, task: ReminderTask) -> CalendarEventPreview:
        """Return a preview payload without calling a real calendar API."""

        return CalendarEventPreview(
            title=task.title,
            start_time=task.trigger_time.isoformat(),
            end_time=task.due_time.isoformat() if task.due_time else None,
            description=task.description,
        )
