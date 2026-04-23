"""Ingest node implementation."""

from __future__ import annotations

from core.graph.nodes.base import WorkflowNode
from core.schemas import AgentState, WorkflowStatus


class IngestNode(WorkflowNode):
    """
    Capture the raw request and mark the workflow as running.

    Input fields:
    - `raw_input`
    - `source_type`
    - `trace_id`
    - `user_id`

    Output fields:
    - `status`
    - `source_metadata`
    - `model_routing["ingest"]`

    Failure strategy:
    - If `raw_input` is empty, record a structured failure and return partial state.
    """

    name = "ingest"

    def _run_impl(self, state: AgentState) -> AgentState:
        if not state.raw_input.strip():
            raise ValueError("raw_input cannot be empty at ingest time.")

        state.status = WorkflowStatus.RUNNING
        state.source_metadata.setdefault("ingest_channel", "manual")
        state.model_routing[self.name] = "rule_based"
        return state
