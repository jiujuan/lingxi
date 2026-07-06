from time import perf_counter

from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.core.secrets import decrypt_secret, encrypt_secret, has_secret
from server.app.integrations.model_providers.registry import (
    ProviderFactory,
    build_provider_adapter,
)
from server.app.models.model_config import (
    ModelCallLog,
    ModelCapability,
    ModelConfig,
    ModelConfigStatus,
    ModelProvider,
    ModelProviderStatus,
    ModelProviderType,
)
from server.app.repositories.model_config_repo import (
    ModelConfigRepository,
    ModelProviderRepository,
)


class ModelConfigService:
    def __init__(
        self,
        session: Session,
        provider_factory: ProviderFactory = build_provider_adapter,
    ) -> None:
        self.session = session
        self.providers = ModelProviderRepository(session)
        self.configs = ModelConfigRepository(session)
        self._build_adapter = provider_factory

    def create_provider(
        self,
        context: AccessContext,
        *,
        provider_type: str,
        name: str,
        base_url: str | None,
        api_key: str | None,
        status: str,
        config: dict | None,
    ) -> ModelProvider:
        self._validate_provider_type(provider_type)
        self._validate_provider_status(status)
        provider = ModelProvider(
            tenant_id=context.tenant_id,
            provider_type=provider_type,
            name=name.strip(),
            base_url=base_url,
            encrypted_api_key=encrypt_secret(api_key),
            status=status,
            config=config or {},
        )
        self.providers.add(provider)
        self.session.commit()
        return provider

    def update_provider(
        self,
        context: AccessContext,
        provider_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        status: str | None = None,
        config: dict | None = None,
    ) -> ModelProvider:
        provider = self._get_provider(context.tenant_id, provider_id)
        if name is not None:
            provider.name = name.strip()
        if base_url is not None:
            provider.base_url = base_url
        if api_key is not None:
            provider.encrypted_api_key = encrypt_secret(api_key)
        if status is not None:
            self._validate_provider_status(status)
            provider.status = status
        if config is not None:
            provider.config = config
        self.session.commit()
        return provider

    def list_providers(self, context: AccessContext) -> list[ModelProvider]:
        return self.providers.list_for_tenant(context.tenant_id)

    def test_provider_connection(
        self, context: AccessContext, provider_id: str
    ) -> dict:
        provider = self._get_provider(context.tenant_id, provider_id)
        api_key = decrypt_secret(provider.encrypted_api_key)
        adapter = self._build_adapter(
            provider.provider_type,
            base_url=provider.base_url,
            api_key=api_key,
            config=provider.config,
        )

        started = perf_counter()
        result = adapter.test_connection()
        latency_ms = max(1, int((perf_counter() - started) * 1000))
        latency_ms = max(latency_ms, result.latency_ms)

        log = ModelCallLog(
            tenant_id=context.tenant_id,
            provider_id=provider.id,
            model_config_id=None,
            capability=ModelCapability.CHAT.value,
            status=result.status,
            latency_ms=latency_ms,
            token_usage={},
            error_code=result.error_code,
            error_message=result.error_message,
            request_id=current_request_id(),
        )
        self.session.add(log)
        self.session.commit()
        return {
            "success": result.success,
            "status": result.status,
            "latency_ms": latency_ms,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }

    def create_model_config(
        self,
        context: AccessContext,
        *,
        provider_id: str,
        capability: str,
        model_name: str,
        embedding_dimension: int | None,
        max_tokens: int | None,
        timeout_ms: int,
        is_default: bool,
        status: str,
        config: dict | None,
    ) -> ModelConfig:
        self._validate_capability(capability)
        self._validate_config_status(status)
        self._get_provider(context.tenant_id, provider_id)
        if is_default:
            self.configs.clear_default(context.tenant_id, capability)
        model_config = ModelConfig(
            tenant_id=context.tenant_id,
            provider_id=provider_id,
            capability=capability,
            model_name=model_name.strip(),
            embedding_dimension=embedding_dimension,
            max_tokens=max_tokens,
            timeout_ms=timeout_ms,
            is_default=is_default,
            status=status,
            config=config or {},
        )
        self.configs.add(model_config)
        self.session.commit()
        return model_config

    def update_model_config(
        self,
        context: AccessContext,
        config_id: str,
        *,
        model_name: str | None = None,
        embedding_dimension: int | None = None,
        max_tokens: int | None = None,
        timeout_ms: int | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        config: dict | None = None,
    ) -> ModelConfig:
        model_config = self._get_model_config(context.tenant_id, config_id)
        if model_name is not None:
            model_config.model_name = model_name.strip()
        if embedding_dimension is not None:
            model_config.embedding_dimension = embedding_dimension
        if max_tokens is not None:
            model_config.max_tokens = max_tokens
        if timeout_ms is not None:
            model_config.timeout_ms = timeout_ms
        if status is not None:
            self._validate_config_status(status)
            model_config.status = status
        if config is not None:
            model_config.config = config
        if is_default is True:
            self.set_default_model(context, config_id)
            return model_config
        if is_default is False:
            model_config.is_default = False
        self.session.commit()
        return model_config

    def set_default_model(self, context: AccessContext, config_id: str) -> ModelConfig:
        model_config = self._get_model_config(context.tenant_id, config_id)
        self.configs.clear_default(context.tenant_id, model_config.capability)
        model_config.is_default = True
        self.session.commit()
        return model_config

    def list_model_configs(
        self, context: AccessContext, capability: str | None = None
    ) -> list[ModelConfig]:
        if capability is not None:
            self._validate_capability(capability)
        return self.configs.list_for_tenant(context.tenant_id, capability)

    @staticmethod
    def provider_to_dict(provider: ModelProvider) -> dict:
        return {
            "id": provider.id,
            "provider_type": provider.provider_type,
            "name": provider.name,
            "base_url": provider.base_url,
            "status": provider.status,
            "config": provider.config or {},
            "secret_configured": has_secret(provider.encrypted_api_key),
        }

    @staticmethod
    def model_config_to_dict(model_config: ModelConfig) -> dict:
        return {
            "id": model_config.id,
            "provider_id": model_config.provider_id,
            "capability": model_config.capability,
            "model_name": model_config.model_name,
            "embedding_dimension": model_config.embedding_dimension,
            "max_tokens": model_config.max_tokens,
            "timeout_ms": model_config.timeout_ms,
            "is_default": model_config.is_default,
            "status": model_config.status,
            "config": model_config.config or {},
        }

    def _get_provider(self, tenant_id: str, provider_id: str) -> ModelProvider:
        provider = self.providers.get_for_tenant(tenant_id, provider_id)
        if provider is None:
            raise not_found("模型供应商不存在")
        return provider

    def _get_model_config(self, tenant_id: str, config_id: str) -> ModelConfig:
        model_config = self.configs.get_for_tenant(tenant_id, config_id)
        if model_config is None:
            raise not_found("模型配置不存在")
        return model_config

    @staticmethod
    def _validate_provider_type(provider_type: str) -> None:
        if provider_type not in {item.value for item in ModelProviderType}:
            raise bad_request("INVALID_PROVIDER_TYPE", "模型供应商类型不支持")

    @staticmethod
    def _validate_provider_status(status: str) -> None:
        if status not in {item.value for item in ModelProviderStatus}:
            raise bad_request("INVALID_PROVIDER_STATUS", "模型供应商状态不支持")

    @staticmethod
    def _validate_config_status(status: str) -> None:
        if status not in {item.value for item in ModelConfigStatus}:
            raise bad_request("INVALID_MODEL_STATUS", "模型配置状态不支持")

    @staticmethod
    def _validate_capability(capability: str) -> None:
        if capability not in {item.value for item in ModelCapability}:
            raise bad_request("INVALID_MODEL_CAPABILITY", "模型能力不支持")
