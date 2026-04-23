"""Tests for Phase 14 grounded chat and RAG retrieval paths."""

from __future__ import annotations

from apps.api.src.services import ApiServiceContainer
from core.runtime.dependencies import WorkflowDependencies
from core.runtime.settings import AppSettings, FeatureFlags, LLMSettings, RAGSettings, ProviderSettings
from core.schemas import SourceType
from core.tools import NoopLLMGateway


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
