"""Classify node implementation."""

from __future__ import annotations

from core.extraction.live_llm import classify_text_with_llm
from core.extraction.parse import classify_text
from core.graph.nodes.base import WorkflowNode
from core.runtime.time import now_in_project_timezone
from core.schemas import AgentState, ContentCategory, WorkflowIssue


class ClassifyNode(WorkflowNode):
    """
    Assign a high-level category to the normalized item.

    Input fields:
    - `normalized_item.normalized_text`

    Output fields:
    - `classified_category`
    - `normalized_item.classification_hint`
    - `model_routing["classify"]`

    Failure strategy:
    - If `normalized_item` is missing, record failure and return partial state.
    """

    name = "classify"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.normalized_item is None:
            raise ValueError("normalized_item is required before classify.")

        forced_category = state.source_metadata.get("force_content_category")
        if forced_category:
            category = ContentCategory(str(forced_category))
            state.classified_category = category
            state.normalized_item.classification_hint = category
            state.model_routing[self.name] = "forced_by_source_metadata"
            return state

        route = self.dependencies.model_router.select("classify", "low")
        state.model_routing[self.name] = route

        if self.dependencies.llm_gateway.is_available(route):
            try:
                live_result = classify_text_with_llm(
                    normalized_text=state.normalized_item.normalized_text,
                    source_type=state.normalized_item.source_type,
                    route=route,
                    llm_gateway=self.dependencies.llm_gateway,
                    prompt_loader=self.dependencies.prompt_loader,
                )
                state.classified_category = live_result.category
                state.normalized_item.classification_hint = live_result.category
                return state
            except Exception as exc:
                state.issues.append(
                    WorkflowIssue(
                        node_name=self.name,
                        severity="warning",
                        message="Live classify failed. Fallback heuristic applied.",
                        retryable=True,
                        details={"route": route, "reason": str(exc)},
                        observed_at=now_in_project_timezone(),
                    )
                )
                self.dependencies.trace_logger.warning(
                    "live_classify_fallback",
                    trace_id=state.trace_id,
                    route=route,
                    reason=str(exc),
                )

        state.classified_category = classify_text(state.normalized_item.normalized_text)
        state.normalized_item.classification_hint = state.classified_category
        return state
