from typing import Protocol

from server.app.integrations.model_providers.base import BaseProvider, MockProvider
from server.app.integrations.model_providers.claude import ClaudeProvider
from server.app.integrations.model_providers.internal_gateway import (
    InternalGatewayProvider,
)
from server.app.integrations.model_providers.ollama import OllamaProvider
from server.app.integrations.model_providers.openai_compatible import (
    OpenAICompatibleProvider,
)


ALLOWED_PROVIDER_OPTIONS: dict[str, frozenset[str]] = {
    "OLLAMA": frozenset(
        {"keepAlive", "numCtx", "numPredict", "temperature"}
    ),
    "OPENAI_COMPATIBLE": frozenset(
        {
            "responseFormat",
            "reasoningEffort",
            "thinking",
            "chatPath",
            "embeddingPath",
        }
    ),
    "INTERNAL_GATEWAY": frozenset(
        {
            "responseFormat",
            "reasoningEffort",
            "thinking",
            "chatPath",
            "embeddingPath",
        }
    ),
    "CLAUDE": frozenset({"anthropicVersion"}),
}

# These values are adapter/runtime controls rather than provider-specific
# request options. They are kept so timeout, mock fixtures, and output limits
# continue to work after provider option filtering.
_COMMON_RUNTIME_KEYS = frozenset(
    {
        "modelName",
        "model",
        "maxTokens",
        "max_tokens",
        "maxRetries",
        "timeoutMs",
        "timeout_ms",
        "connectTimeoutMs",
        "connect_timeout_ms",
        "writeTimeoutMs",
        "write_timeout_ms",
        "readIdleTimeoutMs",
        "read_idle_timeout_ms",
        "overallTimeoutMs",
        "overall_timeout_ms",
        "modelsPath",
        "mock",
        "chatResponse",
        "qaSplitResponse",
        "chatError",
        "testMode",
        "chatChunkSize",
        "embeddingDimension",
        "qaSplit",
    }
)


def filter_provider_config(
    provider_type: str, config: dict | None = None
) -> dict:
    """Return only safe adapter/runtime keys for a provider.

    Configurations may use either the historical flat shape or the
    ``providerOptions`` envelope used by the admin API. Unknown provider
    options remain persisted for compatibility, but never reach a real
    adapter's HTTP payload.
    """

    raw = dict(config or {})
    normalized_type = str(provider_type).upper()
    allowed = ALLOWED_PROVIDER_OPTIONS.get(normalized_type, frozenset())
    filtered = {
        key: value for key, value in raw.items() if key in _COMMON_RUNTIME_KEYS
    }

    nested = raw.get("providerOptions")
    if isinstance(nested, dict):
        scoped = nested.get(normalized_type)
        if isinstance(scoped, dict):
            for key, value in scoped.items():
                if key in allowed:
                    filtered[key] = value

    for key, value in raw.items():
        if key in allowed:
            filtered[key] = value

    return filtered


class ProviderFactory(Protocol):
    """Callable that builds a provider adapter.

    Services depend on this instead of the concrete ``build_provider_adapter``
    so a fake factory can be injected in tests without monkeypatching module
    globals. ``build_provider_adapter`` is the default implementation.
    """

    def __call__(
        self,
        provider_type: str,
        base_url: str | None,
        api_key: str | None,
        config: dict | None = None,
        *,
        model_name: str | None = None,
        timeout_ms: int | None = None,
        connect_timeout_ms: int | None = None,
        write_timeout_ms: int | None = None,
        read_idle_timeout_ms: int | None = None,
        overall_timeout_ms: int | None = None,
        max_tokens: int | None = None,
        provider_name: str | None = None,
    ) -> BaseProvider: ...


PROVIDER_TYPES: dict[str, type[BaseProvider]] = {
    "OPENAI_COMPATIBLE": OpenAICompatibleProvider,
    "CLAUDE": ClaudeProvider,
    "OLLAMA": OllamaProvider,
    "INTERNAL_GATEWAY": InternalGatewayProvider,
}

# Config keys whose presence signals a deterministic test/mock fixture.
_MOCK_MARKER_KEYS = frozenset(
    {"chatResponse", "qaSplitResponse", "chatError", "testMode"}
)


def _is_mock_mode(base_url: str | None, config: dict) -> bool:
    """Route to the in-process mock instead of a real HTTP call.

    Mock mode is chosen when there is no real endpoint to talk to (empty or
    ``mock://`` base_url) or the config carries explicit test fixtures. This
    keeps the test suite hermetic while real deployments hit real providers.
    """

    if not base_url or str(base_url).startswith("mock://"):
        return True
    if config.get("mock") is True:
        return True
    return any(key in config for key in _MOCK_MARKER_KEYS)


def build_provider_adapter(
    provider_type: str,
    base_url: str | None,
    api_key: str | None,
    config: dict | None = None,
    *,
    model_name: str | None = None,
    timeout_ms: int | None = None,
    connect_timeout_ms: int | None = None,
    write_timeout_ms: int | None = None,
    read_idle_timeout_ms: int | None = None,
    overall_timeout_ms: int | None = None,
    max_tokens: int | None = None,
    provider_name: str | None = None,
) -> BaseProvider:
    merged: dict = dict(config or {})
    if model_name is not None:
        merged["modelName"] = model_name
    if timeout_ms is not None:
        merged["timeoutMs"] = timeout_ms
    if connect_timeout_ms is not None:
        merged["connectTimeoutMs"] = connect_timeout_ms
    if write_timeout_ms is not None:
        merged["writeTimeoutMs"] = write_timeout_ms
    if read_idle_timeout_ms is not None:
        merged["readIdleTimeoutMs"] = read_idle_timeout_ms
    if overall_timeout_ms is not None:
        merged["overallTimeoutMs"] = overall_timeout_ms
    if max_tokens is not None:
        merged["maxTokens"] = max_tokens

    if _is_mock_mode(base_url, merged):
        return MockProvider(
            base_url=base_url,
            api_key=api_key,
            config=merged,
            provider_name=provider_name,
        )

    provider_class = PROVIDER_TYPES.get(provider_type)
    if provider_class is None:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    return provider_class(
        base_url=base_url,
        api_key=api_key,
        config=filter_provider_config(provider_type, merged),
        provider_name=provider_name,
    )
