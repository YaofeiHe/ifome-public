"""Boss 直聘 connector helpers."""

from integrations.boss_zhipin.contracts import (
    BossZhipinConversationMessage,
    BossZhipinConversationPayload,
    BossZhipinJobPayload,
)
from integrations.boss_zhipin.translator import (
    render_conversation_metadata,
    render_conversation_text,
    render_job_posting_metadata,
    render_job_posting_text,
)

__all__ = [
    "BossZhipinConversationMessage",
    "BossZhipinConversationPayload",
    "BossZhipinJobPayload",
    "render_conversation_metadata",
    "render_conversation_text",
    "render_job_posting_metadata",
    "render_job_posting_text",
]
