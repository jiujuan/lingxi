from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from server.app.db.base import Base, IdMixin, TimestampMixin


class QaSplitRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QaSplitBatchStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class QaSplitRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "qa_split_runs"
    __table_args__ = (
        CheckConstraint("batch_count >= 0", name="ck_qa_split_runs_batch_count"),
        CheckConstraint(
            "completed_batch_count >= 0",
            name="ck_qa_split_runs_completed_batch_count",
        ),
        CheckConstraint(
            "completed_batch_count <= batch_count",
            name="ck_qa_split_runs_completed_not_greater_than_total",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("import_jobs.id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )
    task_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("task_runs.id")
    )
    model_config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_configs.id"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_providers.id"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    chunk_generation_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=QaSplitRunStatus.CREATED.value,
        server_default=QaSplitRunStatus.CREATED.value,
    )
    batch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_batch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)

    batches: Mapped[list[QaSplitBatch]] = relationship(
        "QaSplitBatch",
        back_populates="run",
        lazy="select",
    )


class QaSplitBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "qa_split_batches"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "batch_index",
            name="uq_qa_split_batches_run_batch_index",
        ),
        CheckConstraint("split_depth >= 0", name="ck_qa_split_batches_split_depth"),
        CheckConstraint("attempt_count >= 0", name="ck_qa_split_batches_attempt_count"),
        CheckConstraint(
            "estimated_input_tokens >= 0",
            name="ck_qa_split_batches_estimated_input_tokens",
        ),
        CheckConstraint(
            "reserved_output_tokens >= 0",
            name="ck_qa_split_batches_reserved_output_tokens",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("qa_split_runs.id"), nullable=False
    )
    batch_index: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("qa_split_batches.id")
    )
    split_depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    chunk_indexes: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=QaSplitBatchStatus.PENDING.value,
        server_default=QaSplitBatchStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_hash: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    timeout_phase: Mapped[str | None] = mapped_column(String(40))

    run: Mapped[QaSplitRun] = relationship(
        "QaSplitRun",
        back_populates="batches",
        lazy="select",
    )
    parent_batch: Mapped[QaSplitBatch | None] = relationship(
        "QaSplitBatch",
        remote_side="QaSplitBatch.id",
        back_populates="child_batches",
        lazy="select",
    )
    child_batches: Mapped[list[QaSplitBatch]] = relationship(
        "QaSplitBatch",
        back_populates="parent_batch",
        lazy="select",
    )

    @validates("chunk_indexes")
    def _validate_chunk_indexes(self, _: str, value: list[int]) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("chunk_indexes must be a non-empty list")
        if any(not isinstance(index, int) or isinstance(index, bool) for index in value):
            raise ValueError("chunk_indexes must contain only integer indexes")
        if len(set(value)) != len(value):
            raise ValueError("chunk_indexes must be unique")
        return value

    @validates("result_payload")
    def _validate_result_payload(
        self, _: str, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is not None:
            _reject_sensitive_payload_keys(value)
        return value


def _reject_sensitive_payload_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if isinstance(key, str) and key.casefold() in {"prompt", "api_key", "content"}:
                raise ValueError("result_payload contains sensitive key")
            _reject_sensitive_payload_keys(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _reject_sensitive_payload_keys(nested_value)
