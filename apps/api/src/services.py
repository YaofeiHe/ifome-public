"""Application services wiring the API layer to the workflow scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from core.chat import RAGChatService
from core.extraction.parse import extract_all_datetimes, extract_city, pick_next_datetime
from core.graph import JobWorkflow, create_initial_state
from core.memory.experimental import ProjectSelfMemoryPayload, ProjectSelfMemoryService
from core.runtime.dependencies import WorkflowDependencies
from core.runtime.settings import AppSettings
from core.runtime.time import now_in_project_timezone
from core.schemas import (
    AgentState,
    CareerStateMemory,
    ContentCategory,
    HardFilter,
    MemoryWriteMode,
    PriorityLevel,
    ProfileMemory,
    RenderedItemCard,
    SourceType,
)
from core.tools import LLMGatewayError, fetch_recent_site_titles
from integrations.boss_zhipin import (
    BossZhipinConversationPayload,
    BossZhipinJobPayload,
    render_conversation_metadata,
    render_conversation_text,
    render_job_posting_metadata,
    render_job_posting_text,
)

URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
DOMAIN_PATTERN = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s]*)?\b")
ORG_SUFFIX_PATTERN = re.compile(
    r"([A-Za-z0-9\u4e00-\u9fff]{2,24}(?:集团|公司|科技|网络|智能|云|游戏|互娱|电商|零售|物流|金融|能源|汽车))"
)
SEASON_TAGS = ("暑期实习", "日常实习", "实习", "秋招", "校招", "春招", "社招")
TOPIC_MARKER_PATTERN = re.compile(r"#?\s*([A-Za-z0-9\u4e00-\u9fff]{2,18})(?:相关|方向|赛道)")
NON_SECTION_BRACKET_TITLES = {
    "内推链接",
    "内推码",
    "面向对象",
    "地点",
    "工作地点",
    "岗位职责",
    "岗位要求",
    "投递方式",
}
SEARCH_INSTRUCTION_PATTERNS = (
    "请在网页上搜索",
    "请先搜索",
    "先搜索",
    "帮我搜索",
    "搜索有关内容",
    "搜索相关内容",
    "网页上搜索",
)
GENERIC_KEYWORD_HINTS = {
    "岗位类别",
    "面向人群",
    "投递规则",
    "工作地点",
    "招聘流程",
    "投递方式",
    "校招官网",
    "春季",
    "春季校招",
    "校园",
    "招聘",
    "岗位",
    "投递",
}
MARKET_ARTICLE_FETCH_LIMIT = 5
MARKET_VALUE_KEYWORDS = (
    "发布",
    "上线",
    "开源",
    "融资",
    "收购",
    "产品",
    "平台",
    "模型",
    "智能体",
    "agent",
    "评测",
    "工具",
    "开发",
    "工程化",
    "工作流",
    "生态",
    "落地",
    "企业",
    "应用",
    "训练",
    "推理",
    "芯片",
    "机器人",
    "自动驾驶",
    "多模态",
)


@dataclass(frozen=True)
class SubmissionAnalysis:
    """Normalized view of one pasted input before the workflow is invoked."""

    input_kind: str
    context_text: str
    urls: list[str]
    should_visit_links: bool
    reasons: list[str]
    keyword_hints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SubmissionSection:
    """One logical recruiting section split from a mixed pasted submission."""

    section_title: str
    section_text: str
    urls: list[str]
    semantic_tags: list[str]
    role_variants: list[str]
    relationship_family: str | None = None
    relationship_stage: str | None = None
    primary_unit: str | None = None
    identity_tag: str | None = None


@dataclass(frozen=True)
class MarketArticleCandidate:
    """One title-level market article candidate before or after正文抓取."""

    url: str
    title: str
    snippet: str
    relevance_score: float
    llm_score: float
    market_value_score: float
    diversity_gap_score: float
    title_score: float
    brief: str
    reason: str
    selection_mode: str = "keyword"
    candidate_source: str = "search"
    published_at: str | None = None


@dataclass
class ApiServiceContainer:
    """
    Shared service container for the minimal API.

    Responsibilities:
    - Hold one shared dependency graph for the whole FastAPI process.
    - Expose helpers to ingest items, read stored states, update memory, and chat.

    Non-responsibilities:
    - HTTP request validation.
    - Durable multi-process storage.
    """

    dependencies: WorkflowDependencies = field(default_factory=WorkflowDependencies)
    settings: AppSettings = field(default_factory=AppSettings.from_env)
    project_self_memory_service: ProjectSelfMemoryService = field(
        default_factory=ProjectSelfMemoryService
    )

    def __post_init__(self) -> None:
        self.workflow = JobWorkflow(self.dependencies)
        self.chat_service = RAGChatService(
            dependencies=self.dependencies,
            settings=self.settings,
        )

    def ingest(
        self,
        *,
        raw_input: str,
        source_type: SourceType,
        user_id: str,
        workspace_id: str | None,
        source_ref: str | None = None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
        source_metadata: dict | None = None,
    ) -> AgentState:
        """Run the workflow for one input and return the full workflow state."""

        initial_state = create_initial_state(
            raw_input=raw_input,
            source_type=source_type,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            memory_write_mode=memory_write_mode,
            source_metadata=source_metadata or {},
        )
        final_state = self.workflow.invoke(initial_state, prefer_langgraph=True)

        # The graph follows `persist -> render` to match the design doc. After the
        # workflow finishes, we refresh the repository with the final rendered
        # state so read APIs can expose the latest card payload.
        if final_state.normalized_item is not None:
            self.dependencies.workflow_repository.save(final_state)

        return final_state

    def ingest_link(
        self,
        *,
        url: str,
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
        raw_text: str | None = None,
    ) -> AgentState:
        """Ingest one link, fetching real page text when no override is provided."""

        source_metadata: dict = {"source_kind": "link"}
        effective_text = raw_text
        if raw_text:
            source_metadata["fetch_method"] = "caller_override"
        else:
            extracted_page = self.dependencies.web_page_client.fetch(url)
            effective_text = extracted_page.text
            source_metadata.update(extracted_page.source_metadata)

        return self.ingest(
            raw_input=effective_text or url,
            source_type=SourceType.LINK,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=url,
            memory_write_mode=memory_write_mode,
            source_metadata=source_metadata,
        )

    def ingest_auto(
        self,
        *,
        content: str,
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
        visit_links: bool | None = None,
    ) -> tuple[SubmissionAnalysis, list[AgentState]]:
        """Analyze mixed pasted input and fan out into one or more workflow runs."""

        analysis = self.analyze_submission(content, visit_links=visit_links)
        search_references = self._collect_search_references(
            content=content,
            analysis=analysis,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        keyword_hints = self._discover_keyword_hints(
            content,
            analysis,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        analysis = SubmissionAnalysis(
            input_kind=analysis.input_kind,
            context_text=analysis.context_text,
            urls=analysis.urls,
            should_visit_links=analysis.should_visit_links,
            reasons=[
                *analysis.reasons,
                "keyword hints expanded before section extraction" if keyword_hints else "no external keyword expansion",
                "explicit web search references attached" if search_references else "no explicit web search references",
            ],
            keyword_hints=keyword_hints,
        )
        shared_context, sections = self._split_submission_sections(
            content,
            keyword_hints=keyword_hints,
        )
        shared_exam_dates = self._extract_shared_exam_dates(shared_context or content)
        next_shared_exam_date = pick_next_datetime(shared_exam_dates)
        states: list[AgentState] = []
        fetch_cache: dict[str, tuple[str, dict]] = {}
        visited_urls: list[str] = []
        proactive_fetch = analysis.input_kind == "link" or self._has_sparse_context(analysis.context_text)

        if sections:
            for section in sections:
                if self._is_collection_only_section(section):
                    continue
                variants = self._expand_section_variants(section)
                for variant in variants:
                    fetched_texts: list[str] = []
                    fetched_metadata: dict = {}
                    fetch_plans = [
                        self._build_fetch_plan(
                            url=url,
                            shared_context=shared_context,
                            section_text=variant["section_text"],
                            source_title=str(variant["source_title"]),
                            role_variant=variant["role_variant"],
                        )
                        for url in variant["urls"]
                    ]
                    for url in variant["urls"]:
                        if not self._should_visit_url(
                            url=url,
                            shared_context=shared_context,
                            section_text=variant["section_text"],
                            visit_links=visit_links,
                            force_visit=proactive_fetch,
                        ):
                            continue
                        try:
                            if url not in fetch_cache:
                                extracted_page = self.dependencies.web_page_client.fetch(url)
                                fetch_cache[url] = (
                                    extracted_page.text,
                                    extracted_page.source_metadata,
                                )
                            fetched_text, page_metadata = fetch_cache[url]
                            visited_urls.append(url)
                            fetched_metadata = {
                                **fetched_metadata,
                                **page_metadata,
                            }
                            fetched_texts.extend(
                                self._select_relevant_fetched_segments(
                                    section_title=str(variant["source_title"]),
                                    section_text=variant["section_text"],
                                    role_variant=variant["role_variant"],
                                    keyword_hints=keyword_hints,
                                    fetched_segments=self._split_link_payload(fetched_text),
                                )
                            )
                        except Exception:
                            continue

                    source_ref = variant["urls"][0] if variant["urls"] else None
                    source_type = SourceType.LINK if source_ref else SourceType.TEXT
                    states.append(
                        self.ingest(
                            raw_input=self._compose_contextual_payload(
                                source_title=str(variant["source_title"]),
                                shared_context=self._select_shared_context_for_candidate(
                                    shared_context=shared_context,
                                    semantic_tags=variant["semantic_tags"],
                                    keyword_hints=keyword_hints,
                                ),
                                section_text=variant["section_text"],
                                relationship_tags=variant["semantic_tags"],
                                keyword_hints=keyword_hints,
                                search_references=search_references,
                                fetched_texts=fetched_texts,
                            ),
                            source_type=source_type,
                            user_id=user_id,
                            workspace_id=workspace_id,
                            source_ref=source_ref,
                            memory_write_mode=memory_write_mode,
                            source_metadata={
                                **fetched_metadata,
                                "source_title": variant["source_title"],
                                "source_kind": source_type.value,
                                "detected_input_kind": analysis.input_kind,
                                "input_urls": analysis.urls,
                                "analysis_reasons": analysis.reasons,
                                "keyword_hints": keyword_hints,
                                "search_references": search_references,
                                "shared_context": shared_context,
                                "shared_exam_dates": [
                                    value.isoformat() for value in shared_exam_dates
                                ],
                                "next_shared_exam_date": (
                                    next_shared_exam_date.isoformat()
                                    if next_shared_exam_date
                                    else None
                                ),
                                "global_deadline": (
                                    next_shared_exam_date.isoformat()
                                    if next_shared_exam_date
                                    else None
                                ),
                                "section_title": section.section_title,
                                "original_section_text": variant["section_text"],
                                "role_variant": variant["role_variant"],
                                "semantic_tags": variant["semantic_tags"],
                                "relationship_tags": variant["semantic_tags"],
                                "relationship_family": variant["relationship_family"],
                                "relationship_stage": variant["relationship_stage"],
                                "primary_unit": variant["primary_unit"],
                                "identity_tag": variant["identity_tag"],
                                "fetch_plan": fetch_plans,
                                "location_pending": self._is_location_pending(
                                    section_text=variant["section_text"],
                                    fetched_texts=fetched_texts,
                                ),
                                "visited_urls": [
                                    url
                                    for url in variant["urls"]
                                    if url in visited_urls
                                ],
                            },
                        )
                    )

            analysis = SubmissionAnalysis(
                input_kind=analysis.input_kind,
                context_text=shared_context or analysis.context_text,
                urls=analysis.urls,
                should_visit_links=analysis.should_visit_links,
                reasons=[
                    *analysis.reasons,
                    f"split into {len(states)} card candidates",
                    "shared context stored separately from role extraction",
                ],
                keyword_hints=keyword_hints,
            )

        if not states:
            fetched_texts: list[str] = []
            fallback_title = "统一输入卡片"
            source_metadata = {
                "detected_input_kind": analysis.input_kind,
                "input_urls": analysis.urls,
                "analysis_reasons": analysis.reasons,
                "keyword_hints": keyword_hints,
                "link_visit_attempted": analysis.should_visit_links,
                "source_title": fallback_title,
                "shared_context": analysis.context_text,
                "shared_exam_dates": [
                    value.isoformat() for value in shared_exam_dates
                ],
                "next_shared_exam_date": (
                    next_shared_exam_date.isoformat() if next_shared_exam_date else None
                ),
                "global_deadline": (
                    next_shared_exam_date.isoformat() if next_shared_exam_date else None
                ),
                "original_section_text": analysis.context_text or content,
            }
            fetch_plans = [
                self._build_fetch_plan(
                    url=url,
                    shared_context=analysis.context_text,
                    section_text=analysis.context_text or content,
                    source_title=fallback_title,
                    role_variant=None,
                )
                for url in analysis.urls
            ]
            if analysis.should_visit_links and analysis.urls:
                for url in analysis.urls:
                    if not self._should_visit_url(
                        url=url,
                        shared_context=analysis.context_text,
                        section_text=analysis.context_text or content,
                        visit_links=visit_links,
                        force_visit=proactive_fetch,
                    ):
                        continue
                    try:
                        extracted_page = self.dependencies.web_page_client.fetch(url)
                        fetched_texts.extend(self._split_link_payload(extracted_page.text))
                        fallback_title = self._derive_fallback_source_title(
                            original_content=content,
                            fetched_texts=fetched_texts,
                            page_title=str(extracted_page.source_metadata.get("page_title") or ""),
                            keyword_hints=keyword_hints,
                        )
                        source_metadata = {
                            **source_metadata,
                            **extracted_page.source_metadata,
                            "source_title": fallback_title,
                            "visited_urls": list(dict.fromkeys([*source_metadata.get("visited_urls", []), url])),
                        }
                    except Exception:
                        continue
            fetch_plans = [
                self._build_fetch_plan(
                    url=url,
                    shared_context=analysis.context_text,
                    section_text=analysis.context_text or content,
                    source_title=fallback_title,
                    role_variant=None,
                )
                for url in analysis.urls
            ]
            fallback_source_type = SourceType.LINK if analysis.input_kind == "link" else SourceType.TEXT
            states.append(
                self.ingest(
                    raw_input=self._compose_contextual_payload(
                        source_title=fallback_title,
                        shared_context=self._select_shared_context_for_candidate(
                            shared_context=analysis.context_text,
                            semantic_tags=[],
                            keyword_hints=keyword_hints,
                        ),
                        section_text=analysis.context_text or content,
                        relationship_tags=[],
                        keyword_hints=keyword_hints,
                        search_references=search_references,
                        fetched_texts=fetched_texts,
                    ),
                    source_type=fallback_source_type,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    source_ref=analysis.urls[0] if analysis.urls else None,
                    memory_write_mode=memory_write_mode,
                    source_metadata={
                        **source_metadata,
                        "search_references": search_references,
                        "fetch_plan": fetch_plans,
                        "location_pending": self._is_location_pending(
                            section_text=analysis.context_text or content,
                            fetched_texts=fetched_texts,
                        ),
                    },
                )
            )

        return analysis, states

    def ingest_image_file(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
    ) -> AgentState:
        """Ingest one uploaded image by running OCR before the workflow."""

        upload_dir = Path("data/runtime/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("._") or "upload.png"
        stored_path = upload_dir / f"{uuid4().hex[:10]}_{safe_name}"
        stored_path.write_bytes(file_bytes)

        ocr_result = self.dependencies.ocr_client.extract_text(stored_path)
        source_metadata = {
            "source_kind": "image",
            "file_name": file_name,
            "stored_path": str(stored_path),
            **ocr_result.source_metadata,
        }

        return self.ingest(
            raw_input=ocr_result.text,
            source_type=SourceType.IMAGE,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=file_name,
            memory_write_mode=memory_write_mode,
            source_metadata=source_metadata,
        )

    def list_items(
        self,
        *,
        user_id: str = "demo_user",
        workspace_id: str | None = "demo_workspace",
    ) -> list[AgentState]:
        """Return all stored workflow states."""

        states = self.dependencies.workflow_repository.list_all(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        for state in states:
            if state.render_card is None and state.normalized_item is not None:
                state.render_card = self._build_fallback_card(state)
        return states

    def get_item(self, item_id: str) -> AgentState | None:
        """Return one stored workflow state by id."""

        state = self.dependencies.workflow_repository.get(item_id)
        if state is not None and state.render_card is None and state.normalized_item is not None:
            state.render_card = self._build_fallback_card(state)
        return state

    def update_item(
        self,
        *,
        item_id: str,
        summary_one_line: str | None = None,
        company: str | None = None,
        role: str | None = None,
        city: str | None = None,
        tags: list[str] | None = None,
        priority: PriorityLevel | None = None,
        content_category: ContentCategory | None = None,
        ddl: datetime | None = None,
        interview_time: datetime | None = None,
        event_time: datetime | None = None,
    ) -> AgentState | None:
        """Apply a manual edit to one stored card."""

        state = self.get_item(item_id)
        if state is None or state.normalized_item is None:
            return None

        if state.extracted_signal is not None:
            if summary_one_line is not None:
                state.extracted_signal.summary_one_line = summary_one_line
            if company is not None:
                state.extracted_signal.company = company
            if role is not None:
                state.extracted_signal.role = role
            if city is not None:
                state.extracted_signal.city = city
            if tags is not None:
                state.extracted_signal.tags = tags
            if content_category is not None:
                state.extracted_signal.category = content_category
            if ddl is not None:
                state.extracted_signal.ddl = ddl
            if interview_time is not None:
                state.extracted_signal.interview_time = interview_time
            if event_time is not None:
                state.extracted_signal.event_time = event_time

        if state.score_result is not None and priority is not None:
            state.score_result.priority = priority

        card = state.render_card or self._build_fallback_card(state)
        if summary_one_line is not None:
            card.summary_one_line = summary_one_line
        if company is not None:
            card.company = company
        if role is not None:
            card.role = role
        if city is not None:
            card.city = city
        if tags is not None:
            card.tags = tags
        if priority is not None:
            card.priority = priority
        if content_category is not None:
            card.content_category = content_category
        if ddl is not None:
            card.ddl = ddl
        if interview_time is not None:
            card.interview_time = interview_time
        if event_time is not None:
            card.event_time = event_time
        card.updated_at = now_in_project_timezone()
        state.render_card = card
        state.persistence_summary["manual_edit"] = True
        self.dependencies.workflow_repository.save(state)
        return state

    def delete_item(self, item_id: str) -> bool:
        """Delete one stored item plus its reminders."""

        state = self.get_item(item_id)
        if state is not None and state.render_card is not None:
            for child_item_id in state.render_card.market_child_item_ids:
                if child_item_id != item_id:
                    self.dependencies.reminder_queue.delete_for_item(child_item_id)
                    self.dependencies.workflow_repository.delete(child_item_id)
        self.dependencies.reminder_queue.delete_for_item(item_id)
        return self.dependencies.workflow_repository.delete(item_id)

    def delete_items(self, item_ids: list[str]) -> tuple[list[str], list[str]]:
        """Delete multiple stored items and return deleted vs missing ids."""

        deleted_item_ids: list[str] = []
        missing_item_ids: list[str] = []
        seen: set[str] = set()

        for item_id in item_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            if self.delete_item(item_id):
                deleted_item_ids.append(item_id)
            else:
                missing_item_ids.append(item_id)

        return deleted_item_ids, missing_item_ids

    def analyze_items(
        self,
        *,
        item_ids: list[str],
        user_id: str,
        workspace_id: str | None,
        question: str | None = None,
    ) -> tuple[str, list[str], list[str], str]:
        """Run one deeper analysis over selected cards using stored raw text."""

        selected_states: list[AgentState] = []
        missing_item_ids: list[str] = []
        seen: set[str] = set()

        for item_id in item_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            state = self.get_item(item_id)
            if state is None:
                missing_item_ids.append(item_id)
                continue
            if state.user_id != user_id or state.workspace_id != workspace_id:
                missing_item_ids.append(item_id)
                continue
            selected_states.append(state)

        if not selected_states:
            return (
                "当前没有可分析的卡片，请先选择至少一张有效卡片。",
                [],
                missing_item_ids,
                "empty",
            )

        effective_question = (
            question.strip()
            if question and question.strip()
            else "请基于这些卡片，分析共同关系、岗位差异、关键DDL、原链接、投递建议和风险。"
        )

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="batch_card_analysis",
                    system_prompt=(
                        "你在分析多张求职信息卡片。"
                        "请严格基于输入卡片内容，综合原文、标准化文本、标签和来源链接。"
                        "只返回 JSON，字段：analysis(string), key_points(array of string)。"
                    ),
                    user_payload={
                        "question": effective_question,
                        "cards": [
                            self._build_batch_analysis_payload(state)
                            for state in selected_states
                        ],
                    },
                )
                analysis = str(response.get("analysis") or "").strip()
                key_points = [
                    str(value).strip()
                    for value in response.get("key_points", [])
                    if str(value).strip()
                ]
                if analysis:
                    if key_points:
                        analysis = analysis + "\n\n重点：\n- " + "\n- ".join(key_points[:6])
                    return (
                        analysis,
                        [
                            state.normalized_item.id
                            for state in selected_states
                            if state.normalized_item is not None
                        ],
                        missing_item_ids,
                        "batch_llm",
                    )
            except (LLMGatewayError, TypeError, ValueError, KeyError):
                pass

        return (
            self._build_batch_analysis_fallback(
                states=selected_states,
                question=effective_question,
            ),
            [
                state.normalized_item.id
                for state in selected_states
                if state.normalized_item is not None
            ],
            missing_item_ids,
            "batch_fallback",
        )

    def ingest_boss_job(
        self,
        *,
        payload: BossZhipinJobPayload,
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
    ) -> AgentState:
        """Ingest one Boss 直聘岗位详情 payload through the shared workflow."""

        source_ref = f"boss_zhipin:job:{payload.job_id}"
        if payload.job_url:
            source_ref = payload.job_url
        return self.ingest(
            raw_input=render_job_posting_text(payload),
            source_type=SourceType.TEXT,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            memory_write_mode=memory_write_mode,
            source_metadata=render_job_posting_metadata(payload),
        )

    def ingest_boss_conversation(
        self,
        *,
        payload: BossZhipinConversationPayload,
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
    ) -> AgentState:
        """Ingest one Boss 直聘 HR conversation payload through the shared workflow."""

        source_ref = f"boss_zhipin:conversation:{payload.thread_id}"
        if payload.job_url:
            source_ref = payload.job_url
        return self.ingest(
            raw_input=render_conversation_text(payload),
            source_type=SourceType.TEXT,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            memory_write_mode=memory_write_mode,
            source_metadata=render_conversation_metadata(payload),
        )

    def list_reminders(self):
        """Return all reminder tasks currently stored."""

        return self.dependencies.reminder_queue.list_tasks()

    def get_feature_flags(self) -> dict[str, bool]:
        """Return runtime feature-flag values used by optional modules."""

        return {
            "enable_project_self_memory": self.settings.feature_flags.enable_project_self_memory
        }

    def upsert_profile_memory(
        self, profile_memory: ProfileMemory
    ) -> tuple[ProfileMemory, CareerStateMemory]:
        """Replace profile memory while preserving current career-state memory."""

        current = self.dependencies.memory_provider.load(
            user_id=profile_memory.user_id,
            workspace_id=profile_memory.workspace_id,
        )
        current["profile_memory"] = profile_memory
        self.dependencies.memory_provider.save(
            {
                "user_id": profile_memory.user_id,
                "workspace_id": profile_memory.workspace_id,
                **current,
            }
        )
        return profile_memory, CareerStateMemory.model_validate(current["career_state_memory"])

    def upsert_career_state_memory(
        self, career_state_memory: CareerStateMemory
    ) -> tuple[ProfileMemory, CareerStateMemory]:
        """Replace career-state memory while preserving current profile memory."""

        current = self.dependencies.memory_provider.load(
            user_id=career_state_memory.user_id,
            workspace_id=career_state_memory.workspace_id,
        )
        current["career_state_memory"] = career_state_memory
        self.dependencies.memory_provider.save(
            {
                "user_id": career_state_memory.user_id,
                "workspace_id": career_state_memory.workspace_id,
                **current,
            }
        )
        return ProfileMemory.model_validate(current["profile_memory"]), career_state_memory

    def refresh_market_watch(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
        input_link: str | None = None,
        force: bool = False,
    ) -> tuple[bool, str, list[AgentState], datetime | None]:
        """Refresh market insight cards from remembered sources or one-off links."""

        profile_memory, career_state_memory = self._load_profile_context(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        now = now_in_project_timezone()
        is_due = self._market_refresh_due(career_state_memory.last_market_refresh_at, now)
        should_refresh = bool(input_link) or force or is_due
        if not should_refresh:
            return (
                False,
                "距离下一次强制更新时间还未到，本次未触发市场刷新。",
                [],
                career_state_memory.last_market_refresh_at,
            )

        source_urls = [input_link] if input_link else career_state_memory.market_watch_sources
        source_urls = list(dict.fromkeys(url for url in source_urls if url))
        if not source_urls:
            return (
                False,
                "当前还没有配置每日关注网站，先到记忆管理里补充来源。",
                [],
                career_state_memory.last_market_refresh_at,
            )

        states: list[AgentState] = []
        search_tokens = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        seen_article_urls: set[str] = set()
        refreshed_sources: set[str] = set()

        if input_link:
            direct_states = self._build_market_article_states(
                source_site=input_link,
                source_candidates=[
                    MarketArticleCandidate(
                        url=input_link,
                        title="手动市场链接",
                        snippet="",
                        relevance_score=1.0,
                        llm_score=1.0,
                        market_value_score=1.0,
                        diversity_gap_score=0.0,
                        title_score=1.0,
                        brief="手动输入链接",
                        reason="manual link refresh",
                        candidate_source="manual_link",
                        )
                ],
                user_id=user_id,
                workspace_id=workspace_id,
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
                now=now,
                seen_article_urls=seen_article_urls,
            )
            states.extend(direct_states)
            refreshed_sources.add(input_link)
        else:
            for url in source_urls:
                discovered_candidates = self._discover_market_article_candidates(
                    source_url=url,
                    profile_memory=profile_memory,
                    career_state_memory=career_state_memory,
                    input_link=None,
                )
                ranked_candidates = self._rank_market_article_candidates(
                    source_url=url,
                    candidates=discovered_candidates,
                    profile_memory=profile_memory,
                    career_state_memory=career_state_memory,
                )
                if not ranked_candidates:
                    homepage_fallback_state = self._build_market_source_homepage_state(
                        source_url=url,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        profile_memory=profile_memory,
                        career_state_memory=career_state_memory,
                        now=now,
                    )
                    if homepage_fallback_state is not None:
                        states.append(homepage_fallback_state)
                        refreshed_sources.add(url)
                    continue

                fetch_limit = max(1, int(career_state_memory.market_article_fetch_limit or MARKET_ARTICLE_FETCH_LIMIT))
                top_candidates = self._select_market_article_candidates(
                    ranked_candidates=ranked_candidates,
                    fetch_limit=fetch_limit,
                )
                child_states = self._build_market_article_states(
                    source_site=url,
                    source_candidates=top_candidates,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    profile_memory=profile_memory,
                    career_state_memory=career_state_memory,
                    now=now,
                    seen_article_urls=seen_article_urls,
                )
                overview_state = self._build_market_overview_state(
                    source_url=url,
                    ranked_candidates=ranked_candidates,
                    child_states=child_states,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    profile_memory=profile_memory,
                    career_state_memory=career_state_memory,
                    now=now,
                )
                if overview_state is not None:
                    states.append(overview_state)
                states.extend(child_states)
                refreshed_sources.add(url)
                if overview_state is None and not child_states:
                    homepage_fallback_state = self._build_market_source_homepage_state(
                        source_url=url,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        profile_memory=profile_memory,
                        career_state_memory=career_state_memory,
                        now=now,
                    )
                    if homepage_fallback_state is not None:
                        states.append(homepage_fallback_state)

        if states:
            self._prune_market_history(
                user_id=user_id,
                workspace_id=workspace_id,
                now=now,
                refreshed_sources=refreshed_sources,
                keep_item_ids={
                    state.normalized_item.id
                    for state in states
                    if state.normalized_item is not None
                },
            )
            updated_career = career_state_memory.model_copy(
                update={
                    "last_market_refresh_at": now,
                    "updated_at": now,
                }
            )
            self.upsert_career_state_memory(updated_career)
            reason = (
                "已完成市场信息刷新。"
                if input_link
                else "已完成本轮市场信息刷新。"
            )
            return True, reason, states, now

        return False, "本次市场刷新未获取到可用正文，稍后会继续尝试。", [], career_state_memory.last_market_refresh_at

    def chat_query(
        self,
        *,
        query: str,
        user_id: str,
        workspace_id: str | None,
        item_id: str | None = None,
        recent_days: int = 30,
    ) -> tuple[str, list[str], list, str]:
        """Answer grounded follow-up questions from stored workflow and memory data."""

        states = self.list_items(user_id=user_id, workspace_id=workspace_id)
        if item_id:
            target = self.get_item(item_id)
            states = [target] if target else []
        else:
            cutoff = now_in_project_timezone()
            states = [
                state
                for state in states
                if state is not None
                and self._state_timestamp(state) is not None
                and (cutoff - self._state_timestamp(state)).days <= max(1, recent_days)
            ]

        valid_states = [state for state in states if state is not None and state.normalized_item]
        supporting_ids = [
            state.normalized_item.id
            for state in valid_states
            if state.normalized_item is not None
        ]

        if not valid_states:
            return (
                "当前时间窗口内还没有可参考的卡片，先提交一条文本、链接、截图或放宽检索时间范围。",
                [],
                [],
                "empty",
            )

        current_memory = self.dependencies.memory_provider.load(
            user_id=user_id, workspace_id=workspace_id
        )
        profile = ProfileMemory.model_validate(current_memory["profile_memory"])
        career_state = CareerStateMemory.model_validate(
            current_memory["career_state_memory"]
        )
        result = self.chat_service.answer(
            query=query,
            states=valid_states,
            profile=profile,
            career_state=career_state,
            item_id=item_id,
            recent_days=recent_days,
        )
        return (
            result.answer,
            result.supporting_item_ids or supporting_ids[:3],
            result.citations,
            result.retrieval_mode,
        )

    def _market_refresh_due(
        self,
        last_refresh_at: datetime | None,
        now: datetime,
    ) -> bool:
        """Check whether a mandatory 10:00 / 21:00 market refresh has been missed."""

        current_day_slots = [
            now.replace(hour=10, minute=0, second=0, microsecond=0),
            now.replace(hour=21, minute=0, second=0, microsecond=0),
        ]
        previous_day = now - timedelta(days=1)
        slots = [
            previous_day.replace(hour=21, minute=0, second=0, microsecond=0),
            *current_day_slots,
        ]
        latest_due_slot = max((slot for slot in slots if slot <= now), default=None)
        if latest_due_slot is None:
            return False
        return last_refresh_at is None or last_refresh_at < latest_due_slot

    def _collect_market_search_references(
        self,
        *,
        url: str,
        page_title: str,
        profile_terms: list[str],
        page_text: str,
    ) -> list[str]:
        """Search for extra market context around one watched source."""

        query_parts = [page_title.strip(), " ".join(profile_terms[:3])]
        keyword_hints = self._extract_keyword_candidates(page_text[:500])
        if keyword_hints:
            query_parts.append(" ".join(keyword_hints[:3]))
        query_parts.append(urlparse(url).netloc)
        query = " ".join(part for part in query_parts if part).strip()
        if not query:
            return []

        try:
            results = self.dependencies.search_client.search(query=query, limit=3)
        except Exception:
            return []

        references: list[str] = []
        for result in results:
            title = str(result.get("title") or "").strip()
            snippet = str(result.get("snippet") or "").strip()
            if title or snippet:
                references.append(" | ".join(part for part in (title, snippet) if part))
        return references[:2]

    def _discover_market_article_candidates(
        self,
        *,
        source_url: str,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        input_link: str | None,
    ) -> list[dict[str, str | None]]:
        """Turn one watched source into article-level candidates before fetching."""

        if input_link:
            return [{"title": None, "snippet": None, "url": input_link}]

        candidate_limit = max(
            12,
            max(1, int(career_state_memory.market_article_fetch_limit or MARKET_ARTICLE_FETCH_LIMIT)) * 4,
        )
        adapter_candidates = self._discover_market_article_candidates_with_adapter(
            source_url=source_url,
            profile_memory=profile_memory,
            career_state_memory=career_state_memory,
            candidate_limit=candidate_limit,
        )
        if adapter_candidates:
            return adapter_candidates

        query = self._build_market_search_query(
            source_url=source_url,
            profile_terms=self._collect_market_keyword_terms(
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
            ),
        )
        results = self._run_market_search_queries(
            source_url=source_url,
            queries=[query],
            candidate_limit=candidate_limit,
            candidate_source="search_generic",
        )

        candidates: list[dict[str, str | None]] = []
        for result in results:
            candidates.append(
                {
                    "title": str(result.get("title") or "").strip() or None,
                    "snippet": str(result.get("snippet") or "").strip() or None,
                    "url": str(result.get("url") or "").strip() or None,
                    "candidate_source": str(result.get("candidate_source") or "search_generic"),
                    "published_at": str(result.get("published_at") or "").strip() or None,
                }
            )
        return candidates

    def _discover_market_article_candidates_with_adapter(
        self,
        *,
        source_url: str,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        candidate_limit: int,
    ) -> list[dict[str, str | None]]:
        """Use site-specific adapters before falling back to generic search."""

        hostname = urlparse(source_url).netloc.lower().replace("www.", "")
        if hostname == "qbitai.com":
            try:
                recent_titles = fetch_recent_site_titles(
                    source_url,
                    hours=24,
                    limit=candidate_limit,
                )
            except Exception:
                recent_titles = []
            if recent_titles:
                return [
                    {
                        "title": item.title,
                        "snippet": item.snippet
                        or f"站点级近24小时标题抓取，发布时间 {item.published_at}",
                        "url": item.url,
                        "candidate_source": f"site_recent_titles:{item.discovery_source}",
                        "published_at": item.published_at,
                    }
                    for item in recent_titles
                ]
            return []

        if hostname == "jiqizhixin.com":
            try:
                recent_titles = fetch_recent_site_titles(
                    source_url,
                    hours=24,
                    limit=candidate_limit,
                )
            except Exception:
                recent_titles = []
            if recent_titles:
                return [
                    {
                        "title": item.title,
                        "snippet": item.snippet
                        or f"站点级近24小时标题抓取，发布时间 {item.published_at}",
                        "url": item.url,
                        "candidate_source": f"site_recent_titles:{item.discovery_source}",
                        "published_at": item.published_at,
                    }
                    for item in recent_titles
                ]
            profile_terms = self._collect_market_keyword_terms(
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
            )
            focus_terms = " ".join(profile_terms[:4]).strip()
            queries = [
                f"site:jiqizhixin.com/articles 最近24小时 文章 {focus_terms}".strip(),
                f"site:jiqizhixin.com 机器之心 AI 文章 {focus_terms}".strip(),
            ]
            return self._run_market_search_queries(
                source_url=source_url,
                queries=queries,
                candidate_limit=candidate_limit,
                candidate_source="search_adapter:jiqizhixin",
            )

        return []

    def _run_market_search_queries(
        self,
        *,
        source_url: str,
        queries: list[str],
        candidate_limit: int,
        candidate_source: str,
    ) -> list[dict[str, str | None]]:
        """Run one or more site-constrained search queries and merge article candidates."""

        candidates: list[dict[str, str | None]] = []
        seen_urls: set[str] = set()
        for query in queries:
            if not query.strip():
                continue
            try:
                results = self.dependencies.search_client.search(query=query, limit=candidate_limit)
            except Exception:
                continue
            for result in results:
                article_url = str(result.get("url") or "").strip()
                if not article_url or article_url in seen_urls:
                    continue
                if not self._url_matches_market_source(source_url, article_url):
                    continue
                seen_urls.add(article_url)
                candidates.append(
                    {
                        "title": str(result.get("title") or "").strip() or None,
                        "snippet": str(result.get("snippet") or "").strip() or None,
                        "url": article_url,
                        "candidate_source": candidate_source,
                        "published_at": str(result.get("published_at") or "").strip() or None,
                    }
                )
                if len(candidates) >= candidate_limit:
                    return candidates[:candidate_limit]
        return candidates

    def _rank_market_article_candidates(
        self,
        *,
        source_url: str,
        candidates: list[dict[str, str | None]],
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> list[MarketArticleCandidate]:
        """Score source article titles before fetching any正文."""

        profile_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        keyword_terms = self._collect_market_keyword_terms(
            profile_memory=profile_memory,
            career_state_memory=career_state_memory,
        )

        ranked: list[MarketArticleCandidate] = []
        for candidate in candidates:
            url = str(candidate.get("url") or "").strip()
            title = str(candidate.get("title") or "").strip()
            snippet = str(candidate.get("snippet") or "").strip()
            if not url or not title:
                continue
            relevance_score = self._score_market_title_relevance(
                title=title,
                snippet=snippet,
                profile_terms=keyword_terms,
            )
            market_value_score = self._score_market_title_market_value(
                title=title,
                snippet=snippet,
            )
            diversity_gap_score = round(max(0.0, 1.0 - min(relevance_score, 1.0)), 4)
            title_score = round(
                min(
                    0.62 * relevance_score
                    + 0.28 * market_value_score
                    + 0.10 * min(diversity_gap_score, 0.7),
                    0.99,
                ),
                4,
            )
            brief = self._build_market_preview_brief(title).strip()
            reason = self._build_market_title_reason(
                title=title,
                snippet=snippet,
                profile_terms=profile_terms,
                relevance_score=relevance_score,
                market_value_score=market_value_score,
                diversity_gap_score=diversity_gap_score,
            )
            ranked.append(
                MarketArticleCandidate(
                    url=url,
                    title=title,
                    snippet=snippet,
                    relevance_score=round(relevance_score, 4),
                    llm_score=round(relevance_score, 4),
                    market_value_score=round(market_value_score, 4),
                    diversity_gap_score=diversity_gap_score,
                    title_score=title_score,
                    brief=brief[:36],
                    reason=reason,
                    selection_mode="keyword_rule",
                    candidate_source=str(candidate.get("candidate_source") or "search"),
                    published_at=str(candidate.get("published_at") or "").strip() or None,
                )
            )

        ranked.sort(key=lambda item: item.title_score, reverse=True)
        return ranked

    def _select_market_article_candidates(
        self,
        *,
        ranked_candidates: list[MarketArticleCandidate],
        fetch_limit: int,
    ) -> list[MarketArticleCandidate]:
        """Select fetch candidates with one reserved slot for a high-value exploration article."""

        if len(ranked_candidates) <= fetch_limit:
            return ranked_candidates

        selected: list[MarketArticleCandidate] = []
        selected_urls: set[str] = set()

        primary_quota = fetch_limit - 1 if fetch_limit > 1 else fetch_limit

        for candidate in ranked_candidates:
            if len(selected) >= primary_quota:
                break
            if candidate.url in selected_urls:
                continue
            selected.append(candidate)
            selected_urls.add(candidate.url)

        remaining_candidates = [
            candidate for candidate in ranked_candidates if candidate.url not in selected_urls
        ]
        best_exploratory = None
        if remaining_candidates and fetch_limit > 1:
            remaining_candidates.sort(
                key=lambda candidate: (
                    candidate.market_value_score + 0.25 * candidate.diversity_gap_score,
                    candidate.title_score,
                ),
                reverse=True,
            )
            best_exploratory = remaining_candidates[0]

        if best_exploratory is not None and best_exploratory.url not in selected_urls:
            selected.append(replace(best_exploratory, selection_mode="keyword_exploration"))
            selected_urls.add(best_exploratory.url)

        if len(selected) < fetch_limit:
            for candidate in ranked_candidates:
                if len(selected) >= fetch_limit:
                    break
                if candidate.url in selected_urls:
                    continue
                selected.append(candidate)
                selected_urls.add(candidate.url)

        return selected[:fetch_limit]

    def _score_market_title_relevance(
        self,
        *,
        title: str,
        snippet: str,
        profile_terms: list[str],
    ) -> float:
        """Heuristic relevance score before fetching article正文."""

        combined = f"{title} {snippet}".lower()
        title_lower = title.lower()
        direct_hits = 0.0
        unique_matches: set[str] = set()
        for term in profile_terms[:18]:
            lowered = term.lower()
            if not lowered:
                continue
            if lowered in title_lower:
                direct_hits += 1.4
                unique_matches.add(lowered)
            elif lowered in combined:
                direct_hits += 0.9
                unique_matches.add(lowered)
        entity_hints = self._extract_keyword_candidates(f"{title} {snippet}")
        entity_matches = 0
        for entity in entity_hints[:6]:
            lowered = entity.lower()
            if lowered in unique_matches:
                continue
            if lowered in title_lower:
                entity_matches += 1
            elif lowered in combined:
                entity_matches += 0.6
        return min(0.12 * direct_hits + 0.08 * entity_matches + 0.05 * min(len(unique_matches), 4), 0.95)

    def _score_market_title_market_value(
        self,
        *,
        title: str,
        snippet: str,
    ) -> float:
        """Estimate whether one title looks like a high-value market signal even beyond direct profile overlap."""

        combined = f"{title} {snippet}".lower()
        hits = 0.0
        for keyword in MARKET_VALUE_KEYWORDS:
            lowered = keyword.lower()
            if lowered in title.lower():
                hits += 1.0
            elif lowered in combined:
                hits += 0.65
        entity_hints = self._extract_keyword_candidates(f"{title} {snippet}")
        organization_bonus = min(len(entity_hints), 3) * 0.08
        return min(0.1 + 0.07 * hits + organization_bonus, 0.95)

    def _build_market_title_reason(
        self,
        *,
        title: str,
        snippet: str,
        profile_terms: list[str],
        relevance_score: float,
        market_value_score: float,
        diversity_gap_score: float,
    ) -> str:
        """Explain deterministic market-title selection in a concise way."""

        matched_terms: list[str] = []
        combined = f"{title} {snippet}".lower()
        for term in profile_terms[:12]:
            lowered = term.lower()
            if lowered and lowered in combined:
                matched_terms.append(term)
        matched_terms = list(dict.fromkeys(matched_terms))[:3]
        if matched_terms and diversity_gap_score < 0.35:
            return f"关键词命中：{'、'.join(matched_terms)}；与当前方向贴合。"
        if market_value_score >= 0.55 and diversity_gap_score >= 0.35:
            return "市场价值较高，且与当前方向有一定距离，作为探索项保留。"
        if matched_terms:
            return f"关键词命中：{'、'.join(matched_terms)}；值得继续抓正文。"
        return "关键词覆盖一般，但标题本身具备较强市场价值。"

    def _build_market_preview_brief(self, title: str) -> str:
        """Compress one ranked article title into a preview label."""

        normalized = re.sub(r"\s+", " ", title).strip()
        return normalized[:36]

    def _build_market_article_states(
        self,
        *,
        source_site: str,
        source_candidates: list[MarketArticleCandidate],
        user_id: str,
        workspace_id: str | None,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        now: datetime,
        seen_article_urls: set[str],
    ) -> list[AgentState]:
        """Fetch and build market article child cards one by one."""

        states: list[AgentState] = []
        search_tokens = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        for candidate in source_candidates:
            article_url = candidate.url
            if article_url in seen_article_urls:
                continue
            seen_article_urls.add(article_url)
            extracted_page = None
            try:
                extracted_page = self.dependencies.web_page_client.fetch(article_url)
            except Exception:
                extracted_page = None

            candidate_text = str(candidate.snippet or "").strip()
            fallback_page_title = str(candidate.title or "").strip()
            fallback_message_time = self._coerce_datetime(candidate.published_at) or now

            if extracted_page is None:
                if not candidate_text or source_site != article_url and not self._is_recent_market_article(
                    fallback_message_time, now
                ):
                    continue

                keyword_hints = self._extract_keyword_candidates(
                    f"{fallback_page_title} {candidate_text[:500]}"
                )
                market_references = self._collect_market_search_references(
                    url=article_url,
                    page_title=fallback_page_title,
                    profile_terms=search_tokens,
                    page_text=candidate_text,
                )
                source_title = self._derive_fallback_source_title(
                    original_content=article_url,
                    fetched_texts=[candidate_text],
                    page_title=fallback_page_title,
                    keyword_hints=keyword_hints,
                )
                raw_input = self._compose_market_watch_payload(
                    source_title=source_title,
                    source_url=article_url,
                    source_site=source_site,
                    page_title=fallback_page_title,
                    keyword_hints=keyword_hints,
                    profile_terms=search_tokens,
                    search_references=market_references,
                    page_text=candidate_text,
                    published_at=fallback_message_time,
                )
                state = self.ingest(
                    raw_input=raw_input,
                    source_type=SourceType.LINK,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    source_ref=article_url,
                    memory_write_mode=MemoryWriteMode.CONTEXT_ONLY,
                    source_metadata={
                        "source_kind": "link",
                        "fetch_method": "market_candidate_snippet_fallback",
                        "page_title": fallback_page_title,
                        "text_length": len(candidate_text),
                        "source_title": source_title,
                        "market_watch": True,
                        "market_group_kind": "article",
                        "force_content_category": ContentCategory.GENERAL_UPDATE.value,
                        "market_watch_source": source_site,
                        "market_article_url": article_url,
                        "market_article_title": fallback_page_title,
                        "market_article_snippet": candidate.snippet,
                        "market_title_reason": candidate.reason,
                        "market_title_brief": candidate.brief,
                        "market_title_score": candidate.title_score,
                        "market_title_llm_score": candidate.llm_score,
                        "market_title_keyword_score": candidate.relevance_score,
                        "market_title_market_value_score": candidate.market_value_score,
                        "market_title_diversity_gap_score": candidate.diversity_gap_score,
                        "market_title_selection_mode": candidate.selection_mode,
                        "market_candidate_source": candidate.candidate_source,
                        "market_relevance_score": candidate.relevance_score,
                        "message_time": fallback_message_time.isoformat(),
                        "published_at": fallback_message_time.isoformat(),
                        "search_references": market_references,
                        "keyword_hints": keyword_hints,
                        "profile_terms": search_tokens[:8],
                        "market_watch_query": self._build_market_search_query(
                            source_url=source_site,
                            profile_terms=search_tokens,
                        ),
                        "ingest_channel": "market_watch",
                    },
                )
                self._postprocess_market_state(
                    state=state,
                    profile_memory=profile_memory,
                    career_state_memory=career_state_memory,
                    now=now,
                    market_group_kind="article",
                )
                self.dependencies.workflow_repository.save(state)
                states.append(state)
                continue

            article_time = self._coerce_datetime(
                extracted_page.source_metadata.get("published_at")
                or candidate.published_at
            )
            if source_site != article_url and not self._is_recent_market_article(article_time, now):
                continue

            keyword_hints = self._extract_keyword_candidates(
                f"{candidate.title} {extracted_page.title or ''} {extracted_page.text[:500]}"
            )
            market_references = self._collect_market_search_references(
                url=article_url,
                page_title=candidate.title or extracted_page.title or "",
                profile_terms=search_tokens,
                page_text=extracted_page.text,
            )
            source_title = self._derive_fallback_source_title(
                original_content=article_url,
                fetched_texts=[extracted_page.text],
                page_title=candidate.title or extracted_page.title or "",
                keyword_hints=keyword_hints,
            )
            message_time = article_time or now
            raw_input = self._compose_market_watch_payload(
                source_title=source_title,
                source_url=article_url,
                source_site=source_site,
                page_title=extracted_page.title or "",
                keyword_hints=keyword_hints,
                profile_terms=search_tokens,
                search_references=market_references,
                page_text=extracted_page.text,
                published_at=message_time,
            )
            state = self.ingest(
                raw_input=raw_input,
                source_type=SourceType.LINK,
                user_id=user_id,
                workspace_id=workspace_id,
                source_ref=article_url,
                memory_write_mode=MemoryWriteMode.CONTEXT_ONLY,
                source_metadata={
                    **extracted_page.source_metadata,
                    "source_title": source_title,
                    "market_watch": True,
                    "market_group_kind": "article",
                    "force_content_category": ContentCategory.GENERAL_UPDATE.value,
                    "market_watch_source": source_site,
                    "market_article_url": article_url,
                    "market_article_title": candidate.title or extracted_page.title or "",
                    "market_article_snippet": candidate.snippet,
                    "market_title_reason": candidate.reason,
                    "market_title_brief": candidate.brief,
                    "market_title_score": candidate.title_score,
                    "market_title_llm_score": candidate.llm_score,
                    "market_title_keyword_score": candidate.relevance_score,
                    "market_title_market_value_score": candidate.market_value_score,
                    "market_title_diversity_gap_score": candidate.diversity_gap_score,
                    "market_title_selection_mode": candidate.selection_mode,
                    "market_candidate_source": candidate.candidate_source,
                    "market_relevance_score": candidate.relevance_score,
                    "message_time": message_time.isoformat(),
                    "search_references": market_references,
                    "keyword_hints": keyword_hints,
                    "profile_terms": search_tokens[:8],
                    "market_watch_query": self._build_market_search_query(
                        source_url=source_site,
                        profile_terms=search_tokens,
                    ),
                    "ingest_channel": "market_watch",
                },
            )
            self._postprocess_market_state(
                state=state,
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
                now=now,
                market_group_kind="article",
            )
            self.dependencies.workflow_repository.save(state)
            states.append(state)
        return states

    def _build_market_source_homepage_state(
        self,
        *,
        source_url: str,
        user_id: str,
        workspace_id: str | None,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        now: datetime,
    ) -> AgentState | None:
        """Fallback to analyzing one watched source homepage when title search yields nothing."""

        try:
            extracted_page = self.dependencies.web_page_client.fetch(source_url)
        except Exception:
            return None

        profile_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        keyword_hints = self._extract_keyword_candidates(
            f"{extracted_page.title or ''} {extracted_page.text[:600]}"
        )
        market_references = self._collect_market_search_references(
            url=source_url,
            page_title=extracted_page.title or "",
            profile_terms=profile_terms,
            page_text=extracted_page.text,
        )
        source_title = self._derive_fallback_source_title(
            original_content=source_url,
            fetched_texts=[extracted_page.text],
            page_title=extracted_page.title or "",
            keyword_hints=keyword_hints,
        )
        message_time = self._coerce_datetime(
            extracted_page.source_metadata.get("published_at")
        ) or now
        raw_input = self._compose_market_watch_payload(
            source_title=source_title,
            source_url=source_url,
            source_site=source_url,
            page_title=extracted_page.title or "",
            keyword_hints=keyword_hints,
            profile_terms=profile_terms,
            search_references=market_references,
            page_text=extracted_page.text,
            published_at=message_time,
        )
        state = self.ingest(
            raw_input=raw_input,
            source_type=SourceType.LINK,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_url,
            memory_write_mode=MemoryWriteMode.CONTEXT_ONLY,
            source_metadata={
                **extracted_page.source_metadata,
                "source_title": self._build_market_overview_title(source_url),
                "market_watch": True,
                "market_group_kind": "overview",
                "force_content_category": ContentCategory.GENERAL_UPDATE.value,
                "market_watch_source": source_url,
                "market_watch_fallback": "homepage_fetch",
                "market_watch_query": self._build_market_search_query(
                    source_url=source_url,
                    profile_terms=profile_terms,
                ),
                "market_overview_title": self._build_market_overview_title(source_url),
                "keyword_hints": keyword_hints,
                "search_references": market_references,
                "message_time": message_time.isoformat(),
                "ingest_channel": "market_watch",
            },
        )
        self._postprocess_market_state(
            state=state,
            profile_memory=profile_memory,
            career_state_memory=career_state_memory,
            now=now,
            market_group_kind="overview",
            child_states=[],
            overview_title=self._build_market_overview_title(source_url),
            overview_summary=source_title,
            overview_advice="标题检索不足时已回退到来源站点首页分析，建议点开详情查看原文。",
            overview_keywords=list(dict.fromkeys(["市场总览", *keyword_hints[:5]]))[:8],
            overview_score=0.48,
            child_previews=[],
        )
        self.dependencies.workflow_repository.save(state)
        return state

    def _build_market_overview_state(
        self,
        *,
        source_url: str,
        ranked_candidates: list[MarketArticleCandidate],
        child_states: list[AgentState],
        user_id: str,
        workspace_id: str | None,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        now: datetime,
    ) -> AgentState | None:
        """Create one overview card from the exported title list of a fixed market source."""

        overview_payload = self._summarize_market_source_titles(
            source_url=source_url,
            ranked_candidates=ranked_candidates,
            profile_memory=profile_memory,
            career_state_memory=career_state_memory,
        )
        if not ranked_candidates:
            return None
        overview_title = self._build_market_overview_title(source_url)
        actual_child_previews = [
            str(child_state.source_metadata.get("market_title_brief") or "").strip()
            for child_state in child_states
            if str(child_state.source_metadata.get("market_title_brief") or "").strip()
        ]

        raw_input = self._compose_market_title_overview_payload(
            source_url=source_url,
            ranked_candidates=ranked_candidates,
            overview_payload=overview_payload,
        )
        state = self.ingest(
            raw_input=raw_input,
            source_type=SourceType.LINK,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_url,
            memory_write_mode=MemoryWriteMode.CONTEXT_ONLY,
            source_metadata={
                "source_title": overview_title,
                "market_watch": True,
                "market_group_kind": "overview",
                "force_content_category": ContentCategory.GENERAL_UPDATE.value,
                "market_watch_source": source_url,
                "market_watch_query": self._build_market_search_query(
                    source_url=source_url,
                    profile_terms=self._collect_profile_focus_terms(
                        profile_memory, career_state_memory
                    ),
                ),
                "market_title_list": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "brief": item.brief,
                        "title_score": item.title_score,
                    }
                    for item in ranked_candidates
                ],
                "market_overview_title": overview_title,
                "market_overview_summary": overview_payload["summary"],
                "market_overview_advice": overview_payload["advice"],
                "market_overview_keywords": overview_payload["keywords"],
                "market_overview_score": overview_payload["overview_score"],
                "market_child_previews": actual_child_previews
                or [item.brief for item in ranked_candidates[: max(1, int(career_state_memory.market_article_fetch_limit or MARKET_ARTICLE_FETCH_LIMIT))]],
                "keyword_hints": overview_payload["keywords"],
                "message_time": now.isoformat(),
                "ingest_channel": "market_watch",
            },
        )
        self._postprocess_market_state(
            state=state,
            profile_memory=profile_memory,
            career_state_memory=career_state_memory,
            now=now,
            market_group_kind="overview",
            child_states=child_states,
            overview_title=overview_title,
            overview_summary=overview_payload["summary"],
            overview_advice=overview_payload["advice"],
            overview_keywords=overview_payload["keywords"],
            overview_score=float(overview_payload["overview_score"]),
            child_previews=actual_child_previews
            or [item.brief for item in ranked_candidates[: max(1, int(career_state_memory.market_article_fetch_limit or MARKET_ARTICLE_FETCH_LIMIT))]],
        )
        parent_item_id = state.normalized_item.id if state.normalized_item is not None else None
        if parent_item_id:
            child_ids: list[str] = []
            for child_state in child_states:
                if child_state.normalized_item is None or child_state.render_card is None:
                    continue
                child_ids.append(child_state.normalized_item.id)
                child_state.source_metadata["market_parent_item_id"] = parent_item_id
                child_state.render_card.market_parent_item_id = parent_item_id
                self.dependencies.workflow_repository.save(child_state)
            if state.render_card is not None:
                state.render_card.market_child_item_ids = child_ids
            state.source_metadata["market_child_item_ids"] = child_ids
        self.dependencies.workflow_repository.save(state)
        return state

    def _summarize_market_source_titles(
        self,
        *,
        source_url: str,
        ranked_candidates: list[MarketArticleCandidate],
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> dict[str, Any]:
        """Summarize one source title list into a parent market card."""

        profile_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        fetch_limit = max(
            1,
            int(career_state_memory.market_article_fetch_limit or MARKET_ARTICLE_FETCH_LIMIT),
        )
        route = self.dependencies.model_router.select("chat", "low")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("market_watch_overview")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="market_watch_overview",
                    system_prompt=prompt,
                    user_payload={
                        "source_url": source_url,
                        "profile_terms": profile_terms[:8],
                        "items": [
                            {
                                "title": item.title,
                                "url": item.url,
                                "brief": item.brief,
                                "title_score": item.title_score,
                            }
                            for item in ranked_candidates[: max(8, fetch_limit)]
                        ],
                    },
                )
                summary = str(response.get("summary") or "").strip()
                advice = str(response.get("advice") or "").strip()
                keywords = [
                    str(value).strip()
                    for value in response.get("keywords", [])
                    if str(value).strip()
                ]
                overview_score = float(response.get("overview_score") or 0.0)
                if summary and advice:
                    return {
                        "summary": summary,
                        "advice": advice,
                        "keywords": list(dict.fromkeys(["市场总览", *keywords]))[:8],
                        "overview_score": max(0.0, min(overview_score, 1.0)),
                    }
            except Exception:
                pass

        top_titles = [item.title for item in ranked_candidates[:3]]
        avg_title_score = sum(
            item.title_score for item in ranked_candidates[:fetch_limit]
        ) / max(
            1, min(len(ranked_candidates), fetch_limit)
        )
        hostname = urlparse(source_url).netloc.replace("www.", "")
        return {
            "summary": "、".join(self._extract_keyword_candidates(" ".join(top_titles))[:4])
            or f"{hostname} 最近24小时重点方向",
            "advice": f"建议先展开前 {fetch_limit} 篇文章，再决定是否继续跟进具体正文。",
            "keywords": list(
                dict.fromkeys(
                    ["市场总览", *self._extract_keyword_candidates(" ".join(top_titles))[:5]]
                )
            )[:8],
            "overview_score": round(avg_title_score, 4),
        }

    def _build_market_overview_title(self, source_url: str) -> str:
        """Render one stable overview-card title for a watched site."""

        hostname = urlparse(source_url).netloc.replace("www.", "") or source_url
        return f"{hostname} 更新"

    def _compose_market_title_overview_payload(
        self,
        *,
        source_url: str,
        ranked_candidates: list[MarketArticleCandidate],
        overview_payload: dict[str, Any],
    ) -> str:
        """Build the parent market overview payload from exported titles."""

        parts = [
            f"市场来源：{source_url}",
            f"标题总览：{overview_payload['summary']}",
            f"总览建议：{overview_payload['advice']}",
            "标题列表：",
        ]
        for index, item in enumerate(ranked_candidates[:8], start=1):
            parts.append(
                f"{index}. {item.title} | 分数={item.title_score:.2f} | 简介={item.brief} | 链接={item.url}"
            )
        return "\n".join(parts)

    def _build_market_search_query(
        self,
        *,
        source_url: str,
        profile_terms: list[str],
    ) -> str:
        """Build a site-constrained query for recent market-watch content."""

        hostname = urlparse(source_url).netloc.replace("www.", "")
        focus_terms = " ".join(profile_terms[:4]).strip()
        query_parts = [
            f"site:{hostname}",
            "最近24小时",
            "文章",
            focus_terms,
        ]
        return " ".join(part for part in query_parts if part).strip()

    def _url_matches_market_source(self, source_url: str, article_url: str) -> bool:
        """Keep search results constrained to the configured source site."""

        source_host = urlparse(source_url).netloc.lower().replace("www.", "")
        article_host = urlparse(article_url).netloc.lower().replace("www.", "")
        if not source_host or not article_host:
            return False
        return article_host == source_host or article_host.endswith(f".{source_host}")

    def _coerce_datetime(self, value: Any) -> datetime | None:
        """Parse flexible datetime payloads into project-timezone-aware values."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(
                tzinfo=now_in_project_timezone().tzinfo
            )

        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00").replace("/", "-")
        normalized = (
            normalized.replace("年", "-").replace("月", "-").replace("日", "")
        )
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=now_in_project_timezone().tzinfo)
        return parsed

    def _is_recent_market_article(self, published_at: datetime | None, now: datetime) -> bool:
        """Keep market-watch refresh focused on source content from the last 24 hours."""

        if published_at is None:
            return False
        return now - published_at <= timedelta(hours=24)

    def _compose_market_watch_payload(
        self,
        *,
        source_title: str,
        source_url: str,
        source_site: str,
        page_title: str,
        keyword_hints: list[str],
        profile_terms: list[str],
        search_references: list[str],
        page_text: str,
        published_at: datetime | None,
    ) -> str:
        """Build one market-watch payload that differs from job cards."""

        parts = [
            f"市场主题：{source_title}",
            f"来源链接：{source_url}",
            f"来源站点：{source_site}",
        ]
        if page_title:
            parts.append(f"网页标题：{page_title}")
        if published_at:
            parts.append(f"消息时间：{published_at.isoformat()}")
        if profile_terms:
            parts.append(f"画像关注：{'、'.join(profile_terms[:6])}")
        if keyword_hints:
            parts.append(f"市场关键词：{'、'.join(keyword_hints[:8])}")
        if search_references:
            parts.append("搜索参考：")
            parts.extend(search_references[:2])
        parts.append("市场正文：")
        parts.append(page_text[:3000])
        return "\n".join(parts)

    def _postprocess_market_state(
        self,
        *,
        state: AgentState,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        now: datetime,
        market_group_kind: str | None = None,
        child_states: list[AgentState] | None = None,
        overview_title: str | None = None,
        overview_summary: str | None = None,
        overview_advice: str | None = None,
        overview_keywords: list[str] | None = None,
        overview_score: float | None = None,
        child_previews: list[str] | None = None,
    ) -> None:
        """Normalize market cards so the list UI can render summary, advice, and score clearly."""

        if state.normalized_item is None or state.render_card is None:
            return

        card = state.render_card
        card.content_category = ContentCategory.GENERAL_UPDATE
        card.is_market_signal = True
        card.market_group_kind = market_group_kind or str(
            state.source_metadata.get("market_group_kind") or "article"
        )
        card.market_parent_item_id = str(
            state.source_metadata.get("market_parent_item_id") or ""
        ) or None
        card.market_child_item_ids = list(state.source_metadata.get("market_child_item_ids", []))
        card.market_child_previews = list(child_previews or state.source_metadata.get("market_child_previews", []))
        card.message_time = self._coerce_datetime(
            state.source_metadata.get("message_time")
            or state.source_metadata.get("published_at")
        ) or card.generated_at
        if card.market_group_kind == "overview":
            child_scores = [
                child_state.render_card.ai_score
                for child_state in (child_states or [])
                if child_state.render_card is not None and child_state.render_card.ai_score is not None
            ]
            computed_overview_score = max(0.0, min(float(overview_score or 0.0), 0.99))
            child_average = sum(child_scores) / len(child_scores) if child_scores else computed_overview_score
            card.ai_score = round((computed_overview_score + child_average) / 2, 4)
            title = (
                overview_title
                or str(state.source_metadata.get("market_overview_title") or "").strip()
                or card.summary_one_line
            )
            summary = overview_summary or str(
                state.source_metadata.get("market_overview_summary") or ""
            ).strip() or card.summary_one_line
            fetch_limit = max(
                1,
                int(career_state_memory.market_article_fetch_limit or MARKET_ARTICLE_FETCH_LIMIT),
            )
            advice = overview_advice or f"建议先展开前 {fetch_limit} 篇文章再看正文。"
            tags = list(dict.fromkeys(["市场总览", *(overview_keywords or [])]))[:8]
            card.market_child_previews = list(child_previews or [])[:fetch_limit]
            card.summary_one_line = title
        else:
            card.ai_score = self._score_market_signal(
                state=state,
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
                now=now,
            )
            summary, advice, tags = self._summarize_market_signal(
                state=state,
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
            )
            card.summary_one_line = summary
        card.insight_summary = summary
        card.advice = advice
        card.tags = tags
        if state.extracted_signal is not None:
            state.extracted_signal.category = ContentCategory.GENERAL_UPDATE
            state.extracted_signal.summary_one_line = card.summary_one_line
            state.extracted_signal.company = None
            state.extracted_signal.role = None
            state.extracted_signal.city = None
            state.extracted_signal.location_note = None
            state.extracted_signal.tags = tags
        state.render_card = card

    def _score_market_signal(
        self,
        *,
        state: AgentState,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
        now: datetime,
    ) -> float:
        """Combine freshness and profile overlap into one market-card score."""

        normalized = state.normalized_item
        if normalized is None:
            return 0.0

        profile_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        keyword_hints = [
            str(value).strip()
            for value in state.source_metadata.get("keyword_hints", [])
            if str(value).strip()
        ]
        overlap_hits = 0
        normalized_text = normalized.normalized_text.lower()
        for term in profile_terms[:10]:
            if term.lower() in normalized_text:
                overlap_hits += 1
        for term in keyword_hints[:6]:
            if term.lower() in normalized_text:
                overlap_hits += 1
        overlap_score = min(overlap_hits / 6, 1.0)

        message_time = self._coerce_datetime(
            state.source_metadata.get("message_time")
            or state.source_metadata.get("published_at")
        )
        freshness_score = 0.2
        if message_time is not None:
            age = now - message_time
            if age <= timedelta(hours=6):
                freshness_score = 1.0
            elif age <= timedelta(hours=24):
                freshness_score = 0.85
            elif age <= timedelta(hours=72):
                freshness_score = 0.55
            else:
                freshness_score = 0.25

        base_score = state.score_result.total_score if state.score_result else 0.35
        title_score = float(state.source_metadata.get("market_title_score") or overlap_score)
        keyword_score = float(
            state.source_metadata.get("market_title_keyword_score")
            or state.source_metadata.get("market_title_llm_score")
            or overlap_score
        )
        market_value_score = float(
            state.source_metadata.get("market_title_market_value_score")
            or state.source_metadata.get("market_title_score")
            or overlap_score
        )
        return round(
            min(
                0.28 * base_score
                + 0.22 * keyword_score
                + 0.18 * title_score
                + 0.12 * market_value_score
                + 0.10 * overlap_score
                + 0.10 * freshness_score,
                0.99,
            ),
            4,
        )

    def _summarize_market_signal(
        self,
        *,
        state: AgentState,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> tuple[str, str, list[str]]:
        """Use LLM when available, otherwise fall back to a deterministic market summary."""

        normalized = state.normalized_item
        route = self.dependencies.model_router.select("chat", "low")
        if normalized is None:
            return "市场信息待整理", "建议稍后重试刷新。", ["市场信息"]

        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("market_watch_summarize")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="market_watch_summarize",
                    system_prompt=prompt,
                    user_payload={
                        "source_title": normalized.source_title,
                        "normalized_text": normalized.normalized_text[:2500],
                        "message_time": state.source_metadata.get("message_time")
                        or state.source_metadata.get("published_at"),
                        "profile_terms": self._collect_profile_focus_terms(
                            profile_memory, career_state_memory
                        )[:8],
                        "keyword_hints": state.source_metadata.get("keyword_hints", []),
                    },
                )
                summary = str(response.get("summary") or "").strip()
                advice = str(response.get("advice") or "").strip()
                tags = [
                    str(value).strip()
                    for value in response.get("keywords", [])
                    if str(value).strip()
                ]
                if summary and advice:
                    return summary, advice, list(dict.fromkeys(["市场信息", *tags]))[:8]
            except Exception:
                pass

        score_reason = state.score_result.reasoning if state.score_result else "暂无评分"
        keyword_hints = [
            str(value).strip()
            for value in state.source_metadata.get("keyword_hints", [])
            if str(value).strip()
        ]
        summary = normalized.source_title or "市场信息更新"
        advice = f"建议优先关注与画像最相关的市场线索。{score_reason}"
        tags = list(
            dict.fromkeys(
                [
                    "市场信息",
                    *keyword_hints[:4],
                    *self._collect_profile_focus_terms(profile_memory, career_state_memory)[:2],
                ]
            )
        )
        return summary, advice, tags[:8]

    def _prune_market_history(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
        now: datetime,
        refreshed_sources: set[str],
        keep_item_ids: set[str],
    ) -> None:
        """Drop duplicate or stale low-value market cards after each refresh."""

        states = self.dependencies.workflow_repository.list_all(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        market_states = [
            state
            for state in states
            if state.normalized_item is not None
            and (
                state.source_metadata.get("market_watch")
                or state.classified_category == ContentCategory.GENERAL_UPDATE
            )
        ]

        grouped: dict[str, list[AgentState]] = {}
        for state in market_states:
            key = self._market_dedupe_key(state)
            grouped.setdefault(key, []).append(state)

        for siblings in grouped.values():
            siblings.sort(
                key=lambda item: (
                    item.render_card.ai_score if item.render_card and item.render_card.ai_score is not None else 0.0,
                    self._coerce_datetime(
                        item.source_metadata.get("message_time")
                        or item.source_metadata.get("published_at")
                    )
                    or datetime.min.replace(tzinfo=now.tzinfo),
                ),
                reverse=True,
            )
            for redundant in siblings[1:]:
                if redundant.normalized_item is None:
                    continue
                if redundant.normalized_item.id in keep_item_ids:
                    continue
                self.delete_item(redundant.normalized_item.id)

        for state in market_states:
            if state.normalized_item is None:
                continue
            if state.normalized_item.id in keep_item_ids:
                continue
            source_key = str(state.source_metadata.get("market_watch_source") or "").strip()
            if source_key and source_key in refreshed_sources:
                self.delete_item(state.normalized_item.id)
                continue
            message_time = self._coerce_datetime(
                state.source_metadata.get("message_time")
                or state.source_metadata.get("published_at")
            )
            ai_score = state.render_card.ai_score if state.render_card and state.render_card.ai_score is not None else 0.0
            if message_time and now - message_time > timedelta(hours=72) and ai_score < 0.55:
                self.delete_item(state.normalized_item.id)

    def _market_dedupe_key(self, state: AgentState) -> str:
        """Prefer article URL as the dedupe key, then fall back to normalized title."""

        group_kind = str(state.source_metadata.get("market_group_kind") or "")
        if group_kind == "overview":
            source_url = str(state.source_metadata.get("market_watch_source") or state.source_ref or "").strip()
            if source_url:
                return f"{source_url}#overview"
        article_url = str(
            state.source_metadata.get("market_article_url")
            or state.source_ref
            or ""
        ).strip()
        if article_url:
            return article_url

        fallback_title = (
            state.normalized_item.source_title if state.normalized_item is not None else ""
        )
        title = str(
            state.source_metadata.get("market_article_title") or fallback_title
        ).strip()
        return re.sub(r"\s+", " ", title.lower())

    def analyze_submission(
        self,
        content: str,
        *,
        visit_links: bool | None = None,
    ) -> SubmissionAnalysis:
        """Classify one pasted input as text, link, or mixed content."""

        urls = list(dict.fromkeys(URL_PATTERN.findall(content)))
        context_text = URL_PATTERN.sub(" ", content)
        context_text = re.sub(r"\s+", " ", context_text).strip()

        if urls and context_text:
            input_kind = "mixed"
        elif urls:
            input_kind = "link"
        else:
            input_kind = "text"

        reasons: list[str] = []
        if urls:
            reasons.append("detected urls")
        if context_text and self._looks_recruiting_or_market_text(context_text):
            reasons.append("context looks recruiting or market related")
        if input_kind == "link":
            reasons.append("pure link submission")

        if visit_links is not None:
            should_visit_links = visit_links and bool(urls)
        else:
            should_visit_links = bool(urls) and (
                input_kind == "link"
                or not context_text
                or self._has_sparse_context(context_text)
                or self._looks_recruiting_or_market_text(context_text)
                or any(self._looks_supported_domain(url) for url in urls)
            )

        standardized = self._standardize_submission_with_prompt(
            content=content,
            heuristic_input_kind=input_kind,
            heuristic_urls=urls,
            heuristic_context_text=context_text,
        )
        if standardized is not None:
            standardized_kind = str(standardized.get("input_kind") or "").strip()
            if standardized_kind in {"text", "link", "mixed"}:
                input_kind = standardized_kind
            if isinstance(standardized.get("should_visit_links"), bool):
                should_visit_links = bool(standardized["should_visit_links"]) and bool(urls)
            reason = str(standardized.get("reason") or "").strip()
            if reason:
                reasons.append(f"prompt standardized: {reason}")

        return SubmissionAnalysis(
            input_kind=input_kind,
            context_text=context_text,
            urls=urls,
            should_visit_links=should_visit_links,
            reasons=reasons or ["fallback text ingest"],
            keyword_hints=[],
        )

    def _standardize_submission_with_prompt(
        self,
        *,
        content: str,
        heuristic_input_kind: str,
        heuristic_urls: list[str],
        heuristic_context_text: str,
    ) -> dict | None:
        """Use the prompt library to standardize `/ingest/auto` intake when live LLM is available."""

        route = self.dependencies.model_router.select("classify", "medium")
        if not self.dependencies.llm_gateway.is_available(route):
            return None

        try:
            prompt = self.dependencies.prompt_loader.load("intake_standardize")
            response = self.dependencies.llm_gateway.complete_json(
                route=route,
                task_name="intake_standardize",
                system_prompt=prompt,
                user_payload={
                    "content": content,
                    "heuristic_input_kind": heuristic_input_kind,
                    "heuristic_urls": heuristic_urls,
                    "heuristic_context_text": heuristic_context_text,
                },
            )
        except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
            return None

        if not isinstance(response, dict):
            return None
        return response

    def _looks_recruiting_or_market_text(self, text: str) -> bool:
        keywords = (
            "招聘",
            "岗位",
            "投递",
            "jd",
            "面试",
            "薪资",
            "公司",
            "行情",
            "市场",
            "机会",
            "内推",
        )
        lowered = text.lower()
        return any(keyword in lowered for keyword in keywords)

    def _has_sparse_context(self, text: str) -> bool:
        """Treat very short surrounding text as insufficient and prefer fetching the linked page."""

        normalized = re.sub(r"\s+", "", text)
        return bool(normalized) and len(normalized) <= 18

    def _has_explicit_search_instruction(self, content: str) -> bool:
        """Detect when the user explicitly asks the agent to search the web before continuing."""

        lowered = content.lower()
        return any(pattern in lowered for pattern in SEARCH_INSTRUCTION_PATTERNS)

    def _strip_search_instruction(self, content: str) -> str:
        """Remove explicit search instructions so the remaining text can seed the query."""

        cleaned = content
        for pattern in SEARCH_INSTRUCTION_PATTERNS:
            cleaned = cleaned.replace(pattern, " ")
        cleaned = URL_PATTERN.sub(" ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip("，。；;：: ")

    def _collect_search_references(
        self,
        *,
        content: str,
        analysis: SubmissionAnalysis,
        user_id: str,
        workspace_id: str | None,
    ) -> list[str]:
        """Run an explicit web search only when the user clearly asked for it."""

        if not self._has_explicit_search_instruction(content):
            return []

        profile_memory, career_state_memory = self._load_profile_context(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        query_seed = self._strip_search_instruction(content)
        profile_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        query_parts = [query_seed, " ".join(profile_terms[:3])]
        query = " ".join(part for part in query_parts if part).strip()
        if not query:
            query = " ".join(profile_terms[:4]).strip()
        if not query:
            return []

        try:
            results = self.dependencies.search_client.search(query=query, limit=4)
        except Exception:
            return []

        references: list[str] = []
        for result in results:
            title = str(result.get("title") or "").strip()
            snippet = str(result.get("snippet") or "").strip()
            url = str(result.get("url") or "").strip()
            if not title and not snippet:
                continue
            reference = " | ".join(part for part in (title, snippet, url) if part)
            if reference:
                references.append(reference)
        return references[:3]

    def _looks_supported_domain(self, url: str) -> bool:
        hostname = urlparse(url).netloc.lower()
        return any(
            keyword in hostname
            for keyword in (
                "zhipin",
                "job",
                "jobs",
                "lagou",
                "liepin",
                "linkedin",
                "boss",
                "kanzhun",
                "alibaba",
                "antgroup",
                "lingxigames",
                "weixin",
                "qq.com",
            )
        )

    def _split_link_payload(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []

        boundaries = {0}
        for pattern in (
            r"(?=(?:\d+[\.、]))",
            r"(?=(?:【[^】]{2,20}】))",
            r"(?=(?:公司[:：]))",
            r"(?=(?:[^\s，,。；;]{2,20}(?:公司|集团|科技|信息|网络|汽车|智能)))",
        ):
            boundaries.update(match.start() for match in re.finditer(pattern, normalized))

        ordered = sorted(boundaries)
        if len(ordered) <= 1:
            return [normalized]

        segments: list[str] = []
        for index, start in enumerate(ordered):
            end = ordered[index + 1] if index + 1 < len(ordered) else len(normalized)
            piece = normalized[start:end].strip(" ，,。；;")
            if len(piece) < 20 or not self._looks_recruiting_or_market_text(piece):
                continue
            segments.append(piece)

        unique_segments: list[str] = []
        seen: set[str] = set()
        for segment in segments:
            key = segment[:120]
            if key in seen:
                continue
            seen.add(key)
            unique_segments.append(segment)

        return unique_segments[:6] or [normalized]

    def _discover_keyword_hints(
        self,
        content: str,
        analysis: SubmissionAnalysis,
        *,
        user_id: str,
        workspace_id: str | None,
    ) -> list[str]:
        """Recognize profile-guided seed entities, run one-shot search, and expand related keywords."""

        profile_memory, career_state_memory = self._load_profile_context(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        hints = self._extract_seed_entities(
            content,
            profile_memory=profile_memory,
            career_state_memory=career_state_memory,
        )
        if not hints:
            return []

        query = self._build_keyword_search_query(hints, analysis)
        results: list[dict] = []
        if query:
            try:
                results = self.dependencies.search_client.search(query=query, limit=5)
            except Exception:
                results = []

        discovered: list[str] = []
        for result in results:
            discovered.extend(
                self._extract_keyword_candidates(
                    " ".join(
                        [
                            str(result.get("title") or ""),
                            str(result.get("snippet") or ""),
                        ]
                    )
                )
            )

        merged: list[str] = []
        seen: set[str] = set()
        for candidate in [*hints, *discovered]:
            cleaned = re.sub(r"\s+", "", str(candidate)).strip(" -：:")
            if (
                len(cleaned) < 2
                or cleaned in seen
                or cleaned in GENERIC_KEYWORD_HINTS
                or cleaned.startswith("届")
            ):
                continue
            seen.add(cleaned)
            merged.append(cleaned)
        return merged[:16]

    def _extract_seed_entities(
        self,
        content: str,
        *,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> list[str]:
        """Collect profile-guided theme candidates plus early company/business markers."""

        seeds: list[str] = []
        seeds.extend(
            self._derive_profile_guided_topics(
                content,
                profile_memory=profile_memory,
                career_state_memory=career_state_memory,
            )
        )
        for match in re.finditer(r"【([^】]+)】", content):
            seeds.extend(self._extract_keyword_candidates(match.group(1)))

        for match in TOPIC_MARKER_PATTERN.finditer(content):
            seeds.append(match.group(1).strip())

        seeds.extend(
            match.group(1).strip()
            for match in re.finditer(r"([A-Za-z0-9\u4e00-\u9fff]{2,12}系)", content)
        )

        first_lines = [line.strip() for line in content.splitlines()[:4] if line.strip()]
        for line in first_lines:
            campaign_company = self._extract_campaign_company(line)
            if campaign_company:
                seeds.append(campaign_company)
            seeds.extend(self._extract_keyword_candidates(line))

        merged: list[str] = []
        seen: set[str] = set()
        for seed in seeds:
            normalized = re.sub(r"\s+", "", seed)
            if (
                len(normalized) < 2
                or normalized in seen
                or normalized in GENERIC_KEYWORD_HINTS
                or normalized.startswith("届")
            ):
                continue
            seen.add(normalized)
            merged.append(seed.strip())
        return merged[:6]

    def _load_profile_context(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
    ) -> tuple[ProfileMemory, CareerStateMemory]:
        """Load current profile and career-state memory for profile-guided intake."""

        current = self.dependencies.memory_provider.load(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        return (
            ProfileMemory.model_validate(current["profile_memory"]),
            CareerStateMemory.model_validate(current["career_state_memory"]),
        )

    def _derive_profile_guided_topics(
        self,
        content: str,
        *,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> list[str]:
        """Use user profile focus to decide which top-of-text theme lines deserve expansion."""

        profile_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        content_candidates = self._extract_topic_candidates_from_content(content)
        if not profile_terms:
            return content_candidates[:2]

        scored: list[tuple[int, str]] = []
        for candidate in content_candidates:
            score = max(
                self._score_topic_overlap(candidate, profile_term)
                for profile_term in profile_terms
            )
            if score > 0:
                scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        ordered_topics = [candidate for _, candidate in scored]
        if ordered_topics:
            return list(dict.fromkeys(ordered_topics))[:2]
        return content_candidates[:1]

    def _collect_profile_focus_terms(
        self,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> list[str]:
        """Gather stable and current user-focus phrases that can anchor theme detection."""

        raw_terms = [
            *profile_memory.priority_domains,
            *profile_memory.target_roles,
            *profile_memory.soft_preferences,
            *profile_memory.skills,
            *career_state_memory.watched_companies,
            *career_state_memory.today_focus,
            *career_state_memory.active_priorities,
        ]
        normalized: list[str] = []
        seen: set[str] = set()
        for value in raw_terms:
            cleaned = self._normalize_topic_phrase(value)
            if len(cleaned) < 2 or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    def _collect_market_keyword_terms(
        self,
        *,
        profile_memory: ProfileMemory,
        career_state_memory: CareerStateMemory,
    ) -> list[str]:
        """Expand profile memory into broader market-title matching keywords."""

        base_terms = self._collect_profile_focus_terms(profile_memory, career_state_memory)
        expanded: list[str] = []
        for value in base_terms:
            expanded.append(value)
            expanded.extend(self._extract_keyword_candidates(value))
            expanded.extend(
                match.group(0)
                for match in re.finditer(r"[A-Za-z][A-Za-z0-9.+#-]{1,20}|[\u4e00-\u9fff]{2,10}", value)
            )

        normalized: list[str] = []
        seen: set[str] = set()
        for term in [*expanded, *MARKET_VALUE_KEYWORDS]:
            cleaned = self._normalize_topic_phrase(term)
            if len(cleaned) < 2 or cleaned in seen or cleaned in GENERIC_KEYWORD_HINTS:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized[:32]

    def _extract_topic_candidates_from_content(self, content: str) -> list[str]:
        """Collect possible theme heads from the pasted text without assuming a fixed company library."""

        candidates: list[str] = []
        first_lines = [line.strip() for line in content.splitlines()[:6] if line.strip()]
        for line in first_lines:
            normalized_line = self._normalize_topic_phrase(line)
            if 2 <= len(normalized_line) <= 18:
                candidates.append(normalized_line)
            for match in TOPIC_MARKER_PATTERN.finditer(line):
                normalized = self._normalize_topic_phrase(match.group(1))
                if len(normalized) >= 2:
                    candidates.append(normalized)

        return list(dict.fromkeys(candidates))

    def _normalize_topic_phrase(self, text: str) -> str:
        """Trim emoji, numbering, and recruiting boilerplate from a topic phrase."""

        cleaned = str(text).strip()
        cleaned = re.sub(r"^\s*#\s*", "", cleaned)
        cleaned = re.sub(r"^\s*[0-9①②③④⑤⑥⑦⑧⑨⑩]+[^\u4e00-\u9fffA-Za-z0-9]*", "", cleaned)
        cleaned = re.sub(r"[🔥❗️❗⏰📅🕹🔗👉🏻～~]+", " ", cleaned)
        cleaned = re.sub(
            r"(?:笔试提醒|招聘提醒|招聘信息|招聘汇总|信息汇总|每日更新|欢迎分享|仅可内推.*|内推链接.*|内推码.*)$",
            "",
            cleaned,
        )
        cleaned = re.sub(r"(?:相关|方向|赛道)$", "", cleaned)
        cleaned = re.sub(r"\(.*?\)|（.*?）", " ", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        return cleaned.strip(" -：:")

    def _score_topic_overlap(self, candidate: str, profile_term: str) -> int:
        """Score how strongly a content-side topic candidate matches the user's profile focus."""

        left = self._normalize_topic_phrase(candidate)
        right = self._normalize_topic_phrase(profile_term)
        if not left or not right:
            return 0
        if left == right:
            return 10
        if left in right or right in left:
            return min(len(left), len(right)) + 4

        common_length = self._longest_common_substring_length(left, right)
        if common_length >= 2:
            return common_length * 2
        return 0

    def _longest_common_substring_length(self, left: str, right: str) -> int:
        """Compute a tiny longest-common-substring score for short profile/topic phrases."""

        if not left or not right:
            return 0

        longest = 0
        previous = [0] * (len(right) + 1)
        for left_char in left:
            current = [0]
            for index, right_char in enumerate(right, start=1):
                if left_char == right_char:
                    value = previous[index - 1] + 1
                    current.append(value)
                    if value > longest:
                        longest = value
                else:
                    current.append(0)
            previous = current
        return longest

    def _build_keyword_search_query(
        self,
        hints: list[str],
        analysis: SubmissionAnalysis,
    ) -> str | None:
        """Build one web search query for business-line keyword discovery."""

        if not hints:
            return None
        top_hints = " ".join(hints[:3])
        return f"{top_hints} 招聘 业务 品牌 团队 实习 校招"

    def _extract_keyword_candidates(self, text: str) -> list[str]:
        """Extract plausible business-line keywords from text snippets."""

        candidates: list[str] = []
        include_match = re.search(
            r"(?:包括|包含|常见公司包括|例如|如)\s*([A-Za-z0-9\u4e00-\u9fff、，, /]{2,60})",
            text,
        )
        if include_match:
            for piece in re.split(r"[、，,/ ]+", include_match.group(1)):
                normalized_piece = self._normalize_topic_phrase(piece)
                if 2 <= len(normalized_piece) <= 12:
                    candidates.append(normalized_piece)
        for pattern in (
            r"#?\s*([A-Za-z0-9\u4e00-\u9fff]{2,12})(?:相关|方向|赛道)",
            r"([A-Za-z0-9\u4e00-\u9fff]{2,16}系)",
            r"([A-Za-z0-9\u4e00-\u9fff]{2,18}(?:集团|公司|科技|网络|智能|云|游戏|互娱|电商|零售|物流|金融|汽车))",
            r"([A-Za-z0-9\u4e00-\u9fff]{2,12}(?:闪购|电商|淘天|菜鸟|蚂蚁|云|互娱|游戏|出行|零售|物流|视频))",
            r"([A-Za-z\u4e00-\u9fff]{2,12})\s+(?:暑期实习|校招|秋招|春招|社招)",
            r"([A-Za-z\u4e00-\u9fff]{2,12})\s*(?:27届|26届|25届|暑期实习|秋储实习生|预投递|实习|校招|招聘)",
        ):
            candidates.extend(match.group(1).strip() for match in re.finditer(pattern, text))
        return candidates

    def _split_submission_sections(
        self,
        content: str,
        *,
        keyword_hints: list[str],
    ) -> tuple[str, list[SubmissionSection]]:
        """Split one pasted submission into shared context plus logical sections."""

        lines = [line.strip() for line in content.splitlines()]
        shared_lines: list[str] = []
        sections: list[SubmissionSection] = []
        current_title: str | None = None
        current_lines: list[str] = []

        for line in lines:
            if not line:
                continue
            header_title = self._extract_section_header_title(line)
            is_numbered_line = bool(re.match(r"^\s*(?:\d+|[①②③④⑤⑥⑦⑧⑨⑩])", line))
            is_section_header = self._looks_like_section_header(
                line=line,
                header_title=header_title,
                is_numbered_line=is_numbered_line,
            )
            if is_section_header:
                if current_title and current_lines:
                    sections.append(
                        self._build_submission_section(
                            current_title,
                            current_lines,
                            shared_lines,
                            keyword_hints=keyword_hints,
                        )
                    )
                current_title = self._clean_section_title(header_title)
                current_lines = [line]
                continue

            if current_title:
                current_lines.append(line)
            else:
                shared_lines.append(line)

        if current_title and current_lines:
            sections.append(
                self._build_submission_section(
                    current_title,
                    current_lines,
                    shared_lines,
                    keyword_hints=keyword_hints,
                )
            )

        if not sections:
            inferred_section = self._build_unstructured_submission_section(
                content,
                keyword_hints=keyword_hints,
            )
            if inferred_section is not None:
                sections.append(inferred_section)

        shared_context = "\n".join(shared_lines).strip()
        return shared_context, sections

    def _looks_like_section_header(
        self,
        *,
        line: str,
        header_title: str | None,
        is_numbered_line: bool,
    ) -> bool:
        """Decide whether one line should start a new recruiting section."""

        if not header_title:
            return False
        if header_title in NON_SECTION_BRACKET_TITLES:
            return False
        return bool(
            "【" in line
            or (
                is_numbered_line
                and any(
                    keyword in line
                    for keyword in ("内推", "实习", "校招", "秋招", "春招", "社招", "招聘")
                )
            )
        )

    def _build_submission_section(
        self,
        title: str,
        lines: list[str],
        shared_lines: list[str],
        *,
        keyword_hints: list[str],
    ) -> SubmissionSection:
        """Build one normalized submission section with semantic tags and role variants."""

        section_text = "\n".join(lines).strip()
        relationships = self._derive_section_relationships(
            title=title,
            section_text=section_text,
            shared_context="\n".join(shared_lines).strip(),
            keyword_hints=keyword_hints,
        )
        return SubmissionSection(
            section_title=title,
            section_text=section_text,
            urls=list(dict.fromkeys(URL_PATTERN.findall(section_text))),
            semantic_tags=relationships["semantic_tags"],
            role_variants=self._extract_role_variants(section_text),
            relationship_family=relationships["relationship_family"],
            relationship_stage=relationships["relationship_stage"],
            primary_unit=relationships["primary_unit"],
            identity_tag=relationships["identity_tag"],
        )

    def _build_unstructured_submission_section(
        self,
        content: str,
        *,
        keyword_hints: list[str],
    ) -> SubmissionSection | None:
        """Create one candidate section from a long recruiting bulletin with no explicit numbered cards."""

        normalized_content = content.strip()
        if not normalized_content or not self._looks_recruiting_or_market_text(normalized_content):
            return None
        non_empty_lines = [line.strip() for line in normalized_content.splitlines() if line.strip()]
        if len(non_empty_lines) < 3 and URL_PATTERN.search(normalized_content):
            return None

        title = self._infer_submission_title_from_content(
            normalized_content,
            keyword_hints=keyword_hints,
        )
        relationships = self._derive_section_relationships(
            title=title,
            section_text=normalized_content,
            shared_context="",
            keyword_hints=keyword_hints,
        )
        urls = list(dict.fromkeys(URL_PATTERN.findall(normalized_content)))
        if not urls:
            urls = self._extract_domain_urls(normalized_content)

        return SubmissionSection(
            section_title=title,
            section_text=normalized_content,
            urls=urls,
            semantic_tags=relationships["semantic_tags"],
            role_variants=[],
            relationship_family=None,
            relationship_stage=relationships["relationship_stage"],
            primary_unit=None,
            identity_tag=None,
        )

    def _infer_submission_title_from_content(
        self,
        content: str,
        *,
        keyword_hints: list[str],
    ) -> str:
        """Infer a stable card title for one long-form recruiting campaign bulletin."""

        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        cleaned_line = self._clean_section_title(first_line)
        company = self._extract_campaign_company(cleaned_line)
        campaign = self._extract_campaign_stage_phrase(cleaned_line) or self._extract_campaign_stage_phrase(content)

        if company and campaign:
            return f"{company}-{campaign}"
        if company:
            return company

        for hint in keyword_hints:
            normalized_hint = self._normalize_topic_phrase(hint)
            if normalized_hint and normalized_hint not in GENERIC_KEYWORD_HINTS:
                if campaign and normalized_hint != campaign:
                    return f"{normalized_hint}-{campaign}"
                return normalized_hint

        return cleaned_line[:24] or "未命名岗位"

    def _extract_campaign_company(self, text: str) -> str | None:
        """Extract the leading company/business name from campaign-style titles."""

        match = re.search(
            r"^\s*([A-Za-z\u4e00-\u9fff]{2,16})\s*(?=(?:20\d{2}|[0-9]{2})届|(?:春季)?校招|春招|秋招|暑期实习|日常实习|招聘|正式启动)",
            text,
        )
        if match:
            return match.group(1).strip(" -：:")
        return None

    def _extract_campaign_stage_phrase(self, text: str) -> str | None:
        """Extract a campaign label such as 2026届春季校招 from one bulletin."""

        for pattern in (
            r"((?:20\d{2}|[0-9]{2})届春季校招)",
            r"((?:20\d{2}|[0-9]{2})届校招)",
            r"((?:20\d{2}|[0-9]{2})届秋招)",
            r"((?:20\d{2}|[0-9]{2})届春招)",
            r"((?:20\d{2}|[0-9]{2})届暑期实习)",
            r"(春季校招)",
            r"(春招)",
            r"(秋招)",
            r"(暑期实习)",
            r"(校招)",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    def _extract_domain_urls(self, text: str) -> list[str]:
        """Promote bare domains into source refs when the input omits URL schemes."""

        urls: list[str] = []
        for match in DOMAIN_PATTERN.findall(text):
            candidate = match.strip("，。；;：:")
            if "." not in candidate:
                continue
            if candidate.lower().startswith("http://") or candidate.lower().startswith("https://"):
                urls.append(candidate)
            else:
                urls.append(f"https://{candidate}")
        return list(dict.fromkeys(urls))

    def _derive_fallback_source_title(
        self,
        *,
        original_content: str,
        fetched_texts: list[str],
        page_title: str,
        keyword_hints: list[str],
    ) -> str:
        """Build a less-generic fallback card title after proactive link fetching."""

        combined_text = "\n".join(segment for segment in fetched_texts if segment).strip()
        if combined_text:
            return self._infer_submission_title_from_content(
                combined_text,
                keyword_hints=keyword_hints,
            )
        if page_title and page_title != "微信公众平台":
            return self._clean_section_title(page_title)
        if original_content.startswith("http://") or original_content.startswith("https://"):
            return "链接待解析卡片"
        return "统一输入卡片"

    def _clean_section_title(self, raw_title: str) -> str:
        """Normalize the visible title extracted from a numbered section header."""

        title = raw_title
        title = re.sub(r"[🔥❗️❗⏰📅🕹🔗]+", " ", title)
        title = title.replace("【", " ").replace("】", " ")
        title = re.sub(r"\s+", " ", title).strip(" -")
        return title or "未命名岗位"

    def _extract_section_header_title(self, line: str) -> str | None:
        """Extract a stable section title from numbered lines with emoji or brackets."""

        bracket_match = re.search(r"【([^】]+)】", line)
        if bracket_match:
            return bracket_match.group(1).strip()

        cleaned = re.sub(r"^\s*[0-9①②③④⑤⑥⑦⑧⑨⑩]+[^\u4e00-\u9fffA-Za-z0-9]*", "", line)
        cleaned = cleaned.strip()
        return cleaned or None

    def _derive_section_relationships(
        self,
        *,
        title: str,
        section_text: str,
        shared_context: str,
        keyword_hints: list[str],
    ) -> dict[str, str | list[str] | None]:
        """Build platform-agnostic relationship tags from shared context and title."""

        tags: list[str] = []
        combined = f"{shared_context}\n{title}\n{section_text}"

        family = self._extract_relationship_family(shared_context=shared_context, title=title)
        stage = self._extract_relationship_stage(combined)
        unit = self._extract_primary_unit(title=title, keyword_hints=keyword_hints)

        if family:
            tags.append(family)
        if stage:
            tags.append(stage)
        if unit:
            tags.append(unit)

        identity_tag = None
        if family and stage and unit:
            identity_tag = f"{family}-{stage}-{unit}"
        elif family and unit:
            identity_tag = f"{family}-{unit}"
        elif stage and unit:
            identity_tag = f"{stage}-{unit}"
        if identity_tag:
            tags.append(identity_tag)

        return {
            "semantic_tags": list(dict.fromkeys(tag for tag in tags if tag)),
            "relationship_family": family,
            "relationship_stage": stage,
            "primary_unit": unit,
            "identity_tag": identity_tag,
        }

    def _extract_role_variants(self, section_text: str) -> list[str]:
        """Extract role variants listed inside one business-line section."""

        variants = [
            match.group(1).strip("：: ;；")
            for match in re.finditer(
                r"[①②③④⑤⑥⑦⑧⑨⑩]\s*([^\n①②③④⑤⑥⑦⑧⑨⑩]+)",
                section_text,
            )
        ]
        cleaned = [
            variant
            for variant in variants
            if any(keyword in variant for keyword in ("工程师", "分析师", "经理"))
        ]
        return list(dict.fromkeys(cleaned))

    def _extract_relationship_family(self, *, shared_context: str, title: str) -> str | None:
        """Infer one organization family tag without hard-coding specific companies."""

        for source in (shared_context, title):
            match = re.search(r"([A-Za-z0-9\u4e00-\u9fff]{2,12}系)", source)
            if match:
                return match.group(1).strip()

        if shared_context:
            first_line = next(
                (line.strip() for line in shared_context.splitlines() if line.strip()),
                "",
            )
            match = re.search(
                r"([A-Za-z0-9\u4e00-\u9fff]{2,16}?)(?:笔试提醒|招聘提醒|招聘信息|招聘汇总|暑期实习|日常实习|实习|校招|秋招|春招|社招)",
                first_line,
            )
            if match:
                return match.group(1).strip(" -：:")

        return None

    def _extract_relationship_stage(self, text: str) -> str | None:
        """Infer one recruiting stage tag such as 暑期实习 / 校招."""

        for candidate in SEASON_TAGS:
            if candidate in text:
                return candidate
        return None

    def _extract_primary_unit(self, *, title: str, keyword_hints: list[str]) -> str | None:
        """Derive the concrete business unit or company name from one section title."""

        cleaned = re.sub(r"\(.*?\)|（.*?）", " ", title)
        cleaned = re.sub(r"20\d{2,4}", " ", cleaned)
        for token in (
            "暑期实习",
            "日常实习",
            "实习",
            "校招",
            "秋招",
            "春招",
            "社招",
            "招聘",
            "岗位",
            "内推",
            "计划",
            "批次",
        ):
            cleaned = cleaned.replace(token, " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -：:")
        if not cleaned:
            return None

        direct_match = re.match(r"([A-Za-z\u4e00-\u9fff]{2,12})\b", cleaned)
        if direct_match:
            return direct_match.group(1).strip()

        leading_parts = [
            part.strip()
            for part in re.split(r"[-/| ]+", cleaned)
            if part.strip() and len(part.strip()) >= 2
        ]
        if leading_parts:
            normalized_head = self._normalize_topic_phrase(leading_parts[0])
            if 2 <= len(normalized_head) <= 12:
                return normalized_head

        for hint in keyword_hints:
            if hint in cleaned and len(hint) >= 2:
                return hint

        match = ORG_SUFFIX_PATTERN.search(cleaned)
        if match:
            return match.group(1).strip()

        if not leading_parts:
            return None
        return cleaned if len(cleaned) <= 18 else leading_parts[0]

    def _select_shared_context_for_candidate(
        self,
        *,
        shared_context: str,
        semantic_tags: list[str],
        keyword_hints: list[str],
    ) -> str:
        """Keep the shared rules block with each card, but only in a filtered form."""

        if not shared_context:
            return ""

        lines = [line.strip() for line in shared_context.splitlines() if line.strip()]
        tokens = {
            token
            for token in [*semantic_tags, *keyword_hints]
            if len(str(token).strip()) >= 2
        }
        selected: list[str] = []
        for line in lines:
            if any(keyword in line for keyword in ("笔试", "面试", "终面", "DDL", "投递", "内推")):
                selected.append(line)
                continue
            if any(token in line for token in tokens):
                selected.append(line)

        merged = list(dict.fromkeys(selected or lines[:3]))
        return "\n".join(merged[:4])

    def _expand_section_variants(self, section: SubmissionSection) -> list[dict]:
        """Expand one section into one or more card candidates."""

        if not section.role_variants:
            source_title = section.identity_tag or section.primary_unit or section.section_title
            return [
                {
                    "source_title": source_title,
                    "section_text": section.section_text,
                    "urls": section.urls,
                    "semantic_tags": section.semantic_tags,
                    "role_variant": None,
                    "relationship_family": section.relationship_family,
                    "relationship_stage": section.relationship_stage,
                    "primary_unit": section.primary_unit,
                    "identity_tag": section.identity_tag,
                }
            ]

        variants: list[dict] = []
        base_title = section.identity_tag or section.primary_unit or section.section_title
        for role_variant in section.role_variants:
            variants.append(
                {
                    "source_title": f"{base_title}-{role_variant}",
                    "section_text": f"{section.section_text}\n岗位细分：{role_variant}",
                    "urls": section.urls,
                    "semantic_tags": [*section.semantic_tags, role_variant],
                    "role_variant": role_variant,
                    "relationship_family": section.relationship_family,
                    "relationship_stage": section.relationship_stage,
                    "primary_unit": section.primary_unit,
                    "identity_tag": section.identity_tag,
                }
            )
        return variants

    def _is_collection_only_section(self, section: SubmissionSection) -> bool:
        """Skip generic collection links that are not one concrete recruiting card."""

        hostname = urlparse(section.urls[0]).netloc.lower() if section.urls else ""
        return (
            "汇总" in section.section_title
            and ("docs.qq.com" in hostname or "smartsheet" in hostname)
        )

    def _should_visit_url(
        self,
        *,
        url: str,
        shared_context: str,
        section_text: str,
        visit_links: bool | None,
        force_visit: bool = False,
    ) -> bool:
        """Decide whether one URL is worth visiting for more recruiting context."""

        if visit_links is False:
            return False

        hostname = urlparse(url).netloc.lower()
        combined = f"{shared_context}\n{section_text}"
        if "docs.qq.com" in hostname and "汇总" in combined:
            return False
        if force_visit:
            return True
        if any(keyword in hostname for keyword in ("campus-talent.alibaba.com", "antgroup.com", "lingxigames.com")):
            return True
        if "go.lingxigames.com" in hostname:
            return True
        return self._looks_supported_domain(url) and self._looks_recruiting_or_market_text(combined)

    def _select_relevant_fetched_segments(
        self,
        *,
        section_title: str,
        section_text: str,
        role_variant: str | None,
        keyword_hints: list[str],
        fetched_segments: list[str],
    ) -> list[str]:
        """Choose the most relevant fetched snippets for one card candidate."""

        if not fetched_segments:
            return []
        if not role_variant:
            return fetched_segments[:2]

        tokens = {
            token
            for token in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,8}", f"{section_title} {role_variant}")
            if len(token) >= 2
        }
        tokens.update(token for token in keyword_hints if len(str(token)) >= 2)
        scored = []
        for segment in fetched_segments:
            score = sum(1 for token in tokens if token in segment)
            scored.append((score, segment))
        scored.sort(key=lambda item: item[0], reverse=True)
        top = [segment for score, segment in scored if score > 0][:2]
        return top or fetched_segments[:1]

    def _compose_contextual_payload(
        self,
        *,
        source_title: str,
        shared_context: str,
        section_text: str,
        relationship_tags: list[str],
        keyword_hints: list[str],
        search_references: list[str],
        fetched_texts: list[str],
    ) -> str:
        """Compose one role-focused payload with structured shared rules."""

        parts: list[str] = []
        if source_title:
            parts.append(f"岗位标题：{source_title}")
        if relationship_tags:
            parts.append(f"关系标签：{'、'.join(relationship_tags[:5])}")
        if keyword_hints:
            parts.append(f"关键词提示：{'、'.join(keyword_hints[:8])}")
        if search_references:
            parts.append("搜索参考：")
            parts.extend(search_references[:2])
        if shared_context:
            parts.append(f"共享规则：{shared_context}")
        parts.append(f"当前岗位片段：{section_text}")
        if fetched_texts:
            parts.append("链接解析结果：")
            parts.extend(fetched_texts[:2])
        return "\n".join(parts)

    def _extract_shared_exam_dates(self, text: str) -> list[datetime]:
        """Parse shared written-test dates from top-level context text."""

        if "笔试" not in text and "剩余" not in text:
            return []
        return extract_all_datetimes(text)

    def _build_fetch_plan(
        self,
        *,
        url: str,
        shared_context: str,
        section_text: str,
        source_title: str,
        role_variant: str | None,
    ) -> dict:
        """Describe why one link should be visited and which fields to collect."""

        return {
            "url": url,
            "target_card": source_title,
            "role_variant": role_variant,
            "decision_reason": "补全岗位详情、投递方式、地点、DDL 与笔面试相关信息。",
            "context_summary": (shared_context or section_text)[:180],
            "must_collect": [
                "岗位名称与业务线",
                "岗位职责与要求",
                "投递方式与截止时间",
                "地点或线上信息",
                "笔试/面试/测评相关提示",
            ],
        }

    def _is_location_pending(
        self,
        *,
        section_text: str,
        fetched_texts: list[str],
    ) -> bool:
        """Mark cards whose location still depends on downstream confirmation."""

        combined = "\n".join([section_text, *fetched_texts])
        if extract_city(combined):
            return False
        return any(keyword in combined for keyword in ("投递", "后续通知", "线上", "待确认"))

    def _build_batch_analysis_payload(self, state: AgentState) -> dict:
        """Build one card payload for deeper batch analysis."""

        normalized = state.normalized_item
        extracted = state.extracted_signal
        return {
            "item_id": normalized.id if normalized else None,
            "title": (
                normalized.source_title
                if normalized and normalized.source_title
                else extracted.summary_one_line if extracted else None
            ),
            "summary": extracted.summary_one_line if extracted else None,
            "company": extracted.company if extracted else None,
            "role": extracted.role if extracted else None,
            "city": extracted.city if extracted else None,
            "ddl": extracted.ddl.isoformat() if extracted and extracted.ddl else None,
            "tags": extracted.tags if extracted else [],
            "source_ref": state.source_ref,
            "raw_content": normalized.raw_content if normalized else state.raw_input,
            "normalized_text": normalized.normalized_text if normalized else None,
            "shared_context": state.source_metadata.get("shared_context"),
            "original_section_text": state.source_metadata.get("original_section_text"),
        }

    def _build_batch_analysis_fallback(
        self,
        *,
        states: list[AgentState],
        question: str,
    ) -> str:
        """Provide a deterministic local summary when live LLM analysis is unavailable."""

        titles: list[str] = []
        ddl_values: list[str] = []
        relation_tags: list[str] = []
        source_links: list[str] = []

        for state in states:
            normalized = state.normalized_item
            extracted = state.extracted_signal
            title = (
                normalized.source_title
                if normalized and normalized.source_title
                else extracted.summary_one_line if extracted else None
            )
            if title:
                titles.append(title)
            if extracted and extracted.ddl:
                ddl_values.append(extracted.ddl.strftime("%Y-%m-%d %H:%M"))
            for raw_tag in state.source_metadata.get("relationship_tags", []):
                tag = str(raw_tag).strip()
                if tag:
                    relation_tags.append(tag)
            if state.source_ref:
                source_links.append(state.source_ref)

        unique_tags = list(dict.fromkeys(relation_tags))
        unique_titles = list(dict.fromkeys(titles))
        unique_links = list(dict.fromkeys(source_links))
        unique_ddls = list(dict.fromkeys(ddl_values))

        lines = [
            f"分析问题：{question}",
            f"已分析卡片：{len(states)} 张",
        ]
        if unique_titles:
            lines.append("涉及岗位：")
            lines.extend(f"- {title}" for title in unique_titles[:8])
        if unique_tags:
            lines.append("共同关系：")
            lines.extend(f"- {tag}" for tag in unique_tags[:8])
        if unique_ddls:
            lines.append("关键DDL：")
            lines.extend(f"- {ddl}" for ddl in unique_ddls[:6])
        if unique_links:
            lines.append("原链接：")
            lines.extend(f"- {link}" for link in unique_links[:6])
        lines.append("说明：当前处于本地回退分析模式，已基于卡片原文与标准化文本做摘要。")
        return "\n".join(lines)

    def _build_fallback_card(self, state: AgentState) -> RenderedItemCard:
        normalized = state.normalized_item
        extracted = state.extracted_signal
        summary = (
            extracted.summary_one_line
            if extracted and extracted.summary_one_line
            else normalized.source_title
            or normalized.normalized_text[:80]
            or normalized.id
        )
        return RenderedItemCard(
            item_id=normalized.id,
            summary_one_line=summary,
            company=extracted.company if extracted else None,
            role=extracted.role if extracted else None,
            city=extracted.city if extracted else None,
            location_note=extracted.location_note if extracted else None,
            ddl=extracted.ddl if extracted else None,
            interview_time=extracted.interview_time if extracted else None,
            event_time=extracted.event_time if extracted else None,
            priority=state.score_result.priority if state.score_result else None,
            content_category=(
                extracted.category
                if extracted
                else state.classified_category or ContentCategory.UNKNOWN
            ),
            source_type=state.source_type,
            workflow_status=state.status,
            source_ref=state.source_ref,
            updated_at=self._state_timestamp(state) or now_in_project_timezone(),
            message_time=self._coerce_datetime(
                state.source_metadata.get("message_time")
                or state.source_metadata.get("published_at")
            )
            or normalized.created_at,
            generated_at=normalized.created_at,
            ai_score=round(state.score_result.total_score, 4) if state.score_result else None,
            insight_summary=summary,
            advice=state.score_result.reasoning if state.score_result else None,
            is_market_signal=bool(state.source_metadata.get("market_watch")),
            market_group_kind=str(state.source_metadata.get("market_group_kind") or "") or None,
            market_parent_item_id=str(state.source_metadata.get("market_parent_item_id") or "") or None,
            market_child_item_ids=list(state.source_metadata.get("market_child_item_ids", [])),
            market_child_previews=list(state.source_metadata.get("market_child_previews", [])),
            tags=extracted.tags if extracted else [],
        )

    def _state_timestamp(self, state: AgentState) -> datetime | None:
        card = state.render_card
        if card and card.updated_at:
            return card.updated_at
        if state.normalized_item is not None:
            return state.normalized_item.created_at
        return None

    def write_project_self_memory(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
        payload: ProjectSelfMemoryPayload,
    ) -> tuple[ProfileMemory, CareerStateMemory]:
        """
        Write one project entry into profile memory when the feature flag is enabled.

        This function is intentionally isolated from the main workflow so the
        experimental feature can be disabled or removed without touching the
        ingest / rank / reminder chain.
        """

        if not self.settings.feature_flags.enable_project_self_memory:
            raise PermissionError("ENABLE_PROJECT_SELF_MEMORY is disabled.")

        current = self.dependencies.memory_provider.load(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        profile_memory = ProfileMemory.model_validate(current["profile_memory"])
        updated_profile = self.project_self_memory_service.merge_into_profile(
            profile_memory=profile_memory,
            payload=payload,
        )
        current["profile_memory"] = updated_profile
        self.dependencies.memory_provider.save(
            {
                "user_id": user_id,
                "workspace_id": workspace_id,
                **current,
            }
        )
        return updated_profile, CareerStateMemory.model_validate(
            current["career_state_memory"]
        )


def build_default_profile_memory(
    payload: ProfileMemory,
) -> ProfileMemory:
    """Normalize profile memory timestamps in API write flows."""

    return payload.model_copy(update={"updated_at": now_in_project_timezone()})


def build_default_career_state_memory(
    payload: CareerStateMemory,
) -> CareerStateMemory:
    """Normalize career-state memory timestamps in API write flows."""

    return payload.model_copy(update={"updated_at": now_in_project_timezone()})


def build_profile_memory_from_write_request(
    *,
    user_id: str,
    workspace_id: str | None,
    target_roles: list[str],
    priority_domains: list[str],
    skills: list[str],
    location_preferences: list[str],
    soft_preferences: list[str],
    excluded_companies: list[str],
    summary: str | None,
) -> ProfileMemory:
    """Create a complete `ProfileMemory` from the simplified API write payload."""

    return ProfileMemory(
        user_id=user_id,
        workspace_id=workspace_id,
        target_roles=target_roles,
        priority_domains=priority_domains,
        skills=skills,
        projects=[],
        location_preferences=location_preferences,
        hard_filters=[],
        soft_preferences=soft_preferences,
        excluded_companies=excluded_companies,
        summary=summary,
        updated_at=now_in_project_timezone(),
    )


def build_career_state_from_write_request(
    *,
    user_id: str,
    workspace_id: str | None,
    watched_companies: list[str],
    market_watch_sources: list[str],
    market_article_fetch_limit: int,
    today_focus: list[str],
    active_priorities: list[str],
    notes: str | None,
) -> CareerStateMemory:
    """Create a complete `CareerStateMemory` from the simplified API write payload."""

    return CareerStateMemory(
        user_id=user_id,
        workspace_id=workspace_id,
        watched_companies=watched_companies,
        market_watch_sources=market_watch_sources,
        market_article_fetch_limit=market_article_fetch_limit,
        today_focus=today_focus,
        active_priorities=active_priorities,
        notes=notes,
        updated_at=now_in_project_timezone(),
    )
