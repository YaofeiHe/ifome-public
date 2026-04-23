"""Reserved email reminder adapter interface."""

from __future__ import annotations

from dataclasses import dataclass

from core.schemas import ReminderTask


@dataclass
class EmailReminderPreview:
    """Serializable preview for a future email reminder send."""

    subject: str
    body: str
    recipient: str | None = None


class EmailClient:
    """
    Reserved adapter for future email reminder delivery.

    Responsibilities:
    - Convert one `ReminderTask` into an email-ready payload.

    Non-responsibilities:
    - Queue persistence.
    - Workflow planning logic.
    """

    def build_preview(self, task: ReminderTask) -> EmailReminderPreview:
        """Return a preview payload without sending a real email."""

        return EmailReminderPreview(
            subject=task.title,
            body=task.description or f"请关注提醒：{task.title}",
        )
