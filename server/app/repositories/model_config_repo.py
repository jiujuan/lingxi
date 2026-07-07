from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from server.app.models.model_config import ModelConfig, ModelProvider


class ModelProviderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, provider: ModelProvider) -> ModelProvider:
        self.session.add(provider)
        self.session.flush()
        return provider

    def get_for_tenant(self, tenant_id: str, provider_id: str) -> ModelProvider | None:
        return self.session.scalar(
            select(ModelProvider).where(
                ModelProvider.tenant_id == tenant_id,
                ModelProvider.id == provider_id,
                ModelProvider.deleted_at.is_(None),
            )
        )

    def list_for_tenant(self, tenant_id: str) -> list[ModelProvider]:
        return list(
            self.session.scalars(
                select(ModelProvider)
                .where(
                    ModelProvider.tenant_id == tenant_id,
                    ModelProvider.deleted_at.is_(None),
                )
                .order_by(ModelProvider.created_at.desc())
            ).all()
        )


class ModelConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, config: ModelConfig) -> ModelConfig:
        self.session.add(config)
        self.session.flush()
        return config

    def get_for_tenant(self, tenant_id: str, config_id: str) -> ModelConfig | None:
        return self.session.scalar(
            select(ModelConfig).where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.id == config_id,
                ModelConfig.deleted_at.is_(None),
            )
        )

    def list_for_tenant(
        self, tenant_id: str, capability: str | None = None
    ) -> list[ModelConfig]:
        statement = select(ModelConfig).where(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.deleted_at.is_(None),
        )
        if capability:
            statement = statement.where(ModelConfig.capability == capability)
        return list(
            self.session.scalars(
                statement.order_by(ModelConfig.capability, ModelConfig.created_at.desc())
            ).all()
        )

    def count_active_for_provider(self, tenant_id: str, provider_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(ModelConfig.id)).where(
                    ModelConfig.tenant_id == tenant_id,
                    ModelConfig.provider_id == provider_id,
                    ModelConfig.deleted_at.is_(None),
                )
            )
            or 0
        )

    def clear_default(self, tenant_id: str, capability: str) -> None:
        self.session.execute(
            update(ModelConfig)
            .where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.capability == capability,
                ModelConfig.deleted_at.is_(None),
            )
            .values(is_default=False)
        )
