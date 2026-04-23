"""Memory schemas for long-term profile and dynamic career state."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from core.schemas.base import (
    RecommendedAction,
    SchemaModel,
    UserScopedModel,
    ensure_timezone_aware,
)


class ProjectMemoryEntry(SchemaModel):
    """
    A project summary stored inside long-term profile memory.

    The project entry is intentionally compact: rich enough for downstream
    interview preparation, but still understandable during demos and reviews.
    """

    name: str = Field(description="Project name shown to the user and interviewer.")
    summary: str = Field(description="Short project description in plain language.")
    role: str | None = Field(
        default=None,
        description="The user's role or contribution within the project.",
    )
    tech_stack: list[str] = Field(
        default_factory=list,
        description="Core technologies or tools used in the project.",
    )
    highlight_points: list[str] = Field(
        default_factory=list,
        description="Memorable accomplishments, metrics, or architecture choices.",
    )
    interview_story_hooks: list[str] = Field(
        default_factory=list,
        description="Talking points that can later feed interview preparation prompts.",
    )


class HardFilter(SchemaModel):
    """Explicit must-have or must-not-have conditions used in ranking."""

    key: str = Field(description="Machine-readable filter name.")
    value: str = Field(description="Expected filter value or rule payload.")
    rationale: str | None = Field(
        default=None,
        description="Why this filter exists, useful for future UI explanations.",
    )


class ProfileMemory(UserScopedModel):
    """
    Long-term, relatively stable user profile used for matching and ranking.

    Responsibilities:
    - Store user preferences that change infrequently.
    - Act as a reusable input to scoring and chat preparation.

    Non-responsibilities:
    - Tracking live interview progress.
    - Storing transient one-off workflow context.
    """

    target_roles: list[str] = Field(
        default_factory=list,
        description="Preferred role families such as backend or ML engineer.",
    )
    priority_domains: list[str] = Field(
        default_factory=list,
        description="Preferred industries or domains such as AI infra or autonomy.",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Skills that help the matcher assess relevance.",
    )
    projects: list[ProjectMemoryEntry] = Field(
        default_factory=list,
        description="Project summaries that later support matching and interview prep.",
    )
    location_preferences: list[str] = Field(
        default_factory=list,
        description="Preferred work cities or acceptable remote arrangements.",
    )
    hard_filters: list[HardFilter] = Field(
        default_factory=list,
        description="Strict constraints such as must-be-city or no-sales-role.",
    )
    soft_preferences: list[str] = Field(
        default_factory=list,
        description="Nice-to-have preferences that should influence but not block ranking.",
    )
    excluded_companies: list[str] = Field(
        default_factory=list,
        description="Companies the user does not want to pursue.",
    )
    summary: str | None = Field(
        default=None,
        description="Human-readable profile summary suitable for debugging and UI display.",
    )
    updated_at: datetime = Field(
        description="Timezone-aware timestamp when the profile memory was last updated."
    )
    last_confirmed_at: datetime | None = Field(
        default=None,
        description="Most recent time the user explicitly confirmed this profile.",
    )

    @field_validator("updated_at", "last_confirmed_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Require timezone-aware timestamps for all profile memory dates."""

        return ensure_timezone_aware(value, info.field_name)


class AppliedJobRecord(SchemaModel):
    """A lightweight record for one submitted application."""

    company: str = Field(description="Company applied to.")
    role: str = Field(description="Role applied to.")
    applied_at: datetime = Field(
        description="Timezone-aware time when the application was submitted."
    )
    status: str = Field(
        description="Current application stage such as submitted or rejected."
    )
    source_item_id: str | None = Field(
        default=None,
        description="Originating normalized item id when available.",
    )

    @field_validator("applied_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info) -> datetime:
        """Prevent ambiguous application timestamps in career tracking."""

        return ensure_timezone_aware(value, info.field_name)


class InterviewLoopRecord(SchemaModel):
    """A currently active interview or assessment process."""

    company: str = Field(description="Company running the interview loop.")
    role: str = Field(description="Role under interview.")
    stage: str = Field(description="Stage label such as OA, phone screen, or onsite.")
    scheduled_at: datetime | None = Field(
        default=None,
        description="Timezone-aware schedule time if the event is fixed.",
    )
    location: str | None = Field(
        default=None,
        description="Interview location or video call reference.",
    )
    source_item_id: str | None = Field(
        default=None,
        description="Originating item id for traceability.",
    )

    @field_validator("scheduled_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Keep interview scheduling fields aligned with the reminder subsystem."""

        return ensure_timezone_aware(value, info.field_name)


class DeadlineRecord(SchemaModel):
    """A deadline the user should track in current career state."""

    title: str = Field(description="Short label shown in dashboards or reminders.")
    due_at: datetime = Field(
        description="Timezone-aware deadline timestamp in ISO 8601 format."
    )
    source_item_id: str | None = Field(
        default=None,
        description="Source normalized item id when the deadline comes from a job signal.",
    )
    recommended_action: RecommendedAction | None = Field(
        default=None,
        description="Action the user is currently expected to take before the deadline.",
    )

    @field_validator("due_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info) -> datetime:
        """Keep all deadlines precise enough for future reminder scheduling."""

        return ensure_timezone_aware(value, info.field_name)


class CareerStateMemory(UserScopedModel):
    """
    Dynamic memory that tracks the user's current job-hunt progress.

    Responsibilities:
    - Record applications, interviews, upcoming deadlines, and current focus.
    - Capture fast-changing context used by ranking and chat planning.

    Non-responsibilities:
    - Storing evergreen skill or preference information.
    - Sending reminders directly.
    """

    applied_jobs: list[AppliedJobRecord] = Field(
        default_factory=list,
        description="Applications already submitted by the user.",
    )
    active_interviews: list[InterviewLoopRecord] = Field(
        default_factory=list,
        description="Interview loops or assessments currently in progress.",
    )
    watched_companies: list[str] = Field(
        default_factory=list,
        description="Companies the user wants to monitor closely.",
    )
    market_watch_sources: list[str] = Field(
        default_factory=list,
        description="Websites or feeds that should be refreshed for market insight cards.",
    )
    market_article_fetch_limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of market articles fetched into child cards per watched source.",
    )
    today_focus: list[str] = Field(
        default_factory=list,
        description="Short list of tasks the user wants to finish today.",
    )
    upcoming_deadlines: list[DeadlineRecord] = Field(
        default_factory=list,
        description="Deadlines that should influence urgency scoring.",
    )
    active_priorities: list[str] = Field(
        default_factory=list,
        description="Current high-level priorities such as resume polishing or OA prep.",
    )
    notes: str | None = Field(
        default=None,
        description="Compact human notes about current job-hunt state.",
    )
    last_market_refresh_at: datetime | None = Field(
        default=None,
        description="Most recent successful market-watch refresh time.",
    )
    updated_at: datetime = Field(
        description="Timezone-aware timestamp when career state was last updated."
    )

    @field_validator("updated_at", "last_market_refresh_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info) -> datetime:
        """Keep state timestamps safe for sorting and reminder planning."""

        return ensure_timezone_aware(value, info.field_name)
