from server.app.integrations.model_providers.base import ConfiguredProvider


class OpenAICompatibleProvider(ConfiguredProvider):
    provider_name = "openai_compatible"
