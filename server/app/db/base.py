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


# Model registry: importing this module must register every model on
# Base.metadata (create_all in tests/migration 0001 depends on it). These MUST
# stay plain module imports, not ``from X import Name``: when a model module
# is the process's first import it re-enters here mid-initialization, and a
# from-import would raise ImportError on its not-yet-defined class, while a
# module import succeeds and lets the cycle resolve for any entry order.
import server.app.models.user  # noqa: E402,F401
import server.app.models.role  # noqa: E402,F401
import server.app.models.permission  # noqa: E402,F401
import server.app.models.document  # noqa: E402,F401
import server.app.models.knowledge_category  # noqa: E402,F401
import server.app.models.import_job  # noqa: E402,F401
import server.app.models.qa_pair  # noqa: E402,F401
import server.app.models.chat  # noqa: E402,F401
import server.app.models.logs  # noqa: E402,F401
import server.app.models.model_config  # noqa: E402,F401
import server.app.models.qa_split_run  # noqa: E402,F401
