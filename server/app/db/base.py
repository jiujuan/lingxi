from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid_str() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


from server.app.models.user import Department, Tenant, User  # noqa: E402,F401
from server.app.models.role import Role, RolePermission, UserRole  # noqa: E402,F401
from server.app.models.permission import Permission  # noqa: E402,F401
from server.app.models.document import Document, DocumentAccessRule  # noqa: E402,F401
from server.app.models.import_job import ImportJob, ImportJobFile, ParseArtifact  # noqa: E402,F401
from server.app.models.qa_pair import DocumentChunk, QaPair  # noqa: E402,F401
from server.app.models.chat import ChatMessage, ChatSession, QueryCitation, QueryRun, MissedQuestion  # noqa: E402,F401
from server.app.models.logs import ApiCallLog, ApiKey, AuditLog, SystemSetting, TaskRun  # noqa: E402,F401
from server.app.models.model_config import ModelCallLog, ModelConfig, ModelProvider  # noqa: E402,F401
