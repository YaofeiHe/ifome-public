"""Read-only MCP client helpers for boss-agent-cli.

This module intentionally exposes only read operations. It is the boundary that
keeps ifome from calling Boss chat, apply, greet, resume, or recruiter tools.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from integrations.boss_zhipin.contracts import BossZhipinJobPayload


READ_ONLY_BOSS_MCP_TOOLS = frozenset(
    {
        "boss_status",
        "boss_search",
        "boss_detail",
        "boss_cities",
    }
)


class BossMCPReadOnlyError(RuntimeError):
    """Raised when the Boss MCP client cannot safely complete a read-only call."""


@dataclass(frozen=True)
class BossZhipinMCPReadOnlyClient:
    """Small stdio MCP client for the boss-agent-cli read-only tool subset."""

    command: str = "boss-mcp"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    read_timeout_seconds: int = 60
    allowed_tools: frozenset[str] = READ_ONLY_BOSS_MCP_TOOLS

    def _assert_allowed(self, tool_name: str) -> None:
        if tool_name not in self.allowed_tools:
            allowed = ", ".join(sorted(self.allowed_tools))
            raise BossMCPReadOnlyError(
                f"Boss MCP tool '{tool_name}' is not allowed in read-only mode. "
                f"Allowed tools: {allowed}"
            )

    async def call_tool_async(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one allowed MCP tool and decode the JSON envelope returned by boss-agent-cli."""

        self._assert_allowed(tool_name)
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise BossMCPReadOnlyError(
                "The optional 'mcp' package is not installed. Install boss-agent-cli[mcp] "
                "in the runtime environment before enabling Boss read-only sync."
            ) from exc

        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        command_path = Path(self.command)
        if command_path.is_absolute():
            env["PATH"] = f"{command_path.parent}{os.pathsep}{env.get('PATH', '')}"

        server_params = StdioServerParameters(
            command=self.command,
            args=list(self.args),
            env=env,
        )
        timeout = timedelta(seconds=self.read_timeout_seconds)
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        tool_name,
                        arguments or {},
                        read_timeout_seconds=timeout,
                    )
        except Exception as exc:  # pragma: no cover - exercised through integration smoke runs.
            raise BossMCPReadOnlyError(f"Boss MCP call failed for {tool_name}: {exc}") from exc

        text_chunks: list[str] = []
        for content in result.content:
            text = getattr(content, "text", None)
            if text:
                text_chunks.append(text)
        raw_text = "\n".join(text_chunks).strip()
        if not raw_text:
            raise BossMCPReadOnlyError(f"Boss MCP tool {tool_name} returned no text content.")
        try:
            decoded = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise BossMCPReadOnlyError(
                f"Boss MCP tool {tool_name} returned non-JSON text."
            ) from exc
        if not isinstance(decoded, dict):
            raise BossMCPReadOnlyError(f"Boss MCP tool {tool_name} returned an unexpected payload.")
        return decoded

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Synchronously call one allowed MCP tool."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.call_tool_async(tool_name, arguments))
        raise BossMCPReadOnlyError(
            "Boss MCP sync calls cannot run inside an existing event loop. "
            "Use call_tool_async instead."
        )

    def status(self) -> dict[str, Any]:
        """Return the boss-agent-cli login status envelope."""

        return self.call_tool("boss_status", {})

    def search_jobs(
        self,
        *,
        query: str,
        city: str | None = None,
        salary: str | None = None,
        experience: str | None = None,
        education: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search jobs through boss_search without enabling any write operation."""

        arguments: dict[str, Any] = {"query": query, "page": page}
        for key, value in {
            "city": city,
            "salary": salary,
            "experience": experience,
            "education": education,
        }.items():
            if value:
                arguments[key] = value
        return self.call_tool("boss_search", arguments)

    def job_detail(self, *, security_id: str, job_id: str | None = None) -> dict[str, Any]:
        """Fetch one job detail through boss_detail."""

        arguments: dict[str, Any] = {"security_id": security_id}
        if job_id:
            arguments["job_id"] = job_id
        return self.call_tool("boss_detail", arguments)


def _compact_list(values: list[Any], *, limit: int = 12) -> list[str]:
    return [str(value).strip() for value in values[:limit] if str(value).strip()]


def build_job_description_from_search_item(item: dict[str, Any]) -> str:
    """Render a Boss search result into a conservative job-description surrogate."""

    lines = ["Boss 搜索结果摘要："]
    for label, key in (
        ("职位", "title"),
        ("公司", "company"),
        ("薪资", "salary"),
        ("地点", "city"),
        ("区域", "district"),
        ("经验", "experience"),
        ("学历", "education"),
        ("行业", "industry"),
        ("规模", "scale"),
        ("融资阶段", "stage"),
        ("招聘者", "boss_name"),
        ("招聘者头衔", "boss_title"),
        ("活跃状态", "boss_active"),
    ):
        value = item.get(key)
        if value:
            lines.append(f"{label}：{value}")

    skills = _compact_list(item.get("skills") or [])
    if skills:
        lines.append(f"技能：{', '.join(skills)}")
    welfare = _compact_list(item.get("welfare") or [])
    if welfare:
        lines.append(f"福利：{', '.join(welfare)}")
    if item.get("security_id"):
        lines.append(f"Boss security_id：{item['security_id']}")
    return "\n".join(lines)


def search_item_to_job_payload(item: dict[str, Any]) -> BossZhipinJobPayload:
    """Convert one boss_search item into the existing ifome Boss job payload."""

    job_id = str(item.get("job_id") or item.get("security_id") or "").strip()
    if not job_id:
        raise BossMCPReadOnlyError("Boss search item is missing both job_id and security_id.")

    city = str(item.get("city") or "").strip() or None
    district = str(item.get("district") or "").strip()
    if city and district:
        city = f"{city} {district}"

    tags = _compact_list(item.get("skills") or []) + _compact_list(item.get("welfare") or [])
    if item.get("industry"):
        tags.append(str(item["industry"]).strip())
    if item.get("stage"):
        tags.append(str(item["stage"]).strip())

    return BossZhipinJobPayload(
        job_id=job_id,
        company_name=str(item.get("company") or "未知公司"),
        role_title=str(item.get("title") or "未知岗位"),
        city=city,
        salary_range=str(item.get("salary") or "").strip() or None,
        experience_requirement=str(item.get("experience") or "").strip() or None,
        education_requirement=str(item.get("education") or "").strip() or None,
        job_description=build_job_description_from_search_item(item),
        tags=tags,
        hr_name=str(item.get("boss_name") or "").strip() or None,
        hr_title=str(item.get("boss_title") or "").strip() or None,
    )


def search_item_identity(item: dict[str, Any]) -> str:
    """Return a stable best-effort identity for Boss search result de-duplication."""

    return str(item.get("job_id") or item.get("security_id") or "").strip()


def search_envelope_to_job_payloads(envelope: dict[str, Any], *, max_items: int = 10) -> list[BossZhipinJobPayload]:
    """Convert a boss_search JSON envelope into ifome job payloads."""

    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        message = error.get("message") or "Boss search failed."
        raise BossMCPReadOnlyError(str(message))
    data = envelope.get("data") or []
    if not isinstance(data, list):
        raise BossMCPReadOnlyError("Boss search envelope data must be a list.")
    return [search_item_to_job_payload(item) for item in data[:max_items] if isinstance(item, dict)]
