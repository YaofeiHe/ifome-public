"""Translate Boss 直聘 payloads into workflow-friendly text and metadata."""

from __future__ import annotations

from integrations.boss_zhipin.contracts import (
    BossZhipinConversationPayload,
    BossZhipinJobPayload,
)


def render_job_posting_text(payload: BossZhipinJobPayload) -> str:
    """Render one Boss 直聘岗位详情为统一文本输入。"""

    lines = [
        "来源平台：Boss直聘",
        f"公司：{payload.company_name}",
        f"岗位：{payload.role_title}",
    ]
    if payload.city:
        lines.append(f"地点：{payload.city}")
    if payload.salary_range:
        lines.append(f"薪资：{payload.salary_range}")
    if payload.experience_requirement:
        lines.append(f"经验要求：{payload.experience_requirement}")
    if payload.education_requirement:
        lines.append(f"学历要求：{payload.education_requirement}")
    if payload.apply_deadline:
        lines.append(f"投递截止：{payload.apply_deadline.isoformat()}")
    if payload.hr_name:
        hr_line = f"HR：{payload.hr_name}"
        if payload.hr_title:
            hr_line += f" / {payload.hr_title}"
        lines.append(hr_line)
    if payload.tags:
        lines.append(f"标签：{', '.join(payload.tags)}")
    if payload.job_url:
        lines.append(f"岗位链接：{payload.job_url}")
    lines.append("岗位描述：")
    lines.append(payload.job_description)
    return "\n".join(lines)


def render_job_posting_metadata(payload: BossZhipinJobPayload) -> dict[str, str | list[str]]:
    """Build metadata attached to a Boss 直聘岗位 ingest run."""

    metadata: dict[str, str | list[str]] = {
        "connector": "boss_zhipin",
        "connector_entity": "job_posting",
        "boss_job_id": payload.job_id,
    }
    if payload.job_url:
        metadata["job_url"] = payload.job_url
    if payload.tags:
        metadata["boss_tags"] = payload.tags
    return metadata


def render_conversation_text(payload: BossZhipinConversationPayload) -> str:
    """Render one Boss 直聘 HR 对话线程为统一文本输入。"""

    lines = ["来源平台：Boss直聘", "内容类型：HR对话"]
    if payload.company_name:
        lines.append(f"公司：{payload.company_name}")
    if payload.role_title:
        lines.append(f"岗位：{payload.role_title}")
    if payload.city:
        lines.append(f"地点：{payload.city}")
    if payload.hr_name:
        lines.append(f"HR：{payload.hr_name}")
    lines.append("对话记录：")

    for message in payload.messages:
        prefix = {
            "candidate": "候选人",
            "hr": "HR",
            "system": "系统",
        }[message.sender_role]
        if message.sent_at:
            lines.append(f"{prefix} [{message.sent_at.isoformat()}]：{message.text}")
        else:
            lines.append(f"{prefix}：{message.text}")
    return "\n".join(lines)


def render_conversation_metadata(
    payload: BossZhipinConversationPayload,
) -> dict[str, str | int]:
    """Build metadata attached to a Boss 直聘 HR conversation ingest run."""

    metadata: dict[str, str | int] = {
        "connector": "boss_zhipin",
        "connector_entity": "conversation",
        "boss_thread_id": payload.thread_id,
        "message_count": len(payload.messages),
    }
    if payload.job_id:
        metadata["boss_job_id"] = payload.job_id
    if payload.job_url:
        metadata["job_url"] = payload.job_url
    return metadata
