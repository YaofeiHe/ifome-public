"""Persist node implementation."""

from __future__ import annotations

import math
import re

from core.extraction.prompt_context import collect_prompt_references
from core.graph.nodes.base import WorkflowNode
from core.schemas import AgentState


class PersistNode(WorkflowNode):
    """
    Save the workflow outputs into the configured workflow repository and reminder queue.

    Input fields:
    - `normalized_item`
    - `extracted_signal`
    - `score_result`
    - `reminder_tasks`

    Output fields:
    - `persistence_summary`

    Failure strategy:
    - Missing `normalized_item` produces partial-state failure.
    - Repository errors are captured as structured issues.
    """

    name = "persist"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.normalized_item is None:
            raise ValueError("normalized_item is required before persist.")

        dedupe_decision = self._resolve_duplicate(state)
        if dedupe_decision is not None:
            target_item_id, action, score, reason = dedupe_decision
            previous_item_id = state.normalized_item.id
            state.normalized_item.id = target_item_id
            if state.extracted_signal is not None:
                state.extracted_signal.source_item_id = target_item_id
            for reminder in state.reminder_tasks:
                reminder.source_item_id = target_item_id
            self.dependencies.reminder_queue.delete_for_item(target_item_id)
            state.persistence_summary.update(
                {
                    "dedupe_action": action,
                    "dedupe_score": round(score, 4),
                    "dedupe_reason": reason,
                    "dedupe_previous_item_id": previous_item_id,
                    "dedupe_target_item_id": target_item_id,
                }
            )

        record_id = self.dependencies.workflow_repository.save(state)
        reminder_ids = self.dependencies.reminder_queue.enqueue(state.reminder_tasks)
        state.persistence_summary = {
            **state.persistence_summary,
            "workflow_record_id": record_id,
            "reminder_count": len(reminder_ids),
            "reminder_ids": reminder_ids,
        }
        return state

    def _resolve_duplicate(self, state: AgentState) -> tuple[str, str, float, str] | None:
        existing_states = self.dependencies.workflow_repository.list_all(
            user_id=state.user_id,
            workspace_id=state.workspace_id,
        )
        if not existing_states or state.extracted_signal is None:
            return None

        candidates = [
            existing
            for existing in existing_states
            if existing.normalized_item is not None
            and existing.normalized_item.id != state.normalized_item.id
            and self._is_candidate_pair(state, existing)
        ]
        if not candidates:
            return None

        best_existing: AgentState | None = None
        best_score = 0.0
        best_decision: tuple[str, str, float, str] | None = None
        for existing in candidates[:8]:
            score, replace_existing, reason = self._similarity_decision(state, existing)
            if score > best_score and score >= 0.6:
                best_existing = existing
                action = "replace_existing" if replace_existing else "skip_duplicate"
                best_score = score
                best_decision = (
                    existing.normalized_item.id,
                    action,
                    score,
                    reason,
                )

        if best_existing is None:
            return None
        return best_decision

    def _is_candidate_pair(self, current: AgentState, existing: AgentState) -> bool:
        current_signal = current.extracted_signal
        existing_signal = existing.extracted_signal
        if current_signal is None or existing_signal is None:
            return False
        if self._has_identity_conflict(current, existing):
            return False

        if current.source_ref and existing.source_ref and current.source_ref == existing.source_ref:
            return True
        if (
            current_signal.apply_url
            and existing_signal.apply_url
            and current_signal.apply_url == existing_signal.apply_url
        ):
            return True
        if (
            current_signal.company
            and existing_signal.company
            and current_signal.company == existing_signal.company
            and current_signal.role
            and existing_signal.role
            and current_signal.role == existing_signal.role
        ):
            return True
        return self._text_similarity(
            current.normalized_item.normalized_text,
            existing.normalized_item.normalized_text,
        ) >= 0.45

    def _has_identity_conflict(self, current: AgentState, existing: AgentState) -> bool:
        """Reject dedupe when the generated card identity already says they differ."""

        current_title = self._source_title(current)
        existing_title = self._source_title(existing)
        if current_title and existing_title and current_title != existing_title:
            return True

        current_variant = self._role_variant(current)
        existing_variant = self._role_variant(existing)
        if current_variant and existing_variant and current_variant != existing_variant:
            return True

        current_identity_tag = self._identity_tag(current)
        existing_identity_tag = self._identity_tag(existing)
        if current_identity_tag and existing_identity_tag and current_identity_tag != existing_identity_tag:
            return True
        return False

    def _similarity_decision(
        self,
        current: AgentState,
        existing: AgentState,
    ) -> tuple[float, bool, str]:
        heuristic_score, heuristic_replace, heuristic_reason = self._heuristic_similarity_decision(
            current=current,
            existing=existing,
        )
        force_llm = self._should_force_llm_company_role_check(
            current=current,
            existing=existing,
        )
        route = self.dependencies.model_router.select("deduplicate", "medium")
        if force_llm and self.dependencies.llm_gateway.is_available(route):
            try:
                return self._llm_similarity_decision(
                    current=current,
                    existing=existing,
                    route=route,
                    heuristic_score=heuristic_score,
                    heuristic_reason=f"force_llm_company_role::{heuristic_reason}",
                )
            except Exception:
                return (heuristic_score, heuristic_replace, heuristic_reason)
        if heuristic_score >= 0.82 or heuristic_score < 0.45:
            return (heuristic_score, heuristic_replace, heuristic_reason)

        if self.dependencies.llm_gateway.is_available(route):
            try:
                return self._llm_similarity_decision(
                    current=current,
                    existing=existing,
                    route=route,
                    heuristic_score=heuristic_score,
                    heuristic_reason=heuristic_reason,
                )
            except Exception:
                return (heuristic_score, heuristic_replace, heuristic_reason)
        return (heuristic_score, heuristic_replace, heuristic_reason)

    def _llm_similarity_decision(
        self,
        *,
        current: AgentState,
        existing: AgentState,
        route: str,
        heuristic_score: float,
        heuristic_reason: str,
    ) -> tuple[float, bool, str]:
        prompt = self.dependencies.prompt_loader.load("deduplicate")
        prompt_references = self._collect_dedupe_prompt_references(
            current=current,
            existing=existing,
        )
        response = self.dependencies.llm_gateway.complete_json(
            route=route,
            task_name="card_deduplicate",
            system_prompt=prompt,
            user_payload={
                "heuristic_precheck": {
                    "score": round(heuristic_score, 4),
                    "reason": heuristic_reason,
                },
                "keyword_hints": self._dedupe_keyword_hints(current, existing),
                "prompt_references": [reference.to_payload() for reference in prompt_references],
                "current": self._state_snapshot(current),
                "existing": self._state_snapshot(existing),
            },
        )
        confidence = float(response.get("confidence") or 0.0)
        same_core = bool(response.get("same_core"))
        replace_existing = bool(response.get("should_replace_existing"))
        reason = str(response.get("reason") or "LLM dedupe decision.")
        return (confidence if same_core else min(confidence, 0.69), replace_existing, reason)

    def _heuristic_similarity_decision(
        self,
        *,
        current: AgentState,
        existing: AgentState,
    ) -> tuple[float, bool, str]:
        current_signal = current.extracted_signal
        existing_signal = existing.extracted_signal
        if current_signal is None or existing_signal is None:
            return (0.0, False, "Missing extracted signal.")

        score = 0.0
        reasons: list[str] = []
        if current.classified_category == existing.classified_category:
            score += 0.1
        if self._source_title(current) and self._source_title(current) == self._source_title(existing):
            score += 0.2
            reasons.append("source_title matched")
        if self._role_variant(current) and self._role_variant(current) == self._role_variant(existing):
            score += 0.16
            reasons.append("role_variant matched")
        if self._identity_tag(current) and self._identity_tag(current) == self._identity_tag(existing):
            score += 0.14
            reasons.append("identity_tag matched")
        if current.source_ref and existing.source_ref and current.source_ref == existing.source_ref:
            score += 0.14
            reasons.append("source_ref matched")
        if (
            current_signal.apply_url
            and existing_signal.apply_url
            and current_signal.apply_url == existing_signal.apply_url
        ):
            score += 0.16
            reasons.append("apply_url matched")
        if current_signal.company and current_signal.company == existing_signal.company:
            score += 0.16
            reasons.append("company matched")
        if current_signal.role and current_signal.role == existing_signal.role:
            score += 0.18
            reasons.append("role matched")
        if current_signal.city and current_signal.city == existing_signal.city:
            score += 0.08
            reasons.append("city matched")
        if (
            current_signal.company
            and current_signal.company == existing_signal.company
            and current_signal.role
            and current_signal.role == existing_signal.role
        ):
            score += 0.12
            reasons.append("company-role core matched")

        text_score = self._text_similarity(
            current.normalized_item.normalized_text,
            existing.normalized_item.normalized_text,
        )
        score += text_score * 0.2
        if text_score >= 0.55:
            reasons.append("source text overlapped")

        key_changed = any(
            [
                current_signal.ddl != existing_signal.ddl,
                current_signal.interview_time != existing_signal.interview_time,
                current_signal.event_time != existing_signal.event_time,
                self._normalize_piece(current_signal.summary_one_line)
                != self._normalize_piece(existing_signal.summary_one_line),
            ]
        )
        replace_existing = score >= 0.6 and key_changed
        reason = ", ".join(reasons) or "heuristic similarity below threshold"
        return (min(score, 0.99), replace_existing, reason)

    def _should_force_llm_company_role_check(self, current: AgentState, existing: AgentState) -> bool:
        """Escalate directly to LLM when the pair looks like same-company similar-role ambiguity."""

        current_signal = current.extracted_signal
        existing_signal = existing.extracted_signal
        if current_signal is None or existing_signal is None:
            return False
        if not current_signal.company or current_signal.company != existing_signal.company:
            return False
        current_role = current_signal.role or self._role_variant(current) or ""
        existing_role = existing_signal.role or self._role_variant(existing) or ""
        if not current_role or not existing_role:
            return False
        return self._role_similarity(current_role, existing_role) >= 0.45

    def _role_similarity(self, left: str, right: str) -> float:
        """Measure shallow role similarity for dedupe escalation decisions."""

        left_tokens = self._tokenize(left)
        right_tokens = self._tokenize(right)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        return overlap / max(len(left_tokens), len(right_tokens))

    def _collect_dedupe_prompt_references(
        self,
        *,
        current: AgentState,
        existing: AgentState,
    ):
        """Assemble retrieval-backed prompt context for LLM dedupe decisions."""

        normalized = current.normalized_item
        if normalized is None:
            return []
        source_metadata = {
            **current.source_metadata,
            "keyword_hints": self._dedupe_keyword_hints(current, existing),
            "primary_unit": current.extracted_signal.company if current.extracted_signal else None,
            "role_variant": current.extracted_signal.role if current.extracted_signal else None,
        }
        query_text = " ".join(
            part
            for part in [
                normalized.normalized_text[:240],
                existing.normalized_item.normalized_text[:240]
                if existing.normalized_item is not None
                else "",
                current.extracted_signal.company if current.extracted_signal else "",
                current.extracted_signal.role if current.extracted_signal else "",
                existing.extracted_signal.role if existing.extracted_signal else "",
            ]
            if part
        )
        return collect_prompt_references(
            user_id=current.user_id,
            workspace_id=current.workspace_id,
            current_item_id=normalized.id,
            query_text=query_text,
            source_metadata=source_metadata,
            workflow_repository=self.dependencies.workflow_repository,
            search_client=None,
            embedding_gateway=self.dependencies.embedding_gateway,
            vector_store=self.dependencies.vector_store,
            embed_route=self.dependencies.model_router.select("embed", "low"),
            category_hint=current.classified_category.value if current.classified_category else None,
        )

    def _dedupe_keyword_hints(self, current: AgentState, existing: AgentState) -> list[str]:
        """Combine current and existing card keywords for dedupe prompting."""

        values = [
            *(current.source_metadata.get("keyword_hints", []) or []),
            *(existing.source_metadata.get("keyword_hints", []) or []),
            current.extracted_signal.company if current.extracted_signal else None,
            current.extracted_signal.role if current.extracted_signal else None,
            existing.extracted_signal.company if existing.extracted_signal else None,
            existing.extracted_signal.role if existing.extracted_signal else None,
            self._identity_tag(current),
            self._identity_tag(existing),
        ]
        deduped: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in deduped:
                deduped.append(text)
        return deduped[:8]

    def _state_snapshot(self, state: AgentState) -> dict:
        signal = state.extracted_signal
        normalized = state.normalized_item
        return {
            "item_id": normalized.id if normalized else None,
            "source_ref": state.source_ref,
            "category": state.classified_category.value if state.classified_category else None,
            "company": signal.company if signal else None,
            "role": signal.role if signal else None,
            "city": signal.city if signal else None,
            "ddl": signal.ddl.isoformat() if signal and signal.ddl else None,
            "interview_time": (
                signal.interview_time.isoformat() if signal and signal.interview_time else None
            ),
            "event_time": signal.event_time.isoformat() if signal and signal.event_time else None,
            "summary_one_line": signal.summary_one_line if signal else None,
            "raw_excerpt": signal.raw_text_excerpt if signal else None,
            "normalized_text": normalized.normalized_text[:400] if normalized else None,
            "source_title": normalized.source_title if normalized else None,
            "role_variant": state.source_metadata.get("role_variant"),
            "identity_tag": state.source_metadata.get("identity_tag"),
            "semantic_tags": state.source_metadata.get("semantic_tags", []),
        }

    def _source_title(self, state: AgentState) -> str | None:
        normalized = state.normalized_item
        title = normalized.source_title if normalized else state.source_metadata.get("source_title")
        if not title:
            return None
        normalized_title = self._normalize_piece(str(title))
        if self._is_instructional_title(normalized_title):
            return None
        return normalized_title

    def _role_variant(self, state: AgentState) -> str | None:
        role_variant = state.source_metadata.get("role_variant")
        if not role_variant:
            return None
        return self._normalize_piece(str(role_variant))

    def _identity_tag(self, state: AgentState) -> str | None:
        direct_tag = state.source_metadata.get("identity_tag")
        if direct_tag:
            return self._normalize_piece(str(direct_tag))

        raw_tags = state.source_metadata.get("semantic_tags", [])
        for value in raw_tags:
            tag = self._normalize_piece(str(value))
            if tag and "-" in tag:
                return tag
        return None

    def _text_similarity(self, left: str, right: str) -> float:
        left_tokens = self._tokenize(left)
        right_tokens = self._tokenize(right)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        return overlap / math.sqrt(len(left_tokens) * len(right_tokens))

    def _tokenize(self, text: str) -> set[str]:
        cleaned = re.sub(r"\s+", "", text.lower())
        if not cleaned:
            return set()
        token_pattern = r"https?://[^\s]+|[a-z0-9_+-]+|[\u4e00-\u9fff]{1,4}"
        return {token for token in re.findall(token_pattern, cleaned) if token}

    def _normalize_piece(self, value: str | None) -> str:
        return re.sub(r"\s+", "", (value or "").lower())

    def _is_instructional_title(self, title: str | None) -> bool:
        """Ignore action-only titles so they do not block duplicate merging."""

        if not title:
            return True
        return any(
            title.startswith(prefix)
            for prefix in (
                "填写内推码",
                "内推码",
                "网申链接",
                "投递链接",
                "投递方式",
                "申请方式",
                "官方内推投递",
                "点击链接",
                "链接",
                "填写",
            )
        )
