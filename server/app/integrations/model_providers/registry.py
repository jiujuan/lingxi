from server.app.integrations.model_providers.base import BaseProvider, MockProvider
from server.app.integrations.model_providers.claude import ClaudeProvider
from server.app.integrations.model_providers.internal_gateway import (
    InternalGatewayProvider,
)
from server.app.integrations.model_providers.ollama import OllamaProvider
from server.app.integrations.model_providers.openai_compatible import (
    OpenAICompatibleProvider,
)


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
) -> BaseProvider:
    merged: dict = dict(config or {})
    if model_name is not None and "modelName" not in merged:
        merged["modelName"] = model_name
    if timeout_ms is not None and "timeoutMs" not in merged:
        merged["timeoutMs"] = timeout_ms

    if _is_mock_mode(base_url, merged):
        return MockProvider(base_url=base_url, api_key=api_key, config=merged)

    provider_class = PROVIDER_TYPES.get(provider_type)
    if provider_class is None:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    return provider_class(base_url=base_url, api_key=api_key, config=merged)
