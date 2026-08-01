import hashlib

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.core.config import settings
from server.app.db.base import Base, IdMixin, TimestampMixin
from server.app.db.types import EmbeddingVector


_EMPTY_CONTENT_HASH = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
_LEGACY_CONFIG_HASH = hashlib.sha256(b"legacy_parser:legacy").hexdigest()


class DocumentChunk(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("idx_document_chunks_parent_chunk_id", "parent_chunk_id"),
        Index(
            "idx_document_chunks_tenant_document_status_level",
            "tenant_id",
            "document_id",
            "status",
            "chunk_level",
            "chunk_index",
        ),
        Index(
            "idx_document_chunks_tenant_content_hash",
            "tenant_id",
            "content_hash",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"))
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title_path: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(
        String(40), default="ACTIVE", server_default="ACTIVE"
    )

    block_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="TEXT", server_default="TEXT"
    )
    chunk_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="CHILD", server_default="CHILD"
    )
    parent_chunk_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "document_chunks.id",
            name="fk_document_chunks_parent_chunk_id",
            ondelete="SET NULL",
        ),
    )
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    source_locators: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    atomic_block_indexes: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=_EMPTY_CONTENT_HASH,
        server_default=_EMPTY_CONTENT_HASH,
    )
    chunker_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="legacy_parser",
        server_default="legacy_parser",
    )
    chunker_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="legacy", server_default="legacy"
    )
    chunker_config_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=_LEGACY_CONFIG_HASH,
        server_default=_LEGACY_CONFIG_HASH,
    )
    embedding: Mapped[list | None] = mapped_column(
        EmbeddingVector(settings.embedding_vector_dimension)
    )
    search_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    chunk_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}"
    )

    parent_chunk: Mapped["DocumentChunk | None"] = relationship(
        "DocumentChunk",
        remote_side="DocumentChunk.id",
        back_populates="child_chunks",
        lazy="select",
    )
    child_chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="parent_chunk",
        lazy="select",
    )


class QaPair(IdMixin, TimestampMixin, Base):
    __tablename__ = "qa_pairs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"))
    chunk_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_chunks.id")
    )
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id"))
    pair_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    question_embedding: Mapped[list | None] = mapped_column(
        EmbeddingVector(settings.embedding_vector_dimension)
    )
    search_text: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    qa_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
