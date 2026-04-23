"""Input normalization and extraction schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from core.schemas.base import (
    ContentCategory,
    JsonDict,
    MemoryWriteMode,
    SchemaModel,
    SourceType,
    UserScopedModel,
    WorkflowStatus,
    ensure_timezone_aware,
)


class EvidenceSpan(SchemaModel):
    """
    A small piece of evidence supporting one extracted field.

    Keeping field-level evidence explicit helps the project stay explainable in
    demos and debugging sessions instead of hiding all reasoning inside prompts.
    """

    field_name: str = Field(description="Name of the extracted field being supported.")
    snippet: str = Field(description="Raw text snippet that supports the field.")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for this evidence snippet.",
    )


class NormalizedItem(UserScopedModel):
    """
    Unified representation of any incoming recruiting-related input.

    Responsibilities:
    - Preserve the original payload and the cleaned normalized text.
    - Record source metadata and processing scope.
    - Act as the canonical handoff format after normalization.

    Non-responsibilities:
    - Deciding user priority.
    - Creating reminders or chat answers.
    """

    id: str = Field(description="Stable identifier for the normalized item.")
    trace_id: str = Field(description="Trace identifier propagated through the workflow.")
    source_type: SourceType = Field(description="Raw source type received at ingest.")
    source_ref: str | None = Field(
        default=None,
        description="External reference such as a URL, filename, or message id.",
    )
    source_title: str | None = Field(
        default=None,
        description="Optional title captured from a page, upload, or chat context.",
    )
    raw_content: str = Field(description="Original raw content before any cleanup.")
    normalized_text: str = Field(
        description="Cleaned text representation used by downstream nodes."
    )
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether this item is allowed to write into long-term memory.",
    )
    source_metadata: JsonDict = Field(
        default_factory=dict,
        description="Auxiliary metadata such as OCR stats, page title, or mime type.",
    )
    classification_hint: ContentCategory = Field(
        default=ContentCategory.UNKNOWN,
        description="Optional heuristic label available before model-based classify.",
    )
    processing_status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING,
        description="Current workflow status for this item.",
    )
    created_at: datetime = Field(
        description="Timezone-aware ingest timestamp in ISO 8601 format."
    )
    normalized_at: datetime | None = Field(
        default=None,
        description="Timezone-aware timestamp when normalization completed.",
    )

    @field_validator("created_at", "normalized_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Enforce the project-wide timezone-aware datetime policy."""

        return ensure_timezone_aware(value, info.field_name)


class ExtractedJobSignal(UserScopedModel):
    """
    Structured hiring signal extracted from a normalized item.

    Responsibilities:
    - Store the fields needed by matching, scoring, reminders, and UI rendering.
    - Preserve extraction confidence and evidence snippets for explainability.

    Non-responsibilities:
    - Final prioritization decisions.
    - Persistence orchestration.
    """

    source_item_id: str = Field(description="Identifier of the originating normalized item.")
    trace_id: str = Field(description="Trace identifier shared with the source item.")
    category: ContentCategory = Field(
        default=ContentCategory.UNKNOWN,
        description="Classify output for the normalized item.",
    )
    company: str | None = Field(default=None, description="Company or organization name.")
    role: str | None = Field(default=None, description="Role or job title.")
    city: str | None = Field(default=None, description="Primary city or location.")
    location_note: str | None = Field(
        default=None,
        description="Clarifying note when the exact location is still pending.",
    )
    interview_location: str | None = Field(
        default=None,
        description="Physical or online interview location if explicitly mentioned.",
    )
    ddl: datetime | None = Field(
        default=None,
        description="Application deadline as a timezone-aware ISO 8601 timestamp.",
    )
    event_time: datetime | None = Field(
        default=None,
        description="Recruiting event time such as a talk or assessment window.",
    )
    interview_time: datetime | None = Field(
        default=None,
        description="Interview time when present in notices or chat messages.",
    )
    apply_url: str | None = Field(default=None, description="Application submission URL.")
    source_url: str | None = Field(
        default=None,
        description="Original source URL when the item comes from a web page.",
    )
    summary_one_line: str = Field(
        description="One-line summary suitable for card rendering."
    )
    raw_text_excerpt: str | None = Field(
        default=None,
        description="Compact excerpt kept for debugging low-confidence extractions.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Shallow labels such as backend, AI, campus, or urgent.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall extraction confidence across the structured fields.",
    )
    evidence: list[EvidenceSpan] = Field(
        default_factory=list,
        description="Field-level evidence snippets kept for explainability.",
    )
    extracted_at: datetime = Field(
        description="Timezone-aware timestamp when extraction completed."
    )

    @field_validator("ddl", "event_time", "interview_time", "extracted_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Keep all extracted time fields on the same timezone-aware standard."""

        return ensure_timezone_aware(value, info.field_name)
