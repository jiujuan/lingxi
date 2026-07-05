from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class ChatSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    session_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ChatMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="CREATED")
    request_id: Mapped[str | None] = mapped_column(String(120))


class QueryRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "query_runs"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_id: Mapped[str] = mapped_column(String(120), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chat_sessions.id"))
    user_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id")
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING")
    retrieval_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(120))


class QueryCitation(IdMixin, Base):
    __tablename__ = "query_citations"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("query_runs.id"))
    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chat_messages.id"))
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id"))
    qa_pair_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("qa_pairs.id"))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class MissedQuestion(IdMixin, TimestampMixin, Base):
    __tablename__ = "missed_questions"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    question_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="OPEN")
    missed_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
