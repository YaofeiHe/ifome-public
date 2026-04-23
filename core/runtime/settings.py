"""Runtime settings and feature flags."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.runtime.env import load_local_env

load_local_env()


def _read_bool_env(name: str, default: bool = False) -> bool:
    """Parse a boolean-like environment variable using conservative defaults."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    """Parse an integer environment variable using a safe fallback."""

    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _read_csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into a tuple of strings."""

    value = os.getenv(name)
    if value is None:
        return default
    items = [item.strip() for item in value.split(",")]
    return tuple(item for item in items if item)


@dataclass(frozen=True)
class FeatureFlags:
    """Feature flags controlling optional and removable modules."""

    enable_project_self_memory: bool = False


@dataclass(frozen=True)
class ProviderSettings:
    """Provider-specific connection settings for one live model backend."""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    fallback_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class LLMSettings:
    """Settings used by the optional live LLM adapter layer."""

    enable_live_llm: bool = False
    enable_openai_routing: bool = False
    request_timeout_seconds: int = 30
    dashscope: ProviderSettings = ProviderSettings()
    openai: ProviderSettings = ProviderSettings()
    deepseek: ProviderSettings = ProviderSettings()


@dataclass(frozen=True)
class RAGSettings:
    """Settings used by the optional RAG retrieval and answer-generation layer."""

    enable_live_rag: bool = False
    embedding: ProviderSettings = ProviderSettings()
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    collection_name: str = "ifome_rag"
    query_limit: int = 8
    rerank_limit: int = 4


@dataclass(frozen=True)
class AppSettings:
    """
    Application settings assembled from environment variables.

    Responsibilities:
    - Centralize runtime flags used by API and auxiliary services.
    - Keep removable experimental behavior behind explicit configuration.
    """

    feature_flags: FeatureFlags
    llm: LLMSettings = LLMSettings()
    rag: RAGSettings = RAGSettings()

    @classmethod
    def from_env(cls) -> "AppSettings":
        """Build settings from environment variables."""

        return cls(
            feature_flags=FeatureFlags(
                enable_project_self_memory=_read_bool_env(
                    "ENABLE_PROJECT_SELF_MEMORY", default=False
                )
            ),
            llm=LLMSettings(
                enable_live_llm=_read_bool_env("ENABLE_LIVE_LLM", default=False),
                enable_openai_routing=_read_bool_env(
                    "ENABLE_OPENAI_ROUTING", default=False
                ),
                request_timeout_seconds=_read_int_env("LLM_REQUEST_TIMEOUT_SECONDS", 30),
                dashscope=ProviderSettings(
                    api_key=os.getenv("DASHSCOPE_API_KEY"),
                    base_url=os.getenv(
                        "DASHSCOPE_BASE_URL",
                        "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    ),
                    model=os.getenv("DASHSCOPE_CHAT_MODEL", "qwen-plus"),
                    fallback_models=_read_csv_env(
                        "DASHSCOPE_FALLBACK_MODELS",
                        default=("qwen-turbo", "qwen-flash"),
                    ),
                ),
                openai=ProviderSettings(
                    api_key=os.getenv("OPENAI_API_KEY"),
                    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                    model=os.getenv("OPENAI_REASONING_MODEL", "gpt-5.4"),
                ),
                deepseek=ProviderSettings(
                    api_key=os.getenv("DEEPSEEK_API_KEY"),
                    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                    model=os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat"),
                ),
            ),
            rag=RAGSettings(
                enable_live_rag=_read_bool_env("ENABLE_LIVE_RAG", default=False),
                embedding=ProviderSettings(
                    api_key=os.getenv("DASHSCOPE_API_KEY"),
                    base_url=os.getenv(
                        "DASHSCOPE_BASE_URL",
                        "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    ),
                    model=os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v4"),
                ),
                qdrant_url=os.getenv("QDRANT_URL"),
                qdrant_api_key=os.getenv("QDRANT_API_KEY"),
                collection_name=os.getenv("QDRANT_COLLECTION", "ifome_rag"),
                query_limit=_read_int_env("RAG_QUERY_LIMIT", 8),
                rerank_limit=_read_int_env("RAG_RERANK_LIMIT", 4),
            ),
        )
