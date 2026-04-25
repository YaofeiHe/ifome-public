"""Tests for OCR routing defaults and fallback behavior."""

from __future__ import annotations

from pathlib import Path

from core.runtime.settings import (
    AppSettings,
    RuntimeOCROverrides,
    RuntimeProviderOverrides,
    RuntimeSettingsOverrides,
)
from core.tools import OCRExtractionResult, build_ocr_client_from_settings
from core.tools.ocr_client import CascadingOCRClient


class UnavailableOCRClient:
    """Fake OCR route that is never available."""

    def is_available(self) -> bool:
        return False

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        raise RuntimeError("should not be called")


class FailingOCRClient:
    """Fake OCR route that is available but fails at runtime."""

    def is_available(self) -> bool:
        return True

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        raise RuntimeError("upstream failed")


class SuccessOCRClient:
    """Fake OCR route that succeeds deterministically."""

    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    def is_available(self) -> bool:
        return True

    def extract_text(self, image_path: Path) -> OCRExtractionResult:
        return OCRExtractionResult(
            text="识别成功",
            source_metadata={
                "source_kind": "image",
                "ocr_engine": self.engine_name,
            },
        )


def test_build_ocr_client_includes_general_llm_by_default() -> None:
    """When dedicated OCR is off, the runtime should still try general LLM OCR first."""

    settings = AppSettings.from_env(
        RuntimeSettingsOverrides(
            llm=RuntimeProviderOverrides(
                api_key="sk-general",
                base_url="https://example.com/v1",
                model="qwen-vl-max",
            ),
            ocr=RuntimeOCROverrides(enabled=False),
        )
    )

    client = build_ocr_client_from_settings(settings)

    assert isinstance(client, CascadingOCRClient)
    assert client.route_names == ["general_llm", "local_tesseract"]


def test_build_ocr_client_keeps_dedicated_override_ahead_of_default() -> None:
    """Dedicated OCR should stay as the first route when the user explicitly enables it."""

    settings = AppSettings.from_env(
        RuntimeSettingsOverrides(
            llm=RuntimeProviderOverrides(
                api_key="sk-general",
                base_url="https://example.com/v1",
                model="qwen-vl-max",
            ),
            ocr=RuntimeOCROverrides(
                enabled=True,
                api_key="sk-ocr",
                base_url="https://ocr.example.com/v1",
                model="qwen-vl-ocr",
            ),
        )
    )

    client = build_ocr_client_from_settings(settings)

    assert isinstance(client, CascadingOCRClient)
    assert client.route_names == ["dedicated_ocr", "general_llm", "local_tesseract"]


def test_cascading_ocr_client_falls_back_to_next_available_route(tmp_path) -> None:
    """A failing route should not block later OCR candidates."""

    image_path = tmp_path / "demo.png"
    image_path.write_bytes(b"fake-image")
    client = CascadingOCRClient(
        [
            ("unavailable", UnavailableOCRClient()),
            ("failing", FailingOCRClient()),
            ("success", SuccessOCRClient("fallback-ocr")),
        ]
    )

    result = client.extract_text(image_path)

    assert result.text == "识别成功"
    assert result.source_metadata["ocr_engine"] == "fallback-ocr"
