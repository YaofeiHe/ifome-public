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


def _coalesce_value(*values: str | None) -> str | None:
    """Return the first non-empty string-like value."""

    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


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
class OCRSettings:
    """Settings used by the independent OCR model route."""

    enabled: bool = False
    provider_label: str = "Qwen-VL-OCR"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    request_timeout_seconds: int = 60


@dataclass(frozen=True)
class RuntimeProviderOverrides:
    """User-managed local overrides for one OpenAI-compatible provider."""

    enabled: bool | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    fallback_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeOCROverrides:
    """User-managed local overrides for OCR model configuration."""

    enabled: bool | None = None
    provider_label: str = "Qwen-VL-OCR"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    request_timeout_seconds: int | None = None


@dataclass(frozen=True)
class SourceFileSettings:
    """Settings used by archived source-file retention and cleanup."""

    max_age_days: int = 30
    max_total_size_mb: int = 2048
    delete_when_item_deleted: bool = True
    filter_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeSourceFileOverrides:
    """User-managed local overrides for source file management."""

    max_age_days: int | None = None
    max_total_size_mb: int | None = None
    delete_when_item_deleted: bool | None = None
    filter_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeSettingsOverrides:
    """Local runtime settings persisted outside long-term memory."""

    llm: RuntimeProviderOverrides = RuntimeProviderOverrides()
    ocr: RuntimeOCROverrides = RuntimeOCROverrides()
    source_files: RuntimeSourceFileOverrides = RuntimeSourceFileOverrides()
    llm_request_timeout_seconds: int | None = None


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
    ocr: OCRSettings = OCRSettings()
    source_files: SourceFileSettings = SourceFileSettings()

    @classmethod
    def from_env(
        cls,
        runtime_overrides: RuntimeSettingsOverrides | None = None,
    ) -> "AppSettings":
        """Build settings from environment variables."""

        runtime_overrides = runtime_overrides or RuntimeSettingsOverrides()
        llm_enabled = (
            runtime_overrides.llm.enabled
            if runtime_overrides.llm.enabled is not None
            else _read_bool_env("ENABLE_LIVE_LLM", default=False)
        )
        llm_api_key = _coalesce_value(
            runtime_overrides.llm.api_key,
            os.getenv("DASHSCOPE_API_KEY"),
        )
        llm_base_url = _coalesce_value(
            runtime_overrides.llm.base_url,
            os.getenv(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
        llm_model = _coalesce_value(
            runtime_overrides.llm.model,
            os.getenv("DASHSCOPE_CHAT_MODEL", "qwen-plus"),
        )
        llm_fallback_models = (
            runtime_overrides.llm.fallback_models
            if runtime_overrides.llm.fallback_models
            else _read_csv_env(
                "DASHSCOPE_FALLBACK_MODELS",
                default=("qwen-turbo", "qwen-flash"),
            )
        )
        llm_request_timeout_seconds = (
            runtime_overrides.llm_request_timeout_seconds
            if runtime_overrides.llm_request_timeout_seconds is not None
            else _read_int_env("LLM_REQUEST_TIMEOUT_SECONDS", 30)
        )
        ocr_enabled = (
            runtime_overrides.ocr.enabled
            if runtime_overrides.ocr.enabled is not None
            else _read_bool_env("ENABLE_QWEN_VL_OCR", default=False)
        )
        ocr_api_key = _coalesce_value(
            runtime_overrides.ocr.api_key,
            os.getenv("QWEN_VL_OCR_API_KEY"),
        )
        ocr_base_url = _coalesce_value(
            runtime_overrides.ocr.base_url,
            os.getenv(
                "QWEN_VL_OCR_BASE_URL",
                os.getenv(
                    "DASHSCOPE_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
            ),
        )
        ocr_model = _coalesce_value(
            runtime_overrides.ocr.model,
            os.getenv("QWEN_VL_OCR_MODEL", "qwen-vl-ocr"),
        )

        return cls(
            feature_flags=FeatureFlags(
                enable_project_self_memory=_read_bool_env(
                    "ENABLE_PROJECT_SELF_MEMORY", default=False
                )
            ),
            llm=LLMSettings(
                enable_live_llm=llm_enabled,
                enable_openai_routing=_read_bool_env(
                    "ENABLE_OPENAI_ROUTING", default=False
                ),
                request_timeout_seconds=llm_request_timeout_seconds,
                dashscope=ProviderSettings(
                    api_key=llm_api_key,
                    base_url=llm_base_url,
                    model=llm_model,
                    fallback_models=llm_fallback_models,
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
            ocr=OCRSettings(
                enabled=ocr_enabled,
                provider_label=runtime_overrides.ocr.provider_label or "Qwen-VL-OCR",
                api_key=ocr_api_key,
                base_url=ocr_base_url,
                model=ocr_model,
                request_timeout_seconds=(
                    runtime_overrides.ocr.request_timeout_seconds
                    if runtime_overrides.ocr.request_timeout_seconds is not None
                    else _read_int_env("OCR_REQUEST_TIMEOUT_SECONDS", 60)
                ),
            ),
            source_files=SourceFileSettings(
                max_age_days=max(
                    1,
                    runtime_overrides.source_files.max_age_days
                    if runtime_overrides.source_files.max_age_days is not None
                    else _read_int_env("SOURCE_FILES_MAX_AGE_DAYS", 30),
                ),
                max_total_size_mb=max(
                    64,
                    runtime_overrides.source_files.max_total_size_mb
                    if runtime_overrides.source_files.max_total_size_mb is not None
                    else _read_int_env("SOURCE_FILES_MAX_TOTAL_SIZE_MB", 2048),
                ),
                delete_when_item_deleted=(
                    runtime_overrides.source_files.delete_when_item_deleted
                    if runtime_overrides.source_files.delete_when_item_deleted is not None
                    else _read_bool_env("SOURCE_FILES_DELETE_WHEN_ITEM_DELETED", default=True)
                ),
                filter_patterns=(
                    runtime_overrides.source_files.filter_patterns
                    if runtime_overrides.source_files.filter_patterns
                    else _read_csv_env("SOURCE_FILES_FILTER_PATTERNS", default=())
                ),
            ),
        )
