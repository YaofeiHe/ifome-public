"""External tool adapters package."""

from core.tools.calendar_client import CalendarClient
from core.tools.document_text_extractor import (
    DocumentTextExtractionResult,
    LocalDocumentTextExtractor,
)
from core.tools.email_client import EmailClient
from core.tools.embedding_client import (
    EmbeddingGatewayError,
    EmbeddingNotConfiguredError,
    NoopEmbeddingGateway,
    OpenAICompatibleEmbeddingGateway,
)
from core.tools.llm_client import (
    LLMGatewayError,
    LLMNotConfiguredError,
    NoopLLMGateway,
    OpenAICompatibleLLMGateway,
)
from core.tools.ocr_client import (
    CascadingOCRClient,
    GeneralLLMOCRClient,
    LocalTesseractOCRClient,
    OCRExtractionResult,
    OCRClient,
    QwenVLOCRClient,
    build_ocr_client_from_settings,
)
from core.tools.prompt_loader import PromptLoader
from core.tools.recent_site_titles import RecentArticleTitle, fetch_recent_site_titles
from core.tools.search_client import NoopSearchClient, WebSearchClient
from core.tools.vector_store import NoopVectorStore, QdrantRESTVectorStore, VectorStoreError
from core.tools.web_page_client import WebPageClient, WebPageExtractionResult
from core.tools.web_push_client import WebPushClient

__all__ = [
    "CalendarClient",
    "CascadingOCRClient",
    "DocumentTextExtractionResult",
    "EmbeddingGatewayError",
    "EmbeddingNotConfiguredError",
    "EmailClient",
    "GeneralLLMOCRClient",
    "LLMGatewayError",
    "LLMNotConfiguredError",
    "LocalDocumentTextExtractor",
    "LocalTesseractOCRClient",
    "NoopEmbeddingGateway",
    "NoopLLMGateway",
    "NoopSearchClient",
    "NoopVectorStore",
    "OpenAICompatibleEmbeddingGateway",
    "OpenAICompatibleLLMGateway",
    "OCRClient",
    "OCRExtractionResult",
    "PromptLoader",
    "QwenVLOCRClient",
    "QdrantRESTVectorStore",
    "RecentArticleTitle",
    "VectorStoreError",
    "build_ocr_client_from_settings",
    "fetch_recent_site_titles",
    "WebPageClient",
    "WebPageExtractionResult",
    "WebSearchClient",
    "WebPushClient",
]
