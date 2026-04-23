"""Minimal workflow integration tests."""

from __future__ import annotations

from core.graph import JobWorkflow, create_initial_state
from core.schemas import SourceType, WorkflowStatus


def test_sequential_workflow_runs_end_to_end() -> None:
    """The minimal workflow should complete and render one card."""

    workflow = JobWorkflow()
    state = create_initial_state(
        raw_input=(
            "阿里云招聘 后端工程师，工作地点上海，投递截止 2026年05月01日 18:00，"
            "投递链接 https://example.com/apply"
        ),
        source_type=SourceType.TEXT,
        user_id="demo_user",
        workspace_id="demo_workspace",
    )

    result = workflow.run_sequential(state)

    assert result.status == WorkflowStatus.COMPLETED
    assert result.normalized_item is not None
    assert result.extracted_signal is not None
    assert result.score_result is not None
    assert result.render_card is not None
    assert len(result.node_history) == 9
