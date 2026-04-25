"""Local document-to-text helpers used by the unified ingest flow."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _normalize_document_text(text: str) -> str:
    """Trim extracted document text while keeping paragraph breaks readable."""

    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    compact_lines: list[str] = []
    blank_streak = 0
    for line in lines:
        if not line.strip():
            blank_streak += 1
            if blank_streak <= 1:
                compact_lines.append("")
            continue
        blank_streak = 0
        compact_lines.append(line.strip())
    return "\n".join(compact_lines).strip()


@dataclass(frozen=True)
class DocumentTextExtractionResult:
    """Document text extraction result returned to the unified ingest flow."""

    text: str
    source_metadata: dict[str, Any]


class LocalDocumentTextExtractor:
    """Extract text from local text files and text-based PDFs."""

    def extract_text(self, file_path: Path) -> DocumentTextExtractionResult:
        """Extract normalized text from one supported local document."""

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf_text(file_path)
        return self._extract_plain_text(file_path)

    def _extract_plain_text(self, file_path: Path) -> DocumentTextExtractionResult:
        raw_bytes = file_path.read_bytes()
        encodings = ("utf-8", "utf-8-sig", "utf-16", "gb18030", "big5", "latin-1")
        decoded_text: str | None = None
        selected_encoding: str | None = None

        for encoding in encodings:
            try:
                decoded_text = raw_bytes.decode(encoding)
                selected_encoding = encoding
                break
            except UnicodeDecodeError:
                continue

        if decoded_text is None:
            raise RuntimeError(f"暂不支持读取该文本文件编码：{file_path.name}")

        normalized_text = _normalize_document_text(decoded_text)
        if not normalized_text:
            raise RuntimeError(f"文件 {file_path.name} 中没有可分析的文本内容。")

        return DocumentTextExtractionResult(
            text=normalized_text,
            source_metadata={
                "document_extractor": "local_text_decoder",
                "document_encoding": selected_encoding,
                "document_text_length": len(normalized_text),
            },
        )

    def _extract_pdf_text(self, file_path: Path) -> DocumentTextExtractionResult:
        completed = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"PDF 转文字失败：{completed.stderr.strip() or 'textutil returned non-zero exit code.'}"
            )

        normalized_text = _normalize_document_text(completed.stdout)
        if not normalized_text:
            raise RuntimeError(
                f"PDF {file_path.name} 暂时没有提取到文字，可能是扫描版 PDF。"
            )

        return DocumentTextExtractionResult(
            text=normalized_text,
            source_metadata={
                "document_extractor": "textutil",
                "document_text_length": len(normalized_text),
            },
        )
