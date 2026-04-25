"""Helpers for assembling rule-first prompt context from storage and retrieval layers."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from core.schemas import AgentState


@dataclass(frozen=True)
class PromptReference:
    """One compact evidence block injected into an LLM prompt."""

    source_label: str
    snippet: str
    reason: str
    score: float
    source_kind: str
    item_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-safe prompt payload."""

        return {
            "item_id": self.item_id,
            "source_label": self.source_label,
            "snippet": self.snippet,
            "reason": self.reason,
            "score": round(self.score, 4),
            "source_kind": self.source_kind,
        }


def collect_prompt_references(
    *,
    user_id: str,
    workspace_id: str | None,
    current_item_id: str | None,
    query_text: str,
    source_metadata: dict[str, Any],
    workflow_repository,
    search_client,
    embedding_gateway,
    vector_store,
    embed_route: str,
    category_hint: str | None = None,
    limit: int = 4,
) -> list[PromptReference]:
    """Collect prompt references from explicit search hints, SQLite cards, and optional vectors."""

    references: dict[str, PromptReference] = {}
    lexical_candidates = _collect_sqlite_references(
        user_id=user_id,
        workspace_id=workspace_id,
        current_item_id=current_item_id,
        query_text=query_text,
        source_metadata=source_metadata,
        workflow_repository=workflow_repository,
    )

    for index, raw_reference in enumerate(source_metadata.get("search_references", [])[:2]):
        snippet = str(raw_reference).strip()
        if not snippet:
            continue
        key = f"search:{index}"
        references[key] = PromptReference(
            source_label=f"显式搜索参考 {index + 1}",
            snippet=snippet[:240],
            reason="user_requested_search_reference",
            score=0.98 - index * 0.03,
            source_kind="search_reference",
        )

    for index, reference in enumerate(
        _collect_search_lookup_references(
            query_text=query_text,
            source_metadata=source_metadata,
            search_client=search_client,
            category_hint=category_hint,
        )[:2]
    ):
        references.setdefault(f"keyword_search:{index}", reference)

    for reference in lexical_candidates[:limit]:
        if reference.item_id:
            references.setdefault(f"sqlite:{reference.item_id}", reference)

    for reference in _collect_vector_references(
        query_text=query_text,
        user_id=user_id,
        workspace_id=workspace_id,
        lexical_candidates=lexical_candidates[:8],
        embedding_gateway=embedding_gateway,
        vector_store=vector_store,
        embed_route=embed_route,
    ):
        if not reference.item_id:
            continue
        key = f"sqlite:{reference.item_id}"
        existing = references.get(key)
        if existing is None or reference.score > existing.score:
            references[key] = reference

    ordered = sorted(references.values(), key=lambda item: item.score, reverse=True)
    return ordered[:limit]


def _collect_search_lookup_references(
    *,
    query_text: str,
    source_metadata: dict[str, Any],
    search_client,
    category_hint: str | None,
) -> list[PromptReference]:
    """Search the web for compact prompt evidence when LLM escalation needs more context."""

    if search_client is None:
        return []

    references: list[PromptReference] = []
    seen_snippets: set[str] = set()
    for query_index, query in enumerate(
        _build_search_queries(
            query_text=query_text,
            source_metadata=source_metadata,
            category_hint=category_hint,
        )
    ):
        try:
            results = search_client.search(query=query, limit=2)
        except Exception:
            continue
        for result_index, result in enumerate(results[:2]):
            title = str(result.get("title") or "").strip()
            snippet = str(result.get("snippet") or "").strip()
            url = str(result.get("url") or "").strip()
            combined = " | ".join(part for part in [title, snippet, url] if part)[:240]
            if not combined or combined in seen_snippets:
                continue
            seen_snippets.add(combined)
            references.append(
                PromptReference(
                    source_label=f"关键词搜索 {query_index + 1}.{result_index + 1}",
                    snippet=combined,
                    reason=f"keyword_search:{query[:80]}",
                    score=max(0.76 - query_index * 0.04 - result_index * 0.03, 0.56),
                    source_kind="keyword_search",
                )
            )
    return references


def _build_search_queries(
    *,
    query_text: str,
    source_metadata: dict[str, Any],
    category_hint: str | None,
) -> list[str]:
    """Build compact keyword queries from structured hints before falling back to raw text."""

    raw_terms = [
        source_metadata.get("primary_unit"),
        source_metadata.get("role_variant"),
        source_metadata.get("relationship_family"),
        source_metadata.get("relationship_stage"),
        source_metadata.get("identity_tag"),
        *source_metadata.get("keyword_hints", [])[:4],
    ]
    terms: list[str] = []
    for raw_value in raw_terms:
        value = str(raw_value or "").strip()
        if not value or value in terms or len(value) > 48:
            continue
        terms.append(value)

    suffix = _category_search_suffix(category_hint)
    queries: list[str] = []
    if terms:
        queries.append(" ".join([*terms[:4], suffix]).strip())
        if len(terms) > 2:
            queries.append(" ".join([*terms[:2], *terms[-2:], suffix]).strip())

    normalized_text = re.sub(r"\s+", " ", query_text).strip()
    if normalized_text and not queries:
        queries.append(f"{normalized_text[:48]} {suffix}".strip())

    deduped: list[str] = []
    for query in queries:
        compact = re.sub(r"\s+", " ", query).strip()
        if compact and compact not in deduped:
            deduped.append(compact)
    return deduped[:2]


def _category_search_suffix(category_hint: str | None) -> str:
    """Choose one short search suffix that nudges the web lookup toward the right domain."""

    if category_hint in {"job_posting", "referral", "interview_notice", "talk_event"}:
        return "招聘 岗位"
    if category_hint == "general_update":
        return "市场 产品 动态"
    return "信息"


def _collect_sqlite_references(
    *,
    user_id: str,
    workspace_id: str | None,
    current_item_id: str | None,
    query_text: str,
    source_metadata: dict[str, Any],
    workflow_repository,
) -> list[PromptReference]:
    """Rank recent cards from SQLite using lexical overlap and shared field hints."""

    references: list[PromptReference] = []
    keyword_hints = [str(value).strip() for value in source_metadata.get("keyword_hints", []) if str(value).strip()]
    current_company = str(source_metadata.get("primary_unit") or "").strip()
    current_role = str(source_metadata.get("role_variant") or "").strip()

    for candidate in workflow_repository.list_all(user_id=user_id, workspace_id=workspace_id):
        normalized = candidate.normalized_item
        signal = candidate.extracted_signal
        if normalized is None:
            continue
        if current_item_id and normalized.id == current_item_id:
            continue

        combined_text = _snapshot_text(candidate)
        score = _lexical_similarity(query_text, combined_text)
        reasons: list[str] = []
        if signal and current_company and signal.company == current_company:
            score += 0.18
            reasons.append("same_company")
        if signal and current_role and signal.role == current_role:
            score += 0.14
            reasons.append("same_role")
        if keyword_hints:
            matched_hints = sum(1 for hint in keyword_hints[:6] if hint and hint in combined_text)
            if matched_hints:
                score += min(0.12, matched_hints * 0.03)
                reasons.append("keyword_hint_overlap")

        if score < 0.18:
            continue

        source_label = (
            signal.summary_one_line
            if signal and signal.summary_one_line
            else normalized.source_title
            or normalized.source_ref
            or normalized.id
        )
        references.append(
            PromptReference(
                item_id=normalized.id,
                source_label=str(source_label)[:80],
                snippet=combined_text[:220],
                reason="sqlite_card_overlap" + (f":{','.join(reasons)}" if reasons else ""),
                score=min(score, 0.95),
                source_kind="sqlite",
            )
        )

    references.sort(key=lambda item: item.score, reverse=True)
    return references


def _collect_vector_references(
    *,
    query_text: str,
    user_id: str,
    workspace_id: str | None,
    lexical_candidates: list[PromptReference],
    embedding_gateway,
    vector_store,
    embed_route: str,
) -> list[PromptReference]:
    """Optionally rerank a small lexical candidate pool with live vector similarity."""

    if not lexical_candidates:
        return []
    if not embedding_gateway.is_available(embed_route) or not vector_store.is_available():
        return []

    texts = [query_text, *[reference.snippet for reference in lexical_candidates]]
    try:
        vectors = embedding_gateway.embed_texts(route=embed_route, texts=texts)
        if len(vectors) != len(texts):
            return []
        collection_name = _prompt_collection_name(user_id=user_id, workspace_id=workspace_id)
        vector_store.ensure_collection(name=collection_name, vector_size=len(vectors[0]))
        points = []
        for index, reference in enumerate(lexical_candidates, start=1):
            points.append(
                {
                    "id": index,
                    "vector": vectors[index],
                    "payload": {
                        "item_id": reference.item_id,
                        "source_label": reference.source_label,
                        "snippet": reference.snippet,
                    },
                }
            )
        vector_store.upsert_points(collection_name=collection_name, points=points)
        queried = vector_store.query_points(
            collection_name=collection_name,
            query_vector=vectors[0],
            limit=min(3, len(points)),
        )
    except Exception:
        return []

    references: list[PromptReference] = []
    for raw_point in queried:
        payload = raw_point.get("payload") or {}
        item_id = payload.get("item_id")
        if not item_id:
            continue
        references.append(
            PromptReference(
                item_id=str(item_id),
                source_label=str(payload.get("source_label") or item_id)[:80],
                snippet=str(payload.get("snippet") or "")[:220],
                reason="vector_similarity_support",
                score=float(raw_point.get("score") or 0.0),
                source_kind="vector",
            )
        )
    references.sort(key=lambda item: item.score, reverse=True)
    return references


def _snapshot_text(state: AgentState) -> str:
    """Create one prompt-friendly text snapshot for lexical/vector comparison."""

    normalized = state.normalized_item
    signal = state.extracted_signal
    pieces = [
        normalized.source_title if normalized else "",
        signal.company if signal else "",
        signal.role if signal else "",
        signal.summary_one_line if signal else "",
        normalized.normalized_text[:320] if normalized and normalized.normalized_text else "",
    ]
    return "\n".join(piece for piece in pieces if piece).lower()


def _lexical_similarity(left: str, right: str) -> float:
    """Score short prompt candidates with a cheap lexical similarity."""

    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / math.sqrt(len(left_tokens) * len(right_tokens))


def _tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text.lower())
    if not cleaned:
        return set()
    token_pattern = r"https?://[^\s]+|[a-z0-9_+-]+|[\u4e00-\u9fff]{1,4}"
    return {token for token in re.findall(token_pattern, cleaned) if token}


def _prompt_collection_name(*, user_id: str, workspace_id: str | None) -> str:
    """Keep prompt-support vector candidates isolated by user/workspace scope."""

    raw_scope = f"{user_id}_{workspace_id or 'default'}".lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw_scope).strip("_")
    return f"ifome_prompt_support_{normalized[:32] or 'default'}"
