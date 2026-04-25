"""Experimental service for writing project-self knowledge into long-term memory."""

from __future__ import annotations

from dataclasses import dataclass

from core.runtime.time import now_in_project_timezone
from core.schemas import ProfileMemory, ProjectMemoryEntry


@dataclass
class ProjectSelfMemoryPayload:
    """
    Input payload for the experimental project-self-memory feature.

    This payload is intentionally scoped to the experimental module so the
    stable profile schema does not need to absorb temporary feature semantics.
    """

    name: str
    summary: str
    role: str | None
    tech_stack: list[str]
    highlight_points: list[str]
    interview_story_hooks: list[str]


class ProjectSelfMemoryService:
    """
    Write or update one project entry inside profile memory.

    Responsibilities:
    - Convert project-self payloads into `ProjectMemoryEntry`.
    - Merge them into the existing profile memory without mutating the main
      ingest / extract / rank / reminder chain.

    Non-responsibilities:
    - Deciding when the feature is enabled.
    - Triggering chat generation or interview prep directly.
    """

    def merge_into_profile(
        self,
        *,
        profile_memory: ProfileMemory,
        payload: ProjectSelfMemoryPayload,
    ) -> ProfileMemory:
        """Insert or replace one project entry by name."""

        project_entry = ProjectMemoryEntry(
            name=payload.name,
            summary=payload.summary,
            role=payload.role,
            tech_stack=payload.tech_stack,
            highlight_points=payload.highlight_points,
            interview_story_hooks=payload.interview_story_hooks,
            source_file_name=None,
            source_file_path=None,
        )

        remaining_projects = [
            project
            for project in profile_memory.projects
            if project.name.strip().lower() != payload.name.strip().lower()
        ]

        return profile_memory.model_copy(
            update={
                "projects": [*remaining_projects, project_entry],
                "updated_at": now_in_project_timezone(),
            }
        )
