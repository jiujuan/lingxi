from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.app.core.config import settings
from server.app.db.base import Base, IdMixin, TimestampMixin
from server.app.db.types import EmbeddingVector


class DocumentChunk(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"))
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title_path: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")


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
