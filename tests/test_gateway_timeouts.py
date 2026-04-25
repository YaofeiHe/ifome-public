"""Regression tests for live gateway timeout handling."""

from __future__ import annotations

import base64
import socket

from core.runtime.settings import LLMSettings, OCRSettings, ProviderSettings
from core.tools.llm_client import LLMGatewayError, OpenAICompatibleLLMGateway
from core.tools.ocr_client import GeneralLLMOCRClient, QwenVLOCRClient


def test_live_llm_gateway_wraps_socket_timeout(monkeypatch) -> None:
    """Live LLM gateway should convert low-level timeouts into LLMGatewayError."""

    gateway = OpenAICompatibleLLMGateway(
        LLMSettings(
            enable_live_llm=True,
            request_timeout_seconds=1,
            dashscope=ProviderSettings(
                api_key="demo-key",
                base_url="https://example.com/v1",
                model="qwen-plus",
            ),
        )
    )

    def raise_timeout(*args, **kwargs):
        raise socket.timeout("The read operation timed out")

    monkeypatch.setattr("core.tools.llm_client.urlopen", raise_timeout)

    try:
        gateway.complete_json(
            route="dashscope:qwen-primary",
            task_name="timeout_test",
            system_prompt="Return JSON.",
            user_payload={"query": "test"},
        )
    except LLMGatewayError as exc:
        assert "timeout" in str(exc).lower()
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected LLMGatewayError for socket timeout.")


def test_general_ocr_client_wraps_socket_timeout(tmp_path, monkeypatch) -> None:
    """Vision OCR client should convert low-level timeouts into RuntimeError."""

    client = GeneralLLMOCRClient(
        LLMSettings(
            request_timeout_seconds=1,
            dashscope=ProviderSettings(
                api_key="demo-key",
                base_url="https://example.com/v1",
                model="qwen-vl-max",
            ),
        )
    )
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnSUs8AAAAASUVORK5CYII="
        )
    )

    def raise_timeout(*args, **kwargs):
        raise socket.timeout("The read operation timed out")

    monkeypatch.setattr("core.tools.ocr_client.urlopen", raise_timeout)

    try:
        client.extract_text(image_path)
    except RuntimeError as exc:
        assert "超时" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected RuntimeError for OCR socket timeout.")


def test_dedicated_ocr_client_wraps_socket_timeout(tmp_path, monkeypatch) -> None:
    """Dedicated OCR route should also surface timeouts as RuntimeError."""

    client = QwenVLOCRClient(
        OCRSettings(
            enabled=True,
            provider_label="Qwen-VL-OCR",
            api_key="demo-key",
            base_url="https://example.com/v1",
            model="qwen-vl-ocr",
            request_timeout_seconds=1,
        )
    )
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnSUs8AAAAASUVORK5CYII="
        )
    )

    def raise_timeout(*args, **kwargs):
        raise socket.timeout("The read operation timed out")

    monkeypatch.setattr("core.tools.ocr_client.urlopen", raise_timeout)

    try:
        client.extract_text(image_path)
    except RuntimeError as exc:
        assert "超时" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected RuntimeError for OCR socket timeout.")
