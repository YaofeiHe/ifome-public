"""Heuristic matching and scoring helpers for the minimal workflow."""

from __future__ import annotations

from datetime import datetime

from core.runtime.time import now_in_project_timezone
from core.schemas import (
    ExtractedJobSignal,
    MatchProfileResult,
    PriorityLevel,
    ProfileMemory,
    RecommendedAction,
    ScoreResult,
)


def match_against_profile(
    signal: ExtractedJobSignal, profile: ProfileMemory
) -> MatchProfileResult:
    """Compute a lightweight profile match result using explicit heuristics."""

    text = " ".join(
        [
            signal.company or "",
            signal.role or "",
            signal.city or "",
            signal.summary_one_line,
            signal.raw_text_excerpt or "",
            " ".join(signal.tags),
        ]
    ).lower()

    matched_roles = [role for role in profile.target_roles if role.lower() in text]
    matched_domains = [
        domain for domain in profile.priority_domains if domain.lower() in text
    ]
    matched_skills = [skill for skill in profile.skills if skill.lower() in text]
    blockers: list[str] = []

    if signal.company and signal.company in profile.excluded_companies:
        blockers.append("命中排除公司")
    if (
        signal.city
        and profile.location_preferences
        and signal.city not in profile.location_preferences
        and "远程" not in profile.location_preferences
    ):
        blockers.append("地点不在偏好范围")

    fit_score = min(
        1.0,
        0.25 * len(matched_roles)
        + 0.2 * len(matched_domains)
        + 0.1 * len(matched_skills)
        - 0.25 * len(blockers),
    )
    fit_score = max(0.0, fit_score)

    rationale_parts = []
    if matched_roles:
        rationale_parts.append(f"匹配目标岗位：{', '.join(matched_roles)}")
    if matched_domains:
        rationale_parts.append(f"匹配重点方向：{', '.join(matched_domains)}")
    if matched_skills:
        rationale_parts.append(f"命中技能：{', '.join(matched_skills)}")
    if blockers:
        rationale_parts.append(f"阻塞项：{', '.join(blockers)}")
    if not rationale_parts:
        rationale_parts.append("当前仅命中基础字段，需后续接入 LLM 语义匹配增强。")

    return MatchProfileResult(
        matched_roles=matched_roles,
        matched_domains=matched_domains,
        matched_skills=matched_skills,
        blockers=blockers,
        rationale="；".join(rationale_parts),
        fit_score=fit_score,
    )


def compute_urgency(reference_time: datetime | None) -> float:
    """Convert a deadline-like timestamp into an urgency score."""

    if reference_time is None:
        return 0.15

    delta = reference_time - now_in_project_timezone()
    hours_left = delta.total_seconds() / 3600

    if hours_left <= 0:
        return 1.0
    if hours_left <= 24:
        return 0.95
    if hours_left <= 72:
        return 0.75
    if hours_left <= 168:
        return 0.55
    return 0.25


def score_signal(
    signal: ExtractedJobSignal, match_result: MatchProfileResult
) -> ScoreResult:
    """Combine profile fit and urgency into a user-facing ranking result."""

    reference_time = signal.ddl or signal.interview_time or signal.event_time
    urgency_score = compute_urgency(reference_time)
    relevance_score = match_result.fit_score
    total_score = min(1.0, 0.65 * relevance_score + 0.35 * urgency_score)

    if total_score >= 0.8:
        priority = PriorityLevel.P0
        action = RecommendedAction.APPLY_NOW
    elif total_score >= 0.65:
        priority = PriorityLevel.P1
        action = RecommendedAction.PREPARE_INTERVIEW
    elif total_score >= 0.45:
        priority = PriorityLevel.P2
        action = RecommendedAction.SAVE_FOR_LATER
    else:
        priority = PriorityLevel.P3
        action = RecommendedAction.TRACK_ONLY

    if match_result.blockers and total_score < 0.35:
        action = RecommendedAction.IGNORE

    reasoning = (
        f"匹配分 {relevance_score:.2f}，紧急度 {urgency_score:.2f}。"
        f"{match_result.rationale}"
    )

    return ScoreResult(
        relevance_score=relevance_score,
        urgency_score=urgency_score,
        total_score=total_score,
        priority=priority,
        recommended_action=action,
        reasoning=reasoning,
    )
