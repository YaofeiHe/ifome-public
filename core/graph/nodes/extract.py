"""Extract node implementation."""

from __future__ import annotations

from datetime import datetime
import re

from core.extraction.live_llm import extract_signal_with_llm
from core.extraction.parse import (
    build_summary,
    derive_signal_tags,
    extract_city,
    extract_company,
    extract_datetime,
    extract_role,
    extract_url,
    infer_location_note,
)
from core.graph.nodes.base import WorkflowNode
from core.runtime.time import now_in_project_timezone
from core.schemas import (
    AgentState,
    ContentCategory,
    EvidenceSpan,
    ExtractedJobSignal,
    WorkflowIssue,
)

GENERIC_RELATIONSHIP_TAGS = {
    "暑期实习",
    "日常实习",
    "实习",
    "校招",
    "秋招",
    "春招",
    "社招",
    "笔试",
    "面试",
    "内推",
    "统一输入卡片",
    "未命名岗位",
}


def _parse_iso_datetime(value: object) -> datetime | None:
    """Parse one ISO datetime string from source metadata if present."""

    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _looks_like_role(value: str) -> bool:
    return bool(re.search(r"(工程师|分析师|经理|研究员|运营|设计师)", value))


def _looks_like_noisy_company(value: str | None) -> bool:
    if not value:
        return True
    return any(keyword in value for keyword in ("登录", "官网", "公众号", "当前岗位片段"))


def _derive_company_from_metadata(source_metadata: dict) -> str | None:
    """Recover the business line from semantic tags before trusting noisy text."""

    primary_unit = str(source_metadata.get("primary_unit") or "").strip()
    if primary_unit:
        return primary_unit

    for raw_value in source_metadata.get("semantic_tags", []):
        value = str(raw_value).strip()
        if (
            not value
            or value in GENERIC_RELATIONSHIP_TAGS
            or value == str(source_metadata.get("relationship_family") or "").strip()
            or value == str(source_metadata.get("relationship_stage") or "").strip()
            or value == str(source_metadata.get("identity_tag") or "").strip()
            or _looks_like_role(value)
        ):
            continue
        return value

    title = str(source_metadata.get("source_title") or "").strip()
    for piece in title.split("-"):
        value = piece.strip()
        if (
            not value
            or value in GENERIC_RELATIONSHIP_TAGS
            or value == str(source_metadata.get("relationship_family") or "").strip()
            or value == str(source_metadata.get("relationship_stage") or "").strip()
            or value == str(source_metadata.get("identity_tag") or "").strip()
            or _looks_like_role(value)
        ):
            continue
        return value
    return None


def _derive_role_from_metadata(source_metadata: dict) -> str | None:
    """Prefer the per-card role variant generated during section expansion."""

    role_variant = str(source_metadata.get("role_variant") or "").strip()
    if role_variant:
        return role_variant

    for raw_value in source_metadata.get("semantic_tags", []):
        value = str(raw_value).strip()
        if value and _looks_like_role(value):
            return value
    return None


class ExtractNode(WorkflowNode):
    """
    Parse structured recruiting fields from the normalized item.

    Input fields:
    - `normalized_item.normalized_text`
    - `classified_category`
    - `trace_id`

    Output fields:
    - `extracted_signal`
    - `model_routing["extract"]`

    Failure strategy:
    - Missing `normalized_item` leads to partial-state failure.
    - Low-confidence fields are left as `None` instead of fabricated.
    """

    name = "extract"

    def _run_impl(self, state: AgentState) -> AgentState:
        if state.normalized_item is None:
            raise ValueError("normalized_item is required before extract.")

        route = self.dependencies.model_router.select("extract", "low")
        state.model_routing[self.name] = route
        if self.dependencies.llm_gateway.is_available(route):
            try:
                state.extracted_signal = extract_signal_with_llm(
                    state=state,
                    route=route,
                    llm_gateway=self.dependencies.llm_gateway,
                    prompt_loader=self.dependencies.prompt_loader,
                )
                return state
            except Exception as exc:
                state.issues.append(
                    WorkflowIssue(
                        node_name=self.name,
                        severity="warning",
                        message="Live extract failed. Fallback heuristic applied.",
                        retryable=True,
                        details={"route": route, "reason": str(exc)},
                        observed_at=now_in_project_timezone(),
                    )
                )
                self.dependencies.trace_logger.warning(
                    "live_extract_fallback",
                    trace_id=state.trace_id,
                    route=route,
                    reason=str(exc),
                )

        text = state.normalized_item.normalized_text
        source_metadata = state.source_metadata or {}
        company = extract_company(text)
        role = extract_role(text)
        city = extract_city(text)
        extracted_time = extract_datetime(text)
        apply_url = extract_url(text)
        metadata_company = _derive_company_from_metadata(source_metadata)
        metadata_role = _derive_role_from_metadata(source_metadata)
        next_shared_exam_date = _parse_iso_datetime(source_metadata.get("next_shared_exam_date"))
        global_deadline = _parse_iso_datetime(source_metadata.get("global_deadline"))

        if metadata_company and (
            not company
            or company in {"各集团分开", "当前岗位片段："}
            or _looks_like_noisy_company(company)
        ):
            company = metadata_company
        if metadata_role:
            role = metadata_role
        location_note = infer_location_note(
            text=text,
            city=city,
            source_metadata=source_metadata,
        )

        category = state.classified_category or ContentCategory.UNKNOWN
        ddl = (
            extracted_time
            if category in {ContentCategory.JOB_POSTING, ContentCategory.REFERRAL}
            else None
        )
        if category in {ContentCategory.JOB_POSTING, ContentCategory.REFERRAL} and global_deadline is not None:
            if extracted_time and extracted_time != global_deadline:
                source_metadata["job_specific_deadline"] = extracted_time.isoformat()
            ddl = global_deadline
        elif ddl is None:
            ddl = next_shared_exam_date
        event_time = extracted_time if category == ContentCategory.TALK_EVENT else None
        interview_time = (
            extracted_time if category == ContentCategory.INTERVIEW_NOTICE else None
        )

        evidence: list[EvidenceSpan] = []
        if company:
            evidence.append(EvidenceSpan(field_name="company", snippet=company, confidence=0.7))
        if role:
            evidence.append(EvidenceSpan(field_name="role", snippet=role, confidence=0.8))
        if city:
            evidence.append(EvidenceSpan(field_name="city", snippet=city, confidence=0.75))
        if ddl and next_shared_exam_date and ddl == next_shared_exam_date:
            evidence.append(
                EvidenceSpan(
                    field_name="ddl",
                    snippet=f"共享笔试日期：{ddl.isoformat()}",
                    confidence=0.72,
                )
            )

        summary = (
            str(source_metadata.get("source_title")).strip()
            if source_metadata.get("source_title")
            else build_summary(company, role, city)
        )
        confidence = min(1.0, 0.2 + 0.2 * len(evidence) + (0.2 if apply_url else 0.0))

        state.extracted_signal = ExtractedJobSignal(
            user_id=state.user_id,
            workspace_id=state.workspace_id,
            source_item_id=state.normalized_item.id,
            trace_id=state.trace_id,
            category=category,
            company=company,
            role=role,
            city=city,
            location_note=location_note,
            interview_location=city if category == ContentCategory.INTERVIEW_NOTICE else None,
            ddl=ddl,
            event_time=event_time,
            interview_time=interview_time,
            apply_url=apply_url,
            source_url=state.source_ref if state.source_type.value == "link" else None,
            summary_one_line=summary,
            raw_text_excerpt=text[:280],
            tags=derive_signal_tags(
                text=text,
                company=company,
                role=role,
                city=city,
                source_metadata=source_metadata,
            ),
            confidence=confidence,
            evidence=evidence,
            extracted_at=now_in_project_timezone(),
        )
        return state
