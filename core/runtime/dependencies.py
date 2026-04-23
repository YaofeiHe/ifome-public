"""Default runtime dependencies used by the step-3 workflow scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.reminders.queue import ReminderQueue
from core.runtime.interfaces import (
    EmbeddingGateway,
    LLMGateway,
    MemoryProvider,
    ModelRouter,
    SearchClient,
    TraceLogger,
    VectorStore,
)
from core.runtime.settings import AppSettings
from core.runtime.time import now_in_project_timezone
from core.schemas import CareerStateMemory, ProfileMemory
from core.storage.sqlite_memory import SQLiteMemoryProvider
from core.storage.sqlite_reminders import SQLiteReminderRepository
from core.storage.sqlite_workflows import SQLiteWorkflowRepository
from core.tools import (
    CalendarClient,
    EmailClient,
    LocalTesseractOCRClient,
    NoopEmbeddingGateway,
    NoopLLMGateway,
    NoopSearchClient,
    NoopVectorStore,
    OpenAICompatibleEmbeddingGateway,
    OpenAICompatibleLLMGateway,
    PromptLoader,
    QdrantRESTVectorStore,
    WebPageClient,
    WebSearchClient,
    WebPushClient,
)


class StaticModelRouter(ModelRouter):
    """
    Minimal model router used before real provider integration.

    The router records intended provider choices so the workflow can already
    expose cost-control decisions before any live API key is required.
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings.from_env()

    def select(self, task_type: str, complexity: str) -> str:
        """Return the provider route chosen for a specific task."""

        if complexity == "high":
            if self.settings.llm.enable_openai_routing:
                return "openai:gpt-5.4"
            return "dashscope:qwen-primary"
        if task_type == "embed":
            return "dashscope:text-embedding-v4"
        return "dashscope:qwen-primary"


class InMemoryMemoryProvider(MemoryProvider):
    """
    In-memory memory provider seeded with project-default profile examples.

    This matches the POC goal: keep memory explicit and inspectable without
    forcing external storage before the main workflow is visible.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str | None], dict[str, Any]] = {}

    def load(self, user_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        """Load or initialize profile and career memories for one user scope."""

        key = (user_id, workspace_id)
        if key not in self._store:
            self._store[key] = build_seed_memory_payload(user_id, workspace_id)
        return self._store[key]

    def save(self, payload: dict[str, Any]) -> None:
        """Persist memory data back into the in-memory store."""

        user_id = payload["user_id"]
        workspace_id = payload.get("workspace_id")
        self._store[(user_id, workspace_id)] = payload


class InMemoryTraceLogger(TraceLogger):
    """Collect structured trace events in memory during local execution."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        """Record an info-level event."""

        self.events.append({"level": "INFO", "event": event, **kwargs})

    def warning(self, event: str, **kwargs: Any) -> None:
        """Record a warning-level event."""

        self.events.append({"level": "WARNING", "event": event, **kwargs})

    def error(self, event: str, **kwargs: Any) -> None:
        """Record an error-level event."""

        self.events.append({"level": "ERROR", "event": event, **kwargs})


def build_default_llm_gateway() -> LLMGateway:
    """Create the live LLM gateway from environment-backed runtime settings."""

    settings = AppSettings.from_env()
    if settings.llm.enable_live_llm:
        return OpenAICompatibleLLMGateway(settings.llm)
    return NoopLLMGateway()


def build_default_model_router() -> ModelRouter:
    """Create the model router from current runtime settings."""

    return StaticModelRouter(AppSettings.from_env())


def build_default_embedding_gateway() -> EmbeddingGateway:
    """Create the embedding gateway from current runtime settings."""

    settings = AppSettings.from_env()
    if settings.rag.enable_live_rag:
        return OpenAICompatibleEmbeddingGateway(settings.rag)
    return NoopEmbeddingGateway()


def build_default_vector_store() -> VectorStore:
    """Create the vector store client from current runtime settings."""

    settings = AppSettings.from_env()
    if settings.rag.enable_live_rag:
        return QdrantRESTVectorStore(settings.rag)
    return NoopVectorStore()


def build_default_search_client() -> SearchClient:
    """Create the default web search client used for keyword discovery."""

    settings = AppSettings.from_env()
    if settings.llm.enable_live_llm or settings.rag.enable_live_rag:
        return WebSearchClient()
    return NoopSearchClient()


def build_seed_memory_payload(user_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    """Create the default memory payload used by local POC storage backends."""

    return {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "profile_memory": ProfileMemory(
            user_id=user_id,
            workspace_id=workspace_id,
            target_roles=[
                "AI 应用工程师",
                "智能体平台工程师",
                "LLM 应用后端",
                "AI 搜索工程师",
                "RAG/知识库工程师",
            ],
            priority_domains=[
                "AI 大模型工程化",
                "企业级 agent 平台",
                "办公 agent",
                "编程 agent",
                "AI 搜索与信息助手",
                "本地生活与旅行 agent",
                "电商经营与客服 agent",
                "产业与医疗 agent",
                "智能驾驶",
            ],
            skills=["Python", "FastAPI", "RAG", "Agent", "MCP", "评测", "工作流编排"],
            location_preferences=["上海", "杭州", "北京", "远程"],
            summary=(
                "默认求职画像：重点关注 AI agent 工程化应用，不局限于智能驾驶，"
                "同时覆盖企业级智能体平台、办公 agent、编程 agent、搜索助手与电商 agent。"
            ),
            updated_at=now_in_project_timezone(),
        ),
        "career_state_memory": CareerStateMemory(
            user_id=user_id,
            workspace_id=workspace_id,
            watched_companies=["阿里云", "钉钉", "夸克", "高德", "淘天"],
            market_watch_sources=[
                "https://www.jiqizhixin.com/",
                "https://www.qbitai.com/",
            ],
            market_article_fetch_limit=5,
            today_focus=["筛选高匹配岗位", "跟进 AI agent 工程化方向的市场信号"],
            active_priorities=["高匹配岗位优先投递", "重要时间点不遗漏", "持续更新市场信息"],
            notes="默认 career state：重点关注 AI agent 工程化相关岗位与市场动态。",
            updated_at=now_in_project_timezone(),
        ),
    }


@dataclass
class WorkflowDependencies:
    """Shared dependency bundle passed into workflow nodes."""

    model_router: ModelRouter = field(default_factory=build_default_model_router)
    memory_provider: MemoryProvider = field(
        default_factory=lambda: SQLiteMemoryProvider(
            Path("data/runtime/memory.sqlite3"),
            default_payload_factory=build_seed_memory_payload,
        )
    )
    trace_logger: TraceLogger = field(default_factory=InMemoryTraceLogger)
    workflow_repository: SQLiteWorkflowRepository = field(
        default_factory=lambda: SQLiteWorkflowRepository(
            Path("data/runtime/workflows.sqlite3")
        )
    )
    reminder_queue: ReminderQueue = field(
        default_factory=lambda: ReminderQueue(
            SQLiteReminderRepository(Path("data/runtime/reminders.sqlite3"))
        )
    )
    embedding_gateway: EmbeddingGateway = field(default_factory=build_default_embedding_gateway)
    vector_store: VectorStore = field(default_factory=build_default_vector_store)
    llm_gateway: LLMGateway = field(default_factory=build_default_llm_gateway)
    prompt_loader: PromptLoader = field(default_factory=PromptLoader)
    web_page_client: WebPageClient = field(default_factory=WebPageClient)
    search_client: SearchClient = field(default_factory=build_default_search_client)
    ocr_client: LocalTesseractOCRClient = field(default_factory=LocalTesseractOCRClient)
    email_client: EmailClient = field(default_factory=EmailClient)
    calendar_client: CalendarClient = field(default_factory=CalendarClient)
    web_push_client: WebPushClient = field(default_factory=WebPushClient)
