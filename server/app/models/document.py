from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    QA_SPLITTING = "QA_SPLITTING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"
    DELETED = "DELETED"


class DocumentAccessSubjectType(StrEnum):
    ALL_AUTHENTICATED = "ALL_AUTHENTICATED"
    DEPARTMENT = "DEPARTMENT"
    ROLE = "ROLE"
    USER = "USER"


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    file_type: Mapped[str] = mapped_column(String(40), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    parser_name: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    page_count: Mapped[int | None] = mapped_column(Integer)
    qa_pair_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    knowledge_space_id: Mapped[str | None] = mapped_column(String(36))
    category_department_id: Mapped[str | None] = mapped_column(String(36))
    knowledge_category_id: Mapped[str | None] = mapped_column(String(36))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    last_error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "idx_documents_tenant_space_updated",
            "tenant_id",
            "knowledge_space_id",
            "updated_at",
        ),
        Index(
            "idx_documents_tenant_category_department_updated",
            "tenant_id",
            "category_department_id",
            "updated_at",
        ),
        Index(
            "idx_documents_tenant_knowledge_category_updated",
            "tenant_id",
            "knowledge_category_id",
            "updated_at",
        ),
    )


class DocumentAccessRule(IdMixin, Base):
    __tablename__ = "document_access_rules"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )
    subject_type: Mapped[DocumentAccessSubjectType] = mapped_column(
        Enum(DocumentAccessSubjectType, native_enum=False), nullable=False
    )
    subject_id: Mapped[str | None] = mapped_column(String(36))

