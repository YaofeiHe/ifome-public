"""Shared schema primitives used across workflow state and domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    """Supported raw input types accepted by the ingestion layer."""

    TEXT = "text"
    LINK = "link"
    IMAGE = "image"


class ContentCategory(str, Enum):
    """High-level categories assigned by the classify step."""

    JOB_POSTING = "job_posting"
    INTERVIEW_NOTICE = "interview_notice"
    TALK_EVENT = "talk_event"
    REFERRAL = "referral"
    GENERAL_UPDATE = "general_update"
    NOISE = "noise"
    UNKNOWN = "unknown"


class MemoryWriteMode(str, Enum):
    """
    Control whether a piece of information stays ephemeral or becomes memory.

    The flag lives in the schema layer so API requests, workflow state, and
    memory services all speak the same language about write intent.
    """

    CONTEXT_ONLY = "context_only"
    PERSIST_TO_LONG_TERM = "persist_to_long_term"


class WorkflowStatus(str, Enum):
    """Processing lifecycle states shared by items, nodes, and reminders."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class PriorityLevel(str, Enum):
    """Priority buckets surfaced to the user interface and reminder queue."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ReminderChannel(str, Enum):
    """Delivery channels reserved by the reminder subsystem."""

    IN_APP = "in_app"
    EMAIL = "email"
    CALENDAR = "calendar"
    WEB_PUSH = "web_push"


class ReminderStatus(str, Enum):
    """State machine for a reminder task."""

    PLANNED = "planned"
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RecommendedAction(str, Enum):
    """Suggested next action after profile matching and scoring."""

    APPLY_NOW = "apply_now"
    PREPARE_INTERVIEW = "prepare_interview"
    SAVE_FOR_LATER = "save_for_later"
    TRACK_ONLY = "track_only"
    IGNORE = "ignore"


class SchemaModel(BaseModel):
    """
    Base model for all schema objects.

    Responsibilities:
    - Enforce strict field validation.
    - Provide a common place for project-wide Pydantic behavior.

    Non-responsibilities:
    - Business logic execution.
    - Persistence or framework orchestration.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
        protected_namespaces=(),
    )


class UserScopedModel(SchemaModel):
    """
    Base model for records that belong to a logical user/workspace scope.

    Every core record reserves both identifiers from day one so the POC can
    remain single-user while still being structurally ready for multi-user use.
    """

    user_id: str = Field(description="Logical user identifier.")
    workspace_id: str | None = Field(
        default=None,
        description="Optional workspace or tenant identifier reserved for future use.",
    )


def ensure_timezone_aware(value: datetime | None, field_name: str) -> datetime | None:
    """
    Guardrail for all datetime fields in the project.

    The project standardizes on timezone-aware ISO 8601 timestamps. Raising here
    prevents silent mixing of local naive timestamps with stored UTC or offset
    timestamps, which would make reminders and interview schedules ambiguous.
    """

    if value is None:
        return None

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware and serialized as ISO 8601."
        )

    return value


JsonDict = dict[str, Any]
