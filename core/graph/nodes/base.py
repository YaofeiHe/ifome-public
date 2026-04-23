"""Shared node wrapper for the minimal workflow graph."""

from __future__ import annotations

from typing import Any

from core.runtime.dependencies import WorkflowDependencies
from core.runtime.time import now_in_project_timezone
from core.schemas import AgentState, NodeExecutionRecord, WorkflowIssue, WorkflowStatus


class WorkflowNode:
    """
    Base implementation for one workflow node.

    Responsibilities:
    - Normalize input state into `AgentState`.
    - Record node execution history and structured failures.
    - Expose a LangGraph-compatible callable wrapper.

    Non-responsibilities:
    - Owning business logic for specific steps.
    - Persisting workflow state by itself.
    """

    name = "base"

    def __init__(self, dependencies: WorkflowDependencies) -> None:
        self.dependencies = dependencies

    def _run_impl(self, state: AgentState) -> AgentState:
        raise NotImplementedError

    def execute(self, state: AgentState | dict[str, Any]) -> AgentState:
        """Run the node and return an updated `AgentState` without raising."""

        normalized_state = (
            state if isinstance(state, AgentState) else AgentState.model_validate(state)
        )
        working_state = normalized_state.model_copy(deep=True)
        started_at = now_in_project_timezone()

        try:
            self.dependencies.trace_logger.info(
                "node_started",
                trace_id=working_state.trace_id,
                node_name=self.name,
            )
            updated_state = self._run_impl(working_state)
            updated_state.node_history.append(
                NodeExecutionRecord(
                    node_name=self.name,
                    status=WorkflowStatus.COMPLETED,
                    started_at=started_at,
                    completed_at=now_in_project_timezone(),
                )
            )
            self.dependencies.trace_logger.info(
                "node_completed",
                trace_id=updated_state.trace_id,
                node_name=self.name,
            )
            return updated_state
        except Exception as exc:  # pragma: no cover - fallback path
            working_state.issues.append(
                WorkflowIssue(
                    node_name=self.name,
                    severity="error",
                    message=str(exc),
                    retryable=False,
                    details={"node_name": self.name},
                    observed_at=now_in_project_timezone(),
                )
            )
            working_state.node_history.append(
                NodeExecutionRecord(
                    node_name=self.name,
                    status=WorkflowStatus.FAILED,
                    started_at=started_at,
                    completed_at=now_in_project_timezone(),
                    notes="Node failed and returned partial state.",
                )
            )
            working_state.status = WorkflowStatus.PARTIAL
            self.dependencies.trace_logger.error(
                "node_failed",
                trace_id=working_state.trace_id,
                node_name=self.name,
                error_reason=str(exc),
            )
            return working_state

    def as_langgraph_node(self):
        """Return a callable adapter suitable for LangGraph node registration."""

        def _wrapped(state: AgentState | dict[str, Any]) -> dict[str, Any]:
            updated_state = self.execute(state)
            return updated_state.model_dump(mode="python")

        return _wrapped
