"""External tool adapters package."""

from core.tools.calendar_client import CalendarClient
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
from core.tools.ocr_client import LocalTesseractOCRClient, OCRExtractionResult
from core.tools.prompt_loader import PromptLoader
from core.tools.recent_site_titles import RecentArticleTitle, fetch_recent_site_titles
from core.tools.search_client import NoopSearchClient, WebSearchClient
from core.tools.vector_store import NoopVectorStore, QdrantRESTVectorStore, VectorStoreError
from core.tools.web_page_client import WebPageClient, WebPageExtractionResult
from core.tools.web_push_client import WebPushClient

__all__ = [
    "CalendarClient",
    "EmbeddingGatewayError",
    "EmbeddingNotConfiguredError",
    "EmailClient",
    "LLMGatewayError",
    "LLMNotConfiguredError",
    "LocalTesseractOCRClient",
    "NoopEmbeddingGateway",
    "NoopLLMGateway",
    "NoopSearchClient",
    "NoopVectorStore",
    "OpenAICompatibleEmbeddingGateway",
    "OCRExtractionResult",
    "OpenAICompatibleLLMGateway",
    "PromptLoader",
    "QdrantRESTVectorStore",
    "RecentArticleTitle",
    "VectorStoreError",
    "fetch_recent_site_titles",
    "WebPageClient",
    "WebPageExtractionResult",
    "WebSearchClient",
    "WebPushClient",
]
