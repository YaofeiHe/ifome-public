"""OCR adapters used by image ingest."""

from __future__ import annotations

import base64
import json
import socket
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.runtime.time import now_in_project_timezone
from core.runtime.settings import AppSettings, LLMSettings, OCRSettings


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


class OCRClient(Protocol):
    """Minimal OCR client protocol shared by runtime dependencies."""

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        """Extract normalized text from an image file."""

    def is_available(self) -> bool:
        """Return whether this OCR route is currently usable."""


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
                "ocr_route": "local_tesseract",
                "ocr_languages": self.languages,
                "ocr_psm": self.psm,
                "ocr_text_length": len(text),
            },
        )


class OpenAICompatibleVisionOCRClient:
    """OCR adapter backed by an OpenAI-compatible multimodal endpoint."""

    def __init__(
        self,
        *,
        provider_label: str,
        api_key: str | None,
        base_url: str | None,
        model_candidates: tuple[str, ...],
        request_timeout_seconds: int,
        route_name: str,
    ) -> None:
        self.provider_label = provider_label
        self.api_key = api_key
        self.base_url = base_url
        self.model_candidates = model_candidates
        self.request_timeout_seconds = request_timeout_seconds
        self.route_name = route_name

    def is_available(self) -> bool:
        return bool(
            self.api_key
            and self.base_url
            and self.model_candidates
        )

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        """Run OCR through the configured OpenAI-compatible vision endpoint."""

        if not self.is_available():
            raise RuntimeError(
                f"{self.provider_label} 未配置，请先检查 API Key、Base URL 和模型设置。"
            )

        image_bytes = image_path.read_bytes()
        data_url = self._build_data_url(image_path, image_bytes)
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        last_error: RuntimeError | None = None
        current_timestamp = now_in_project_timezone().isoformat()

        for index, model_name in enumerate(self.model_candidates):
            body = {
                "model": model_name,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"当前时间戳：{current_timestamp}\n\n"
                            "你是一个严格的 OCR 转写助手。"
                            "请忠实提取图片中的文字，尽量保持段落与换行，不要总结，不要解释。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"当前时间戳：{current_timestamp}\n"
                                    "请输出图片中的全部可见文字。"
                                    "如果存在表格或列表，尽量按阅读顺序转成纯文本。"
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    },
                ],
            }

            request = Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            try:
                with urlopen(
                    request, timeout=max(1, self.request_timeout_seconds)
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="ignore")
                last_error = RuntimeError(
                    f"{self.provider_label} 请求失败：{exc.code} {error_body or 'HTTP error'}"
                )
                if index < len(self.model_candidates) - 1 and self._should_try_next_model(
                    exc.code, error_body
                ):
                    continue
                raise last_error from exc
            except URLError as exc:
                raise RuntimeError(f"{self.provider_label} 网络错误：{exc.reason}") from exc
            except (TimeoutError, socket.timeout) as exc:
                raise RuntimeError(f"{self.provider_label} 请求超时：{exc}") from exc

            text = _normalize_ocr_text(self._extract_message_text(payload))
            if not text:
                last_error = RuntimeError(f"{self.provider_label} 未识别到可用文本。")
                continue

            return OCRExtractionResult(
                text=text,
                source_metadata={
                    "source_kind": "image",
                    "ocr_engine": self.provider_label,
                    "ocr_route": self.route_name,
                    "ocr_model": model_name,
                    "ocr_text_length": len(text),
                },
            )

        raise last_error or RuntimeError(f"{self.provider_label} 未识别到可用文本。")

    def _extract_message_text(self, payload: dict[str, Any]) -> str:
        message = payload["choices"][0]["message"]["content"]
        if isinstance(message, str):
            return message
        if isinstance(message, list):
            text_parts: list[str] = []
            for item in message:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text") or ""))
            return "\n".join(part for part in text_parts if part)
        raise RuntimeError("OCR 返回结果格式无法解析。")

    def _build_data_url(self, image_path: Path, image_bytes: bytes) -> str:
        suffix = image_path.suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(suffix, "image/png")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _should_try_next_model(self, status_code: int, error_body: str) -> bool:
        lowered = error_body.lower()
        keywords = (
            "quota",
            "limit",
            "insufficient",
            "rate",
            "unavailable",
            "not enabled",
            "image",
            "vision",
            "multimodal",
        )
        if status_code in {400, 402, 403, 429, 503} and any(
            keyword in lowered for keyword in keywords
        ):
            return True
        return False


class GeneralLLMOCRClient(OpenAICompatibleVisionOCRClient):
    """Default OCR route that reuses the general LLM provider configuration."""

    def __init__(self, settings: LLMSettings) -> None:
        model_candidates = tuple(
            item.strip()
            for item in (settings.dashscope.model, *settings.dashscope.fallback_models)
            if item and item.strip()
        )
        super().__init__(
            provider_label="通用 LLM OCR",
            api_key=settings.dashscope.api_key,
            base_url=settings.dashscope.base_url,
            model_candidates=model_candidates,
            request_timeout_seconds=settings.request_timeout_seconds,
            route_name="general_llm",
        )


class QwenVLOCRClient(OpenAICompatibleVisionOCRClient):
    """Dedicated OCR route backed by an independently configured multimodal endpoint."""

    def __init__(self, settings: OCRSettings) -> None:
        self.settings = settings
        super().__init__(
            provider_label=settings.provider_label,
            api_key=settings.api_key,
            base_url=settings.base_url,
            model_candidates=(settings.model,) if settings.model else (),
            request_timeout_seconds=settings.request_timeout_seconds,
            route_name="dedicated_ocr",
        )

    def is_available(self) -> bool:
        return bool(self.settings.enabled) and super().is_available()


class CascadingOCRClient:
    """Try multiple OCR routes in order until one succeeds."""

    def __init__(self, candidates: list[tuple[str, OCRClient]]) -> None:
        self.candidates = candidates

    @property
    def route_names(self) -> list[str]:
        """Return the current OCR fallback chain in evaluation order."""

        return [name for name, _ in self.candidates]

    def is_available(self) -> bool:
        for _, client in self.candidates:
            if client.is_available():
                return True
        return False

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        errors: list[str] = []
        for candidate_name, client in self.candidates:
            if not client.is_available():
                errors.append(f"{candidate_name}: 未配置")
                continue
            try:
                return client.extract_text(image_path)
            except RuntimeError as exc:
                errors.append(f"{candidate_name}: {exc}")

        detail = "；".join(errors) if errors else "未找到可用 OCR 路线。"
        raise RuntimeError(f"OCR 失败：{detail}")


def build_ocr_client_from_settings(settings: AppSettings) -> OCRClient:
    """Create the runtime OCR client with explicit override and graceful fallback."""

    candidates: list[tuple[str, OCRClient]] = []
    if settings.ocr.enabled:
        candidates.append(("dedicated_ocr", QwenVLOCRClient(settings.ocr)))
    candidates.append(("general_llm", GeneralLLMOCRClient(settings.llm)))
    candidates.append(("local_tesseract", LocalTesseractOCRClient()))
    return CascadingOCRClient(candidates)
