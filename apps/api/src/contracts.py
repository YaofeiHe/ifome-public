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


class UnifiedAttachmentResult(BaseModel):
    """One attachment converted to text before entering the workflow."""

    display_name: str = Field(description="Human-readable attachment label.")
    source_ref: str = Field(description="Original uploaded file name or local path.")
    source_type: str = Field(description="Source type used for downstream workflow runs.")
    extraction_kind: str = Field(description="How the attachment was converted into text.")
    text_length: int = Field(description="Character length of the extracted text.")


class UnifiedIngestResponse(BaseModel):
    """Result returned by the single-composer unified ingest endpoint."""

    detected_input_kind: str = Field(description="Aggregate input kind after text/path/file merge.")
    visited_links: list[str] = Field(default_factory=list)
    analysis_reasons: list[str] = Field(default_factory=list)
    results: list[IngestResult] = Field(default_factory=list)
    attachments: list[UnifiedAttachmentResult] = Field(default_factory=list)
    resolved_local_paths: list[str] = Field(default_factory=list)


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


class RuntimeProviderSettingsPayload(BaseModel):
    """Client-facing runtime settings payload for one provider section."""

    enabled: bool = Field(default=False)
    api_key: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    model: str | None = Field(default=None)
    fallback_models: list[str] = Field(default_factory=list)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)


class RuntimeOCRSettingsPayload(BaseModel):
    """Client-facing runtime settings payload for OCR."""

    enabled: bool = Field(default=False)
    provider_label: str = Field(default="Qwen-VL-OCR")
    api_key: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    model: str | None = Field(default="qwen-vl-ocr")
    request_timeout_seconds: int = Field(default=60, ge=1, le=300)


class SourceFileSettingsPayload(BaseModel):
    """Client-facing runtime settings payload for source file retention."""

    max_age_days: int = Field(default=30, ge=1, le=3650)
    max_total_size_mb: int = Field(default=2048, ge=64, le=102400)
    delete_when_item_deleted: bool = Field(default=True)
    filter_patterns: list[str] = Field(default_factory=list)


class RuntimeSettingsResponse(BaseModel):
    """Local runtime settings returned to the dedicated settings page."""

    llm: RuntimeProviderSettingsPayload = Field(
        default_factory=RuntimeProviderSettingsPayload
    )
    ocr: RuntimeOCRSettingsPayload = Field(default_factory=RuntimeOCRSettingsPayload)
    source_files: SourceFileSettingsPayload = Field(default_factory=SourceFileSettingsPayload)


class RuntimeSettingsUpdateRequest(BaseModel):
    """Request body for updating local runtime settings."""

    llm: RuntimeProviderSettingsPayload = Field(
        default_factory=RuntimeProviderSettingsPayload
    )
    ocr: RuntimeOCRSettingsPayload = Field(default_factory=RuntimeOCRSettingsPayload)
    source_files: SourceFileSettingsPayload = Field(default_factory=SourceFileSettingsPayload)


class SourceFileCleanupReport(BaseModel):
    """Summary returned after one source file cleanup pass."""

    trigger: str = Field(default="manual")
    scanned_file_count: int = Field(default=0)
    deleted_file_count: int = Field(default=0)
    reclaimed_bytes: int = Field(default=0)
    remaining_bytes: int = Field(default=0)
    deleted_orphan_file_count: int = Field(default=0)
    deleted_due_to_age_count: int = Field(default=0)
    deleted_due_to_size_count: int = Field(default=0)
    deleted_due_to_filter_count: int = Field(default=0)
    deleted_paths: list[str] = Field(default_factory=list)


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
    apply_memory_updates: bool = Field(
        default=True,
        description="Whether the chat flow may persist low-risk profile and career updates.",
    )


class ChatCitation(BaseModel):
    """Grounding citation returned by the RAG chat endpoint."""

    doc_id: str = Field(description="Retrieved document identifier.")
    item_id: str | None = Field(default=None, description="Underlying item id when present.")
    source_label: str = Field(description="Human-readable source label.")
    snippet: str = Field(description="Compact snippet shown to the user.")
    score: float = Field(description="Final retrieval or rerank score.")


class ChatQueryPlan(BaseModel):
    """Preprocessed chat intent and retrieval hints."""

    intent: str = Field(default="general_grounded_chat")
    search_hints: list[str] = Field(default_factory=list)
    rewritten_query: str | None = Field(default=None)
    retrieval_queries: list[str] = Field(default_factory=list)
    web_search_queries: list[str] = Field(default_factory=list)
    profile_update_hints: list[str] = Field(default_factory=list)
    career_update_hints: list[str] = Field(default_factory=list)
    should_update_memory: bool = Field(default=False)
    needs_resume: bool = Field(default=False)
    recent_days: int = Field(default=30)


class ChatMemoryUpdate(BaseModel):
    """Summary of memory fields updated during chat preprocessing."""

    applied: bool = Field(default=False)
    profile_fields: list[str] = Field(default_factory=list)
    career_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ChatAttachmentDiagnostic(BaseModel):
    """One chat attachment processed before retrieval."""

    display_name: str = Field(description="Human-readable attachment name.")
    source_ref: str = Field(description="Original attachment reference.")
    extraction_kind: str = Field(description="How the attachment text was extracted.")
    attachment_kind: str = Field(
        default="document",
        description="Lightweight classifier such as resume or document.",
    )
    summary: str = Field(
        default="",
        description="Compact summary of what the attachment mainly says.",
    )
    persisted_to_profile: bool = Field(
        default=False,
        description="Whether this attachment was written into long-term profile memory.",
    )
    text_length: int = Field(description="Character length of extracted attachment text.")
    processing_error: str | None = Field(
        default=None,
        description="Attachment processing error when text extraction did not succeed.",
    )


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
    query_plan: ChatQueryPlan | None = Field(
        default=None,
        description="Preprocessed task intent and retrieval hints for debugging.",
    )
    memory_update: ChatMemoryUpdate | None = Field(
        default=None,
        description="Summary of conservative memory updates applied during chat.",
    )
    attachments: list[ChatAttachmentDiagnostic] = Field(
        default_factory=list,
        description="Files or local paths processed specifically for this chat turn.",
    )


class ChatSessionTurn(BaseModel):
    """One turn snapshot used for client-side conversation summarization."""

    mode: str = Field(default="grounded_chat")
    user_message: str = Field(description="User or Boss message shown in the thread.")
    answer: str = Field(description="Assistant answer or suggested reply.")
    strategy: str | None = Field(
        default=None,
        description="Optional strategy notes for Boss reply simulation turns.",
    )


class ChatSessionSummaryRequest(BaseModel):
    """Request body for compressing one stored chat conversation."""

    mode: str = Field(default="grounded_chat")
    turns: list[ChatSessionTurn] = Field(default_factory=list)
    conversation_title: str | None = Field(default=None)


class ChatSessionSummaryResponse(BaseModel):
    """Compressed metadata used to render archived chat conversations."""

    title: str = Field(description="Short archived conversation title.")
    summary: str = Field(description="Compact archived conversation summary.")
    keywords: list[str] = Field(default_factory=list)
    compressed_transcript: str = Field(
        default="",
        description="Compressed conversation context used for lightweight reload.",
    )
    summary_source: str = Field(
        default="heuristic",
        description="Whether the summary came from local fallback or live LLM compression.",
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
    deleted_item_ids: list[str] = Field(
        default_factory=list,
        description="Identifiers removed by this delete, including cascade-deleted children.",
    )


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
