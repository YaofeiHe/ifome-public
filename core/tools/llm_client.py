"""OpenAI-compatible live LLM gateway with graceful local fallback support."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.runtime.settings import LLMSettings, ProviderSettings


class LLMGatewayError(RuntimeError):
    """Base exception for live LLM gateway failures."""


class LLMNotConfiguredError(LLMGatewayError):
    """Raised when a requested live route has no usable provider configuration."""


@dataclass(frozen=True)
class ResolvedProvider:
    """Resolved provider configuration used for one live request."""

    provider_name: str
    base_url: str
    api_key: str
    model_candidates: tuple[str, ...]


class NoopLLMGateway:
    """Gateway used when live LLM execution is disabled for local development."""

    def is_available(self, route: str) -> bool:
        return False

    def complete_json(
        self,
        *,
        route: str,
        task_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise LLMNotConfiguredError("Live LLM execution is disabled.")


class OpenAICompatibleLLMGateway:
    """
    Minimal HTTP client for providers exposing OpenAI-compatible chat APIs.

    The goal is not to hide provider differences completely. Instead, the class
    gives the workflow one stable adapter so classify/extract can start using a
    live model while the rest of the project stays independent from any SDK.
    """

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def is_available(self, route: str) -> bool:
        try:
            self._resolve_provider(route)
        except LLMNotConfiguredError:
            return False
        return True

    def complete_json(
        self,
        *,
        route: str,
        task_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        provider = self._resolve_provider(route)
        endpoint = f"{provider.base_url.rstrip('/')}/chat/completions"
        last_error: Exception | None = None

        for index, model_name in enumerate(provider.model_candidates):
            body = {
                "model": model_name,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
                    },
                ],
            }

            request = Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            try:
                with urlopen(
                    request, timeout=max(1, self.settings.request_timeout_seconds)
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:  # pragma: no cover - network path
                error_body = exc.read().decode("utf-8", errors="ignore")
                last_error = LLMGatewayError(
                    f"Live LLM HTTP error for {provider.provider_name}/{model_name}: "
                    f"{exc.code} {error_body}"
                )
                if index < len(provider.model_candidates) - 1 and self._should_try_next_model(
                    exc.code, error_body
                ):
                    continue
                raise last_error from exc
            except URLError as exc:  # pragma: no cover - network path
                raise LLMGatewayError(
                    f"Live LLM network error for {provider.provider_name}/{model_name}: "
                    f"{exc.reason}"
                ) from exc

            try:
                content = self._extract_message_content(payload)
                return self._extract_json(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise LLMGatewayError(
                    f"Live LLM response for task `{task_name}` from {model_name} was not valid JSON."
                ) from exc

        raise last_error or LLMGatewayError("No live model candidate available.")

    def _resolve_provider(self, route: str) -> ResolvedProvider:
        if not self.settings.enable_live_llm:
            raise LLMNotConfiguredError("ENABLE_LIVE_LLM is disabled.")

        provider_name = route.split(":", 1)[0]
        provider = self._lookup_provider(provider_name)
        if provider is None or not provider.api_key or not provider.base_url or not provider.model:
            raise LLMNotConfiguredError(
                f"Route `{route}` is not fully configured for live execution."
            )

        model_candidates = (provider.model, *provider.fallback_models)

        return ResolvedProvider(
            provider_name=provider_name,
            base_url=provider.base_url,
            api_key=provider.api_key,
            model_candidates=model_candidates,
        )

    def _lookup_provider(self, provider_name: str) -> ProviderSettings | None:
        providers = {
            "dashscope": self.settings.dashscope,
            "openai": self.settings.openai,
            "deepseek": self.settings.deepseek,
        }
        return providers.get(provider_name)

    def _extract_message_content(self, payload: dict[str, Any]) -> str:
        message = payload["choices"][0]["message"]["content"]
        if isinstance(message, str):
            return message

        if isinstance(message, list):
            text_parts: list[str] = []
            for item in message:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return "\n".join(part for part in text_parts if part)

        raise TypeError("Unsupported message content format.")

    def _extract_json(self, content: str) -> dict[str, Any]:
        fenced_match = re.search(r"```json\s*(\{.*\})\s*```", content, re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))

        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)

        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            return json.loads(stripped[first_brace : last_brace + 1])

        raise json.JSONDecodeError("No JSON object found.", stripped, 0)

    def _should_try_next_model(self, status_code: int, error_body: str) -> bool:
        """
        Decide whether the next cheaper candidate model should be attempted.

        We only fallback on errors that are likely related to quota, rate limit,
        temporary availability, or model access constraints.
        """

        lowered = error_body.lower()
        keywords = (
            "quota",
            "limit",
            "insufficient",
            "rate",
            "exceed",
            "exhaust",
            "unavailable",
            "not available",
            "not enabled",
        )
        if status_code in {402, 403, 429, 503}:
            return True
        if status_code == 400 and any(keyword in lowered for keyword in keywords):
            return True
        return False
