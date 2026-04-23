"""Normalize node implementation."""

from __future__ import annotations

from uuid import uuid4

from core.extraction.normalize import normalize_text
from core.graph.nodes.base import WorkflowNode
from core.runtime.time import now_in_project_timezone
from core.schemas import AgentState, NormalizedItem


class NormalizeNode(WorkflowNode):
    """
    Convert raw input into the canonical `NormalizedItem`.

    Input fields:
    - `raw_input`
    - `source_type`
    - `source_ref`
    - `memory_write_mode`

    Output fields:
    - `normalized_item`

    Failure strategy:
    - If normalization produces empty text, record failure and return partial state.
    """

    name = "normalize"

    def _run_impl(self, state: AgentState) -> AgentState:
        normalized_text = normalize_text(state.raw_input)
        if not normalized_text:
            raise ValueError("Normalization produced empty text.")

        created_at = now_in_project_timezone()
        state.normalized_item = NormalizedItem(
            id=f"item_{uuid4().hex[:10]}",
            user_id=state.user_id,
            workspace_id=state.workspace_id,
            trace_id=state.trace_id,
            source_type=state.source_type,
            source_ref=state.source_ref,
            source_title=(
                str(state.source_metadata.get("source_title")).strip()
                if state.source_metadata.get("source_title")
                else str(state.source_metadata.get("page_title")).strip()
                if state.source_metadata.get("page_title")
                else None
            ),
            raw_content=state.raw_input,
            normalized_text=normalized_text,
            memory_write_mode=state.memory_write_mode,
            source_metadata=state.source_metadata,
            created_at=created_at,
            normalized_at=created_at,
        )
        return state
