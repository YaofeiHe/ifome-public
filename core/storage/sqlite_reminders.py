"""SQLite-backed reminder queue repository."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.schemas import ReminderTask


class SQLiteReminderRepository:
    """
    Persist reminder tasks in a local SQLite queue.

    Responsibilities:
    - Create and migrate the minimal reminders table on startup.
    - Store reminder tasks durably for local development.
    - Return queue contents for API reads and future dispatchers.

    Non-responsibilities:
    - Sending notifications.
    - Cross-process locking beyond SQLite's default guarantees.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection for one short-lived repository operation."""

        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        """Create the reminders table if it does not exist yet."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workspace_id TEXT,
                    trace_id TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    trigger_time TEXT NOT NULL,
                    due_time TEXT,
                    priority TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
                """
            )
            connection.commit()

    def save_many(self, tasks: list[ReminderTask]) -> list[str]:
        """Upsert reminder tasks into SQLite and return their identifiers."""

        with self._connect() as connection:
            for task in tasks:
                connection.execute(
                    """
                    INSERT INTO reminder_tasks (
                        id, user_id, workspace_id, trace_id, source_item_id, title,
                        description, trigger_time, due_time, priority, channel, status,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        user_id=excluded.user_id,
                        workspace_id=excluded.workspace_id,
                        trace_id=excluded.trace_id,
                        source_item_id=excluded.source_item_id,
                        title=excluded.title,
                        description=excluded.description,
                        trigger_time=excluded.trigger_time,
                        due_time=excluded.due_time,
                        priority=excluded.priority,
                        channel=excluded.channel,
                        status=excluded.status,
                        payload_json=excluded.payload_json,
                        created_at=excluded.created_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        task.id,
                        task.user_id,
                        task.workspace_id,
                        task.trace_id,
                        task.source_item_id,
                        task.title,
                        task.description,
                        task.trigger_time.isoformat(),
                        task.due_time.isoformat() if task.due_time else None,
                        task.priority.value,
                        task.channel.value,
                        task.status.value,
                        task.model_dump_json(include={"payload"}),
                        task.created_at.isoformat(),
                        task.updated_at.isoformat() if task.updated_at else None,
                    ),
                )
            connection.commit()
        return [task.id for task in tasks]

    def list_all(self) -> list[ReminderTask]:
        """Return all queued reminders ordered by trigger time ascending."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM reminder_tasks
                ORDER BY trigger_time ASC
                """
            ).fetchall()

        reminders: list[ReminderTask] = []
        for row in rows:
            payload = ReminderTask.model_validate(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "workspace_id": row["workspace_id"],
                    "trace_id": row["trace_id"],
                    "source_item_id": row["source_item_id"],
                    "title": row["title"],
                    "description": row["description"],
                    "trigger_time": row["trigger_time"],
                    "due_time": row["due_time"],
                    "priority": row["priority"],
                    "channel": row["channel"],
                    "status": row["status"],
                    "payload": json.loads(row["payload_json"]).get("payload", {}),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
            reminders.append(payload)
        return reminders

    def delete_by_source_item_id(self, source_item_id: str) -> int:
        """Delete all reminders generated from one source item."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM reminder_tasks
                WHERE source_item_id = ?
                """,
                (source_item_id,),
            )
            connection.commit()
        return int(cursor.rowcount or 0)
