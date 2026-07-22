"""AI client layer for the workbook-aware Claude assistant."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol
from urllib import error, request


class AIProviderError(RuntimeError):
    """Raised when an AI request cannot be completed."""


@dataclass(frozen=True)
class AISettings:
    """Runtime settings for the selected AI provider."""

    provider: str
    model: str
    api_key: str
    max_tokens: int = 420
    temperature: float = 0.2
    web_search_enabled: bool = False
    web_search_max_uses: int = 3


class AIClient(Protocol):
    """Minimal interface implemented by the AI client."""

    def complete(self, system_prompt: str, user_payload: str) -> str:
        """Return an assistant response for the supplied prompt."""


def create_ai_client(settings: AISettings) -> AIClient:
    """Create the configured Claude client."""

    if settings.provider.lower().strip() != "anthropic":
        raise AIProviderError(f"Unsupported AI provider: {settings.provider}")
    return ClaudeMessagesClient(settings)


class ClaudeMessagesClient:
    """Anthropic Messages API implementation."""

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings

    def complete(self, system_prompt: str, user_payload: str) -> str:
        if not self.settings.api_key:
            raise AIProviderError("Claude API key is missing.")

        compact_payload = _cap_payload(user_payload, max_chars=12000)
        try:
            request_params = {
                "model": self.settings.model,
                "max_tokens": max(100, min(self.settings.max_tokens, 3000)),
                "system": system_prompt,
                "messages": [{"role": "user", "content": compact_payload}],
            }
            if _supports_temperature(self.settings.model):
                request_params["temperature"] = self.settings.temperature
            if self.settings.web_search_enabled:
                request_params["tools"] = [
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": max(1, min(self.settings.web_search_max_uses, 5)),
                    }
                ]

            response_payload = self._create_message(request_params)
            text_blocks = _text_blocks(response_payload)
            text = "\n".join(text_blocks).strip()
            if text:
                return text
            raise AIProviderError("Claude returned an empty response.")
        except AIProviderError:
            raise
        except Exception as exc:  # pragma: no cover - provider errors are environment-specific.
            message = str(exc)
            if _is_auth_error(message):
                raise AIProviderError("Claude rejected the API key. Check that the Anthropic key is active.") from exc
            if _is_limit_error(message):
                raise AIProviderError("Claude rejected the request due to an account or rate limit. Try again in a minute.") from exc
            raise AIProviderError(f"Claude request failed: {exc}") from exc

    def _create_message(self, request_params: dict) -> object:
        """Create a Claude message using the SDK when present, else direct HTTPS."""

        try:
            import anthropic
        except ModuleNotFoundError:
            return _create_message_with_http(self.settings.api_key, request_params)

        client = anthropic.Anthropic(api_key=self.settings.api_key)
        return client.messages.create(**request_params)


def _create_message_with_http(api_key: str, request_params: dict) -> dict:
    data = json.dumps(request_params).encode("utf-8")
    api_request = request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with request.urlopen(api_request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {details}") from exc


def _text_blocks(response: object) -> list[str]:
    if isinstance(response, dict):
        return [
            block.get("text", "")
            for block in response.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        ]
    return [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]


def _cap_payload(payload: str, max_chars: int) -> str:
    if len(payload) <= max_chars:
        return payload
    marker = "\n\nUser question:"
    if marker in payload:
        evidence, question = payload.rsplit(marker, 1)
        allowed_evidence_chars = max(1200, max_chars - len(question) - len(marker) - 140)
        evidence = evidence[:allowed_evidence_chars].rstrip()
        return f"{evidence}\n\n[Older evidence trimmed to reduce AI cost.]{marker}{question}"
    return payload[:max_chars].rstrip()


def _is_auth_error(message: str) -> bool:
    lower = message.lower()
    return "401" in lower or "invalid" in lower and "api" in lower or "authentication" in lower


def _is_limit_error(message: str) -> bool:
    lower = message.lower()
    return "rate limit" in lower or "overloaded" in lower or "quota" in lower or "too many requests" in lower


def _supports_temperature(model: str) -> bool:
    """Return whether a Claude model accepts the temperature request parameter."""

    lowered = model.lower()
    return "sonnet-5" not in lowered and "opus-4-8" not in lowered and "fable" not in lowered
