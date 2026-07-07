from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import time

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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingServiceError(Exception):
    code: str
    message: str
    retryable: bool = True


def build_search_text(tokenizer: SearchTextTokenizer, qa_pair: QaPair) -> str:
    """Compose the FTS document for a QA pair. Shared with the backfill
    script (``server.scripts.backfill_search_text``) so index rebuilds use
    the exact composition the embedding path wrote."""
    source = " ".join(
        item
        for item in [qa_pair.question, qa_pair.answer, qa_pair.quote or ""]
        if item
    )
    return tokenizer.to_search_text(source)


class EmbeddingService:
    def __init__(
        self,
        session: Session,
        tokenizer: SearchTextTokenizer | None = None,
        provider_factory: ProviderFactory = build_provider_adapter,
    ) -> None:
        self.session = session
        self.tokenizer = tokenizer or JiebaTokenizer()
        self._build_adapter = provider_factory

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
        self.session.flush()

        try:
            qa_pairs = self._list_qa_pairs(job.tenant_id, document.id)
            if not qa_pairs:
                raise EmbeddingServiceError(
                    "EMBEDDING_NO_QA_PAIRS", "文档没有可向量化的 QA 对"
                )
            model_config, provider = self._default_model(job.tenant_id)
            expected_dimension = int(model_config.embedding_dimension or 1536)
            adapter = self._build_adapter(
                provider.provider_type,
                provider.base_url,
                decrypt_secret(provider.encrypted_api_key),
                {**(provider.config or {}), **(model_config.config or {})},
                model_name=model_config.model_name,
                timeout_ms=model_config.timeout_ms,
            )
            vectors = self._embed_in_batches(
                adapter, [item.question for item in qa_pairs], expected_dimension
            )
            self._validate_vectors(vectors, expected_dimension, len(qa_pairs))

            for qa_pair, vector in zip(qa_pairs, vectors, strict=True):
                qa_pair.question_embedding = vector
                qa_pair.search_text = build_search_text(self.tokenizer, qa_pair)
                qa_pair.token_count = len(qa_pair.search_text.split())
                qa_pair.status = "ACTIVE"

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
            self._mark_failed(job, document, task_run, exc.code, exc.message, exc.retryable)
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
            )
            return job

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

    def _list_qa_pairs(self, tenant_id: str, document_id: str) -> list[QaPair]:
        return list(
            self.session.scalars(
                select(QaPair)
                .where(
                    QaPair.tenant_id == tenant_id,
                    QaPair.document_id == document_id,
                    QaPair.deleted_at.is_(None),
                    QaPair.status.in_(["ACTIVE", "EMBEDDING_FAILED"]),
                )
                .order_by(QaPair.pair_index)
            ).all()
        )

    def _embed_in_batches(
        self, adapter, questions: list[str], expected_dimension: int
    ) -> list[list[float]]:
        """Embed questions in bounded batches, fanned out over a thread pool.

        Large documents cannot be embedded in a single call (provider batch
        limits), so questions are split into ``embedding_batch_size`` chunks.
        Each batch is embedded independently with its own transient-failure
        retries; a batch that keeps failing raises and lets the task layer
        (Celery) retry the whole job.
        """
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
    ) -> None:
        for qa_pair in self._list_qa_pairs(job.tenant_id, document.id):
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
