from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class ModelProviderType(StrEnum):
    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"
    CLAUDE = "CLAUDE"
    OLLAMA = "OLLAMA"
    INTERNAL_GATEWAY = "INTERNAL_GATEWAY"


class ModelProviderStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class ModelCapability(StrEnum):
    CHAT = "CHAT"
    EMBEDDING = "EMBEDDING"
    QA_SPLIT = "QA_SPLIT"


class ModelConfigStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class ModelProvider(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_providers"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(40), default=ModelProviderStatus.DISABLED.value, nullable=False
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("tenant_id", "name"),)


class ModelConfig(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_configs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_providers.id"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(40), default=ModelConfigStatus.ACTIVE.value, nullable=False
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class ModelCallLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_call_logs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_providers.id")
    )
    model_config_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("model_configs.id")
    )
    run_id: Mapped[str | None] = mapped_column(String(120))
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(120))
