"""Prompt loading helpers used by workflow nodes."""

from __future__ import annotations

from pathlib import Path


class PromptLoader:
    """
    Read prompt assets from the repository-level `prompts/` directory.

    Keeping prompt files on disk instead of hard-coding them inside Python
    modules makes the project easier to review in interviews and safer to
    iterate on without touching node control flow.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path(__file__).resolve().parents[2] / "prompts"

    def load(self, prompt_name: str) -> str:
        """Load one markdown prompt file by stem name."""

        prompt_path = self.base_path / f"{prompt_name}.md"
        return prompt_path.read_text(encoding="utf-8").strip()
