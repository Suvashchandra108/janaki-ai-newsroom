"""AI gateway adapters, tested with a mocked HTTP transport (no real keys or network)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import get_settings
from app.modules.ai_gateway import gateway
from app.modules.ai_gateway.gateway import AIError, GeminiProvider, OpenAICompatibleProvider


def _transport(status: int, payload: dict, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def test_openai_compatible_request_and_parsing() -> None:
    seen: list[httpx.Request] = []
    payload = {
        "choices": [{"message": {"content": '```json\n{"claims": []}\n```'}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 7},
    }
    p = OpenAICompatibleProvider(
        base_url="https://llm.example.com/v1/",
        api_key="k-123",
        model="model-x",
        transport=_transport(200, payload, seen),
    )
    res = p.generate_json(system="S", user="U", max_output_tokens=50)
    assert res.data == {"claims": []} and res.input_tokens == 120 and res.output_tokens == 7
    req = seen[0]
    assert str(req.url) == "https://llm.example.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer k-123"
    body = json.loads(req.content)
    assert body["model"] == "model-x" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_gemini_request_and_parsing() -> None:
    seen: list[httpx.Request] = []
    payload = {
        "candidates": [{"content": {"parts": [{"text": '{"claims": [1]}'}]}}],
        "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 40},
    }
    p = GeminiProvider(api_key="g-key", model="gem-model", transport=_transport(200, payload, seen))
    res = p.generate_json(system="S", user="U", max_output_tokens=50)
    assert res.data == {"claims": [1]} and (res.input_tokens, res.output_tokens) == (300, 40)
    req = seen[0]
    assert req.url.path.endswith("/models/gem-model:generateContent")
    assert req.headers["x-goog-api-key"] == "g-key" and "key=" not in str(req.url)
    body = json.loads(req.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["systemInstruction"]["parts"][0]["text"] == "S"


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (429, "rate_limited", True),
        (503, "provider_error", True),
        (401, "request_rejected", False),
    ],
)
def test_provider_errors(status: int, code: str, retryable: bool) -> None:
    p = OpenAICompatibleProvider(
        base_url="https://llm.example.com/v1",
        api_key="k",
        model="m",
        transport=_transport(status, {}, []),
    )
    with pytest.raises(AIError) as exc:
        p.generate_json(system="S", user="U", max_output_tokens=10)
    assert exc.value.code == code and exc.value.retryable is retryable


def test_non_json_output_is_rejected() -> None:
    payload = {"choices": [{"message": {"content": "Sure! Here are the claims..."}}]}
    p = OpenAICompatibleProvider(
        base_url="https://llm.example.com/v1",
        api_key="k",
        model="m",
        transport=_transport(200, payload, []),
    )
    with pytest.raises(AIError) as exc:
        p.generate_json(system="S", user="U", max_output_tokens=10)
    assert exc.value.code == "bad_output"


def test_provider_selection_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    assert gateway.get_extraction_provider() is None  # default: AI not configured
    monkeypatch.setattr(s, "ai_provider", "openai_compatible")
    monkeypatch.setattr(s, "ai_api_key", "k")
    monkeypatch.setattr(s, "ai_model_extraction", "m")
    monkeypatch.setattr(s, "ai_base_url", "http://insecure.example.com/v1")
    assert gateway.get_extraction_provider() is None  # refuses non-HTTPS endpoints
    monkeypatch.setattr(s, "ai_base_url", "https://api.example.com/v1")
    assert isinstance(gateway.get_extraction_provider(), OpenAICompatibleProvider)
    monkeypatch.setattr(s, "ai_provider", "gemini")
    assert isinstance(gateway.get_extraction_provider(), GeminiProvider)
    monkeypatch.setattr(s, "ai_model_extraction", "")
    assert gateway.get_extraction_provider() is None  # no hard-coded default model
