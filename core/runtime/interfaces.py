"""Framework-agnostic runtime contracts for future migration away from LangGraph."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class BaseState(BaseModel):
    """
    Minimal state contract shared by workflow nodes.

    The state object stays explicit so the project never depends on hidden
    framework context. Every future schema can extend this base model.
    """

    model_config = ConfigDict(protected_namespaces=())

    trace_id: str = Field(description="Trace identifier for observability.")
    user_id: str = Field(description="Logical user identifier.")
    workspace_id: str | None = Field(
        default=None,
        description="Workspace or tenant scope reserved for multi-user support.",
    )


class BaseNode(Protocol):
    """
    Execution contract for a workflow node.

    Each node reads part of the state and returns an updated state. Concrete
    nodes can be backed by LangGraph first and later by a custom runtime.
    """

    name: str

    def run(self, state: BaseState) -> BaseState:
        """Execute the node and return the updated state."""


class ToolDispatcher(Protocol):
    """Resolve and execute tool calls behind a stable interface."""

    def invoke(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a named tool and return a normalized result payload."""


class MemoryProvider(Protocol):
    """Read and write long-term or short-term memory through one abstraction."""

    def load(self, user_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        """Load memory state for a logical user scope."""

    def save(self, payload: dict[str, Any]) -> None:
        """Persist a normalized memory payload."""


class TraceLogger(Protocol):
    """Structured observability contract used by API, graph, and tools."""

    def info(self, event: str, **kwargs: Any) -> None:
        """Log a successful event."""

    def warning(self, event: str, **kwargs: Any) -> None:
        """Log a degraded event."""

    def error(self, event: str, **kwargs: Any) -> None:
        """Log a failed event."""


class ModelRouter(Protocol):
    """Select a model based on task type, complexity, and cost constraints."""

    def select(self, task_type: str, complexity: str) -> str:
        """Return the model identifier chosen for a specific task."""


class LLMGateway(Protocol):
    """Stable interface for live LLM calls behind workflow nodes."""

    def is_available(self, route: str) -> bool:
        """Return whether a live model route is configured and callable."""

    def complete_json(
        self,
        *,
        route: str,
        task_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one structured generation call and return parsed JSON."""


class EmbeddingGateway(Protocol):
    """Stable interface for embedding generation used by RAG indexing and search."""

    def is_available(self, route: str) -> bool:
        """Return whether a live embedding route is configured and callable."""

    def embed_texts(self, *, route: str, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for one batch of texts."""


class VectorStore(Protocol):
    """Stable interface for vector indexing and semantic retrieval."""

    def is_available(self) -> bool:
        """Return whether the vector store is configured for live use."""

    def ensure_collection(self, *, name: str, vector_size: int) -> None:
        """Create the target collection if needed."""

    def upsert_points(self, *, collection_name: str, points: list[dict[str, Any]]) -> None:
        """Insert or update a batch of vector points."""

    def query_points(
        self, *, collection_name: str, query_vector: list[float], limit: int
    ) -> list[dict[str, Any]]:
        """Return the top matching points for one vector query."""


class SearchClient(Protocol):
    """Stable interface for one-shot web search used in keyword expansion."""

    def search(self, *, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return normalized search snippets for one query."""
