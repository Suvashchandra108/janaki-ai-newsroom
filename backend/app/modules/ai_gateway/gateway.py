"""Provider-independent AI gateway.

Adapters return parsed JSON plus token usage. They never get tools, file access or network
access beyond their own fixed provider endpoint. Callers must validate the returned structure
(see ``research.claims``) — model output is untrusted input.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai_gateway.models import UsageRecord

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class AIError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, *, system: str, user: str, max_output_tokens: int) -> LLMResult: ...


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIError("bad_output", "Model did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise AIError("bad_output", "Model JSON is not an object")
    return data


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        raise AIError("rate_limited", "Provider rate limit or free quota reached", retryable=True)
    if resp.status_code >= 500:
        raise AIError("provider_error", f"Provider error {resp.status_code}", retryable=True)
    if resp.status_code >= 400:
        raise AIError("request_rejected", f"Provider rejected request ({resp.status_code})")


class OpenAICompatibleProvider:
    """Chat Completions API: works with Groq, OpenRouter, OpenAI and similar services."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._client = httpx.Client(
            timeout=timeout, transport=transport, headers={"Authorization": f"Bearer {api_key}"}
        )

    def generate_json(self, *, system: str, user: str, max_output_tokens: int) -> LLMResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise AIError(
                "network", f"Provider unreachable: {type(exc).__name__}", retryable=True
            ) from exc
        _raise_for_status(resp)
        payload = resp.json()
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("bad_output", "Unexpected provider response shape") from exc
        usage = payload.get("usage") or {}
        return LLMResult(
            _parse_json(text or ""),
            self.name,
            self.model,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._url = f"{GEMINI_BASE}/models/{model}:generateContent"
        self._client = httpx.Client(
            timeout=timeout, transport=transport, headers={"x-goog-api-key": api_key}
        )

    def generate_json(self, *, system: str, user: str, max_output_tokens: int) -> LLMResult:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
                "maxOutputTokens": max_output_tokens,
            },
        }
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise AIError(
                "network", f"Provider unreachable: {type(exc).__name__}", retryable=True
            ) from exc
        _raise_for_status(resp)
        payload = resp.json()
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("bad_output", "Unexpected provider response shape (blocked?)") from exc
        usage = payload.get("usageMetadata") or {}
        return LLMResult(
            _parse_json(text),
            self.name,
            self.model,
            int(usage.get("promptTokenCount", 0)),
            int(usage.get("candidatesTokenCount", 0)),
        )


def get_extraction_provider() -> LLMProvider | None:
    """The configured provider for extraction tasks, or None if AI is not configured."""
    s = get_settings()
    if s.ai_provider == "none" or not s.ai_api_key or not s.ai_model_extraction:
        return None
    if s.ai_provider == "gemini":
        return GeminiProvider(
            api_key=s.ai_api_key, model=s.ai_model_extraction, timeout=s.ai_timeout_seconds
        )
    if not s.ai_base_url.startswith("https://"):
        return None
    return OpenAICompatibleProvider(
        base_url=s.ai_base_url,
        api_key=s.ai_api_key,
        model=s.ai_model_extraction,
        timeout=s.ai_timeout_seconds,
    )


def record_usage(
    db: Session, *, tenant_id: uuid.UUID, kind: str, result: LLMResult, job_id: uuid.UUID | None
) -> None:
    db.add(
        UsageRecord(
            tenant_id=tenant_id,
            kind=kind,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            job_id=job_id,
        )
    )
