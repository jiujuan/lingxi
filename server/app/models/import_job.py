from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class ImportJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id"))
    status: Mapped[str] = mapped_column(String(40), default=ImportJobStatus.PENDING.value)
    stage: Mapped[str] = mapped_column(String(40), default="CREATED")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSON, default=dict)


class ImportJobFile(IdMixin, Base):
    __tablename__ = "import_job_files"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_jobs.id"))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)


class ParseArtifact(IdMixin, Base):
    __tablename__ = "parse_artifacts"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"))
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id"))
    artifact_type: Mapped[str] = mapped_column(String(60), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    artifact_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

