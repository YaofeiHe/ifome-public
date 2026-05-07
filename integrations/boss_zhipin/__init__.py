"""Boss 直聘 connector helpers."""

from integrations.boss_zhipin.contracts import (
    BossZhipinConversationMessage,
    BossZhipinConversationPayload,
    BossZhipinJobPayload,
)
from integrations.boss_zhipin.mcp_readonly import (
    READ_ONLY_BOSS_MCP_TOOLS,
    BossMCPReadOnlyError,
    BossZhipinMCPReadOnlyClient,
    search_envelope_to_job_payloads,
    search_item_identity,
    search_item_to_job_payload,
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
    "READ_ONLY_BOSS_MCP_TOOLS",
    "BossMCPReadOnlyError",
    "BossZhipinMCPReadOnlyClient",
    "render_conversation_metadata",
    "render_conversation_text",
    "render_job_posting_metadata",
    "render_job_posting_text",
    "search_envelope_to_job_payloads",
    "search_item_identity",
    "search_item_to_job_payload",
]
