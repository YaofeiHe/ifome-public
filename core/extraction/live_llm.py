"""Live LLM-backed classify and extract helpers with schema validation."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from core.extraction.parse import build_summary
from core.runtime.time import now_in_project_timezone
from core.schemas import (
    AgentState,
    ContentCategory,
    EvidenceSpan,
    ExtractedJobSignal,
    SchemaModel,
    SourceType,
)
from core.tools import PromptLoader


class LLMClassificationResult(SchemaModel):
    """Validated JSON contract expected back from the live classify prompt."""

    category: ContentCategory = Field(description="One category from the shared enum.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(description="Compact explanation for the chosen category.")


class LLMExtractionResult(SchemaModel):
    """Validated JSON contract expected back from the live extract prompt."""

    category: ContentCategory | None = Field(default=None)
    company: str | None = Field(default=None)
    role: str | None = Field(default=None)
    city: str | None = Field(default=None)
    interview_location: str | None = Field(default=None)
    ddl: datetime | None = Field(default=None)
    event_time: datetime | None = Field(default=None)
    interview_time: datetime | None = Field(default=None)
    apply_url: str | None = Field(default=None)
    summary_one_line: str | None = Field(default=None)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpan] = Field(default_factory=list)


def classify_text_with_llm(
    *,
    normalized_text: str,
    source_type: SourceType,
    route: str,
    llm_gateway,
    prompt_loader: PromptLoader,
) -> LLMClassificationResult:
    """Classify one normalized item using the configured live LLM route."""

    prompt = prompt_loader.load("classify")
    system_prompt = (
        f"{prompt}\n\n"
        "补充约束：\n"
        "- 只输出一个 JSON 对象，不要输出 Markdown。\n"
        "- `category` 只能取这些值之一："
        "job_posting, interview_notice, talk_event, referral, general_update, noise, unknown。\n"
        "- `confidence` 必须是 0 到 1 的小数。\n"
        "- `reason` 用一句中文解释。"
    )
    payload = {
        "source_type": source_type.value,
        "normalized_text": normalized_text,
    }
    response = llm_gateway.complete_json(
        route=route,
        task_name="classify",
        system_prompt=system_prompt,
        user_payload=payload,
    )
    return LLMClassificationResult.model_validate(response)


def extract_signal_with_llm(
    *,
    state: AgentState,
    route: str,
    llm_gateway,
    prompt_loader: PromptLoader,
) -> ExtractedJobSignal:
    """Extract one structured signal from the normalized item using a live LLM."""

    if state.normalized_item is None:
        raise ValueError("normalized_item is required before live extraction.")

    prompt = prompt_loader.load("extract")
    system_prompt = (
        f"{prompt}\n\n"
        "补充约束：\n"
        "- 只输出一个 JSON 对象，不要输出 Markdown。\n"
        "- 时间字段如果能确定，必须输出带时区的 ISO 8601，例如 2026-05-01T18:00:00+08:00。\n"
        "- `category` 如果输出，必须来自共享枚举："
        "job_posting, interview_notice, talk_event, referral, general_update, noise, unknown。\n"
        "- `evidence` 需要是数组，每项包含 `field_name`, `snippet`, `confidence`。\n"
        "- 如果无法确定字段，请返回 null，不要编造。"
    )
    payload = {
        "source_type": state.source_type.value,
        "source_ref": state.source_ref,
        "classified_category": (
            state.classified_category.value if state.classified_category else None
        ),
        "normalized_text": state.normalized_item.normalized_text,
    }
    response = llm_gateway.complete_json(
        route=route,
        task_name="extract",
        system_prompt=system_prompt,
        user_payload=payload,
    )
    parsed = LLMExtractionResult.model_validate(response)

    category = parsed.category or state.classified_category or ContentCategory.UNKNOWN
    summary = parsed.summary_one_line or build_summary(
        parsed.company, parsed.role, parsed.city
    )

    return ExtractedJobSignal(
        user_id=state.user_id,
        workspace_id=state.workspace_id,
        source_item_id=state.normalized_item.id,
        trace_id=state.trace_id,
        category=category,
        company=parsed.company,
        role=parsed.role,
        city=parsed.city,
        interview_location=parsed.interview_location,
        ddl=parsed.ddl,
        event_time=parsed.event_time,
        interview_time=parsed.interview_time,
        apply_url=parsed.apply_url,
        source_url=state.source_ref if state.source_type == SourceType.LINK else None,
        summary_one_line=summary,
        raw_text_excerpt=state.normalized_item.normalized_text[:280],
        tags=parsed.tags,
        confidence=parsed.confidence,
        evidence=parsed.evidence,
        extracted_at=now_in_project_timezone(),
    )
