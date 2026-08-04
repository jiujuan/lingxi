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


def test_openai_compatible_filters_options_and_controls_json_mode(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"items":[]}'}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1",
        "sk-test",
        {
            "modelName": "gpt-x",
            "maxTokens": 64,
            "responseFormat": "json_object",
            "reasoningEffort": "low",
            "thinking": False,
            "temperature": 0,
            "unknownOption": "must-not-leak",
        },
    )

    provider.generate_qa_pairs("hi")
    assert seen[-1]["response_format"] == {"type": "json_object"}
    assert seen[-1]["reasoning_effort"] == "low"
    assert seen[-1]["thinking"] is False
    assert seen[-1]["max_tokens"] == 64
    assert "temperature" not in seen[-1]
    assert "unknownOption" not in seen[-1]

    provider.config.pop("responseFormat")
    provider.complete_chat("hi")
    assert "response_format" not in seen[-1]


def test_ollama_provider_whitelists_native_options(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": '{"items":[],"coveredChunkIndexes":[],"skippedChunks":[]}'
                }
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider(
        "http://localhost:11434",
        None,
        {
            "modelName": "gemma3",
            "keepAlive": "10m",
            "numCtx": 8192,
            "numPredict": 4096,
            "temperature": 0,
            "responseFormat": "json_object",
            "unknownOption": "must-not-leak",
        },
    )

    provider.generate_qa_pairs("hi")
    body = seen[-1]
    assert body["model"] == "gemma3"
    assert body["keep_alive"] == "10m"
    assert body["options"] == {
        "num_predict": 4096,
        "num_ctx": 8192,
        "temperature": 0.0,
    }
    assert "response_format" not in body
    assert "unknownOption" not in body


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


def test_stream_first_byte_and_read_idle_timeout_phases(monkeypatch):
    class FakeResponse:
        status_code = 200

        def __init__(self, lines):
            self._lines = lines

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def iter_lines(self):
            return iter(self._lines)

        def read(self):
            return b""

    class FakeClient:
        def __init__(self, lines):
            self._lines = lines

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def stream(self, method, url, *, headers, json):
            return FakeResponse(self._lines)

    first_byte_clock = iter([0.0, 0.0, 0.0, 2.0, 2.0])
    monkeypatch.setattr(
        base_module.time, "monotonic", lambda: next(first_byte_clock)
    )
    monkeypatch.setattr(
        base_module.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            ['data: {"choices":[{"delta":{"content":"a"}}]}']
        ),
    )
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1",
        "sk-test",
        {
            "modelName": "gpt-x",
            "readIdleTimeoutMs": 1000,
            "overallTimeoutMs": 10000,
        },
    )
    with pytest.raises(ProviderError) as first_byte_exc:
        list(provider.stream_chat("hi"))
    assert first_byte_exc.value.code == "PROVIDER_INFERENCE_TIMEOUT"
    assert first_byte_exc.value.timeout_phase == "first_byte"

    read_idle_clock = iter([0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0])
    monkeypatch.setattr(
        base_module.time, "monotonic", lambda: next(read_idle_clock)
    )
    monkeypatch.setattr(
        base_module.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            [
                'data: {"choices":[{"delta":{"content":"a"}}]}',
                'data: {"choices":[{"delta":{"content":"b"}}]}',
            ]
        ),
    )
    with pytest.raises(ProviderError) as read_idle_exc:
        list(provider.stream_chat("hi"))
    assert read_idle_exc.value.code == "PROVIDER_INFERENCE_TIMEOUT"
    assert read_idle_exc.value.timeout_phase == "read_idle"


def test_openai_compatible_finish_reason_length_is_terminal(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "截断"},
                    }
                ]
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        "https://api.example.com/v1", "sk-test", {"modelName": "deepseek-chat"}
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.complete_chat("hi")

    assert excinfo.value.code == "PROVIDER_OUTPUT_TRUNCATED"
    assert excinfo.value.retryable is False


def test_ollama_done_reason_length_is_terminal(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "done_reason": "length",
                "message": {"content": "截断"},
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider(
        "http://localhost:11434", None, {"modelName": "gemma3"}
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.complete_chat("hi")

    assert excinfo.value.code == "PROVIDER_OUTPUT_TRUNCATED"
    assert excinfo.value.retryable is False


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
        body = json.loads(request.content)
        assert "response_format" not in body
        assert "reasoning_effort" not in body
        assert "thinking" not in body
        return httpx.Response(200, json={"content": [{"type": "text", "text": "claude"}]})

    _patch_transport(monkeypatch, handler)
    provider = ClaudeProvider(
        None,
        "ak-test",
        {
            "modelName": "claude-x",
            "responseFormat": "json_object",
            "reasoningEffort": "low",
            "thinking": True,
        },
    )
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
        (httpx.WriteTimeout, "PROVIDER_WRITE_TIMEOUT", "write"),
        (httpx.ReadTimeout, "PROVIDER_INFERENCE_TIMEOUT", "read"),
        (httpx.PoolTimeout, "PROVIDER_POOL_TIMEOUT", "pool"),
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


def test_overall_timeout_is_not_reset_by_retry(monkeypatch):
    calls = {"n": 0}
    clock = iter([0.0, 0.0, 0.0, 0.06, 0.06, 0.11])

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    _patch_transport(monkeypatch, handler)
    monkeypatch.setattr(base_module.time, "monotonic", lambda: next(clock))
    provider = OllamaProvider(
        "http://localhost:11434",
        None,
        {"modelName": "gemma3", "timeoutMs": 100, "maxRetries": 3},
        provider_name="Gemma",
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.generate_qa_pairs("hi")

    error = excinfo.value
    assert error.code == "PROVIDER_OVERALL_TIMEOUT"
    assert error.timeout_phase == "overall"
    assert calls["n"] == 1


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


def test_registry_filters_provider_options_before_real_adapter():
    adapter = build_provider_adapter(
        "OLLAMA",
        "http://localhost:11434",
        None,
        {
            "modelName": "gemma3",
            "keepAlive": "10m",
            "numCtx": 8192,
            "unknownOption": "must-not-leak",
            "providerOptions": {
                "OLLAMA": {"numPredict": 4096},
                "OPENAI_COMPATIBLE": {"responseFormat": "json_object"},
            },
        },
    )

    assert adapter.config["keepAlive"] == "10m"
    assert adapter.config["numCtx"] == 8192
    assert adapter.config["numPredict"] == 4096
    assert "unknownOption" not in adapter.config
    assert "providerOptions" not in adapter.config
