"""Persistent QA split checkpoints and all-or-nothing QA pair publishing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.models.document import Document, DocumentStatus
from server.app.models.import_job import ImportJob, ImportJobStatus
from server.app.models.model_config import ModelCapability, ModelConfig, ModelProvider
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.models.qa_split_run import (
    QaSplitBatch,
    QaSplitBatchStatus,
    QaSplitRun,
    QaSplitRunStatus,
)
from server.app.schemas.qa_split_run import (
    QaSplitBatchFailurePayload,
    QaSplitBatchResultPayload,
    QaSplitResultItem,
)
from server.app.services.qa_prompt_builder import QA_SPLIT_PROMPT_VERSION

if TYPE_CHECKING:
    from server.app.services.qa_split_batching import QaBatch
    from server.app.services.qa_split_service import ValidatedQaItem


QA_SPLIT_RUN_CONFIG_CHANGED = "QA_SPLIT_RUN_CONFIG_CHANGED"
QA_SPLIT_RUN_INCOMPLETE = "QA_SPLIT_RUN_INCOMPLETE"
QA_SPLIT_RUN_PROVENANCE_INVALID = "QA_SPLIT_RUN_PROVENANCE_INVALID"

ReplaceQaPairs = Callable[
    [ImportJob, Document, list[DocumentChunk], list["ValidatedQaItem"]], None
]
BindEmbeddingGeneration = Callable[[ImportJob, list[DocumentChunk]], None]
DefaultModelResolver = Callable[[str], tuple[ModelConfig, ModelProvider]]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batch_path(batch: "QaBatch") -> str:
    return ".".join(str(index) for index in batch.batch_index_path)


def _batch_path_key(path: str) -> tuple[int, ...]:
    return tuple(int(part) for part in path.split("."))


def chunk_generation_hash(chunks: Sequence[DocumentChunk]) -> str:
    """Fingerprint source identity without persisting document text."""

    return _canonical_hash(
        [
            {
                "chunkIndex": chunk.chunk_index,
                "contentHash": getattr(chunk, "content_hash", None),
                "generation": getattr(chunk, "chunker_config_hash", None),
            }
            for chunk in sorted(chunks, key=lambda value: value.chunk_index)
        ]
    )


def _validation_error(code: str, message: str, *, retryable: bool = False) -> Exception:
    # Avoid importing QaSplitService while it imports this module.
    from server.app.services.qa_split_service import QaSplitValidationError

    return QaSplitValidationError(message, code=code, retryable=retryable)


class QaSplitRunService:
    """Store safe batch checkpoints and publish only complete QA generations."""

    def __init__(
        self,
        session: Session,
        *,
        replace_qa_pairs: ReplaceQaPairs | None = None,
        bind_embedding_generation: BindEmbeddingGeneration | None = None,
        default_model_resolver: DefaultModelResolver | None = None,
    ) -> None:
        self.session = session
        self._replace_qa_pairs_callback = replace_qa_pairs
        self._bind_embedding_generation_callback = bind_embedding_generation
        self._default_model_resolver = default_model_resolver

    def get_or_create_run(
        self,
        *,
        job: ImportJob,
        document: Document,
        model_config: ModelConfig,
        provider: ModelProvider,
        batches: list["QaBatch"],
        task_run_id: str | None,
    ) -> QaSplitRun:
        generation_hash = chunk_generation_hash(
            [chunk for batch in batches for chunk in batch.chunks]
        )
        expected_specs = {
            _batch_path(batch): (
                tuple(sorted(chunk.chunk_index for chunk in batch.chunks)),
                batch.input_hash,
                batch.estimated_input_tokens,
                batch.reserved_output_tokens,
                batch.split_depth,
            )
            for batch in batches
        }
        candidates = list(
            self.session.scalars(
                select(QaSplitRun)
                .where(
                    QaSplitRun.job_id == job.id,
                    QaSplitRun.document_id == document.id,
                    QaSplitRun.status.in_(
                        [
                            QaSplitRunStatus.CREATED.value,
                            QaSplitRunStatus.RUNNING.value,
                            QaSplitRunStatus.FAILED.value,
                            QaSplitRunStatus.COMPLETED.value,
                        ]
                    ),
                )
                .order_by(QaSplitRun.created_at.desc())
            ).all()
        )
        for run in candidates:
            if self._run_matches(
                run,
                model_config=model_config,
                provider=provider,
                generation_hash=generation_hash,
                expected_specs=expected_specs,
            ):
                if task_run_id is not None:
                    run.task_run_id = task_run_id
                self.session.flush()
                return run
            if run.status != QaSplitRunStatus.COMPLETED.value:
                run.status = QaSplitRunStatus.CANCELLED.value
                run.error_code = QA_SPLIT_RUN_CONFIG_CHANGED
                run.error_message = "QA Split 输入 generation 或模型配置已变化"

        run = QaSplitRun(
            tenant_id=job.tenant_id,
            job_id=job.id,
            document_id=document.id,
            task_run_id=task_run_id,
            model_config_id=model_config.id,
            provider_id=provider.id,
            model_name=model_config.model_name,
            prompt_version=QA_SPLIT_PROMPT_VERSION,
            chunk_generation_hash=generation_hash,
            status=QaSplitRunStatus.RUNNING.value,
            batch_count=len(batches),
            completed_batch_count=0,
        )
        self.session.add(run)
        self.session.flush()

        persistent_batches: dict[str, QaSplitBatch] = {}
        for batch in sorted(batches, key=lambda value: value.batch_index_path):
            path = _batch_path(batch)
            parent_id = None
            if len(batch.batch_index_path) > 1:
                parent_path = ".".join(
                    str(index) for index in batch.batch_index_path[:-1]
                )
                parent = persistent_batches.get(parent_path)
                if parent is None:
                    raise ValueError("QA Split child batch is missing its persisted parent")
                parent_id = parent.id
            persisted = QaSplitBatch(
                run_id=run.id,
                batch_index=path,
                parent_batch_id=parent_id,
                split_depth=batch.split_depth,
                chunk_indexes=sorted({chunk.chunk_index for chunk in batch.chunks}),
                input_hash=batch.input_hash,
                estimated_input_tokens=batch.estimated_input_tokens,
                reserved_output_tokens=batch.reserved_output_tokens,
                status=QaSplitBatchStatus.PENDING.value,
                attempt_count=0,
            )
            self.session.add(persisted)
            self.session.flush()
            persistent_batches[path] = persisted
        return run

    def claim_next_pending_batch(self, run_id: str) -> QaSplitBatch | None:
        run = self.session.get(QaSplitRun, run_id)
        if run is None or run.status in {
            QaSplitRunStatus.CANCELLED.value,
            QaSplitRunStatus.COMPLETED.value,
        }:
            return None
        batches = list(
            self.session.scalars(
                select(QaSplitBatch)
                .where(
                    QaSplitBatch.run_id == run_id,
                    QaSplitBatch.status.in_(
                        [
                            QaSplitBatchStatus.PENDING.value,
                            QaSplitBatchStatus.FAILED.value,
                        ]
                    ),
                )
                .order_by(QaSplitBatch.batch_index)
                .with_for_update()
            ).all()
        )
        batch = next(
            (
                candidate
                for candidate in batches
                if candidate.status == QaSplitBatchStatus.PENDING.value
                or self._failed_batch_retryable(candidate)
            ),
            None,
        )
        if batch is None:
            return None
        batch.status = QaSplitBatchStatus.RUNNING.value
        batch.attempt_count += 1
        run.status = QaSplitRunStatus.RUNNING.value
        self.session.flush()
        return batch

    def save_success(
        self,
        batch_id: str,
        validated_items: list["ValidatedQaItem"],
        *,
        latency_ms: int,
    ) -> None:
        batch = self._require_batch(batch_id)
        payload = QaSplitBatchResultPayload(
            items=[
                QaSplitResultItem(
                    question=item.question,
                    answer=item.answer,
                    quote=item.quote,
                    pageNo=item.page_no,
                    chunkIndex=item.chunk_index,
                )
                for item in validated_items
            ]
        ).model_dump(by_alias=True)
        batch.result_payload = payload
        batch.result_hash = _canonical_hash(payload)
        batch.latency_ms = max(0, int(latency_ms))
        batch.error_code = None
        batch.error_message = None
        batch.timeout_phase = None
        batch.status = QaSplitBatchStatus.SUCCESS.value
        run = self._require_run(batch.run_id)
        run.completed_batch_count = self._successful_batch_count(run.id)
        run.status = QaSplitRunStatus.RUNNING.value
        run.error_code = None
        run.error_message = None
        self.session.flush()

    def save_failure(
        self,
        batch_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
        timeout_phase: str | None,
    ) -> None:
        batch = self._require_batch(batch_id)
        batch.status = QaSplitBatchStatus.FAILED.value
        batch.result_payload = QaSplitBatchFailurePayload(
            retryable=retryable
        ).model_dump()
        batch.result_hash = None
        batch.error_code = code[:120]
        batch.error_message = message.strip()[:1000]
        batch.timeout_phase = timeout_phase[:40] if timeout_phase else None
        run = self._require_run(batch.run_id)
        run.status = QaSplitRunStatus.FAILED.value
        run.error_code = batch.error_code
        run.error_message = batch.error_message
        self.session.flush()

    def collect_complete_items(self, run_id: str) -> list["ValidatedQaItem"]:
        run = self._require_run(run_id)
        batches = self._run_batches(run.id)
        if (
            len(batches) != run.batch_count
            or any(batch.status != QaSplitBatchStatus.SUCCESS.value for batch in batches)
        ):
            raise _validation_error(
                QA_SPLIT_RUN_INCOMPLETE,
                "QA Split Run 尚有未完成或失败的 Batch",
            )

        from server.app.services.qa_split_service import ValidatedQaItem

        items: list[ValidatedQaItem] = []
        for batch in batches:
            try:
                payload = QaSplitBatchResultPayload.model_validate(batch.result_payload)
            except Exception as exc:
                raise _validation_error(
                    QA_SPLIT_RUN_PROVENANCE_INVALID,
                    "QA Split Batch 缺少已验证结果",
                ) from exc
            items.extend(
                ValidatedQaItem(
                    question=item.question,
                    answer=item.answer,
                    quote=item.quote,
                    page_no=item.page_no,
                    chunk_index=item.chunk_index,
                )
                for item in payload.items
            )
        return items

    def publish_complete_run(
        self,
        run_id: str,
        *,
        job: ImportJob,
        document: Document,
        chunks: list[DocumentChunk],
    ) -> list["ValidatedQaItem"]:
        run = self._require_run(run_id)
        if run.status == QaSplitRunStatus.COMPLETED.value:
            return self.collect_complete_items(run.id)
        self._assert_publishable(run, job=job, document=document, chunks=chunks)
        items = self.collect_complete_items(run.id)
        self._assert_item_provenance(items, chunks)

        # Publishing is deliberately contained in a savepoint.  QA pair deletion
        # and replacement are never left visible if a provenance/configuration
        # check or a persistence error occurs midway through the operation.
        with self.session.begin_nested():
            self._replace_qa_pairs(job, document, chunks, items)
            self._bind_embedding_generation(job, chunks)
            document.qa_pair_count = len(items)
            document.status = DocumentStatus.EMBEDDING
            document.last_error_code = None
            document.last_error_message = None
            job.status = ImportJobStatus.RUNNING.value
            job.stage = "EMBEDDING"
            job.progress = max(job.progress, 65)
            job.error_code = None
            job.error_message = None
            run.status = QaSplitRunStatus.COMPLETED.value
            run.completed_batch_count = run.batch_count
            run.error_code = None
            run.error_message = None
            self.session.flush()
        return items

    def _run_matches(
        self,
        run: QaSplitRun,
        *,
        model_config: ModelConfig,
        provider: ModelProvider,
        generation_hash: str,
        expected_specs: dict[str, tuple[tuple[int, ...], str, int, int, int]],
    ) -> bool:
        if (
            run.model_config_id != model_config.id
            or run.provider_id != provider.id
            or run.model_name != model_config.model_name
            or run.prompt_version != QA_SPLIT_PROMPT_VERSION
            or run.chunk_generation_hash != generation_hash
        ):
            return False
        actual_specs = {
            batch.batch_index: (
                tuple(sorted(batch.chunk_indexes)),
                batch.input_hash,
                batch.estimated_input_tokens,
                batch.reserved_output_tokens,
                batch.split_depth,
            )
            for batch in self._run_batches(run.id)
        }
        return actual_specs == expected_specs

    def _assert_publishable(
        self,
        run: QaSplitRun,
        *,
        job: ImportJob,
        document: Document,
        chunks: list[DocumentChunk],
    ) -> None:
        if (
            run.job_id != job.id
            or run.document_id != document.id
            or run.tenant_id != job.tenant_id
            or job.document_id != document.id
        ):
            raise _validation_error(
                QA_SPLIT_RUN_PROVENANCE_INVALID,
                "QA Split Run 与当前文档或导入任务不匹配",
            )
        if run.prompt_version != QA_SPLIT_PROMPT_VERSION:
            raise _validation_error(
                QA_SPLIT_RUN_CONFIG_CHANGED,
                "QA Split Prompt 版本已变化",
            )
        if run.chunk_generation_hash != chunk_generation_hash(chunks):
            raise _validation_error(
                QA_SPLIT_RUN_CONFIG_CHANGED,
                "QA Split Chunk generation 已变化",
            )
        model_config, provider = self._resolve_current_model(job.tenant_id)
        if (
            model_config.id != run.model_config_id
            or provider.id != run.provider_id
            or model_config.model_name != run.model_name
        ):
            raise _validation_error(
                QA_SPLIT_RUN_CONFIG_CHANGED,
                "QA Split 模型配置已变化",
            )
        batches = self._run_batches(run.id)
        if len(batches) != run.batch_count:
            raise _validation_error(
                QA_SPLIT_RUN_PROVENANCE_INVALID,
                "QA Split Batch 数量不完整",
            )
        if any(batch.status != QaSplitBatchStatus.SUCCESS.value for batch in batches):
            raise _validation_error(
                QA_SPLIT_RUN_INCOMPLETE,
                "QA Split Run 尚有未完成或失败的 Batch",
            )
        expected_indexes = {chunk.chunk_index for chunk in chunks}
        actual_indexes = {
            index for batch in batches for index in batch.chunk_indexes
        }
        if actual_indexes != expected_indexes:
            raise _validation_error(
                QA_SPLIT_RUN_PROVENANCE_INVALID,
                "QA Split Batch 未完整覆盖当前 Chunk generation",
            )

    def _resolve_current_model(
        self, tenant_id: str
    ) -> tuple[ModelConfig, ModelProvider]:
        if self._default_model_resolver is not None:
            return self._default_model_resolver(tenant_id)
        row = self.session.execute(
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.capability == ModelCapability.QA_SPLIT.value,
                ModelConfig.is_default.is_(True),
                ModelConfig.status == "ACTIVE",
                ModelConfig.deleted_at.is_(None),
                ModelProvider.status == "ACTIVE",
                ModelProvider.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise _validation_error(
                QA_SPLIT_RUN_CONFIG_CHANGED,
                "当前没有可用的 QA Split 模型",
            )
        return row[0], row[1]

    def _assert_item_provenance(
        self, items: list["ValidatedQaItem"], chunks: list[DocumentChunk]
    ) -> None:
        chunk_by_index = {chunk.chunk_index: chunk for chunk in chunks}
        for item in items:
            chunk = chunk_by_index.get(item.chunk_index)
            if chunk is None:
                raise _validation_error(
                    QA_SPLIT_RUN_PROVENANCE_INVALID,
                    "已保存 QA 结果包含未知 Chunk",
                )
            page_start = chunk.page_start or chunk.page_no or 1
            page_end = chunk.page_end or page_start
            if item.page_no < page_start or item.page_no > page_end:
                raise _validation_error(
                    QA_SPLIT_RUN_PROVENANCE_INVALID,
                    "已保存 QA 结果页码不属于当前 Chunk",
                )
            quote = " ".join(item.quote.split())
            source = " ".join((chunk.content or "").split())
            if not quote or quote not in source:
                raise _validation_error(
                    QA_SPLIT_RUN_PROVENANCE_INVALID,
                    "已保存 QA 引用不属于当前 Chunk",
                )

    def _replace_qa_pairs(
        self,
        job: ImportJob,
        document: Document,
        chunks: list[DocumentChunk],
        items: list["ValidatedQaItem"],
    ) -> None:
        if self._replace_qa_pairs_callback is not None:
            self._replace_qa_pairs_callback(job, document, chunks, items)
            return
        chunk_by_index = {chunk.chunk_index: chunk for chunk in chunks}
        self.session.execute(delete(QaPair).where(QaPair.document_id == document.id))
        for pair_index, item in enumerate(items):
            chunk = chunk_by_index[item.chunk_index]
            self.session.add(
                QaPair(
                    tenant_id=job.tenant_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    job_id=job.id,
                    pair_index=pair_index,
                    question=item.question,
                    answer=item.answer,
                    quote=item.quote,
                    page_no=item.page_no,
                    question_embedding=None,
                    search_text="",
                    token_count=len(item.question.split()) + len(item.answer.split()),
                    status="ACTIVE",
                    qa_metadata={"sourceChunkIndex": chunk.chunk_index},
                )
            )

    def _bind_embedding_generation(
        self, job: ImportJob, chunks: list[DocumentChunk]
    ) -> None:
        if self._bind_embedding_generation_callback is not None:
            self._bind_embedding_generation_callback(job, chunks)
            return
        config_hashes = {
            chunk.chunker_config_hash.strip()
            for chunk in chunks
            if isinstance(chunk.chunker_config_hash, str) and chunk.chunker_config_hash.strip()
        }
        if len(config_hashes) != 1:
            raise _validation_error(
                QA_SPLIT_RUN_PROVENANCE_INVALID,
                "QA 来源 Chunk generation 无法唯一确定",
            )
        options = dict(job.options) if isinstance(job.options, dict) else {}
        embedding_options = options.get("embedding")
        options["embedding"] = {
            **(embedding_options if isinstance(embedding_options, dict) else {}),
            "run_config_hash": config_hashes.pop(),
        }
        job.options = options

    def _run_batches(self, run_id: str) -> list[QaSplitBatch]:
        return list(
            self.session.scalars(
                select(QaSplitBatch)
                .where(QaSplitBatch.run_id == run_id)
                .order_by(QaSplitBatch.batch_index)
            ).all()
        )

    def _successful_batch_count(self, run_id: str) -> int:
        return sum(
            batch.status == QaSplitBatchStatus.SUCCESS.value
            for batch in self._run_batches(run_id)
        )

    @staticmethod
    def _failed_batch_retryable(batch: QaSplitBatch) -> bool:
        try:
            payload = QaSplitBatchFailurePayload.model_validate(batch.result_payload)
        except Exception:
            return False
        return payload.retryable

    def _require_batch(self, batch_id: str) -> QaSplitBatch:
        batch = self.session.get(QaSplitBatch, batch_id)
        if batch is None:
            raise ValueError("QA Split Batch does not exist")
        return batch

    def _require_run(self, run_id: str) -> QaSplitRun:
        run = self.session.get(QaSplitRun, run_id)
        if run is None:
            raise ValueError("QA Split Run does not exist")
        return run
