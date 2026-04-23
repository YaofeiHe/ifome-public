"""OCR adapters used by image ingest."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _normalize_ocr_text(text: str) -> str:
    """Trim OCR output while keeping line-level readability."""

    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class OCRExtractionResult:
    """OCR result and metadata returned to the ingest service."""

    text: str
    source_metadata: dict[str, Any]


class LocalTesseractOCRClient:
    """Local OCR adapter backed by the installed `tesseract` CLI."""

    def __init__(self, languages: str = "eng+osd", psm: int = 6) -> None:
        self.languages = languages
        self.psm = psm

    def is_available(self) -> bool:
        """Return whether `tesseract` is available in the current environment."""

        return shutil.which("tesseract") is not None

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        """Run OCR on one image file and return normalized text."""

        if not self.is_available():
            raise RuntimeError("本地 OCR 不可用：未找到 tesseract。")

        completed = subprocess.run(
            [
                "tesseract",
                str(image_path),
                "stdout",
                "-l",
                self.languages,
                "--psm",
                str(self.psm),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"OCR 失败：{completed.stderr.strip() or 'tesseract returned non-zero exit code.'}"
            )

        text = _normalize_ocr_text(completed.stdout)
        if not text:
            raise RuntimeError("OCR 失败：未识别到可用文本。")

        return OCRExtractionResult(
            text=text,
            source_metadata={
                "source_kind": "image",
                "ocr_engine": "tesseract",
                "ocr_languages": self.languages,
                "ocr_psm": self.psm,
                "ocr_text_length": len(text),
            },
        )
