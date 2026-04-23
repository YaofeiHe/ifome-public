"""Reserved web push adapter interface."""

from __future__ import annotations

from dataclasses import dataclass

from core.schemas import ReminderTask


@dataclass
class WebPushPreview:
    """Serializable preview for a future web push send."""

    title: str
    body: str
    topic: str


class WebPushClient:
    """
    Reserved adapter for future browser push delivery.

    Responsibilities:
    - Convert one `ReminderTask` into a web-push shaped payload.

    Non-responsibilities:
    - Subscription management.
    - Actual push delivery in the current scaffold stage.
    """

    def build_preview(self, task: ReminderTask) -> WebPushPreview:
        """Return a push preview payload without sending a real notification."""

        return WebPushPreview(
            title=task.title,
            body=task.description or "你有一个新的提醒待处理。",
            topic=f"reminder:{task.id}",
        )
