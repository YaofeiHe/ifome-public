"""Render node implementation."""

from __future__ import annotations

from datetime import datetime

from core.graph.nodes.base import WorkflowNode
from core.runtime.time import now_in_project_timezone
from core.schemas import ContentCategory
from core.schemas import AgentState, RenderedItemCard, WorkflowStatus


def _parse_message_time(value) -> datetime | None:
    """Parse source metadata message times into timezone-aware datetimes."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(
            tzinfo=now_in_project_timezone().tzinfo
        )
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=now_in_project_timezone().tzinfo)
    return parsed


class RenderNode(WorkflowNode):
    """
    Produce a minimal card payload for the Web layer.

    Input fields:
    - `normalized_item`
    - `extracted_signal`
    - `score_result`

    Output fields:
    - `render_card`
    - `status`

    Failure strategy:
    - Missing prerequisites produce partial-state failure.
    """

    name = "render"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.normalized_item is None:
            raise ValueError("normalized_item is required before render.")

        extracted = state.extracted_signal
        normalized = state.normalized_item
        summary = (
            extracted.summary_one_line
            if extracted and extracted.summary_one_line
            else normalized.source_title
            or normalized.normalized_text[:80]
            or normalized.id
        )

        state.render_card = RenderedItemCard(
            item_id=normalized.id,
            summary_one_line=summary,
            company=extracted.company if extracted else None,
            role=extracted.role if extracted else None,
            city=extracted.city if extracted else None,
            location_note=extracted.location_note if extracted else None,
            ddl=extracted.ddl if extracted else None,
            interview_time=extracted.interview_time if extracted else None,
            event_time=extracted.event_time if extracted else None,
            priority=state.score_result.priority if state.score_result else None,
            content_category=(
                extracted.category
                if extracted
                else state.classified_category or ContentCategory.UNKNOWN
            ),
            source_type=state.source_type,
            workflow_status=state.status,
            source_ref=state.source_ref,
            updated_at=now_in_project_timezone(),
            message_time=_parse_message_time(
                state.source_metadata.get("message_time")
                or state.source_metadata.get("published_at")
            )
            or normalized.created_at,
            generated_at=normalized.created_at,
            ai_score=round(state.score_result.total_score, 4) if state.score_result else None,
            insight_summary=summary,
            advice=state.score_result.reasoning if state.score_result else None,
            is_market_signal=bool(state.source_metadata.get("market_watch")),
            market_group_kind=str(state.source_metadata.get("market_group_kind") or "") or None,
            market_parent_item_id=str(state.source_metadata.get("market_parent_item_id") or "") or None,
            market_child_item_ids=list(state.source_metadata.get("market_child_item_ids", [])),
            market_child_previews=list(state.source_metadata.get("market_child_previews", [])),
            tags=extracted.tags if extracted else [],
        )
        if extracted is not None:
            state.status = WorkflowStatus.COMPLETED
        elif state.status == WorkflowStatus.PENDING:
            state.status = WorkflowStatus.PARTIAL
        state.render_card.workflow_status = state.status
        return state
