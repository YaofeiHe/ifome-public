"""Local runtime settings storage isolated from long-term memory."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.runtime.settings import (
    RuntimeOCROverrides,
    RuntimeProviderOverrides,
    RuntimeSourceFileOverrides,
    RuntimeSettingsOverrides,
)


class LocalRuntimeSettingsRepository:
    """Persist local runtime settings in a dedicated JSON file."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def load(self) -> RuntimeSettingsOverrides:
        """Load persisted runtime overrides if present."""

        if not self.file_path.exists():
            return RuntimeSettingsOverrides()

        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RuntimeSettingsOverrides()

        llm_payload = payload.get("llm", {}) if isinstance(payload, dict) else {}
        ocr_payload = payload.get("ocr", {}) if isinstance(payload, dict) else {}
        return RuntimeSettingsOverrides(
            llm=RuntimeProviderOverrides(
                enabled=llm_payload.get("enabled"),
                api_key=llm_payload.get("api_key"),
                base_url=llm_payload.get("base_url"),
                model=llm_payload.get("model"),
                fallback_models=tuple(llm_payload.get("fallback_models", [])),
            ),
            ocr=RuntimeOCROverrides(
                enabled=ocr_payload.get("enabled"),
                provider_label=ocr_payload.get("provider_label", "Qwen-VL-OCR"),
                api_key=ocr_payload.get("api_key"),
                base_url=ocr_payload.get("base_url"),
                model=ocr_payload.get("model"),
                request_timeout_seconds=ocr_payload.get("request_timeout_seconds"),
            ),
            source_files=RuntimeSourceFileOverrides(
                max_age_days=payload.get("source_files", {}).get("max_age_days")
                if isinstance(payload.get("source_files"), dict)
                else None,
                max_total_size_mb=payload.get("source_files", {}).get("max_total_size_mb")
                if isinstance(payload.get("source_files"), dict)
                else None,
                delete_when_item_deleted=payload.get("source_files", {}).get(
                    "delete_when_item_deleted"
                )
                if isinstance(payload.get("source_files"), dict)
                else None,
                filter_patterns=tuple(
                    (payload.get("source_files", {}) or {}).get("filter_patterns", [])
                )
                if isinstance(payload.get("source_files"), dict)
                else (),
            ),
            llm_request_timeout_seconds=payload.get("llm_request_timeout_seconds"),
        )

    def save(self, overrides: RuntimeSettingsOverrides) -> RuntimeSettingsOverrides:
        """Persist one runtime settings snapshot."""

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            json.dumps(asdict(overrides), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return overrides
