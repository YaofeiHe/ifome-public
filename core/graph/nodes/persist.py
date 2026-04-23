"""Persist node implementation."""

from __future__ import annotations

import math
import re

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
        route = self.dependencies.model_router.select("deduplicate", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                return self._llm_similarity_decision(current=current, existing=existing, route=route)
            except Exception:
                pass
        return self._heuristic_similarity_decision(current=current, existing=existing)

    def _llm_similarity_decision(
        self,
        *,
        current: AgentState,
        existing: AgentState,
        route: str,
    ) -> tuple[float, bool, str]:
        response = self.dependencies.llm_gateway.complete_json(
            route=route,
            task_name="card_deduplicate",
            system_prompt=(
                "你在判断两张求职信息卡片是否属于同一核心岗位信息。"
                "只返回 JSON。"
                "字段：same_core(boolean), should_replace_existing(boolean), confidence(number), reason(string)。"
                "判断标准：公司、岗位、地点、链接、时间、原文片段是否指向同一个岗位。"
                "如果只是同一岗位的新版本，same_core=true 且 should_replace_existing=true。"
                "如果核心信息相同且没有重要变化，same_core=true 且 should_replace_existing=false。"
            ),
            user_payload={
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
        return self._normalize_piece(str(title))

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
