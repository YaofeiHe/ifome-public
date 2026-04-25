"""Extract node implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from core.extraction.live_llm import assess_job_title_with_llm, extract_signal_with_llm
from core.extraction.prompt_context import PromptReference, collect_prompt_references
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


@dataclass(frozen=True)
class HeuristicExtractionAssessment:
    """Rule-first extraction result and the decision about whether LLM is still needed."""

    signal: ExtractedJobSignal
    completeness_score: float
    reasons: list[str]
    should_consult_llm: bool


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
    return any(
        keyword in value
        for keyword in ("登录", "官网", "公众号", "当前岗位片段", "请分析", "帮我看看", "岗位标题")
    )


def _is_placeholder_title(value: str | None) -> bool:
    """Return whether one source title is a generic fallback placeholder."""

    if not value:
        return True
    normalized = value.strip()
    if not normalized:
        return True
    placeholder_markers = (
        "统一输入卡片",
        "链接待解析卡片",
        "未命名岗位",
        "岗位标题：统一输入卡片",
    )
    return any(marker in normalized for marker in placeholder_markers)


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
        embed_route = self.dependencies.model_router.select("embed", "low")
        assessment = self._build_heuristic_assessment(state)
        state.model_routing[self.name] = "rule_first"
        title_assessment = self._assess_job_title_if_needed(state, route)
        should_consult_llm = assessment.should_consult_llm or (
            title_assessment is not None and not title_assessment["is_complete_segment"]
        )

        if not should_consult_llm or not self.dependencies.llm_gateway.is_available(route):
            state.extracted_signal = assessment.signal
            state.source_metadata["extraction_rule_assessment"] = {
                "completeness_score": round(assessment.completeness_score, 4),
                "reasons": assessment.reasons,
            }
            if title_assessment is not None:
                state.source_metadata["title_llm_assessment"] = title_assessment
            return state

        prompt_references = collect_prompt_references(
            user_id=state.user_id,
            workspace_id=state.workspace_id,
            current_item_id=state.normalized_item.id,
            query_text=state.normalized_item.normalized_text,
            source_metadata=state.source_metadata,
            workflow_repository=self.dependencies.workflow_repository,
            search_client=self.dependencies.search_client,
            embedding_gateway=self.dependencies.embedding_gateway,
            vector_store=self.dependencies.vector_store,
            embed_route=embed_route,
            category_hint=(state.classified_category or ContentCategory.UNKNOWN).value,
        )
        state.model_routing[self.name] = f"rule_first_then_{route}"

        try:
            llm_signal = extract_signal_with_llm(
                state=state,
                rule_extraction=self._signal_to_prompt_payload(assessment.signal, assessment),
                prompt_references=prompt_references,
                route=route,
                llm_gateway=self.dependencies.llm_gateway,
                prompt_loader=self.dependencies.prompt_loader,
            )
            state.extracted_signal = self._merge_signals(
                state=state,
                heuristic_signal=assessment.signal,
                llm_signal=llm_signal,
                prompt_references=prompt_references,
            )
            self._refresh_generated_title_if_needed(
                state=state,
                title_assessment=title_assessment,
            )
            state.source_metadata["extraction_rule_assessment"] = {
                "completeness_score": round(assessment.completeness_score, 4),
                "reasons": assessment.reasons,
            }
            state.source_metadata["extraction_prompt_references"] = [
                reference.to_payload() for reference in prompt_references
            ]
            if title_assessment is not None:
                state.source_metadata["title_llm_assessment"] = title_assessment
            return state
        except Exception as exc:
            state.issues.append(
                WorkflowIssue(
                    node_name=self.name,
                    severity="warning",
                    message="Live extract failed. Rule-first fallback applied.",
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

        state.extracted_signal = assessment.signal
        return state

    def _assess_job_title_if_needed(self, state: AgentState, route: str) -> dict[str, Any] | None:
        """Use one lightweight LLM step to judge whether a job-facing title is complete."""

        if state.normalized_item is None:
            return None
        if state.classified_category not in {ContentCategory.JOB_POSTING, ContentCategory.REFERRAL}:
            return None
        if not self.dependencies.llm_gateway.is_available(route):
            return None

        source_title = str(
            state.normalized_item.source_title or state.source_metadata.get("source_title") or ""
        ).strip()
        if not source_title:
            return None

        try:
            result = assess_job_title_with_llm(
                normalized_text=state.normalized_item.normalized_text,
                source_title=source_title,
                source_metadata=state.source_metadata,
                route=route,
                llm_gateway=self.dependencies.llm_gateway,
                prompt_loader=self.dependencies.prompt_loader,
            )
            return {
                "is_complete_segment": result.is_complete_segment,
                "confidence": result.confidence,
                "reason": result.reason,
            }
        except Exception:
            return None

    def _build_heuristic_assessment(self, state: AgentState) -> HeuristicExtractionAssessment:
        """Extract fields with rules first and decide whether LLM is still needed."""

        text = state.normalized_item.normalized_text
        source_metadata = state.source_metadata or {}
        company = extract_company(text)
        role = extract_role(text)
        city = extract_city(text)
        extracted_time = extract_datetime(text)
        apply_url = extract_url(text)
        if _looks_like_noisy_company(company):
            company = None
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

        source_title = str(source_metadata.get("source_title") or "").strip()
        summary = (
            build_summary(company, role, city)
            if _is_placeholder_title(source_title)
            else source_title
        )
        confidence = min(1.0, 0.2 + 0.2 * len(evidence) + (0.2 if apply_url else 0.0))
        completeness_score, reasons = self._score_extraction_completeness(
            category=category,
            company=company,
            role=role,
            city=city,
            location_note=location_note,
            ddl=ddl,
            event_time=event_time,
            interview_time=interview_time,
            apply_url=apply_url,
            summary=summary,
            source_metadata=source_metadata,
        )

        signal = ExtractedJobSignal(
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
        should_consult_llm = (
            completeness_score < 0.76
            or category in {ContentCategory.UNKNOWN, ContentCategory.GENERAL_UPDATE}
            or (
                category in {ContentCategory.JOB_POSTING, ContentCategory.REFERRAL}
                and not role
            )
            or (
                category == ContentCategory.GENERAL_UPDATE
                and bool(source_metadata.get("market_watch") or source_metadata.get("search_references"))
            )
        )
        return HeuristicExtractionAssessment(
            signal=signal,
            completeness_score=completeness_score,
            reasons=reasons,
            should_consult_llm=should_consult_llm,
        )

    def _score_extraction_completeness(
        self,
        *,
        category: ContentCategory,
        company: str | None,
        role: str | None,
        city: str | None,
        location_note: str | None,
        ddl: datetime | None,
        event_time: datetime | None,
        interview_time: datetime | None,
        apply_url: str | None,
        summary: str,
        source_metadata: dict[str, Any],
    ) -> tuple[float, list[str]]:
        """Score how complete the rule-based extraction already is."""

        score = 0.16
        reasons: list[str] = []
        if company:
            score += 0.18
            reasons.append("company extracted")
        if role:
            score += 0.22
            reasons.append("role extracted")
        if city or location_note:
            score += 0.12
            reasons.append("location inferred")
        if summary and not _is_placeholder_title(summary):
            score += 0.12
            reasons.append("summary stabilized")
        if apply_url:
            score += 0.12
            reasons.append("apply url found")
        if category in {ContentCategory.JOB_POSTING, ContentCategory.REFERRAL} and ddl:
            score += 0.12
            reasons.append("deadline found")
        if category == ContentCategory.INTERVIEW_NOTICE and interview_time:
            score += 0.16
            reasons.append("interview time found")
        if category == ContentCategory.TALK_EVENT and event_time:
            score += 0.16
            reasons.append("event time found")
        if category == ContentCategory.GENERAL_UPDATE and source_metadata.get("market_watch"):
            score += 0.12
            reasons.append("market update metadata present")
        return min(score, 0.99), reasons or ["rule extraction remained partial"]

    def _signal_to_prompt_payload(
        self,
        signal: ExtractedJobSignal,
        assessment: HeuristicExtractionAssessment,
    ) -> dict[str, Any]:
        """Serialize the rule-first extraction for prompt grounding."""

        return {
            "category": signal.category.value,
            "company": signal.company,
            "role": signal.role,
            "city": signal.city,
            "location_note": signal.location_note,
            "ddl": signal.ddl.isoformat() if signal.ddl else None,
            "event_time": signal.event_time.isoformat() if signal.event_time else None,
            "interview_time": signal.interview_time.isoformat() if signal.interview_time else None,
            "apply_url": signal.apply_url,
            "summary_one_line": signal.summary_one_line,
            "confidence": signal.confidence,
            "completeness_score": round(assessment.completeness_score, 4),
            "assessment_reasons": assessment.reasons,
            "tags": signal.tags,
        }

    def _merge_signals(
        self,
        *,
        state: AgentState,
        heuristic_signal: ExtractedJobSignal,
        llm_signal: ExtractedJobSignal,
        prompt_references: list[PromptReference],
    ) -> ExtractedJobSignal:
        """Merge rule-first extraction with LLM补全结果 while keeping stable fields."""

        final_category = (
            llm_signal.category
            if llm_signal.category != ContentCategory.UNKNOWN
            else heuristic_signal.category
        )
        final_company = llm_signal.company or heuristic_signal.company
        final_role = llm_signal.role or heuristic_signal.role
        final_city = llm_signal.city or heuristic_signal.city
        final_location_note = heuristic_signal.location_note
        if final_city:
            final_location_note = None
        final_summary = (
            llm_signal.summary_one_line
            if llm_signal.summary_one_line and not _is_placeholder_title(llm_signal.summary_one_line)
            else heuristic_signal.summary_one_line
        )
        merged_tags = list(
            dict.fromkeys(
                [
                    *heuristic_signal.tags,
                    *llm_signal.tags,
                    *[reference.source_label for reference in prompt_references[:2]],
                ]
            )
        )[:8]

        return ExtractedJobSignal(
            user_id=state.user_id,
            workspace_id=state.workspace_id,
            source_item_id=state.normalized_item.id,
            trace_id=state.trace_id,
            category=final_category,
            company=final_company,
            role=final_role,
            city=final_city,
            location_note=final_location_note,
            interview_location=llm_signal.interview_location or heuristic_signal.interview_location,
            ddl=llm_signal.ddl or heuristic_signal.ddl,
            event_time=llm_signal.event_time or heuristic_signal.event_time,
            interview_time=llm_signal.interview_time or heuristic_signal.interview_time,
            apply_url=llm_signal.apply_url or heuristic_signal.apply_url,
            source_url=heuristic_signal.source_url or llm_signal.source_url,
            summary_one_line=final_summary,
            raw_text_excerpt=heuristic_signal.raw_text_excerpt,
            tags=merged_tags,
            confidence=max(heuristic_signal.confidence, llm_signal.confidence),
            evidence=llm_signal.evidence or heuristic_signal.evidence,
            extracted_at=now_in_project_timezone(),
        )

    def _refresh_generated_title_if_needed(
        self,
        *,
        state: AgentState,
        title_assessment: dict[str, Any] | None,
    ) -> None:
        """Replace one incomplete source title with the LLM-repaired summary after extraction."""

        if state.normalized_item is None or state.extracted_signal is None:
            return
        if title_assessment is None or title_assessment.get("is_complete_segment"):
            return

        generated_title = str(state.extracted_signal.summary_one_line or "").strip()
        if not generated_title or _is_placeholder_title(generated_title):
            return
        state.normalized_item.source_title = generated_title
        state.source_metadata["source_title"] = generated_title
