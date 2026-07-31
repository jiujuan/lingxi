from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import logging
import time
from typing import TypeAlias

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.app.core.config import settings
from server.app.core.secrets import decrypt_secret
import server.app.db.base  # noqa: F401
from server.app.integrations.model_providers.base import ProviderError
from server.app.integrations.model_providers.registry import (
    ProviderFactory,
    build_provider_adapter,
)
from server.app.integrations.tokenizers.base import SearchTextTokenizer
from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer
from server.app.models.document import Document, DocumentStatus
from server.app.models.import_job import ImportJob, ImportJobStatus
from server.app.models.logs import TaskRun
from server.app.models.model_config import ModelCapability, ModelConfig, ModelProvider
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.services._batching import run_ordered
from server.app.services.chunking.tokenizer import (
    LocalTokenCounter,
    TokenCounter,
    TokenizerUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingServiceError(Exception):
    code: str
    message: str
    retryable: bool = True


class EmbeddingTargetType(StrEnum):
    QA = "QA"
    CHUNK = "CHUNK"


QA_EMBEDDING_TEMPLATE_VERSION = "qa-question-v1"
CHUNK_EMBEDDING_TEMPLATE_VERSION = "chunk-document-title-path-type-content-v1"


EmbeddingRecord: TypeAlias = QaPair | DocumentChunk


@dataclass(frozen=True)
class EmbeddingTarget:
    """A fully prepared target for one independently embedded record type."""

    target_type: EmbeddingTargetType
    record: EmbeddingRecord
    input_text: str
    search_text: str
    template_version: str


def _input_text_hash(input_text: str) -> str:
    """Return the SHA256 of the exact text sent to the embedding provider."""
    return hashlib.sha256(input_text.encode("utf-8")).hexdigest()


def _title_path_text(chunk: DocumentChunk | None) -> str:
    if chunk is None or not isinstance(chunk.title_path, list):
        return ""
    return " / ".join(
        value.strip() for value in chunk.title_path if isinstance(value, str) and value.strip()
    )


def build_chunk_embedding_text(document: Document, chunk: DocumentChunk) -> str:
    """Build the version-stable Chunk embedding template from Spec §11.1."""
    fields = (
        ("文档", document.title),
        ("章节", _title_path_text(chunk)),
        ("类型", chunk.block_type),
        ("正文", chunk.content),
    )
    return "\n".join(f"{label}：{value}" for label, value in fields if value)


def build_chunk_search_text(
    tokenizer: SearchTextTokenizer, document: Document, chunk: DocumentChunk
) -> str:
    """Build Chunk FTS text as document title + title path + content."""
    return tokenizer.to_search_text(
        " ".join(
            value
            for value in [document.title, _title_path_text(chunk), chunk.content]
            if value
        )
    )


def build_search_text(
    tokenizer: SearchTextTokenizer,
    qa_pair: QaPair,
    document: Document | None = None,
    source_chunk: DocumentChunk | None = None,
) -> str:
    """Compose QA FTS text with document and source-section provenance.

    ``document`` and ``source_chunk`` are optional only for compatibility with
    callers that have not loaded the relations yet. The embedding and backfill
    paths always supply them so new search text includes the Spec §11.2 fields.
    """
    source = " ".join(
        item
        for item in [
            document.title if document is not None else "",
            _title_path_text(source_chunk),
            qa_pair.question,
            qa_pair.answer,
            qa_pair.quote or "",
        ]
        if item
    )
    return tokenizer.to_search_text(source)


class EmbeddingService:
    def __init__(
        self,
        session: Session,
        tokenizer: SearchTextTokenizer | None = None,
        provider_factory: ProviderFactory = build_provider_adapter,
        *,
        chunk_indexing_enabled: bool = False,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self.session = session
        self.tokenizer = tokenizer or JiebaTokenizer()
        self._build_adapter = provider_factory
        # Task 16 owns Settings wiring. This is an explicit dependency so the
        # embedding service never reads feature flags from the environment.
        self.chunk_indexing_enabled = chunk_indexing_enabled
        self._token_counter = token_counter

    def embed_import_job(self, job_id: str) -> ImportJob:
        job = self.session.get(ImportJob, job_id)
        if job is None:
            raise ValueError("Import job does not exist")
        document = self.session.get(Document, job.document_id)
        if document is None:
            raise ValueError("Import job document does not exist")

        # Idempotency: a duplicate delivery of an already-finished job is a no-op.
        if job.status == ImportJobStatus.COMPLETED.value:
            return job

        task_run = TaskRun(
            tenant_id=job.tenant_id,
            task_type="embed_qa_pairs_task",
            queue_name="embedding",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="EMBEDDING",
            status="RUNNING",
            error=None,
            request_id=None,
        )
        self.session.add(task_run)
        self.session.flush()

        job.status = ImportJobStatus.RUNNING.value
        job.stage = "EMBEDDING"
        job.progress = max(job.progress, 75)
        document.status = DocumentStatus.EMBEDDING
        # Provider calls can take seconds. Persist the RUNNING transition now so
        # PostgreSQL does not retain a Document write lock while waiting on the
        # external provider. The final commit below takes the same row lock as
        # document_parse_service only after vectors are available.
        self.session.commit()

        qa_targets: list[EmbeddingTarget] = []
        try:
            model_config, provider = self._default_model(job.tenant_id)
            expected_dimension = int(
                model_config.embedding_dimension or settings.embedding_vector_dimension
            )
            model_key = self._model_key(model_config, provider, expected_dimension)
            run_config_hash = None
            if self.chunk_indexing_enabled:
                run_config_hash = self._bound_run_config_hash(job)
                self._assert_bound_active_collection(document.id, run_config_hash)
            qa_pairs = self._list_qa_pairs(
                job.tenant_id, document.id, run_config_hash=run_config_hash
            )
            if not qa_pairs:
                raise EmbeddingServiceError(
                    "EMBEDDING_NO_QA_PAIRS", "文档没有可向量化的 QA 对"
                )
            qa_targets = self._build_qa_targets(document, qa_pairs, model_key)
            chunk_targets = (
                self._build_chunk_targets(document, model_key, run_config_hash)
                if self.chunk_indexing_enabled
                else []
            )
            self._validate_target_inputs(
                [*qa_targets, *chunk_targets], model_config.max_tokens
            )

            adapter = self._build_adapter(
                provider.provider_type,
                provider.base_url,
                decrypt_secret(provider.encrypted_api_key),
                {**(provider.config or {}), **(model_config.config or {})},
                model_name=model_config.model_name,
                timeout_ms=model_config.timeout_ms,
            )
            # Provider calls intentionally remain type-isolated. We do not
            # mutate either target group until both groups have passed all
            # count/dimension validation, preventing partial vector writes.
            qa_vectors = self._embed_targets(adapter, qa_targets, expected_dimension)
            chunk_vectors = self._embed_targets(
                adapter, chunk_targets, expected_dimension
            )
            # Serialize final collection validation and persistence with the
            # parse pipeline. PostgreSQL holds this Document row lock through
            # both target groups, terminal statuses, and commit; provider calls
            # above intentionally run before lock acquisition.
            document = self._lock_document_for_embedding_commit(document.id)
            if run_config_hash is not None:
                # Re-read after the lock. A parse/rechunk that committed while
                # the provider ran must fail before either target group writes.
                self._assert_bound_active_collection(document.id, run_config_hash)
            self._persist_targets(
                qa_targets, qa_vectors, model_config, provider, expected_dimension, model_key
            )
            self._persist_targets(
                chunk_targets,
                chunk_vectors,
                model_config,
                provider,
                expected_dimension,
                model_key,
            )

            document.qa_pair_count = len(qa_pairs)
            document.chunk_count = self._count_chunks(document.id)
            document.status = DocumentStatus.READY
            document.last_error_code = None
            document.last_error_message = None
            job.status = ImportJobStatus.COMPLETED.value
            job.stage = "COMPLETED"
            job.progress = 100
            job.error_code = None
            job.error_message = None
            task_run.status = "SUCCESS"
            task_run.error = None
            self.session.commit()
            return job
        except EmbeddingServiceError as exc:
            self._mark_failed(
                job,
                document,
                task_run,
                exc.code,
                exc.message,
                exc.retryable,
                qa_targets,
            )
            return job
        except Exception:
            logger.exception("Unexpected error embedding import job %s", job.id)
            self._mark_failed(
                job,
                document,
                task_run,
                "EMBEDDING_INTERNAL_ERROR",
                "Embedding 处理失败",
                True,
                qa_targets,
            )
            return job

    def _lock_document_for_embedding_commit(self, document_id: str) -> Document:
        """Acquire the parse-compatible Document lock for final persistence."""
        document = self.session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is None:
            raise ValueError("Import job document does not exist")
        return document

    def _default_model(self, tenant_id: str) -> tuple[ModelConfig, ModelProvider]:
        statement = (
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.capability == ModelCapability.EMBEDDING.value,
                ModelConfig.is_default.is_(True),
                ModelConfig.status == "ACTIVE",
                ModelConfig.deleted_at.is_(None),
                ModelProvider.status == "ACTIVE",
                ModelProvider.deleted_at.is_(None),
            )
        )
        row = self.session.execute(statement).first()
        if row is None:
            raise EmbeddingServiceError("EMBEDDING_MODEL_MISSING", "未配置默认 Embedding 模型")
        return row[0], row[1]

    def _list_qa_pairs(
        self,
        tenant_id: str,
        document_id: str,
        *,
        run_config_hash: str | None = None,
    ) -> list[QaPair]:
        statement = select(QaPair).where(
            QaPair.tenant_id == tenant_id,
            QaPair.document_id == document_id,
            QaPair.deleted_at.is_(None),
            QaPair.status.in_(["ACTIVE", "EMBEDDING_FAILED"]),
        )
        if run_config_hash is not None:
            # Adaptive runs are generation-bound: a QA pair is current only
            # while the source Child in that immutable run remains current.
            statement = statement.join(
                DocumentChunk, DocumentChunk.id == QaPair.chunk_id
            ).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.deleted_at.is_(None),
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "CHILD",
                DocumentChunk.chunker_config_hash == run_config_hash,
            )
        return list(self.session.scalars(statement.order_by(QaPair.pair_index)).all())

    def _bound_run_config_hash(self, job: ImportJob) -> str:
        options = job.options if isinstance(job.options, dict) else {}
        embedding_options = options.get("embedding")
        run_config_hash = (
            embedding_options.get("run_config_hash")
            if isinstance(embedding_options, dict)
            else None
        )
        if not isinstance(run_config_hash, str) or not run_config_hash.strip():
            raise EmbeddingServiceError(
                "EMBEDDING_RUN_CONFIG_MISSING",
                "Adaptive Embedding 缺少 QA 阶段绑定的 chunk generation",
            )
        return run_config_hash

    def _assert_bound_active_collection(
        self, document_id: str, run_config_hash: str
    ) -> None:
        active_chunks = list(
            self.session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.status == "ACTIVE",
                )
            ).all()
        )
        has_bound_child = any(
            chunk.chunk_level == "CHILD"
            and chunk.chunker_config_hash == run_config_hash
            for chunk in active_chunks
        )
        if (
            not active_chunks
            or not has_bound_child
            or any(chunk.chunker_config_hash != run_config_hash for chunk in active_chunks)
        ):
            raise EmbeddingServiceError(
                "EMBEDDING_RUN_CONFIG_CHANGED",
                "Embedding 期间 Chunk generation 已切换，请重试",
            )

    def _build_qa_targets(
        self, document: Document, qa_pairs: list[QaPair], model_key: str
    ) -> list[EmbeddingTarget]:
        chunks_by_id = {
            chunk.id: chunk
            for chunk in self.session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.deleted_at.is_(None),
                )
            ).all()
        }
        targets: list[EmbeddingTarget] = []
        for qa_pair in qa_pairs:
            source_chunk = chunks_by_id.get(qa_pair.chunk_id)
            search_text = build_search_text(
                self.tokenizer, qa_pair, document, source_chunk
            )
            target = EmbeddingTarget(
                EmbeddingTargetType.QA,
                qa_pair,
                qa_pair.question,
                search_text,
                QA_EMBEDDING_TEMPLATE_VERSION,
            )
            if self._is_current_embedding(target, model_key) and qa_pair.search_text == search_text:
                continue
            targets.append(target)
        return targets

    def _build_chunk_targets(
        self, document: Document, model_key: str, run_config_hash: str | None
    ) -> list[EmbeddingTarget]:
        if run_config_hash is None:
            raise AssertionError("Adaptive Chunk targets require a bound generation")
        targets: list[EmbeddingTarget] = []
        for chunk in self._list_current_active_children(document.id, run_config_hash):
            input_text = build_chunk_embedding_text(document, chunk)
            search_text = build_chunk_search_text(self.tokenizer, document, chunk)
            target = EmbeddingTarget(
                EmbeddingTargetType.CHUNK,
                chunk,
                input_text,
                search_text,
                CHUNK_EMBEDDING_TEMPLATE_VERSION,
            )
            if self._is_current_embedding(target, model_key) and chunk.search_text == search_text:
                continue
            targets.append(target)
        return targets

    def _list_current_active_children(
        self, document_id: str, run_config_hash: str
    ) -> list[DocumentChunk]:
        """Return only active Child chunks from the QA-bound generation."""
        return list(
            self.session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.status == "ACTIVE",
                    DocumentChunk.chunk_level == "CHILD",
                    DocumentChunk.chunker_config_hash == run_config_hash,
                )
                .order_by(DocumentChunk.chunk_index)
            ).all()
        )

    def _embed_targets(
        self, adapter, targets: list[EmbeddingTarget], expected_dimension: int
    ) -> list[list[float]]:
        if not targets:
            return []
        return self._embed_in_batches(
            adapter, [target.input_text for target in targets], expected_dimension
        )

    def _validate_target_inputs(
        self, targets: list[EmbeddingTarget], max_tokens: int | None
    ) -> None:
        if max_tokens is None:
            return
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise EmbeddingServiceError(
                "EMBEDDING_INPUT_LIMIT_INVALID", "Embedding 模型输入 token 上限无效", False
            )
        counter = self._token_counter
        if counter is None:
            try:
                counter = LocalTokenCounter()
            except TokenizerUnavailableError as exc:
                raise EmbeddingServiceError(exc.code, exc.message, exc.retryable) from exc
        for target in targets:
            if counter.count(target.input_text) > max_tokens:
                raise EmbeddingServiceError(
                    "EMBEDDING_INPUT_TOO_LONG",
                    f"{target.target_type.value} embedding 输入超过模型 token 上限",
                    False,
                )

    def _persist_targets(
        self,
        targets: list[EmbeddingTarget],
        vectors: list[list[float]],
        model_config: ModelConfig,
        provider: ModelProvider,
        dimension: int,
        model_key: str,
    ) -> None:
        self._validate_vectors(vectors, dimension, len(targets))
        for target, vector in zip(targets, vectors, strict=True):
            metadata = self._record_metadata(target.record)
            metadata["embedding"] = {
                "targetType": target.target_type.value,
                "embeddingTemplateVersion": target.template_version,
                "inputTextHash": _input_text_hash(target.input_text),
                "modelKey": model_key,
                "modelConfigId": model_config.id,
                "providerId": provider.id,
                "modelName": model_config.model_name,
                "dimension": dimension,
            }
            if target.target_type == EmbeddingTargetType.QA:
                qa_pair = target.record
                assert isinstance(qa_pair, QaPair)
                qa_pair.question_embedding = vector
                qa_pair.search_text = target.search_text
                qa_pair.token_count = len(target.search_text.split())
                qa_pair.status = "ACTIVE"
                qa_pair.qa_metadata = metadata
            else:
                chunk = target.record
                assert isinstance(chunk, DocumentChunk)
                chunk.embedding = vector
                chunk.search_text = target.search_text
                chunk.chunk_metadata = metadata

    def _model_key(
        self, model_config: ModelConfig, provider: ModelProvider, dimension: int
    ) -> str:
        payload = {
            "modelConfigId": model_config.id,
            "modelConfigUpdatedAt": model_config.updated_at.isoformat()
            if model_config.updated_at
            else None,
            "modelName": model_config.model_name,
            "modelConfig": model_config.config or {},
            "providerId": provider.id,
            "providerUpdatedAt": provider.updated_at.isoformat() if provider.updated_at else None,
            "providerConfig": provider.config or {},
            "dimension": dimension,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _record_metadata(record: EmbeddingRecord) -> dict:
        source = record.qa_metadata if isinstance(record, QaPair) else record.chunk_metadata
        return dict(source) if isinstance(source, dict) else {}

    def _is_current_embedding(self, target: EmbeddingTarget, model_key: str) -> bool:
        record = target.record
        vector = record.question_embedding if isinstance(record, QaPair) else record.embedding
        metadata = self._record_metadata(record)
        embedding_metadata = metadata.get("embedding")
        return bool(
            vector is not None
            and isinstance(embedding_metadata, dict)
            and embedding_metadata.get("targetType") == target.target_type.value
            and embedding_metadata.get("embeddingTemplateVersion") == target.template_version
            and embedding_metadata.get("inputTextHash") == _input_text_hash(target.input_text)
            and embedding_metadata.get("modelKey") == model_key
        )

    def _embed_in_batches(
        self, adapter, questions: list[str], expected_dimension: int
    ) -> list[list[float]]:
        """Embed inputs in bounded, ordered batches with retry per provider call."""
        batch_size = max(1, settings.embedding_batch_size)
        batches = [
            questions[start : start + batch_size]
            for start in range(0, len(questions), batch_size)
        ]
        batch_vectors = run_ordered(
            batches,
            lambda batch: self._embed_batch_with_retry(
                adapter, batch, expected_dimension
            ),
            settings.embedding_max_concurrency,
        )
        return [vector for batch in batch_vectors for vector in batch]

    def _embed_batch_with_retry(
        self, adapter, batch: list[str], expected_dimension: int
    ) -> list[list[float]]:
        max_retries = max(0, settings.embedding_batch_max_retries)
        attempt = 0
        while True:
            try:
                vectors = adapter.embed_texts(batch)
                self._validate_vectors(vectors, expected_dimension, len(batch))
                return vectors
            except ProviderError as exc:
                if exc.retryable and attempt < max_retries:
                    attempt += 1
                    time.sleep(min(5.0, 0.5 * (2**attempt)))
                    logger.warning(
                        "embedding batch retry %d/%d: %s",
                        attempt,
                        max_retries,
                        exc.code,
                    )
                    continue
                raise EmbeddingServiceError(
                    exc.code, exc.message, retryable=exc.retryable
                ) from exc

    def _validate_vectors(
        self, vectors: list[list[float]], expected_dimension: int, expected_count: int
    ) -> None:
        if len(vectors) != expected_count:
            raise EmbeddingServiceError(
                "EMBEDDING_RESULT_COUNT_MISMATCH", "Embedding 返回数量不匹配"
            )
        for vector in vectors:
            if len(vector) != expected_dimension:
                raise EmbeddingServiceError(
                    "EMBEDDING_DIMENSION_MISMATCH",
                    "Embedding 向量维度与模型配置不一致",
                )

    def _count_chunks(self, document_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.status == "ACTIVE",
                    DocumentChunk.chunk_level == "CHILD",
                )
            )
            or 0
        )

    def _mark_failed(
        self,
        job: ImportJob,
        document: Document,
        task_run: TaskRun,
        code: str,
        message: str,
        retryable: bool,
        qa_targets: list[EmbeddingTarget],
    ) -> None:
        # Preserve already-current QA targets if an independent Chunk group
        # fails. Only QA targets participating in this attempt become retryable.
        for target in qa_targets:
            qa_pair = target.record
            assert isinstance(qa_pair, QaPair)
            qa_pair.status = "EMBEDDING_FAILED"
        document.status = DocumentStatus.FAILED
        document.last_error_code = code
        document.last_error_message = message
        job.status = ImportJobStatus.FAILED.value
        job.stage = "EMBEDDING"
        job.error_code = code
        job.error_message = message
        task_run.status = "FAILED"
        task_run.error = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "failedAt": datetime.now(UTC).isoformat(),
        }
        self.session.commit()
