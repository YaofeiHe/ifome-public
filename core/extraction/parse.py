"""Heuristic parsing helpers for the minimal extract node."""

from __future__ import annotations

import re
from datetime import datetime

from core.runtime.time import PROJECT_TIMEZONE, now_in_project_timezone
from core.schemas import ContentCategory

CITY_CANDIDATES = [
    "北京",
    "上海",
    "杭州",
    "深圳",
    "广州",
    "南京",
    "苏州",
    "成都",
    "武汉",
    "西安",
    "远程",
]

ROLE_CANDIDATES = [
    "后端工程师",
    "前端工程师",
    "算法工程师",
    "数据分析师",
    "数据研发工程师",
    "测试工程师",
    "AI Agent 工程师",
    "大模型工程师",
    "产品经理",
]


def classify_text(normalized_text: str) -> ContentCategory:
    """Classify one normalized input using simple keyword heuristics."""

    text = normalized_text.lower()
    if any(keyword in normalized_text for keyword in ["面试", "笔试", "OA", "线上面试"]):
        return ContentCategory.INTERVIEW_NOTICE
    if "宣讲" in normalized_text:
        return ContentCategory.TALK_EVENT
    if "内推" in normalized_text:
        return ContentCategory.REFERRAL
    if any(keyword in normalized_text for keyword in ["招聘", "岗位", "投递", "jd", "任职要求"]):
        return ContentCategory.JOB_POSTING
    if len(text) < 12:
        return ContentCategory.NOISE
    return ContentCategory.GENERAL_UPDATE


def extract_company(text: str) -> str | None:
    """Extract a likely company name from raw text."""

    patterns = [
        r"^\s*([A-Za-z\u4e00-\u9fff]{2,16})\s*(?=(?:20\d{2}|[0-9]{2})届|(?:春季)?校招|春招|秋招|暑期实习|招聘|正式启动)",
        r"公司[:：]?\s*([^\n，,。；;]+)",
        r"([^\s，,。；;]{2,20}?)(?:招聘|诚聘)",
        r"([^\n，,。；;]+?(?:公司|集团|科技|网络|信息|汽车|智能))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def extract_role(text: str) -> str | None:
    """Extract a likely role name using a small candidate list first."""

    for pattern in (
        r"((?:20\d{2}|[0-9]{2})届春季校招)",
        r"((?:20\d{2}|[0-9]{2})届校招)",
        r"((?:20\d{2}|[0-9]{2})届秋招)",
        r"((?:20\d{2}|[0-9]{2})届春招)",
        r"((?:20\d{2}|[0-9]{2})届暑期实习)",
        r"(春季校招)",
        r"(春招)",
        r"(秋招)",
        r"(校招)",
        r"(暑期实习)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()

    for role in ROLE_CANDIDATES:
        if role in text:
            return role

    match = re.search(r"岗位[:：]?\s*([^\n，,。；;]+)", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"([^\n，,。；;]*(?:工程师|分析师|经理)(?:[-—][^\n，,。；;]+)?)", text)
    if match:
        return match.group(1).strip()
    return None


def extract_city(text: str) -> str | None:
    """Return the first city candidate found in the text."""

    for city in CITY_CANDIDATES:
        if city in text:
            return city
    return None


def extract_url(text: str) -> str | None:
    """Extract the first URL from text if present."""

    match = re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None


def extract_datetime(text: str) -> datetime | None:
    """Parse a small set of common Chinese and ISO-like datetime formats."""

    now = now_in_project_timezone()

    iso_match = re.search(
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2})[:：](\d{2}))?",
        text,
    )
    if iso_match:
        year, month, day, hour, minute = iso_match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 9),
            int(minute or 0),
            tzinfo=PROJECT_TIMEZONE,
        )

    cn_match = re.search(
        r"(?:(\d{4})年)?\s*(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2})[:：](\d{2}))?",
        text,
    )
    if cn_match:
        year, month, day, hour, minute = cn_match.groups()
        return datetime(
            int(year or now.year),
            int(month),
            int(day),
            int(hour or 9),
            int(minute or 0),
            tzinfo=PROJECT_TIMEZONE,
        )

    return None


def extract_all_datetimes(text: str) -> list[datetime]:
    """Parse all recognizable dates from one text block in encounter order."""

    now = now_in_project_timezone()
    matches: list[datetime] = []

    for match in re.finditer(
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2})[:：](\d{2}))?",
        text,
    ):
        year, month, day, hour, minute = match.groups()
        matches.append(
            datetime(
                int(year),
                int(month),
                int(day),
                int(hour or 9),
                int(minute or 0),
                tzinfo=PROJECT_TIMEZONE,
            )
        )

    for match in re.finditer(
        r"(?:(\d{4})年)?\s*(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2})[:：](\d{2}))?",
        text,
    ):
        year, month, day, hour, minute = match.groups()
        matches.append(
            datetime(
                int(year or now.year),
                int(month),
                int(day),
                int(hour or 9),
                int(minute or 0),
                tzinfo=PROJECT_TIMEZONE,
            )
        )

    unique_matches: list[datetime] = []
    seen: set[str] = set()
    for value in matches:
        key = value.isoformat()
        if key in seen:
            continue
        seen.add(key)
        unique_matches.append(value)
    return unique_matches


def pick_next_datetime(candidates: list[datetime]) -> datetime | None:
    """Return the nearest future datetime from a parsed candidate list."""

    if not candidates:
        return None

    now = now_in_project_timezone()
    future_candidates = sorted(value for value in candidates if value >= now)
    if future_candidates:
        return future_candidates[0]
    return sorted(candidates)[-1]


def infer_location_note(
    *,
    text: str,
    city: str | None,
    source_metadata: dict | None = None,
) -> str | None:
    """Explain why a card still lacks a precise location."""

    if city:
        return None

    metadata = source_metadata or {}
    lowered = text.lower()
    if "线上" in text or "online" in lowered:
        return "地点待识别，当前信息显示可能为线上安排。"
    if metadata.get("location_pending"):
        return "地点待识别，可能为线上，需投递后进一步确认。"
    if any(keyword in text for keyword in ("投递后", "待确认", "后续通知")):
        return "地点待识别，需投递后进一步确认。"
    if metadata.get("visited_urls"):
        return "地点待识别，可能为线上，需结合投递页或后续通知确认。"
    return None


def build_summary(company: str | None, role: str | None, city: str | None) -> str:
    """Create a compact one-line summary for list rendering."""

    company_part = company or "未知公司"
    role_part = role or "待识别岗位"
    city_part = f" / {city}" if city else ""
    return f"{company_part} - {role_part}{city_part}"


def derive_signal_tags(
    *,
    text: str,
    company: str | None,
    role: str | None,
    city: str | None,
    source_metadata: dict | None = None,
) -> list[str]:
    """Build UI-friendly tags from extracted fields and ingest metadata."""

    tags: list[str] = []
    metadata = source_metadata or {}

    for value in metadata.get("semantic_tags", []):
        cleaned = str(value).strip()
        if cleaned:
            tags.append(cleaned)

    if city:
        tags.append(city)
    if role:
        tags.append(role)
    if company:
        tags.append(company)

    lowered = text.lower()
    keyword_map = {
        "暑期实习": ("暑期实习", "summer"),
        "校招": ("校招", "campus"),
        "秋招": ("秋招", "autumn"),
        "笔试": ("笔试", "oa"),
        "面试": ("面试", "interview"),
        "内推": ("内推", "referral"),
    }
    for label, keywords in keyword_map.items():
        if any(keyword in lowered for keyword in keywords):
            tags.append(label)

    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = re.sub(r"\s+", "", tag)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(tag)
    return deduped[:8]
