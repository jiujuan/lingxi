from server.app.integrations.model_providers.base import ConfiguredProvider
from server.app.integrations.model_providers.claude import ClaudeProvider
from server.app.integrations.model_providers.internal_gateway import (
    InternalGatewayProvider,
)
from server.app.integrations.model_providers.ollama import OllamaProvider
from server.app.integrations.model_providers.openai_compatible import (
    OpenAICompatibleProvider,
)


PROVIDER_TYPES: dict[str, type[ConfiguredProvider]] = {
    "OPENAI_COMPATIBLE": OpenAICompatibleProvider,
    "CLAUDE": ClaudeProvider,
    "OLLAMA": OllamaProvider,
    "INTERNAL_GATEWAY": InternalGatewayProvider,
}


def build_provider_adapter(
    provider_type: str,
    base_url: str | None,
    api_key: str | None,
    config: dict | None = None,
) -> ConfiguredProvider:
    provider_class = PROVIDER_TYPES.get(provider_type)
    if provider_class is None:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    return provider_class(base_url=base_url, api_key=api_key, config=config)
