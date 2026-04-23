"""Reminder queue service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.schemas import ReminderTask


class ReminderRepository(Protocol):
    """Persistence contract used by the reminder queue service."""

    def save_many(self, tasks: list[ReminderTask]) -> list[str]:
        """Persist reminder tasks and return their identifiers."""

    def list_all(self) -> list[ReminderTask]:
        """Return all stored reminder tasks."""

    def delete_by_source_item_id(self, source_item_id: str) -> int:
        """Delete reminder tasks associated with one source item."""


@dataclass
class ReminderQueue:
    """
    Queue service wrapping reminder persistence behind a stable interface.

    Responsibilities:
    - Accept reminder tasks produced by workflow planning.
    - Provide one queue-shaped read/write interface for future dispatchers.

    Non-responsibilities:
    - Deciding which reminders should exist.
    - Sending messages to end users.
    """

    repository: ReminderRepository

    def enqueue(self, tasks: list[ReminderTask]) -> list[str]:
        """Persist tasks into the queue and return the created ids."""

        if not tasks:
            return []
        return self.repository.save_many(tasks)

    def list_tasks(self) -> list[ReminderTask]:
        """Return all currently queued reminder tasks."""

        return self.repository.list_all()

    def delete_for_item(self, source_item_id: str) -> int:
        """Delete all reminders associated with one source item."""

        return self.repository.delete_by_source_item_id(source_item_id)
