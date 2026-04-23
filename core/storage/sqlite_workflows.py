"""SQLite-backed workflow state repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.schemas import AgentState
from core.runtime.time import now_in_project_timezone


class SQLiteWorkflowRepository:
    """
    Persist workflow state snapshots in a local SQLite database.

    Responsibilities:
    - Create and migrate the minimal workflow state table on startup.
    - Store one full `AgentState` JSON snapshot per normalized item.
    - Expose simple read APIs for item list/detail endpoints.

    Non-responsibilities:
    - Complex analytical queries.
    - Full event sourcing or node-level replay storage.
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
        """Create the workflow states table and lookup indexes when missing."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_states (
                    record_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workspace_id TEXT,
                    trace_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT,
                    classified_category TEXT,
                    workflow_status TEXT NOT NULL,
                    priority TEXT,
                    company TEXT,
                    role TEXT,
                    city TEXT,
                    ddl TEXT,
                    summary_one_line TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workflow_states_user_created
                ON workflow_states (user_id, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workflow_states_workspace_created
                ON workflow_states (workspace_id, created_at DESC)
                """
            )
            connection.commit()

    def save(self, state: AgentState) -> str:
        """Upsert one full workflow snapshot and return its record identifier."""

        record_id = state.normalized_item.id if state.normalized_item else state.trace_id
        normalized_item = state.normalized_item
        extracted_signal = state.extracted_signal
        render_card = state.render_card
        timestamp = now_in_project_timezone().isoformat()
        created_at = (
            normalized_item.created_at.isoformat() if normalized_item else timestamp
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_states (
                    record_id, user_id, workspace_id, trace_id, source_type, source_ref,
                    classified_category, workflow_status, priority, company, role, city,
                    ddl, summary_one_line, created_at, updated_at, state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    workspace_id=excluded.workspace_id,
                    trace_id=excluded.trace_id,
                    source_type=excluded.source_type,
                    source_ref=excluded.source_ref,
                    classified_category=excluded.classified_category,
                    workflow_status=excluded.workflow_status,
                    priority=excluded.priority,
                    company=excluded.company,
                    role=excluded.role,
                    city=excluded.city,
                    ddl=excluded.ddl,
                    summary_one_line=excluded.summary_one_line,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    state_json=excluded.state_json
                """,
                (
                    record_id,
                    state.user_id,
                    state.workspace_id,
                    state.trace_id,
                    state.source_type.value,
                    state.source_ref,
                    state.classified_category.value if state.classified_category else None,
                    state.status.value,
                    render_card.priority.value if render_card and render_card.priority else None,
                    render_card.company if render_card else extracted_signal.company if extracted_signal else None,
                    render_card.role if render_card else extracted_signal.role if extracted_signal else None,
                    render_card.city if render_card else extracted_signal.city if extracted_signal else None,
                    render_card.ddl.isoformat() if render_card and render_card.ddl else (
                        extracted_signal.ddl.isoformat() if extracted_signal and extracted_signal.ddl else None
                    ),
                    render_card.summary_one_line if render_card else (
                        extracted_signal.summary_one_line if extracted_signal else None
                    ),
                    created_at,
                    timestamp,
                    state.model_dump_json(),
                ),
            )
            connection.commit()
        return record_id

    def list_all(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[AgentState]:
        """Return workflow states ordered by most recent update first."""

        clauses: list[str] = []
        params: list[str | None] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)

        query = """
            SELECT state_json
            FROM workflow_states
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, created_at DESC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [AgentState.model_validate_json(row["state_json"]) for row in rows]

    def get(self, record_id: str) -> AgentState | None:
        """Return one workflow state snapshot by normalized item identifier."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state_json
                FROM workflow_states
                WHERE record_id = ?
                """,
                (record_id,),
            ).fetchone()

        if row is None:
            return None
        return AgentState.model_validate_json(row["state_json"])

    def delete(self, record_id: str) -> bool:
        """Delete one stored workflow state by item identifier."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM workflow_states
                WHERE record_id = ?
                """,
                (record_id,),
            )
            connection.commit()
        return bool(cursor.rowcount)
