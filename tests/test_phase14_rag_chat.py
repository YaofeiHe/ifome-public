"""Tests for Phase 14 grounded chat and RAG retrieval paths."""

from __future__ import annotations

import base64

from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.runtime.settings import AppSettings, FeatureFlags, LLMSettings, RAGSettings, ProviderSettings
from core.schemas import SourceType
from core.tools import NoopLLMGateway, OCRExtractionResult


class FakeEmbeddingGateway:
    """Deterministic embedding gateway for RAG tests."""

    def is_available(self, route: str) -> bool:
        return True

    def embed_texts(self, *, route: str, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    1.0 if "后端" in text or "backend" in lowered else 0.0,
                    1.0 if "面试" in text or "interview" in lowered else 0.0,
                    float(len(text) % 7) / 10.0,
                ]
            )
        return vectors


class FakeVectorStore:
    """In-memory vector store used to emulate Qdrant behavior in tests."""

    def __init__(self) -> None:
        self.points: dict[str, dict] = {}

    def is_available(self) -> bool:
        return True

    def ensure_collection(self, *, name: str, vector_size: int) -> None:
        return None

    def upsert_points(self, *, collection_name: str, points: list[dict]) -> None:
        for point in points:
            self.points[point["id"]] = point

    def query_points(
        self, *, collection_name: str, query_vector: list[float], limit: int
    ) -> list[dict]:
        scored = []
        for point in self.points.values():
            vector = point["vector"]
            score = sum(left * right for left, right in zip(vector, query_vector, strict=False))
            scored.append(
                {
                    "id": point["id"],
                    "score": score,
                    "payload": point["payload"],
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]


class FakeOCRClient:
    """OCR client used to emulate PDF preview OCR fallback."""

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def extract_text(self, image_path) -> OCRExtractionResult:
        self.calls += 1
        return OCRExtractionResult(
            text=(
                f"教育经历：XX 大学 第{self.calls}页\n"
                f"项目经历：RAG 求职助手 第{self.calls}页\n"
                "技能：Python FastAPI Agent"
            ),
            source_metadata={"ocr_engine": "fake_ocr", "ocr_route": "fake_ocr"},
        )


def test_chat_query_uses_local_rag_fallback_when_live_rag_disabled() -> None:
    """Chat should still return grounded citations when live RAG is not configured."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    services.ingest(
        raw_input="阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    answer, supporting_item_ids, citations, retrieval_mode = services.chat_query(
        query="今天该投什么",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert "今天建议先处理" in answer
    assert supporting_item_ids
    assert citations
    assert retrieval_mode == "local_hybrid"


def test_chat_query_uses_live_rag_when_embedding_and_vector_store_are_available() -> None:
    """Chat should use the live vector path when fake live dependencies are injected."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
            embedding_gateway=FakeEmbeddingGateway(),
            vector_store=FakeVectorStore(),
        ),
        settings=AppSettings(
            feature_flags=FeatureFlags(),
            llm=LLMSettings(),
            rag=RAGSettings(
                enable_live_rag=True,
                embedding=ProviderSettings(
                    api_key="demo-key",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    model="text-embedding-v4",
                ),
                qdrant_url="https://example.qdrant.tech",
                qdrant_api_key="demo-qdrant-key",
                collection_name="ifome_test_rag",
                query_limit=8,
                rerank_limit=4,
            ),
        ),
    )
    services.ingest(
        raw_input="阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月01日 18:00。",
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    answer, supporting_item_ids, citations, retrieval_mode = services.chat_query(
        query="这段JD和我匹配吗",
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    assert "目标方向" in answer or "目标岗位" in answer
    assert supporting_item_ids
    assert citations
    assert retrieval_mode == "live_qdrant_hybrid"


def test_chat_query_can_answer_from_memory_without_items() -> None:
    """Chat should still answer when only profile and career memory are available."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    answer, supporting_item_ids, citations, retrieval_mode = services.chat_query(
        query="我现在的求职重点是什么",
        user_id="demo_user",
        workspace_id="memory_only_workspace",
    )

    assert answer
    assert supporting_item_ids == []
    assert citations
    assert retrieval_mode == "local_hybrid"


def test_chat_query_unified_updates_resume_snapshot_from_attachment() -> None:
    """Resume-like chat attachments should be persisted into profile memory."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    result = services.chat_query_enhanced(
        query="帮我润色简历并准备面试自我介绍",
        user_id="demo_user",
        workspace_id="resume_chat_workspace",
        uploaded_files=[
            (
                "我的简历.txt",
                (
                    "姓名：张三\n"
                    "教育经历：XX 大学 计算机\n"
                    "项目经历：做过 RAG 求职助手\n"
                    "技能：Python FastAPI React RAG Agent\n"
                ).encode("utf-8"),
            )
        ],
        apply_memory_updates=True,
    )

    current_memory = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="resume_chat_workspace",
    )
    profile = current_memory["profile_memory"]

    assert result.memory_update.applied is True
    assert "resume_snapshot" in result.memory_update.profile_fields
    assert result.attachments
    assert result.attachments[0].summary
    assert result.answer.startswith("你上传的文件主要讲了这些内容：")
    assert profile.resume_snapshot is not None
    assert "RAG 求职助手" in profile.resume_snapshot.text
    assert profile.resume_snapshot.structured_profile is not None
    assert profile.resume_snapshot.structured_profile.sections


def test_chat_query_unified_updates_project_memory_from_attachment() -> None:
    """Project-like chat attachments should be persisted into long-term project memory."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    result = services.chat_query_enhanced(
        query="请基于这个项目帮我准备面试自我介绍",
        user_id="demo_user",
        workspace_id="project_chat_workspace",
        uploaded_files=[
            (
                "RAG求职助手项目说明.md",
                (
                    "RAG 求职助手\n"
                    "项目简介：统一处理岗位链接、聊天截图、简历和项目说明，并支持 grounded chat。\n"
                    "技术栈：Python FastAPI Next.js SQLite Qdrant\n"
                    "职责：负责工作流设计、RAG 检索和前后端联动。\n"
                    "亮点：支持聊天预处理、多路检索、项目画像和简历画像更新。\n"
                ).encode("utf-8"),
            )
        ],
        apply_memory_updates=True,
    )

    current_memory = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="project_chat_workspace",
    )
    profile = current_memory["profile_memory"]

    assert result.memory_update.applied is True
    assert "projects" in result.memory_update.profile_fields
    assert result.attachments
    assert result.attachments[0].attachment_kind == "project"
    assert profile.projects
    assert profile.projects[0].name
    assert profile.projects[0].summary
    assert profile.projects[0].source_file_name is not None


def test_chat_query_can_refresh_project_cards_from_saved_resume_snapshot() -> None:
    """An explicit chat request should rebuild project cards from the already saved resume snapshot."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    services.chat_query_enhanced(
        query="请先保存这份简历",
        user_id="demo_user",
        workspace_id="resume_project_workspace",
        uploaded_files=[
            (
                "我的简历.txt",
                (
                    "姓名：张三\n"
                    "教育经历：XX 大学 计算机\n"
                    "项目经历\n"
                    "RAG 求职助手\n"
                    "负责统一处理岗位链接、聊天截图、简历与项目说明。\n"
                    "技术栈：Python FastAPI Next.js Qdrant\n"
                    "项目经历\n"
                    "Agent 工作流控制台\n"
                    "负责工作流编排、状态传递和卡片渲染。\n"
                ).encode("utf-8"),
            )
        ],
        apply_memory_updates=True,
    )

    result = services.chat_query_enhanced(
        query="请用简历更新项目画像",
        user_id="demo_user",
        workspace_id="resume_project_workspace",
        apply_memory_updates=True,
    )

    current_memory = services.dependencies.memory_provider.load(
        user_id="demo_user",
        workspace_id="resume_project_workspace",
    )
    profile = current_memory["profile_memory"]

    assert result.memory_update.applied is True
    assert "projects" in result.memory_update.profile_fields
    assert profile.projects
    assert any(project.name for project in profile.projects)


def test_pdf_attachment_falls_back_to_ocr_when_text_extraction_fails(tmp_path) -> None:
    """PDF attachments should fallback to OCR instead of failing fast."""

    fake_ocr = FakeOCRClient()
    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
            ocr_client=fake_ocr,
        )
    )

    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")
    preview_path_1 = tmp_path / "resume_page_1.png"
    preview_path_1.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnSUs8AAAAASUVORK5CYII="
        )
    )
    preview_path_2 = tmp_path / "resume_page_2.png"
    preview_path_2.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnSUs8AAAAASUVORK5CYII="
        )
    )

    def fail_extract_text(_file_path):
        raise RuntimeError("PDF resume.pdf 暂时没有提取到文字，可能是扫描版 PDF。")

    services.dependencies.document_text_extractor.extract_text = fail_extract_text
    services._render_pdf_preview_images = lambda _file_path: [preview_path_1, preview_path_2]

    attachment = services._extract_attachment_from_upload(
        file_name="resume.pdf",
        file_bytes=b"%PDF-1.4 fake pdf",
    )

    assert attachment.extraction_kind == "pdf_preview_ocr_multi_page"
    assert "[第 1 页]" in attachment.text
    assert "[第 2 页]" in attachment.text
    assert fake_ocr.calls == 2


def test_pdf_preview_renderer_falls_back_to_swift_when_appkit_bridge_is_unavailable(tmp_path) -> None:
    """PDF preview rendering should still work when the Python AppKit bridge is unavailable."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    preview_path = tmp_path / "resume_page_1.png"
    preview_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnSUs8AAAAASUVORK5CYII="
        )
    )

    services._render_pdf_preview_images_with_appkit = lambda _file_path: (_ for _ in ()).throw(
        RuntimeError("当前环境缺少 Python AppKit 桥接。")
    )
    services._render_pdf_preview_images_with_swift = lambda _file_path: [preview_path]

    rendered = services._render_pdf_preview_images(tmp_path / "resume.pdf")

    assert rendered == [preview_path]


def test_chat_query_keeps_responding_when_attachment_extraction_fails() -> None:
    """Attachment extraction failures should be surfaced in diagnostics without a hard 400."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    def fail_extract(*, file_name: str, file_bytes: bytes):
        raise RuntimeError(f"文件 {file_name} 暂时无法解析，请尝试导出为文本型 PDF。")

    services._extract_attachment_from_upload = fail_extract

    result = services.chat_query_enhanced(
        query="请先看看这份简历",
        user_id="demo_user",
        workspace_id="resume_failure_workspace",
        uploaded_files=[("broken_resume.pdf", b"fake bytes")],
        apply_memory_updates=True,
    )

    assert result.answer
    assert result.attachments
    assert result.attachments[0].processing_error is not None
    assert "broken_resume.pdf" in result.answer


def test_chat_query_expands_sparse_job_listing_requests_into_name_and_link_answers() -> None:
    """Sparse job-listing queries should be rewritten and still return grounded links."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )
    services.ingest(
        raw_input="阿里云招聘 AI 应用工程师，负责 Agent 与 RAG 系统开发。",
        source_type=SourceType.TEXT,
        source_ref="https://jobs.example.com/alibaba-ai-agent",
        user_id="demo_user",
        workspace_id="job_link_workspace",
    )
    services.ingest(
        raw_input="字节跳动招聘 后端工程师，负责模型平台与服务治理。",
        source_type=SourceType.TEXT,
        source_ref="https://jobs.example.com/bytedance-backend",
        user_id="demo_user",
        workspace_id="job_link_workspace",
    )

    result = services.chat_query_enhanced(
        query="请给我所有待投递岗位的名称与链接",
        user_id="demo_user",
        workspace_id="job_link_workspace",
    )

    assert result.query_analysis.rewritten_query
    assert result.query_analysis.retrieval_queries
    assert "https://jobs.example.com/" in result.answer


def test_chat_session_summary_falls_back_without_live_llm() -> None:
    """Archived chat conversations should still get deterministic summary metadata locally."""

    services = ApiServiceContainer(
        dependencies=WorkflowDependencies(
            llm_gateway=NoopLLMGateway(),
        )
    )

    result = services.summarize_chat_session(
        mode="boss_simulator",
        conversation_title="阿里沟通",
        turns=[
            {
                "mode": "boss_simulator",
                "user_message": "您好，这周可以安排一轮沟通吗？",
                "answer": "可以的，我周三和周四下午都可以。",
                "strategy": "先给出明确可约时间，降低来回确认成本。",
            },
            {
                "mode": "boss_simulator",
                "user_message": "方便再发一下你的简历和项目介绍吗？",
                "answer": "好的，我现在把简历和项目说明一并发您，也补充一下我的 Agent 项目重点。",
                "strategy": "顺势补充项目亮点，让后续面试官更容易抓到重点。",
            },
        ],
    )

    assert result.title
    assert result.summary
    assert result.keywords
    assert "最近窗口" in result.compressed_transcript
