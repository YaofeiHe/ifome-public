"""Qdrant-backed vector store client used by the RAG layer."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.runtime.settings import RAGSettings


class VectorStoreError(RuntimeError):
    """Base exception for vector store failures."""


class NoopVectorStore:
    """Vector store used when live RAG retrieval is disabled."""

    def is_available(self) -> bool:
        return False

    def ensure_collection(self, *, name: str, vector_size: int) -> None:
        return None

    def upsert_points(self, *, collection_name: str, points: list[dict]) -> None:
        return None

    def query_points(
        self, *, collection_name: str, query_vector: list[float], limit: int
    ) -> list[dict]:
        return []


class QdrantRESTVectorStore:
    """Small REST client for the subset of Qdrant operations needed by the POC."""

    def __init__(self, settings: RAGSettings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return bool(
            self.settings.enable_live_rag
            and self.settings.qdrant_url
            and self.settings.qdrant_api_key
        )

    def ensure_collection(self, *, name: str, vector_size: int) -> None:
        if not self.is_available():
            return
        try:
            self._request(
                method="PUT",
                path=f"/collections/{name}",
                body={
                    "vectors": {
                        "size": vector_size,
                        "distance": "Cosine",
                    }
                },
            )
        except VectorStoreError as exc:
            lowered = str(exc).lower()
            if "already exists" in lowered or "409" in lowered:
                return
            raise

    def upsert_points(self, *, collection_name: str, points: list[dict]) -> None:
        if not self.is_available() or not points:
            return
        self._request(
            method="PUT",
            path=f"/collections/{collection_name}/points",
            body={"points": points},
        )

    def query_points(
        self, *, collection_name: str, query_vector: list[float], limit: int
    ) -> list[dict]:
        if not self.is_available():
            return []

        payload = {
            "query": query_vector,
            "limit": limit,
            "with_payload": True,
        }
        try:
            result = self._request(
                method="POST",
                path=f"/collections/{collection_name}/points/query",
                body=payload,
            )
        except VectorStoreError:
            result = self._request(
                method="POST",
                path=f"/collections/{collection_name}/points/search",
                body={
                    "vector": query_vector,
                    "limit": limit,
                    "with_payload": True,
                },
            )

        points = result.get("points")
        if points:
            return points

        nested_result = result.get("result")
        if isinstance(nested_result, dict):
            nested_points = nested_result.get("points")
            if nested_points:
                return nested_points
        if isinstance(nested_result, list):
            return nested_result
        return []

    def _request(self, *, method: str, path: str, body: dict | None = None) -> dict:
        if not self.settings.qdrant_url or not self.settings.qdrant_api_key:
            raise VectorStoreError("Qdrant is not configured.")

        endpoint = f"{self.settings.qdrant_url.rstrip('/')}{path}"
        request = Request(
            endpoint,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "api-key": self.settings.qdrant_api_key,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:  # pragma: no cover - network path
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise VectorStoreError(
                f"Qdrant HTTP error for {path}: {exc.code} {error_body}"
            ) from exc
        except URLError as exc:  # pragma: no cover - network path
            raise VectorStoreError(f"Qdrant network error: {exc.reason}") from exc
        return payload
