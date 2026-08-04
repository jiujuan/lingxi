import json

import httpx
import pytest

from server.app.integrations.model_providers import base as base_module
from server.app.integrations.model_providers.base import MockProvider, ProviderError
from server.app.integrations.model_providers.claude import ClaudeProvider
from server.app.integrations.model_providers.ollama import OllamaProvider
from server.app.integrations.model_providers.openai_compatible import (
    OpenAICompatibleProvider,
)
from server.app.integrations.model_providers.registry import build_provider_adapter


def _patch_transport(monkeypatch, handler):
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(base_module.httpx, "Client", factory)
    monkeypatch.setattr(base_module.time, "sleep", lambda *_: None)


def test_openai_compatible_complete_chat_and_embeddings(monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer sk-test"
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "真实回答"}}]}
            )
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.3, 0.4]},
                        {"index": 0, "embedding": [0.1, 0.2]},
                    ]
                },
            )
        return httpx.Response(404)

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1", "sk-test", {"modelName": "gpt-x"}
    )

    assert provider.complete_chat("hi") == "真实回答"
    vectors = provider.embed_texts(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]  # reordered by index
    assert any(path.endswith("/chat/completions") for path in seen)


def test_openai_compatible_generate_qa_pairs_forces_json_object(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"items":[]}'}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1", "sk-test", {"modelName": "gpt-x"}
    )

    # QA split constrains output to a strict JSON object (parity with Ollama).
    provider.generate_qa_pairs("hi")
    assert seen[-1]["response_format"] == {"type": "json_object"}

    # Plain chat must not force JSON — it serves free-form conversation.
    provider.complete_chat("hi")
    assert "response_format" not in seen[-1]


def test_openai_compatible_stream_chat_parses_sse(monkeypatch):
    body = (
        b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"\xe5\xa5\xbd"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1", "sk-test", {"modelName": "gpt-x"}
    )
    assert "".join(provider.stream_chat("hi")) == "你好"


def test_ollama_chat_uses_native_shape(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": "ollama 回答"}})

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider("http://localhost:11434", None, {"modelName": "qwen"})
    assert provider.complete_chat("hi") == "ollama 回答"


def test_ollama_generate_qa_pairs_uses_structured_output_schema(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": (
                        '{"items":[],"coveredChunkIndexes":[],"skippedChunks":[]}'
                    )
                }
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider(
        "http://localhost:11434", None, {"modelName": "gemma3"}
    )

    provider.generate_qa_pairs("hi")

    output_format = seen[-1]["format"]
    assert output_format["type"] == "object"
    assert set(output_format["required"]) == {
        "items",
        "coveredChunkIndexes",
        "skippedChunks",
    }
    assert output_format["properties"]["items"]["type"] == "array"
    assert (
        output_format["properties"]["items"]["items"]["required"]
        == ["question", "answer", "quote", "pageNo", "chunkIndex"]
    )
    assert seen[-1]["options"]["temperature"] == 0


def test_claude_uses_messages_api_and_rejects_embeddings(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "ak-test"
        assert request.headers["anthropic-version"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "claude"}]})

    _patch_transport(monkeypatch, handler)
    provider = ClaudeProvider(None, "ak-test", {"modelName": "claude-x"})
    assert provider.complete_chat("hi") == "claude"

    with pytest.raises(ProviderError) as excinfo:
        provider.embed_texts(["a"])
    assert excinfo.value.code == "PROVIDER_EMBEDDING_UNSUPPORTED"


def test_http_provider_retries_transient_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1", "sk", {"modelName": "gpt-x", "maxRetries": 2}
    )
    assert provider.complete_chat("hi") == "ok"
    assert calls["n"] == 3


def test_http_provider_maps_auth_error_and_does_not_retry(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1", "sk", {"modelName": "gpt-x", "maxRetries": 3}
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete_chat("hi")
    assert excinfo.value.code == "PROVIDER_UNAUTHORIZED"
    assert excinfo.value.retryable is False
    assert calls["n"] == 1  # 401 is terminal, no retry


def test_http_provider_transport_error_is_not_reported_as_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider(
        "http://localhost:11434",
        None,
        {"modelName": "gemma3", "timeoutMs": 30000, "maxRetries": 0},
        provider_name="Gemma",
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.generate_qa_pairs("hi")

    error = excinfo.value
    assert error.code == "PROVIDER_CONNECTION_ERROR"
    assert error.timeout_phase is None
    assert "30 秒" not in error.message


@pytest.mark.parametrize(
    ("exception_type", "expected_code", "expected_phase"),
    [
        (httpx.ConnectTimeout, "PROVIDER_CONNECTION_TIMEOUT", "connect"),
        (httpx.ReadTimeout, "PROVIDER_INFERENCE_TIMEOUT", "read"),
    ],
)
def test_http_provider_timeout_error_contains_provider_model_endpoint_and_phase(
    monkeypatch, exception_type, expected_code, expected_phase
):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("timed out", request=request)

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider(
        "http://localhost:11434",
        None,
        {"modelName": "gemma3", "timeoutMs": 30000, "maxRetries": 0},
        provider_name="Gemma",
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.generate_qa_pairs("hi")

    error = excinfo.value
    assert error.code == expected_code
    assert error.provider_name == "Gemma"
    assert error.provider_type == "OLLAMA"
    assert error.model_name == "gemma3"
    assert error.endpoint == "http://localhost:11434/api/chat"
    assert error.timeout_ms == 30000
    assert error.timeout_phase == expected_phase
    assert "Gemma" in error.message
    assert "gemma3" in error.message
    assert "Ollama" in error.message
    assert "30 秒" in error.message


def test_ollama_model_connection_uses_selected_model_chat_endpoint(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider(
        "http://localhost:11434",
        None,
        {"modelName": "gemma3", "maxTokens": 8},
        provider_name="Gemma",
    )

    result = provider.test_model_connection()

    assert result.success is True
    assert result.endpoint == "http://localhost:11434/api/chat"
    assert seen == [
        {
            "model": "gemma3",
            "messages": [{"role": "user", "content": "连接测试：请只回复 OK。"}],
            "stream": False,
            "options": {"num_predict": 8},
        }
    ]


def test_registry_dispatches_mock_vs_real():
    # mock:// scheme -> deterministic mock
    assert isinstance(
        build_provider_adapter("OPENAI_COMPATIBLE", "mock://success", None), MockProvider
    )
    # explicit fixture marker -> mock even with a real-looking URL
    assert isinstance(
        build_provider_adapter(
            "OPENAI_COMPATIBLE", "https://api.example.com/v1", None, {"chatResponse": "x"}
        ),
        MockProvider,
    )
    # real URL + no markers -> real HTTP adapter
    assert isinstance(
        build_provider_adapter(
            "OPENAI_COMPATIBLE", "https://api.example.com/v1", "sk", {"modelName": "m"}
        ),
        OpenAICompatibleProvider,
    )


def test_registry_injects_model_name_and_timeout():
    adapter = build_provider_adapter(
        "OLLAMA",
        "http://localhost:11434",
        None,
        {},
        model_name="qwen",
        timeout_ms=12000,
    )
    assert adapter.model_name == "qwen"
    assert adapter.timeout_seconds == 12.0


def test_registry_explicit_model_settings_override_provider_config():
    adapter = build_provider_adapter(
        "OLLAMA",
        "http://localhost:11434",
        None,
        {"modelName": "provider-model", "timeoutMs": 1000, "maxTokens": 4},
        model_name="qa-model",
        timeout_ms=30000,
        max_tokens=8,
    )

    assert adapter.model_name == "qa-model"
    assert adapter.timeout_ms == 30000
    assert adapter.config["maxTokens"] == 8
