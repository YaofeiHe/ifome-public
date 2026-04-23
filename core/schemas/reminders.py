"""Reminder queue schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from core.schemas.base import (
    JsonDict,
    PriorityLevel,
    ReminderChannel,
    ReminderStatus,
    UserScopedModel,
    ensure_timezone_aware,
)


class ReminderTask(UserScopedModel):
    """
    A scheduled reminder created from extracted recruiting signals.

    Responsibilities:
    - Represent a reminder candidate in a queue-friendly format.
    - Preserve enough payload for later notification adapters.

    Non-responsibilities:
    - Sending notifications itself.
    - Updating profile or career memories.
    """

    id: str = Field(description="Stable identifier for the reminder task.")
    trace_id: str = Field(description="Trace identifier inherited from the source workflow.")
    source_item_id: str = Field(description="Normalized item id that produced the reminder.")
    title: str = Field(description="Short reminder title shown to the user.")
    description: str | None = Field(
        default=None,
        description="Optional human-readable reminder context.",
    )
    trigger_time: datetime = Field(
        description="Timezone-aware time when the reminder should fire."
    )
    due_time: datetime | None = Field(
        default=None,
        description="Original business event time such as DDL or interview schedule.",
    )
    priority: PriorityLevel = Field(
        default=PriorityLevel.P2,
        description="User-facing priority bucket for this reminder.",
    )
    channel: ReminderChannel = Field(
        default=ReminderChannel.IN_APP,
        description="Delivery channel reserved for the reminder.",
    )
    status: ReminderStatus = Field(
        default=ReminderStatus.PLANNED,
        description="Current lifecycle state inside the reminder queue.",
    )
    payload: JsonDict = Field(
        default_factory=dict,
        description="Adapter-ready payload reserved for later email/calendar/push delivery.",
    )
    created_at: datetime = Field(
        description="Timezone-aware timestamp when the reminder task was created."
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timezone-aware timestamp when the reminder was last updated.",
    )

    @field_validator("trigger_time", "due_time", "created_at", "updated_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Enforce one datetime standard across queue planning and delivery."""

        return ensure_timezone_aware(value, info.field_name)
