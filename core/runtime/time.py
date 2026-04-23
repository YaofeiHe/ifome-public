"""Project-wide time helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

PROJECT_TIMEZONE = timezone(timedelta(hours=8))


def now_in_project_timezone() -> datetime:
    """Return the current time using the project-default timezone."""

    return datetime.now(PROJECT_TIMEZONE)
