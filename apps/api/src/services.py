"""Application services wiring the API layer to the workflow scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import re
import tempfile
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from core.chat import QueryAnalysis, RAGChatService, RAGDocument, RetrievedContext
from core.extraction.prompt_context import collect_prompt_references
from core.extraction.parse import extract_all_datetimes, extract_city, pick_next_datetime
from core.graph import JobWorkflow, create_initial_state
from core.memory.experimental import ProjectSelfMemoryPayload, ProjectSelfMemoryService
from core.runtime.dependencies import StaticModelRouter, WorkflowDependencies
from core.runtime.settings import (
    AppSettings,
    RuntimeOCROverrides,
    RuntimeProviderOverrides,
    RuntimeSourceFileOverrides,
    RuntimeSettingsOverrides,
)
from core.runtime.time import now_in_project_timezone
from core.schemas import (
    AgentState,
    CareerStateMemory,
    ContentCategory,
    HardFilter,
    MemoryWriteMode,
    PriorityLevel,
    ProfileMemory,
    ProjectMemoryEntry,
    ResumeStructuredProfile,
    ResumeStructuredSection,
    ResumeSnapshot,
    RenderedItemCard,
    SourceType,
)
from core.storage.runtime_settings import LocalRuntimeSettingsRepository
from core.tools import (
    CascadingOCRClient,
    DocumentTextExtractionResult,
    GeneralLLMOCRClient,
    LLMGatewayError,
    LocalTesseractOCRClient,
    NoopLLMGateway,
    NoopSearchClient,
    OpenAICompatibleLLMGateway,
    QwenVLOCRClient,
    WebSearchClient,
    build_ocr_client_from_settings,
    fetch_recent_site_titles,
)
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
NON_SECTION_ACTION_PREFIXES = (
    "填写内推码",
    "内推码",
    "网申链接",
    "投递链接",
    "投递方式",
    "申请方式",
    "官方内推投递",
    "点击链接",
    "链接地址",
    "链接",
    "扫码投递",
    "扫码申请",
    "立即投递",
)
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
IMAGE_FILE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
}
TEXT_FILE_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".log",
    ".yaml",
    ".yml",
}
DOCUMENT_FILE_SUFFIXES = TEXT_FILE_SUFFIXES | {".pdf"}
SOURCE_ARCHIVE_ROOT = Path("data/runtime/source_files")
RESUME_FILE_NAME_PATTERN = re.compile(r"(resume|cv|简历)", re.IGNORECASE)
RESUME_SECTION_MARKERS = (
    "教育经历",
    "项目经历",
    "实习经历",
    "工作经历",
    "校园经历",
    "技能",
    "专业技能",
    "自我评价",
)
PROJECT_FILE_NAME_PATTERN = re.compile(
    r"(project|项目|prd|设计|架构|方案|readme|说明)",
    re.IGNORECASE,
)
PROJECT_SECTION_MARKERS = (
    "项目背景",
    "项目简介",
    "项目说明",
    "项目经历",
    "技术栈",
    "系统设计",
    "系统架构",
    "职责",
    "负责",
    "难点",
    "亮点",
    "成果",
)
KNOWN_LOCATION_TERMS = (
    "上海",
    "北京",
    "杭州",
    "深圳",
    "广州",
    "苏州",
    "成都",
    "南京",
    "武汉",
    "西安",
    "远程",
)
KNOWN_SKILL_TERMS = (
    "Python",
    "Java",
    "C++",
    "Go",
    "Rust",
    "TypeScript",
    "JavaScript",
    "FastAPI",
    "Django",
    "Flask",
    "React",
    "Next.js",
    "Vue",
    "PyTorch",
    "TensorFlow",
    "SQL",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "Docker",
    "Kubernetes",
    "Linux",
    "RAG",
    "Agent",
    "MCP",
    "LangGraph",
    "LLM",
    "NLP",
    "多模态",
    "向量检索",
    "知识库",
)
CHAT_INTENT_PRIORITY_LABELS = {
    "deadline_planning": "跟进近期 DDL",
    "resume_polish": "简历润色",
    "interview_prep": "面试准备",
    "hr_reply": "沟通话术准备",
    "job_targeting": "高匹配岗位筛选",
}


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
class ExtractedAttachment:
    """One attachment or local file converted into analyzable text."""

    display_name: str
    source_ref: str
    source_type: SourceType
    text: str
    source_metadata: dict[str, Any]
    extraction_kind: str


@dataclass(frozen=True)
class ChatAttachmentResult:
    """One chat-specific attachment prepared for retrieval and optional memory writes."""

    display_name: str
    source_ref: str
    extraction_kind: str
    attachment_kind: str
    summary: str
    persisted_to_profile: bool
    text_length: int
    processing_error: str | None = None


@dataclass(frozen=True)
class ChatMemoryUpdateSummary:
    """Conservative profile and career updates applied during one chat turn."""

    applied: bool
    profile_fields: list[str] = field(default_factory=list)
    career_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChatExecutionResult:
    """Rich chat result returned to the API layer for UI inspection."""

    answer: str
    supporting_item_ids: list[str]
    citations: list[RetrievedContext]
    retrieval_mode: str
    query_analysis: QueryAnalysis
    memory_update: ChatMemoryUpdateSummary
    attachments: list[ChatAttachmentResult] = field(default_factory=list)


@dataclass(frozen=True)
class ChatSessionSummaryResult:
    """Compressed metadata for archived chat conversations."""

    title: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    compressed_transcript: str = ""
    summary_source: str = "heuristic"


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


@dataclass(frozen=True)
class JobCardRelationshipDecision:
    """One LLM decision about how two job cards relate within the same company context."""

    relation: str
    confidence: float
    reason: str
    group_title: str | None = None


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
    runtime_settings_repository: LocalRuntimeSettingsRepository = field(
        default_factory=lambda: LocalRuntimeSettingsRepository(
            Path("data/runtime/runtime_settings.json")
        )
    )
    project_self_memory_service: ProjectSelfMemoryService = field(
        default_factory=ProjectSelfMemoryService
    )

    def __post_init__(self) -> None:
        self.runtime_overrides = self.runtime_settings_repository.load()
        self.settings = AppSettings.from_env(self.runtime_overrides)
        self._refresh_runtime_bindings()

    def _refresh_runtime_bindings(self) -> None:
        """Refresh runtime-bound clients after local settings change."""

        self.dependencies.model_router = StaticModelRouter(self.settings)
        if isinstance(
            self.dependencies.llm_gateway,
            (OpenAICompatibleLLMGateway, NoopLLMGateway),
        ):
            if self.settings.llm.enable_live_llm:
                self.dependencies.llm_gateway = OpenAICompatibleLLMGateway(self.settings.llm)
            else:
                self.dependencies.llm_gateway = NoopLLMGateway()

        if isinstance(self.dependencies.search_client, (WebSearchClient, NoopSearchClient)):
            if self.settings.llm.enable_live_llm or self.settings.rag.enable_live_rag:
                self.dependencies.search_client = WebSearchClient()
            else:
                self.dependencies.search_client = NoopSearchClient()

        if isinstance(
            self.dependencies.ocr_client,
            (
                CascadingOCRClient,
                GeneralLLMOCRClient,
                LocalTesseractOCRClient,
                QwenVLOCRClient,
            ),
        ):
            self.dependencies.ocr_client = build_ocr_client_from_settings(self.settings)

        self.workflow = JobWorkflow(self.dependencies)
        self.chat_service = RAGChatService(
            dependencies=self.dependencies,
            settings=self.settings,
        )

    def get_runtime_settings(self) -> dict[str, Any]:
        """Return the current runtime settings snapshot used by the local app."""

        return {
            "llm": {
                "enabled": self.settings.llm.enable_live_llm,
                "api_key": self.settings.llm.dashscope.api_key,
                "base_url": self.settings.llm.dashscope.base_url,
                "model": self.settings.llm.dashscope.model,
                "fallback_models": list(self.settings.llm.dashscope.fallback_models),
                "request_timeout_seconds": self.settings.llm.request_timeout_seconds,
            },
            "ocr": {
                "enabled": self.settings.ocr.enabled,
                "provider_label": self.settings.ocr.provider_label,
                "api_key": self.settings.ocr.api_key,
                "base_url": self.settings.ocr.base_url,
                "model": self.settings.ocr.model,
                "request_timeout_seconds": self.settings.ocr.request_timeout_seconds,
            },
            "source_files": {
                "max_age_days": self.settings.source_files.max_age_days,
                "max_total_size_mb": self.settings.source_files.max_total_size_mb,
                "delete_when_item_deleted": self.settings.source_files.delete_when_item_deleted,
                "filter_patterns": list(self.settings.source_files.filter_patterns),
            },
        }

    def update_runtime_settings(
        self,
        *,
        llm_enabled: bool,
        llm_api_key: str | None,
        llm_base_url: str | None,
        llm_model: str | None,
        llm_fallback_models: list[str],
        llm_request_timeout_seconds: int,
        ocr_enabled: bool,
        ocr_provider_label: str,
        ocr_api_key: str | None,
        ocr_base_url: str | None,
        ocr_model: str | None,
        ocr_request_timeout_seconds: int,
        source_files_max_age_days: int,
        source_files_max_total_size_mb: int,
        source_files_delete_when_item_deleted: bool,
        source_files_filter_patterns: list[str],
    ) -> dict[str, Any]:
        """Persist local runtime settings and refresh bound clients."""

        self.runtime_overrides = RuntimeSettingsOverrides(
            llm=RuntimeProviderOverrides(
                enabled=llm_enabled,
                api_key=llm_api_key,
                base_url=llm_base_url,
                model=llm_model,
                fallback_models=tuple(
                    item.strip() for item in llm_fallback_models if item.strip()
                ),
            ),
            ocr=RuntimeOCROverrides(
                enabled=ocr_enabled,
                provider_label=ocr_provider_label.strip() or "Qwen-VL-OCR",
                api_key=ocr_api_key,
                base_url=ocr_base_url,
                model=ocr_model,
                request_timeout_seconds=ocr_request_timeout_seconds,
            ),
            source_files=RuntimeSourceFileOverrides(
                max_age_days=source_files_max_age_days,
                max_total_size_mb=source_files_max_total_size_mb,
                delete_when_item_deleted=source_files_delete_when_item_deleted,
                filter_patterns=tuple(
                    item.strip()
                    for item in source_files_filter_patterns
                    if item.strip()
                ),
            ),
            llm_request_timeout_seconds=llm_request_timeout_seconds,
        )
        self.runtime_settings_repository.save(self.runtime_overrides)
        self.settings = AppSettings.from_env(self.runtime_overrides)
        self._refresh_runtime_bindings()
        self.cleanup_source_files(trigger="settings_update")
        return self.get_runtime_settings()

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

        source_metadata = dict(source_metadata or {})
        source_ref, source_metadata = self._ensure_source_artifact(
            raw_input=raw_input,
            source_type=source_type,
            source_ref=source_ref,
            source_metadata=source_metadata,
        )
        initial_state = create_initial_state(
            raw_input=raw_input,
            source_type=source_type,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            memory_write_mode=memory_write_mode,
            source_metadata=source_metadata,
        )
        final_state = self.workflow.invoke(initial_state, prefer_langgraph=False)

        # The graph follows `persist -> render` to match the design doc. After the
        # workflow finishes, we refresh the repository with the final rendered
        # state so read APIs can expose the latest card payload.
        if final_state.normalized_item is not None:
            self.dependencies.workflow_repository.save(final_state)
            if not source_metadata.get("skip_relationship_reorg"):
                final_state = self._maybe_reorganize_company_job_cards(final_state)

        return final_state

    def _maybe_reorganize_company_job_cards(self, state: AgentState) -> AgentState:
        """Use LLM relation checks to organize same-company cards into overview/child structure."""

        if not self._should_run_dynamic_job_grouping(state):
            return state

        related_states = self._dedupe_states_by_item_id(self._list_related_company_cards(state))
        if not related_states:
            return state

        grouped_members, relationship_checks, group_title_votes = self._collect_job_relationship_cluster(
            anchor_state=state,
            candidate_states=[state, *related_states[:8]],
        )
        state.source_metadata["job_relationship_checks"] = relationship_checks
        if len(grouped_members) < 2:
            self.dependencies.workflow_repository.save(state)
            return state

        unique_members = self._dedupe_states_by_item_id(grouped_members)
        group_title = self._pick_job_group_title(unique_members, group_title_votes)
        if not group_title:
            return state

        overview_state = self._upsert_dynamic_job_group_overview(
            anchor_state=state,
            child_states=unique_members,
            group_title=group_title,
        )
        self._refresh_stale_job_overviews(
            user_id=state.user_id,
            workspace_id=state.workspace_id,
            keep_parent_id=overview_state.normalized_item.id if overview_state.normalized_item else None,
        )
        self.dependencies.workflow_repository.save(state)
        return state

    def _collect_job_relationship_cluster(
        self,
        *,
        anchor_state: AgentState,
        candidate_states: list[AgentState],
    ) -> tuple[list[AgentState], list[dict[str, Any]], list[str]]:
        """Expand from the new card across same-company candidates to collect one related cluster."""

        states = self._dedupe_states_by_item_id(candidate_states)
        if len(states) < 2 or anchor_state.normalized_item is None:
            return [anchor_state], [], []

        states_by_id = {
            state.normalized_item.id: state
            for state in states
            if state.normalized_item is not None
        }
        anchor_id = anchor_state.normalized_item.id
        if anchor_id not in states_by_id:
            return [anchor_state], [], []

        relationship_checks: list[dict[str, Any]] = []
        group_title_votes: list[str] = []
        connected_ids: set[str] = {anchor_id}
        frontier: list[str] = [anchor_id]
        checked_pairs: set[tuple[str, str]] = set()
        adjacency: dict[str, set[str]] = {item_id: set() for item_id in states_by_id}

        while frontier:
            current_id = frontier.pop(0)
            current_state = states_by_id[current_id]
            for other_id, other_state in states_by_id.items():
                if other_id == current_id:
                    continue
                pair_key = tuple(sorted((current_id, other_id)))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                try:
                    decision = self._assess_job_card_relationship(current_state, other_state)
                except Exception:
                    continue
                relationship_checks.append(
                    {
                        "left_item_id": current_id,
                        "right_item_id": other_id,
                        "relation": decision.relation,
                        "confidence": round(decision.confidence, 4),
                        "reason": decision.reason,
                        "group_title": decision.group_title,
                    }
                )
                if not self._is_group_relationship(decision):
                    continue
                adjacency[current_id].add(other_id)
                adjacency[other_id].add(current_id)
                if decision.group_title:
                    group_title_votes.append(decision.group_title)
                if other_id not in connected_ids:
                    connected_ids.add(other_id)
                    frontier.append(other_id)
                if current_id not in connected_ids:
                    connected_ids.add(current_id)
                    frontier.append(current_id)

        grouped_members = [states_by_id[item_id] for item_id in states_by_id if item_id in connected_ids]
        grouped_members.sort(
            key=lambda candidate: 0
            if candidate.normalized_item and candidate.normalized_item.id == anchor_id
            else 1
        )
        return grouped_members, relationship_checks, group_title_votes

    def _is_group_relationship(self, decision: JobCardRelationshipDecision) -> bool:
        """Return whether one relationship decision should place cards in the same overview cluster."""

        return decision.relation in {"parallel", "subordinate", "parent"}

    def _should_run_dynamic_job_grouping(self, state: AgentState) -> bool:
        """Restrict dynamic job grouping to newly ingested activity cards."""

        if state.normalized_item is None or state.extracted_signal is None:
            return False
        if state.source_metadata.get("job_group_kind") == "overview":
            return False
        if state.source_metadata.get("market_watch"):
            return False
        if state.persistence_summary.get("dedupe_action"):
            return False
        return state.extracted_signal.category in {
            ContentCategory.JOB_POSTING,
            ContentCategory.REFERRAL,
        }

    def _list_related_company_cards(self, state: AgentState) -> list[AgentState]:
        """Fetch stored non-market job cards from the same company or business line."""

        current_signal = state.extracted_signal
        if state.normalized_item is None or current_signal is None:
            return []

        current_company = self._relationship_company_name(state)
        current_identity = str(state.source_metadata.get("identity_tag") or "").strip()
        current_primary_unit = str(state.source_metadata.get("primary_unit") or "").strip()
        current_role = str(current_signal.role or state.source_metadata.get("role_variant") or "").strip()

        related: list[AgentState] = []
        for existing in self.dependencies.workflow_repository.list_all(
            user_id=state.user_id,
            workspace_id=state.workspace_id,
        ):
            if existing.normalized_item is None or existing.extracted_signal is None:
                continue
            if existing.normalized_item.id == state.normalized_item.id:
                continue
            if existing.source_metadata.get("market_watch"):
                continue
            if existing.source_metadata.get("job_group_kind") == "overview":
                continue
            existing_company = self._relationship_company_name(existing)
            existing_identity = str(existing.source_metadata.get("identity_tag") or "").strip()
            existing_primary_unit = str(existing.source_metadata.get("primary_unit") or "").strip()
            if current_company and existing_company and current_company == existing_company:
                related.append(existing)
                continue
            if current_identity and existing_identity and current_identity == existing_identity:
                related.append(existing)
                continue
            if current_primary_unit and existing_primary_unit and current_primary_unit == existing_primary_unit:
                related.append(existing)
                continue
            if self._state_references_target_entity(
                existing=existing,
                company=current_company,
                role=current_role,
            ):
                related.append(existing)
        return related

    def _assess_job_card_relationship(
        self,
        current: AgentState,
        existing: AgentState,
    ) -> JobCardRelationshipDecision:
        """Use one LLM step to judge whether two same-company cards should share one overview."""

        route = self.dependencies.model_router.select("deduplicate", "medium")
        if not self.dependencies.llm_gateway.is_available(route):
            return JobCardRelationshipDecision(relation="none", confidence=0.0, reason="llm_unavailable")

        keyword_hints = self._relationship_keyword_hints(current, existing)
        prompt_references = collect_prompt_references(
            user_id=current.user_id,
            workspace_id=current.workspace_id,
            current_item_id=current.normalized_item.id if current.normalized_item else None,
            query_text=self._relationship_query_text(current, existing),
            source_metadata={
                **current.source_metadata,
                "keyword_hints": keyword_hints,
                "primary_unit": current.extracted_signal.company if current.extracted_signal else None,
                "role_variant": current.extracted_signal.role if current.extracted_signal else None,
            },
            workflow_repository=self.dependencies.workflow_repository,
            search_client=None,
            embedding_gateway=self.dependencies.embedding_gateway,
            vector_store=self.dependencies.vector_store,
            embed_route=self.dependencies.model_router.select("embed", "low"),
            category_hint=current.classified_category.value if current.classified_category else None,
        )
        prompt = self.dependencies.prompt_loader.load("job_card_relationship")
        response = self.dependencies.llm_gateway.complete_json(
            route=route,
            task_name="job_card_relationship",
            system_prompt=prompt,
            user_payload={
                "keyword_hints": keyword_hints,
                "prompt_references": [reference.to_payload() for reference in prompt_references],
                "current": self._job_relationship_snapshot(current),
                "existing": self._job_relationship_snapshot(existing),
                "current_entity_candidates": self._reconstruct_job_card_entities(current),
                "existing_entity_candidates": self._reconstruct_job_card_entities(existing),
                "related_existing_cards": self._collect_related_job_context(
                    current=current,
                    existing=existing,
                ),
            },
        )
        relation = str(response.get("relation") or "none").strip().lower()
        if relation not in {"none", "parallel", "subordinate", "parent"}:
            relation = "none"
        return JobCardRelationshipDecision(
            relation=relation,
            confidence=max(0.0, min(float(response.get("confidence") or 0.0), 1.0)),
            reason=str(response.get("reason") or "job_card_relationship"),
            group_title=str(response.get("group_title") or "").strip() or None,
        )

    def _job_relationship_snapshot(self, state: AgentState) -> dict[str, Any]:
        """Serialize one job card into a compact relationship-judgment payload."""

        signal = state.extracted_signal
        normalized = state.normalized_item
        return {
            "item_id": normalized.id if normalized else None,
            "source_title": normalized.source_title if normalized else None,
            "summary_one_line": signal.summary_one_line if signal else None,
            "company": self._relationship_company_name(state),
            "role": signal.role if signal else None,
            "city": signal.city if signal else None,
            "ddl": signal.ddl.isoformat() if signal and signal.ddl else None,
            "source_ref": state.source_ref,
            "primary_unit": state.source_metadata.get("primary_unit"),
            "identity_tag": state.source_metadata.get("identity_tag"),
            "relationship_tags": list(state.source_metadata.get("relationship_tags", []))[:8],
            "normalized_text": normalized.normalized_text[:500] if normalized else None,
        }

    def _relationship_query_text(self, current: AgentState, existing: AgentState) -> str:
        """Build a retrieval query covering both cards and their core fields."""

        values = [
            current.normalized_item.normalized_text[:240] if current.normalized_item else "",
            existing.normalized_item.normalized_text[:240] if existing.normalized_item else "",
            current.extracted_signal.company if current.extracted_signal else "",
            current.extracted_signal.role if current.extracted_signal else "",
            existing.extracted_signal.role if existing.extracted_signal else "",
            current.source_metadata.get("identity_tag"),
            existing.source_metadata.get("identity_tag"),
        ]
        return " ".join(str(value).strip() for value in values if str(value or "").strip())

    def _relationship_keyword_hints(self, current: AgentState, existing: AgentState) -> list[str]:
        """Combine both cards' company, department, role and tag hints."""

        values = [
            *(current.source_metadata.get("keyword_hints", []) or []),
            *(existing.source_metadata.get("keyword_hints", []) or []),
            current.extracted_signal.company if current.extracted_signal else None,
            current.extracted_signal.role if current.extracted_signal else None,
            existing.extracted_signal.company if existing.extracted_signal else None,
            existing.extracted_signal.role if existing.extracted_signal else None,
            current.source_metadata.get("primary_unit"),
            existing.source_metadata.get("primary_unit"),
            current.source_metadata.get("identity_tag"),
            existing.source_metadata.get("identity_tag"),
        ]
        deduped: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in deduped:
                deduped.append(text)
        return deduped[:10]

    def _relationship_company_name(self, state: AgentState) -> str:
        """Choose the company-like field that is safest for relationship grouping."""

        candidates = [
            str(state.extracted_signal.company if state.extracted_signal else "").strip(),
            str(state.source_metadata.get("primary_unit") or "").strip(),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if candidate.startswith("-"):
                continue
            if any(
                keyword in candidate
                for keyword in ("工程师", "分析师", "经理", "研究员", "运营", "设计师")
            ):
                continue
            return candidate
        return next((candidate for candidate in candidates if candidate), "")

    def _state_references_target_entity(
        self,
        *,
        existing: AgentState,
        company: str,
        role: str,
    ) -> bool:
        """Detect whether one older ambiguous card may still mention the target company/role."""

        if not company and not role:
            return False
        for candidate in self._reconstruct_job_card_entities(existing):
            candidate_company = str(candidate.get("company") or "").strip()
            candidate_role = str(candidate.get("role") or "").strip()
            if company and candidate_company and candidate_company == company:
                return True
            if role and candidate_role and self._role_similarity(candidate_role, role) >= 0.45:
                return True
        return False

    def _role_similarity(self, left: str, right: str) -> float:
        """Measure shallow role overlap for multi-entity relationship filtering."""

        left_tokens = {
            token
            for token in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{1,4}", left.lower())
            if token
        }
        right_tokens = {
            token
            for token in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{1,4}", right.lower())
            if token
        }
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))

    def _collect_related_job_context(
        self,
        *,
        current: AgentState,
        existing: AgentState,
    ) -> list[dict[str, Any]]:
        """Provide nearby old-card summaries so LLM can reconstruct wider overview logic."""

        current_company = str(
            current.extracted_signal.company if current.extracted_signal else ""
        ).strip()
        current_role = str(
            current.extracted_signal.role or current.source_metadata.get("role_variant") or ""
            if current.extracted_signal is not None
            else current.source_metadata.get("role_variant") or ""
        ).strip()

        related_context: list[dict[str, Any]] = []
        for state in self.dependencies.workflow_repository.list_all(
            user_id=current.user_id,
            workspace_id=current.workspace_id,
        ):
            if state.normalized_item is None or state.extracted_signal is None:
                continue
            if existing.normalized_item and state.normalized_item.id == existing.normalized_item.id:
                continue
            if current.normalized_item and state.normalized_item.id == current.normalized_item.id:
                continue
            if state.source_metadata.get("market_watch"):
                continue
            if state.source_metadata.get("job_group_kind") == "overview":
                continue
            if not self._state_references_target_entity(
                existing=state,
                company=current_company,
                role=current_role,
            ):
                continue
            related_context.append(
                {
                    "item_id": state.normalized_item.id,
                    "source_title": state.normalized_item.source_title,
                    "summary_one_line": state.extracted_signal.summary_one_line,
                    "company": state.extracted_signal.company,
                    "role": state.extracted_signal.role,
                    "identity_tag": state.source_metadata.get("identity_tag"),
                    "entity_candidates": self._reconstruct_job_card_entities(state),
                }
            )
        return related_context[:4]

    def _reconstruct_job_card_entities(self, state: AgentState) -> list[dict[str, Any]]:
        """Rebuild multi-entity candidates from one old card's title, metadata and raw section text."""

        normalized = state.normalized_item
        signal = state.extracted_signal
        if normalized is None:
            return []

        source_metadata = state.source_metadata or {}
        raw_text = str(
            source_metadata.get("original_section_text")
            or source_metadata.get("shared_context")
            or normalized.raw_content
            or normalized.normalized_text
            or ""
        )
        source_title = str(normalized.source_title or source_metadata.get("source_title") or "").strip()
        keyword_hints = [
            str(value).strip()
            for value in source_metadata.get("keyword_hints", [])
            if str(value).strip()
        ]

        role_candidates: list[str] = []
        for value in [
            signal.role if signal is not None else None,
            source_metadata.get("role_variant"),
            *self._extract_role_variants(raw_text),
        ]:
            text = str(value or "").strip("：: ;；")
            if not text or text in role_candidates:
                continue
            if any(keyword in text for keyword in ("工程师", "分析师", "经理", "研究员", "运营", "设计师")):
                role_candidates.append(text)

        company_candidates: list[str] = []
        semantic_tags = [str(value).strip() for value in source_metadata.get("semantic_tags", []) if str(value).strip()]
        for value in [
            signal.company if signal is not None else None,
            source_metadata.get("primary_unit"),
            self._extract_primary_unit(title=source_title, keyword_hints=keyword_hints),
            *semantic_tags,
        ]:
            text = str(value or "").strip("：: -")
            if not text or text in company_candidates:
                continue
            if text in SEASON_TAGS or text.endswith("系") or "-" in text:
                continue
            if any(keyword in text for keyword in ("工程师", "分析师", "经理", "研究员", "运营", "设计师")):
                continue
            company_candidates.append(text)

        if not company_candidates and signal is not None and signal.company:
            company_candidates.append(signal.company)
        if not role_candidates and signal is not None and signal.role:
            role_candidates.append(signal.role)

        candidates: list[dict[str, Any]] = []
        if company_candidates and role_candidates:
            for company_value in company_candidates[:3]:
                for role_value in role_candidates[:4]:
                    candidates.append(
                        {
                            "company": company_value,
                            "role": role_value,
                            "identity_tag": source_metadata.get("identity_tag"),
                        }
                    )
        else:
            candidates.append(
                {
                    "company": company_candidates[0] if company_candidates else (signal.company if signal else None),
                    "role": role_candidates[0] if role_candidates else (signal.role if signal else None),
                    "identity_tag": source_metadata.get("identity_tag"),
                }
            )

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for candidate in candidates:
            key = (
                str(candidate.get("company") or "").strip(),
                str(candidate.get("role") or "").strip(),
                str(candidate.get("identity_tag") or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped[:6]

    def _dedupe_states_by_item_id(self, states: list[AgentState]) -> list[AgentState]:
        """Keep one state per item id while preserving original order."""

        deduped: list[AgentState] = []
        seen: set[str] = set()
        for state in states:
            if state.normalized_item is None:
                continue
            item_id = state.normalized_item.id
            if item_id in seen:
                continue
            seen.add(item_id)
            deduped.append(state)
        return deduped

    def _pick_job_group_title(self, child_states: list[AgentState], title_votes: list[str]) -> str | None:
        """Choose one stable overview title for a dynamically grouped company cluster."""

        cleaned_votes = [title.strip() for title in title_votes if title and title.strip()]
        if cleaned_votes:
            counts: dict[str, int] = {}
            for title in cleaned_votes:
                counts[title] = counts.get(title, 0) + 1
            return max(counts.items(), key=lambda item: item[1])[0]

        anchor = child_states[0] if child_states else None
        if anchor is None or anchor.extracted_signal is None:
            return None
        company = str(anchor.extracted_signal.company or anchor.source_metadata.get("primary_unit") or "").strip()
        identity_tag = str(anchor.source_metadata.get("identity_tag") or "").strip()
        primary_unit = str(anchor.source_metadata.get("primary_unit") or "").strip()
        return identity_tag or primary_unit or (f"{company}-岗位合集" if company else None)

    def _upsert_dynamic_job_group_overview(
        self,
        *,
        anchor_state: AgentState,
        child_states: list[AgentState],
        group_title: str,
    ) -> AgentState:
        """Create or update one overview card for a same-company relation cluster."""

        unique_children = self._dedupe_states_by_item_id(child_states)
        section = SubmissionSection(
            section_title=group_title,
            section_text=self._compose_dynamic_job_group_text(group_title, unique_children),
            urls=[
                child.source_ref
                for child in unique_children
                if child.source_ref and URL_PATTERN.match(str(child.source_ref))
            ][:8],
            semantic_tags=self._dynamic_job_group_tags(unique_children, group_title),
            role_variants=[],
            relationship_family=str(anchor_state.source_metadata.get("relationship_family") or "").strip() or None,
            relationship_stage=str(anchor_state.source_metadata.get("relationship_stage") or "").strip() or None,
            primary_unit=str(
                anchor_state.extracted_signal.company
                or anchor_state.source_metadata.get("primary_unit")
                or ""
            ).strip()
            or None,
            identity_tag=group_title,
        )
        shared_exam_dates = [
            child.extracted_signal.ddl
            for child in unique_children
            if child.extracted_signal is not None and child.extracted_signal.ddl is not None
        ]
        next_shared_exam_date = min(shared_exam_dates) if shared_exam_dates else None
        base_source_metadata = {
            **anchor_state.source_metadata,
            "skip_relationship_reorg": True,
            "source_title": group_title,
            "source_kind": anchor_state.source_type.value,
        }
        return self._build_job_group_overview_state(
            section=section,
            child_states=unique_children,
            shared_context="同公司/同业务线卡片经过关系判断后自动组织为岗位合集。",
            shared_exam_dates=shared_exam_dates,
            next_shared_exam_date=next_shared_exam_date,
            keyword_hints=self._dynamic_job_group_tags(unique_children, group_title),
            search_references=[],
            user_id=anchor_state.user_id,
            workspace_id=anchor_state.workspace_id,
            memory_write_mode=anchor_state.memory_write_mode,
            base_source_metadata=base_source_metadata,
            source_type_override=SourceType.LINK if section.urls else SourceType.TEXT,
            source_ref_override=section.urls[0] if section.urls else None,
        )

    def _compose_dynamic_job_group_text(self, group_title: str, child_states: list[AgentState]) -> str:
        """Build synthetic overview raw text for dynamically organized company clusters."""

        lines = [
            f"岗位合集主题：{group_title}",
            f"岗位数量：{len(child_states)}",
            "说明：这些卡片在入库后被识别为同公司下的并列或从属岗位信息。",
            "岗位子项：",
        ]
        for child in child_states[:10]:
            summary = (
                child.render_card.summary_one_line
                if child.render_card is not None
                else child.extracted_signal.summary_one_line if child.extracted_signal is not None else None
            )
            if summary:
                lines.append(f"- {summary}")
        return "\n".join(lines)

    def _dynamic_job_group_tags(self, child_states: list[AgentState], group_title: str) -> list[str]:
        """Build overview tags from grouped company, department and role hints."""

        values = ["岗位合集", group_title]
        for child in child_states:
            values.extend(child.source_metadata.get("relationship_tags", [])[:4])
            if child.extracted_signal is not None:
                values.extend(
                    [
                        child.extracted_signal.company,
                        child.extracted_signal.role,
                        child.extracted_signal.city,
                    ]
                )
        deduped: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in deduped:
                deduped.append(text)
        return deduped[:10]

    def _refresh_stale_job_overviews(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
        keep_parent_id: str | None,
    ) -> None:
        """Refresh or delete overview cards whose child links changed after regrouping."""

        all_states = self.dependencies.workflow_repository.list_all(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        parent_to_children: dict[str, list[AgentState]] = {}
        for state in all_states:
            if state.source_metadata.get("job_group_kind") != "role":
                continue
            parent_id = str(state.source_metadata.get("job_parent_item_id") or "").strip()
            if not parent_id:
                continue
            current = parent_to_children.get(parent_id, [])
            current.append(state)
            parent_to_children[parent_id] = current

        for state in all_states:
            if state.source_metadata.get("job_group_kind") != "overview" or state.normalized_item is None:
                continue
            parent_id = state.normalized_item.id
            if keep_parent_id and parent_id == keep_parent_id:
                continue
            child_states = parent_to_children.get(parent_id, [])
            if len(child_states) < 2:
                self.dependencies.workflow_repository.delete(parent_id)
                for child in child_states:
                    child.source_metadata["job_group_kind"] = None
                    child.source_metadata["job_parent_item_id"] = None
                    child.source_metadata["job_child_item_ids"] = []
                    child.source_metadata["job_child_previews"] = []
                    if child.render_card is not None:
                        child.render_card.job_group_kind = None
                        child.render_card.job_parent_item_id = None
                        child.render_card.job_child_item_ids = []
                        child.render_card.job_child_previews = []
                    self.dependencies.workflow_repository.save(child)

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
        source_type_override: SourceType | None = None,
        source_ref_override: str | None = None,
        base_source_metadata: dict[str, Any] | None = None,
    ) -> tuple[SubmissionAnalysis, list[AgentState]]:
        """Analyze mixed pasted input and fan out into one or more workflow runs."""

        base_source_metadata = dict(base_source_metadata or {})
        if not base_source_metadata.get("archived_source_path") and content.strip():
            archived_text_path = self._archive_text_input(
                raw_text=content,
                preferred_name=self._derive_text_source_name(source_ref_override, base_source_metadata),
            )
            base_source_metadata["archived_source_path"] = str(archived_text_path)
            base_source_metadata["archived_source_name"] = archived_text_path.name
            base_source_metadata.setdefault("source_kind", "text")
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
                should_skip_relationship_reorg = len(variants) >= 2
                section_states: list[AgentState] = []
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

                    source_ref = source_ref_override or (
                        variant["urls"][0] if variant["urls"] else None
                    )
                    source_type = source_type_override or (
                        SourceType.LINK if source_ref else SourceType.TEXT
                    )
                    child_state = self.ingest(
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
                            **base_source_metadata,
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
                            "skip_relationship_reorg": should_skip_relationship_reorg,
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
                    section_states.append(child_state)
                    states.append(child_state)

                if len(section_states) >= 2:
                    overview_state = self._build_job_group_overview_state(
                        section=section,
                        child_states=section_states,
                        shared_context=shared_context,
                        shared_exam_dates=shared_exam_dates,
                        next_shared_exam_date=next_shared_exam_date,
                        keyword_hints=keyword_hints,
                        search_references=search_references,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        memory_write_mode=memory_write_mode,
                        base_source_metadata=base_source_metadata,
                        source_type_override=source_type_override,
                        source_ref_override=source_ref_override,
                    )
                    overview_state = self._expand_job_group_overview_with_existing_cards(
                        overview_state=overview_state,
                        child_states=section_states,
                    )
                    states.append(overview_state)

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
            fallback_title = self._infer_submission_title_from_content(
                analysis.context_text or content,
                keyword_hints=keyword_hints,
            )
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
            fallback_source_type = source_type_override or (
                SourceType.LINK if analysis.input_kind == "link" else SourceType.TEXT
            )
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
                    source_ref=source_ref_override or (
                        analysis.urls[0] if analysis.urls else None
                    ),
                    memory_write_mode=memory_write_mode,
                    source_metadata={
                        **base_source_metadata,
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

    def ingest_unified(
        self,
        *,
        content: str,
        uploaded_files: list[tuple[str, bytes]],
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode = MemoryWriteMode.CONTEXT_ONLY,
        visit_links: bool | None = None,
    ) -> tuple[SubmissionAnalysis, list[AgentState], list[dict[str, Any]], list[str]]:
        """Ingest inline text, uploaded files, and local file paths in one request."""

        inline_content, local_paths = self._split_inline_content_and_paths(content)
        analyses: list[SubmissionAnalysis] = []
        states: list[AgentState] = []
        attachment_summaries: list[dict[str, Any]] = []
        resolved_paths = [str(path) for path in local_paths]

        if inline_content:
            analysis, inline_states = self.ingest_auto(
                content=inline_content,
                user_id=user_id,
                workspace_id=workspace_id,
                memory_write_mode=memory_write_mode,
                visit_links=visit_links,
            )
            analyses.append(analysis)
            states.extend(inline_states)

        attachments: list[ExtractedAttachment] = []
        for local_path in local_paths:
            attachments.append(self._extract_attachment_from_local_path(local_path))
        for file_name, file_bytes in uploaded_files:
            attachments.append(
                self._extract_attachment_from_upload(
                    file_name=file_name,
                    file_bytes=file_bytes,
                )
            )

        for attachment in attachments:
            attachment_summaries.append(
                {
                    "display_name": attachment.display_name,
                    "source_ref": attachment.source_ref,
                    "source_type": attachment.source_type.value,
                    "extraction_kind": attachment.extraction_kind,
                    "text_length": len(attachment.text),
                }
            )
            attachment_analysis, attachment_states = self.ingest_auto(
                content=attachment.text,
                user_id=user_id,
                workspace_id=workspace_id,
                memory_write_mode=memory_write_mode,
                visit_links=visit_links,
                source_type_override=attachment.source_type,
                source_ref_override=attachment.source_ref,
                base_source_metadata=attachment.source_metadata,
            )
            analyses.append(attachment_analysis)
            states.extend(attachment_states)

        if not analyses:
            raise RuntimeError("请输入文本、上传文件，或提供本地图片/文件路径。")

        merged_reasons: list[str] = []
        merged_urls: list[str] = []
        merged_keywords: list[str] = []
        for analysis in analyses:
            for reason in analysis.reasons:
                if reason not in merged_reasons:
                    merged_reasons.append(reason)
            for url in analysis.urls:
                if url not in merged_urls:
                    merged_urls.append(url)
            for keyword in analysis.keyword_hints:
                if keyword not in merged_keywords:
                    merged_keywords.append(keyword)

        aggregate_kind = analyses[0].input_kind
        if attachments and inline_content:
            aggregate_kind = "mixed_text_and_files"
        elif attachments and not inline_content:
            aggregate_kind = "attachments_only"

        merged_analysis = SubmissionAnalysis(
            input_kind=aggregate_kind,
            context_text=inline_content,
            urls=merged_urls,
            should_visit_links=any(analysis.should_visit_links for analysis in analyses),
            reasons=[
                *merged_reasons,
                (
                    f"processed {len(attachments)} attachments"
                    if attachments
                    else "no attachments"
                ),
                (
                    f"resolved {len(local_paths)} local paths"
                    if local_paths
                    else "no local paths"
                ),
            ],
            keyword_hints=merged_keywords,
        )
        return merged_analysis, states, attachment_summaries, resolved_paths

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

        attachment = self._extract_attachment_from_upload(
            file_name=file_name,
            file_bytes=file_bytes,
        )

        _, states = self.ingest_auto(
            content=attachment.text,
            user_id=user_id,
            workspace_id=workspace_id,
            memory_write_mode=memory_write_mode,
            source_type_override=attachment.source_type,
            source_ref_override=attachment.source_ref,
            base_source_metadata=attachment.source_metadata,
        )
        return self._select_primary_ingest_state(states)

    def _extract_attachment_from_upload(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
    ) -> ExtractedAttachment:
        """Store one uploaded file and convert it into analyzable text."""

        stored_path = self._store_upload_bytes(
            file_name=file_name,
            file_bytes=file_bytes,
        )
        return self._extract_attachment_from_path(
            file_path=stored_path,
            display_name=file_name,
            source_ref=file_name,
            source_origin="uploaded_file",
        )

    def _extract_attachment_from_local_path(self, file_path: Path) -> ExtractedAttachment:
        """Convert one user-provided local file path into analyzable text."""

        archived_path = self._archive_existing_file(
            file_path=file_path,
            preferred_name=file_path.name,
            category="local_path",
        )
        return self._extract_attachment_from_path(
            file_path=archived_path,
            display_name=file_path.name,
            source_ref=str(archived_path),
            source_origin="local_path",
        )

    def _extract_attachment_from_path(
        self,
        *,
        file_path: Path,
        display_name: str,
        source_ref: str,
        source_origin: str,
    ) -> ExtractedAttachment:
        """Extract text from one stored or local file."""

        suffix = file_path.suffix.lower()
        if suffix in IMAGE_FILE_SUFFIXES:
            ocr_result = self.dependencies.ocr_client.extract_text(file_path)
            return ExtractedAttachment(
                display_name=display_name,
                source_ref=source_ref,
                source_type=SourceType.IMAGE,
                text=ocr_result.text,
                extraction_kind="ocr",
                source_metadata={
                    "source_kind": "image",
                    "source_origin": source_origin,
                    "file_name": display_name,
                    "stored_path": str(file_path),
                    "archived_source_path": str(file_path.resolve()),
                    "archived_source_name": file_path.name,
                    **ocr_result.source_metadata,
                },
            )

        if suffix in DOCUMENT_FILE_SUFFIXES:
            document_result = self._extract_document_text_with_fallback(
                file_path=file_path,
                display_name=display_name,
            )
            return ExtractedAttachment(
                display_name=display_name,
                source_ref=source_ref,
                source_type=SourceType.TEXT,
                text=document_result.text,
                extraction_kind=str(
                    document_result.source_metadata.get("document_extractor")
                    or "document_text"
                ),
                source_metadata={
                    "source_kind": "document",
                    "source_origin": source_origin,
                    "file_name": display_name,
                    "stored_path": str(file_path),
                    "archived_source_path": str(file_path.resolve()),
                    "archived_source_name": file_path.name,
                    "original_file_suffix": suffix,
                    **document_result.source_metadata,
                },
            )

        raise RuntimeError(
            f"暂不支持上传 {display_name} 这类文件。当前支持图片、PDF 和常见文本文件。"
        )

    def _extract_document_text_with_fallback(
        self,
        *,
        file_path: Path,
        display_name: str,
    ) -> DocumentTextExtractionResult:
        """Extract document text and fallback to OCR for PDFs that lack embedded text."""

        try:
            return self.dependencies.document_text_extractor.extract_text(file_path)
        except RuntimeError as exc:
            if file_path.suffix.lower() != ".pdf":
                raise
            return self._extract_pdf_text_via_ocr_fallback(
                file_path=file_path,
                display_name=display_name,
                original_error=str(exc),
            )

    def _extract_pdf_text_via_ocr_fallback(
        self,
        *,
        file_path: Path,
        display_name: str,
        original_error: str,
    ) -> DocumentTextExtractionResult:
        """Fallback to multi-page preview OCR when one PDF has no embedded text layer."""

        try:
            preview_images = self._render_pdf_preview_images(file_path)
        except RuntimeError as render_error:
            raise RuntimeError(
                f"PDF {display_name} 读取失败。先尝试文本提取未成功：{original_error}；"
                f"再尝试渲染预览图做 OCR 也失败：{render_error}"
            ) from render_error

        page_texts: list[str] = []
        page_routes: list[str] = []
        for index, preview_image in enumerate(preview_images, start=1):
            try:
                ocr_result = self.dependencies.ocr_client.extract_text(preview_image)
            except RuntimeError as ocr_error:
                raise RuntimeError(
                    f"PDF {display_name} 第 {index} 页暂时无法转成可分析文本。"
                    f"文本提取失败：{original_error}；OCR fallback 失败：{ocr_error}"
                ) from ocr_error
            page_routes.append(str(ocr_result.source_metadata.get("ocr_route") or "ocr"))
            page_texts.append(f"[第 {index} 页]\n{ocr_result.text}")

        combined_text = "\n\n".join(text for text in page_texts if text.strip())
        if not combined_text.strip():
            raise RuntimeError(
                f"PDF {display_name} 经过多页 OCR 后仍未得到可分析文本。"
            )

        return DocumentTextExtractionResult(
            text=combined_text,
            source_metadata={
                "document_extractor": "pdf_preview_ocr_multi_page",
                "document_text_length": len(combined_text),
                "pdf_text_fallback_reason": original_error,
                "pdf_preview_images": [str(path) for path in preview_images],
                "pdf_preview_page_count": len(preview_images),
                "pdf_preview_ocr_routes": page_routes,
            },
        )

    def _render_pdf_preview_images(self, file_path: Path) -> list[Path]:
        """Render every PDF page into one PNG image for downstream OCR."""

        try:
            return self._render_pdf_preview_images_with_appkit(file_path)
        except RuntimeError as appkit_error:
            try:
                return self._render_pdf_preview_images_with_swift(file_path)
            except RuntimeError as swift_error:
                raise RuntimeError(
                    "当前环境无法完成多页 PDF 渲染。"
                    f"AppKit 路径失败：{appkit_error}；"
                    f"Swift PDFKit 路径失败：{swift_error}"
                ) from swift_error

    def _render_pdf_preview_images_with_appkit(self, file_path: Path) -> list[Path]:
        """Render one PDF through the in-process AppKit bridge when available."""

        try:
            import AppKit
        except ImportError as exc:
            raise RuntimeError("当前环境缺少 Python AppKit 桥接。") from exc

        data = AppKit.NSData.dataWithContentsOfFile_(str(file_path))
        if data is None:
            raise RuntimeError("无法读取 PDF 数据。")

        pdf_rep = AppKit.NSPDFImageRep.imageRepWithData_(data)
        if pdf_rep is None:
            raise RuntimeError("无法创建 PDF 预览表示。")

        page_count = int(pdf_rep.pageCount() or 0)
        if page_count <= 0:
            raise RuntimeError("PDF 页数不可用。")

        preview_dir = SOURCE_ARCHIVE_ROOT / "pdf_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        rendered_paths: list[Path] = []

        for page_index in range(page_count):
            pdf_rep.setCurrentPage_(page_index)
            page_bounds = pdf_rep.bounds()
            page_size = page_bounds.size
            image = AppKit.NSImage.alloc().initWithSize_(page_size)
            image.lockFocus()
            pdf_rep.drawInRect_(
                AppKit.NSMakeRect(0, 0, page_size.width, page_size.height)
            )
            image.unlockFocus()

            tiff_data = image.TIFFRepresentation()
            bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(tiff_data)
            png_data = bitmap.representationUsingType_properties_(
                AppKit.NSBitmapImageFileTypePNG,
                None,
            )
            output_path = preview_dir / (
                f"{uuid4().hex[:10]}_{file_path.stem}_page_{page_index + 1}.png"
            )
            success = png_data.writeToFile_atomically_(str(output_path), True)
            if not success:
                raise RuntimeError(f"第 {page_index + 1} 页预览图写入失败。")
            rendered_paths.append(output_path)

        return rendered_paths

    def _render_pdf_preview_images_with_swift(self, file_path: Path) -> list[Path]:
        """Fallback to a tiny Swift + PDFKit renderer when Python AppKit is unavailable."""

        swift_binary = shutil.which("swift") or "/usr/bin/swift"
        if not Path(swift_binary).exists():
            raise RuntimeError("系统缺少 Swift 运行时。")

        preview_dir = SOURCE_ARCHIVE_ROOT / "pdf_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        run_dir = preview_dir / uuid4().hex[:12]
        run_dir.mkdir(parents=True, exist_ok=True)

        swift_source = """
import Foundation
import AppKit
import PDFKit

let arguments = CommandLine.arguments
guard arguments.count >= 3 else {
    fputs("missing arguments\\n", stderr)
    exit(2)
}

let pdfURL = URL(fileURLWithPath: arguments[1])
let outputDirectory = URL(fileURLWithPath: arguments[2], isDirectory: true)

guard let document = PDFDocument(url: pdfURL) else {
    fputs("unable to open pdf\\n", stderr)
    exit(3)
}

let pageCount = document.pageCount
if pageCount <= 0 {
    fputs("pdf has no pages\\n", stderr)
    exit(4)
}

var renderedPaths: [String] = []

for pageIndex in 0..<pageCount {
    guard let page = document.page(at: pageIndex) else { continue }
    let pageBounds = page.bounds(for: .mediaBox)
    if pageBounds.width <= 0 || pageBounds.height <= 0 { continue }

    let pageSize = pageBounds.size
    let image = NSImage(size: pageSize)
    image.lockFocus()
    NSColor.white.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: pageSize)).fill()
    guard let graphicsContext = NSGraphicsContext.current else {
        image.unlockFocus()
        continue
    }
    page.draw(with: .mediaBox, to: graphicsContext.cgContext)
    image.unlockFocus()

    guard
        let tiffData = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiffData),
        let pngData = bitmap.representation(using: .png, properties: [:])
    else {
        continue
    }

    let outputURL = outputDirectory.appendingPathComponent(
        "\\(pageIndex + 1)_\\(pdfURL.deletingPathExtension().lastPathComponent).png"
    )
    do {
        try pngData.write(to: outputURL)
        renderedPaths.append(outputURL.path)
    } catch {
        fputs("write failed: \\(error)\\n", stderr)
        exit(5)
    }
}

if renderedPaths.isEmpty {
    fputs("no pages rendered\\n", stderr)
    exit(6)
}

for path in renderedPaths {
    print(path)
}
"""

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".swift",
            delete=False,
        ) as script_file:
            script_file.write(swift_source)
            script_path = Path(script_file.name)

        try:
            completed = subprocess.run(
                [swift_binary, str(script_path), str(file_path), str(run_dir)],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Swift PDF 渲染超时。") from exc
        finally:
            script_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(error_text or "Swift PDF 渲染失败。")

        rendered_paths = [
            Path(line.strip())
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        rendered_paths = [path for path in rendered_paths if path.exists() and path.is_file()]
        if not rendered_paths:
            raise RuntimeError("Swift PDF 渲染没有产出任何预览图。")
        return rendered_paths

    def _store_upload_bytes(self, *, file_name: str, file_bytes: bytes) -> Path:
        """Persist one uploaded file into the local runtime upload directory."""

        upload_dir = SOURCE_ARCHIVE_ROOT / "uploaded"
        upload_dir.mkdir(parents=True, exist_ok=True)
        original_path = Path(file_name)
        suffix = original_path.suffix.lower()
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", original_path.stem).strip("._") or "upload"
        safe_name = f"{stem}{suffix}" if suffix else stem
        stored_path = upload_dir / f"{uuid4().hex[:10]}_{safe_name}"
        stored_path.write_bytes(file_bytes)
        return stored_path

    def _ensure_source_artifact(
        self,
        *,
        raw_input: str,
        source_type: SourceType,
        source_ref: str | None,
        source_metadata: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        """Ensure manual text and local-file inputs have archived source artifacts."""

        if source_metadata.get("archived_source_path"):
            archived_path = str(source_metadata.get("archived_source_path") or "").strip()
            if archived_path:
                return source_ref or archived_path, source_metadata

        if source_type in {SourceType.TEXT, SourceType.IMAGE} and source_metadata.get("source_origin") in {
            "uploaded_file",
            "local_path",
        }:
            archived_path = str(source_metadata.get("stored_path") or "").strip()
            if archived_path:
                source_metadata["archived_source_path"] = archived_path
                source_metadata["archived_source_name"] = Path(archived_path).name
                return archived_path, source_metadata

        if source_type == SourceType.TEXT:
            archived_path = self._archive_text_input(
                raw_text=raw_input,
                preferred_name=self._derive_text_source_name(source_ref, source_metadata),
            )
            if source_ref:
                source_metadata.setdefault("original_source_ref", source_ref)
            source_metadata["archived_source_path"] = str(archived_path)
            source_metadata["archived_source_name"] = archived_path.name
            source_metadata.setdefault("source_kind", "text")
            return str(archived_path), source_metadata

        return source_ref, source_metadata

    def _derive_text_source_name(
        self,
        source_ref: str | None,
        source_metadata: dict[str, Any],
    ) -> str:
        """Build one readable archived file name for text-origin inputs."""

        title = str(
            source_metadata.get("source_title")
            or source_metadata.get("file_name")
            or source_ref
            or "text_input"
        ).strip()
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._") or "text_input"
        if not safe_title.lower().endswith(".txt"):
            safe_title = f"{safe_title}.txt"
        return safe_title

    def _archive_text_input(self, *, raw_text: str, preferred_name: str) -> Path:
        """Persist one raw text input into the fixed local source archive."""

        text_dir = SOURCE_ARCHIVE_ROOT / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", preferred_name).strip("._") or "text_input.txt"
        if not safe_name.lower().endswith(".txt"):
            safe_name = f"{safe_name}.txt"
        archived_path = text_dir / f"{uuid4().hex[:10]}_{safe_name}"
        archived_path.write_text(raw_text, encoding="utf-8")
        return archived_path

    def _archive_existing_file(
        self,
        *,
        file_path: Path,
        preferred_name: str,
        category: str,
    ) -> Path:
        """Copy one existing local file into the fixed source archive directory."""

        archive_dir = SOURCE_ARCHIVE_ROOT / category
        archive_dir.mkdir(parents=True, exist_ok=True)
        preferred_path = Path(preferred_name)
        suffix = preferred_path.suffix or file_path.suffix
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", preferred_path.stem).strip("._") or "attachment"
        safe_name = f"{stem}{suffix}" if suffix else stem
        archived_path = archive_dir / f"{uuid4().hex[:10]}_{safe_name}"
        shutil.copy2(file_path, archived_path)
        return archived_path

    def _split_inline_content_and_paths(self, content: str) -> tuple[str, list[Path]]:
        """Split pasted content into inline text and standalone local file paths."""

        inline_lines: list[str] = []
        resolved_paths: list[Path] = []
        seen_paths: set[str] = set()

        for raw_line in content.splitlines():
            candidate = self._resolve_local_path_candidate(raw_line)
            if candidate is not None:
                normalized = str(candidate)
                if normalized not in seen_paths:
                    seen_paths.add(normalized)
                    resolved_paths.append(candidate)
                continue
            inline_lines.append(raw_line)

        inline_content = "\n".join(inline_lines).strip()
        return inline_content, resolved_paths

    def _resolve_local_path_candidate(self, raw_line: str) -> Path | None:
        """Resolve one standalone local file path from the pasted input."""

        candidate = raw_line.strip().strip('"').strip("'")
        if not candidate:
            return None
        if not (
            candidate.startswith("/")
            or candidate.startswith("~/")
            or candidate.startswith("./")
            or candidate.startswith("../")
        ):
            return None

        file_path = Path(candidate).expanduser()
        if not file_path.is_file():
            return None
        return file_path.resolve()

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
        self._repair_market_cards(states)
        return states

    def get_item(self, item_id: str) -> AgentState | None:
        """Return one stored workflow state by id."""

        state = self.dependencies.workflow_repository.get(item_id)
        if state is not None and state.render_card is None and state.normalized_item is not None:
            state.render_card = self._build_fallback_card(state)
        if state is not None:
            sibling_states = self.dependencies.workflow_repository.list_all(
                user_id=state.user_id,
                workspace_id=state.workspace_id,
            )
            for sibling in sibling_states:
                if sibling.render_card is None and sibling.normalized_item is not None:
                    sibling.render_card = self._build_fallback_card(sibling)
            self._repair_market_cards(sibling_states)
        return state

    def _repair_market_cards(self, states: list[AgentState]) -> None:
        """Backfill visible market titles and preview lists for older stored cards."""

        article_titles_by_parent: dict[str, list[str]] = {}
        for state in states:
            if state.normalized_item is None or state.render_card is None:
                continue
            group_kind = str(state.source_metadata.get("market_group_kind") or "")
            if group_kind != "article":
                continue

            normalized_title = str(state.normalized_item.source_title or "").strip()
            desired_title = str(
                state.source_metadata.get("market_article_title") or normalized_title
            ).strip()
            changed = False
            if desired_title and state.render_card.summary_one_line != desired_title:
                state.render_card.summary_one_line = desired_title
                changed = True
            if desired_title and state.extracted_signal is not None:
                if state.extracted_signal.summary_one_line != desired_title:
                    state.extracted_signal.summary_one_line = desired_title
                    changed = True
            parent_id = str(state.source_metadata.get("market_parent_item_id") or "").strip()
            if parent_id and desired_title:
                article_titles_by_parent.setdefault(parent_id, []).append(desired_title)
            if changed:
                self.dependencies.workflow_repository.save(state)

        for state in states:
            if state.normalized_item is None or state.render_card is None:
                continue
            group_kind = str(state.source_metadata.get("market_group_kind") or "")
            if group_kind != "overview":
                continue

            ordered_titles: list[str] = []
            seen_ordered_titles: set[str] = set()
            child_ids = list(dict.fromkeys(state.render_card.market_child_item_ids or []))
            if child_ids != list(state.render_card.market_child_item_ids or []):
                state.render_card.market_child_item_ids = child_ids
                state.source_metadata["market_child_item_ids"] = child_ids
                self.dependencies.workflow_repository.save(state)
            for child_id in child_ids:
                child_state = next(
                    (
                        candidate
                        for candidate in states
                        if candidate.normalized_item is not None
                        and candidate.normalized_item.id == child_id
                        and candidate.render_card is not None
                    ),
                    None,
                )
                if child_state is None or not child_state.render_card.summary_one_line:
                    continue
                title = child_state.render_card.summary_one_line
                title_key = re.sub(r"\s+", " ", title).strip().lower()
                if title_key in seen_ordered_titles:
                    continue
                seen_ordered_titles.add(title_key)
                ordered_titles.append(title)
            if not ordered_titles:
                for title in article_titles_by_parent.get(state.normalized_item.id, []):
                    title_key = re.sub(r"\s+", " ", title).strip().lower()
                    if title_key in seen_ordered_titles:
                        continue
                    seen_ordered_titles.add(title_key)
                    ordered_titles.append(title)

            preview_limit = max(
                len(state.render_card.market_child_previews),
                len(state.source_metadata.get("market_child_previews", [])),
                min(len(ordered_titles), MARKET_ARTICLE_FETCH_LIMIT),
            )
            desired_previews = ordered_titles[:preview_limit]
            if desired_previews and state.render_card.market_child_previews != desired_previews:
                state.render_card.market_child_previews = desired_previews
                state.source_metadata["market_child_previews"] = desired_previews
                self.dependencies.workflow_repository.save(state)

    def get_source_file(self, item_id: str) -> tuple[Path, str] | None:
        """Return one archived source file path and file name for the given item."""

        state = self.get_item(item_id)
        if state is None:
            return None
        archived_path = str(state.source_metadata.get("archived_source_path") or "").strip()
        if not archived_path:
            return None
        path = Path(archived_path)
        if not path.exists() or not path.is_file():
            return None
        file_name = str(state.source_metadata.get("archived_source_name") or "").strip() or path.name
        return path, file_name

    def cleanup_source_files(self, *, trigger: str = "manual") -> dict[str, Any]:
        """Delete archived source files based on retention settings and references."""

        states = self.dependencies.workflow_repository.list_all()
        referenced_by_path: dict[str, list[AgentState]] = {}
        for state in states:
            archived_path = str(state.source_metadata.get("archived_source_path") or "").strip()
            if not archived_path:
                continue
            referenced_by_path.setdefault(str(Path(archived_path).resolve()), []).append(state)

        existing_files = [
            file_path
            for file_path in SOURCE_ARCHIVE_ROOT.rglob("*")
            if file_path.is_file()
        ]
        total_size_before = sum(file_path.stat().st_size for file_path in existing_files)
        max_age_cutoff = now_in_project_timezone() - timedelta(
            days=self.settings.source_files.max_age_days
        )
        size_limit_bytes = self.settings.source_files.max_total_size_mb * 1024 * 1024
        filter_patterns = [
            pattern.lower().strip()
            for pattern in self.settings.source_files.filter_patterns
            if pattern.strip()
        ]

        reports = {
            "scanned_file_count": len(existing_files),
            "deleted_file_count": 0,
            "reclaimed_bytes": 0,
            "remaining_bytes": total_size_before,
            "deleted_orphan_file_count": 0,
            "deleted_due_to_age_count": 0,
            "deleted_due_to_size_count": 0,
            "deleted_due_to_filter_count": 0,
            "deleted_paths": [],
            "trigger": trigger,
        }

        deletion_candidates: list[tuple[Path, str]] = []
        for file_path in existing_files:
            resolved = str(file_path.resolve())
            linked_states = referenced_by_path.get(resolved, [])
            reason: str | None = None
            if not linked_states:
                reason = "orphan"
            elif any(self._matches_source_file_filter(file_path, state, filter_patterns) for state in linked_states):
                reason = "filter"
            else:
                modified_at = datetime.fromtimestamp(
                    file_path.stat().st_mtime,
                    tz=now_in_project_timezone().tzinfo,
                )
                if modified_at < max_age_cutoff:
                    reason = "age"

            if reason is None:
                continue
            deletion_candidates.append((file_path, reason))

        for file_path, reason in deletion_candidates:
            self._delete_source_file_and_detach_refs(
                file_path=file_path,
                referenced_states=referenced_by_path.get(str(file_path.resolve()), []),
                report=reports,
                reason=reason,
            )

        remaining_files = [
            file_path
            for file_path in SOURCE_ARCHIVE_ROOT.rglob("*")
            if file_path.is_file()
        ]
        total_size = sum(file_path.stat().st_size for file_path in remaining_files)
        if total_size > size_limit_bytes:
            for file_path in sorted(
                remaining_files,
                key=lambda candidate: candidate.stat().st_mtime,
            ):
                if total_size <= size_limit_bytes:
                    break
                total_size -= self._delete_source_file_and_detach_refs(
                    file_path=file_path,
                    referenced_states=referenced_by_path.get(str(file_path.resolve()), []),
                    report=reports,
                    reason="size",
                )

        reports["remaining_bytes"] = sum(
            file_path.stat().st_size
            for file_path in SOURCE_ARCHIVE_ROOT.rglob("*")
            if file_path.is_file()
        )
        return reports

    def _matches_source_file_filter(
        self,
        file_path: Path,
        state: AgentState,
        filter_patterns: list[str],
    ) -> bool:
        """Return whether one file or its card metadata matches cleanup filters."""

        if not filter_patterns:
            return False
        haystacks = [
            str(file_path),
            str(state.source_ref or ""),
            str(state.raw_input or ""),
            str(state.source_metadata.get("source_title") or ""),
            str(state.render_card.summary_one_line if state.render_card else ""),
        ]
        joined = "\n".join(haystacks).lower()
        return any(pattern in joined for pattern in filter_patterns)

    def _delete_source_file_and_detach_refs(
        self,
        *,
        file_path: Path,
        referenced_states: list[AgentState],
        report: dict[str, Any],
        reason: str,
    ) -> int:
        """Delete one archived source file and detach related active card metadata."""

        if not file_path.exists() or not file_path.is_file():
            return 0
        file_size = file_path.stat().st_size
        resolved = str(file_path.resolve())
        file_path.unlink(missing_ok=True)
        report["deleted_file_count"] += 1
        report["reclaimed_bytes"] += file_size
        report["deleted_paths"].append(resolved)
        if reason == "orphan":
            report["deleted_orphan_file_count"] += 1
        elif reason == "age":
            report["deleted_due_to_age_count"] += 1
        elif reason == "size":
            report["deleted_due_to_size_count"] += 1
        elif reason == "filter":
            report["deleted_due_to_filter_count"] += 1

        for state in referenced_states:
            archived_path = str(state.source_metadata.get("archived_source_path") or "").strip()
            if str(Path(archived_path).resolve()) != resolved:
                continue
            self._detach_archived_source_from_state(state)
        return file_size

    def _detach_archived_source_from_state(self, state: AgentState) -> None:
        """Remove archived source file metadata from one stored state."""

        state.source_metadata.pop("archived_source_path", None)
        state.source_metadata.pop("archived_source_name", None)
        if state.render_card is not None:
            state.render_card.has_source_file = False
            state.render_card.source_file_name = None
            state.render_card.source_file_path = None
        self.dependencies.workflow_repository.save(state)

    def _collect_archived_paths_from_states(
        self,
        states: list[AgentState],
    ) -> set[str]:
        """Collect normalized archived source paths from a state list."""

        archived_paths: set[str] = set()
        for state in states:
            archived_path = str(state.source_metadata.get("archived_source_path") or "").strip()
            if not archived_path:
                continue
            archived_paths.add(str(Path(archived_path).resolve()))
        return archived_paths

    def _delete_unreferenced_archived_paths(self, archived_paths: set[str]) -> None:
        """Delete archived files that are no longer referenced by any remaining card."""

        if not archived_paths:
            return

        remaining_paths = self._collect_archived_paths_from_states(
            self.dependencies.workflow_repository.list_all()
        )
        for archived_path in archived_paths:
            if archived_path in remaining_paths:
                continue
            path = Path(archived_path)
            if not path.exists() or not path.is_file():
                continue
            path.unlink(missing_ok=True)
            self._prune_empty_source_dirs(path.parent)

    def _prune_empty_source_dirs(self, directory: Path) -> None:
        """Remove empty source-file subdirectories after one archived file is deleted."""

        root = SOURCE_ARCHIVE_ROOT.resolve()
        current = directory.resolve()
        while current != root and root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _remove_deleted_item_links_from_remaining_cards(self, deleted_item_ids: set[str]) -> None:
        """Detach deleted child ids from remaining overview cards."""

        if not deleted_item_ids:
            return

        states = self.dependencies.workflow_repository.list_all()
        for state in states:
            if state.render_card is None:
                continue
            card = state.render_card
            changed = False

            next_market_children = [
                child_id for child_id in card.market_child_item_ids if child_id not in deleted_item_ids
            ]
            if next_market_children != card.market_child_item_ids:
                card.market_child_item_ids = next_market_children
                card.market_child_previews = card.market_child_previews[: len(next_market_children)]
                changed = True

            next_job_children = [
                child_id for child_id in card.job_child_item_ids if child_id not in deleted_item_ids
            ]
            if next_job_children != card.job_child_item_ids:
                card.job_child_item_ids = next_job_children
                card.job_child_previews = card.job_child_previews[: len(next_job_children)]
                changed = True

            if card.market_parent_item_id in deleted_item_ids:
                card.market_parent_item_id = None
                card.market_group_kind = None
                changed = True

            if card.job_parent_item_id in deleted_item_ids:
                card.job_parent_item_id = None
                card.job_group_kind = None
                changed = True

            if changed:
                card.updated_at = now_in_project_timezone()
                self.dependencies.workflow_repository.save(state)

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

    def _expand_job_group_overview_with_existing_cards(
        self,
        *,
        overview_state: AgentState,
        child_states: list[AgentState],
    ) -> AgentState:
        """Merge one newly built overview with older related cards when the new section is only part of the cluster."""

        if not child_states:
            return overview_state

        candidate_states: list[AgentState] = [*child_states]
        candidate_states.extend(self._list_related_company_cards(overview_state))
        for child_state in child_states:
            candidate_states.extend(self._list_related_company_cards(child_state))
        unique_candidates = self._dedupe_states_by_item_id(candidate_states)
        if len(unique_candidates) <= len(child_states):
            return overview_state

        connected_ids: set[str] = set()
        relationship_checks: list[dict[str, Any]] = []
        group_title_votes: list[str] = []
        for anchor_state in [*child_states, overview_state]:
            cluster_states, cluster_checks, cluster_votes = self._collect_job_relationship_cluster(
                anchor_state=anchor_state,
                candidate_states=unique_candidates,
            )
            relationship_checks.extend(cluster_checks)
            group_title_votes.extend(cluster_votes)
            for cluster_state in cluster_states:
                if cluster_state.normalized_item is not None:
                    connected_ids.add(cluster_state.normalized_item.id)

        if len(connected_ids) <= len(
            [
                child_state
                for child_state in child_states
                if child_state.normalized_item is not None
            ]
        ):
            return overview_state

        expanded_children = [
            state
            for state in unique_candidates
            if state.normalized_item is not None and state.normalized_item.id in connected_ids
        ]
        group_title = self._pick_job_group_title(
            expanded_children,
            [
                str(overview_state.normalized_item.source_title or "").strip()
                if overview_state.normalized_item is not None
                else "",
                *group_title_votes,
            ],
        )
        if not group_title:
            return overview_state

        expanded_overview = self._upsert_dynamic_job_group_overview(
            anchor_state=child_states[0],
            child_states=expanded_children,
            group_title=group_title,
        )
        expanded_overview.source_metadata["job_relationship_checks"] = relationship_checks
        self._refresh_stale_job_overviews(
            user_id=child_states[0].user_id,
            workspace_id=child_states[0].workspace_id,
            keep_parent_id=expanded_overview.normalized_item.id if expanded_overview.normalized_item else None,
        )
        self.dependencies.workflow_repository.save(expanded_overview)
        return expanded_overview

    def _select_primary_ingest_state(self, states: list[AgentState]) -> AgentState:
        """Choose the most representative state for single-item API responses."""

        if not states:
            raise RuntimeError("本次导入没有生成任何卡片。")
        for state in reversed(states):
            if state.source_metadata.get("job_group_kind") == "overview":
                return state
        for state in reversed(states):
            parent_id = str(state.source_metadata.get("job_parent_item_id") or "").strip()
            if not parent_id:
                continue
            parent_state = self.dependencies.workflow_repository.get(parent_id)
            if parent_state is not None:
                return parent_state
        for state in reversed(states):
            if state.render_card is not None:
                return state
        return states[-1]

    def _collect_cascade_delete_states(self, item_id: str) -> list[AgentState]:
        """Collect one item and any overview children that should be deleted together."""

        state = self.get_item(item_id)
        if state is None:
            return []

        states_to_delete: list[AgentState] = []
        pending_item_ids = [item_id]
        seen_target_ids: set[str] = set()
        while pending_item_ids:
            target_item_id = pending_item_ids.pop()
            if target_item_id in seen_target_ids:
                continue
            target_state = self.get_item(target_item_id)
            if target_state is None:
                continue
            states_to_delete.append(target_state)
            if target_state.normalized_item is not None:
                seen_target_ids.add(target_state.normalized_item.id)
            else:
                seen_target_ids.add(target_item_id)
            if target_state.render_card is None:
                continue
            pending_item_ids.extend(
                child_item_id
                for child_item_id in [
                    *target_state.render_card.market_child_item_ids,
                    *target_state.render_card.job_child_item_ids,
                ]
                if child_item_id not in seen_target_ids
            )
        return states_to_delete

    def delete_item_ids(self, item_id: str) -> list[str]:
        """Delete one stored item tree and return every item id actually removed."""

        states_to_delete = self._collect_cascade_delete_states(item_id)
        if not states_to_delete:
            return []

        archived_paths = self._collect_archived_paths_from_states(states_to_delete)
        deleted_item_ids: set[str] = set()
        for target_state in states_to_delete:
            target_item_id = (
                target_state.normalized_item.id
                if target_state.normalized_item is not None
                else None
            )
            if not target_item_id:
                continue
            self.dependencies.reminder_queue.delete_for_item(target_item_id)
            deleted_current = self.dependencies.workflow_repository.delete(target_item_id)
            if deleted_current:
                deleted_item_ids.add(target_item_id)
        if deleted_item_ids:
            self._remove_deleted_item_links_from_remaining_cards(deleted_item_ids)
        if deleted_item_ids and self.settings.source_files.delete_when_item_deleted:
            self._delete_unreferenced_archived_paths(archived_paths)
        return [
            target_state.normalized_item.id
            for target_state in states_to_delete
            if target_state.normalized_item is not None
            and target_state.normalized_item.id in deleted_item_ids
        ]

    def delete_item(self, item_id: str) -> bool:
        """Delete one stored item plus its reminders."""

        return bool(self.delete_item_ids(item_id))

    def delete_items(self, item_ids: list[str]) -> tuple[list[str], list[str]]:
        """Delete multiple stored items and return deleted vs missing ids."""

        deleted_item_ids: list[str] = []
        missing_item_ids: list[str] = []
        seen: set[str] = set()
        deleted_seen: set[str] = set()

        for item_id in item_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            if item_id in deleted_seen:
                continue
            if self.get_item(item_id) is None:
                missing_item_ids.append(item_id)
                continue
            deleted_current = self.delete_item_ids(item_id)
            for deleted_item_id in deleted_current:
                if deleted_item_id in deleted_seen:
                    continue
                deleted_seen.add(deleted_item_id)
                deleted_item_ids.append(deleted_item_id)

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
        current_profile = ProfileMemory.model_validate(current["profile_memory"])
        merged_profile = profile_memory.model_copy(
            update={
                "persona_keywords": (
                    profile_memory.persona_keywords
                    if profile_memory.persona_keywords
                    else current_profile.persona_keywords
                ),
                "projects": (
                    profile_memory.projects
                    if profile_memory.projects
                    else current_profile.projects
                ),
                "hard_filters": (
                    profile_memory.hard_filters
                    if profile_memory.hard_filters
                    else current_profile.hard_filters
                ),
                "resume_snapshot": profile_memory.resume_snapshot or current_profile.resume_snapshot,
                "last_confirmed_at": profile_memory.last_confirmed_at or current_profile.last_confirmed_at,
            }
        )
        current["profile_memory"] = merged_profile
        self.dependencies.memory_provider.save(
            {
                "user_id": profile_memory.user_id,
                "workspace_id": profile_memory.workspace_id,
                **current,
            }
        )
        return merged_profile, CareerStateMemory.model_validate(current["career_state_memory"])

    def get_memory_snapshot(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
    ) -> tuple[ProfileMemory, CareerStateMemory]:
        """Return the current persisted memory snapshot for one user scope."""

        current = self.dependencies.memory_provider.load(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        return (
            ProfileMemory.model_validate(current["profile_memory"]),
            CareerStateMemory.model_validate(current["career_state_memory"]),
        )

    def get_resume_source_file(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
    ) -> tuple[Path, str] | None:
        """Return the archived resume source file saved in profile memory, when present."""

        profile, _ = self.get_memory_snapshot(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if profile.resume_snapshot is None or not profile.resume_snapshot.source_file_path:
            return None

        file_path = Path(profile.resume_snapshot.source_file_path)
        if not file_path.exists() or not file_path.is_file():
            return None
        file_name = profile.resume_snapshot.source_file_name or file_path.name
        return file_path, file_name

    def get_project_source_file(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
        project_name: str,
    ) -> tuple[Path, str] | None:
        """Return one archived project source file stored in profile memory."""

        profile, _ = self.get_memory_snapshot(user_id=user_id, workspace_id=workspace_id)
        for project in profile.projects:
            if project.name.strip().lower() != project_name.strip().lower():
                continue
            if not project.source_file_path:
                return None
            file_path = Path(project.source_file_path)
            if not file_path.exists():
                return None
            return file_path, project.source_file_name or file_path.name
        return None

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
                    user_id=user_id,
                    workspace_id=workspace_id,
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

        result = self.chat_query_enhanced(
            query=query,
            user_id=user_id,
            workspace_id=workspace_id,
            item_id=item_id,
            recent_days=recent_days,
            uploaded_files=[],
            apply_memory_updates=True,
        )
        supporting_ids = result.supporting_item_ids
        return (
            result.answer,
            supporting_ids,
            result.citations,
            result.retrieval_mode,
        )

    def chat_query_enhanced(
        self,
        *,
        query: str,
        user_id: str,
        workspace_id: str | None,
        item_id: str | None = None,
        recent_days: int = 30,
        uploaded_files: list[tuple[str, bytes]] | None = None,
        apply_memory_updates: bool = True,
    ) -> ChatExecutionResult:
        """Run chat preprocessing, optional attachment handling, retrieval, and memory updates."""

        query_text, local_paths = self._split_inline_content_and_paths(query)
        query_text = query_text.strip()
        current_memory = self.dependencies.memory_provider.load(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        profile = ProfileMemory.model_validate(current_memory["profile_memory"])
        career_state = CareerStateMemory.model_validate(current_memory["career_state_memory"])

        attachments, attachment_failures = self._collect_chat_attachments(
            local_paths=local_paths,
            uploaded_files=uploaded_files or [],
        )
        if not query_text:
            if any(self._looks_like_resume_attachment(attachment) for attachment in attachments):
                query_text = "请基于我的简历给出求职建议、简历润色重点和面试准备方向。"
            elif attachments:
                query_text = "请基于我刚上传的资料给出下一步求职建议。"
            elif attachment_failures:
                query_text = "我上传的资料暂时解析失败了，请先说明可能原因，并告诉我下一步该怎么处理。"
            else:
                query_text = "请基于当前卡片和画像给我下一步建议。"

        query_analysis = self.chat_service.analyze_query(
            query=query_text,
            recent_days=recent_days,
        )
        query_analysis = self._expand_chat_query_analysis(
            query=query_text,
            query_analysis=query_analysis,
            profile=profile,
            career_state=career_state,
        )
        selected_states = self._select_chat_states(
            user_id=user_id,
            workspace_id=workspace_id,
            item_id=item_id,
            recent_days=query_analysis.recent_days,
        )
        valid_states = [
            state for state in selected_states if state is not None and state.normalized_item
        ]

        (
            profile,
            career_state,
            attachment_documents,
            attachment_results,
            memory_update,
        ) = self._prepare_chat_context(
            profile=profile,
            career_state=career_state,
            query=query_text,
            query_analysis=query_analysis,
            attachments=attachments,
            apply_memory_updates=apply_memory_updates,
        )

        result = self.chat_service.answer(
            query=query_text,
            states=valid_states,
            profile=profile,
            career_state=career_state,
            item_id=item_id,
            recent_days=query_analysis.recent_days,
            extra_documents=attachment_documents,
            query_analysis=query_analysis,
        )
        all_attachment_results = [*attachment_failures, *attachment_results]
        final_answer = self._compose_attachment_aware_answer(
            answer=result.answer,
            attachments=all_attachment_results,
        )
        supporting_ids = result.supporting_item_ids or [
            state.normalized_item.id
            for state in valid_states[:3]
            if state.normalized_item is not None
        ]

        if memory_update.applied:
            self.dependencies.memory_provider.save(
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "profile_memory": profile,
                    "career_state_memory": career_state,
                }
            )

        return ChatExecutionResult(
            answer=final_answer,
            supporting_item_ids=supporting_ids,
            citations=result.citations,
            retrieval_mode=result.retrieval_mode,
            query_analysis=query_analysis,
            memory_update=memory_update,
            attachments=all_attachment_results,
        )

    def summarize_chat_session(
        self,
        *,
        mode: str,
        turns: list[dict[str, Any]],
        conversation_title: str | None = None,
    ) -> ChatSessionSummaryResult:
        """Compress one archived conversation using keyword extraction + hierarchical summary."""

        cleaned_turns = [
            {
                "mode": str(turn.get("mode") or mode or "grounded_chat"),
                "user_message": str(turn.get("user_message") or "").strip(),
                "answer": str(turn.get("answer") or "").strip(),
                "strategy": str(turn.get("strategy") or "").strip(),
            }
            for turn in turns
            if str(turn.get("user_message") or "").strip() or str(turn.get("answer") or "").strip()
        ]
        if not cleaned_turns:
            return ChatSessionSummaryResult(
                title=conversation_title or "空白对话",
                summary="这段对话还没有有效内容。",
                keywords=[],
                compressed_transcript="暂无历史对话。",
                summary_source="heuristic",
            )

        keywords = self._extract_chat_session_keywords(cleaned_turns)
        compressed_transcript = self._compress_chat_session_turns(cleaned_turns)
        fallback = self._build_chat_session_summary_fallback(
            mode=mode,
            turns=cleaned_turns,
            keywords=keywords,
            compressed_transcript=compressed_transcript,
            conversation_title=conversation_title,
        )

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("chat_session_summary")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="chat_session_summary",
                    system_prompt=prompt,
                    user_payload={
                        "mode": mode,
                        "conversation_title": conversation_title,
                        "keywords": keywords,
                        "compressed_transcript": compressed_transcript,
                        "fallback": {
                            "title": fallback.title,
                            "summary": fallback.summary,
                            "keywords": fallback.keywords,
                        },
                    },
                )
                title = str(response.get("title") or "").strip() or fallback.title
                summary = str(response.get("summary") or "").strip() or fallback.summary
                llm_keywords = [
                    str(value).strip()
                    for value in response.get("keywords", [])
                    if str(value).strip()
                ]
                return ChatSessionSummaryResult(
                    title=title[:60],
                    summary=summary[:240],
                    keywords=list(dict.fromkeys([*llm_keywords, *keywords]))[:8],
                    compressed_transcript=compressed_transcript,
                    summary_source="llm",
                )
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        return fallback

    def _extract_chat_session_keywords(self, turns: list[dict[str, str]]) -> list[str]:
        """Extract reusable keywords from archived chat turns before summarization."""

        combined = "\n".join(
            "\n".join(
                [
                    str(turn.get("user_message") or ""),
                    str(turn.get("answer") or ""),
                    str(turn.get("strategy") or ""),
                ]
            )
            for turn in turns
        )
        keywords: list[str] = []
        keywords.extend(self._extract_role_candidates(combined))
        keywords.extend(self._extract_skill_candidates(combined))
        keywords.extend(self._extract_company_candidates(combined))
        keywords.extend(self._extract_keyword_candidates(combined))
        return list(dict.fromkeys(keyword for keyword in keywords if len(keyword.strip()) >= 2))[:8]

    def _compress_chat_session_turns(self, turns: list[dict[str, str]]) -> str:
        """Keep recent turns verbatim while compressing older ones into a lightweight memo."""

        recent_window = turns[-4:]
        older_turns = turns[:-4]
        lines: list[str] = []

        if older_turns:
            lines.append("中期摘要：")
            for index, turn in enumerate(older_turns[-8:], start=max(len(older_turns) - 7, 1)):
                user_message = str(turn.get("user_message") or "").replace("\n", " ").strip()
                answer = str(turn.get("answer") or "").replace("\n", " ").strip()
                strategy = str(turn.get("strategy") or "").replace("\n", " ").strip()
                parts = [f"第 {index} 轮"]
                if user_message:
                    parts.append(f"输入：{user_message[:80]}")
                if answer:
                    parts.append(f"输出：{answer[:90]}")
                if strategy:
                    parts.append(f"策略：{strategy[:60]}")
                lines.append(" | ".join(parts))

        lines.append("最近窗口：")
        for index, turn in enumerate(recent_window, start=max(len(turns) - len(recent_window) + 1, 1)):
            user_message = str(turn.get("user_message") or "").strip()
            answer = str(turn.get("answer") or "").strip()
            strategy = str(turn.get("strategy") or "").strip()
            lines.append(f"第 {index} 轮输入：{user_message[:220]}")
            if answer:
                lines.append(f"第 {index} 轮输出：{answer[:260]}")
            if strategy:
                lines.append(f"第 {index} 轮策略：{strategy[:160]}")
        return "\n".join(lines)[:3200]

    def _build_chat_session_summary_fallback(
        self,
        *,
        mode: str,
        turns: list[dict[str, str]],
        keywords: list[str],
        compressed_transcript: str,
        conversation_title: str | None,
    ) -> ChatSessionSummaryResult:
        """Build one deterministic archived-conversation summary when live LLM is unavailable."""

        latest_turn = turns[-1]
        latest_user_message = str(latest_turn.get("user_message") or "").strip()
        latest_answer = str(latest_turn.get("answer") or "").strip()
        title = (
            str(conversation_title or "").strip()
            or " / ".join(keywords[:2]).strip()
            or latest_user_message[:24]
            or "聊天对话"
        )
        mode_label = "Boss 模拟" if mode == "boss_simulator" else "聊天问答"
        summary_bits = [
            f"{mode_label}共 {len(turns)} 轮",
            f"最近在处理：{latest_user_message[:50] or '未记录问题'}",
        ]
        if latest_answer:
            summary_bits.append(f"最新输出：{latest_answer[:70]}")
        if keywords:
            summary_bits.append(f"关键词：{'、'.join(keywords[:4])}")
        return ChatSessionSummaryResult(
            title=title[:60],
            summary="；".join(summary_bits)[:240],
            keywords=keywords[:8],
            compressed_transcript=compressed_transcript,
            summary_source="heuristic",
        )

    def _expand_chat_query_analysis(
        self,
        *,
        query: str,
        query_analysis: QueryAnalysis,
        profile: ProfileMemory,
        career_state: CareerStateMemory,
    ) -> QueryAnalysis:
        """Build richer retrieval queries before RAG, using profile context and optional web expansion."""

        heuristic_rewrite = self._build_chat_rewritten_query(
            query=query,
            query_analysis=query_analysis,
            profile=profile,
            career_state=career_state,
        )
        heuristic_queries = self._build_chat_retrieval_queries(
            query=query,
            query_analysis=query_analysis,
            profile=profile,
            career_state=career_state,
            rewritten_query=heuristic_rewrite,
        )
        heuristic_web_queries = self._build_chat_web_search_queries(
            query=query,
            query_analysis=query_analysis,
            profile=profile,
            career_state=career_state,
            rewritten_query=heuristic_rewrite,
        )
        search_hints = list(query_analysis.search_hints)
        rewritten_query = heuristic_rewrite
        retrieval_queries = heuristic_queries
        web_search_queries = heuristic_web_queries

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("chat_query_rewrite")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="chat_query_rewrite",
                    system_prompt=prompt,
                    user_payload={
                        "query": query,
                        "intent": query_analysis.intent,
                        "search_hints": search_hints,
                        "profile_summary": {
                            "target_roles": profile.target_roles,
                            "priority_domains": profile.priority_domains,
                            "skills": profile.skills,
                            "persona_keywords": profile.persona_keywords,
                        },
                        "career_state_summary": {
                            "today_focus": career_state.today_focus,
                            "active_priorities": career_state.active_priorities,
                            "watched_companies": career_state.watched_companies,
                        },
                        "fallback_rewritten_query": heuristic_rewrite,
                        "fallback_retrieval_queries": heuristic_queries,
                        "fallback_web_search_queries": heuristic_web_queries,
                    },
                )
                rewritten_candidate = str(response.get("rewritten_query") or "").strip()
                llm_queries = [
                    str(value).strip()
                    for value in response.get("retrieval_queries", [])
                    if str(value).strip()
                ]
                llm_web_queries = [
                    str(value).strip()
                    for value in response.get("web_search_queries", [])
                    if str(value).strip()
                ]
                llm_hints = [
                    str(value).strip()
                    for value in response.get("search_hints", [])
                    if str(value).strip()
                ]
                if rewritten_candidate:
                    rewritten_query = rewritten_candidate
                retrieval_queries = self._merge_unique_texts(
                    [query, rewritten_query, *heuristic_queries, *llm_queries],
                    limit=6,
                )
                web_search_queries = self._merge_unique_texts(
                    [*heuristic_web_queries, *llm_web_queries],
                    limit=3,
                )
                search_hints = self._merge_unique_texts(
                    [*search_hints, *llm_hints],
                    limit=16,
                )
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        if self._should_expand_chat_query_with_web(query, query_analysis=query_analysis):
            search_hints, web_search_queries = self._expand_chat_search_hints_via_web(
                search_hints=search_hints,
                web_search_queries=web_search_queries,
            )

        retrieval_queries = self._merge_unique_texts(
            [query, rewritten_query, *retrieval_queries],
            limit=6,
        )
        return replace(
            query_analysis,
            search_hints=tuple(search_hints),
            rewritten_query=rewritten_query,
            retrieval_queries=tuple(retrieval_queries),
            web_search_queries=tuple(web_search_queries),
        )

    def _build_chat_rewritten_query(
        self,
        *,
        query: str,
        query_analysis: QueryAnalysis,
        profile: ProfileMemory,
        career_state: CareerStateMemory,
    ) -> str:
        """Normalize sparse chat questions into one more retrieval-friendly expression."""

        focus_terms = self._collect_profile_focus_terms(profile, career_state)[:4]
        base_query = re.sub(r"\s+", " ", query).strip()
        if not base_query:
            return "结合求职卡片和画像给出下一步建议"
        if query_analysis.intent == "job_targeting" and any(
            keyword in base_query for keyword in ("链接", "名称", "待投递", "岗位")
        ):
            joined_focus = " ".join(focus_terms)
            return (
                f"结合现有求职卡片，整理待跟进岗位的名称、公司、投递链接、来源链接 {joined_focus}"
            ).strip()
        if query_analysis.intent == "deadline_planning":
            return f"结合现有卡片整理近期投递、面试、活动的 DDL 和时间节点 {base_query}".strip()
        if query_analysis.intent in {"resume_polish", "interview_prep", "hr_reply"}:
            joined_focus = " ".join(focus_terms)
            return f"{base_query} 简历 项目经历 岗位 JD 面试 {joined_focus}".strip()
        if self._is_sparse_chat_query(base_query):
            joined_focus = " ".join(focus_terms)
            return f"{base_query} 求职卡片 画像 {joined_focus}".strip()
        return base_query

    def _build_chat_retrieval_queries(
        self,
        *,
        query: str,
        query_analysis: QueryAnalysis,
        profile: ProfileMemory,
        career_state: CareerStateMemory,
        rewritten_query: str,
    ) -> list[str]:
        """Create multiple retrieval formulations inspired by query rewrite and step-back retrieval."""

        profile_terms = self._collect_profile_focus_terms(profile, career_state)[:4]
        focus_suffix = " ".join(profile_terms).strip()
        retrieval_queries = [query, rewritten_query]

        if query_analysis.intent == "job_targeting":
            retrieval_queries.append(
                f"岗位 名称 链接 投递链接 来源链接 {' '.join(query_analysis.search_hints[:6])}".strip()
            )
            if focus_suffix:
                retrieval_queries.append(f"岗位 投递 {focus_suffix}".strip())
        elif query_analysis.intent == "deadline_planning":
            retrieval_queries.append(
                f"DDL 截止时间 投递 面试 提醒 {' '.join(query_analysis.search_hints[:6])}".strip()
            )
        elif query_analysis.intent in {"resume_polish", "interview_prep", "hr_reply"}:
            retrieval_queries.append(
                f"简历 项目经历 技术栈 岗位 JD {' '.join(query_analysis.search_hints[:6])}".strip()
            )
        elif self._is_sparse_chat_query(query):
            retrieval_queries.append(
                f"{' '.join(query_analysis.search_hints[:6])} {' '.join(profile_terms)}".strip()
            )

        if any(marker in query for marker in ("为什么", "如何", "怎么")):
            retrieval_queries.append(
                f"相关背景 原理 经验 {' '.join(query_analysis.search_hints[:6])}".strip()
            )

        return self._merge_unique_texts(retrieval_queries, limit=6)

    def _build_chat_web_search_queries(
        self,
        *,
        query: str,
        query_analysis: QueryAnalysis,
        profile: ProfileMemory,
        career_state: CareerStateMemory,
        rewritten_query: str,
    ) -> list[str]:
        """Prepare one or more tiny web-search queries only for keyword expansion."""

        focus_terms = self._collect_profile_focus_terms(profile, career_state)[:3]
        seed_terms = self._merge_unique_texts(
            [*query_analysis.search_hints, *focus_terms],
            limit=5,
        )
        web_queries = []
        if seed_terms:
            web_queries.append(" ".join(seed_terms))
        if self._is_sparse_chat_query(query):
            web_queries.append(f"{rewritten_query} {' '.join(seed_terms[:3])}".strip())
        return self._merge_unique_texts(web_queries, limit=3)

    def _should_expand_chat_query_with_web(
        self,
        query: str,
        *,
        query_analysis: QueryAnalysis,
    ) -> bool:
        """Use web snippets only as query-expansion fuel for underspecified questions."""

        return bool(
            self._is_sparse_chat_query(query)
            or (
                query_analysis.intent == "job_targeting"
                and any(keyword in query for keyword in ("名称", "链接", "待投递", "所有"))
            )
        )

    def _expand_chat_search_hints_via_web(
        self,
        *,
        search_hints: list[str],
        web_search_queries: list[str],
    ) -> tuple[list[str], list[str]]:
        """Search the web once to discover extra query terms, without answering from web results."""

        if not web_search_queries:
            return search_hints, web_search_queries
        expanded_hints = list(search_hints)
        successful_queries: list[str] = []
        for query in web_search_queries[:2]:
            try:
                results = self.dependencies.search_client.search(query=query, limit=5)
            except Exception:
                continue
            if not results:
                continue
            successful_queries.append(query)
            for result in results:
                expanded_hints.extend(
                    self._extract_keyword_candidates(
                        " ".join(
                            [
                                str(result.get("title") or ""),
                                str(result.get("snippet") or ""),
                            ]
                        )
                    )
                )
        return (
            self._merge_unique_texts(expanded_hints, limit=16),
            self._merge_unique_texts([*web_search_queries, *successful_queries], limit=3),
        )

    def _merge_unique_texts(self, values: list[str], *, limit: int) -> list[str]:
        """Deduplicate short strings while preserving order."""

        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = re.sub(r"\s+", " ", str(value)).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
            if len(merged) >= limit:
                break
        return merged

    def _is_sparse_chat_query(self, query: str) -> bool:
        """Detect questions that are too short or generic to retrieve well without expansion."""

        normalized = re.sub(r"\s+", " ", query).strip()
        if len(normalized) <= 18:
            return True
        generic_markers = (
            "请给我",
            "帮我看看",
            "有哪些",
            "所有",
            "这个",
            "那个",
            "名称与链接",
            "待投递",
        )
        token_count = len(
            re.findall(r"[A-Za-z0-9_+.#-]+|[\u4e00-\u9fff]{2,10}", normalized.lower())
        )
        return token_count <= 5 or any(marker in normalized for marker in generic_markers)

    def _select_chat_states(
        self,
        *,
        user_id: str,
        workspace_id: str | None,
        item_id: str | None,
        recent_days: int,
    ) -> list[AgentState]:
        """Select item states relevant to one chat turn before retrieval."""

        states = self.list_items(user_id=user_id, workspace_id=workspace_id)
        if item_id:
            target = self.get_item(item_id)
            return [target] if target else []

        cutoff = now_in_project_timezone()
        return [
            state
            for state in states
            if state is not None
            and self._state_timestamp(state) is not None
            and (cutoff - self._state_timestamp(state)).days <= max(1, recent_days)
        ]

    def _collect_chat_attachments(
        self,
        *,
        local_paths: list[Path],
        uploaded_files: list[tuple[str, bytes]],
    ) -> tuple[list[ExtractedAttachment], list[ChatAttachmentResult]]:
        """Extract chat attachments without sending them through the item workflow."""

        attachments: list[ExtractedAttachment] = []
        failures: list[ChatAttachmentResult] = []
        for local_path in local_paths:
            try:
                attachments.append(self._extract_attachment_from_local_path(local_path))
            except Exception as exc:
                failures.append(
                    ChatAttachmentResult(
                        display_name=local_path.name,
                        source_ref=str(local_path),
                        extraction_kind="failed",
                        attachment_kind="document",
                        summary="附件暂时未能成功转成可分析文本。",
                        persisted_to_profile=False,
                        text_length=0,
                        processing_error=str(exc),
                    )
                )
        for file_name, file_bytes in uploaded_files:
            try:
                attachments.append(
                    self._extract_attachment_from_upload(
                        file_name=file_name,
                        file_bytes=file_bytes,
                    )
                )
            except Exception as exc:
                failures.append(
                    ChatAttachmentResult(
                        display_name=file_name,
                        source_ref=file_name,
                        extraction_kind="failed",
                        attachment_kind="document",
                        summary="附件暂时未能成功转成可分析文本。",
                        persisted_to_profile=False,
                        text_length=0,
                        processing_error=str(exc),
                    )
                )
        return attachments, failures

    def _prepare_chat_context(
        self,
        *,
        profile: ProfileMemory,
        career_state: CareerStateMemory,
        query: str,
        query_analysis: QueryAnalysis,
        attachments: list[ExtractedAttachment],
        apply_memory_updates: bool,
    ) -> tuple[
        ProfileMemory,
        CareerStateMemory,
        list[RAGDocument],
        list[ChatAttachmentResult],
        ChatMemoryUpdateSummary,
    ]:
        """Prepare extra chat documents and conservative memory updates."""

        extra_documents: list[RAGDocument] = []
        attachment_results: list[ChatAttachmentResult] = []
        notes: list[str] = []
        profile_fields: list[str] = []
        career_fields: list[str] = []
        updated_profile = profile
        updated_career = career_state

        for attachment in attachments:
            if self._looks_like_resume_attachment(attachment):
                attachment_kind = "resume"
            elif self._looks_like_project_attachment(attachment):
                attachment_kind = "project"
            else:
                attachment_kind = "document"
            attachment_summary = self._summarize_chat_attachment(
                display_name=attachment.display_name,
                attachment_kind=attachment_kind,
                text=attachment.text,
            )
            extra_documents.append(
                RAGDocument(
                    doc_id=f"chat_attachment:{uuid4().hex}",
                    doc_type=attachment_kind,
                    source_label=(
                        f"简历附件 - {attachment.display_name}"
                        if attachment_kind == "resume"
                        else (
                            f"项目附件 - {attachment.display_name}"
                            if attachment_kind == "project"
                            else f"聊天附件 - {attachment.display_name}"
                        )
                    ),
                    text=(
                        f"文件名：{attachment.display_name}\n"
                        f"主要内容：{attachment_summary}\n"
                        f"文件正文：{attachment.text}"
                    ),
                    snippet=attachment_summary[:240],
                    created_at=now_in_project_timezone(),
                )
            )
            persisted = False
            if apply_memory_updates and attachment_kind == "resume":
                structured_resume = self._structure_resume_snapshot(
                    display_name=attachment.display_name,
                    text=attachment.text,
                )
                updated_profile = updated_profile.model_copy(
                    update={
                        "resume_snapshot": ResumeSnapshot(
                            file_name=attachment.display_name,
                            source_file_name=str(
                                attachment.source_metadata.get("archived_source_name")
                                or attachment.source_metadata.get("file_name")
                                or attachment.display_name
                            ),
                            source_file_path=str(
                                attachment.source_metadata.get("archived_source_path")
                                or attachment.source_metadata.get("stored_path")
                                or ""
                            )
                            or None,
                            text=attachment.text,
                            summary=self._build_resume_summary(attachment.text),
                            structured_profile=structured_resume,
                            updated_at=now_in_project_timezone(),
                        ),
                        "updated_at": now_in_project_timezone(),
                    }
                )
                if "resume_snapshot" not in profile_fields:
                    profile_fields.append("resume_snapshot")
                notes.append(f"已把 {attachment.display_name} 作为最新简历原文写入画像。")
                persisted = True
            elif apply_memory_updates and attachment_kind == "project":
                project_entry = self._structure_project_snapshot(
                    display_name=attachment.display_name,
                    text=attachment.text,
                    source_file_name=str(
                        attachment.source_metadata.get("archived_source_name")
                        or attachment.source_metadata.get("file_name")
                        or attachment.display_name
                    )
                    or None,
                    source_file_path=str(
                        attachment.source_metadata.get("archived_source_path")
                        or attachment.source_metadata.get("stored_path")
                        or ""
                    )
                    or None,
                )
                merged_projects, _ = self._merge_project_entries(
                    current_projects=list(updated_profile.projects),
                    new_entry=project_entry,
                )
                updated_profile = updated_profile.model_copy(
                    update={
                        "projects": merged_projects,
                        "updated_at": now_in_project_timezone(),
                    }
                )
                if "projects" not in profile_fields:
                    profile_fields.append("projects")
                notes.append(f"已把 {attachment.display_name} 整理成项目画像并写入长期记忆。")
                persisted = True
            attachment_results.append(
                ChatAttachmentResult(
                    display_name=attachment.display_name,
                    source_ref=attachment.source_ref,
                    extraction_kind=attachment.extraction_kind,
                    attachment_kind=attachment_kind,
                    summary=attachment_summary,
                    persisted_to_profile=persisted,
                    text_length=len(attachment.text),
                    processing_error=None,
                )
            )

        signal_texts = [query, *(attachment.text for attachment in attachments)]
        if apply_memory_updates and query_analysis.should_update_memory:
            updated_profile, new_profile_fields, profile_notes = self._merge_profile_from_chat_signals(
                profile=updated_profile,
                texts=signal_texts,
                query_analysis=query_analysis,
            )
            updated_career, new_career_fields, career_notes = self._merge_career_from_chat_signals(
                career_state=updated_career,
                texts=signal_texts,
                query_analysis=query_analysis,
            )
            profile_fields.extend(field for field in new_profile_fields if field not in profile_fields)
            career_fields.extend(field for field in new_career_fields if field not in career_fields)
            notes.extend(profile_notes)
            notes.extend(career_notes)

        if apply_memory_updates and self._should_refresh_projects_from_resume(
            query=query,
            query_analysis=query_analysis,
            profile=updated_profile,
        ):
            refreshed_projects = self._extract_projects_from_resume_snapshot(
                updated_profile.resume_snapshot
            )
            if refreshed_projects:
                merged_projects = list(updated_profile.projects)
                for project_entry in refreshed_projects:
                    merged_projects, _ = self._merge_project_entries(
                        current_projects=merged_projects,
                        new_entry=project_entry,
                    )
                updated_profile = updated_profile.model_copy(
                    update={
                        "projects": merged_projects,
                        "updated_at": now_in_project_timezone(),
                    }
                )
                if "projects" not in profile_fields:
                    profile_fields.append("projects")
                resume_label = (
                    updated_profile.resume_snapshot.source_file_name
                    if updated_profile.resume_snapshot is not None
                    else "当前简历"
                )
                notes.append(f"已基于 {resume_label} 更新项目画像卡片。")

        applied = bool(profile_fields or career_fields)
        return (
            updated_profile,
            updated_career,
            extra_documents,
            attachment_results,
            ChatMemoryUpdateSummary(
                applied=applied,
                profile_fields=profile_fields,
                career_fields=career_fields,
                notes=notes,
            ),
        )

    def _looks_like_resume_attachment(self, attachment: ExtractedAttachment) -> bool:
        """Detect whether one attachment is likely a resume or self-profile document."""

        if RESUME_FILE_NAME_PATTERN.search(attachment.display_name):
            return True
        marker_hits = sum(1 for marker in RESUME_SECTION_MARKERS if marker in attachment.text)
        return marker_hits >= 2

    def _looks_like_project_attachment(self, attachment: ExtractedAttachment) -> bool:
        """Detect whether one attachment is likely a project profile or project description."""

        if PROJECT_FILE_NAME_PATTERN.search(attachment.display_name):
            return True
        marker_hits = sum(1 for marker in PROJECT_SECTION_MARKERS if marker in attachment.text)
        return marker_hits >= 2

    def _build_resume_summary(self, text: str) -> str:
        """Create one compact local summary from extracted resume text."""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "未提取到简历正文。"
        return " / ".join(lines[:3])[:240]

    def _build_project_summary(self, text: str) -> str:
        """Create one compact local summary from a project description attachment."""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "未提取到项目说明正文。"
        return " / ".join(lines[:4])[:260]

    def _should_refresh_projects_from_resume(
        self,
        *,
        query: str,
        query_analysis: QueryAnalysis,
        profile: ProfileMemory,
    ) -> bool:
        """Detect explicit requests to rebuild project cards from the saved resume snapshot."""

        if profile.resume_snapshot is None:
            return False
        normalized = re.sub(r"\s+", "", query.lower())
        explicit_markers = (
            "用简历更新项目画像",
            "根据简历更新项目画像",
            "用简历生成项目画像",
            "根据简历生成项目画像",
            "从简历更新项目画像",
            "从简历生成项目画像",
            "用简历更新项目卡片",
            "根据简历更新项目卡片",
            "根据简历整理项目经历",
        )
        if any(marker in normalized for marker in explicit_markers):
            return True
        return bool(
            "projects" in query_analysis.profile_update_hints
            and "简历" in query
            and any(keyword in query for keyword in ("项目画像", "项目卡片", "项目经历"))
            and any(keyword in query for keyword in ("更新", "整理", "生成", "同步"))
        )

    def _extract_projects_from_resume_snapshot(
        self,
        resume_snapshot: ResumeSnapshot | None,
    ) -> list[ProjectMemoryEntry]:
        """Build project memory entries from the current saved resume snapshot."""

        if resume_snapshot is None:
            return []

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("resume_projects_to_memory")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="resume_projects_to_memory",
                    system_prompt=prompt,
                    user_payload={
                        "file_name": resume_snapshot.file_name or "resume",
                        "text": resume_snapshot.text[:14000],
                    },
                )
                projects: list[ProjectMemoryEntry] = []
                for item in response.get("projects", []):
                    name = str(item.get("name") or "").strip()
                    summary = str(item.get("summary") or "").strip()
                    if not name or not summary:
                        continue
                    projects.append(
                        ProjectMemoryEntry(
                            name=name[:80],
                            summary=summary[:280],
                            role=str(item.get("role") or "").strip() or None,
                            tech_stack=[
                                str(value).strip()
                                for value in item.get("tech_stack", [])
                                if str(value).strip()
                            ][:12],
                            highlight_points=[
                                str(value).strip()
                                for value in item.get("highlight_points", [])
                                if str(value).strip()
                            ][:8],
                            interview_story_hooks=[
                                str(value).strip()
                                for value in item.get("interview_story_hooks", [])
                                if str(value).strip()
                            ][:6],
                            source_file_name=resume_snapshot.source_file_name,
                            source_file_path=resume_snapshot.source_file_path,
                        )
                    )
                if projects:
                    return projects
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        return self._heuristic_extract_projects_from_resume_snapshot(resume_snapshot)

    def _heuristic_extract_projects_from_resume_snapshot(
        self,
        resume_snapshot: ResumeSnapshot,
    ) -> list[ProjectMemoryEntry]:
        """Fallback extraction of project cards from resume text without a live LLM."""

        lines = [line.strip() for line in resume_snapshot.text.splitlines() if line.strip()]
        if not lines:
            return []

        start_index = next(
            (index for index, line in enumerate(lines) if "项目经历" in line or "项目经验" in line),
            None,
        )
        if start_index is None:
            return []

        section_lines: list[str] = []
        for line in lines[start_index + 1 :]:
            compact = line.replace(" ", "")
            if compact in {"教育经历", "工作经历", "实习经历", "校园经历", "技能", "专业技能", "自我评价"}:
                break
            section_lines.append(line)

        if not section_lines:
            return []

        chunks: list[list[str]] = []
        current_chunk: list[str] = []
        for line in section_lines:
            normalized = line.strip("：: ")
            is_candidate_title = (
                2 <= len(normalized) <= 36
                and not URL_PATTERN.search(normalized)
                and any(char not in "0123456789.-/" for char in normalized)
                and any(keyword in normalized for keyword in ("项目", "系统", "平台", "助手", "工具", "引擎"))
            )
            if is_candidate_title and current_chunk:
                chunks.append(current_chunk)
                current_chunk = [line]
                continue
            current_chunk.append(line)
        if current_chunk:
            chunks.append(current_chunk)

        projects: list[ProjectMemoryEntry] = []
        for chunk in chunks[:6]:
            if not chunk:
                continue
            title = chunk[0].strip("：: ")
            body = "\n".join(chunk[1:] or chunk[:3])
            summary = self._build_project_summary(body or "\n".join(chunk))
            tech_stack = [
                skill
                for skill in KNOWN_SKILL_TERMS
                if skill.lower() in (body or "\n".join(chunk)).lower()
            ][:12]
            highlights = [
                line
                for line in chunk[1:]
                if any(
                    marker in line
                    for marker in ("负责", "设计", "实现", "优化", "提升", "落地", "指标", "%", "效果")
                )
            ][:6]
            if not highlights:
                highlights = chunk[1:4] or chunk[:3]
            projects.append(
                ProjectMemoryEntry(
                    name=title[:80],
                    summary=summary,
                    role=None,
                    tech_stack=tech_stack,
                    highlight_points=highlights,
                    interview_story_hooks=highlights[:3],
                    source_file_name=resume_snapshot.source_file_name,
                    source_file_path=resume_snapshot.source_file_path,
                )
            )
        return projects

    def _structure_project_snapshot(
        self,
        *,
        display_name: str,
        text: str,
        source_file_name: str | None,
        source_file_path: str | None,
    ) -> ProjectMemoryEntry:
        """Build one structured project profile from an uploaded project document."""

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("project_structure")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="project_structure",
                    system_prompt=prompt,
                    user_payload={
                        "display_name": display_name,
                        "text": text[:12000],
                    },
                )
                name = str(response.get("name") or "").strip()
                summary = str(response.get("summary") or "").strip()
                if name and summary:
                    return ProjectMemoryEntry(
                        name=name,
                        summary=summary[:280],
                        role=str(response.get("role") or "").strip() or None,
                        tech_stack=[
                            str(value).strip()
                            for value in response.get("tech_stack", [])
                            if str(value).strip()
                        ][:12],
                        highlight_points=[
                            str(value).strip()
                            for value in response.get("highlight_points", [])
                            if str(value).strip()
                        ][:8],
                        interview_story_hooks=[
                            str(value).strip()
                            for value in response.get("interview_story_hooks", [])
                            if str(value).strip()
                        ][:6],
                        source_file_name=source_file_name,
                        source_file_path=source_file_path,
                    )
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        return self._heuristic_structure_project(
            display_name=display_name,
            text=text,
            source_file_name=source_file_name,
            source_file_path=source_file_path,
        )

    def _heuristic_structure_project(
        self,
        *,
        display_name: str,
        text: str,
        source_file_name: str | None,
        source_file_path: str | None,
    ) -> ProjectMemoryEntry:
        """Fallback project structuring without a live LLM."""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        name = Path(display_name).stem.strip() or "项目说明"
        if lines:
            first_line = lines[0].strip("：: ")
            if 2 <= len(first_line) <= 48 and not URL_PATTERN.search(first_line):
                name = first_line

        summary = self._build_project_summary(text)
        tech_stack = [
            skill
            for skill in KNOWN_SKILL_TERMS
            if skill.lower() in text.lower()
        ][:12]
        highlight_points = [
            line
            for line in lines
            if any(
                marker in line
                for marker in ("负责", "设计", "实现", "搭建", "优化", "提升", "落地", "效果", "指标", "%")
            )
        ][:6]
        if not highlight_points:
            highlight_points = lines[:4]
        interview_story_hooks = highlight_points[:3] or lines[:3]
        role = None
        for line in lines[:10]:
            if any(marker in line for marker in ("角色", "职责", "负责")):
                role = line[:120]
                break

        return ProjectMemoryEntry(
            name=name[:80],
            summary=summary,
            role=role,
            tech_stack=tech_stack,
            highlight_points=highlight_points,
            interview_story_hooks=interview_story_hooks,
            source_file_name=source_file_name,
            source_file_path=source_file_path,
        )

    def _merge_project_entries(
        self,
        *,
        current_projects: list[ProjectMemoryEntry],
        new_entry: ProjectMemoryEntry,
    ) -> tuple[list[ProjectMemoryEntry], bool]:
        """Insert or replace one project entry by normalized project name."""

        normalized_name = new_entry.name.strip().lower()
        remaining_projects = [
            project
            for project in current_projects
            if project.name.strip().lower() != normalized_name
        ]
        merged_projects = [*remaining_projects, new_entry]
        return merged_projects, True

    def _build_market_candidate_fallback_text(
        self,
        *,
        candidate: MarketArticleCandidate,
        published_at: datetime,
    ) -> str:
        """Build a minimal analyzable article body when only the title-level signal is available."""

        lines = [
            f"标题：{candidate.title}",
            f"发布时间：{published_at.isoformat()}",
            f"原始链接：{candidate.url}",
        ]
        if candidate.reason:
            lines.append(f"入选原因：{candidate.reason}")
        if candidate.snippet:
            lines.append(f"标题摘要：{candidate.snippet}")
        lines.append("说明：当前没有抓到正文，先保留标题级信号，方便在市场卡片中展开查看。")
        return "\n".join(lines)

    def _structure_resume_snapshot(
        self,
        *,
        display_name: str,
        text: str,
    ) -> ResumeStructuredProfile:
        """Build a structured resume view for the memory management page."""

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("resume_structure")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="resume_structure",
                    system_prompt=prompt,
                    user_payload={
                        "display_name": display_name,
                        "text": text[:12000],
                    },
                )
                sections = [
                    ResumeStructuredSection(
                        title=str(section.get("title") or "").strip(),
                        items=[
                            str(item).strip()
                            for item in section.get("items", [])
                            if str(item).strip()
                        ],
                    )
                    for section in response.get("sections", [])
                    if str(section.get("title") or "").strip()
                ]
                if sections:
                    return ResumeStructuredProfile(
                        headline=str(response.get("headline") or "").strip() or None,
                        sections=sections,
                    )
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        return self._heuristic_structure_resume(text=text)

    def _heuristic_structure_resume(self, *, text: str) -> ResumeStructuredProfile:
        """Fallback structured resume parsing without a live LLM."""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ResumeStructuredProfile(headline="未提取到简历正文。", sections=[])

        section_aliases = {
            "基本信息": "基本信息",
            "教育经历": "教育经历",
            "工作经历": "工作经历",
            "实习经历": "实习经历",
            "项目经历": "项目经历",
            "校园经历": "校园经历",
            "技能": "技能",
            "专业技能": "技能",
            "技能栈": "技能",
            "自我评价": "自我评价",
            "获奖经历": "获奖经历",
            "证书": "证书",
        }

        sections: list[ResumeStructuredSection] = []
        current_title = "基本信息"
        current_items: list[str] = []
        headline = " / ".join(lines[:2])[:160]

        def flush_section() -> None:
            nonlocal current_title, current_items
            if not current_items:
                return
            sections.append(
                ResumeStructuredSection(
                    title=current_title,
                    items=current_items[:12],
                )
            )
            current_items = []

        for line in lines:
            normalized = line.strip("：: ").replace(" ", "")
            matched_title = next(
                (
                    canonical
                    for alias, canonical in section_aliases.items()
                    if normalized.startswith(alias.replace(" ", ""))
                    and len(normalized) <= len(alias.replace(" ", "")) + 2
                ),
                None,
            )
            if matched_title is not None:
                flush_section()
                current_title = matched_title
                continue
            current_items.append(line)

        flush_section()
        if not sections:
            sections = [
                ResumeStructuredSection(
                    title="简历正文",
                    items=lines[:20],
                )
            ]
        return ResumeStructuredProfile(headline=headline, sections=sections[:8])

    def _summarize_chat_attachment(
        self,
        *,
        display_name: str,
        attachment_kind: str,
        text: str,
    ) -> str:
        """Summarize what one uploaded file mainly says before final answer generation."""

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("chat_attachment_summary")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="chat_attachment_summary",
                    system_prompt=prompt,
                    user_payload={
                        "display_name": display_name,
                        "attachment_kind": attachment_kind,
                        "text": text[:8000],
                    },
                )
                summary = str(response.get("summary") or "").strip()
                if summary:
                    return summary[:240]
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return f"{display_name} 暂时没有提取到可用文本。"
        if attachment_kind == "resume":
            prefix = "这份简历主要包含"
        elif attachment_kind == "project":
            prefix = "这份项目说明主要包含"
        else:
            prefix = "这份文件主要包含"
        return f"{prefix}：{' / '.join(lines[:3])}"[:240]

    def _compose_attachment_aware_answer(
        self,
        *,
        answer: str,
        attachments: list[ChatAttachmentResult],
    ) -> str:
        """Ensure answers with uploaded files first explain what the files mainly say."""

        if not attachments:
            return answer

        successful_attachments = [
            attachment for attachment in attachments if not attachment.processing_error
        ]
        failed_attachments = [
            attachment for attachment in attachments if attachment.processing_error
        ]

        summary_lines = [
            f"- {attachment.display_name}：{attachment.summary}"
            for attachment in successful_attachments
        ]
        failure_lines = [
            f"- {attachment.display_name}：{attachment.processing_error}"
            for attachment in failed_attachments
        ]

        blocks: list[str] = []
        if summary_lines:
            blocks.append(
                "你上传的文件主要讲了这些内容：\n"
                f"{chr(10).join(summary_lines)}"
            )
        if failure_lines:
            blocks.append(
                "以下附件这次没有成功解析：\n"
                f"{chr(10).join(failure_lines)}"
            )
        blocks.append("结合这些文件内容，我的建议是：\n" f"{answer}")
        return "\n\n".join(blocks)

    def _merge_profile_from_chat_signals(
        self,
        *,
        profile: ProfileMemory,
        texts: list[str],
        query_analysis: QueryAnalysis,
    ) -> tuple[ProfileMemory, list[str], list[str]]:
        """Merge low-risk profile fields from chat phrasing and attachments."""

        changed_fields: list[str] = []
        notes: list[str] = []
        updates: dict[str, Any] = {}
        combined_text = "\n".join(texts)

        if any(hint in query_analysis.profile_update_hints for hint in ("target_roles", "projects")):
            roles = self._extract_role_candidates(combined_text)
            merged_roles, changed = self._merge_unique_strings(profile.target_roles, roles, limit=12)
            if changed:
                updates["target_roles"] = merged_roles
                changed_fields.append("target_roles")
                notes.append(f"补充目标岗位：{', '.join(roles[:4])}。")

        if any(hint in query_analysis.profile_update_hints for hint in ("skills", "resume_snapshot", "projects")):
            skills = self._extract_skill_candidates(combined_text)
            merged_skills, changed = self._merge_unique_strings(profile.skills, skills, limit=20)
            if changed:
                updates["skills"] = merged_skills
                changed_fields.append("skills")
                notes.append(f"补充技能关键词：{', '.join(skills[:6])}。")

        if "location_preferences" in query_analysis.profile_update_hints:
            locations = self._extract_location_candidates(combined_text)
            merged_locations, changed = self._merge_unique_strings(
                profile.location_preferences,
                locations,
                limit=12,
            )
            if changed:
                updates["location_preferences"] = merged_locations
                changed_fields.append("location_preferences")
                notes.append(f"补充地点偏好：{', '.join(locations[:4])}。")

        if "persona_keywords" in query_analysis.profile_update_hints:
            persona_keywords = self._extract_persona_keywords(combined_text, query_analysis)
            merged_keywords, changed = self._merge_unique_strings(
                profile.persona_keywords,
                persona_keywords,
                limit=16,
            )
            if changed:
                updates["persona_keywords"] = merged_keywords
                changed_fields.append("persona_keywords")
                notes.append(f"记录用户自述关键词：{', '.join(persona_keywords[:5])}。")

        if not updates:
            return profile, [], []
        updates["updated_at"] = now_in_project_timezone()
        return profile.model_copy(update=updates), changed_fields, notes

    def _merge_career_from_chat_signals(
        self,
        *,
        career_state: CareerStateMemory,
        texts: list[str],
        query_analysis: QueryAnalysis,
    ) -> tuple[CareerStateMemory, list[str], list[str]]:
        """Merge low-risk dynamic career-state hints from chat turns."""

        changed_fields: list[str] = []
        notes: list[str] = []
        updates: dict[str, Any] = {}
        combined_text = "\n".join(texts)

        if "watched_companies" in query_analysis.career_update_hints:
            companies = self._extract_company_candidates(combined_text)
            merged_companies, changed = self._merge_unique_strings(
                career_state.watched_companies,
                companies,
                limit=16,
            )
            if changed:
                updates["watched_companies"] = merged_companies
                changed_fields.append("watched_companies")
                notes.append(f"补充重点关注公司：{', '.join(companies[:4])}。")

        if "active_priorities" in query_analysis.career_update_hints:
            priority_label = CHAT_INTENT_PRIORITY_LABELS.get(query_analysis.intent)
            priorities = [priority_label] if priority_label else []
            merged_priorities, changed = self._merge_unique_strings(
                career_state.active_priorities,
                priorities,
                limit=12,
            )
            if changed:
                updates["active_priorities"] = merged_priorities
                changed_fields.append("active_priorities")
                notes.append(f"更新当前优先级：{priority_label}。")

        if not updates:
            return career_state, [], []
        updates["updated_at"] = now_in_project_timezone()
        return career_state.model_copy(update=updates), changed_fields, notes

    def _merge_unique_strings(
        self,
        existing: list[str],
        candidates: list[str],
        *,
        limit: int,
    ) -> tuple[list[str], bool]:
        """Append unique normalized strings while preserving original order."""

        merged = list(existing)
        seen = {value.strip().lower() for value in existing if value.strip()}
        changed = False
        for candidate in candidates:
            cleaned = candidate.strip()
            if not cleaned:
                continue
            normalized = cleaned.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            merged.append(cleaned)
            changed = True
            if len(merged) >= limit:
                break
        return merged, changed

    def _extract_role_candidates(self, text: str) -> list[str]:
        """Extract role-like phrases from free-form chat and resume text."""

        matches = re.findall(
            r"([A-Za-z0-9+\-/#.\u4e00-\u9fff]{1,18}(?:工程师|开发|研发|产品经理|算法|分析师|设计师|运营|研究员|实习生))",
            text,
        )
        return list(dict.fromkeys(match.strip() for match in matches if len(match.strip()) >= 2))[:8]

    def _extract_skill_candidates(self, text: str) -> list[str]:
        """Extract a compact skill list from known engineering terms."""

        lowered = text.lower()
        found: list[str] = []
        for skill in KNOWN_SKILL_TERMS:
            if skill.lower() in lowered:
                found.append(skill)
        return list(dict.fromkeys(found))[:10]

    def _extract_location_candidates(self, text: str) -> list[str]:
        """Extract location preferences from one chat turn."""

        found = [location for location in KNOWN_LOCATION_TERMS if location in text]
        return list(dict.fromkeys(found))[:6]

    def _extract_company_candidates(self, text: str) -> list[str]:
        """Extract company-like names from user questions and attachments."""

        matches = [
            match.group(1).strip()
            for match in ORG_SUFFIX_PATTERN.finditer(text)
        ]
        short_names = re.findall(r"(阿里云|钉钉|夸克|高德|淘天|腾讯|字节跳动|美团|小红书|百度|华为)", text)
        return list(dict.fromkeys([*matches, *short_names]))[:8]

    def _extract_persona_keywords(
        self,
        text: str,
        query_analysis: QueryAnalysis,
    ) -> list[str]:
        """Extract compact self-description keywords that can help future chat retrieval."""

        keywords: list[str] = []
        keywords.extend(query_analysis.search_hints)
        keywords.extend(self._extract_role_candidates(text))
        keywords.extend(self._extract_skill_candidates(text))
        return list(dict.fromkeys(keyword for keyword in keywords if len(keyword) >= 2))[:8]

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
        user_id: str,
        workspace_id: str | None,
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
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        for candidate in candidates:
            url = str(candidate.get("url") or "").strip()
            title = str(candidate.get("title") or "").strip()
            snippet = str(candidate.get("snippet") or "").strip()
            if not url or not title:
                continue
            title_key = re.sub(r"\s+", " ", title).strip().lower()
            if url in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(title_key)
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

        llm_rank_payload = self._rank_market_titles_with_llm(
            source_url=source_url,
            candidates=ranked,
            user_id=user_id,
            workspace_id=workspace_id,
            profile_terms=profile_terms,
            keyword_terms=keyword_terms,
        )
        if llm_rank_payload:
            llm_by_url = {
                str(item.get("url") or "").strip(): item
                for item in llm_rank_payload
                if str(item.get("url") or "").strip()
            }
            reranked: list[MarketArticleCandidate] = []
            for candidate in ranked:
                llm_item = llm_by_url.get(candidate.url)
                if not llm_item:
                    reranked.append(candidate)
                    continue
                llm_score = self._coerce_score(llm_item.get("llm_score"), candidate.llm_score)
                brief = str(llm_item.get("brief") or "").strip() or candidate.brief
                reason = str(llm_item.get("reason") or "").strip() or candidate.reason
                title_score = round(
                    min(
                        0.48 * llm_score
                        + 0.32 * candidate.relevance_score
                        + 0.15 * candidate.market_value_score
                        + 0.05 * min(candidate.diversity_gap_score, 0.7),
                        0.99,
                    ),
                    4,
                )
                reranked.append(
                    replace(
                        candidate,
                        llm_score=round(llm_score, 4),
                        title_score=title_score,
                        brief=brief[:36],
                        reason=reason,
                        selection_mode="llm_keyword_blend",
                    )
                )
            ranked = reranked

        ranked.sort(key=lambda item: item.title_score, reverse=True)
        return ranked

    def _rank_market_titles_with_llm(
        self,
        *,
        source_url: str,
        candidates: list[MarketArticleCandidate],
        user_id: str,
        workspace_id: str | None,
        profile_terms: list[str],
        keyword_terms: list[str],
    ) -> list[dict[str, Any]]:
        """Ask the configured LLM to score title-level candidates, with retrieval context."""

        if not candidates:
            return []

        route = self.dependencies.model_router.select("chat", "low")
        if not self.dependencies.llm_gateway.is_available(route):
            return []

        query_text = "\n".join(
            [
                f"来源：{source_url}",
                f"画像关注：{'、'.join(profile_terms[:10])}",
                "候选标题：",
                *[f"- {item.title} | {item.snippet[:120]}" for item in candidates[:24]],
            ]
        )
        try:
            prompt_references = collect_prompt_references(
                user_id=user_id,
                workspace_id=workspace_id,
                current_item_id=None,
                query_text=query_text,
                source_metadata={
                    "source_title": "market_watch_title_ranking",
                    "keyword_hints": keyword_terms[:12],
                    "market_watch": True,
                },
                workflow_repository=self.dependencies.workflow_repository,
                search_client=self.dependencies.search_client,
                embedding_gateway=self.dependencies.embedding_gateway,
                vector_store=self.dependencies.vector_store,
                embed_route="dashscope:embedding",
                category_hint=ContentCategory.GENERAL_UPDATE.value,
                limit=4,
            )
        except Exception:
            prompt_references = []

        try:
            prompt = self.dependencies.prompt_loader.load("market_watch_title_rank")
            response = self.dependencies.llm_gateway.complete_json(
                route=route,
                task_name="market_watch_title_rank",
                system_prompt=prompt,
                user_payload={
                    "source_url": source_url,
                    "profile_terms": profile_terms[:12],
                    "keyword_terms": keyword_terms[:18],
                    "prompt_references": [
                        reference.to_payload() for reference in prompt_references
                    ],
                    "items": [
                        {
                            "title": item.title,
                            "url": item.url,
                            "snippet": item.snippet[:500],
                            "keyword_score": item.relevance_score,
                            "market_value_score": item.market_value_score,
                            "published_at": item.published_at,
                            "candidate_source": item.candidate_source,
                        }
                        for item in candidates[:24]
                    ],
                },
            )
        except Exception:
            return []

        items = response.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _coerce_score(self, value: Any, fallback: float) -> float:
        """Normalize arbitrary LLM score output into the 0-1 range."""

        try:
            score = float(value)
        except (TypeError, ValueError):
            return fallback
        return max(0.0, min(score, 1.0))

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
                if source_site != article_url and not self._is_recent_market_article(
                    fallback_message_time, now
                ):
                    continue
                if not candidate_text:
                    candidate_text = self._build_market_candidate_fallback_text(
                        candidate=candidate,
                        published_at=fallback_message_time,
                    )

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
        actual_child_previews = list(
            dict.fromkeys(
                str(child_state.source_metadata.get("market_title_brief") or "").strip()
                for child_state in child_states
                if str(child_state.source_metadata.get("market_title_brief") or "").strip()
            )
        )

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
                if child_state.normalized_item.id in child_ids:
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

    def _build_job_group_overview_state(
        self,
        *,
        section: SubmissionSection,
        child_states: list[AgentState],
        shared_context: str,
        shared_exam_dates: list[datetime],
        next_shared_exam_date: datetime | None,
        keyword_hints: list[str],
        search_references: list[str],
        user_id: str,
        workspace_id: str | None,
        memory_write_mode: MemoryWriteMode,
        base_source_metadata: dict[str, Any],
        source_type_override: SourceType | None,
        source_ref_override: str | None,
    ) -> AgentState:
        """Create one overview card for a multi-role recruiting section."""

        child_titles = [
            child.render_card.summary_one_line
            for child in child_states
            if child.render_card is not None and child.render_card.summary_one_line
        ]
        overview_title = section.identity_tag or section.primary_unit or section.section_title
        source_ref = (
            source_ref_override
            or next(
                (
                    child.source_ref
                    for child in child_states
                    if child.source_ref
                ),
                section.urls[0] if section.urls else None,
            )
        )
        source_type = source_type_override or (SourceType.LINK if source_ref else SourceType.TEXT)
        state = self.ingest(
            raw_input=self._compose_job_group_overview_payload(
                section=section,
                child_states=child_states,
                shared_context=shared_context,
                keyword_hints=keyword_hints,
                search_references=search_references,
            ),
            source_type=source_type,
            user_id=user_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            memory_write_mode=memory_write_mode,
            source_metadata={
                **base_source_metadata,
                "source_title": overview_title,
                "source_kind": source_type.value,
                "job_group_kind": "overview",
                "job_child_previews": child_titles[:6],
                "child_role_count": len(child_states),
                "keyword_hints": keyword_hints,
                "search_references": search_references,
                "shared_context": shared_context,
                "shared_exam_dates": [value.isoformat() for value in shared_exam_dates],
                "next_shared_exam_date": next_shared_exam_date.isoformat() if next_shared_exam_date else None,
                "global_deadline": next_shared_exam_date.isoformat() if next_shared_exam_date else None,
                "section_title": section.section_title,
                "original_section_text": section.section_text,
                "semantic_tags": list(dict.fromkeys([*section.semantic_tags, "岗位合集"])),
                "relationship_tags": list(dict.fromkeys([*section.semantic_tags, "岗位合集"])),
                "relationship_family": section.relationship_family,
                "relationship_stage": section.relationship_stage,
                "primary_unit": section.primary_unit,
                "identity_tag": section.identity_tag,
                "job_group_child_titles": child_titles[:8],
                "job_group_child_categories": [
                    child.classified_category.value
                    for child in child_states
                    if child.classified_category is not None
                ],
            },
        )
        self._postprocess_job_group_state(
            state=state,
            section=section,
            child_states=child_states,
            overview_title=overview_title,
            child_previews=child_titles[:6],
        )
        parent_item_id = state.normalized_item.id if state.normalized_item is not None else None
        if parent_item_id:
            child_ids: list[str] = []
            for child_state in child_states:
                if child_state.normalized_item is None:
                    continue
                child_ids.append(child_state.normalized_item.id)
                child_state.source_metadata["job_group_kind"] = "role"
                child_state.source_metadata["job_parent_item_id"] = parent_item_id
                child_state.source_metadata["job_child_item_ids"] = []
                child_state.source_metadata["job_child_previews"] = []
                if child_state.render_card is not None:
                    child_state.render_card.job_group_kind = "role"
                    child_state.render_card.job_parent_item_id = parent_item_id
                    child_state.render_card.job_child_item_ids = []
                    child_state.render_card.job_child_previews = []
                self.dependencies.workflow_repository.save(child_state)
            state.source_metadata["job_child_item_ids"] = child_ids
            if state.render_card is not None:
                state.render_card.job_child_item_ids = child_ids
                state.render_card.job_child_previews = child_titles[:6]
        self.dependencies.workflow_repository.save(state)
        return state

    def _compose_job_group_overview_payload(
        self,
        *,
        section: SubmissionSection,
        child_states: list[AgentState],
        shared_context: str,
        keyword_hints: list[str],
        search_references: list[str],
    ) -> str:
        """Build one overview payload describing a multi-role recruiting section."""

        lines = [
            f"岗位合集主题：{section.identity_tag or section.primary_unit or section.section_title}",
            f"岗位数量：{len(child_states)}",
        ]
        if shared_context:
            lines.append(f"共享规则：{shared_context}")
        if keyword_hints:
            lines.append(f"关键词提示：{'、'.join(keyword_hints[:8])}")
        if search_references:
            lines.append("搜索参考：")
            lines.extend(search_references[:2])
        lines.append("岗位子项：")
        for child_state in child_states[:8]:
            child_summary = (
                child_state.render_card.summary_one_line
                if child_state.render_card is not None
                else child_state.normalized_item.source_title if child_state.normalized_item else None
            )
            if child_summary:
                lines.append(f"- {child_summary}")
        lines.append("原始片段：")
        lines.append(section.section_text[:2400])
        return "\n".join(lines)

    def _postprocess_job_group_state(
        self,
        *,
        state: AgentState,
        section: SubmissionSection,
        child_states: list[AgentState],
        overview_title: str,
        child_previews: list[str],
    ) -> None:
        """Normalize one grouped activity overview card for the activity list UI."""

        if state.normalized_item is None or state.render_card is None:
            return

        card = state.render_card
        dominant_category = self._dominant_activity_category(child_states)
        child_scores = [
            child.render_card.ai_score
            for child in child_states
            if child.render_card is not None and child.render_card.ai_score is not None
        ]
        child_ddls = sorted(
            [
                child.extracted_signal.ddl
                for child in child_states
                if child.extracted_signal is not None and child.extracted_signal.ddl is not None
            ]
        )
        child_companies = list(
            dict.fromkeys(
                child.extracted_signal.company
                for child in child_states
                if child.extracted_signal is not None and child.extracted_signal.company
            )
        )
        child_cities = list(
            dict.fromkeys(
                child.extracted_signal.city
                for child in child_states
                if child.extracted_signal is not None and child.extracted_signal.city
            )
        )
        overview_summary = f"{overview_title}（{len(child_states)}个岗位）"
        overview_advice = "建议先展开岗位列表，再按 DDL、匹配度和地点筛选优先投递顺序。"
        overview_tags = list(
            dict.fromkeys(
                [
                    "岗位合集",
                    *section.semantic_tags,
                    *child_companies[:2],
                    *child_cities[:2],
                ]
            )
        )[:8]

        card.content_category = dominant_category
        card.job_group_kind = "overview"
        card.job_parent_item_id = None
        card.job_child_item_ids = list(state.source_metadata.get("job_child_item_ids", []))
        card.job_child_previews = list(child_previews)
        card.summary_one_line = overview_summary
        card.company = child_companies[0] if len(child_companies) == 1 else section.primary_unit
        card.role = None
        card.city = child_cities[0] if len(child_cities) == 1 else None
        card.location_note = None if len(child_cities) <= 1 else "该合集包含多个岗位地点，请展开子卡查看。"
        card.ddl = child_ddls[0] if child_ddls else None
        card.ai_score = round(sum(child_scores) / len(child_scores), 4) if child_scores else card.ai_score
        card.insight_summary = f"识别到同一业务线下 {len(child_states)} 个岗位方向。"
        card.advice = overview_advice
        card.tags = overview_tags

        if state.extracted_signal is not None:
            state.extracted_signal.category = dominant_category
            state.extracted_signal.company = card.company
            state.extracted_signal.role = None
            state.extracted_signal.city = card.city
            state.extracted_signal.location_note = card.location_note
            state.extracted_signal.ddl = card.ddl
            state.extracted_signal.summary_one_line = overview_summary
            state.extracted_signal.tags = overview_tags

    def _dominant_activity_category(self, child_states: list[AgentState]) -> ContentCategory:
        """Pick the dominant activity category from grouped child cards."""

        counts: dict[ContentCategory, int] = {}
        for child_state in child_states:
            category = (
                child_state.extracted_signal.category
                if child_state.extracted_signal is not None
                else child_state.classified_category
            ) or ContentCategory.UNKNOWN
            counts[category] = counts.get(category, 0) + 1
        if not counts:
            return ContentCategory.UNKNOWN
        return max(counts.items(), key=lambda item: item[1])[0]

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
            article_title = str(state.source_metadata.get("market_article_title") or "").strip()
            card.summary_one_line = article_title or summary
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
        if self._is_non_section_action_title(line=line, header_title=header_title):
            return False
        if self._looks_like_inline_role_variant_title(line=line, header_title=header_title):
            return False
        return bool(
            "【" in line
            or (
                is_numbered_line
                and (
                    any(
                        keyword in line
                        for keyword in ("内推", "实习", "校招", "秋招", "春招", "社招", "招聘")
                    )
                    or self._looks_like_job_section_title(header_title)
                )
            )
        )

    def _looks_like_job_section_title(self, header_title: str) -> bool:
        """Return whether one numbered title looks like a real role/business card header."""

        normalized = self._clean_section_title(header_title)
        return bool(
            self._contains_role_keyword(normalized)
            or (
                any(separator in normalized for separator in ("-", "／", "/", "|"))
                and len(normalized) >= 4
            )
        )

    def _looks_like_inline_role_variant_title(self, *, line: str, header_title: str) -> bool:
        """Return whether one numbered line is only a child role bullet inside a section."""

        if "【" in line or URL_PATTERN.search(line):
            return False

        normalized = self._clean_section_title(header_title)
        if not normalized or len(normalized) > 24:
            return False
        if any(keyword in normalized for keyword in ("实习", "校招", "秋招", "春招", "社招", "招聘", "内推")):
            return False
        if not self._contains_role_keyword(normalized):
            return False

        if any(separator in normalized for separator in ("-", "／", "/", "|")):
            left = re.split(r"[-/／|]", normalized, maxsplit=1)[0].strip()
            if left and not self._contains_role_keyword(left):
                return False

        return True

    def _contains_role_keyword(self, text: str) -> bool:
        """Return whether a short phrase primarily looks like one role title."""

        return bool(
            re.search(
                r"(工程师|研究员|分析师|经理|运营|产品|设计师|开发|算法|测试|架构师|顾问|专家|实习生)",
                text,
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

    def _is_non_section_action_title(self, *, line: str, header_title: str) -> bool:
        """Return whether one numbered line is just an apply/action instruction."""

        normalized_title = self._normalize_submission_header_token(header_title)
        normalized_line = self._normalize_submission_header_token(line)

        if normalized_title in NON_SECTION_BRACKET_TITLES:
            return True
        if any(
            normalized_title.startswith(prefix) or normalized_line.startswith(prefix)
            for prefix in NON_SECTION_ACTION_PREFIXES
        ):
            return True
        return (
            ("http://" in line or "https://" in line)
            and any(keyword in line for keyword in ("链接", "投递", "申请", "内推码"))
        )

    def _normalize_submission_header_token(self, value: str) -> str:
        """Normalize one potential section title before header classification."""

        normalized = re.sub(r"[：:（(].*$", "", value).strip()
        normalized = re.sub(r"\s+", "", normalized)
        return normalized

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
            has_source_file=bool(state.source_metadata.get("archived_source_path")),
            source_file_name=(
                str(state.source_metadata.get("archived_source_name") or "").strip() or None
            ),
            source_file_path=(
                str(state.source_metadata.get("archived_source_path") or "").strip() or None
            ),
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
            job_group_kind=str(state.source_metadata.get("job_group_kind") or "") or None,
            job_parent_item_id=str(state.source_metadata.get("job_parent_item_id") or "") or None,
            job_child_item_ids=list(state.source_metadata.get("job_child_item_ids", [])),
            job_child_previews=list(state.source_metadata.get("job_child_previews", [])),
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
