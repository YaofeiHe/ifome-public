"""Memory write strategy tests."""

from __future__ import annotations

import pytest

from apps.api.src.services import ApiServiceContainer
from core.memory.experimental import ProjectSelfMemoryPayload, ProjectSelfMemoryService
from core.runtime.settings import AppSettings, FeatureFlags


def test_project_self_memory_service_merges_project_into_profile() -> None:
    """The experimental service should add one project entry without changing schema shape."""

    services = ApiServiceContainer()
    current = services.dependencies.memory_provider.load("user_1", "ws_1")
    profile = current["profile_memory"]

    merged = ProjectSelfMemoryService().merge_into_profile(
        profile_memory=profile,
        payload=ProjectSelfMemoryPayload(
            name="ifome",
            summary="求职信息流 Agent",
            role="builder",
            tech_stack=["FastAPI", "LangGraph"],
            highlight_points=["显式状态"],
            interview_story_hooks=["为什么单 Agent"],
        ),
    )

    assert len(merged.projects) == 1
    assert merged.projects[0].name == "ifome"


def test_project_self_memory_requires_feature_flag() -> None:
    """Experimental project memory writes should be blocked when the flag is off."""

    services = ApiServiceContainer(
        settings=AppSettings(feature_flags=FeatureFlags(enable_project_self_memory=False))
    )

    with pytest.raises(PermissionError):
        services.write_project_self_memory(
            user_id="user_1",
            workspace_id="ws_1",
            payload=ProjectSelfMemoryPayload(
                name="ifome",
                summary="求职信息流 Agent",
                role="builder",
                tech_stack=["FastAPI"],
                highlight_points=["显式状态"],
                interview_story_hooks=["为什么单 Agent"],
            ),
        )
