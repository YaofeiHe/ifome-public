"""FastAPI entrypoint for the job information flow agent POC."""

from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from apps.api.src.contracts import (
    ApiEnvelope,
    AutoIngestRequest,
    AutoIngestResponse,
    BatchAnalyzeItemsRequest,
    BatchAnalyzeItemsResponse,
    BatchDeleteItemsRequest,
    BatchDeleteItemsResponse,
    BossZhipinConversationIngestRequest,
    BossZhipinJobIngestRequest,
    CareerStateMemoryWriteRequest,
    ChatCitation,
    ChatQueryRequest,
    ChatQueryResponse,
    DeleteItemResponse,
    FeatureFlagsResponse,
    IngestImageRequest,
    IngestLinkRequest,
    IngestResult,
    IngestTextRequest,
    ItemUpdateRequest,
    ItemDetailResponse,
    ItemListResponse,
    MarketRefreshRequest,
    MarketRefreshResponse,
    MemoryResponse,
    ProfileMemoryWriteRequest,
    ProjectSelfMemoryWriteRequest,
    ReminderListResponse,
)
from apps.api.src.services import (
    ApiServiceContainer,
    build_career_state_from_write_request,
    build_profile_memory_from_write_request,
)
from core.memory.experimental import ProjectSelfMemoryPayload
from core.schemas import MemoryWriteMode, SourceType

app = FastAPI(
    title="ifome Job Agent API",
    description="Lightweight API scaffold for the job information flow agent.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

services = ApiServiceContainer()


def _ok(data, trace_id: str | None = None) -> ApiEnvelope:
    """Build a success response using the shared envelope."""

    return ApiEnvelope(success=True, data=data, trace_id=trace_id)


@app.get("/health", response_model=ApiEnvelope)
def health_check() -> ApiEnvelope:
    """Return a minimal liveness payload for local development."""

    return _ok({"status": "ok", "stage": "api_step_7"})


@app.post("/ingest/text", response_model=ApiEnvelope)
def ingest_text(payload: IngestTextRequest) -> ApiEnvelope:
    """Process one plain-text recruiting input through the workflow."""

    state = services.ingest(
        raw_input=payload.text,
        source_type=SourceType.TEXT,
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        memory_write_mode=payload.memory_write_mode,
        source_metadata=payload.source_metadata,
    )
    result = IngestResult(
        item_id=state.normalized_item.id if state.normalized_item else None,
        status=state.status.value,
        card=state.render_card,
        reminder_count=len(state.reminder_tasks),
        model_routing=state.model_routing,
    )
    return _ok(result, trace_id=state.trace_id)


@app.post("/ingest/link", response_model=ApiEnvelope)
def ingest_link(payload: IngestLinkRequest) -> ApiEnvelope:
    """Process one recruiting link using fetched page text or caller override text."""

    try:
        state = services.ingest_link(
            url=payload.url,
            raw_text=payload.raw_text,
            user_id=payload.user_id,
            workspace_id=payload.workspace_id,
            memory_write_mode=payload.memory_write_mode,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = IngestResult(
        item_id=state.normalized_item.id if state.normalized_item else None,
        status=state.status.value,
        card=state.render_card,
        reminder_count=len(state.reminder_tasks),
        model_routing=state.model_routing,
    )
    return _ok(result, trace_id=state.trace_id)


@app.post("/ingest/auto", response_model=ApiEnvelope)
def ingest_auto(payload: AutoIngestRequest) -> ApiEnvelope:
    """Process one free-form submission that may contain text, links, or both."""

    try:
        analysis, states = services.ingest_auto(
            content=payload.content,
            user_id=payload.user_id,
            workspace_id=payload.workspace_id,
            memory_write_mode=payload.memory_write_mode,
            visit_links=payload.visit_links,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    results = [
        IngestResult(
            item_id=state.normalized_item.id if state.normalized_item else None,
            status=state.status.value,
            card=state.render_card,
            reminder_count=len(state.reminder_tasks),
            model_routing=state.model_routing,
        )
        for state in states
    ]
    return _ok(
        AutoIngestResponse(
            detected_input_kind=analysis.input_kind,
            visited_links=analysis.urls if analysis.should_visit_links else [],
            analysis_reasons=analysis.reasons,
            results=results,
        ),
        trace_id=states[0].trace_id if states else None,
    )


@app.post("/integrations/boss-zhipin/job", response_model=ApiEnvelope)
def ingest_boss_zhipin_job(payload: BossZhipinJobIngestRequest) -> ApiEnvelope:
    """Process one Boss 直聘岗位详情 payload through the shared workflow."""

    state = services.ingest_boss_job(
        payload=payload.payload,
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        memory_write_mode=payload.memory_write_mode,
    )
    result = IngestResult(
        item_id=state.normalized_item.id if state.normalized_item else None,
        status=state.status.value,
        card=state.render_card,
        reminder_count=len(state.reminder_tasks),
        model_routing=state.model_routing,
    )
    return _ok(result, trace_id=state.trace_id)


@app.post("/integrations/boss-zhipin/conversation", response_model=ApiEnvelope)
def ingest_boss_zhipin_conversation(
    payload: BossZhipinConversationIngestRequest,
) -> ApiEnvelope:
    """Process one Boss 直聘 HR conversation payload through the shared workflow."""

    state = services.ingest_boss_conversation(
        payload=payload.payload,
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        memory_write_mode=payload.memory_write_mode,
    )
    result = IngestResult(
        item_id=state.normalized_item.id if state.normalized_item else None,
        status=state.status.value,
        card=state.render_card,
        reminder_count=len(state.reminder_tasks),
        model_routing=state.model_routing,
    )
    return _ok(result, trace_id=state.trace_id)


@app.post("/ingest/image", response_model=ApiEnvelope)
def ingest_image(payload: IngestImageRequest) -> ApiEnvelope:
    """Process one image input using caller-provided OCR text override."""

    state = services.ingest(
        raw_input=payload.ocr_text,
        source_type=SourceType.IMAGE,
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        source_ref=payload.file_name,
        memory_write_mode=payload.memory_write_mode,
        source_metadata={"source_kind": "image", "file_name": payload.file_name},
    )
    result = IngestResult(
        item_id=state.normalized_item.id if state.normalized_item else None,
        status=state.status.value,
        card=state.render_card,
        reminder_count=len(state.reminder_tasks),
        model_routing=state.model_routing,
    )
    return _ok(result, trace_id=state.trace_id)


@app.post("/ingest/image-file", response_model=ApiEnvelope)
async def ingest_image_file(
    file: UploadFile = File(...),
    user_id: str = Form("demo_user"),
    workspace_id: str | None = Form("demo_workspace"),
    memory_write_mode: MemoryWriteMode = Form(MemoryWriteMode.CONTEXT_ONLY),
) -> ApiEnvelope:
    """Process one uploaded image by running local OCR before the workflow."""

    try:
        payload_bytes = await file.read()
        state = services.ingest_image_file(
            file_name=file.filename or "upload.png",
            file_bytes=payload_bytes,
            user_id=user_id,
            workspace_id=workspace_id,
            memory_write_mode=memory_write_mode,  # validated below
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = IngestResult(
        item_id=state.normalized_item.id if state.normalized_item else None,
        status=state.status.value,
        card=state.render_card,
        reminder_count=len(state.reminder_tasks),
        model_routing=state.model_routing,
    )
    return _ok(result, trace_id=state.trace_id)


@app.get("/items", response_model=ApiEnvelope)
def list_items(
    user_id: str = "demo_user",
    workspace_id: str | None = "demo_workspace",
) -> ApiEnvelope:
    """Return all processed item cards."""

    cards = [
        state.render_card
        for state in services.list_items(user_id=user_id, workspace_id=workspace_id)
        if state.render_card is not None
    ]
    return _ok(ItemListResponse(items=cards))


@app.get("/items/{item_id}", response_model=ApiEnvelope)
def get_item(item_id: str) -> ApiEnvelope:
    """Return one full processed workflow state by item id."""

    state = services.get_item(item_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found.")
    return _ok(ItemDetailResponse(item=state), trace_id=state.trace_id)


@app.patch("/items/{item_id}", response_model=ApiEnvelope)
def update_item(item_id: str, payload: ItemUpdateRequest) -> ApiEnvelope:
    """Apply a manual edit to one stored card."""

    state = services.update_item(
        item_id=item_id,
        summary_one_line=payload.summary_one_line,
        company=payload.company,
        role=payload.role,
        city=payload.city,
        tags=payload.tags,
        priority=payload.priority,
        content_category=payload.content_category,
        ddl=payload.ddl,
        interview_time=payload.interview_time,
        event_time=payload.event_time,
    )
    if state is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found.")
    return _ok(ItemDetailResponse(item=state), trace_id=state.trace_id)


@app.delete("/items/{item_id}", response_model=ApiEnvelope)
def delete_item(item_id: str) -> ApiEnvelope:
    """Delete one stored card and its reminders."""

    deleted = services.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found.")
    return _ok(DeleteItemResponse(item_id=item_id))


@app.post("/items/batch-delete", response_model=ApiEnvelope)
def batch_delete_items(payload: BatchDeleteItemsRequest) -> ApiEnvelope:
    """Delete multiple stored cards and their reminders."""

    deleted_item_ids, missing_item_ids = services.delete_items(payload.item_ids)
    if not deleted_item_ids and missing_item_ids:
        raise HTTPException(status_code=404, detail="No selected items were found.")
    return _ok(
        BatchDeleteItemsResponse(
            deleted_item_ids=deleted_item_ids,
            missing_item_ids=missing_item_ids,
        )
    )


@app.post("/items/batch-analyze", response_model=ApiEnvelope)
def batch_analyze_items(payload: BatchAnalyzeItemsRequest) -> ApiEnvelope:
    """Run deeper analysis over multiple selected cards."""

    analysis, analyzed_item_ids, missing_item_ids, retrieval_mode = services.analyze_items(
        item_ids=payload.item_ids,
        question=payload.question,
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
    )
    if not analyzed_item_ids and missing_item_ids:
        raise HTTPException(status_code=404, detail="No selected items were found.")
    return _ok(
        BatchAnalyzeItemsResponse(
            analysis=analysis,
            analyzed_item_ids=analyzed_item_ids,
            missing_item_ids=missing_item_ids,
            retrieval_mode=retrieval_mode,
        )
    )


@app.get("/reminders", response_model=ApiEnvelope)
def list_reminders() -> ApiEnvelope:
    """Return all reminder tasks currently stored."""

    return _ok(ReminderListResponse(reminders=services.list_reminders()))


@app.post("/memory/profile", response_model=ApiEnvelope)
def upsert_profile_memory(payload: ProfileMemoryWriteRequest) -> ApiEnvelope:
    """Replace profile memory for one user scope."""

    profile_memory = build_profile_memory_from_write_request(
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        target_roles=payload.target_roles,
        priority_domains=payload.priority_domains,
        skills=payload.skills,
        location_preferences=payload.location_preferences,
        soft_preferences=payload.soft_preferences,
        excluded_companies=payload.excluded_companies,
        summary=payload.summary,
    )
    profile, career = services.upsert_profile_memory(profile_memory)
    return _ok(MemoryResponse(profile_memory=profile, career_state_memory=career))


@app.post("/memory/career-state", response_model=ApiEnvelope)
def upsert_career_state_memory(payload: CareerStateMemoryWriteRequest) -> ApiEnvelope:
    """Replace career-state memory for one user scope."""

    career_state = build_career_state_from_write_request(
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        watched_companies=payload.watched_companies,
        market_watch_sources=payload.market_watch_sources,
        market_article_fetch_limit=payload.market_article_fetch_limit,
        today_focus=payload.today_focus,
        active_priorities=payload.active_priorities,
        notes=payload.notes,
    )
    profile, career = services.upsert_career_state_memory(career_state)
    return _ok(MemoryResponse(profile_memory=profile, career_state_memory=career))


@app.post("/market/refresh", response_model=ApiEnvelope)
def refresh_market(payload: MarketRefreshRequest) -> ApiEnvelope:
    """Refresh market information cards from one-off or remembered watch sources."""

    refreshed, reason, states, last_market_refresh_at = services.refresh_market_watch(
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        input_link=payload.input_link,
        force=payload.force,
    )
    results = [
        IngestResult(
            item_id=state.normalized_item.id if state.normalized_item else None,
            status=state.status.value,
            card=state.render_card,
            reminder_count=len(state.reminder_tasks),
            model_routing=state.model_routing,
        )
        for state in states
    ]
    return _ok(
        MarketRefreshResponse(
            refreshed=refreshed,
            reason=reason,
            refreshed_count=len(results),
            last_market_refresh_at=last_market_refresh_at,
            results=results,
        ),
        trace_id=states[0].trace_id if states else None,
    )


@app.post("/chat/query", response_model=ApiEnvelope)
def chat_query(payload: ChatQueryRequest) -> ApiEnvelope:
    """Answer one minimal follow-up question grounded in stored workflow data."""

    answer, supporting_item_ids, citations, retrieval_mode = services.chat_query(
        query=payload.query,
        user_id=payload.user_id,
        workspace_id=payload.workspace_id,
        item_id=payload.item_id,
        recent_days=payload.recent_days,
    )
    return _ok(
        ChatQueryResponse(
            answer=answer,
            supporting_item_ids=supporting_item_ids,
            citations=[
                ChatCitation(
                    doc_id=citation.doc_id,
                    item_id=citation.item_id,
                    source_label=citation.source_label,
                    snippet=citation.snippet,
                    score=round(citation.score, 4),
                )
                for citation in citations
            ],
            retrieval_mode=retrieval_mode,
        )
    )


@app.get("/experimental/flags", response_model=ApiEnvelope)
def get_experimental_flags() -> ApiEnvelope:
    """Expose the current state of experimental feature flags."""

    return _ok(FeatureFlagsResponse(**services.get_feature_flags()))


@app.post("/experimental/project-self-memory", response_model=ApiEnvelope)
def write_project_self_memory(payload: ProjectSelfMemoryWriteRequest) -> ApiEnvelope:
    """Write one project entry into long-term memory behind a feature flag."""

    try:
        profile, career = services.write_project_self_memory(
            user_id=payload.user_id,
            workspace_id=payload.workspace_id,
            payload=ProjectSelfMemoryPayload(
                name=payload.name,
                summary=payload.summary,
                role=payload.role,
                tech_stack=payload.tech_stack,
                highlight_points=payload.highlight_points,
                interview_story_hooks=payload.interview_story_hooks,
            ),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return _ok(MemoryResponse(profile_memory=profile, career_state_memory=career))
