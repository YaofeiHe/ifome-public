"""SQLite-backed memory provider."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from core.schemas import CareerStateMemory, ProfileMemory


class SQLiteMemoryProvider:
    """
    Persist memory payloads in a local SQLite database.

    Responsibilities:
    - Store profile and career-state memory snapshots per user/workspace scope.
    - Rehydrate the latest payload across service restarts.
    - Seed a default payload when one scope is first accessed.

    Non-responsibilities:
    - Semantic memory merging rules.
    - Retrieval or ranking over memory contents.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        default_payload_factory: Callable[[str, str | None], dict[str, Any]],
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_payload_factory = default_payload_factory
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection for one short-lived repository operation."""

        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        """Create the memory snapshots table if it does not exist yet."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_snapshots (
                    user_id TEXT NOT NULL,
                    workspace_scope TEXT NOT NULL,
                    workspace_id TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, workspace_scope)
                )
                """
            )
            connection.commit()

    def load(self, user_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        """Load one user/workspace memory payload, seeding defaults when missing."""

        workspace_scope = workspace_id or "__default__"
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM memory_snapshots
                WHERE user_id = ? AND workspace_scope = ?
                """,
                (user_id, workspace_scope),
            ).fetchone()

        if row is None:
            payload = self.default_payload_factory(user_id, workspace_id)
            self.save(payload)
            return payload

        return self._rehydrate_payload(json.loads(row["payload_json"]))

    def save(self, payload: dict[str, Any]) -> None:
        """Upsert one memory payload using user/workspace scope as the key."""

        user_id = payload["user_id"]
        workspace_id = payload.get("workspace_id")
        workspace_scope = workspace_id or "__default__"
        updated_at = self._resolve_updated_at(payload)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_snapshots (
                    user_id, workspace_scope, workspace_id, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, workspace_scope) DO UPDATE SET
                    workspace_id=excluded.workspace_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    workspace_scope,
                    workspace_id,
                    json.dumps(self._normalize_payload(payload), ensure_ascii=False),
                    updated_at,
                ),
            )
            connection.commit()

    def _normalize_payload(self, value: Any) -> Any:
        """Convert nested Pydantic models and containers into JSON-safe values."""

        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: self._normalize_payload(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_payload(item) for item in value]
        return value

    def _resolve_updated_at(self, payload: dict[str, Any]) -> str:
        """Pick a stable updated-at value from the nested memory objects."""

        for key in ("career_state_memory", "profile_memory"):
            memory = payload.get(key)
            if memory is None:
                continue
            if hasattr(memory, "updated_at") and memory.updated_at is not None:
                return memory.updated_at.isoformat()
            if isinstance(memory, dict) and memory.get("updated_at"):
                return str(memory["updated_at"])
        raise ValueError("memory payload must include profile_memory or career_state_memory")

    def _rehydrate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Restore nested memory objects to the same shape as the old in-memory provider."""

        restored = dict(payload)
        if "profile_memory" in restored:
            restored["profile_memory"] = ProfileMemory.model_validate(
                restored["profile_memory"]
            )
        if "career_state_memory" in restored:
            restored["career_state_memory"] = CareerStateMemory.model_validate(
                restored["career_state_memory"]
            )
        return restored
