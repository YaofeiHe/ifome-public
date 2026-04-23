"""Request and response contracts for the minimal FastAPI layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from core.schemas import (
    AgentState,
    CareerStateMemory,
    ContentCategory,
    MemoryWriteMode,
    PriorityLevel,
    ProfileMemory,
    ReminderTask,
    RenderedItemCard,
)
from integrations.boss_zhipin import BossZhipinConversationPayload, BossZhipinJobPayload


class ApiEnvelope(BaseModel):
    """
    Unified API response wrapper.

    Responsibilities:
    - Keep success and error shapes stable across endpoints.
    - Allow the frontend to read `data` and `error` consistently.
    """

    success: bool = Field(description="Whether the API call completed successfully.")
    data: Any | None = Field(default=None, description="Successful response payload.")
    error: str | None = Field(default=None, description="Error message when failed.")
    trace_id: str | None = Field(
        default=None, description="Trace id associated with the request or workflow."
    )


class IngestTextRequest(BaseModel):
    """Payload for plain-text ingest requests."""

    text: str = Field(description="Recruiting-related raw text to be processed.")
    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(
        default="demo_workspace", description="Optional workspace identifier."
    )
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether the item may later be written into long-term memory.",
    )
    source_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Auxiliary metadata attached by the caller."
    )


class IngestLinkRequest(BaseModel):
    """Payload for link ingest requests with optional manual text override."""

    url: str = Field(description="Original recruiting link.")
    raw_text: str | None = Field(
        default=None,
        description="Optional extracted body text. If absent, the URL itself is processed.",
    )
    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether the item may later be written into long-term memory.",
    )


class IngestImageRequest(BaseModel):
    """Payload for image ingest requests using manual OCR override text."""

    file_name: str = Field(description="Original image file name or reference.")
    ocr_text: str = Field(
        description="OCR result text. Real OCR integration will replace this later."
    )
    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether the item may later be written into long-term memory.",
    )


class IngestResult(BaseModel):
    """Compact workflow result returned by ingest endpoints."""

    item_id: str | None = Field(default=None, description="Normalized item id.")
    status: str = Field(description="Workflow status after processing.")
    card: RenderedItemCard | None = Field(
        default=None, description="Card payload rendered for list views."
    )
    reminder_count: int = Field(description="Number of planned reminders.")
    model_routing: dict[str, Any] = Field(
        default_factory=dict, description="Model routing decisions recorded by the workflow."
    )


class AutoIngestRequest(BaseModel):
    """Payload for the unified text/link mixed ingest endpoint."""

    content: str = Field(description="Free-form pasted text, links, or a mixed submission.")
    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether the item may later be written into long-term memory.",
    )
    visit_links: bool | None = Field(
        default=None,
        description="Optional override controlling whether detected links should be fetched.",
    )


class AutoIngestResponse(BaseModel):
    """Result returned by the unified mixed-content ingest endpoint."""

    detected_input_kind: str = Field(description="Backend-detected content kind.")
    visited_links: list[str] = Field(default_factory=list)
    analysis_reasons: list[str] = Field(default_factory=list)
    results: list[IngestResult] = Field(default_factory=list)


class BossZhipinJobIngestRequest(BaseModel):
    """Payload for Boss 直聘岗位详情接入。"""

    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether the item may later be written into long-term memory.",
    )
    payload: BossZhipinJobPayload = Field(description="Boss 直聘岗位详情原始结构化数据。")


class BossZhipinConversationIngestRequest(BaseModel):
    """Payload for Boss 直聘 HR 对话接入。"""

    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    memory_write_mode: MemoryWriteMode = Field(
        default=MemoryWriteMode.CONTEXT_ONLY,
        description="Whether the item may later be written into long-term memory.",
    )
    payload: BossZhipinConversationPayload = Field(
        description="Boss 直聘 HR 对话原始结构化数据。"
    )


class ItemListResponse(BaseModel):
    """List payload for `GET /items`."""

    items: list[RenderedItemCard] = Field(
        default_factory=list, description="Rendered cards for all stored items."
    )


class ItemDetailResponse(BaseModel):
    """Detail payload for `GET /items/{id}`."""

    item: AgentState = Field(description="Full stored workflow state.")


class ReminderListResponse(BaseModel):
    """List payload for `GET /reminders`."""

    reminders: list[ReminderTask] = Field(
        default_factory=list, description="All reminder tasks in the queue."
    )


class MemoryResponse(BaseModel):
    """Payload returned by memory update endpoints."""

    profile_memory: ProfileMemory | None = Field(
        default=None, description="Profile memory snapshot after update."
    )
    career_state_memory: CareerStateMemory | None = Field(
        default=None, description="Career-state memory snapshot after update."
    )


class ProfileMemoryWriteRequest(BaseModel):
    """User-friendly request body for profile-memory writes."""

    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    target_roles: list[str] = Field(default_factory=list)
    priority_domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    location_preferences: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    summary: str | None = Field(default=None)


class CareerStateMemoryWriteRequest(BaseModel):
    """User-friendly request body for career-state-memory writes."""

    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    watched_companies: list[str] = Field(default_factory=list)
    market_watch_sources: list[str] = Field(default_factory=list)
    market_article_fetch_limit: int = Field(default=5, ge=1, le=20)
    today_focus: list[str] = Field(default_factory=list)
    active_priorities: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None)


class MarketRefreshRequest(BaseModel):
    """Request body used by manual or scheduled market refresh flows."""

    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    input_link: str | None = Field(
        default=None,
        description="Optional one-off link that should be refreshed into a market card immediately.",
    )
    force: bool = Field(
        default=False,
        description="Whether to refresh even when the next mandatory update is not yet due.",
    )


class MarketRefreshResponse(BaseModel):
    """Response returned by market refresh endpoints."""

    refreshed: bool = Field(description="Whether a refresh actually ran.")
    reason: str = Field(description="Human-readable explanation for the refresh decision.")
    refreshed_count: int = Field(description="How many market cards were generated.")
    last_market_refresh_at: datetime | None = Field(
        default=None,
        description="Most recent successful market refresh time.",
    )
    results: list[IngestResult] = Field(default_factory=list)


class ChatQueryRequest(BaseModel):
    """Minimal chat query payload for the current scaffold."""

    query: str = Field(description="User follow-up question based on processed items.")
    item_id: str | None = Field(
        default=None, description="Optional item id to constrain the answer context."
    )
    recent_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="How many recent days of cards should be considered when no item is pinned.",
    )
    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")


class ChatCitation(BaseModel):
    """Grounding citation returned by the RAG chat endpoint."""

    doc_id: str = Field(description="Retrieved document identifier.")
    item_id: str | None = Field(default=None, description="Underlying item id when present.")
    source_label: str = Field(description="Human-readable source label.")
    snippet: str = Field(description="Compact snippet shown to the user.")
    score: float = Field(description="Final retrieval or rerank score.")


class ChatQueryResponse(BaseModel):
    """Minimal rule-based chat response payload."""

    answer: str = Field(description="Assistant answer returned to the client.")
    supporting_item_ids: list[str] = Field(
        default_factory=list, description="Items used to ground the answer."
    )
    citations: list[ChatCitation] = Field(
        default_factory=list,
        description="Grounding citations surfaced to the user interface.",
    )
    retrieval_mode: str = Field(
        default="local_lexical",
        description="Which retrieval path produced the final context set.",
    )


class ProjectSelfMemoryWriteRequest(BaseModel):
    """Request body for the experimental project-self-memory API."""

    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")
    name: str = Field(description="Project name.")
    summary: str = Field(description="Short project summary.")
    role: str | None = Field(default=None, description="User role in the project.")
    tech_stack: list[str] = Field(default_factory=list)
    highlight_points: list[str] = Field(default_factory=list)
    interview_story_hooks: list[str] = Field(default_factory=list)


class FeatureFlagsResponse(BaseModel):
    """Expose runtime feature-flag state to the client."""

    enable_project_self_memory: bool = Field(
        description="Whether the experimental project-self-memory feature is enabled."
    )


class ItemUpdateRequest(BaseModel):
    """Request body for manually editing one stored card."""

    summary_one_line: str | None = Field(default=None)
    company: str | None = Field(default=None)
    role: str | None = Field(default=None)
    city: str | None = Field(default=None)
    tags: list[str] | None = Field(default=None)
    priority: PriorityLevel | None = Field(default=None)
    content_category: ContentCategory | None = Field(default=None)
    ddl: datetime | None = Field(default=None)
    interview_time: datetime | None = Field(default=None)
    event_time: datetime | None = Field(default=None)


class DeleteItemResponse(BaseModel):
    """Response payload for one delete action."""

    item_id: str = Field(description="Identifier of the deleted item.")


class BatchDeleteItemsRequest(BaseModel):
    """Request body for deleting multiple cards in one operation."""

    item_ids: list[str] = Field(
        min_length=1,
        description="Identifiers of the items selected for deletion.",
    )


class BatchDeleteItemsResponse(BaseModel):
    """Response payload for one batch delete operation."""

    deleted_item_ids: list[str] = Field(default_factory=list)
    missing_item_ids: list[str] = Field(default_factory=list)


class BatchAnalyzeItemsRequest(BaseModel):
    """Request body for deeper analysis over selected cards."""

    item_ids: list[str] = Field(
        min_length=1,
        description="Identifiers of the items selected for further analysis.",
    )
    question: str | None = Field(
        default=None,
        description="Optional custom analysis prompt for the selected cards.",
    )
    user_id: str = Field(default="demo_user", description="Logical user identifier.")
    workspace_id: str | None = Field(default="demo_workspace")


class BatchAnalyzeItemsResponse(BaseModel):
    """Response payload for one batch analysis operation."""

    analysis: str = Field(description="Deeper analysis generated from the selected cards.")
    analyzed_item_ids: list[str] = Field(default_factory=list)
    missing_item_ids: list[str] = Field(default_factory=list)
    retrieval_mode: str = Field(default="batch_fallback")
