"""Workflow state and supporting execution schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from core.runtime.interfaces import BaseState
from core.schemas.base import (
    ContentCategory,
    JsonDict,
    MemoryWriteMode,
    PriorityLevel,
    RecommendedAction,
    SchemaModel,
    SourceType,
    WorkflowStatus,
    ensure_timezone_aware,
)
from core.schemas.items import ExtractedJobSignal, NormalizedItem
from core.schemas.memory import CareerStateMemory, ProfileMemory
from core.schemas.reminders import ReminderTask


class MatchProfileResult(SchemaModel):
    """
    Intermediate result produced by the profile-matching stage.

    The object stays separate from the final score so we can explain whether the
    system liked a role because of profile fit, urgency, or both.
    """

    matched_roles: list[str] = Field(
        default_factory=list,
        description="Role preferences that matched the extracted signal.",
    )
    matched_domains: list[str] = Field(
        default_factory=list,
        description="Industry or domain preferences that matched the signal.",
    )
    matched_skills: list[str] = Field(
        default_factory=list,
        description="Skills inferred to overlap with the opportunity.",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Reasons why the signal may be a poor fit.",
    )
    rationale: str = Field(
        description="Plain-language explanation of the matching outcome."
    )
    fit_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Profile-fit score before urgency is applied.",
    )


class ScoreResult(SchemaModel):
    """Final ranking output used by reminders and front-end rendering."""

    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How well the opportunity matches long-term profile preferences.",
    )
    urgency_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How time-sensitive the opportunity appears to be.",
    )
    total_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Combined score shown in debugging and ranking outputs.",
    )
    priority: PriorityLevel = Field(description="Priority bucket surfaced to the user.")
    recommended_action: RecommendedAction = Field(
        description="Recommended next action for the user."
    )
    reasoning: str = Field(
        description="Compact explanation that can later appear in UI or logs."
    )


class RenderedItemCard(SchemaModel):
    """Minimal card payload returned to the UI layer."""

    item_id: str = Field(description="Normalized item identifier represented by the card.")
    summary_one_line: str = Field(description="Primary headline shown in list views.")
    company: str | None = Field(default=None, description="Company field shown on the card.")
    role: str | None = Field(default=None, description="Role field shown on the card.")
    city: str | None = Field(default=None, description="Location field shown on the card.")
    location_note: str | None = Field(
        default=None,
        description="Supplementary explanation when the location is still pending.",
    )
    ddl: datetime | None = Field(
        default=None,
        description="Deadline highlighted on the card when available.",
    )
    interview_time: datetime | None = Field(
        default=None,
        description="Interview time shown on the card when available.",
    )
    event_time: datetime | None = Field(
        default=None,
        description="Event time shown on the card when available.",
    )
    priority: PriorityLevel | None = Field(
        default=None,
        description="Priority badge displayed in the interface.",
    )
    content_category: ContentCategory = Field(
        default=ContentCategory.UNKNOWN,
        description="Semantic category used to organize the card.",
    )
    source_type: SourceType | None = Field(
        default=None,
        description="Original source type of the card.",
    )
    workflow_status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING,
        description="Current workflow status represented by the card.",
    )
    source_ref: str | None = Field(
        default=None,
        description="Original URL, file name, or connector reference.",
    )
    has_source_file: bool = Field(
        default=False,
        description="Whether one archived local source file is available for direct access.",
    )
    source_file_name: str | None = Field(
        default=None,
        description="Archived local source file name when available.",
    )
    source_file_path: str | None = Field(
        default=None,
        description="Absolute archived local source file path when available.",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timezone-aware timestamp of the latest card update."
    )
    message_time: datetime | None = Field(
        default=None,
        description="Primary message or publish time associated with the source content.",
    )
    generated_at: datetime | None = Field(
        default=None,
        description="Timezone-aware timestamp when the card was first generated.",
    )
    ai_score: float | None = Field(
        default=None,
        description="Model-assisted fit score used for ranking and market insight ordering.",
    )
    insight_summary: str | None = Field(
        default=None,
        description="Short summary used especially for market information cards.",
    )
    advice: str | None = Field(
        default=None,
        description="Compact next-step suggestion shown in the list UI.",
    )
    is_market_signal: bool = Field(
        default=False,
        description="Whether this card belongs to the market-information section.",
    )
    market_group_kind: str | None = Field(
        default=None,
        description="Grouped market-card kind such as overview or article.",
    )
    market_parent_item_id: str | None = Field(
        default=None,
        description="Parent market card id when this card is a grouped child article.",
    )
    market_child_item_ids: list[str] = Field(
        default_factory=list,
        description="Child market article ids linked from one overview card.",
    )
    market_child_previews: list[str] = Field(
        default_factory=list,
        description="Short preview labels shown before expanding grouped market articles.",
    )
    job_group_kind: str | None = Field(
        default=None,
        description="Grouped activity-card kind such as overview or role.",
    )
    job_parent_item_id: str | None = Field(
        default=None,
        description="Parent activity card id when this card is a grouped child role.",
    )
    job_child_item_ids: list[str] = Field(
        default_factory=list,
        description="Child activity item ids linked from one overview card.",
    )
    job_child_previews: list[str] = Field(
        default_factory=list,
        description="Short preview labels shown before expanding grouped activity cards.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Auxiliary labels shown in compact UI form.",
    )

    @field_validator(
        "ddl",
        "interview_time",
        "event_time",
        "updated_at",
        "message_time",
        "generated_at",
    )
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Keep UI-facing timestamps consistent with backend time handling."""

        return ensure_timezone_aware(value, info.field_name)


class WorkflowIssue(SchemaModel):
    """A structured problem captured during execution."""

    node_name: str = Field(description="Workflow node that raised or reported the issue.")
    severity: str = Field(description="Severity label such as warning or error.")
    message: str = Field(description="Human-readable issue summary.")
    retryable: bool = Field(
        default=False,
        description="Whether the caller may retry this node safely.",
    )
    details: JsonDict = Field(
        default_factory=dict,
        description="Optional machine-readable metadata for debugging.",
    )
    observed_at: datetime = Field(
        description="Timezone-aware timestamp when the issue was captured."
    )

    @field_validator("observed_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info) -> datetime:
        """Require timezone-aware timestamps for structured issue tracking."""

        return ensure_timezone_aware(value, info.field_name)


class NodeExecutionRecord(SchemaModel):
    """Execution trace for one workflow node."""

    node_name: str = Field(description="Workflow node name.")
    status: WorkflowStatus = Field(description="Node outcome status.")
    started_at: datetime = Field(
        description="Timezone-aware timestamp when node execution started."
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Timezone-aware timestamp when node execution finished.",
    )
    notes: str | None = Field(
        default=None,
        description="Compact notes for debugging or human review.",
    )

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Keep execution tracing aligned with the rest of observability data."""

        return ensure_timezone_aware(value, info.field_name)


class AgentState(BaseState):
    """
    End-to-end workflow state passed between graph nodes.

    Responsibilities:
    - Carry the explicit state for each processing stage.
    - Preserve intermediate outputs, issues, and card-ready render payloads.

    Non-responsibilities:
    - Running nodes on its own.
    - Persisting itself without a storage layer.
    """

    request_id: str | None = Field(
        default=None,
        description="Request identifier emitted by the API layer.",
    )
    source_type: SourceType = Field(
        description="Raw input type associated with the current workflow run."
    )
    source_ref: str | None = Field(
        default=None,
        description="External source reference such as a URL, file name, or connector id.",
    )
    source_metadata: JsonDict = Field(
        default_factory=dict,
        description="Auxiliary metadata gathered at ingest time.",
    )
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether this run may write data into long-term memory.",
    )
    raw_input: str = Field(description="Original inbound payload before normalization.")
    classified_category: ContentCategory | None = Field(
        default=None,
        description="Category produced by the classify node before full extraction.",
    )
    normalized_item: NormalizedItem | None = Field(
        default=None,
        description="Normalized representation after the normalize node.",
    )
    extracted_signal: ExtractedJobSignal | None = Field(
        default=None,
        description="Structured extraction output after the extract node.",
    )
    profile_memory: ProfileMemory | None = Field(
        default=None,
        description="Loaded long-term user profile for matching.",
    )
    career_state_memory: CareerStateMemory | None = Field(
        default=None,
        description="Loaded dynamic career-state memory.",
    )
    profile_match: MatchProfileResult | None = Field(
        default=None,
        description="Intermediate profile-matching result.",
    )
    score_result: ScoreResult | None = Field(
        default=None,
        description="Final ranking output after the score node.",
    )
    reminder_tasks: list[ReminderTask] = Field(
        default_factory=list,
        description="Reminder tasks planned from the current signal.",
    )
    render_card: RenderedItemCard | None = Field(
        default=None,
        description="Card payload prepared for the front-end layer.",
    )
    node_history: list[NodeExecutionRecord] = Field(
        default_factory=list,
        description="Execution history kept for debugging and demos.",
    )
    issues: list[WorkflowIssue] = Field(
        default_factory=list,
        description="Warnings or errors captured during execution.",
    )
    model_routing: JsonDict = Field(
        default_factory=dict,
        description="Model routing decisions recorded for transparency and cost control.",
    )
    persistence_summary: JsonDict = Field(
        default_factory=dict,
        description="Storage-layer write summary captured by the persist node.",
    )
    status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING,
        description="Overall workflow status for this state object.",
    )
