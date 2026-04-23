"""OpenAI-compatible embedding client used by the RAG layer."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.runtime.settings import ProviderSettings, RAGSettings


class EmbeddingGatewayError(RuntimeError):
    """Base exception for embedding client failures."""


class EmbeddingNotConfiguredError(EmbeddingGatewayError):
    """Raised when live embedding execution is not configured."""


class NoopEmbeddingGateway:
    """Embedding gateway used when live RAG retrieval is disabled."""

    def is_available(self, route: str) -> bool:
        return False

    def embed_texts(self, *, route: str, texts: list[str]) -> list[list[float]]:
        raise EmbeddingNotConfiguredError("Live embedding execution is disabled.")


class OpenAICompatibleEmbeddingGateway:
    """Minimal HTTP client for providers exposing OpenAI-compatible embeddings APIs."""

    max_batch_size = 10

    def __init__(self, settings: RAGSettings) -> None:
        self.settings = settings

    def is_available(self, route: str) -> bool:
        try:
            self._resolve_provider(route)
        except EmbeddingNotConfiguredError:
            return False
        return True

    def embed_texts(self, *, route: str, texts: list[str]) -> list[list[float]]:
        provider = self._resolve_provider(route)
        endpoint = f"{provider.base_url.rstrip('/')}/embeddings"
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.max_batch_size):
            chunk = texts[start : start + self.max_batch_size]
            body = {
                "model": provider.model,
                "input": chunk,
                "encoding_format": "float",
            }
            request = Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:  # pragma: no cover - network path
                error_body = exc.read().decode("utf-8", errors="ignore")
                raise EmbeddingGatewayError(
                    f"Embedding HTTP error for {provider.model}: {exc.code} {error_body}"
                ) from exc
            except URLError as exc:  # pragma: no cover - network path
                raise EmbeddingGatewayError(
                    f"Embedding network error for {provider.model}: {exc.reason}"
                ) from exc

            try:
                data = payload["data"]
                vectors.extend(item["embedding"] for item in data)
            except (KeyError, TypeError) as exc:
                raise EmbeddingGatewayError(
                    "Embedding response did not contain the expected vector payload."
                ) from exc

        return vectors

    def _resolve_provider(self, route: str) -> ProviderSettings:
        if not self.settings.enable_live_rag:
            raise EmbeddingNotConfiguredError("ENABLE_LIVE_RAG is disabled.")

        provider_name = route.split(":", 1)[0]
        if provider_name != "dashscope":
            raise EmbeddingNotConfiguredError(f"Unsupported embedding provider `{route}`.")

        provider = self.settings.embedding
        if not provider.api_key or not provider.base_url or not provider.model:
            raise EmbeddingNotConfiguredError(
                f"Route `{route}` is not fully configured for live embeddings."
            )
        return provider
