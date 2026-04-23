"""Boss 直聘 connector payload contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.schemas.base import ensure_timezone_aware


class BossZhipinJobPayload(BaseModel):
    """Minimal Boss 直聘岗位详情输入模型。"""

    job_id: str = Field(description="Boss 直聘岗位 id。")
    job_url: str | None = Field(default=None, description="岗位详情链接。")
    company_name: str = Field(description="公司名称。")
    role_title: str = Field(description="岗位名称。")
    city: str | None = Field(default=None, description="工作地点。")
    salary_range: str | None = Field(default=None, description="薪资范围。")
    experience_requirement: str | None = Field(default=None, description="经验要求。")
    education_requirement: str | None = Field(default=None, description="学历要求。")
    apply_deadline: datetime | None = Field(default=None, description="投递截止时间。")
    job_description: str = Field(description="岗位描述正文。")
    tags: list[str] = Field(default_factory=list, description="平台标签。")
    hr_name: str | None = Field(default=None, description="对应 HR 名称。")
    hr_title: str | None = Field(default=None, description="HR 职位头衔。")
    published_at: datetime | None = Field(default=None, description="发布时间。")

    @field_validator("apply_deadline", "published_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Keep connector timestamps aligned with project-wide timezone policy."""

        return ensure_timezone_aware(value, info.field_name)


class BossZhipinConversationMessage(BaseModel):
    """One Boss 直聘对话消息。"""

    sender_role: Literal["candidate", "hr", "system"] = Field(description="消息发送方。")
    text: str = Field(description="消息正文。")
    sent_at: datetime | None = Field(default=None, description="消息时间。")

    @field_validator("sent_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info) -> datetime | None:
        """Keep connector timestamps aligned with project-wide timezone policy."""

        return ensure_timezone_aware(value, info.field_name)


class BossZhipinConversationPayload(BaseModel):
    """Minimal Boss 直聘 HR 对话线程输入模型。"""

    thread_id: str = Field(description="会话线程 id。")
    job_id: str | None = Field(default=None, description="关联岗位 id。")
    job_url: str | None = Field(default=None, description="关联岗位链接。")
    company_name: str | None = Field(default=None, description="公司名称。")
    role_title: str | None = Field(default=None, description="关联岗位名称。")
    city: str | None = Field(default=None, description="岗位地点。")
    hr_name: str | None = Field(default=None, description="HR 名称。")
    messages: list[BossZhipinConversationMessage] = Field(
        default_factory=list, description="对话消息列表。"
    )
