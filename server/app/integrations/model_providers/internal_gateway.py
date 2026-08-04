from server.app.integrations.model_providers.openai_compatible import (
    OpenAICompatibleProvider,
)


class InternalGatewayProvider(OpenAICompatibleProvider):
    """Internal model gateway.

    Assumes an OpenAI-compatible surface (the common shape for in-house
    gateways). Override endpoint paths via config if the gateway differs.
    """

    provider_name = "internal_gateway"
    provider_type = "INTERNAL_GATEWAY"
