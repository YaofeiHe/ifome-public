"""Reminder planning node implementation."""

from __future__ import annotations

from core.graph.nodes.base import WorkflowNode
from core.reminders.planner import plan_reminders
from core.schemas import AgentState


class ReminderPlanNode(WorkflowNode):
    """
    Turn extracted time fields into reminder tasks.

    Input fields:
    - `extracted_signal`
    - `score_result`

    Output fields:
    - `reminder_tasks`

    Failure strategy:
    - Missing `extracted_signal` produces partial-state failure.
    - Missing time fields returns an empty reminder list rather than failing.
    """

    name = "reminder_plan"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.extracted_signal is None:
            raise ValueError("extracted_signal is required before reminder planning.")

        state.reminder_tasks = plan_reminders(state.extracted_signal, state.score_result)
        return state
