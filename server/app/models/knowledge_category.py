from enum import StrEnum

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class KnowledgeCategoryType(StrEnum):
    PROJECT = "PROJECT"
    TOPIC = "TOPIC"


class KnowledgeSpace(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_spaces"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(40), default="ACTIVE", server_default="ACTIVE", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index(
            "idx_knowledge_spaces_tenant_status",
            "tenant_id",
            "status",
            "sort_order",
        ),
    )


class KnowledgeCategory(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_categories"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id"), nullable=False
    )
    department_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("departments.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    category_type: Mapped[KnowledgeCategoryType] = mapped_column(
        Enum(KnowledgeCategoryType, native_enum=False, length=40),
        default=KnowledgeCategoryType.TOPIC,
        server_default=KnowledgeCategoryType.TOPIC.value,
        nullable=False,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_categories.id")
    )
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(40), default="ACTIVE", server_default="ACTIVE", nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "space_id", "department_id", "code"),
        Index(
            "idx_knowledge_categories_tenant_space_department",
            "tenant_id",
            "space_id",
            "department_id",
            "sort_order",
        ),
    )
