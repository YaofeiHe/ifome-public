"""Simple normalization helpers used by the minimal workflow."""

from __future__ import annotations

import re


def normalize_text(raw_text: str) -> str:
    """Collapse noisy whitespace while preserving semantic content."""

    text = raw_text.replace("\u3000", " ").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join([line for line in lines if line]).strip()
