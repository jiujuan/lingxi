from server.app.integrations.model_providers.base import ConfiguredProvider


class InternalGatewayProvider(ConfiguredProvider):
    provider_name = "internal_gateway"
