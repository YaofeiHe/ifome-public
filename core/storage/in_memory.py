"""In-memory repositories used by the minimal workflow scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.schemas import AgentState, ReminderTask


@dataclass
class InMemoryWorkflowRepository:
    """
    Store workflow outputs in memory for local development and tests.

    Responsibilities:
    - Keep the latest processed state for each normalized item.
    - Provide a minimal persistence target for the `persist` node.

    Non-responsibilities:
    - Durable storage.
    - Query optimization or multi-process consistency.
    """

    records: dict[str, AgentState] = field(default_factory=dict)

    def save(self, state: AgentState) -> str:
        """Persist the current state snapshot under its normalized item id."""

        record_id = state.normalized_item.id if state.normalized_item else state.trace_id
        self.records[record_id] = state.model_copy(deep=True)
        return record_id

    def list_all(self) -> list[AgentState]:
        """Return all stored workflow states in insertion order."""

        return list(self.records.values())

    def get(self, record_id: str) -> AgentState | None:
        """Return one workflow state by id when present."""

        record = self.records.get(record_id)
        return record.model_copy(deep=True) if record else None


@dataclass
class InMemoryReminderRepository:
    """
    In-memory reminder queue used by the minimal workflow.

    Responsibilities:
    - Collect planned reminders created during the workflow.

    Non-responsibilities:
    - Delivery scheduling.
    - Long-term persistence.
    """

    reminders: dict[str, ReminderTask] = field(default_factory=dict)

    def save_many(self, tasks: list[ReminderTask]) -> list[str]:
        """Store reminder tasks and return their identifiers."""

        for task in tasks:
            self.reminders[task.id] = task.model_copy(deep=True)
        return [task.id for task in tasks]

    def list_all(self) -> list[ReminderTask]:
        """Return all reminder tasks currently in the in-memory queue."""

        return list(self.reminders.values())
