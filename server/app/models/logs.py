from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class TaskRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "task_runs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    error: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(120))


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36))
    before_snapshot: Mapped[dict | None] = mapped_column(JSON)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(120))


class SystemSetting(IdMixin, TimestampMixin, Base):
    __tablename__ = "system_settings"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class ApiKey(IdMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    allowed_department_ids: Mapped[list] = mapped_column(JSON, default=list)
    allowed_role_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiCallLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "api_call_logs"

    tenant_id: Mapped[str | None] = mapped_column(String(36))
    api_key_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("api_keys.id"))
    key_prefix: Mapped[str | None] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[str | None] = mapped_column(String(120))
    request_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
